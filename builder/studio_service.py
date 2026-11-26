"""
What the Prompt Builder web app asks the server to do, without any Gradio:
saved prompts, the draft, the subject library, the prompt enhancer (as
background jobs the page polls), and the checks on the prompt box.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path

from . import studio_core as core


def _s(value) -> str:
    return str(value or "").strip()


def data_dir() -> Path:
    root = Path.cwd()
    for folder in Path(__file__).resolve().parents:
        if (folder / "wgp.py").is_file():
            root = folder
            break
    path = root / "loras" / "h3_prompt_builder"
    path.mkdir(parents=True, exist_ok=True)
    return path


def clean_name(name) -> str:
    keep = [c for c in _s(name) if c.isalnum() or c in " -_.,()"]
    cleaned = "".join(keep).strip(" .")
    while ".." in cleaned:
        cleaned = cleaned.replace("..", ".")
    return cleaned[:80].strip(" .")


def _write_json(path: Path, blob) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(blob, indent=1), encoding="utf-8")
    temp.replace(path)


def _files(folder) -> list:
    try:
        items = [p for p in (data_dir() / folder).glob("*.json") if p.is_file()]
    except Exception:                                  # noqa: BLE001
        return []
    return sorted(items, key=lambda p: p.stat().st_mtime, reverse=True)


class _Progress:
    """Enough of WangpProgress for the prompt enhancer, read by the page."""

    def __init__(self):
        self.gen = {"abort": False}
        self.done = 0
        self.total = 0
        self.desc = ""
        self.timing = ""

    def __call__(self, value=None, desc=None, total=None, unit=None, **_kwargs):
        if isinstance(value, (tuple, list)) and len(value) == 2:
            self.done, self.total = value
        elif isinstance(value, (int, float)):
            self.done = value
        if desc:
            self.desc = str(desc)
        return self

    def stream_tokens(self, *, token_count=0, max_tokens=0, description="Enhancing", **_kwargs):
        self.done, self.total, self.desc = token_count, max_tokens, description

    def changed(self):
        pass

    def tqdm(self, iterable, *args, **kwargs):
        return iterable


class Service:
    def __init__(self, plugin, host):
        self.plugin = plugin
        self.host = host
        self.jobs = {}
        self._lock = threading.Lock()

    # -- saved prompts and the draft ---------------------------------------------

    def prompt_names(self):
        return [p.stem for p in _files("prompts")[:50]]

    def save_prompt(self, name, form):
        filename = clean_name(name)
        if not filename:
            return {"ok": False, "note": "Give the prompt a name first."}
        path = data_dir() / "prompts" / f"{filename}.json"
        existed = path.exists()
        old = self._read_prompt(path) if existed else {}
        try:
            media, _, _, _ = self.resolve(core.clean_form(form))
            packs = sorted({m.pack for m in media if getattr(m, "pack", "")})
        except Exception:                              # noqa: BLE001
            packs = []
        _write_json(path, {"format": 5, "saved": time.strftime("%Y-%m-%d %H:%M"), "name": filename,
                           "category": old.get("category", ""), "fav": bool(old.get("fav")),
                           "packs": packs or old.get("packs") or [], "form": core.clean_form(form)})
        return {"ok": True, "name": filename, "note": f"{'Replaced' if existed else 'Saved'} {filename}."}

    def form_from_blob(self, blob):
        """A saved form from this builder, or a 4.x one mapped across."""
        if isinstance(blob, dict) and isinstance(blob.get("form"), dict):
            return core.clean_form(blob["form"]), ""
        try:
            values, _ = self.plugin._values_from_blob(blob)
            if values is None:
                return None, ""
            return core.form_from_v4(self.plugin._unpack(values)), (
                " It was saved by the 4.x builder: the text and subjects came across; check their pictures "
                "and voices.")
        except Exception:                              # noqa: BLE001
            return None, ""

    def load_prompt(self, name):
        filename = clean_name(name)
        try:
            blob = json.loads((data_dir() / "prompts" / f"{filename}.json").read_text(encoding="utf-8"))
            form, note = self.form_from_blob(blob)
        except Exception:                              # noqa: BLE001
            form, note, blob = None, "", {}
        if form is None:
            return {"ok": False, "note": f"Could not read {filename}."}
        return {"ok": True, "form": form, "packs": list(blob.get("packs") or []) if isinstance(blob, dict) else [],
                "note": f"Loaded {filename}, saved {blob.get('saved', 'earlier')}." + note}

    @staticmethod
    def _read_prompt(path):
        try:
            blob = json.loads(path.read_text(encoding="utf-8"))
            return blob if isinstance(blob, dict) else {}
        except Exception:                              # noqa: BLE001
            return {}

    def library(self):
        """Every saved prompt with its category, star, linked packs and the start of its action."""
        out = []
        for path in _files("prompts"):
            blob = self._read_prompt(path)
            form = blob.get("form") if isinstance(blob.get("form"), dict) else {}
            action = " ".join(str(form.get("action") or form.get("summary") or "").split())
            out.append({"name": path.stem, "saved": blob.get("saved", ""), "category": blob.get("category", ""),
                        "fav": bool(blob.get("fav")), "packs": list(blob.get("packs") or []),
                        "mode": form.get("mode", ""), "text": action[:180]})
        out.sort(key=lambda p: (not p["fav"],))
        return {"items": out}

    def library_meta(self, name, changes):
        """Set a saved prompt's category or star."""
        path = data_dir() / "prompts" / f"{clean_name(name)}.json"
        blob = self._read_prompt(path)
        if not blob:
            return {"ok": False, "note": f"No saved prompt called '{name}'."}
        if "category" in changes:
            blob["category"] = core._s(changes.get("category"))[:60]
        if "fav" in changes:
            blob["fav"] = bool(changes.get("fav"))
        _write_json(path, blob)
        return {"ok": True}

    def delete_prompt(self, name):
        path = data_dir() / "prompts" / f"{clean_name(name)}.json"
        if not path.exists():
            return {"ok": False, "note": f"No saved prompt called '{name}'."}
        bin_dir = data_dir() / "prompts" / "deleted"
        bin_dir.mkdir(parents=True, exist_ok=True)
        path.replace(bin_dir / path.name)   # kept in prompts/deleted, not destroyed
        return {"ok": True, "note": f"Deleted {path.stem} (a copy is kept in prompts/deleted)."}

    def load_recent(self):
        """The most recently saved prompt."""
        files = _files("prompts")
        if not files:
            return {"ok": False, "note": "No saved prompts yet."}
        return self.load_prompt(files[0].stem)

    def import_file(self, filename, text):
        """A prompt from a file on your computer: one this builder or the 4.x one saved (.json), or plain text,
        which goes into the action box."""
        text = text or ""
        try:
            blob = json.loads(text)
        except Exception:                              # noqa: BLE001
            blob = None
        if blob is not None:
            form, note = self.form_from_blob(blob)
            if form is None:
                return {"ok": False, "note": f"{filename} isn't a prompt this builder can read."}
            return {"ok": True, "form": form, "note": f"Loaded {filename}." + note}
        if not text.strip():
            return {"ok": False, "note": f"{filename} is empty."}
        form = core.clean_form({"action": text.strip()})
        return {"ok": True, "form": form, "note": f"Put the text of {filename} into Action."}

    def draft_path(self):
        return data_dir() / "studio_draft.json"

    def save_draft(self, form):
        path = self.draft_path()
        stamp = time.strftime("%H:%M:%S")
        form = core.clean_form(form)
        try:
            old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:                              # noqa: BLE001
            old = {}
        if old.get("form") == form:
            return {"ok": True, "note": f"Draft saved at {old.get('saved', stamp)}."}
        if path.exists():
            path.replace(path.with_name("studio_draft.prev.json"))
        _write_json(path, {"format": 5, "saved": stamp, "form": form})
        return {"ok": True, "note": f"Draft saved at {stamp}."}

    def load_draft(self):
        try:
            blob = json.loads(self.draft_path().read_text(encoding="utf-8"))
            return {"ok": True, "form": core.clean_form(blob.get("form")),
                    "note": f"Restored the draft saved at {blob.get('saved', 'earlier')}."}
        except Exception:                              # noqa: BLE001
            pass
        try:
            old = json.loads((data_dir() / "h3_draft.json").read_text(encoding="utf-8"))
            form, note = self.form_from_blob(old)
            if form is not None:
                return {"ok": True, "form": form, "note": "Restored the last 4.x draft." + note}
        except Exception:                              # noqa: BLE001
            pass
        return {"ok": False, "note": "No saved draft to restore."}

    # -- the subject library -------------------------------------------------------

    def subject_names(self):
        return [p.stem for p in _files("subjects")[:100]]

    def save_subject(self, subject):
        subject = core.clean_subject(subject)
        name = clean_name(subject.get("name"))
        if not name:
            return {"ok": False, "note": "Give the subject a name first."}
        path = data_dir() / "subjects" / f"{name}.json"
        existed = path.exists()
        _write_json(path, {"kind": "subject", "format": 5, "saved": time.strftime("%Y-%m-%d %H:%M"), "name": name,
                           "subject": {k: subject.get(k) for k in core.LIBRARY_KEYS}})
        return {"ok": True, "name": name, "note": f"{'Replaced' if existed else 'Saved'} {name} in the library. "
                                                   "Its sources and voice belong to this project and aren't saved."}

    def load_subject(self, name):
        try:
            blob = json.loads((data_dir() / "subjects" / f"{clean_name(name)}.json").read_text(encoding="utf-8"))
            return {"ok": True, "subject": core.subject_from_library(blob), "note": f"Loaded {name}."}
        except Exception:                              # noqa: BLE001
            return {"ok": False, "note": f"Could not read {name}."}

    # -- the prompt and its checks ---------------------------------------------------

    def lint(self):
        try:
            from .h3studio import lint
            return lint.check
        except Exception:                              # noqa: BLE001
            return None

    def resolve(self, form):
        media, model = self.host.media_list()
        detected = core.auto_mode(media, model)
        mode = detected if form["mode"] in ("", core.AUTO) else form["mode"]
        # "Subject sections" writes a base mode (FL2VA with RefMods, say) in the reference layout.
        return media, model, core.layout_mode(form, mode), detected

    def preview(self, form):
        form = core.clean_form(form)
        media, model, mode, detected = self.resolve(form)
        text = core.assemble(form, media, mode)
        result = core.checks(form, media, mode, text, detected, model, self.lint())
        unused = [m.key for m in media if m.labels and m.role not in ("start", "continue", "end")
                  and not any(l in text for l in m.labels)]
        return {"text": text, "checks": result, "mode": mode, "detected": detected,
                "summary": core.media_summary(media), "unused": unused}

    def check_prompt(self, text):
        media, model = self.host.media_list()
        errors, warnings, info = [], [], []
        if not _s(text):
            return {"errors": [], "warnings": [], "info": ["The prompt box is empty."]}
        lint = self.lint()
        if lint is not None:
            try:
                report = lint(text, "auto", None, 0)
                errors += report.get("errors", [])
                counts = []
                for w in report.get("warnings", []):
                    m = re.search(r"has (\d+) words; 350-500 is normal", w)
                    (counts.append(int(m.group(1))) if m else warnings.append(w))
                info.append(f"{report.get('windows', 1)} window(s)")
                if counts:
                    span = f"{min(counts)}" if min(counts) == max(counts) else f"{min(counts)}-{max(counts)}"
                    info.append(f"{span} words of shots per window (the guide's usual is 350-500)")
            except Exception:                          # noqa: BLE001
                pass
        cited = set(re.findall(r"<(?:Picture|Video|Audio) \d+>", text))
        sent = {label for m in media for label in m.labels}
        missing = sorted(cited - sent, key=lambda l: (l.split()[0], int(re.sub(r"\D", "", l) or 0)))
        if missing and not media:
            errors.append(f"nothing is loaded or armed, so {core.join_labels(missing)} point at nothing: arm the "
                          "mods or load the references before generating")
        elif missing:
            errors.append(f"{core.join_labels(missing)} {'is' if len(missing) == 1 else 'are'} in the prompt but "
                          "nothing loaded or armed gets that label")
        for m in media:
            unused = [l for l in m.labels if l not in cited]
            if unused and m.role not in ("start", "continue", "end"):
                warnings.append(f"{core.join_labels(unused)} ({m.name}) is sent but never used")
        return {"errors": errors, "warnings": warnings, "info": info}

    def snippet(self, kind, form, args):
        form = core.clean_form(form)
        media, _, mode, _ = self.resolve(form)
        form = core.expand_names(form, mode)   # typed !Name counts, e.g. for who already has a speaker ID
        args = args or {}
        if kind == "time":
            return f"At {core.timestamp(args.get('at'))}, "
        if kind == "shot":
            return core.shot_snippet(form["action"], args.get("at"))
        if kind == "camera":
            return core.camera_snippet(args.get("move", ""), args.get("amplitude", ""), args.get("speed", ""),
                                       form["action"], args.get("framing", ""), args.get("rig", ""),
                                       args.get("lens", ""), args.get("of", ""), args.get("verb", ""))
        if kind == "gear":
            body, lens = core._s(args.get("body")), core._s(args.get("lens"))
            if body and lens:
                return f"Shot on {body} using {lens}. "
            return f"Shot on {body}. " if body else (f"Shot using {lens}. " if lens else "")
        if kind == "subject":
            return core.subject_snippet(form["subjects"], int(args.get("index") or 0), mode, form["action"])
        if kind == "line":
            return core.dialogue_snippet(form["subjects"], int(args.get("index") or 0), media, mode, form["action"],
                                         args.get("tone", ""), args.get("language", "English"),
                                         bool(args.get("voiceover")), args.get("line", ""), None,   # only Time writes a time
                                         args.get("delivery", ""), self._stamp(args.get("same_as")), bool(args.get("cutoff")),
                                         args.get("carry", ""))
        if kind == "scene":
            return core.scene_sentence(args.get("style", ""), args.get("location", ""), args.get("time", ""),
                                       args.get("lighting", ""), args.get("atmosphere", ""), args.get("grade", ""))
        if kind == "sound":
            return core.sentence(args.get("text", ""))
        if kind == "music":
            return core.music_sentence(args.get("instruments", ""), args.get("tempo", ""), args.get("dynamics", ""))
        if kind == "text":
            return core.screen_text_snippet(args.get("kind", ""), args.get("words", ""))
        if kind == "summary":
            return core.draft_summary(form, mode)
        return ""

    @staticmethod
    def _stamp(value):
        """A typed time for "same voice as line at": 1.2 becomes 00:01.200; a timestamp is kept."""
        value = core._s(value)
        try:
            return core.timestamp(float(value)) if value else ""
        except ValueError:
            return value

    def draft_subjects(self, form):
        """Subjects for what's sent and not used yet: an armed pack becomes one subject with its sources
        filled in from the members' roles; other mods get one each."""
        form = core.clean_form(form)
        media, _, _, _ = self.resolve(form)
        added = core.subjects_from_media(media, form["subjects"])
        form["subjects"] += added
        note = (f"Added {len(added)} subject(s) from what's sent." if added
                else "Every picture and mod already has a subject.")
        return {"form": form, "note": note}

    # -- phrases: wording you reuse -------------------------------------------------------

    def _phrases_path(self):
        return data_dir() / "phrases.json"

    def phrases(self):
        try:
            items = json.loads(self._phrases_path().read_text(encoding="utf-8"))
        except Exception:                                 # noqa: BLE001
            items = []
        return [p for p in items if isinstance(p, dict) and p.get("text")]

    def _write_phrases(self, items):
        path = self._phrases_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def save_phrase(self, text, category="", phrase_id=None):
        text = str(text or "").strip()
        if not text:
            return {"ok": False, "note": "Select some text first, or type the phrase."}
        category = str(category or "").strip()[:40] or "General"
        items = self.phrases()
        old = next((p for p in items if p.get("id") == phrase_id), None) if phrase_id else None
        if old:
            old.update(text=text, category=category)
        elif any(p["text"] == text for p in items):
            return {"ok": True, "note": "That phrase is already saved.", "phrases": items}
        else:
            items.append({"id": uuid.uuid4().hex[:10], "text": text, "category": category, "saved": time.time()})
        self._write_phrases(items)
        return {"ok": True, "note": f"Saved to phrases ({category}).", "phrases": items}

    def delete_phrase(self, phrase_id):
        items = [p for p in self.phrases() if p.get("id") != phrase_id]
        self._write_phrases(items)
        return {"ok": True, "note": "Phrase deleted.", "phrases": items}

    # -- packs (Refmods) ---------------------------------------------------------------

    def _storage(self):
        import sys
        root = (__package__ or "").rsplit(".", 1)[0]
        return sys.modules.get(f"{root}.refmods.storage")

    def pack_list(self):
        storage = self._storage()
        if storage is None:
            return []
        out = []
        for name in storage.list_packs():
            pack = storage.read_pack(name) or {}
            out.append({"name": name, "kind": pack.get("kind", "mixed"), "character": bool(pack.get("subject")),
                        "mods": len([m for m in pack.get("members") or [] if m.get("on", True) is not False])})
        return out

    def load_pack(self, name, form):
        """A pack as a subject: its character fills the creator, and once the Refmods panel has armed its mods
        each one is a look source or the voice, providing what its role says. Returns armed=False while the
        pack's mods aren't armed yet."""
        storage = self._storage()
        pack = storage.read_pack(name) if storage else None
        if not pack:
            return {"ok": False, "note": f"No pack called '{name}'."}
        self.host.refresh_mods()
        form = core.clean_form(form)
        media, _, _, _ = self.resolve(form)
        mine = [m for m in media if m.pack == name]
        wanted = [m.get("mod") for m in pack.get("members") or [] if m.get("on", True) is not False]
        meta = pack.get("subject") if isinstance(pack.get("subject"), dict) else {}
        kind = {"character": "Character", "location": "Location", "prop": "Prop", "style": "Style"}.get(
            pack.get("kind"), meta.get("kind") or "Character")
        fresh = core.subjects_from_media(mine, []) if mine else []
        if not fresh:
            subject = core.new_subject(kind)
            subject["name"] = pack.get("subject_name") or name
            fresh = [subject]
        core.apply_pack_meta(fresh[0], meta)
        if pack.get("subject_name"):
            fresh[0]["name"] = meta.get("name") or pack["subject_name"]
        keys = {m.key for m in mine}
        index = next((i for i, s in enumerate(form["subjects"])
                      if any(l["key"] in keys for l in s["look"]) or (s.get("voice") and s["voice"] in keys)), None)
        if index is None:
            form["subjects"].append(fresh[0])
            index = len(form["subjects"]) - 1
        else:
            form["subjects"][index] = fresh[0]
        used = {l["key"] for s in form["subjects"] for l in s["look"]}
        for extra in fresh[1:]:
            if not any(l["key"] in used for l in extra["look"]):
                form["subjects"].append(extra)
        armed = bool(mine) or not wanted
        note = (f"Loaded the pack '{name}' as {fresh[0]['name'] or 'a subject'}." if armed else
                f"Filled in '{name}', but its mods aren't armed. Open a MiniMax H3 Ref2VA model on the Generator page "
                "so the Refmods panel can arm them, then load the pack again.")
        return {"ok": True, "armed": armed, "form": form, "selected": index, "note": note}

    def save_pack(self, name, subject):
        """A subject as a pack: its mods (look sources and voice) with their roles and parts, and its character."""
        storage = self._storage()
        if storage is None:
            return {"ok": False, "note": "Packs need the Refmods half of Refmods Studio."}
        subject = core.clean_subject(subject)
        name = str(name or "").strip() or subject["name"].strip()
        if not name:
            return {"ok": False, "note": "Give the subject a name, or type a name for the pack."}
        old = storage.read_pack(name) or {}
        before = {m.get("mod"): dict(m) for m in old.get("members") or []}
        rows = {r.get("mod"): r for r in self.host.armed_rows()}

        def member(mod):
            m = dict(before.get(mod) or {})
            row = rows.get(mod) or {}
            for key in ("strength", "as_video", "send_as", "use_audio"):
                if key in row and key not in m:
                    m[key] = row[key]
            m.setdefault("strength", 1.0)
            m["mod"] = mod   # its On switch is kept: a mod switched off in the pack stays off
            return m

        members, skipped = [], 0
        for look in subject["look"]:
            key = look["key"]
            if not key.startswith("mod:") or key.endswith(":audio"):
                skipped += 0 if key.startswith("mod:") else 1
                continue
            m = member(key[4:])
            m.update(role=core.role_for(look, subject["kind"]), parts=list(look["parts"]), sheet=bool(look["sheet"]))
            members.append(m)
        voice = subject.get("voice") or ""
        if voice.startswith("mod:"):
            mod = voice[4:-len(":audio")] if voice.endswith(":audio") else voice[4:]
            same = next((m for m in members if m["mod"] == mod), None)
            if same:
                same["use_audio"] = True
            else:
                m = member(mod)
                m["role"] = "voice"
                members.append(m)
        names = {m["mod"] for m in members}
        members += [m for mod, m in before.items() if m.get("on", True) is False and mod not in names]
        pack = {**old, "name": name, "kind": subject["kind"].lower(),
                "subject_name": subject["name"], "subject": core.pack_meta(subject), "members": members}
        pack.pop("from_preset", None)
        try:
            storage.write_pack(pack)
        except Exception as exc:                          # noqa: BLE001
            return {"ok": False, "note": f"Could not save the pack ({exc})."}
        note = f"{'Updated' if old else 'Saved'} the pack '{name}' with {len(members)} mod(s) and the character."
        if skipped:
            note += f" {skipped} picture source(s) from the Generator page aren't mods, so they aren't in it."
        return {"ok": True, "note": note, "name": name}

    # -- the prompt enhancer, as jobs ------------------------------------------------

    def start_job(self, kind, payload):
        job_id = uuid.uuid4().hex[:12]
        progress = _Progress()
        job = {"id": job_id, "kind": kind, "done": False, "text": "", "note": "", "error": "", "progress": progress}
        with self._lock:
            self.jobs[job_id] = job

        def run():
            try:
                if kind == "write":
                    job["text"], job["note"] = self._write_all(payload, progress)
                else:
                    job["text"], job["note"] = self._enhance(payload, progress)
            except Exception as exc:                   # noqa: BLE001
                job["error"] = str(exc) or type(exc).__name__
            job["done"] = True

        threading.Thread(target=run, daemon=True, name=f"refmods_studio_{kind}").start()
        return job_id

    def job_status(self, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            return {"done": True, "error": "That job is gone."}
        p = job["progress"]
        return {"done": job["done"], "text": job["text"], "note": job["note"], "error": job["error"],
                "progress": {"done": p.done, "total": p.total, "desc": p.desc}}

    def stop_job(self, job_id):
        job = self.jobs.get(job_id)
        if job is not None:
            job["progress"].gen["abort"] = True
        return {"ok": True}

    def _studio(self):
        studio = getattr(self.plugin, "h3_studio", None)
        if studio is None:
            raise RuntimeError("the prompt enhancer isn't available")
        if self.host.state is None:
            raise RuntimeError("open the Video Generator tab once, then come back, so the builder can reach WanGP")
        return studio

    def context(self, form, media, mode):
        lines = [f"MODE: {mode}. LENGTH: {float(form['duration']):g} seconds."]
        if mode == "Reference":
            defs = core.subject_definitions(form, media)
            if defs:
                lines.append("SUBJECTS AND REFERENCES (use these labels exactly, and write every spoken line as "
                             "<Subject N> (SN), in the voice following <Audio N>, ... when the subject has a "
                             "voice):\n" + defs)
        else:
            for subject in form["subjects"]:
                desc = core.describe(subject)
                if desc:
                    lines.append(f"SUBJECT: {desc}.")
            lines.append("Write every spoken line as: <name> (SN), a woman/man speaking with a <tone> tone, says, "
                         "her/his lips moving: <d>[English] ...</d>. Never describe the type of voice.")
        if _s(form["style"]):
            lines.append(f"STYLE (stays the same for the whole clip): {_s(form['style'])}")
        return "\n".join(lines)

    def _enhance(self, payload, progress):
        part = payload.get("part")
        form = core.clean_form(payload.get("form"))
        think = bool(payload.get("think"))
        studio = self._studio()
        media, _, mode, _ = self.resolve(form)
        form = core.expand_names(form, mode)   # the enhancer sees the subjects, not !Name
        current = _s(form.get(part))
        context = self.context(form, media, mode)
        from .h3studio.modes import ACTION_ROLE, Target, detect_combat
        duration = float(form["duration"] or 0) or None
        if part == "action":
            brief = studio.library.build_brief(
                current or context, Target(mode="T2VA" if mode == "Reference" else mode, duration=duration,
                                           combat=detect_combat(current)),
                budget_tokens=int(studio.settings.get("enhancer_budget_tokens", 10000)),
                enabled_skills=studio.enabled_skills, contract="", purpose="action", role=ACTION_ROLE)
            system = (brief.text + "\n\nAnswer with the action body only. It starts at `[Shot 1]` and ends with the "
                      "last shot's sentence. Nothing before it, nothing after it.")
            request = (context + "\n\nWHAT THE USER TYPED IN THE ACTION BOX: expand this into the finished action, "
                       "keeping everything it asks for, its shots and its timings:\n"
                       + (current or "(nothing yet: write the action from the subjects above)"))
        elif part == "sound":
            system = ("You write the overall_soundscape field of a MiniMax H3 video prompt: 1 to 4 English sentences "
                      "in one paragraph covering ambient sound, physical action sounds and non-verbal human sounds "
                      "across the whole video. Mention an important synchronised sound beside its action. Never "
                      "mention voices, speech, dialogue, whispering or who speaks. Describe the mix in relative words. "
                      "Answer with the paragraph only, without the field name.")
            request = (context + "\n\nTHE ACTION:\n" + (_s(form["action"]) or "(not written yet)")
                       + "\n\nWHAT THE USER TYPED FOR THE SOUND:\n" + (current or "(nothing yet)"))
        elif part == "summary":
            system = ("You write the summary section of a MiniMax H3 reference prompt: one or two plain English "
                      "sentences saying who is in the video, where, and the overall situation, using the <Subject N> "
                      "labels exactly as given. Never retell or paraphrase a spoken line, and never describe "
                      "transitions, timed events or the order of shots. Write no task prefix in square brackets. "
                      "Answer with the sentences only.")
            request = (context + "\n\nTHE ACTION:\n" + (_s(form["action"]) or "(not written yet)")
                       + "\n\nWHAT THE USER TYPED FOR THE SUMMARY:\n" + (current or "(nothing yet)"))
        else:
            system = ("You write the non_diegetic_music field of a MiniMax H3 video prompt: background music only the "
                      "audience hears, in 1 to 3 English sentences about instrumentation, tempo, rhythm and dynamics, "
                      "with no mood words. If the user typed N/A or asked for no music, answer N/A. Answer with the "
                      "text only, without the field name.")
            request = (context + "\n\nTHE ACTION:\n" + (_s(form["action"]) or "(not written yet)")
                       + "\n\nWHAT THE USER TYPED FOR THE MUSIC:\n" + (current or "(nothing yet)"))
        request = request.replace("@", "(at)")
        written = studio._run_enhancer(self.host.state, [request], {request: system}, None,
                                       studio.max_tokens("ref2va" if mode == "Reference" else "fl2va"), progress, think)
        text = _s(written[0] if written else "")
        if part == "action":
            from .h3studio.builder_panel import strip_to_action
            text = strip_to_action(text)
        else:
            if part == "summary":
                text = re.sub(r"^\[[^\]]*\]\s*", "", text)
            for name in ("overall_soundscape:", "non_diegetic_music:", "summary:"):
                if text.lower().startswith(name):
                    text = text[len(name):].strip()
        if not text:
            raise RuntimeError("the enhancer returned nothing usable, so the box is untouched")
        return text, f"{part.title()} written. Read it through; Undo puts back what was there."

    def _write_all(self, payload, progress):
        form = core.clean_form(payload.get("form"))
        idea = _s(payload.get("idea"))
        think = bool(payload.get("think"))
        studio = self._studio()
        media, _, mode, _ = self.resolve(form)
        form = core.expand_names(form, mode)
        family = "ref2va" if mode == "Reference" else "fl2va"
        request = idea or _s(form["action"])
        if not request:
            raise RuntimeError("write an idea first, or some action in the form")
        spec = self.context(form, media, mode)
        if _s(form["action"]) and idea:
            spec += "\n\nALREADY WRITTEN, keep these shots and timings:\n" + _s(form["action"])
        outputs, _, _ = studio.write(
            self.host.state, request, [], family, float(form["duration"] or 0) or None,
            "Ref2VA" if mode == "Reference" else mode, "auto", progress, think, spec_text=spec, plans=None,
            commands_enabled=False,
            force_definitions=core.subject_definitions(form, media) if mode == "Reference" else "")
        text = "\n\n".join(outputs)
        result = self.check_prompt(text)
        problems = len(result["errors"]) + len(result["warnings"])
        return text, ("Written." + (f" {problems} thing(s) to look at: use Check." if problems else ""))
