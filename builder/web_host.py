"""
The Prompt Builder web app's link to the running WanGP, built the way the
Video Editor's host is.

Each time the Prompt Builder tab is opened, WanGP first saves the Generator
form into the session state and then calls the plugin's on_tab_select with it.
capture() keeps what the builder needs from that moment: the model, the media
loaded on the Generator page, and the mods armed in the Refmods panel (which
the panel keeps in the same state). The web app reads it from here.
"""

from __future__ import annotations

import copy
import io
import os
import sys
import threading
import time

from . import studio_core as core

IMAGE_CAPS = {"minimax_p_h3_image": 8, "minimax_h3_image": 16, "minimax_h3_image_pruned": 16}
MEDIA_KEYS = ("image_start", "image_end", "image_refs", "video_source", "video_guide", "video_guide2",
              "video_guide3", "audio_guide", "audio_guide2", "audio_guide3", "image_prompt_type",
              "video_prompt_type", "audio_prompt_type")


class BuilderHost:
    def __init__(self, plugin):
        self.plugin = plugin
        self._lock = threading.Lock()
        self.state = None
        self.settings = {}
        self.model = {}
        self.media = []
        self.objects = {}            # media key -> what the form holds (a path or an image), for thumbnails
        self.captured_at = 0.0
        self.error = ""

    # -- capture -------------------------------------------------------------

    def capture(self, state):
        collect = getattr(self.plugin, "collect_current_model_settings_with_media", None)
        settings = {}
        error = ""
        if callable(collect):
            try:
                settings = dict(collect(state) or {})
            except Exception as exc:                   # noqa: BLE001
                error = f"could not read the Generator settings ({exc!r})"
        else:
            error = "WanGP did not hand the plugin collect_current_model_settings_with_media"
        settings.pop("state", None)
        model = self._model(settings.get("model_type") or (state or {}).get("model_type"))
        mods = self._mods(state)
        inputs = {k: settings.get(k) for k in MEDIA_KEYS}
        media = core.detect_media(inputs, model, mods)
        objects = self._objects(inputs, media)
        with self._lock:
            self.state = state
            self.settings = settings
            self.model = model
            self.media = media
            self.objects = objects
            self.captured_at = time.time()
            self.error = error
        if error:
            print(f"[Refmods Studio] Prompt Builder: {error}")

    def _model(self, model_type) -> dict:
        model_type = str(model_type or "")
        model_def = {}
        get_def = getattr(self.plugin, "get_model_def", None)
        if callable(get_def) and model_type:
            try:
                model_def = get_def(model_type) or {}
            except Exception:                          # noqa: BLE001
                model_def = {}
        arch = str(model_def.get("architecture") or "").lower()
        urls = " ".join(str(u) for u in (model_def.get("URLs") or []) if isinstance(u, str)).lower()
        name = model_type
        get_name = getattr(self.plugin, "get_model_name", None)
        if callable(get_name) and model_type:
            try:
                name = get_name(model_type) or model_type
            except Exception:                          # noqa: BLE001
                pass
        return {"model_type": model_type, "name": name, "h3": "minimax_h3" in (model_type + arch).lower(),
                "ref2va": "ref2va" in (model_type.lower() + arch + urls), "image_cap": IMAGE_CAPS.get(arch, 0)}

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

    @staticmethod
    def _objects(inputs, media) -> dict:
        """The file or image behind each label, so the web app can show a thumbnail."""
        def items(value):
            if value is None or value == "":
                return []
            return list(value) if isinstance(value, (list, tuple)) else [value]
        out = {}
        for m in media:
            if m.source != "gen":
                continue
            if m.key == "gen:start":
                found = items(inputs.get("image_start"))
            elif m.key == "gen:end":
                found = items(inputs.get("image_end"))
            elif m.key.startswith("gen:ref:"):
                refs = items(inputs.get("image_refs"))
                index = int(m.key.rsplit(":", 1)[1]) - 1
                found = [refs[index]] if 0 <= index < len(refs) else []
            else:
                found = []
            if found:
                out[m.key] = found[0]
        return out

    def refresh_mods(self):
        """Read the armed mods again from the captured session state (the Refmods panel may have
        changed them since the tab was opened, e.g. after Load pack)."""
        with self._lock:
            state, settings, model = self.state, dict(self.settings), dict(self.model)
        if state is None:
            return
        inputs = {k: settings.get(k) for k in MEDIA_KEYS}
        media = core.detect_media(inputs, model, self._mods(state))
        objects = self._objects(inputs, media)
        with self._lock:
            self.media, self.objects = media, objects

    def armed_rows(self) -> list:
        """The Refmods panel's armed rows (mod, strength, how it's sent), from the session state."""
        import json
        with self._lock:
            state = self.state
        raw = (state or {}).get("_h3refmod_selection") if isinstance(state, dict) else None
        try:
            return list((json.loads(raw) if isinstance(raw, str) else raw or {}).get("rows") or [])
        except Exception:                              # noqa: BLE001
            return []

    # -- reading ---------------------------------------------------------------

    def snapshot(self) -> dict:
        with self._lock:
            return {"captured": bool(self.captured_at), "captured_at": self.captured_at, "error": self.error,
                    "model": dict(self.model), "media": [m.to_dict() for m in self.media],
                    "prompt": str(self.settings.get("prompt") or "")}

    def media_list(self):
        with self._lock:
            return list(self.media), dict(self.model)

    def thumbnail(self, key):
        """PNG bytes for a picture label, or None."""
        with self._lock:
            item = self.objects.get(key)
        if item is None:
            return None
        try:
            from PIL import Image
            if isinstance(item, (list, tuple)):
                item = item[0]
            if isinstance(item, dict):
                item = item.get("path") or item.get("name") or item.get("image")
            image = item if hasattr(item, "thumbnail") else Image.open(str(item))
            image = image.copy()
            image.thumbnail((96, 96))
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, "PNG")
            return buffer.getvalue()
        except Exception:                              # noqa: BLE001
            return None
