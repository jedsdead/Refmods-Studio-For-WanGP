"""
Refmods For Wan GP -- Wan2GP plugin (formerly MiniMax H3 RefMods).

No-training "reference mods" for MiniMax H3 Ref2VA: compress an image/video
reference into a small .safetensors file once (Extract tab), then reuse it at
any strength in later generations without re-encoding it every time (Generate
tab), optionally blending several mods together. Ported from the ComfyUI
custom-node pack ComfyUI-MiniMaxH3Mod (MIT, (c) 2026 Luisa/luisacaotica) --
see README.md for how the mechanism works and its current limitations.

Design note on why this plugin has its own "Generate" section instead of
hooking the main Media Generator form: the per-model "Custom Settings" fields
Wan2GP auto-builds from a model's definition (the channel this plugin uses to
carry a RefMod selection all the way to the pipeline) are not given a stable
elem_id, so a plugin cannot bind its own rich widgets to them. Submitting a
self-contained task through the API session (the same mechanism the bundled
Sample Plugin demonstrates) sidesteps that limitation entirely and is the
supported, documented way for a plugin to drive a full generation.

The Generate panel below covers the fields most people tune day to day
(prompt, resolution, frame count, steps, flow shift, sampler, reference-image
budget, LoRAs, step-skipping accelerators, sliding window, and the sol-attn
sparsity dial) plus the RefMods themselves. Anything not exposed here still
gets a valid value: "Sync from the main form" copies every setting from
Wan2GP's own Media Generator tab (for the same model) as the starting point,
and `api_session.merge_settings_with_defaults(...)` fills in the rest from
that model's own factory defaults before submission -- so no field is ever
missing, even ones this panel doesn't have a dedicated widget for.
"""

from __future__ import annotations

import functools
import json
import os

import gradio as gr

from shared.utils.plugins import WAN2GPPlugin

from . import core, encframes, storage
from . import flux, flux_ui   # fork.31
from . import outputinfo   # fork.34
import time
from .patches import (EXTRACT_WRAPPER_KEY, SETTING_GENERATE, STASH_KEY, install_patches,
                      install_get_model_settings_patch, install_prepare_inputs_dict_patch,
                      is_minimax_h3_refmod_capable)


PlugIn_Name = "Refmods For Wan GP"
PlugIn_Tab = "Refmods"   # fork.36: the tab's label
PlugIn_Id = "H3RefMods"

# Row counts are just how many picker slots the UI draws -- they are NOT the
# model's limits. Wan2GP's own "at most 12 references: 9 images, 2 videos, 2
# audio" check is bypassed for RefMods (see patches.py's _place_refmod_ref):
# those numbers are a UI/product cap, not an architectural one. MiniMax H3
# uses RoPE positions computed at runtime, an unbounded reference loop, and
# free-running <Picture N> labels, and the ComfyUI community has verified 15
# image references working correctly. Raise these if you want more slots --
# the live counter below will keep telling you what you're actually sending.
IMAGE_ROWS = 20
VIDEO_ROWS = 6
AUDIO_ROWS = 4
NONE_CHOICE = "(none)"

# How video-kind mods behave on sliding windows after the first one. Image and
# audio mods always go to every window (that is what WanGP does with its own
# live references: src_ref_images / audio_guide are set once, before the window
# loop, and passed to every generate() call), so only the video case is a
# choice. The values are what travels in the serialized state; see
# patches.WINDOW_MODE_* for what each one does at injection time.
WINDOW_MODE_CHOICES = [
    ("First frame as a still (recommended)", "still"),
    ("Whole clip, like a live reference video", "full"),
    ("Not at all (first window only)", "first"),
]
WINDOW_MODE_DEFAULT = "still"

# Mirrors models/minimax_h3/minimax_h3_handler.py -- kept as a local constant
# so this UI doesn't need a live import of Wan2GP internals just to draw a
# dropdown. If a future Wan2GP version changes these, only this dropdown's
# labels/values would need updating, nothing else in the plugin depends on it.
FIRST_BLOCK_CACHE_STRENGTHS = [
    ("Low (0.06)", 0.06),
    ("Balanced (0.08, upstream default)", 0.08),
    ("High (0.10)", 0.10),
    ("Very High (0.12)", 0.12),
    ("Maximum (0.14)", 0.14),
]
STEPS_SKIPPING_CHOICES = [
    ("None", ""),
    ("Spectrum Feature Forecasting", "spectrum"),
    ("First Block Cache", "first_block"),
]


def _diagnose(api_session, model_type, patch_error):
    """Confirm the plugin's monkeypatches are actually wired up for the
    selected model, *before* running an extraction/generation -- surfaces the
    exact failure mode that made the original bug so hard to notice (nothing
    ever raised an error; generate() just quietly ran a normal render)."""
    if not model_type:
        return "⚠️ Pick a model above first."
    lines = []
    if patch_error:
        lines.append(f"❌ Pipeline patch failed at plugin startup: {patch_error}")
    else:
        lines.append("✅ Pipeline patched (extraction / injection hooks are active).")
    try:
        model_def = api_session.get_model_def(model_type) or {}
        declared_ids = {s.get("id") for s in (model_def.get("custom_settings") or []) if isinstance(s, dict)}
        missing = [sid for sid in (SETTING_GENERATE,) if sid not in declared_ids]
        if missing:
            lines.append(f"❌ This model does NOT declare {missing} under custom_settings -- RefMods will "
                         f"silently no-op for it (a real generation will run instead of an extraction, or "
                         f"without the mods applied). Check the terminal log for '[Refmods]' lines at "
                         f"Wan2GP startup -- the model-definition patch did not take effect for "
                         f"'{model_type}'.")
        else:
            lines.append(f"✅ '{model_type}' declares both custom_settings ids -- RefMod payloads will "
                         f"survive task submission (with the check below, from the panel under the prompt box).")
    except Exception as e:
        lines.append(f"⚠️ Could not read the model definition for '{model_type}': {e!r}")
    try:
        from . import patches
        if getattr(patches.install_prepare_inputs_dict_patch, patches._PREPARE_INPUTS_PATCH_MARKER, False):
            lines.append("✅ Inline panel hook active (prepare_inputs_dict patched) -- RefMods selected "
                         "in the 'Refmods: MiniMax H3' accordion on the Media Generator page will "
                         "apply to that page's own Generate button.")
        else:
            lines.append("❌ Inline panel hook NOT active -- the inline accordion on the Media Generator "
                         "page will be visible but selections made there will have no effect. Check the terminal "
                         "log for a '[Refmods] prepare_inputs_dict' line explaining why.")
    except Exception as e:
        lines.append(f"⚠️ Could not check the inline panel hook status: {e!r}")
    return "\n".join(lines)


ALL_FOLDERS_CHOICE = "(all folders)"
ROOT_FOLDER_CHOICE = "(main folder only)"


def _folder_choices():
    """Choices for the folder picker above the mod rows: browse everything,
    just the root, or any one subfolder (recursively discovered, shown as
    "characters/voices"-style relative paths). Picking "(all folders)" is
    how you get back to seeing every mod again after narrowing down."""
    return [ALL_FOLDERS_CHOICE, ROOT_FOLDER_CHOICE] + storage.list_mod_folders()


ARMED_PACKS_KEY = "_refmods_packs"   # session state: the packs armed in the panel, for the builder


def _armed_packs(state) -> list:
    packs = (state or {}).get(ARMED_PACKS_KEY) if isinstance(state, dict) else None
    return [dict(p) for p in packs if isinstance(p, dict)] if isinstance(packs, list) else []


def _armed_row_indexes(row_vals, n_rows) -> list:
    """Which picker rows are armed, in order -- the same rule _rows_payload
    uses, so a row lines up with its entry in the payload (fork.48)."""
    armed = []
    for index in range(n_rows):
        name = row_vals[index * ROW_WIDTH]
        try:
            strength = float(row_vals[index * ROW_WIDTH + 1])
        except (TypeError, ValueError):
            continue
        if name and name != NONE_CHOICE and strength > 0:
            armed.append(index)
    return armed


def _mirror_for_other_apps(payload, shared: bool, keywords=()) -> None:
    """fork.47: keep the panel's selection where the pipeline can find it for
    a generation that brings none -- Showrunner shots, Deepy, API tasks. The
    whole payload, so every option the panel sets travels with it. Unticking
    leaves the copy in place but switched off, so ticking again restores it."""
    try:
        saved = storage.read_auto_arm() or {}
        if shared:
            rows = payload.get("rows") or []
            if not rows:
                return   # an empty panel never wipes what is saved
            kept = [{**row, **({"when": str(word).strip()} if str(word or "").strip() else {})}
                    for row, word in zip(rows, list(keywords) + [""] * len(rows))]
            saved.update({"on": True, "state": {**payload, "rows": kept}})
            saved.pop("when", None)   # fork.48: keywords are per mod now
        elif not saved.get("on"):
            return
        else:
            saved["on"] = False
        storage.write_auto_arm(saved)
    except Exception as e:
        print(f"[Refmods] could not save the mods for other apps ({e!r})")


def _autoarm_summary(config: dict) -> str:
    """What other apps would get right now, in words."""
    state = config.get("state") if isinstance(config, dict) else None
    rows = (state or {}).get("rows") or []
    if not rows:
        return ("*Nothing saved yet.* Pick mods in the panel on the Media Generator page and tick "
                "*Also use these for Showrunner, Deepy and API tasks*.")
    parts = []
    for row in rows:
        bits = [f"×{float(row.get('strength', 1.0)):.2f}"]
        if row.get("send_as") == "sheet":
            bits.append("contact sheet")
        elif row.get("as_video"):
            bits.append("as one video")
        if int(row.get("copies") or 1) > 1:
            bits.append(f"{int(row['copies'])} copies")
        if row.get("label"):
            bits.append(f"<Picture {int(row['label'])}>")
        if row.get("use_audio") is False:
            bits.append("no soundtrack")
        if str(row.get("when") or "").strip():
            bits.append(f"only when the prompt mentions *{row['when']}*")
        parts.append(f"**{row.get('mod')}** ({', '.join(bits)})")
    options = []
    if state.get("fit_to_output"):
        options.append("fit to output")
    if state.get("phase1_mods") == "fit":
        options.append("phase 1: fit")
    if state.get("phase2_mods") in ("tile", "off"):
        options.append("phase 2: " + ("fit to tile" if state["phase2_mods"] == "tile" else "off"))
    if state.get("shrink_method") == "fast":
        options.append("shrink: fast")
    lines = [("**On.** " if config.get("on") else "**Off.** ") + "; ".join(parts)]
    if options:
        lines.append("Options: " + " · ".join(options) + ".")
    if config.get("when"):
        lines.append(f"Only when the prompt mentions *{config['when']}*.")
    return "  \n".join(lines)


def _mod_choices(kind=None, folder=ALL_FOLDERS_CHOICE):
    """[(none), name, name, ...], optionally restricted to mods of a given
    "image"/"video"/"audio" kind so a slot can only ever offer mods that
    fit it, and to a chosen folder. Names are folder-relative paths
    ("characters/tanya") so they stay unambiguous across subfolders and
    remain directly usable with storage.load_refmod()."""
    if folder == ROOT_FOLDER_CHOICE:
        list_folder, recursive = None, False
    elif not folder or folder == ALL_FOLDERS_CHOICE:
        list_folder, recursive = None, True
    else:
        list_folder, recursive = folder, True
    if kind in ("image", "video", "audio"):
        names = storage.list_refmods_by_kind(kind, folder=list_folder, recursive=recursive)
    else:
        names = storage.list_refmods(folder=list_folder, recursive=recursive)
    return [NONE_CHOICE] + names


def _refresh_mod_dropdown_updates(folder=ALL_FOLDERS_CHOICE, *current_values):
    """gr.update(...) for the folder picker followed by every mod-picker
    dropdown built by _build_mod_picker_rows, in the same
    image-then-video-then-audio order.

    ``current_values`` are those dropdowns' *current* selections, in the
    same order. Each one is kept selected and force-included in its own
    choices even when it lives outside the folder now being browsed --
    otherwise narrowing to a folder would silently drop selections made
    from other folders (and Gradio would then reject the stale value with
    "Value: x is not in the list of choices"). That's what makes it
    possible to browse folder by folder and still combine mods from
    several different folders in one generation."""
    def row_update(kind, index):
        choices = _mod_choices(kind, folder)
        current = current_values[index] if index < len(current_values) else None
        if current and current != NONE_CHOICE and current not in choices:
            choices = choices + [current]
        return gr.update(choices=choices, value=current if current else NONE_CHOICE)

    updates = [gr.update(choices=_folder_choices(), value=folder)]
    i = 0
    for _ in range(IMAGE_ROWS):
        updates.append(row_update("image", i)); i += 1
    for _ in range(VIDEO_ROWS):
        updates.append(row_update("video", i)); i += 1
    for _ in range(AUDIO_ROWS):
        updates.append(row_update("audio", i)); i += 1
    return updates


FPS_ASSUMED_FOR_DURATION_ESTIMATE = 24  # MiniMax H3's own default fps -- only used to turn a
                                        # video-kind mod's latent frame count into an estimated
                                        # seconds figure for the counter below; the real cap
                                        # generate() enforces is duration-based (<=15s), not a
                                        # frame count, and uses whatever fps the render actually
                                        # runs at.

MAX_LATENT_FRAMES = 90  # the highest "latent frames" value that still stays under MiniMax H3's
                        # native 15s reference cap once the video VAE's causal 4:1 temporal
                        # compression is accounted for -- see latent_frames_to_seconds() below;
                        # 91 already estimates to just over 15s.


AUDIO_LATENTS_PER_SECOND = 40  # MiniMax H3's own audio VAE: encoder downsamples by 800x at
                               # 32kHz = 40 latents/s exactly (models/minimax_h3/components/
                               # audio_autoencoder.py's own docstring) -- unlike the video
                               # estimate below, this is an exact, fps-independent rate, not
                               # an approximation.


def _source_file_count(meta, which):
    """How many source files of a given kind ("img" / "vid") went into a
    mod, read from the "{n} img, {m} vid" tag every extraction writes.
    Falls back to 1 when the tag is missing or unparseable (mods from
    older versions, or hand-made ones), since a mod always came from at
    least one file."""
    for tag in (meta.get("tags") or []):
        counts = core.parse_source_counts(tag)
        if counts is not None:
            return counts[0] if which == "img" else counts[1]
    return 1


# Fork panel. Values per picker row: mod, strength, "Send as one video",
# "Include audio", prompt label, soundtrack's prompt label.
ROW_WIDTH = 6
# Panel-wide controls after the mod rows: picture mode, N, video mode, N,
# fit to output, mods in phase 2, shrink method, video mods on sliding windows,
# mods in phase 1 (fork.30, last so older saved orders still line up).
STACK_CONTROLS = 9

# Label dropdowns (fork.27): how far each one counts.
LABEL_MAX = {"image": 20, "video": 9, "audio": 9}
LABEL_WORDS = {"image": "Picture", "video": "Video", "audio": "Audio"}
AUTO_LABEL = "auto"
PHASE2_MODS_UI = [("Full", "full"), ("Fit to tile", "tile"), ("Off", "off")]
PHASE1_MODS_UI = [("Fit to phase 1", "fit"), ("Full size", "full")]   # fork.30; Fit is the default again since fork.49
SHRINK_METHOD_UI = [("Re-encode (best quality)", "reencode"), ("Fast (resize the stored mod)", "fast")]


def _label_choices(kind):
    """Choices for a prompt-label dropdown: Auto, then <Picture 1>, <Picture 2>..."""
    return [("Auto", AUTO_LABEL)] + [(f"<{LABEL_WORDS[kind]} {n}>", n)
                                      for n in range(1, LABEL_MAX[kind] + 1)]


# fork.34: values a panel restore is putting into a row, so the row's own
# change handlers (which start a newly picked mod fresh) keep them.
_RESTORE_PENDING = {}
_RESTORE_SECONDS = 15.0


def _pending_row(key, name):
    item = _RESTORE_PENDING.get(key)
    if not item or time.time() - item[0] > _RESTORE_SECONDS or item[1].get("mod") != name:
        return None
    return item[1]


def _row_restore_updates(row, kind):
    """The six row widgets set to a saved row (see _rows_payload)."""
    name = row["mod"]
    meta = _row_meta(name, 1.0)
    multi = (kind == "image" and bool(meta) and _is_picture_mod(meta)
             and int(meta.get("latent_t", 1) or 1) > 1)
    has_audio = bool(meta) and meta.get("kind") != "audio" and bool(meta.get("has_audio"))
    send_as = (("sheet" if row.get("send_as") == "sheet" else "video" if row.get("as_video") else "pictures")
               if multi else "pictures")
    as_video = send_as == "video"
    use_audio = bool(row.get("use_audio", True))
    choices = _mod_choices(kind)
    return [gr.update(choices=choices if name in choices else choices + [name], value=name),
            gr.update(value=float(row.get("strength", 1.0) or 0.0)),
            gr.update(visible=multi, value=send_as),
            gr.update(visible=has_audio, value=use_audio),
            gr.update(visible=True, choices=_label_choices("video" if as_video else kind),
                      value=_label_number(row.get("label")) or AUTO_LABEL),
            gr.update(visible=has_audio and use_audio, value=_label_number(row.get("audio_label")) or AUTO_LABEL)]


def _row_boxes_update(name, kind="image", key=None):
    pending = _pending_row(key, name) if key is not None else None
    if pending is not None:
        return tuple(_row_restore_updates(pending, kind)[2:])
    """The per-row options after a row's mod changes, starting fresh for the
    newly picked mod (nothing chosen for the previous mod carries over).

    "Send as one video" (image rows only) shows only while the row holds a
    mod made from several pictures, unticked. "Include audio" (image and
    video rows) shows only while the mod carries a soundtrack, ticked, and
    with it the soundtrack's own label dropdown. The label dropdown shows
    once a mod is picked."""
    meta = _row_meta(name, 1.0)
    multi = (kind == "image" and bool(meta) and _is_picture_mod(meta)
             and int(meta.get("latent_t", 1) or 1) > 1)
    has_audio = bool(meta) and meta.get("kind") != "audio" and bool(meta.get("has_audio"))
    return (gr.update(visible=multi, value="pictures"), gr.update(visible=has_audio, value=True),
            gr.update(visible=bool(meta), choices=_label_choices(kind), value=AUTO_LABEL),
            gr.update(visible=has_audio, value=AUTO_LABEL))


def _panel_restore_updates(raw, keep_controls=False, source="the loaded settings"):
    """fork.34: the inline panel refilled from a loaded file's selection --
    status, folder picker, every row widget, the panel controls, row
    visibility and the per-kind shown counts (see restore_panel)."""
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}
    counts = {"image": IMAGE_ROWS, "video": VIDEO_ROWS, "audio": AUDIO_ROWS}
    slots = {k: [] for k in counts}
    missing = []
    for row in payload.get("rows") or []:
        name = row.get("mod")
        meta = storage.read_refmod_meta(storage.mod_path(name)) if name else None
        if meta is None:
            missing.append(str(name))
            continue
        kind = meta.get("kind", "image")
        if kind == "video" and core.is_still_stack(kind, int(meta.get("latent_t", 1) or 1),
                                                   meta.get("tags"), meta.get("source", "")):
            kind = "image"
        kind = kind if kind in counts else "image"
        if len(slots[kind]) < counts[kind]:
            slots[kind].append(row)
        else:
            missing.append(str(name))
    _RESTORE_PENDING.clear()
    now = time.time()
    widgets, ui, shown = [], [], []
    for kind, count in counts.items():
        for i in range(count):
            if i < len(slots[kind]):
                _RESTORE_PENDING[(kind, i)] = (now, slots[kind][i])
                widgets += _row_restore_updates(slots[kind][i], kind)
            else:
                widgets += _cleared_row_updates()
        n = max(1, len(slots[kind]))
        ui += [gr.update(visible=i < n) for i in range(count)]
        shown.append(n)
    controls = [payload.get("stack_pictures", encframes.STACK_ALL),
                payload.get("stack_pictures_n", encframes.STACK_DEFAULT_N),
                payload.get("video_frames", encframes.STACK_UP_TO_N),
                payload.get("video_frames_n", encframes.MAX_CLIP_FRAMES_SHOWN),
                bool(payload.get("fit_to_output", True)), payload.get("phase2_mods", "full"),
                payload.get("shrink_method", "reencode"), payload.get("window_mode", WINDOW_MODE_DEFAULT),
                payload.get("phase1_mods", "fit")]
    restored = sum(len(v) for v in slots.values())
    status = (f"↺ {restored} RefMod(s) restored from {source}." if restored
              else "*No RefMods selected.*")
    if missing:
        status += " Not found here: " + ", ".join(missing) + "."
    # fork.58: a preset is a set of mods, so loading one leaves the panel's
    # own options (sizing, phases, sheets) as they are.
    control_updates = [gr.update() for _ in controls] if keep_controls else [gr.update(value=v) for v in controls]
    return ([status, gr.update(value=ALL_FOLDERS_CHOICE)] + widgets + control_updates + ui + shown)


def _as_video_label_update(on, name, key=None):
    """The label dropdown after "Send as one video" flips: <Video N> or
    <Picture N> choices, back to Auto (unless a restore is setting it)."""
    pending = _pending_row(key, name) if key is not None else None
    value = (_label_number(pending.get("label")) or AUTO_LABEL) if pending else AUTO_LABEL
    return gr.update(choices=_label_choices("video" if _send_as(on) == "video" else "image"), value=value)


def _soundtrack_label_update(include_audio, name):
    """The soundtrack's label dropdown: shown while the row's mod has a
    soundtrack and "Include audio" is ticked."""
    meta = _row_meta(name, 1.0)
    has_audio = bool(meta) and meta.get("kind") != "audio" and bool(meta.get("has_audio"))
    return gr.update(visible=bool(include_audio and has_audio))


def _cleared_row_updates():
    """gr.update()s returning one picker row to empty."""
    return [gr.update(value=NONE_CHOICE), gr.update(value=1.0),
            gr.update(value="pictures", visible=False), gr.update(value=True, visible=False),
            gr.update(value=AUTO_LABEL, visible=False), gr.update(value=AUTO_LABEL, visible=False)]


def _label_number(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 1 else None


# fork.38: how a multi-picture image row is sent (was the "Send as one video" box).
SEND_AS_UI = [("Separate pictures", "pictures"), ("One video", "video"), ("Contact sheet", "sheet")]
SEND_AS_SHORT = [("pictures", "pictures"), ("one video", "video"), ("contact sheet", "sheet")]

# Refmods Studio: the compact panel's columns (heading, scale, min width).
ROW_COLUMNS = (("Mod", 4, 160), ("Strength", 1, 76), ("Label", 1, 110), ("Send as", 1, 130),
               ("Sound", 1, 74), ("Soundtrack", 1, 120))

PANEL_CSS = """<style>
.rs-panel .rs-row { gap: 6px !important; align-items: center; flex-wrap: nowrap !important; }
.rs-panel .rs-row > div { min-width: 0 !important; }
.rs-panel .rs-row .block, .rs-panel .rs-row .form { padding: 0 !important; border: 0 !important;
  background: transparent !important; box-shadow: none !important; }
.rs-panel .rs-row input[type=number] { padding: 4px 6px !important; }
.rs-panel .rs-head { margin-bottom: -4px; }
.rs-panel .rs-heading { font-size: 11px; opacity: .75; }
.rs-panel .rs-packrow { gap: 6px !important; align-items: center; flex-wrap: wrap; }
.rs-panel .rs-hidden { display: none !important; }
.rs-panel input[type=number] { border: 1px solid var(--border-color-primary) !important;
    border-radius: var(--radius-sm); padding: 4px 6px !important; max-width: 76px; }
.rs-panel .rs-packrow > button { flex: none !important; min-width: max-content !important; }
</style>"""


def _send_as(value) -> str:
    """"pictures" / "video" / "sheet" from the row's Send-as value (older
    callers pass the old checkbox's True / False)."""
    if value in ("pictures", "video", "sheet"):
        return value
    return "video" if value is True else "pictures"


def _rows_payload(values):
    """The selection payload's "rows" from the pickers' flat values
    (ROW_WIDTH per row): one entry per row with a mod and strength > 0."""
    rows = []
    for i in range(0, len(values) - ROW_WIDTH + 1, ROW_WIDTH):
        name, strength, as_video, use_audio, label, audio_label = values[i:i + ROW_WIDTH]
        try:
            strength = float(strength)
        except (TypeError, ValueError):
            continue
        if name and name != NONE_CHOICE and strength > 0:
            send_as = _send_as(as_video)
            row = {"mod": name, "strength": strength, "as_video": send_as == "video",
                   "use_audio": bool(use_audio)}
            if send_as == "sheet":
                row["send_as"] = "sheet"
            if _label_number(label):
                row["label"] = _label_number(label)
            if use_audio and _label_number(audio_label):
                row["audio_label"] = _label_number(audio_label)
            rows.append(row)
    return rows


def _normalize_rows(rows):
    """Picker rows as (name, strength, send-as-one-video, include-audio,
    label, soundtrack label); shorter rows (other plugins, older builds) mean
    "not sent as one video", "audio included" and automatic labels."""
    out = []
    for row in rows or []:
        row = tuple(row)
        out.append((row[0], row[1],
                    _send_as(row[2]) if len(row) > 2 else "pictures",
                    bool(row[3]) if len(row) > 3 else True,
                    _label_number(row[4]) if len(row) > 4 else None,
                    _label_number(row[5]) if len(row) > 5 else None))
    return out


def _row_meta(name, strength):
    """Metadata for a picker row that will actually be sent, else None."""
    try:
        strength = float(strength)
    except (TypeError, ValueError):
        return None
    if not name or name == NONE_CHOICE or strength <= 0:
        return None
    try:
        return storage.read_refmod_meta(storage.mod_path(name))
    except Exception:
        return None


def _is_picture_mod(meta):
    kind = meta.get("kind", "image")
    latent_t = max(1, int(meta.get("latent_t", 1)))
    return kind == "image" or core.is_still_stack(kind, latent_t, meta.get("tags"),
                                                    meta.get("source", ""))


def _stack_payload(stack_mode, stack_n,
                   video_mode=encframes.STACK_UP_TO_N, video_n=encframes.MAX_CLIP_FRAMES_SHOWN,
                   fit_to_output=True, phase2_mods="full", shrink_method="reencode",
                   window_mode=WINDOW_MODE_DEFAULT, phase1_mods="fit"):
    """The selection payload's text-encoder fields (see patches.py's
    _build_refmod_sentinels): how many pictures of a mod sent as one video,
    and how many frames of a video mod, the text encoder is shown, plus the
    panel's sizing and sliding-window options. Whether a mod is sent as one
    video is per row ("as_video" in each row)."""
    def count(value, default):
        try:
            return max(1, int(value or default))
        except (TypeError, ValueError):
            return default
    mode = stack_mode if stack_mode in encframes.STACK_CHOICES else encframes.STACK_ALL
    vmode = video_mode if video_mode in encframes.STACK_CHOICES else encframes.STACK_UP_TO_N
    return {"stack_pictures": mode,
            "stack_pictures_n": count(stack_n, encframes.STACK_DEFAULT_N),
            "video_frames": vmode,
            "video_frames_n": count(video_n, encframes.MAX_CLIP_FRAMES_SHOWN),
            # "Fit mods to the output size" (off by default).
            "fit_to_output": bool(fit_to_output),
            # "Mods in phase 2": full / tile / off.
            "phase2_mods": phase2_mods if phase2_mods in ("full", "tile", "off") else "full",
            # "Mods in phase 1": fit / full (fork.30).
            "phase1_mods": phase1_mods if phase1_mods in ("fit", "full") else "fit",
            # "Shrink method": reencode / fast.
            "shrink_method": shrink_method if shrink_method in ("reencode", "fast") else "reencode",
            # "Video mods on sliding windows 2, 3, ...": still / full / first.
            "window_mode": window_mode if window_mode in [v for _, v in WINDOW_MODE_CHOICES]
            else WINDOW_MODE_DEFAULT}


def _ordered_labels(items, word):
    """Number one kind's mods the way patches._order_by_label does: chosen
    numbers where asked, Auto ones filling the gaps in row order."""
    explicit = sorted((i for i in items if i[2]), key=lambda i: i[2])
    auto = [i for i in items if not i[2]]
    out, position = [], 1
    while explicit or auto:
        name, count, want = (explicit.pop(0) if explicit and (explicit[0][2] <= position or not auto)
                             else auto.pop(0))
        last = position + count - 1
        span = f"<{word} {position}>" if count == 1 else f"<{word} {position}>–<{word} {last}>"
        out.append(f"`{name}` → {span}" + (f" (asked for <{word} {want}>)" if want and want != position else ""))
        position = last + 1
    return out


def _format_label_line(rows):
    """Which <Picture N> / <Video N> / <Audio N> each picked mod will get in
    window 1 -- its chosen number, or the next free one on Auto. Assumes no
    start image, Continue Video or references of the generation's own: those
    take the first numbers, so with a start image pick <Picture 2> onwards (the
    console reports the labels each generation really used)."""
    pictures, videos, audios = [], [], []    # (mod name, count, wanted number)
    for name, strength, as_video, use_audio, label, audio_label in _normalize_rows(rows):
        meta = _row_meta(name, strength)
        if meta is None:
            continue
        kind = meta.get("kind", "image")
        latent_t = max(1, int(meta.get("latent_t", 1)))
        if _is_picture_mod(meta):
            if as_video == "video" and latent_t > 1:
                videos.append((name, 1, label))
            elif as_video == "sheet" and latent_t > 1:
                pictures.append((name, 1, label))
            else:
                pictures.append((name, latent_t, label))
        elif kind == "video":
            videos.append((name, 1, label))
        else:
            audios.append((name, 1, label))
            continue
        if meta.get("has_audio") and use_audio:
            audios.append((name + " (soundtrack)", 1, audio_label))

    parts = (_ordered_labels(pictures, "Picture") + _ordered_labels(videos, "Video")
             + _ordered_labels(audios, "Audio"))
    if not parts:
        return ""
    extra = ""
    if len(videos) > 3:
        extra = " (videos past the third have no label -- only 3 reference-video slots)"
    return ("**Prompt labels** (with no start image, Continue Video or references of your own -- "
            "those come first): " + " · ".join(parts) + extra)


def builder_mod_entries(state):
    """Refmods Studio: the armed mods as the Prompt Builder needs them, in the
    order and grouping _format_label_line uses. Each entry is
    {"key", "name", "kind": "picture" | "video" | "audio", "count", "label"}
    where count is how many labels it takes and label the number picked in
    the panel (None for Auto). A soundtrack is its own audio entry. Reads the
    selection the inline panel keeps in the session state."""
    try:
        payload = json.loads((state or {}).get(STASH_KEY) or "{}")
    except Exception:
        return []
    # Refmods Studio: which armed pack each mod came from, and its role there.
    in_pack = {}
    for pack in _armed_packs(state):
        for member in pack.get("members") or []:
            in_pack.setdefault(member.get("mod"), {"pack": pack.get("name"), "pack_kind": pack.get("kind"),
                                                   "pack_subject": pack.get("subject") or pack.get("name"),
                                                   "role": member.get("role") or "generic",
                                                   "pack_meta": pack.get("meta") or {},
                                                   "pack_parts": member.get("parts"),
                                                   "pack_sheet": member.get("sheet")})
    out = []
    for row in payload.get("rows") or []:
        name = row.get("mod")
        meta = _row_meta(name, row.get("strength", 0))
        if meta is None:
            continue
        kind = meta.get("kind", "image")
        latent_t = max(1, int(meta.get("latent_t", 1)))
        send_as = row.get("send_as") or ("video" if row.get("as_video") else "pictures")
        label = row.get("label")
        entry = {"key": f"mod:{name}", "name": name, "label": label,
                 "description": str(meta.get("description") or ""),
                 "concept": str(meta.get("concept_type") or "generic"), **in_pack.get(name, {})}
        if _is_picture_mod(meta):
            if send_as == "video" and latent_t > 1:
                out.append(dict(entry, kind="video", count=1))
            elif send_as == "sheet" and latent_t > 1:
                out.append(dict(entry, kind="picture", count=1, sheet=True))
            else:
                out.append(dict(entry, kind="picture", count=latent_t))
        elif kind == "video":
            out.append(dict(entry, kind="video", count=1))
        else:
            out.append(dict(entry, kind="audio", count=1))
            continue
        if meta.get("has_audio") and row.get("use_audio", True):
            soundtrack = {"key": f"mod:{name}:audio", "name": f"{name} (soundtrack)", "kind": "audio",
                          "count": 1, "label": row.get("audio_label"), "description": "", "concept": "voice"}
            if name in in_pack:
                soundtrack.update(in_pack[name], role="voice")
            out.append(soundtrack)
    return out


def _format_ref_counter(rows):
    """A live 'how close to MiniMax H3 Ref2VA's own native reference caps am
    I' readout, from the current (mod_name, strength, send-as-one-video) values of every
    picker row (image rows, then video rows, then audio rows, any order
    internally). Mirrors exactly what _inject_refmods will actually send at
    generation time: rows with no mod picked or strength<=0 are skipped,
    and -- critically -- an image-kind mod counts once *per frame it
    contains* (see patches.py's _inject_refmods: a multi-image stack gets
    split into one reference per frame), not once per mod. Video- and
    audio-kind mods, by contrast, each go into their own native reference
    slot no matter how many are picked, so what actually matters for them
    is total duration (each against its own, separate 15-second budget --
    video and audio don't share one)."""
    n_images = 0
    n_stacks = 0
    video_latent_frames = 0
    audio_seconds_total = 0.0
    n_video_files = 0
    n_audio_files = 0
    n_soundtracks = 0
    for name, strength, as_video, use_audio, _label, _audio_label in _normalize_rows(rows):
        try:
            strength = float(strength)
        except (TypeError, ValueError):
            continue
        if not name or name == NONE_CHOICE or strength <= 0:
            continue
        try:
            meta = storage.read_refmod_meta(storage.mod_path(name))
        except Exception:
            meta = None
        if meta is None:
            continue
        kind = meta.get("kind", "image")
        latent_t = max(1, int(meta.get("latent_t", 1)))
        if _is_picture_mod(meta) and as_video == "sheet" and latent_t > 1:
            n_images += 1          # fork.38: one contact sheet
        elif _is_picture_mod(meta) and as_video == "video" and latent_t > 1:
            n_stacks += 1          # one video reference; pictures have no duration
        elif _is_picture_mod(meta):
            n_images += latent_t
        elif kind == "video":
            t_px = (latent_t - 1) * 4 + 1 if latent_t > 1 else 1  # undo the causal 4:1 compression
            video_latent_frames += t_px
            n_video_files += _source_file_count(meta, "vid")
        else:  # "audio"
            audio_seconds_total += latent_t / AUDIO_LATENTS_PER_SECOND
            # Audio extraction takes exactly one file per mod, so each
            # selected audio mod is one source file.
            n_audio_files += 1
        # A soundtrack attached to an image or video mod is injected as its
        # own audio reference, so it counts toward the audio budget too --
        # unless the row's "Include audio" is unticked.
        if kind != "audio" and meta.get("has_audio") and use_audio:
            audio_seconds_total += int(meta.get("audio_t", 0) or 0) / AUDIO_LATENTS_PER_SECOND
            n_soundtracks += 1
    video_seconds = video_latent_frames / FPS_ASSUMED_FOR_DURATION_ESTIMATE
    # The 9 / 15s / 15s figures are MiniMax's *documented* reference budget,
    # which this plugin no longer enforces on RefMods (see patches.py's
    # _place_refmod_ref). They stay here purely as a reference point: the
    # model demonstrably works past them (15 image references verified by
    # the ComfyUI community), but that is past what MiniMax documents, so
    # the counter flags it as "beyond documented" rather than as an error.
    img_mark = "🔶" if n_images > 9 else "▫️" if n_images == 0 else "✅"
    vid_mark = "🔶" if video_seconds > 15 else "▫️" if video_seconds == 0 else "✅"
    aud_mark = "🔶" if audio_seconds_total > 15 else "▫️" if audio_seconds_total == 0 else "✅"
    notes = []
    if n_images > 9:
        notes.append(f"{n_images} images is past MiniMax's documented 9 (a multi-image mod counts "
                     f"once per image it contains). Verified to work up to ~15; expect more VRAM "
                     f"use and, at some point, attention dilution.")
    if video_seconds > 15:
        notes.append("video total is past the documented 15s budget.")
    if audio_seconds_total > 15:
        notes.append("audio total is past the documented 15s budget.")
    note = (" -- " + " ".join(notes)) if notes else ""
    label_line = _format_label_line(rows)
    vid_files = f" from {n_video_files} file{'s' if n_video_files != 1 else ''}" if n_video_files else ""
    if n_stacks:
        vid_files += f" + {n_stacks} picture stack{'s' if n_stacks != 1 else ''} as video"
    aud_parts = []
    if n_audio_files:
        aud_parts.append(f"{n_audio_files} file{'s' if n_audio_files != 1 else ''}")
    if n_soundtracks:
        aud_parts.append(f"{n_soundtracks} mod soundtrack{'s' if n_soundtracks != 1 else ''}")
    aud_files = (" from " + " + ".join(aud_parts)) if aud_parts else ""
    return (f"{img_mark} **Images: {n_images}** (documented budget: 9)&nbsp;&nbsp;&nbsp;"
           f"{vid_mark} **Video: ~{video_seconds:.1f}s**{vid_files} "
           f"(documented: 15s, at {FPS_ASSUMED_FOR_DURATION_ESTIMATE}fps)&nbsp;&nbsp;&nbsp;"
           f"{aud_mark} **Audio: {audio_seconds_total:.1f}s**{aud_files} (documented: 15s)"
           f"{note}"
           + (f"\n\n{label_line}" if label_line else ""))


def _hidden_from_api(build):
    """Run a UI builder and keep every event handler it registers out of
    Gradio's API listing (show_api=False).

    On the first page load Gradio builds that listing for every handler, and
    for each input it searches the whole component list -- so the work grows
    with handlers x inputs x components. The panel's handlers take every
    picker as input (~160 of them), and with Wan2GP's own large UI around it
    the first page load could pass the 3 seconds Gradio allows when it checks
    that localhost is reachable at launch. It then refuses to start with "When
    localhost is not accessible, a shareable link must be created" (seen with
    fork.20, fixed in fork.21). Nothing here is meant to be called through the API -- the
    plugin runs generations through Wan2GP's own session -- so hiding them
    loses nothing."""
    @functools.wraps(build)
    def wrapper(*args, **kwargs):
        try:
            from gradio.context import Context
            root = Context.root_block
            before = set(root.fns.keys()) if root is not None else None
        except Exception:
            root, before = None, None
        try:
            return build(*args, **kwargs)
        finally:
            if root is not None and before is not None:
                hidden = 0
                for key, fn in list(root.fns.items()):
                    if key not in before and getattr(fn, "show_api", False):
                        fn.show_api = False
                        hidden += 1
                if hidden:
                    print(f"[Refmods] {hidden} panel event handler(s) kept out of Gradio's API "
                          f"listing (faster first page load)")
    return wrapper


def _model_choices(api_session):
    try:
        records = api_session.list_model_defs(
            base_model_type=["minimax_h3_ref2va", "minimax_h3_ref2va_pruned"])
    except Exception as e:
        print(f"[Refmods] could not list MiniMax H3 Ref2VA models: {e!r}")
        records = []
    return [(r.get("name") or r.get("model_type"), r.get("model_type")) for r in records]


DEFAULT_MODEL_TYPE = "minimax_h3_ref2va_pruned"  # "MiniMax H3 Ref2VA Pruned 20B"


def _default_model_choice(model_choices):
    """Preselect MiniMax H3 Ref2VA Pruned 20B at startup -- the lighter,
    faster variant most people running this plugin day to day will have
    installed. Falls back to whatever's first if that exact model, or any
    other model whose name mentions "pruned", isn't available."""
    for _, model_type in model_choices:
        if model_type == DEFAULT_MODEL_TYPE:
            return model_type
    for display_name, model_type in model_choices:
        if "pruned" in str(display_name).lower():
            return model_type
    return model_choices[0][1] if model_choices else None


def _patches_module():
    from . import patches
    return patches


def _tag_job(overrides):
    """(overrides, job id) -- the id put into a plugin job's spec, or None
    for an ordinary generation."""
    import uuid
    custom = dict((overrides or {}).get("custom_settings") or {})
    for key, wrapper in ((SETTING_GENERATE, EXTRACT_WRAPPER_KEY), (flux.FLUX_SETTING, flux.FLUX_EXTRACT_KEY)):
        try:
            data = json.loads(custom.get(key) or "")
        except Exception:
            continue
        if isinstance(data, dict) and isinstance(data.get(wrapper), dict):
            job_id = uuid.uuid4().hex
            data[wrapper] = dict(data[wrapper], job_id=job_id)
            custom[key] = json.dumps(data)
            return dict(overrides, custom_settings=custom), job_id
    return overrides, None


_NO_OUTPUT_ERROR = "no output with client_id"


class _JobCallbacks:
    """Holds a job's status lines and errors until it ends, then hands the
    caller the job's own record (or, if the job never ran, what Wan2GP said)."""

    def __init__(self, inner):
        self.inner, self.status, self.errors = inner, [], []

    def on_status(self, message):
        if message:
            self.status.append(str(message))

    def on_error(self, error):
        self.errors.append(getattr(error, "message", None) or str(error))

    def on_progress(self, update):
        method = getattr(self.inner, "on_progress", None)
        if callable(method):
            method(update)

    def finish(self, recorded):
        relay_status = getattr(self.inner, "on_status", None)
        relay_error = getattr(self.inner, "on_error", None)
        lines = list(recorded) if recorded else self.status
        for line in lines:
            if callable(relay_status):
                relay_status(line)
        for message in self.errors:
            if recorded and _NO_OUTPUT_ERROR in message:
                continue   # expected: a job makes no video
            if callable(relay_error):
                relay_error(message)
            elif callable(relay_status):
                relay_status(f"error: {message}")


class MiniMaxH3RefModsPlugin(WAN2GPPlugin):
    def __init__(self):
        super().__init__()
        self.name = PlugIn_Name
        self.version = "0.38.1-fork.49"
        self.description = ("No-training reference mods for MiniMax H3: compress a reference "
                            "into a small file once, reuse it at any strength without "
                            "re-encoding it every generation.")
        self._patch_error = install_patches()
        self._flux_error = flux.install()   # fork.31: Flux 2 / Flux 3
        try:   # fork.32: every mod file in its model's folder (H3 / Flux)
            flux.sort_mod_files()
        except Exception as e:
            print(f"[Refmods] could not sort mod files into their model folders: {e!r}")

    def setup_ui(self):
        self.request_component("state")
        self.request_component("model_choice_target")
        self.request_component("wangp_model_choice_target")  # legacy/alternate name, harmless if absent
        self.request_global("get_current_model_settings")
        self.request_global("refresh_model_defs")
        self.request_global("prepare_inputs_dict")
        self.request_global("get_state_model_type")
        self.request_global("get_model_settings")
        self.request_global("get_base_model_type")
        self.request_global("set_model_settings")          # fork.34: restore on load
        self.request_global("collect_custom_settings_from_inputs")   # fork.42
        self.request_component("refresh_form_trigger")     # fork.34
        try:   # fork.34: a readable RefMods line in each output's info
            self.register_data_hook("before_metadata_save", outputinfo.before_metadata_save)
        except Exception as e:
            print(f"[Refmods] could not register the metadata hook ({e!r}); outputs won't list their RefMods")
        self.add_tab(tab_id=PlugIn_Id, label=PlugIn_Tab, component_constructor=self.create_ui)
        self._library_path = None
        try:   # Refmods Studio: the Library as a web app, shown in the Library subtab
            from .library_server import WEB_PATH as LIBRARY_PATH, create_app as create_library_app
            self.register_web_app(LIBRARY_PATH, lambda: create_library_app(self, self._library_models))
            self._library_path = LIBRARY_PATH
        except Exception as e:
            print(f"[Refmods] the Library web app could not start: {e!r}")
        self.insert_after(target_component_id="loras_multipliers",
                          new_component_constructor=self._build_inline_refmods_section)
        self.insert_after(target_component_id="loras_multipliers",   # fork.31
                          new_component_constructor=self._build_inline_flux_section)

    def post_ui_setup(self, components):
        """Wan2GP builds its whole model catalog (``models_def``, what
        ``get_model_def()`` reads from) once, at import time, well before any
        plugin is loaded -- so the ``family_handler.query_model_def`` patch
        installed in ``__init__`` (see patches.py) has no effect on entries
        already cached by then, even though the patch itself is correctly in
        place. ``self.refresh_model_defs`` (a global, only available once
        Wan2GP finishes injecting plugin globals -- i.e. here, not in
        ``__init__``) is Wan2GP's own supported way to rebuild that catalog
        on demand; calling it once now forces every MiniMax H3 model
        definition to be recomputed through our now-patched function, so the
        two RefMod custom_settings actually end up in the cache the rest of
        Wan2GP reads from."""
        if getattr(self, "_post_ui_setup_done", False):
            return {}  # Wan2GP appears to call post_ui_setup more than once at startup;
                      # everything below is safe to repeat but noisy/wasteful, so skip it.
        self._post_ui_setup_done = True

        refresh = getattr(self, "refresh_model_defs", None)
        if callable(refresh):
            try:
                refresh()
                print("[Refmods] refreshed Wan2GP's model catalog so the RefMod custom_settings "
                     "declaration takes effect on cached MiniMax H3 model definitions")
            except Exception as e:
                print(f"[Refmods] refresh_model_defs() failed ({e!r}); MiniMax H3 model "
                     "definitions may still be missing the RefMod custom_settings -- use "
                     "'Check setup for this model' in the plugin tab to confirm.")
        else:
            print("[Refmods] refresh_model_defs was not exposed by Wan2GP's plugin globals; "
                 "RefMods will likely not take effect until Wan2GP is restarted after this "
                 "plugin was enabled. Use 'Check setup for this model' in the plugin tab to confirm.")

        get_base_mt = getattr(self, "get_base_model_type", None)
        if not callable(get_base_mt):
            print("[Refmods] get_base_model_type was not exposed by Wan2GP's plugin globals; "
                 "a MiniMax H3 Ref2VA finetune whose own model_type name doesn't start with "
                 "'minimax_h3_ref2va' (e.g. a custom-named checkpoint) may not be recognized -- "
                 "the inline panel would stay hidden for it.")
            get_base_mt = None

        orig_prepare = getattr(self, "prepare_inputs_dict", None)
        get_state_mt = getattr(self, "get_state_model_type", None)
        if callable(orig_prepare) and callable(get_state_mt):
            err = install_prepare_inputs_dict_patch(orig_prepare, get_state_mt, self.set_global, get_base_mt)
            if err:
                print(f"[Refmods] {err}")
        else:
            print("[Refmods] prepare_inputs_dict / get_state_model_type were not exposed by "
                 "Wan2GP's plugin globals; the inline RefMods panel on the Media Generator page "
                 "will be visible but will not affect generations from that page's own Generate "
                 "button.")

        orig_set_model_settings = getattr(self, "set_model_settings", None)   # fork.34
        if callable(orig_set_model_settings):
            err3 = outputinfo.install_set_model_settings_patch(orig_set_model_settings, self.set_global, get_base_mt)
            if err3:
                print(f"[Refmods] {err3}")

        orig_collect = getattr(self, "collect_custom_settings_from_inputs", None)   # fork.42
        if callable(orig_collect):
            from . import patches
            err4 = patches.install_collect_custom_settings_patch(orig_collect, self.set_global)
            if err4:
                print(f"[Refmods] {err4}")

        orig_get_model_settings = getattr(self, "get_model_settings", None)
        if callable(orig_get_model_settings):
            err2 = install_get_model_settings_patch(orig_get_model_settings, self.set_global, get_base_mt)
            if err2:
                print(f"[Refmods] {err2}")
        else:
            print("[Refmods] get_model_settings was not exposed by Wan2GP's plugin globals; "
                 "a RefMod change right before clicking Generate (with no other field touched "
                 "in between) may not always be picked up from the inline panel -- change any "
                 "other field (e.g. click into the prompt box) once after picking mods as a "
                 "workaround.")
        return {}

    # ── Inline panel injected onto the Media Generator page ───────────────

    @_hidden_from_api
    def _build_inline_refmods_section(self):
        # Wan2GP hands plugins their requested components out of generate_media_tab's
        # own locals(), so the key is the Python *variable* name ("model_choice_target"),
        # not the elem_id ("wangp_model_choice_target"). Try both so this works across
        # Wan2GP versions regardless of which name a given build exposes.
        target = getattr(self, "model_choice_target", None) or getattr(self, "wangp_model_choice_target", None)
        # Default to visible (matches the previous, always-shown behavior) rather than
        # hidden: there's no confirmed signal that fires on the very first page load
        # (only on an actual model switch), so defaulting to hidden could strand the
        # panel out of sight for anyone who already has a MiniMax H3 Ref2VA model
        # selected by default and hasn't touched the model dropdown yet. The .change()
        # handler below still correctly hides it the moment any model switch happens.
        with gr.Accordion("Refmods: MiniMax H3", open=False, elem_classes="rs-panel") as accordion:
            gr.HTML(PANEL_CSS)
            gr.Markdown(
                "Works with **MiniMax H3 Ref2VA, FL2VA and FL2VA ControlNet**. Make mods on the **Refmods** tab (Create).")
            # Refmods Studio: packs, above the rows they fill. Presets became packs.
            with gr.Row(elem_classes="rs-packrow"):
                pack_box = gr.Dropdown(
                    choices=storage.list_packs(), value=None, allow_custom_value=True, show_label=False,
                    container=False, scale=3, min_width=200, label="Pack",
                    elem_classes="rs-packbox")
                pack_add = gr.Button("Add pack", size="sm", variant="primary", scale=0)
                pack_replace = gr.Button("Replace all", size="sm", scale=0)
                pack_save = gr.Button("Save as pack", size="sm", scale=0)
                pack_delete = gr.Button("Delete pack", size="sm", scale=0)
                pack_all = gr.Checkbox(False, label="Include switched-off mods", container=False, scale=0,
                                       min_width=190, elem_classes="rs-packall")
            gr.Markdown("*Packs are sets of mods, each with its role. Pick one and **Add pack** puts it into "
                        "the rows below, beside what's there; **Replace all** clears the rows first. Mods switched "
                        "off in the pack are left out unless **Include switched-off mods** is ticked. To save the "
                        "rows as a pack, type a name in the box. Your presets are listed as packs.*")
            pack_bridge = gr.Textbox(value="", elem_id="rs-pack-bridge", elem_classes="rs-hidden",
                                     show_label=False, container=False, interactive=True)
            # Fork: the full panel (per-row options, sizing, text encoder).
            mod_rows, panel_controls = self._build_mod_picker_rows_full()
            with gr.Row():
                status = gr.Markdown("*No RefMods selected.*")
                clear_btn = gr.Button("Clear RefMods", size="sm", scale=0)
            saved_arm = storage.read_auto_arm() or {}   # fork.47
            share = gr.Checkbox(
                bool(saved_arm.get("on")),
                label="Also use these for Showrunner, Deepy and API tasks",
                info="They can't pick mods themselves, so these are used whenever a generation "
                     "brings none. Every option set here comes with them.")
            # fork.48: a keyword box per armed mod, shown once the box above is
            # ticked. A mod with keywords waits until the prompt mentions one,
            # which is how one saved selection covers several characters.
            saved_rows = (saved_arm.get("state") or {}).get("rows") or []
            keyword_boxes = []
            for index in range(len(mod_rows)):
                keyword_boxes.append(gr.Textbox(
                    value=str(saved_rows[index].get("when") or "") if index < len(saved_rows) else "",
                    label="", visible=False, scale=1,
                    info="Commas for several. Blank = every generation."))

        widgets = [c for row in mod_rows for c in row] + list(panel_controls)

        def apply_selection(state, *vals):
            n_rows = IMAGE_ROWS + VIDEO_ROWS + AUDIO_ROWS
            row_vals = vals[:n_rows * ROW_WIDTH]
            rows = _rows_payload(row_vals)
            payload = {"rows": rows, "retention": 1.0, "scramble_seed": -1, "curve": None,
                       **_stack_payload(*vals[n_rows * ROW_WIDTH:n_rows * ROW_WIDTH + STACK_CONTROLS])}
            extras = vals[n_rows * ROW_WIDTH + STACK_CONTROLS:]   # fork.47: the "also use these" box
            shared = bool(extras[0]) if extras else False
            keywords = list(extras[1:1 + n_rows])                  # fork.48: one per picker row
            armed = _armed_row_indexes(row_vals, n_rows)
            _mirror_for_other_apps(payload, shared, [keywords[i] if i < len(keywords) else ""
                                                     for i in armed])
            boxes = []
            for index in range(n_rows):
                name = row_vals[index * ROW_WIDTH]
                boxes.append(gr.update(visible=shared and index in armed,
                                       label=f"Keyword for {name}" if index in armed else ""))
            if not isinstance(state, dict):
                return [state, "⚠️ Could not access session state -- try reloading the page."] + boxes
            if rows:
                state[STASH_KEY] = json.dumps(payload)
                msg = f"✅ {len(rows)} RefMod(s) armed for the next MiniMax H3 generation from this page."
                armed_mods = {row["mod"] for row in rows}
                packs = [p for p in _armed_packs(state) if any(m.get("mod") in armed_mods for m in p.get("members") or [])]
                state[ARMED_PACKS_KEY] = packs
                if packs:
                    msg += " Packs: " + ", ".join(p["name"] for p in packs) + "."
                if shared:
                    msg += " Showrunner, Deepy and API tasks use them too."
            else:
                state.pop(STASH_KEY, None)
                state.pop(ARMED_PACKS_KEY, None)
                msg = "*No RefMods selected.*"
            return [state, msg] + boxes

        def clear_selection(state):
            # Fork: empties the slots as well, so the panel never shows mods
            # that aren't armed.
            if isinstance(state, dict):
                state.pop(STASH_KEY, None)
                state.pop(ARMED_PACKS_KEY, None)
            resets = []
            for _ in mod_rows:
                resets += _cleared_row_updates()
            return [state, "*No RefMods selected.*"] + resets

        clear_btn.click(fn=clear_selection, inputs=[self.state],
                        outputs=[self.state, status] + [c for row in mod_rows for c in row], queue=False)

        # Refmods Studio: packs (presets were packs without roles). A pack holds
        # the armed rows, in order, with each row's settings and its role; the
        # panel-wide options only when the pack was saved with them.
        n_row_widgets = (IMAGE_ROWS + VIDEO_ROWS + AUDIO_ROWS) * ROW_WIDTH
        row_widgets = widgets[:n_row_widgets]

        def pack_choices(value=None):
            return gr.update(choices=storage.list_packs(), value=value)

        def save_pack(name, *row_vals):
            name = str(name or "").strip()
            if not name:
                return "Type a name for the pack first.", gr.update()
            rows = _rows_payload(row_vals)
            if not rows:
                return "Nothing is armed, so there is nothing to save.", gr.update()
            old = storage.read_pack(name) or {}
            roles = {m.get("mod"): m.get("role") for m in old.get("members") or []}
            members = [dict(row, role=roles.get(row["mod"]) or storage.mod_concept(row["mod"])) for row in rows]
            armed_names = {row["mod"] for row in rows}
            members += [m for m in old.get("members") or []   # switched off in the editor: kept
                        if m.get("on", True) is False and m.get("mod") not in armed_names]
            pack = {**old, "name": name, "kind": old.get("kind") or "mixed", "members": members}
            pack.pop("from_preset", None)
            try:
                storage.write_pack(pack)
            except Exception as e:
                return f"⚠️ Could not save the pack ({e}).", gr.update()
            return (f"💾 Pack '{name}' {'updated' if old else 'saved'}: {len(rows)} RefMod(s).",
                    pack_choices(name))

        def delete_pack(name):
            name = str(name or "").strip()
            if not storage.read_pack(name):
                return "Pick a saved pack to delete.", pack_choices()
            if not storage.delete_pack(name):
                return f"⚠️ Could not delete the pack '{name}'.", gr.update()
            return f"🗑️ Pack '{name}' deleted.", pack_choices(None)

        pack_save.click(fn=save_pack, inputs=[pack_box] + row_widgets, outputs=[status, pack_box], queue=False)
        pack_delete.click(fn=delete_pack, inputs=[pack_box], outputs=[status, pack_box], queue=False)

        # fork.34: loading a file's settings refills the panel (outputinfo).
        parts = getattr(self, "_panel_parts", None)
        refresh_trigger = getattr(self, "refresh_form_trigger", None)
        triggers = [t.change for t in (refresh_trigger, target) if t is not None]
        if parts is not None and triggers:
            kinds = ("image", "video", "audio")
            restore_outputs = ([status, parts["folder_dd"]] + widgets
                               + [ui for k in kinds for ui in parts["kind_ui"][k]]
                               + [parts["shown"][k] for k in kinds])

            def restore_panel(state):
                if not isinstance(state, dict) or outputinfo.RESTORE_H3 not in state:
                    return [gr.update()] * len(restore_outputs)
                return _panel_restore_updates(state.pop(outputinfo.RESTORE_H3))

            gr.on(triggers=triggers, fn=restore_panel, inputs=[self.state], outputs=restore_outputs,
                  queue=False)

        if parts is not None:
            kinds = ("image", "video", "audio")
            load_outputs = ([status, parts["folder_dd"]] + widgets
                            + [ui for k in kinds for ui in parts["kind_ui"][k]]
                            + [parts["shown"][k] for k in kinds])

            def load_pack(state, name, replace, *row_vals, include_off=False):
                name = str(name or "").strip()
                pack = storage.read_pack(name)
                if not pack:
                    return [state, "Pick a saved pack first."] + [gr.update()] * (len(load_outputs) - 1)
                # Packs editor: a member switched off stays in the pack but isn't loaded.
                members = [dict(m) for m in pack.get("members") or []
                           if m.get("mod") and (include_off or m.get("on", True) is not False)]
                for m in members:
                    m.pop("on", None)
                missing = [m["mod"] for m in members if not os.path.isfile(storage.mod_path(m["mod"]) + ".safetensors")]
                members = [m for m in members if m["mod"] not in missing]
                if not members:
                    return [state, f"⚠️ None of the pack's mods are in your mods folder ({', '.join(missing)})."] + \
                        [gr.update()] * (len(load_outputs) - 1)
                current = [] if replace else _rows_payload(row_vals)
                have = {row["mod"] for row in current}
                rows = current + [m for m in members if m["mod"] not in have]
                payload = {"rows": rows}
                settings = pack.get("settings") if replace else None
                if isinstance(settings, dict):
                    payload.update(settings)
                if isinstance(state, dict):
                    armed = [] if replace else [p for p in _armed_packs(state) if p.get("name") != name]
                    armed.append({"name": name, "kind": pack.get("kind", "mixed"),
                                  "subject": pack.get("subject_name") or "",
                                  "meta": pack.get("subject") if isinstance(pack.get("subject"), dict) else {},
                                  "members": [{"mod": m["mod"], "role": m.get("role") or storage.mod_concept(m["mod"]),
                                               **({"parts": list(m["parts"])} if isinstance(m.get("parts"), list) else {}),
                                               **({"sheet": bool(m["sheet"])} if "sheet" in m else {})}
                                              for m in members]})
                    state[ARMED_PACKS_KEY] = armed
                verb = "replaced the rows with" if replace else "added"
                source = f"pack '{name}' ({verb})" + (f"; not found, skipped: {', '.join(missing)}" if missing else "")
                return [state] + _panel_restore_updates(json.dumps(payload), keep_controls=not isinstance(settings, dict),
                                                        source=source)

            pack_add.click(fn=lambda st, n, inc, *v: load_pack(st, n, False, *v, include_off=bool(inc)),
                           inputs=[self.state, pack_box, pack_all] + row_widgets,
                           outputs=[self.state] + load_outputs, queue=False)
            pack_replace.click(fn=lambda st, n, inc, *v: load_pack(st, n, True, *v, include_off=bool(inc)),
                               inputs=[self.state, pack_box, pack_all] + row_widgets,
                               outputs=[self.state] + load_outputs, queue=False)

            # The Prompt Builder's Load pack writes {"name", "replace"} here; the panel loads it as Add pack does.
            def bridge_load(state, request, include_off, *row_vals):
                try:
                    req = json.loads(request or "{}")
                except Exception:
                    req = {}
                if not req.get("name"):
                    return [state] + [gr.update()] * len(load_outputs)
                return load_pack(state, req["name"], bool(req.get("replace")), *row_vals,
                                 include_off=bool(req.get("all", include_off)))

            pack_bridge.change(fn=bridge_load, inputs=[self.state, pack_bridge, pack_all] + row_widgets,
                               outputs=[self.state] + load_outputs, queue=False)
        else:
            for button in (pack_add, pack_replace):
                button.click(fn=lambda: "Loading packs needs a newer Wan2GP panel layout.",
                             inputs=[], outputs=[status], queue=False)

        # One handler for every widget (gr.on), not one per widget: each takes
        # every widget as input, and Gradio's first page load does work for
        # every handler x input (see _hidden_from_api).
        gr.on(triggers=[w.change for w in widgets + [share] + keyword_boxes], fn=apply_selection,
              inputs=[self.state] + widgets + [share] + keyword_boxes,
              outputs=[self.state, status] + keyword_boxes, queue=False)

        if target is not None:
            get_base_mt = getattr(self, "get_base_model_type", None)

            def update_visibility(target_value):
                model_type = str(target_value or "").split("|", 1)[0].strip()
                return gr.update(visible=is_minimax_h3_refmod_capable(model_type, get_base_mt))

            target.change(fn=update_visibility, inputs=[target], outputs=[accordion], queue=False)
        else:
            print("[Refmods] neither 'model_choice_target' nor 'wangp_model_choice_target' was "
                 "exposed by Wan2GP -- the inline panel will stay visible for every model instead "
                 "of only MiniMax H3 Ref2VA ones (it still has no effect on other models, this "
                 "only affects whether it's shown).")

        return accordion

    @_hidden_from_api
    def _build_inline_flux_section(self):   # fork.31
        return flux_ui.build_inline(self)

    def _submit(self, api_session, model_type, overrides, callbacks):
        """fork.39: a plugin job (extract, decompile, Library job, Flux
        extraction) is tagged with an id, and its own record of what it
        reported is handed to ``callbacks`` once it ends -- Wan2GP's API can
        miss a job's last status line, and reports "no output ... in the
        gallery" for every job, since jobs make no video on purpose."""
        overrides, job_id = _tag_job(overrides)
        if not job_id:
            return self._submit_task(api_session, model_type, overrides, callbacks)
        relay = _JobCallbacks(callbacks)
        try:
            return self._submit_task(api_session, model_type, overrides, relay)
        finally:
            relay.finish(_patches_module().JOB_RESULTS.pop(job_id, None))

    def _submit_task(self, api_session, model_type, overrides, callbacks):
        """Build a full, validated settings dict for ``model_type`` -- starting
        from that model's own factory defaults, then applying ``overrides`` --
        and submit it. Any field this plugin doesn't have a widget for still
        gets a sane, model-correct value this way."""
        payload = dict(overrides)
        payload["model_type"] = model_type  # always wins, even if overrides (e.g. a synced
                                            # main-form snapshot) carried a different one
        merged = api_session.merge_settings_with_defaults(payload)
        merged["model_type"] = model_type
        job = api_session.submit_task(merged, callbacks=callbacks)
        return job.result()

    # ── Extract ─────────────────────────────────────────────────────────


    def _build_mod_picker_rows_full(self):
        """Fork. The mod pickers: a folder picker + "Refresh mod list" button, the
        live budget/label readout, the "Text encoder options" accordion, then
        one slot per kind (image, video, audio) with Add / Remove buttons
        revealing up to IMAGE_ROWS / VIDEO_ROWS / AUDIO_ROWS -- all wired
        before returning. Returns the flat list of (dropdown, strength,
        send-as-one-video, include-audio, max-size) rows (ROW_WIDTH values each), image
        rows first, then video rows, then audio rows. "Send as one video" only
        shows on image rows holding a multi-picture mod, "Include audio" only
        on image/video rows holding a mod with a soundtrack. Callers must keep
        that order when reading values
        back (_refresh_mod_dropdown_updates() does too) -- plus the encoder
        controls (picture mode, N, video mode, N) and the "Fit mods to the
        output size" box, the "Mods in phase 2" and "Shrink method" choices -- STACK_CONTROLS
        values -- which callers put into
        the selection payload with _stack_payload()."""
        with gr.Row():
            folder_dd = gr.Dropdown(choices=_folder_choices(), value=ALL_FOLDERS_CHOICE,
                                    label="Folder", scale=3,
                                    info="Show one subfolder only.")
            refresh_btn = gr.Button("🔄 Refresh mod list", size="sm", scale=1)
        # Above the pickers, where they can't be missed: the readout of what
        # is selected (with each mod's prompt label), then the text encoder
        # options.
        counter = gr.Markdown(_format_ref_counter([]))
        with gr.Accordion("Text encoder options", open=True):
            gr.Markdown("Pictures the text encoder sees per mod, to bind its label. The model always gets the whole mod.")
            with gr.Row():
                stack_mode = gr.Dropdown(
                    choices=list(encframes.STACK_CHOICES), value=encframes.STACK_ALL, scale=3,
                    label="Mods sent as one video: pictures shown",
                    info="'up to N' saves memory on big stacks.")
                stack_n = gr.Number(value=encframes.STACK_DEFAULT_N, precision=0, minimum=1,
                                    maximum=256, label="N", visible=False, scale=1)
            with gr.Row():
                video_mode = gr.Dropdown(
                    choices=[encframes.STACK_UP_TO_N, encframes.STACK_ALL],
                    value=encframes.STACK_UP_TO_N, scale=3,
                    label="Video mods: frames shown",
                    info="Two frames a second are stored; 'up to N' spreads N across the clip.")
                video_n = gr.Number(value=encframes.MAX_CLIP_FRAMES_SHOWN, precision=0, minimum=1,
                                    maximum=256, label="N", scale=1)
        with gr.Row():
            fit_to_output = gr.Checkbox(
                True, label="Fit mods to the output size (faster)", scale=2,
                info="Shrink mods larger than the output. Less detail.")
            shrink_method = gr.Dropdown(
                choices=SHRINK_METHOD_UI, value="reencode", label="Shrink method", scale=1,
                info="Re-encode: best. Fast: instant, rougher.")
        with gr.Row():
            # fork.30: two-phase runs only.
            phase1_mods = gr.Dropdown(
                choices=PHASE1_MODS_UI, value="fit", label="Mods in phase 1 (two-phase)", scale=1,
                info="Fit: shrink to phase 1's half canvas, if phase 1 gets slow.")
            phase2_mods = gr.Dropdown(
                choices=PHASE2_MODS_UI, value="full", label="Mods in phase 2 (two-phase)", scale=1,
                info="Off: no visual mods (fastest).")
        window_mode = gr.Dropdown(
            label="Video mods on sliding windows 2, 3, ...",
            choices=WINDOW_MODE_CHOICES, value=WINDOW_MODE_DEFAULT,
            info="Runs longer than one window only. Image and audio mods reach every window.")

        # One slot per kind to start with; "Add" reveals the next one and
        # "Remove" clears and hides the last. Every slot is still built up
        # front (Gradio can't create components on the fly) -- the hidden ones
        # are simply empty, and the order returned is unchanged: image rows,
        # then video rows, then audio rows, each a (dropdown, strength,
        # send-as-one-video) triple.
        mod_rows = []
        kind_ui_all, shown_all = {}, {}   # fork.34
        counts = (IMAGE_ROWS, VIDEO_ROWS, AUDIO_ROWS)
        for kind, label, count in (("image", "Image RefMods", counts[0]),
                                   ("video", "Video RefMods", counts[1]),
                                   ("audio", "Audio RefMods", counts[2])):
            gr.Markdown(f"**{label}**" + (" -- a start image, Continue Video or your own references "
                                           "take the first label numbers." if kind == "image" else ""))
            kind_rows, kind_ui = [], []
            # Refmods Studio: one compact line per mod, under column headings.
            # Each control sits in a fixed column so a hidden one (Send as on a
            # single picture, Sound on a mod without one) keeps its space and
            # the columns stay lined up.
            columns = [c for c in ROW_COLUMNS if kind != "audio" or c[0] in ("Mod", "Strength", "Label")]
            with gr.Row(elem_classes="rs-row rs-head"):
                for heading, scale, width in columns:
                    with gr.Column(scale=scale, min_width=width):
                        gr.HTML(f"<span class='rs-heading'>{heading}</span>")
            for i in range(count):
                with gr.Row(visible=i == 0, elem_classes="rs-row") as row_ui:
                    with gr.Column(scale=ROW_COLUMNS[0][1], min_width=ROW_COLUMNS[0][2]):
                        mdd = gr.Dropdown(choices=_mod_choices(kind), value=NONE_CHOICE, show_label=False,
                                          container=False, label=f"{kind.capitalize()} mod {i + 1}")
                    with gr.Column(scale=ROW_COLUMNS[1][1], min_width=ROW_COLUMNS[1][2]):
                        strength = gr.Number(value=1.0, minimum=0.0, maximum=2.0, step=0.05, show_label=False,
                                             container=False, label="Strength")
                    with gr.Column(scale=ROW_COLUMNS[2][1], min_width=ROW_COLUMNS[2][2]):
                        # fork.27: the prompt label this mod gets (Auto = next free).
                        label_dd = gr.Dropdown(choices=_label_choices(kind), value=AUTO_LABEL, show_label=False,
                                               container=False, label="Label", visible=False)
                    with gr.Column(scale=ROW_COLUMNS[3][1], min_width=ROW_COLUMNS[3][2],
                                   visible=kind != "audio"):
                        as_video = gr.Dropdown(choices=SEND_AS_SHORT, value="pictures", show_label=False,
                                               container=False, label="Send as",
                                               visible=False)   # fork.38 (was a checkbox)
                    with gr.Column(scale=ROW_COLUMNS[4][1], min_width=ROW_COLUMNS[4][2],
                                   visible=kind != "audio"):
                        use_audio = gr.Checkbox(True, label="use", container=False, visible=False)
                    with gr.Column(scale=ROW_COLUMNS[5][1], min_width=ROW_COLUMNS[5][2],
                                   visible=kind != "audio"):
                        audio_label_dd = gr.Dropdown(choices=_label_choices("audio"), value=AUTO_LABEL,
                                                     show_label=False, container=False,
                                                     label="Soundtrack label", visible=False)
                kind_rows.append((mdd, strength, as_video, use_audio, label_dd, audio_label_dd))
                kind_ui.append(row_ui)
                mdd.change(fn=lambda name, _kind=kind, _key=(kind, i): _row_boxes_update(name, _kind, _key),
                           inputs=[mdd], outputs=[as_video, use_audio, label_dd, audio_label_dd],
                           queue=False)
                if kind == "image":
                    # One video reference: the label becomes a <Video N>.
                    as_video.change(fn=lambda on, name, _key=(kind, i): _as_video_label_update(on, name, _key),
                                    inputs=[as_video, mdd], outputs=[label_dd], queue=False)
                if kind != "audio":
                    use_audio.change(fn=_soundtrack_label_update, inputs=[use_audio, mdd],
                                     outputs=[audio_label_dd], queue=False)
            with gr.Row():
                add_btn = gr.Button(f"➕ Add {kind} mod", size="sm", scale=0, min_width=150)
                remove_btn = gr.Button("➖ Remove last", size="sm", scale=0, min_width=150)
            shown = gr.State(1)
            kind_ui_all[kind], shown_all[kind] = kind_ui, shown   # fork.34
            kind_widgets = [c for row in kind_rows for c in row]

            def add_slot(n, _count=count):
                n = min(_count, int(n or 1) + 1)
                return [n] + [gr.update(visible=k < n) for k in range(_count)]

            def remove_slot(n, _count=count, _width=ROW_WIDTH):
                n = max(1, int(n or 1))
                last = n - 1                       # the slot being cleared
                n = max(1, n - 1)
                cleared = []
                for k in range(_count):
                    if k == last:
                        cleared += _cleared_row_updates()[:_width]
                    else:
                        cleared += [gr.update()] * _width
                return [n] + [gr.update(visible=k < n) for k in range(_count)] + cleared

            add_btn.click(fn=add_slot, inputs=[shown], outputs=[shown] + kind_ui, queue=False)
            remove_btn.click(fn=remove_slot, inputs=[shown],
                             outputs=[shown] + kind_ui + kind_widgets, queue=False)
            mod_rows.extend(kind_rows)

        picker_outputs = [folder_dd] + [r[0] for r in mod_rows]
        # The current selections are passed in as well so switching folders
        # can preserve them (see _refresh_mod_dropdown_updates) -- without
        # that, narrowing to a folder would drop any mod picked from a
        # different one and Gradio would reject the now-stale value.
        picker_inputs = [folder_dd] + [r[0] for r in mod_rows]
        refresh_btn.click(fn=_refresh_mod_dropdown_updates, inputs=picker_inputs,
                          outputs=picker_outputs, queue=False)
        folder_dd.change(fn=_refresh_mod_dropdown_updates, inputs=picker_inputs,
                         outputs=picker_outputs, queue=False)

        def update_counter(*vals):
            rows = [tuple(vals[i * ROW_WIDTH:(i + 1) * ROW_WIDTH]) for i in range(len(mod_rows))]
            return _format_ref_counter(rows)

        row_widgets = [c for row in mod_rows for c in row]
        gr.on(triggers=[w.change for w in row_widgets], fn=update_counter, inputs=row_widgets,
              outputs=[counter], queue=False)
        stack_mode.change(fn=lambda mode: gr.update(visible=mode == encframes.STACK_UP_TO_N),
                          inputs=[stack_mode], outputs=[stack_n], queue=False)
        video_mode.change(fn=lambda mode: gr.update(visible=mode == encframes.STACK_UP_TO_N),
                          inputs=[video_mode], outputs=[video_n], queue=False)

        # fork.34: what a restore (outputinfo) needs to refill this panel.
        self._panel_parts = {"folder_dd": folder_dd, "kind_ui": kind_ui_all, "shown": shown_all}
        return mod_rows, (stack_mode, stack_n, video_mode, video_n, fit_to_output, phase2_mods,
                          shrink_method, window_mode, phase1_mods)


    # ── Library ─────────────────────────────────────────────────────────


    # ── Generate ────────────────────────────────────────────────────────


    def _library_models(self):
        """The models the Refmods app's jobs can run on (it needs WanGP's session)."""
        session = getattr(self, "_wangp_session", None)
        if session is None:
            return {"h3": [], "h3_default": None, "flux": []}
        h3 = _model_choices(session)
        return {"h3": h3, "h3_default": _default_model_choice(h3), "flux": flux_ui._model_choices(session)}

    def _library_setup(self, model_type):
        """The Setup page: the hook check for a model, what other apps get, and where things are."""
        session = getattr(self, "_wangp_session", None)
        if session is None:
            lines = ["⚠️ WanGP hasn't handed the plugin its session yet. Open the Refmods tab, then check again."]
        else:
            lines = [line for line in _diagnose(session, model_type, self._patch_error).split("\n") if line.strip()]
        auto = storage.read_auto_arm() or {}
        errors = []
        if getattr(self, "_flux_error", None):
            errors.append(f"Flux mods are off: {self._flux_error}")
        root = os.path.abspath(os.path.dirname(storage.refmods_dir()))
        paths = [("MiniMax H3 mods", storage.refmods_dir()), ("Flux mods", flux.mods_dir()),
                 ("Packs", storage.packs_dir()), ("Previews", os.path.join(root, "previews")),
                 ("Decompiled files", os.path.join(root, "decompiled")), ("Uploads", os.path.join(root, "uploads"))]
        return {"lines": lines, "autoarm": _autoarm_summary(auto), "autoarm_on": bool(auto.get("on")),
                "paths": [(k, os.path.abspath(v)) for k, v in paths], "errors": errors}

    def _library_autoarm_off(self):
        saved = storage.read_auto_arm() or {}
        if not saved.get("on"):
            return {"ok": True, "message": "It was already off."}
        saved["on"] = False
        storage.write_auto_arm(saved)
        return {"ok": True, "message": "Off. Other apps get no mods unless they bring their own."}

    # ── Tab assembly ────────────────────────────────────────────────────

    @_hidden_from_api
    def create_ui(self, api_session):
        """Refmods Studio: the whole tab is the Refmods web app (Library, Create, Packs, Setup)."""
        with gr.Column() as root:
            if self._patch_error:
                gr.Markdown(f"⚠️ **RefMods could not hook into MiniMax H3**: {self._patch_error}")
            if getattr(self, "_library_path", None):
                # .wangp-addon-web-view lets WanGP's full-screen button size the frame.
                gr.HTML(f'<div class="wangp-addon-web-view"><iframe src="{self._library_path}/?embedded=1" '
                        'title="Refmods" style="width:100%;height:calc(100vh - 215px);'
                        'min-height:700px;border:0;border-radius:8px" allow="clipboard-write"></iframe></div>')
            else:
                gr.Markdown("⚠️ **The Refmods app could not start.** The console says why (look for "
                            "`[Refmods] the Library web app could not start`). The panel under the prompt box "
                            "still works.")
        return root
