"""
The Prompt Builder's interface: the Prompt Builder tab and the compact strip
under WanGP's prompt box.

The builder reads what the Generator page will send (start and end images,
reference images, videos and audio, the source video) and the mods armed in
the Refmods panel, and labels them the way the pipeline will. It loads nothing
itself. Prompt text, labels and checks come from studio_core; this file only
lays out the controls and wires them.

The one piece of browser code is click-to-insert: a label chip or an insert
button puts its text at the cursor of the box you were last typing in.
"""

from __future__ import annotations

import html
import json
import sys
import time
from pathlib import Path

import gradio as gr

from . import studio_core as core

MEDIA_COMPONENTS = ("image_start", "image_end", "image_refs", "video_source", "video_guide", "video_guide2",
                    "video_guide3", "audio_guide", "audio_guide2", "audio_guide3", "image_prompt_type",
                    "video_prompt_type", "audio_prompt_type")

IMAGE_CAPS = {"minimax_p_h3_image": 8, "minimax_h3_image": 16, "minimax_h3_image_pruned": 16}

INSERT_JS = r"""
(function () {
  if (window.__rsInsert) return;
  var last = null;
  document.addEventListener('focusin', function (e) {
    var t = e.target;
    if (t && (t.tagName === 'TEXTAREA' || (t.tagName === 'INPUT' && t.type === 'text'))) last = t;
  }, true);
  window.__rsInsert = function (text) {
    if (!text) return;
    var el = last;
    if (!el || !document.body.contains(el)) {
      el = document.querySelector('#rs-action textarea');
    }
    if (!el) return;
    var start = (el.selectionStart == null) ? el.value.length : el.selectionStart;
    var end = (el.selectionEnd == null) ? start : el.selectionEnd;
    el.setRangeText(text, start, end, 'end');
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.focus();
  };
  document.addEventListener('click', function (e) {
    var b = e.target.closest ? e.target.closest('[data-rs-insert]') : null;
    if (!b) return;
    e.preventDefault();
    window.__rsInsert(b.getAttribute('data-rs-insert'));
  }, true);
})();
"""

INSERT_AFTER = "(s) => { if (window.__rsInsert) { window.__rsInsert(s); } }"

CHIP_CSS = """<style>
.rs-chips{display:flex;flex-wrap:wrap;gap:6px;margin:2px 0}
.rs-chip{display:inline-flex;gap:6px;align-items:center;padding:3px 9px;border-radius:6px;cursor:pointer;
 font:600 12px var(--font-mono, monospace);color:var(--body-text-color);background:var(--block-background-fill);
 border:1px solid var(--border-color-primary)}
.rs-chip:hover{border-color:var(--color-accent)}
.rs-chip small{font-weight:400;color:var(--body-text-color-subdued);font-family:var(--font)}
.rs-gen{border-left:3px solid #3b82f6}.rs-mod{border-left:3px solid #8b5cf6}.rs-aud{border-left:3px solid #14b8a6}
.rs-unused{border-style:dashed;border-color:#d97706}
.rs-note{font-size:12px;color:var(--body-text-color-subdued)}
</style>"""


def _s(value) -> str:
    return str(value or "").strip()


def _data_dir() -> Path:
    root = Path.cwd()
    for folder in Path(__file__).resolve().parents:
        if (folder / "wgp.py").is_file():
            root = folder
            break
    path = root / "loras" / "h3_prompt_builder"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:                                  # noqa: BLE001
        pass
    return path


def _clean_name(name) -> str:
    keep = [c for c in _s(name) if c.isalnum() or c in " -_.,()"]
    cleaned = "".join(keep).strip(" .")
    while ".." in cleaned:
        cleaned = cleaned.replace("..", ".")
    return cleaned[:80].strip(" .")


def _write_json(path: Path, blob) -> None:
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(blob, indent=1), encoding="utf-8")
    temp.replace(path)


class StudioUI:
    """Built once per plugin; build_strip and build_tab each make their part."""

    def __init__(self, plugin):
        self.plugin = plugin
        self._draft_cache = {"form": None}

    # -- reading WanGP -------------------------------------------------------

    def _media_inputs(self):
        return [getattr(self.plugin, name, None) for name in MEDIA_COMPONENTS]

    def _present_media(self):
        return [c for c in self._media_inputs() if c is not None]

    def _media_values(self, values):
        present = [name for name in MEDIA_COMPONENTS if getattr(self.plugin, name, None) is not None]
        return dict(zip(present, values))

    def _model(self, state) -> dict:
        model_type = _s((state or {}).get("model_type")) if isinstance(state, dict) else ""
        model_type = model_type or _s(getattr(self.plugin, "current_model_type", ""))
        model_def = {}
        get_def = getattr(self.plugin, "get_model_def", None)
        if callable(get_def) and model_type:
            try:
                model_def = get_def(model_type) or {}
            except Exception:                          # noqa: BLE001
                model_def = {}
        arch = _s(model_def.get("architecture")).lower()
        urls = " ".join(str(u) for u in (model_def.get("URLs") or []) if isinstance(u, str)).lower()
        return {"model_type": model_type, "h3": "minimax_h3" in (model_type + arch).lower(),
                "ref2va": "ref2va" in (model_type.lower() + arch + urls),
                "image_cap": IMAGE_CAPS.get(arch, 0)}

    def _mods(self, state) -> list:
        root = (__package__ or "").rsplit(".", 1)[0]
        module = sys.modules.get(f"{root}.refmods.plugin")
        reader = getattr(module, "builder_mod_entries", None)
        if not callable(reader):
            return []
        try:
            return reader(state if isinstance(state, dict) else {}) or []
        except Exception as exc:                       # noqa: BLE001
            print(f"[Refmods Studio] could not read the armed mods: {exc!r}")
            return []

    def _read_media(self, state, values):
        model = self._model(state)
        media = core.detect_media(self._media_values(values), model, self._mods(state))
        return {"media": [m.to_dict() for m in media], "model": model}

    @staticmethod
    def _unpack_media(blob):
        blob = blob if isinstance(blob, dict) else {}
        return [core.Media.from_dict(m) for m in blob.get("media") or []], blob.get("model") or {}

    # -- shared pieces -------------------------------------------------------

    @staticmethod
    def _chips_html(media, cited_text="", note=True) -> str:
        if not media:
            return (CHIP_CSS + "<div class='rs-note'>Nothing loaded on the Generator page gets a label yet: "
                    "no start or end image, references or armed mods.</div>")
        chips = []
        for m in media:
            if not m.labels:
                continue
            css = "rs-aud" if m.kind == "audio" else ("rs-mod" if m.source == "mod" else "rs-gen")
            if cited_text and m.role not in ("start", "continue", "end") and not any(l in cited_text for l in m.labels):
                css += " rs-unused"
            what = {"start": "start frame", "continue": "continued video", "end": "end frame",
                    "injected": "injected", "ref": "ref", "refvideo": "ref video", "refaudio": "ref audio",
                    "soundtrack": "soundtrack", "mod": "mod"}.get(m.role, m.role)
            text = m.label_text
            chips.append(f"<button class='rs-chip {css}' data-rs-insert='{html.escape(text, quote=True)}' "
                         f"title='Insert {html.escape(text, quote=True)}'>{html.escape(text)} "
                         f"<small>{html.escape(what)} · {html.escape(m.name)}</small></button>")
        legend = ("<div class='rs-note'>Blue: from the Generator page. Purple: armed mods. Teal: audio. Dashed: "
                  "sent but not used in the prompt yet. Click one to insert it where you were typing.</div>"
                  if note else "")
        return CHIP_CSS + "<div class='rs-chips'>" + "".join(chips) + "</div>" + legend

    @staticmethod
    def _resolve_mode(mode, media):
        detected = core.auto_mode(media)
        return (detected if mode in (None, "", core.AUTO) else mode), detected

    @staticmethod
    def _form(mode, duration, summary, style, action, sound, music, subjects):
        return core.clean_form({"mode": mode, "duration": duration, "summary": summary, "style": style,
                                "action": action, "sound": sound, "music": music, "subjects": subjects or []})

    def _lint(self):
        try:
            from .h3studio import lint
            return lint.check
        except Exception:                              # noqa: BLE001
            return None

    @staticmethod
    def _checks_md(result) -> str:
        lines = [f"- 🔴 **Error:** {e}" for e in result["errors"]]
        lines += [f"- 🟠 {w}" for w in result["warnings"]]
        lines += [f"- 🟢 {i}" for i in result["info"]]
        return "\n".join(lines) or "- 🟢 Nothing to fix."

    # -- the strip under the prompt box ------------------------------------------

    def build_strip(self):
        start_visible = self.plugin._starts_visible() if hasattr(self.plugin, "_starts_visible") else True
        with gr.Column(visible=start_visible, elem_classes="rs-strip") as root:
            with gr.Row():
                status = gr.Markdown("**Prompt Builder**: write prompts in the *Prompt Builder* tab.")
                check_btn = gr.Button("Check the prompt box", size="sm", scale=0, min_width=180)
            chips = gr.HTML(self._chips_html([], note=False))
            result = gr.Markdown("")
            media_state = gr.State({})
            sig = gr.State("")
            warning = gr.Markdown(visible=False)
        self._wire_media(media_state, sig, [chips, status], self._strip_refresh)
        prompt = getattr(self.plugin, "prompt", None)
        if prompt is not None:
            check_btn.click(fn=self._check_prompt_box, inputs=[prompt, media_state], outputs=[result])
        try:
            self.plugin._wire_model_visibility(root, warning, inline=True)
        except Exception as exc:                       # noqa: BLE001
            print(f"[Refmods Studio] builder strip visibility not wired: {exc!r}")
        return root

    def _strip_refresh(self, blob):
        media, model = self._unpack_media(blob)
        mode = core.auto_mode(media)
        counts = core.media_summary(media)
        line = (f"**Prompt Builder** · mode **{mode}** from {counts}. Write prompts in the *Prompt Builder* tab; "
                "click a label to put it in the prompt box.")
        if media and not model.get("h3"):
            line += " The selected model isn't MiniMax H3."
        return [self._chips_html(media, note=False), line]

    def _check_prompt_box(self, text, blob):
        media, model = self._unpack_media(blob)
        mode = core.auto_mode(media)
        if not _s(text):
            return "The prompt box is empty."
        lint = self._lint()
        errors, warnings = [], []
        if lint is not None:
            try:
                report = lint(text, "Ref2VA" if mode == "Reference" else "auto", None, 0)
                errors += report.get("errors", [])
                warnings += report.get("warnings", [])
            except Exception:                          # noqa: BLE001
                pass
        import re
        cited = set(re.findall(r"<(?:Picture|Video|Audio) \d+>", text))
        sent = {label for m in media for label in m.labels}
        errors += [f"{label} is in the prompt but nothing loaded or armed gets that label"
                   for label in sorted(cited - sent)]
        for m in media:
            unused = [l for l in m.labels if l not in cited]
            if unused and m.role not in ("start", "continue", "end"):
                warnings.append(f"{core.join_labels(unused)} ({m.name}) is sent but never used")
        return self._checks_md({"errors": errors, "warnings": warnings, "info": []})

    def _wire_media(self, media_state, sig, outputs, render):
        """Re-read what's loaded whenever a Generator input changes, and every
        few seconds for the Refmods panel, which has no event to follow."""
        state = getattr(self.plugin, "state", None)
        inputs = [state if state is not None else gr.State({})] + self._present_media()

        def refresh(st, *values, _last=None):
            blob = self._read_media(st, values)
            return [blob] + render(blob)

        def refresh_if_changed(st, last, *values):
            blob = self._read_media(st, values)
            signature = json.dumps(blob, sort_keys=True, default=str)
            if signature == last:
                return [gr.update(), last] + [gr.update()] * len(outputs)
            return [blob, signature] + render(blob)

        for comp in self._present_media():
            try:
                comp.change(fn=refresh, inputs=inputs, outputs=[media_state] + outputs, show_progress="hidden")
            except Exception:                          # noqa: BLE001
                pass
        if hasattr(gr, "Timer"):
            timer = gr.Timer(3)
            timer.tick(fn=refresh_if_changed, inputs=[inputs[0], sig] + inputs[1:],
                       outputs=[media_state, sig] + outputs, show_progress="hidden")
        for trigger in (getattr(self.plugin, "refresh_form_trigger", None),
                        getattr(self.plugin, "model_choice_target", None)):
            if trigger is not None:
                try:
                    trigger.change(fn=refresh, inputs=inputs, outputs=[media_state] + outputs,
                                   show_progress="hidden")
                except Exception:                      # noqa: BLE001
                    pass

    # -- the tab -------------------------------------------------------------

    def build_tab(self):
        p = self.plugin
        with gr.Column() as root:
            warning = gr.Markdown(visible=False)
            with gr.Row(equal_height=True):
                mode = gr.Radio([core.AUTO] + list(core.MODES), value=core.AUTO, label="Mode",
                                info="Auto picks the mode from what's loaded on the Generator page.", scale=3)
                duration = gr.Number(10, label="Length (s)", precision=2, minimum=1, maximum=60, scale=0,
                                     min_width=110)
            mode_line = gr.Markdown("")
            with gr.Row():
                insert_btn = gr.Button("Insert into prompt", variant="primary", size="sm")
                append_btn = gr.Button("Append window", size="sm")
                append_cut_btn = gr.Button("Append as new scene", size="sm")
                save_name = gr.Textbox(show_label=False, placeholder="Prompt name", scale=2, min_width=140)
                save_btn = gr.Button("Save prompt", size="sm")
                load_pick = gr.Dropdown(self._prompt_choices(), show_label=False, scale=2, min_width=160,
                                        allow_custom_value=True)
                load_btn = gr.Button("Load", size="sm")
                restore_btn = gr.Button("Restore draft", size="sm")
                clear_btn = gr.Button("Clear", size="sm")
            status = gr.Markdown(self._draft_note())
            gr.Markdown("**What this generation sends** · click a label to insert it at the cursor")
            chips = gr.HTML(self._chips_html([]))
            media_state = gr.State({})
            sig = gr.State("")

            with gr.Row():
                with gr.Column(scale=3, min_width=520):
                    subjects = gr.State([])
                    with gr.Group():
                        gr.Markdown("**Subjects** · each can use a picture, a mod, or just its description. "
                                    "In Reference mode they write subject_definitions and retention_analysis.")
                        cards = gr.Markdown("*No subjects yet: press **+ Add subject**.*")
                        with gr.Row():
                            pick = gr.Dropdown([], label="Editing", scale=2, min_width=160)
                            add_btn = gr.Button("+ Add subject", size="sm")
                            up_btn = gr.Button("↑", size="sm", min_width=40, scale=0)
                            down_btn = gr.Button("↓", size="sm", min_width=40, scale=0)
                            remove_btn = gr.Button("Remove", size="sm")
                        with gr.Row():
                            lib_pick = gr.Dropdown(self._subject_choices(), label="Saved subjects", scale=2,
                                                   min_width=160, allow_custom_value=True)
                            lib_load = gr.Button("Load into this subject", size="sm")
                            lib_save = gr.Button("Save to library", size="sm")
                        with gr.Row():
                            f_kind = gr.Dropdown(list(core.KINDS), value="Character", label="Kind", min_width=110)
                            f_name = gr.Textbox(label="Name", min_width=110)
                            f_gender = gr.Dropdown(list(core.GENDERS), value="", label="Gender", min_width=100)
                            f_age = gr.Textbox(label="Age", placeholder="34, thirties, young", min_width=100)
                            f_ethnicity = gr.Textbox(label="Ethnicity", min_width=100)
                        with gr.Row():
                            f_height = gr.Textbox(label="Height", min_width=100)
                            f_build = gr.Textbox(label="Build", min_width=100)
                            f_hairstyle = gr.Textbox(label="Hairstyle", min_width=100)
                            f_haircolor = gr.Textbox(label="Hair colour", min_width=100)
                            f_eyecolor = gr.Textbox(label="Eye colour", min_width=100)
                        f_clothing = gr.Textbox(label="Clothing")
                        f_details = gr.Textbox(label="Anything else the camera sees",
                                               info="For a location, prop or style, describe it here.")
                        with gr.Row():
                            f_look = gr.Dropdown([], multiselect=True, label="Look comes from",
                                                 info="Pictures or mods. Leave empty for description only.")
                            f_voice = gr.Dropdown([("nothing: gender and tone only", "")], value="",
                                                  label="Voice comes from")
                            f_accent = gr.Textbox(label="Accent (only if wanted)", placeholder="Irish")
                        with gr.Row():
                            f_parts = gr.CheckboxGroup(list(core.PARTS), value=list(core.DEFAULT_PARTS),
                                                       label="Taken from the picture",
                                                       info="Leave clothing unticked when it comes from the "
                                                            "description (partially preserved).")
                            f_sheet = gr.Checkbox(False, label="It's a multi-view reference sheet")
                    fields = [f_kind, f_name, f_gender, f_age, f_ethnicity, f_height, f_build, f_hairstyle,
                              f_haircolor, f_eyecolor, f_clothing, f_details, f_look, f_parts, f_sheet, f_voice,
                              f_accent]
                    field_keys = ["kind", "name", "gender", "age", "ethnicity", "height", "build", "hairstyle",
                                  "haircolor", "eyecolor", "clothing", "details", "look", "parts", "sheet",
                                  "voice", "accent"]

                    with gr.Group():
                        gr.Markdown("**Insert** · goes in wherever you were last typing (the Action box if "
                                    "you haven't clicked into one)")
                        with gr.Row():
                            at = gr.Number(0, label="At (s)", precision=3, minimum=0, scale=0, min_width=90)
                            shot_btn = gr.Button("Shot", size="sm")
                            cam_move = gr.Dropdown(list(core.CAMERA_MOVES), value="Push In", label="Camera",
                                                   min_width=130)
                            cam_amp = gr.Dropdown(list(core.AMPLITUDES), value="", label="Amplitude", min_width=130)
                            cam_speed = gr.Dropdown(list(core.SPEEDS), value="", label="Speed", min_width=110)
                            cam_btn = gr.Button("Camera", size="sm")
                            subj_pick = gr.Dropdown([], label="Subject", min_width=130)
                            subj_btn = gr.Button("Subject", size="sm")
                        with gr.Row():
                            d_who = gr.Dropdown([], label="Speaker", min_width=130)
                            d_tone = gr.Textbox(label="Tone", placeholder="quiet, relieved", min_width=120)
                            d_lang = gr.Dropdown(list(core.LANGUAGES), value="English", label="Language",
                                                 allow_custom_value=True, min_width=110)
                            d_vo = gr.Checkbox(False, label="Voiceover")
                            d_line = gr.Textbox(label="Line, word for word", scale=3)
                            d_btn = gr.Button("Insert line", size="sm")
                        snippet = gr.Textbox(visible=False)

                    summary = gr.Textbox(label="Summary (Reference mode) · one or two sentences: who, where, "
                                               "the situation", lines=1)
                    style = gr.Textbox(label="Style · stays the same for the whole clip",
                                       placeholder="Live-action, cinematic, 35mm, teal and amber grade, night", lines=1)
                    with gr.Row():
                        gr.Markdown("**Action**")
                        think = gr.Checkbox(False, label="Think (Qwen enhancers)", scale=0, min_width=200)
                        act_enh = gr.Button("Enhance", size="sm", scale=0, min_width=90)
                        act_undo = gr.Button("Undo", size="sm", scale=0, min_width=70)
                    action = gr.Textbox(show_label=False, lines=8, elem_id="rs-action",
                                        placeholder="[Shot 1] ... Use the Insert buttons for shots, camera moves, "
                                                    "subjects and lines.")
                    with gr.Row():
                        with gr.Column():
                            with gr.Row():
                                gr.Markdown("**Sound** · ambience and effects, never voices")
                                snd_enh = gr.Button("Enhance", size="sm", scale=0, min_width=90)
                                snd_undo = gr.Button("Undo", size="sm", scale=0, min_width=70)
                            sound = gr.Textbox(show_label=False, lines=2)
                        with gr.Column():
                            with gr.Row():
                                gr.Markdown("**Music** · N/A unless you want a score")
                                mus_enh = gr.Button("Enhance", size="sm", scale=0, min_width=90)
                                mus_undo = gr.Button("Undo", size="sm", scale=0, min_width=70)
                            music = gr.Textbox(show_label=False, lines=2, value="N/A")
                    progress = self._progress_component()
                    enh_status = gr.Markdown("")
                    undo_action, undo_sound, undo_music = gr.State(""), gr.State(""), gr.State("")

                with gr.Column(scale=2, min_width=400):
                    preview = gr.Textbox(label="Live preview · labels as predicted; the console prints the real ones",
                                         lines=24, max_lines=40, interactive=False, show_copy_button=True)
                    checks = gr.Markdown("")
                    writer = self._build_writer()

        # ---- wiring -------------------------------------------------------------
        form_inputs = [mode, duration, summary, style, action, sound, music, subjects]
        self._wire_media(media_state, sig, [chips, f_look, f_voice], self._tab_refresh)

        def update_preview(blob, *values):
            media, model = self._unpack_media(blob)
            form = self._form(*values)
            resolved, detected = self._resolve_mode(form["mode"], media)
            text = core.assemble(form, media, resolved)
            result = core.checks(form, media, resolved, text, detected, model, self._lint())
            line = f"Picked from the Generator page: {core.media_summary(media)} → **{detected}**."
            if form["mode"] != core.AUTO:
                line += f" Overridden: writing **{resolved}**."
            if model and not model.get("h3"):
                line += " ⚠️ The selected model isn't MiniMax H3."
            return text, self._checks_md(result), line, self._chips_html(media, text)

        preview_outputs = [preview, checks, mode_line, chips]
        for comp in (mode, duration, summary, style, action, sound, music, subjects, media_state):
            comp.change(fn=update_preview, inputs=[media_state] + form_inputs, outputs=preview_outputs,
                        show_progress="hidden")

        # Subjects.
        subj_outputs = [subjects, pick, cards, subj_pick, d_who]

        def lists(subs, index):
            choices = [(f"{n} · {core.display_name(s, n)}", n) for n, s in enumerate(subs, 1)]
            lines = []
            for n, s in enumerate(subs, 1):
                look = "picture or mod" if s.get("look") else "description only"
                voice = "with a voice" if s.get("voice") else "gender and tone"
                lines.append(f"**{n} · {core.display_name(s, n)}** ({s.get('kind')}) · look: {look} · voice: {voice}")
            card = "  \n".join(lines) or "*No subjects yet: press **+ Add subject**.*"
            value = index if subs else None
            return (gr.update(choices=choices, value=value), card, gr.update(choices=choices, value=value),
                    gr.update(choices=choices, value=value))

        def field_values(subs, index):
            s = subs[index - 1] if subs and 1 <= (index or 0) <= len(subs) else core.new_subject()
            return [s.get(k) for k in field_keys]

        def on_fields(subs, index, *values):
            subs = [dict(s) for s in (subs or [])]
            if not subs or not index or not (1 <= int(index) <= len(subs)):
                return [subs, gr.update(), gr.update(), gr.update(), gr.update()]
            subs[int(index) - 1] = core.clean_subject(dict(zip(field_keys, values)))
            return [subs, *lists(subs, int(index))]

        for comp in fields:
            comp.input(fn=on_fields, inputs=[subjects, pick] + fields, outputs=subj_outputs, show_progress="hidden")

        def on_pick(subs, index):
            return field_values(subs or [], index)

        pick.input(fn=on_pick, inputs=[subjects, pick], outputs=fields)

        def on_add(subs):
            subs = list(subs or []) + [core.new_subject()]
            return [subs, *lists(subs, len(subs))] + field_values(subs, len(subs))

        def on_move(subs, index, step):
            subs = list(subs or [])
            if not subs or not index:
                return [subs, *lists(subs, index)] + field_values(subs, index)
            i = int(index) - 1
            j = max(0, min(len(subs) - 1, i + step))
            subs[i], subs[j] = subs[j], subs[i]
            return [subs, *lists(subs, j + 1)] + field_values(subs, j + 1)

        def on_remove(subs, index):
            subs = list(subs or [])
            if subs and index and 1 <= int(index) <= len(subs):
                subs.pop(int(index) - 1)
            new = min(int(index or 1), len(subs)) if subs else None
            return [subs, *lists(subs, new)] + field_values(subs, new)

        add_btn.click(fn=on_add, inputs=[subjects], outputs=subj_outputs + fields)
        up_btn.click(fn=lambda s, i: on_move(s, i, -1), inputs=[subjects, pick], outputs=subj_outputs + fields)
        down_btn.click(fn=lambda s, i: on_move(s, i, 1), inputs=[subjects, pick], outputs=subj_outputs + fields)
        remove_btn.click(fn=on_remove, inputs=[subjects, pick], outputs=subj_outputs + fields)

        def on_lib_save(subs, index):
            if not subs or not index:
                return gr.update(), "Pick a subject to save first."
            s = subs[int(index) - 1]
            name = _clean_name(s.get("name"))
            if not name:
                return gr.update(), "Give the subject a name first."
            path = _data_dir() / "subjects" / f"{name}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            existed = path.exists()
            _write_json(path, {"kind": "subject", "format": 5, "saved": time.strftime("%Y-%m-%d %H:%M"),
                               "name": name, "subject": {k: s.get(k) for k in core.LIBRARY_KEYS}})
            return (gr.update(choices=self._subject_choices(), value=name),
                    f"{'Replaced' if existed else 'Saved'} **{name}** in the library. Its pictures and voice "
                    "aren't saved, since they belong to this project.")

        def on_lib_load(subs, index, name):
            subs = [dict(s) for s in (subs or [])]
            path = _data_dir() / "subjects" / f"{_clean_name(name)}.json"
            try:
                loaded = core.subject_from_library(json.loads(path.read_text(encoding="utf-8")))
            except Exception:                          # noqa: BLE001
                return [subs, *lists(subs, index)] + field_values(subs, index) + [f"Could not read **{name}**."]
            if not subs or not index:
                subs.append(loaded)
                index = len(subs)
            else:
                keep = subs[int(index) - 1]
                loaded["look"], loaded["voice"] = keep.get("look") or [], keep.get("voice") or ""
                subs[int(index) - 1] = loaded
            return [subs, *lists(subs, int(index))] + field_values(subs, int(index)) + [f"Loaded **{name}**."]

        lib_save.click(fn=on_lib_save, inputs=[subjects, pick], outputs=[lib_pick, status])
        lib_load.click(fn=on_lib_load, inputs=[subjects, pick, lib_pick], outputs=subj_outputs + fields + [status])

        # Insert buttons: the snippet is worked out here, then put at the cursor.
        def media_of(blob):
            return self._unpack_media(blob)[0]

        def resolved_mode(m, blob):
            return self._resolve_mode(m, media_of(blob))[0]

        shot_btn.click(fn=lambda a, t: core.shot_snippet(a, t), inputs=[action, at], outputs=[snippet]) \
            .then(fn=None, inputs=[snippet], js=INSERT_AFTER)
        cam_btn.click(fn=core.camera_snippet, inputs=[cam_move, cam_amp, cam_speed], outputs=[snippet]) \
            .then(fn=None, inputs=[snippet], js=INSERT_AFTER)
        subj_btn.click(fn=lambda subs, i, m, b, a: core.subject_snippet(subs or [], int(i or 0), resolved_mode(m, b), a),
                       inputs=[subjects, subj_pick, mode, media_state, action], outputs=[snippet]) \
            .then(fn=None, inputs=[snippet], js=INSERT_AFTER)
        d_btn.click(fn=lambda subs, i, b, m, a, tone, lang, vo, line, t: core.dialogue_snippet(
                        subs or [], int(i or 0), media_of(b), resolved_mode(m, b), a, tone, lang, vo, line, t),
                    inputs=[subjects, d_who, media_state, mode, action, d_tone, d_lang, d_vo, d_line, at],
                    outputs=[snippet]) \
            .then(fn=None, inputs=[snippet], js=INSERT_AFTER)

        # Into the prompt box.
        prompt = getattr(p, "prompt", None)

        def build_text(blob, *values):
            media, _ = self._unpack_media(blob)
            form = self._form(*values)
            return core.assemble(form, media, self._resolve_mode(form["mode"], media)[0])

        if prompt is not None:
            insert_btn.click(fn=lambda b, *v: (build_text(b, *v), "Prompt replaced."),
                             inputs=[media_state] + form_inputs, outputs=[prompt, status])
            append_btn.click(fn=lambda cur, b, *v: self._append(cur, build_text(b, *v), cut=False),
                             inputs=[prompt, media_state] + form_inputs, outputs=[prompt, status])
            append_cut_btn.click(fn=lambda cur, b, *v: self._append(cur, build_text(b, *v), cut=True),
                                 inputs=[prompt, media_state] + form_inputs, outputs=[prompt, status])

        # Saving, loading, the draft.
        load_outputs = form_inputs + [pick, cards, subj_pick, d_who] + fields + [status]

        def apply(form, note):
            form = core.clean_form(form)
            subs = form["subjects"]
            index = 1 if subs else None
            return [form[k] for k in core.FORM_KEYS] + list(lists(subs, index)) + field_values(subs, index) + [note]

        save_btn.click(fn=self._save_prompt, inputs=[save_name] + form_inputs, outputs=[load_pick, status])
        load_btn.click(fn=lambda name: apply(*self._load_prompt(name)), inputs=[load_pick], outputs=load_outputs)
        restore_btn.click(fn=lambda: apply(*self._load_draft()), inputs=[], outputs=load_outputs)
        clear_btn.click(fn=lambda: apply(core.new_form(), "Cleared."), inputs=[], outputs=load_outputs) \
            .then(fn=self._save_draft, inputs=form_inputs, outputs=[status])
        if hasattr(gr, "Timer"):
            gr.Timer(20).tick(fn=self._autosave, inputs=form_inputs, outputs=[status], show_progress="hidden")
        for button in (insert_btn, append_btn, append_cut_btn):
            button.click(fn=self._autosave, inputs=form_inputs, outputs=[status])

        # Enhancers.
        state = getattr(p, "state", None) or gr.State({})
        self._bind_enhancer(act_enh, "action", progress, [state, media_state, think] + form_inputs,
                            [action, undo_action, enh_status])
        self._bind_enhancer(snd_enh, "sound", progress, [state, media_state, think] + form_inputs,
                            [sound, undo_sound, enh_status])
        self._bind_enhancer(mus_enh, "music", progress, [state, media_state, think] + form_inputs,
                            [music, undo_music, enh_status])
        for button, box, keep in ((act_undo, action, undo_action), (snd_undo, sound, undo_sound),
                                  (mus_undo, music, undo_music)):
            button.click(fn=lambda old, cur: (old, cur) if old else (cur, old), inputs=[keep, box],
                         outputs=[box, keep])
        if writer is not None:
            self._wire_writer(writer, state, media_state, form_inputs)

        try:
            p._wire_model_visibility(root, warning, inline=False)
        except Exception as exc:                       # noqa: BLE001
            print(f"[Refmods Studio] builder tab visibility not wired: {exc!r}")
        return root

    def _tab_refresh(self, blob):
        media, _ = self._unpack_media(blob)
        looks = [(f"{m.label_text} · {m.name}", m.key) for m in media if m.kind in ("picture", "video")
                 and m.role not in ("start", "continue", "end")]
        voices = [("nothing: gender and tone only", "")] + [(f"{m.label_text} · {m.name}", m.key)
                                                            for m in media if m.kind == "audio"]
        return [self._chips_html(media), gr.update(choices=looks), gr.update(choices=voices)]

    @staticmethod
    def _append(current, text, cut):
        current = (current or "").rstrip()
        if not text.strip():
            return current, "Nothing to append yet."
        if not current:
            return text, "First window written."
        joined = current + "\n\n" + ("[/new_shot] " if cut else "") + text
        windows = joined.count("\n\n") + 1
        return joined, (f"Appended as window {windows}. Set *How to Process each Line of the Text Prompt* to the "
                        "paragraph-per-sliding-window option.")

    # -- files ---------------------------------------------------------------

    @staticmethod
    def _files(folder):
        try:
            items = [p for p in (_data_dir() / folder).glob("*.json") if p.is_file()]
        except Exception:                              # noqa: BLE001
            return []
        return sorted(items, key=lambda p: p.stat().st_mtime, reverse=True)

    def _prompt_choices(self):
        return [p.stem for p in self._files("prompts")[:25]]

    def _subject_choices(self):
        return [p.stem for p in self._files("subjects")[:50]]

    def _save_prompt(self, name, *values):
        filename = _clean_name(name)
        if not filename:
            return gr.update(), "Give the prompt a name first."
        form = self._form(*values)
        path = _data_dir() / "prompts" / f"{filename}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        _write_json(path, {"format": 5, "saved": time.strftime("%Y-%m-%d %H:%M"), "name": filename, "form": form})
        return (gr.update(choices=self._prompt_choices(), value=filename),
                f"{'Replaced' if existed else 'Saved'} **{filename}**.")

    def _form_from_blob(self, blob):
        """A saved form from this builder, or a 4.x one mapped across."""
        if isinstance(blob, dict) and isinstance(blob.get("form"), dict):
            return core.clean_form(blob["form"]), ""
        values, _ = self.plugin._values_from_blob(blob)
        if values is None:
            return None, ""
        return core.form_from_v4(self.plugin._unpack(values)), (
            " It was saved by the 4.x builder: the text and subjects came across, but check the subjects' "
            "pictures and voices.")

    def _load_prompt(self, name):
        filename = _clean_name(name)
        path = _data_dir() / "prompts" / f"{filename}.json"
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
            form, note = self._form_from_blob(blob)
        except Exception:                              # noqa: BLE001
            form, note = None, ""
        if form is None:
            return core.new_form(), f"Could not read **{filename}**; the form was cleared."
        return form, f"Loaded **{filename}**, saved {blob.get('saved', 'earlier')}." + note

    def _draft_path(self):
        return _data_dir() / "studio_draft.json"

    def _draft_note(self):
        try:
            blob = json.loads(self._draft_path().read_text(encoding="utf-8"))
            return f"Draft on disk from {blob.get('saved', 'earlier')}. **Restore draft** brings it back."
        except Exception:                              # noqa: BLE001
            return "The form is saved to disk as you work, so a crash doesn't cost the prompt."

    def _load_draft(self):
        try:
            blob = json.loads(self._draft_path().read_text(encoding="utf-8"))
            return core.clean_form(blob.get("form")), f"Restored the draft saved at {blob.get('saved', 'earlier')}."
        except Exception:                              # noqa: BLE001
            pass
        try:
            old = json.loads((_data_dir() / "h3_draft.json").read_text(encoding="utf-8"))
            form, note = self._form_from_blob(old)
            if form is not None:
                return form, "Restored the last 4.x draft." + note
        except Exception:                              # noqa: BLE001
            pass
        return core.new_form(), "No saved draft to restore."

    def _save_draft(self, *values):
        form = self._form(*values)
        if form == self._draft_cache["form"]:
            return gr.update()
        stamp = time.strftime("%H:%M:%S")
        try:
            path = self._draft_path()
            if path.exists():
                path.replace(path.with_name("studio_draft.prev.json"))
            _write_json(path, {"format": 5, "saved": stamp, "form": form})
        except Exception as exc:                       # noqa: BLE001
            return f"Could not save the draft ({type(exc).__name__})."
        self._draft_cache["form"] = form
        return f"Draft saved at {stamp}."

    def _autosave(self, *values):
        form = self._form(*values)
        empty = not any(_s(form[k]) for k in ("summary", "style", "action", "sound")) and not form["subjects"]
        if empty:
            return gr.update()
        return self._save_draft(*values)

    # -- the prompt enhancer ---------------------------------------------------

    @staticmethod
    def _progress_component():
        try:
            from shared.gradio.progress import WangpProgress
            return WangpProgress.component()
        except Exception:                              # noqa: BLE001
            return None

    def _bind_enhancer(self, button, part, progress, inputs, outputs):
        def run(state, blob, think, *values, progress=None):
            return self._enhance(part, state, blob, think, values, progress)
        try:
            from shared.gradio.progress import WangpProgress

            def run_wangp(state, blob, think, *values, progress=WangpProgress()):
                return self._enhance(part, state, blob, think, values, progress)
            if progress is not None:
                WangpProgress.bind(button.click, run_wangp, inputs=inputs, outputs=outputs, component=progress)
                return
        except Exception:                              # noqa: BLE001
            pass
        button.click(fn=run, inputs=inputs, outputs=outputs)

    def _context(self, form, media, mode):
        """What the enhancer is told about the subjects, style and labels."""
        lines = [f"MODE: {mode}. LENGTH: {float(form['duration']):g} seconds."]
        if mode == "Reference":
            defs = core.subject_definitions(form, media)
            if defs:
                lines.append("SUBJECTS AND REFERENCES (use these labels exactly, and write every spoken line as "
                             "<Subject N> (SN), in the voice following <Audio N>, ... when the subject has a "
                             "voice):\n" + defs)
        else:
            for n, s in enumerate(form["subjects"], 1):
                desc = core.describe(s)
                if desc:
                    lines.append(f"SUBJECT: {desc}.")
            lines.append("Write every spoken line as: <name> (SN), a woman/man speaking with a <tone> tone, says, "
                         "her/his lips moving: <d>[English] ...</d>. Never describe the type of voice.")
        if _s(form["style"]):
            lines.append(f"STYLE (stays the same for the whole clip): {_s(form['style'])}")
        return "\n".join(lines)

    def _enhance(self, part, state, blob, think, values, progress):
        keep = (gr.update(), gr.update())
        studio = getattr(self.plugin, "h3_studio", None)
        if studio is None:
            return (*keep, "The prompt enhancer isn't available, so nothing was written.")
        media, _ = self._unpack_media(blob)
        form = self._form(*values)
        mode = self._resolve_mode(form["mode"], media)[0]
        current = _s(form[part])
        context = self._context(form, media, mode)
        try:
            from .h3studio.modes import ACTION_ROLE, Target, detect_combat
            duration = float(form["duration"] or 0) or None
            if part == "action":
                from .h3studio.builder_panel import strip_to_action
                brief = studio.library.build_brief(
                    current or context, Target(mode="T2VA" if mode == "Reference" else mode, duration=duration,
                                               combat=detect_combat(current)),
                    budget_tokens=int(studio.settings.get("enhancer_budget_tokens", 10000)),
                    enabled_skills=studio.enabled_skills, contract="", purpose="action", role=ACTION_ROLE)
                system = (brief.text + "\n\nAnswer with the action body only. It starts at `[Shot 1]` and ends "
                          "with the last shot's sentence. Nothing before it, nothing after it.")
                request = (context + "\n\nWHAT THE USER TYPED IN THE ACTION BOX: expand this into the finished "
                           "action, keeping everything it asks for, its shots and its timings:\n"
                           + (current or "(nothing yet: write the action from the subjects above)"))
            elif part == "sound":
                system = ("You write the overall_soundscape field of a MiniMax H3 video prompt: 1 to 4 English "
                          "sentences in one paragraph covering ambient sound, physical action sounds and non-verbal "
                          "human sounds across the whole video. Mention an important synchronised sound beside its "
                          "action. Never mention voices, speech, dialogue, whispering or who speaks. Describe the mix "
                          "in relative words. Answer with the paragraph only, without the field name.")
                request = (context + "\n\nTHE ACTION:\n" + (_s(form["action"]) or "(not written yet)")
                           + "\n\nWHAT THE USER TYPED FOR THE SOUND:\n" + (current or "(nothing yet)"))
            else:
                system = ("You write the non_diegetic_music field of a MiniMax H3 video prompt: background music only "
                          "the audience hears, in 1 to 3 English sentences about instrumentation, tempo, rhythm and "
                          "dynamics, with no mood words. If the user typed N/A or asked for no music, answer N/A. "
                          "Answer with the text only, without the field name.")
                request = (context + "\n\nTHE ACTION:\n" + (_s(form["action"]) or "(not written yet)")
                           + "\n\nWHAT THE USER TYPED FOR THE MUSIC:\n" + (current or "(nothing yet)"))
            request = request.replace("@", "(at)")
            written = studio._run_enhancer(state, [request], {request: system}, None,
                                           studio.max_tokens("ref2va" if mode == "Reference" else "fl2va"),
                                           progress, bool(think))
        except Exception as exc:                       # noqa: BLE001
            return (*keep, f"Nothing written: {exc}")
        text = _s(written[0] if written else "")
        if part == "action":
            text = strip_to_action(text)
        else:
            for name in ("overall_soundscape:", "non_diegetic_music:"):
                if text.lower().startswith(name):
                    text = text[len(name):].strip()
        if not text:
            return (*keep, "The enhancer returned nothing usable, so the box is untouched.")
        return text, current, f"**{part.title()} written.** Read it through; **Undo** puts back what was there."

    def _build_writer(self):
        try:
            with gr.Accordion("Write it all with the prompt enhancer", open=False):
                gr.Markdown("Writes the whole prompt from an idea plus the subjects and style above, using the "
                            "prompt enhancer set in Configuration. One paragraph per sliding window, separated by "
                            "a blank line.")
                idea = gr.Textbox(lines=4, label="The idea")
                with gr.Row():
                    think = gr.Checkbox(False, label="Think (Qwen enhancers)")
                    write_btn = gr.Button("Write the prompt", variant="primary")
                progress = self._progress_component()
                output = gr.Textbox(lines=12, label="The written prompt (editable)", show_copy_button=True)
                report = gr.Markdown("")
                with gr.Row():
                    insert_btn = gr.Button("Insert into prompt", size="sm")
                    append_btn = gr.Button("Append window", size="sm")
            return {"idea": idea, "think": think, "write": write_btn, "progress": progress, "output": output,
                    "report": report, "insert": insert_btn, "append": append_btn}
        except Exception as exc:                       # noqa: BLE001
            print(f"[Refmods Studio] the full writer is unavailable: {exc!r}")
            return None

    def _wire_writer(self, w, state, media_state, form_inputs):
        def write(st, blob, idea, think, *values, progress=None):
            studio = getattr(self.plugin, "h3_studio", None)
            if studio is None:
                raise gr.Error("The prompt enhancer isn't available.")
            media, _ = self._unpack_media(blob)
            form = self._form(*values)
            mode = self._resolve_mode(form["mode"], media)[0]
            family = "ref2va" if mode == "Reference" else "fl2va"
            request = _s(idea) or _s(form["action"])
            if not request:
                raise gr.Error("Write an idea first, or some action in the form.")
            spec = self._context(form, media, mode)
            if _s(form["action"]) and _s(idea):
                spec += "\n\nALREADY WRITTEN, keep these shots and timings:\n" + _s(form["action"])
            try:
                outputs, targets, _ = studio.write(
                    st, request, [], family, float(form["duration"] or 0) or None,
                    "Ref2VA" if mode == "Reference" else mode, "auto", progress, bool(think), spec_text=spec,
                    plans=None, commands_enabled=False,
                    force_definitions=core.subject_definitions(form, media) if mode == "Reference" else "")
            except RuntimeError as exc:
                raise gr.Error(str(exc))
            text = "\n\n".join(outputs)
            lint = self._lint()
            report = ""
            if lint is not None:
                from .h3studio import lint as lint_mod
                report = lint_mod.format_report(lint(text, "Ref2VA" if mode == "Reference" else "auto",
                                                     None, len(outputs)))
            return text, report

        inputs = [state, media_state, w["idea"], w["think"]] + form_inputs
        try:
            from shared.gradio.progress import WangpProgress

            def write_wangp(st, blob, idea, think, *values, progress=WangpProgress()):
                return write(st, blob, idea, think, *values, progress=progress)
            if w["progress"] is not None:
                WangpProgress.bind(w["write"].click, write_wangp, inputs=inputs, outputs=[w["output"], w["report"]],
                                   component=w["progress"])
            else:
                w["write"].click(fn=write, inputs=inputs, outputs=[w["output"], w["report"]])
        except Exception:                              # noqa: BLE001
            w["write"].click(fn=write, inputs=inputs, outputs=[w["output"], w["report"]])
        prompt = getattr(self.plugin, "prompt", None)
        if prompt is not None:
            w["insert"].click(fn=lambda t: (t, "Prompt replaced."), inputs=[w["output"]],
                              outputs=[prompt, w["report"]])
            w["append"].click(fn=lambda cur, t: self._append(cur, t or "", cut=False),
                              inputs=[prompt, w["output"]], outputs=[prompt, w["report"]])
