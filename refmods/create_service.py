"""
The Refmods app's Create page: what a mod made from the chosen sources would
cost (the estimate), and the specs the extraction tasks run with. The tasks
themselves run through library_service.Jobs, like every other model job.

Sources arrive as upload tokens (library_service.save_upload); pictures are
cropped in the page and uploaded again, so here a source is just a file.
"""

from __future__ import annotations

import math
import os

from . import core, flux, storage
from . import library_service as lib

FPS = 24
MIN_AUDIO_SECONDS = 2.0
DEFAULT_AUDIO_SECONDS = 4.0
MAX_CLIP_SECONDS = 15.0
H3_PICTURE_LIMIT = 9            # H3's documented picture-reference limit
AUDIO_TOKENS_PER_SECOND = 80


# -- reading the sources ----------------------------------------------------------

def probe(token):
    """What the page needs to show a source: kind, size, length."""
    path = lib.upload_path(token)
    if not path:
        raise FileNotFoundError(token)
    ext = os.path.splitext(path)[1].lower()
    info = {"token": token, "name": os.path.basename(path).split("_", 1)[-1], "kind": "image"}
    if ext in (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"):
        info["kind"] = "audio"
        info["seconds"] = _audio_seconds(path)
        return info
    if ext in (".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".gif"):
        info["kind"] = "video"
        info["seconds"] = round(float(storage.video_duration_seconds(path) or 0.0), 2)
        size = storage.video_size(path)
        info["width"], info["height"] = (size or (0, 0))
        return info
    from PIL import Image
    with Image.open(path) as im:
        info["width"], info["height"] = im.size
    return info


def _audio_seconds(path):
    try:
        import soundfile as sf
        data = sf.info(str(path))
        return round(data.frames / float(data.samplerate), 2)
    except Exception:                                                  # noqa: BLE001
        return None


# -- the estimate -------------------------------------------------------------------

def _picture_tokens(width, height, form):
    if form.get("mode") != "encode":
        return max(1, int(form.get("pool_h", 16)) // 2) * max(1, int(form.get("pool_w", 16)) // 2)
    width, height = max(1, int(width or 1280)), max(1, int(height or 720))
    scale = min(1.0, float(form.get("ref_resolution", 1024)) / min(width, height))
    return max(1, round(height * scale / 32)) * max(1, round(width * scale / 32))


def _span(source):
    seconds = float(source.get("seconds") or 0.0)
    start = float(source.get("start") or 0.0)
    end = float(source.get("end") or seconds or MAX_CLIP_SECONDS)
    return max(0.0, min(end - start, MAX_CLIP_SECONDS))


def _trimmed(source):
    if not source:
        return False
    seconds = float(source.get("seconds") or 0.0)
    return bool(float(source.get("start") or 0.0) > 0.01 or
                (source.get("end") and seconds and float(source["end"]) < seconds - 0.05))


def audio_source(sources):
    return next((s for s in sources if s["kind"] == "audio"), None)


def _h3_estimate(sources, form):
    """(pictures, clip seconds, tokens, bytes, warnings) for one H3 mod."""
    pictures = clips = tokens = enc_frames = 0
    clip_seconds = 0.0
    warnings = []
    per_second = max(0.05, float(form.get("pictures_per_second") or 1.0))
    as_pictures = bool(form.get("video_as_pictures"))
    for s in sources:
        if s["kind"] == "image":
            pictures += 1
            enc_frames += 1
            tokens += _picture_tokens(s.get("width"), s.get("height"), form)
        elif s["kind"] == "video":
            span = _span(s)
            if as_pictures:
                count = max(1, math.ceil(span * per_second - 1e-9))
                pictures += count
                enc_frames += count
                tokens += count * _picture_tokens(s.get("width"), s.get("height"), form)
            else:
                clips += 1
                clip_seconds += span
                frames = max(1, round(span * FPS))
                latent_t = (frames - 1) // 4 + 1
                tokens += latent_t * _picture_tokens(s.get("width"), s.get("height"), form)
                enc_frames += min(core.ENC_MAX_CLIP_FRAMES, max(1, math.ceil(span * 2)))
    if form.get("merge") and form.get("mode") != "encode" and pictures > 1 and not clips:
        tokens = _picture_tokens(0, 0, form)
        pictures, enc_frames = 1, 1
    tokens *= max(1, int(form.get("multiplier") or 1))
    cap = int(form.get("max_tokens") or 0)
    if cap and tokens > cap:
        warnings.append(f"Over the {cap:,}-token cap, so some pictures or frames will be dropped to fit.")
        tokens = cap
    audio = _audio_part(sources, form, warnings, has_visual=bool(pictures or clips))
    tokens += audio
    edge = int(form.get("enc_resolution") or core.ENC_MAX_EDGE)
    still_kb = 220 * (edge / 1024.0) ** 2
    size = tokens * 128 + enc_frames * still_kb * 1024 + audio * 64
    if pictures > H3_PICTURE_LIMIT:
        warnings.append(f"{pictures} pictures is past H3's documented limit of {H3_PICTURE_LIMIT} picture "
                        "references. Fewer pictures per second, a shorter trim or Compressed with Merge keeps it "
                        "inside.")
    if clips > 1:
        warnings.append("Several clips go into one video mod, one after another.")
    if clip_seconds > MAX_CLIP_SECONDS + 0.05:
        warnings.append("More than 15 s of video: H3 takes up to 15 s of reference video.")
    return {"pictures": pictures, "clip_seconds": round(clip_seconds, 1), "tokens": int(tokens),
            "bytes": int(size), "warnings": warnings}


def _audio_part(sources, form, warnings, has_visual):
    audio = [s for s in sources if s["kind"] == "audio"]
    seconds = float(form.get("audio_seconds") or DEFAULT_AUDIO_SECONDS)
    use_clip = bool(form.get("use_clip_audio")) and not audio and any(s["kind"] == "video" for s in sources)
    if not audio and not use_clip:
        return 0
    if audio:
        real = audio[0].get("seconds")
        if real is not None and _trimmed(audio[0]):
            real = _span(audio[0])
            seconds = real
        if real is not None and real < MIN_AUDIO_SECONDS - 0.05:
            warnings.append(f"The audio is only {real:.1f}s. H3 needs at least {MIN_AUDIO_SECONDS:g}s, so this would "
                            "be refused.")
            form["_blocked"] = "the audio is too short"
            return 0
        if real is not None:
            seconds = min(seconds, real)
        if len(audio) > 1:
            warnings.append("Only the first audio file is used.")
    return int(round(seconds * AUDIO_TOKENS_PER_SECOND))


def _flux_estimate(sources, form):
    budget = int(form.get("budget") or flux.DEFAULT_BUDGET)
    per_second = max(0.05, float(form.get("pictures_per_second") or 1.0))
    pictures = 0
    for s in sources:
        if s["kind"] == "image":
            pictures += 1
        elif s["kind"] == "video":
            seconds = float(s.get("seconds") or 0.0)          # Flux takes the whole video
            pictures += min(flux.MAX_VIDEO_PICTURES, max(1, math.ceil(seconds * per_second - 1e-9)))
    layout = form.get("layout") or flux.LAYOUT_SEPARATE
    refs = pictures if layout == flux.LAYOUT_SEPARATE else min(1, pictures)
    tokens = refs * budget
    warnings = []
    if any(s["kind"] == "audio" for s in sources):
        warnings.append("Flux mods have no sound, so the audio is left out.")
    return {"pictures": pictures, "references": refs, "clip_seconds": 0, "tokens": int(tokens),
            "bytes": int(tokens * flux.LATENT_CHANNELS * 2), "warnings": warnings}


def _groups(sources, form):
    """[(suffix, sources)]: one group with everything, or one per picture or video
    (an audio file then goes with each, as its soundtrack)."""
    if form.get("split") != "each":
        return [("", sources)]
    audio = [s for s in sources if s["kind"] == "audio"]
    visual = [s for s in sources if s["kind"] != "audio"]
    if not visual:
        return [("", sources)]
    out = []
    for s in visual:
        stem = os.path.splitext(s.get("name") or "source")[0]
        stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem).strip("_")[:40] or "source"
        out.append((stem, [s] + audio))
    return out


def estimate(form, sources):
    form = dict(form or {})
    family = "flux" if form.get("family") == "flux" else "h3"
    sources = [dict(s) for s in sources or [] if s.get("kind") in ("image", "video", "audio")]
    if family == "flux":
        sources = [s for s in sources if s["kind"] != "audio"] + [s for s in sources if s["kind"] == "audio"]
    groups = _groups(sources, form)
    mods, total_tokens, total_bytes, warnings = [], 0, 0, []
    for suffix, group in groups:
        e = _flux_estimate(group, form) if family == "flux" else _h3_estimate(group, form)
        e["name"] = target_name(form.get("name"), suffix)
        mods.append(e)
        total_tokens += e["tokens"]
        total_bytes += e["bytes"]
        for w in e["warnings"]:
            if w not in warnings:
                warnings.append(w)
    blockers = []
    if not str(form.get("name") or "").strip():
        blockers.append("Give the mod a name.")
    if not sources:
        blockers.append("Add a picture, video" + ("" if family == "flux" else " or audio file") + ".")
    if family == "flux" and sources and not any(s["kind"] != "audio" for s in sources):
        blockers.append("Flux mods need a picture or video.")
    if form.get("_blocked"):
        blockers.append(f"Can't create: {form['_blocked']}.")
    if not form.get("model"):
        blockers.append("Pick a " + ("Flux" if family == "flux" else "MiniMax H3") + " model.")
    existing = [m["name"] for m in mods if _exists(family, m["name"])]
    if existing and form.get("save", True):
        warnings.append("A mod with this name exists, so it gets a number added: " + ", ".join(existing) + ".")
    return {"mods": mods, "tokens": total_tokens, "bytes": total_bytes, "warnings": warnings,
            "blockers": blockers, "ready": not blockers}


def _exists(family, name):
    try:
        return os.path.isfile(flux.mod_path(name) if family == "flux" else storage.mod_path(name) + ".safetensors")
    except Exception:                                                  # noqa: BLE001
        return False


def target_name(name, suffix=""):
    name = str(name or "").strip().replace("\\", "/").strip("/") or "my_mod"
    return f"{name}_{suffix}" if suffix else name


def free_name(family, name):
    if family == "flux":
        return flux.free_name(name)
    if not _exists("h3", name):
        return name
    return storage.free_mod_name(name, "")


# -- the specs the tasks run with ------------------------------------------------------

def plan(form, sources):
    """[(family, model, spec)] for each mod to make."""
    form = dict(form or {})
    family = "flux" if form.get("family") == "flux" else "h3"
    paths = {}
    for s in sources:
        path = lib.upload_path(s.get("token"))
        if not path:
            raise RuntimeError(f"the file {s.get('name')} is no longer uploaded; add it again")
        paths[s["token"]] = path
    out = []
    for suffix, group in _groups([dict(s) for s in sources], form):
        name = target_name(form.get("name"), suffix)
        if form.get("save", True):
            name = free_name(family, name)
        images = [paths[s["token"]] for s in group if s["kind"] == "image"]
        videos = [paths[s["token"]] for s in group if s["kind"] == "video"]
        audio = [paths[s["token"]] for s in group if s["kind"] == "audio"]
        order = [["img" if s["kind"] == "image" else "vid", paths[s["token"]]]
                 for s in group if s["kind"] in ("image", "video")]
        trims = {os.path.basename(paths[s["token"]]): [float(s.get("start") or 0.0),
                                                      float(s.get("end") or s.get("seconds") or MAX_CLIP_SECONDS)]
                 for s in group if s["kind"] in ("video", "audio") and _trimmed(s)}
        audio_seconds = float(form.get("audio_seconds") or DEFAULT_AUDIO_SECONDS)
        if audio and _trimmed(audio_source(group)):
            audio_seconds = min(MAX_CLIP_SECONDS, _span(audio_source(group)))
        if family == "flux":
            out.append(("flux", form.get("model"), {
                "name": name, "images": images, "videos": videos, "order": order,
                "pictures_per_second": float(form.get("pictures_per_second") or 1.0),
                "layout": form.get("layout") or flux.LAYOUT_SEPARATE,
                "budget": int(form.get("budget") or flux.DEFAULT_BUDGET),
                "concept_type": form.get("concept") or "identity", "description": form.get("description") or ""}))
            continue
        out.append(("h3", form.get("model"), {
            "name": name, "mode": "encode" if form.get("mode") == "encode" else "training",
            "concept_type": form.get("concept") or "generic",
            "image_paths": images, "video_paths": videos, "audio_path": audio[0] if audio else None,
            "remove_background_images_ref": 1 if form.get("remove_background") else 0,
            "ref_resolution": int(form.get("ref_resolution") or 1024),
            "enc_resolution": int(form.get("enc_resolution") or core.ENC_MAX_EDGE),
            "pool_h": int(form.get("pool_h") or 16), "pool_w": int(form.get("pool_w") or 16),
            "latent_frames": 90, "identity": int(form.get("identity") if form.get("identity") is not None else 500),
            "multiplier": max(1, int(form.get("multiplier") or 1)),
            "max_tokens": int(form.get("max_tokens") if form.get("max_tokens") is not None else 65536),
            "description": form.get("description") or "", "save": bool(form.get("save", True)),
            "use_clip_audio": bool(form.get("use_clip_audio")), "video_trims": trims,
            "video_as_pictures": bool(form.get("video_as_pictures")),
            "pictures_per_second": float(form.get("pictures_per_second") or 1.0),
            "merge": bool(form.get("merge")) and form.get("mode") != "encode",
            "audio_seconds": max(MIN_AUDIO_SECONDS, audio_seconds),
            "order": order, "clean_audio": bool(form.get("clean_audio")),
        }))
    return out
