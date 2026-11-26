"""
The Refmods Library web app's work: listing H3 and Flux mods, what each one
holds, previews, editing, copying, folders, and the jobs that need the model's
VAEs (decompile, strength preview, encoder frames, soundtracks, clean audio,
convert to Flux). The page (refmods/web) only draws; everything happens here.

A mod is named by an id, "h3:<name>" or "flux:<name>", where name is the
folder-relative path the storage modules use ("characters/tanya").
"""

from __future__ import annotations

import gc
import io
import json
import os
import shutil
import threading
import time
import traceback
import uuid

from PIL import Image

from . import core, flux, storage

AUDIO_LATENTS_PER_SECOND = 40
FPS = 24
THUMB_EDGE = 360
PREVIEW_EDGE = 768
MAX_UPLOAD = 400 * 1024 * 1024


# -- ids and paths ---------------------------------------------------------------

def split_id(mod_id):
    model, _, name = str(mod_id or "").partition(":")
    if model not in ("h3", "flux") or not name:
        raise ValueError(f"not a mod id: {mod_id!r}")
    return model, name


def make_id(model, name):
    return f"{model}:{name}"


def mod_file(model, name):
    return flux.mod_path(name) if model == "flux" else storage.mod_path(name) + ".safetensors"


def plugin_root():
    return os.path.dirname(storage.refmods_dir())       # loras/refmods_plugin


def previews_dir(model):
    return os.path.join(plugin_root(), "previews", model)


def preview_file(model, name):
    return os.path.join(previews_dir(model), *name.split("/")) + ".jpg"


def uploads_dir():
    d = os.path.join(plugin_root(), "uploads")
    os.makedirs(d, exist_ok=True)
    return d


def strength_dir(name, create=False):
    d = os.path.join(storage.decompile_dir(name, create=create), "strength")
    if create:
        os.makedirs(d, exist_ok=True)
    return d


def _within(path, root):
    path, root = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(root))
    return path == root or path.startswith(root + os.sep)


# -- reading ---------------------------------------------------------------------

def _h3_header(name):
    """(meta, tensor keys) without loading the tensors."""
    from safetensors import safe_open
    with safe_open(storage.mod_path(name) + ".safetensors", framework="numpy") as f:
        raw = f.metadata() or {}
        keys = list(f.keys())
    return json.loads(raw.get(core.META_KEY) or "null"), keys


def _enc_jpeg(name, index):
    from safetensors import safe_open
    with safe_open(storage.mod_path(name) + ".safetensors", framework="numpy") as f:
        key = f"enc_{int(index)}"
        if key not in f.keys():
            return None
        return bytes(f.get_tensor(key).tobytes())


def _packs_by_mod():
    out = {}
    for pack_name in storage.list_packs():
        pack = storage.read_pack(pack_name) or {}
        for member in pack.get("members") or []:
            out.setdefault(member.get("mod"), []).append(pack_name)
    return out


def _h3_item(name, packs):
    meta, keys = _h3_header(name)
    if meta is None:
        return None
    kind = meta.get("kind", "image")
    latent_h, latent_w = int(meta.get("latent_h", 0)), int(meta.get("latent_w", 0))
    latent_t = int(meta.get("latent_t", 1))
    if kind == "video" and core.is_still_stack("video", latent_t, meta.get("tags"), meta.get("source", "")):
        kind = "image"
    frames = len([k for k in keys if k.startswith("enc_")])
    has_audio = kind == "audio" or bool(meta.get("has_audio")) or core.AUDIO_LATENT_KEY in keys
    if kind == "audio":
        tokens = latent_t * 2
        length = f"{latent_t / AUDIO_LATENTS_PER_SECOND:.1f}s"
    else:
        tokens = (latent_h // 2) * (latent_w // 2) * latent_t + int(meta.get("audio_t", 0)) * 2
        length = (f"{latent_t} picture{'s' if latent_t != 1 else ''}" if kind == "image"
                  else f"{((latent_t - 1) * 4 + 1) / FPS:.1f}s")
    path = storage.mod_path(name) + ".safetensors"
    folder, leaf = (name.rpartition("/")[0], name.rpartition("/")[2])
    return {
        "id": make_id("h3", name), "model": "h3", "name": name, "folder": folder, "leaf": leaf,
        "kind": kind, "mode": meta.get("mode", "?"), "tokens": tokens, "length": length,
        "size_mb": round(os.path.getsize(path) / (1024 * 1024), 2), "mtime": os.path.getmtime(path),
        "concept": meta.get("concept_type") or "generic", "description": meta.get("description") or "",
        "has_audio": has_audio, "frames": frames, "packs": packs.get(name, []),
        "custom_preview": os.path.isfile(preview_file("h3", name)), "usable": True,
        "thumb": bool(frames) or os.path.isfile(preview_file("h3", name)),
    }


def _flux_item(name):
    meta = flux.read_meta(name)
    if meta is None:
        return None
    path = flux.mod_path(name)
    folder, leaf = (name.rpartition("/")[0], name.rpartition("/")[2])
    pictures = int(meta.get("pictures") or 1)
    return {
        "id": make_id("flux", name), "model": "flux", "name": name, "folder": folder, "leaf": leaf,
        "kind": "image", "mode": meta.get("mode", "encode"), "tokens": meta.get("tokens", 0),
        "length": f"{pictures} picture{'s' if pictures != 1 else ''}",
        "size_mb": meta.get("size_mb", 0), "mtime": os.path.getmtime(path),
        "concept": meta.get("concept_type") or "generic", "description": meta.get("description") or "",
        "has_audio": False, "frames": 0, "packs": [],
        "custom_preview": os.path.isfile(preview_file("flux", name)),
        "usable": bool(meta.get("usable", True)), "thumb": os.path.isfile(preview_file("flux", name)),
    }


def list_items():
    packs = _packs_by_mod()
    items = []
    for name in storage.list_refmods(recursive=True):
        try:
            item = _h3_item(name, packs)
            if item:
                items.append(item)
        except Exception as exc:                                    # noqa: BLE001
            print(f"[Refmods] Library could not read {name}: {exc!r}")
    for name in flux.list_mods():
        try:
            item = _flux_item(name)
            if item:
                items.append(item)
        except Exception as exc:                                    # noqa: BLE001
            print(f"[Refmods] Library could not read Flux/{name}: {exc!r}")
    return items


def folders():
    return {"h3": storage.list_mod_folders(), "flux": flux.list_folders()}


def details(mod_id):
    model, name = split_id(mod_id)
    if model == "flux":
        meta = flux.read_meta(name)
        if meta is None:
            raise FileNotFoundError(name)
        item = _flux_item(name)
        facts = [("Model", "Flux 2"), ("Pictures", str(meta.get("pictures", "?"))),
                 ("Tokens", f"{int(meta.get('tokens') or 0):,}"), ("Mode", meta.get("mode", "encode")),
                 ("Size", f"{item['size_mb']} MB")]
        if meta.get("converted_from"):
            facts.append(("Converted from", f"H3 · {meta['converted_from']}"))
        if not item["usable"]:
            facts.append(("Warning", "not a Flux 2 latent, so it won't load"))
        return {"item": item, "facts": facts, "frames": [], "tags": [], "outputs": _outputs(model, name),
                "strength": []}
    meta, keys = _h3_header(name)
    if meta is None:
        raise FileNotFoundError(name)
    item = _h3_item(name, _packs_by_mod())
    kind = item["kind"]
    latent_h, latent_w = int(meta.get("latent_h", 0)), int(meta.get("latent_w", 0))
    latent_t = int(meta.get("latent_t", 1))
    facts = [("Model", "MiniMax H3"), ("Kind", kind), ("Tokens", f"{item['tokens']:,}")]
    counts = next((c for c in (core.parse_source_counts(t) for t in meta.get("tags") or []) if c), None)
    if counts:
        made = [f"{counts[0]} picture{'s' if counts[0] != 1 else ''}"] if counts[0] else []
        made += [f"{counts[1]} video{'s' if counts[1] != 1 else ''}"] if counts[1] else []
        if made:
            facts.append(("Made from", " and ".join(made)))
    if kind == "audio":
        facts.append(("Audio", item["length"]))
    else:
        px = f"{latent_w * 16}x{latent_h * 16}px"
        mode = core.normalize_mode(meta.get("mode", "training"))
        facts.append(("Mode", f"encode, full detail at {px}" if mode == "encode"
                      else f"training, pooled to {latent_h}x{latent_w} (soft at {px})"))
        facts.append(("Pictures" if kind == "image" else "Video",
                      item["length"] + (" (one merged picture)" if meta.get("source") == "merge" else "")
                      if kind == "image" else f"{latent_t} latent frames, {item['length']}"))
        if meta.get("audio_t"):
            facts.append(("Soundtrack", f"{int(meta['audio_t']) / AUDIO_LATENTS_PER_SECOND:.1f}s"))
        if item["frames"]:
            layout = "one per picture" if meta.get("enc_layout") == core.ENC_LAYOUT_STILLS else "from the clip"
            facts.append(("Encoder frames", f"{item['frames']} stored, {layout}, "
                                            f"long edge {meta.get('enc_max_edge', 512)}px"))
        else:
            facts.append(("Encoder frames", "not stored, so they're decoded every session"))
    facts.append(("Size", f"{item['size_mb']} MB"))
    if meta.get("source"):
        facts.append(("Source", str(meta["source"])))
    times = meta.get("enc_times") or []
    frames = [{"index": i, "label": (f"picture {i + 1}" if meta.get("enc_layout") == core.ENC_LAYOUT_STILLS
                                     else f"{float(times[i]):.1f}s" if i < len(times) else str(i + 1))}
              for i in range(item["frames"])]
    tags = [t for t in meta.get("tags") or [] if core.parse_source_counts(t) is None]
    return {"item": item, "facts": facts, "frames": frames, "tags": tags, "outputs": _outputs(model, name),
            "strength": _strength_outputs(name)}


def _outputs(model, name):
    if model != "h3":
        return {"pictures": [], "videos": [], "audios": []}
    pictures, videos, audios = storage.list_decompiled(name)
    rel = lambda p: os.path.basename(p)
    return {"pictures": [rel(p) for p in pictures], "videos": [rel(p) for p in videos],
            "audios": [rel(p) for p in audios]}


def _strength_outputs(name):
    d = strength_dir(name)
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d)):
        if f.startswith("strength_") and f.endswith(".png"):
            out.append({"file": f, "strength": f[len("strength_"):-4]})
    return out


def output_path(mod_id, filename, strength=False):
    model, name = split_id(mod_id)
    base = strength_dir(name) if strength else storage.decompile_dir(name)
    path = os.path.join(base, os.path.basename(filename))
    return path if _within(path, base) and os.path.isfile(path) else None


# -- pictures ------------------------------------------------------------------------

_thumbs = {}
_thumbs_lock = threading.Lock()


def _jpeg(image, edge, quality=88):
    image = image.convert("RGB")
    image.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def thumb(mod_id, big=False):
    model, name = split_id(mod_id)
    custom = preview_file(model, name)
    source = custom if os.path.isfile(custom) else (mod_file(model, name) if model == "h3" else None)
    if not source or not os.path.isfile(source):
        return None
    key = (source, os.path.getmtime(source), big)
    with _thumbs_lock:
        if key in _thumbs:
            return _thumbs[key]
    if source == custom:
        data = _jpeg(Image.open(custom), PREVIEW_EDGE if big else THUMB_EDGE)
    else:
        raw = _enc_jpeg(name, 0)
        if raw is None:
            return None
        data = raw if big else _jpeg(Image.open(io.BytesIO(raw)), THUMB_EDGE)
    with _thumbs_lock:
        if len(_thumbs) > 600:
            _thumbs.clear()
        _thumbs[key] = data
    return data


def frame(mod_id, index):
    model, name = split_id(mod_id)
    return _enc_jpeg(name, index) if model == "h3" else None


def set_preview(mod_id, data):
    model, name = split_id(mod_id)
    image = Image.open(io.BytesIO(data))
    image.load()
    path = preview_file(model, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(_jpeg(image, PREVIEW_EDGE, 92))
    return {"ok": True, "message": "Preview replaced. The mod itself is unchanged."}


def set_preview_from_output(mod_id, filename, strength=False):
    path = output_path(mod_id, filename, strength)
    if not path:
        raise FileNotFoundError(filename)
    with open(path, "rb") as handle:
        return set_preview(mod_id, handle.read())


def clear_preview(mod_id):
    model, name = split_id(mod_id)
    path = preview_file(model, name)
    if os.path.isfile(path):
        os.remove(path)
    return {"ok": True, "message": "Back to the mod's own first frame."}


# -- editing ---------------------------------------------------------------------------

def _rewrite_h3(name, updates):
    """Change an H3 mod's metadata in place; the latents are copied untouched."""
    from safetensors import safe_open
    from safetensors.torch import load_file, save_file
    path = storage.mod_path(name) + ".safetensors"
    with safe_open(path, framework="numpy") as f:
        raw = dict(f.metadata() or {})
    meta = json.loads(raw.get(core.META_KEY) or "{}")
    meta.update(updates)
    raw[core.META_KEY] = json.dumps(meta)
    loaded = load_file(path, device="cpu")
    tensors = {k: v.clone() for k, v in loaded.items()}
    del loaded
    gc.collect()
    tmp = path + ".tmp"
    save_file(tensors, tmp, metadata=raw)
    os.replace(tmp, path)


def _follow(model, old, new, copy=False):
    """A renamed or copied mod keeps its preview; a renamed one stays in its packs."""
    old_preview, new_preview = preview_file(model, old), preview_file(model, new)
    if os.path.isfile(old_preview):
        os.makedirs(os.path.dirname(new_preview), exist_ok=True)
        (shutil.copy2 if copy else shutil.move)(old_preview, new_preview)
    if copy or model != "h3" or old == new:
        return
    for pack_name in storage.list_packs():
        pack = storage.read_pack(pack_name) or {}
        members = pack.get("members") or []
        if any(m.get("mod") == old for m in members):
            for m in members:
                if m.get("mod") == old:
                    m["mod"] = new
            storage.write_pack(pack)


def save(mod_id, new_name=None, description=None, concept=None):
    model, name = split_id(mod_id)
    typed = str(new_name or "").strip().replace("\\", "/")
    final = name
    if model == "flux":
        if typed and typed != name:
            final = flux.rename_and_update(name, new_name="/" + typed.lstrip("/"), description=description)
        elif description is not None:
            final = flux.rename_and_update(name, description=description)
        if concept:
            flux._rewrite(final, final, {"concept_type": concept})
    else:
        typed = typed.strip("/")
        if typed and typed != name:
            folder, _, leaf = typed.rpartition("/")
            if folder:
                storage.create_mod_folder(folder)
            final = storage.rename_and_update_mod(name, new_name=leaf, new_description=description,
                                                  new_folder=folder)
        elif description is not None:
            final = storage.rename_and_update_mod(name, new_description=description)
        if concept:
            _rewrite_h3(final, {"concept_type": concept})
    _follow(model, name, final)
    return {"ok": True, "id": make_id(model, final),
            "message": f"Saved as '{final}'." if final != name else "Saved."}


def copy(mod_id):
    model, name = split_id(mod_id)
    if model == "flux":
        target = flux.free_name(name)
        shutil.copy2(flux.mod_path(name), flux.mod_path(target))
        flux._rewrite(target, target, {"name": target.split("/")[-1]})
    else:
        target = storage.free_mod_name(name, "_copy")
        shutil.copy2(storage.mod_path(name) + ".safetensors", storage.mod_path(target) + ".safetensors")
        _rewrite_h3(target, {"name": target.split("/")[-1]})
    _follow(model, name, target, copy=True)
    return {"ok": True, "id": make_id(model, target), "message": f"Copied to '{target}'."}


def delete(ids):
    gone, missing = [], []
    for mod_id in ids:
        model, name = split_id(mod_id)
        ok = flux.delete_mod(name) if model == "flux" else storage.delete_refmod(name)
        (gone if ok else missing).append(name)
        preview = preview_file(model, name)
        if ok and os.path.isfile(preview):
            os.remove(preview)
    message = f"Deleted {len(gone)} mod(s)." if gone else "Nothing deleted."
    if missing:
        message += " Not found: " + ", ".join(missing)
    return {"ok": bool(gone), "message": message}


def move(ids, destination):
    model, _, sub = str(destination or "h3").partition("/")
    model = "flux" if model == "flux" else "h3"
    same = [split_id(i)[1] for i in ids if split_id(i)[0] == model]
    other = [split_id(i)[1] for i in ids if split_id(i)[0] != model]
    moved, skipped = flux.move_mods(same, sub) if model == "flux" else storage.move_mods(same, sub)
    for entry in moved:
        old, new = (entry if isinstance(entry, (list, tuple)) else (entry, None))
        if new:
            _follow(model, old, new)
    where = ("Flux" if model == "flux" else "H3") + (f"/{sub}" if sub else "")
    parts = [f"Moved {len(moved)} mod(s) to {where}."] if moved else []
    if other:
        parts.append("H3 and Flux mods stay in their own folders: " + ", ".join(other) + ".")
    if skipped:
        parts.append("Skipped: " + "; ".join(f"{n} ({why})" for n, why in skipped))
    return {"ok": bool(moved), "message": " ".join(parts) or "Nothing to do."}


def create_folder(model, path):
    made = flux.create_folder(path) if model == "flux" else storage.create_mod_folder(path)
    return {"ok": True, "message": f"Created {'Flux' if model == 'flux' else 'H3'}/{made}."}


def delete_folder(model, path):
    gone = flux.delete_folder(path) if model == "flux" else storage.delete_mod_folder(path)
    return {"ok": bool(gone), "message": f"Deleted the folder {path}." if gone else "Nothing to do."}


def reclassify():
    fixed, checked = storage.reclassify_all_mods()
    return {"ok": True, "message": f"Checked {checked} mod(s), fixed {fixed}." if fixed
            else f"Checked {checked} mod(s); all were already right."}


def prompt_hint(ids):
    metas = []
    for mod_id in ids:
        model, name = split_id(mod_id)
        meta = flux.read_meta(name) if model == "flux" else storage.read_refmod_meta(storage.mod_path(name))
        if meta:
            metas.append(meta)
    return {"text": core.build_prompt_hint(metas) or ""}


def save_upload(filename, data):
    if len(data) > MAX_UPLOAD:
        raise ValueError("the file is too large")
    safe = "".join(c for c in os.path.basename(str(filename or "file")) if c.isalnum() or c in "._- ")[-80:] or "file"
    path = os.path.join(uploads_dir(), f"{uuid.uuid4().hex[:8]}_{safe}")
    with open(path, "wb") as handle:
        handle.write(data)
    return path


def upload_path(token):
    path = os.path.join(uploads_dir(), os.path.basename(str(token or "")))
    return path if os.path.isfile(path) else None


# -- jobs (they need the model's VAEs, so they run as WanGP tasks) ----------------------

class Jobs:
    def __init__(self, plugin):
        self.plugin = plugin
        self.jobs = {}
        self.lock = threading.Lock()
        self.queue_lock = threading.Lock()     # one at a time: each loads a model

    def session(self):
        return getattr(self.plugin, "_wangp_session", None)

    def start(self, op, payload):
        job_id = uuid.uuid4().hex[:10]
        record = {"id": job_id, "op": op, "state": "waiting", "lines": [], "message": "",
                  "started": time.time(), "ids": list(payload.get("ids") or [])}
        with self.lock:
            self.jobs[job_id] = record
            for old in [k for k, v in self.jobs.items() if v["state"] in ("done", "error")
                        and time.time() - v["started"] > 3600]:
                self.jobs.pop(old, None)
        threading.Thread(target=self._run, args=(record, op, dict(payload)), daemon=True).start()
        return job_id

    def status(self, job_id):
        with self.lock:
            record = self.jobs.get(job_id)
            return dict(record, lines=list(record["lines"][-30:])) if record else {"state": "missing"}

    def active(self):
        with self.lock:
            return [dict(r, lines=list(r["lines"][-3:])) for r in self.jobs.values()
                    if r["state"] in ("waiting", "running") or time.time() - r["started"] < 20]

    def _say(self, record, line):
        with self.lock:
            record["lines"].append(str(line))
            record["message"] = str(line)

    def _task(self, record, model_type, spec):
        from .patches import EXTRACT_WRAPPER_KEY, SETTING_GENERATE
        session = self.session()
        if session is None:
            raise RuntimeError("open the Refmods tab once first, so WanGP hands the plugin its session")
        if not model_type:
            raise RuntimeError("pick a MiniMax H3 model at the top of the Library")
        job = self

        class Callbacks:
            def on_status(self, message):
                if message:
                    job._say(record, message)

            def on_error(self, message):
                job._say(record, f"error: {message}")

            def on_progress(self, update):
                pass

        self.plugin._submit(session, model_type,
                            {"video_length": 107,
                             "custom_settings": {SETTING_GENERATE: json.dumps({EXTRACT_WRAPPER_KEY: spec})}},
                            Callbacks())

    def _run(self, record, op, payload):
        with self.queue_lock:
            with self.lock:
                record["state"] = "running"
            try:
                names = [split_id(i)[1] for i in payload.get("ids") or [] if split_id(i)[0] == "h3"]
                model_type = payload.get("model")
                if op == "decompile":
                    for name in names:
                        self._task(record, model_type, {"op": "decompile", "name": name})
                elif op == "strength":
                    strengths = [max(0.05, min(2.0, float(s))) for s in payload.get("strengths") or [0.5, 1.0, 1.5]]
                    for name in names:
                        self._task(record, model_type, {"op": "strength_preview", "name": name,
                                                        "strengths": strengths})
                elif op == "store_frames":
                    self._task(record, model_type, {"op": "store_frames", "names": names,
                                                    "all_missing": bool(payload.get("all_missing"))})
                elif op == "soundtrack":
                    remove = bool(payload.get("remove"))
                    path = None if remove else upload_path(payload.get("upload"))
                    if not remove and not path:
                        raise RuntimeError("upload an audio or video file first")
                    self._task(record, model_type, {"op": "attach_audio", "names": names, "audio_path": path,
                                                    "seconds": float(payload.get("seconds") or 6.0),
                                                    "remove": remove,
                                                    "clean": bool(payload.get("clean")) and not remove})
                elif op == "clean_audio":
                    self._task(record, model_type, {"op": "clean_audio", "names": names,
                                                    "as_copy": bool(payload.get("as_copy", True))})
                elif op == "convert":
                    self._convert(record, model_type, names, payload)
                else:
                    raise RuntimeError(f"unknown job {op!r}")
                with self.lock:
                    record["state"] = "done"
                    if not record["message"]:
                        record["message"] = "Finished."
            except Exception as exc:                                  # noqa: BLE001
                traceback.print_exc()
                with self.lock:
                    record["state"] = "error"
                    record["message"] = f"Failed: {exc}"
                    record["lines"].append(record["message"])

    def _convert(self, record, model_type, names, payload):
        from . import flux_ui
        flux_model = payload.get("flux_model")
        if not flux_model:
            raise RuntimeError("pick a Flux model for Convert")
        decoded = []
        for name in names:                       # every decode first, so each model loads once
            self._task(record, model_type, {"op": "decompile", "name": name})
            pictures = storage.list_decompiled(name)[0]
            if pictures:
                decoded.append((name, pictures))
            else:
                self._say(record, f"'{name}': could not decode it")
        for name, pictures in decoded:
            meta = storage.read_refmod_meta(storage.mod_path(name)) or {}
            target = flux.free_name(name)
            ok, message = flux_ui.submit_extract(
                self.plugin, self.session(), flux_model,
                {"name": target, "images": pictures, "budget": int(payload.get("budget") or flux.DEFAULT_BUDGET),
                 "layout": payload.get("layout") or flux.LAYOUT_SEPARATE,
                 "concept_type": meta.get("concept_type") or "identity",
                 "description": meta.get("description") or "", "converted_from": name})
            self._say(record, f"'{name}' -> Flux/{target}: {message}" if ok else f"'{name}': {message}")
