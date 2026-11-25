"""
The Prompt Builder's core, without any Gradio: what the generation sends and
the labels it will get, the form, the finished prompt and the checks.

Prompts follow the bundled H3 writing guide (skills/h3-prompt-writing):

- Reference mode (Ref2VA, and FL2VA with mods) uses the six sections with the
  guide's "Reference Prompts: Default Format" wording for subject definitions,
  retention and dialogue.
- T2VA, I2VA, FL2VA and L2VA use base-en's three fields, with the keyframe
  instruction line for I2VA, FL2VA and L2VA.
- No blank lines anywhere, because WanGP's paragraph mode starts a new sliding
  window at every blank line.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict

MODES = ("T2VA", "I2VA", "FL2VA", "L2VA", "Reference")
AUTO = "Auto"

KINDS = ("Character", "Location", "Prop", "Style")
GENDERS = ("", "woman", "man", "girl", "boy", "person")
PARTS = ("face", "hair", "skin", "body type", "clothing")
DEFAULT_PARTS = ["face", "hair", "skin", "body type"]
LANGUAGES = ("English", "French", "German", "Spanish", "Italian", "Portuguese", "Japanese", "Chinese",
             "Korean", "Russian", "Irish", "Arabic", "Hindi")

CAMERA_MOVES = {
    "Push In": "pushes in", "Pull Out": "pulls out", "Zoom In": "zooms in", "Zoom Out": "zooms out",
    "Pan Left": "pans left", "Pan Right": "pans right", "Truck Left": "trucks left",
    "Truck Right": "trucks right", "Tilt Up": "tilts up", "Tilt Down": "tilts down",
    "Pedestal Up": "pedestals up", "Pedestal Down": "pedestals down", "Arc Shot": "arcs around",
    "Tracking Shot": "tracks", "Static Shot": "holds a static shot", "Shake Slightly": "shakes slightly",
    "Shake Strongly": "shakes strongly", "POV": "moves as a point-of-view shot",
    "Roll Clockwise": "rolls clockwise", "Roll Counterclockwise": "rolls counterclockwise",
}
AMPLITUDES = ("", "with small amplitude", "with large amplitude")
SPEEDS = ("", "at slow speed", "at fast speed")

PICTURE_CAP_REF2VA = 12
VIDEO_CAP = 3
AUDIO_CAP = 3
PROMPT_CHAR_LIMIT = 7000
WORDS_PER_SECOND = 2.8

SUBJECT_KEYS = ("kind", "name", "gender", "age", "ethnicity", "height", "build", "hairstyle", "haircolor",
                "eyecolor", "clothing", "details", "look", "parts", "sheet", "voice", "accent")
# What a saved subject keeps. look and voice point at this generation's
# media, so they belong to the project, not the character.
LIBRARY_KEYS = tuple(k for k in SUBJECT_KEYS if k not in ("look", "voice"))

FORM_KEYS = ("mode", "duration", "summary", "style", "action", "sound", "music", "subjects")


def _s(value) -> str:
    return str(value or "").strip()


def new_subject(kind="Character") -> dict:
    return {"kind": kind, "name": "", "gender": "", "age": "", "ethnicity": "", "height": "", "build": "",
            "hairstyle": "", "haircolor": "", "eyecolor": "", "clothing": "", "details": "", "look": [],
            "parts": list(DEFAULT_PARTS), "sheet": False, "voice": "", "accent": ""}


def new_form() -> dict:
    return {"mode": AUTO, "duration": 10.0, "summary": "", "style": "", "action": "", "sound": "",
            "music": "N/A", "subjects": []}


def clean_subject(data) -> dict:
    out = new_subject()
    if isinstance(data, dict):
        for key in SUBJECT_KEYS:
            if key in data and data[key] is not None:
                out[key] = data[key]
    out["look"] = [str(k) for k in (out["look"] or []) if k]
    out["parts"] = [p for p in (out["parts"] or []) if p in PARTS]
    out["sheet"] = bool(out["sheet"])
    out["kind"] = out["kind"] if out["kind"] in KINDS else "Character"
    return out


def clean_form(data) -> dict:
    form = new_form()
    if isinstance(data, dict):
        for key in FORM_KEYS:
            if key in data and data[key] is not None:
                form[key] = data[key]
    form["subjects"] = [clean_subject(s) for s in (form["subjects"] or [])]
    try:
        form["duration"] = float(form["duration"] or 0) or 10.0
    except (TypeError, ValueError):
        form["duration"] = 10.0
    if form["mode"] not in MODES:
        form["mode"] = AUTO
    return form


# -- what the generation sends -----------------------------------------------------

@dataclass
class Media:
    key: str
    kind: str                  # picture | video | audio
    source: str                # gen | mod
    role: str                  # start, continue, end, injected, ref, refvideo, refaudio, soundtrack, mod
    name: str
    count: int = 1
    want: int | None = None
    sheet: bool = False
    description: str = ""
    labels: list = field(default_factory=list)

    @property
    def label_text(self) -> str:
        return join_labels(self.labels)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Media":
        return Media(**{k: data.get(k) for k in Media.__dataclass_fields__ if k in data})


def join_labels(labels) -> str:
    labels = list(labels or [])
    if len(labels) <= 1:
        return labels[0] if labels else ""
    return ", ".join(labels[:-1]) + " and " + labels[-1]


def media_paths(value) -> list:
    """File paths out of whatever a Gallery, Video, Audio or File component holds."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple)) and value and not isinstance(value[0], (str, dict, list, tuple)) \
            and not hasattr(value[0], "path") and not hasattr(value[0], "image"):
        value = [value]
    items = value if isinstance(value, list) else [value]
    out = []
    for item in items:
        path = _one_path(item)
        if path:
            out.append(path)
    return out


def _one_path(item):
    if item is None:
        return None
    if isinstance(item, str):
        return item
    if isinstance(item, (list, tuple)):
        return _one_path(item[0]) if item else None
    if isinstance(item, dict):
        for key in ("image", "video", "path", "name", "url"):
            if key in item and item[key]:
                return _one_path(item[key])
        return None
    for attr in ("path", "image", "video", "name"):
        inner = getattr(item, attr, None)
        if inner:
            return _one_path(inner)
    return str(item)


def detect_media(inputs: dict, model: dict, mods: list) -> list[Media]:
    """
    Everything this generation sends that gets a label, in label order.

    Mirrors the pipeline and Refmods' own count (refmods/patches.py
    _label_offsets): the start or continued frame, the end image, then in
    Ref2VA (or with injected frames) the generation's own reference pictures,
    then the armed mods. Videos and audio are numbered separately.
    """
    ipt, vpt, apt = (_s(inputs.get(k)) for k in ("image_prompt_type", "video_prompt_type", "audio_prompt_type"))
    ref2va = bool(model.get("ref2va"))
    image_model = bool(model.get("image_cap"))
    out: list[Media] = []

    start = media_paths(inputs.get("image_start")) if "S" in ipt else []
    end = media_paths(inputs.get("image_end")) if "E" in ipt else []
    source = media_paths(inputs.get("video_source")) if ("V" in ipt or "L" in ipt) else []
    if start:
        name = os.path.basename(start[0]) + (f" (+{len(start) - 1} queued)" if len(start) > 1 else "")
        out.append(Media("gen:start", "picture", "gen", "start", name))
    elif source:
        out.append(Media("gen:continue", "picture", "gen", "continue", os.path.basename(source[0])))
    if end:
        out.append(Media("gen:end", "picture", "gen", "end", os.path.basename(end[0])))

    refs = media_paths(inputs.get("image_refs"))
    if refs and (((ref2va or image_model) and "I" in vpt) or "F" in vpt or image_model):
        role = "injected" if ("F" in vpt and not ref2va) else "ref"
        for n, path in enumerate(refs, 1):
            out.append(Media(f"gen:ref:{n}", "picture", "gen", role, os.path.basename(path)))

    if ref2va:
        videos = []
        for comp, flag in (("video_guide", "V"), ("video_guide2", "+"), ("video_guide3", "*")):
            paths = media_paths(inputs.get(comp))
            if paths and flag in vpt:
                videos.append(paths[0])
                out.append(Media(f"gen:{comp}", "video", "gen", "refvideo", os.path.basename(paths[0])))
        if "S" not in apt:
            for comp, flag in (("audio_guide", "A"), ("audio_guide2", "B"), ("audio_guide3", "D")):
                paths = media_paths(inputs.get(comp))
                if paths and flag in apt:
                    out.append(Media(f"gen:{comp}", "audio", "gen", "refaudio", os.path.basename(paths[0])))
            if "K" in apt:
                for n, path in enumerate(videos, 1):
                    out.append(Media(f"gen:soundtrack:{n}", "audio", "gen", "soundtrack",
                                     os.path.basename(path) + " (soundtrack)"))

    for mod in mods or []:
        out.append(Media(str(mod.get("key")), str(mod.get("kind") or "picture"), "mod", "mod",
                         str(mod.get("name") or ""), max(1, int(mod.get("count") or 1)),
                         mod.get("label") or None, bool(mod.get("sheet")), str(mod.get("description") or "")))
    assign_labels(out)
    return out


def assign_labels(media: list[Media]) -> None:
    """The generation's own media take the first numbers; mods follow, on the
    number picked for them in the Refmods panel where there is one, Auto ones
    filling the gaps (refmods/plugin.py _ordered_labels)."""
    words = {"picture": "Picture", "video": "Video", "audio": "Audio"}
    for kind, word in words.items():
        own = [m for m in media if m.kind == kind and m.source == "gen"]
        position = 1
        for m in own:
            m.labels = [f"<{word} {position}>"]
            position += 1
        mods = [m for m in media if m.kind == kind and m.source == "mod"]
        explicit = sorted((m for m in mods if m.want), key=lambda m: m.want)
        auto = [m for m in mods if not m.want]
        while explicit or auto:
            m = explicit.pop(0) if explicit and (explicit[0].want <= position or not auto) else auto.pop(0)
            m.labels = [f"<{word} {position + i}>" for i in range(m.count)]
            position += m.count


def auto_mode(media: list[Media]) -> str:
    roles = {m.role for m in media}
    if roles & {"ref", "refvideo", "refaudio", "soundtrack", "mod"}:
        return "Reference"
    keyframe_start = bool(roles & {"start", "continue"})
    if keyframe_start and "end" in roles:
        return "FL2VA"
    if keyframe_start:
        return "I2VA"
    if "end" in roles:
        return "L2VA"
    return "T2VA"


def media_by_key(media: list[Media]) -> dict:
    return {m.key: m for m in media}


def media_summary(media: list[Media]) -> str:
    """'1 start image, 2 reference images and 3 armed mods' for the mode line."""
    counts = {}
    for m in media:
        name = {"start": "start image", "continue": "continued video", "end": "end image",
                "injected": "injected frame", "ref": "reference image", "refvideo": "reference video",
                "refaudio": "audio reference", "soundtrack": "video soundtrack",
                "mod": "armed mod"}.get(m.role, m.role)
        if m.role == "mod" and m.key.endswith(":audio"):
            continue
        counts[name] = counts.get(name, 0) + 1
    parts = [f"{n} {name}{'s' if n > 1 else ''}" for name, n in counts.items()]
    return join_labels(parts) if parts else "nothing"


# -- describing subjects -------------------------------------------------------------

def pronoun(subject: dict) -> str:
    gender = _s(subject.get("gender")).lower()
    return {"woman": "her", "girl": "her", "man": "his", "boy": "his"}.get(gender, "their")


def gender_noun(subject: dict) -> str:
    return _s(subject.get("gender")).lower() or "person"


def display_name(subject: dict, index: int) -> str:
    return _s(subject.get("name")) or f"Subject {index}"


def describe(subject: dict) -> str:
    """The creator's fields as one sentence, without a trailing full stop."""
    kind = subject.get("kind") or "Character"
    name = _s(subject.get("name"))
    details = _s(subject.get("details")).rstrip(".")
    if kind != "Character":
        bits = [b for b in (name, details) if b]
        return ", ".join(bits)
    age = _s(subject.get("age"))
    gender = _s(subject.get("gender")) or ("person" if any(_s(subject.get(k)) for k in
                                                          ("height", "build", "ethnicity")) else "")
    lead = []
    if age and age.isdigit():
        lead.append(f"{age}-year-old")
    for key in ("height", "build", "ethnicity"):
        if _s(subject.get(key)):
            lead.append(_s(subject.get(key)))
    noun = " ".join(lead + ([gender] if gender else []))
    text = f"a {noun}" if noun else ""
    if age and not age.isdigit():
        text += (" " if text else "") + (f"in {pronoun(subject)} {age}" if age.endswith("s") else age)
    hair = " ".join(_s(subject.get(k)) for k in ("hairstyle", "haircolor") if _s(subject.get(k)))
    eyes = _s(subject.get("eyecolor"))
    withs = []
    if hair:
        withs.append(f"{hair} hair")
    if eyes:
        withs.append(f"{eyes} eyes")
    if withs:
        text += (" " if text else "") + "with " + " and ".join(withs)
    clothing = _s(subject.get("clothing")).rstrip(".")
    if clothing:
        text += (", " if text else "") + f"wearing {clothing}"
    lead_text = ", ".join(b for b in (name, text) if b)
    return ". ".join(b for b in (lead_text, details) if b)


def subject_media(subject: dict, media: dict) -> tuple[list, str]:
    """(picture-or-video labels for the look, audio label for the voice)."""
    looks = []
    for key in subject.get("look") or []:
        m = media.get(key)
        if m and m.kind in ("picture", "video"):
            looks.extend(m.labels)
    voice = media.get(subject.get("voice") or "")
    return looks, (voice.labels[0] if voice and voice.kind == "audio" and voice.labels else "")


def _parts_phrase(parts) -> str:
    names = {"face": "facial features", "hair": "hair", "skin": "skin", "body type": "body type",
             "clothing": "clothing"}
    return join_labels([names[p] for p in PARTS if p in (parts or [])]) or "visual identity"


def _what_for(kind: str) -> str:
    return {"Location": "layout, materials and lighting", "Prop": "shape, materials and colours",
            "Style": "visual style, colour palette and texture"}.get(kind, "")


# -- speaker IDs ---------------------------------------------------------------------

def speaker_ids(action: str, subjects: list, reference: bool) -> dict:
    """{subject index (1-based): 'S1'} in order of who first speaks in the
    action, read off the speaker tags the Dialogue button writes."""
    found = {}
    for n, subject in enumerate(subjects, 1):
        tags = [f"<Subject {n}>"] if reference else []
        name = _s(subject.get("name"))
        if name:
            tags.append(name)
        best = None
        for tag in tags:
            m = re.search(re.escape(tag) + r"\s*\((S\d+)\)", action or "")
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), m.group(1))
        if best:
            found[n] = best
    return {n: sid for n, (_, sid) in sorted(found.items(), key=lambda kv: kv[1][0])}


def next_speaker_id(action: str) -> str:
    used = [int(x) for x in re.findall(r"\(S(\d+)\)", action or "")]
    return f"S{(max(used) if used else 0) + 1}"


# -- assembling the prompt -----------------------------------------------------------

def no_blank_lines(text: str) -> str:
    return "\n".join(line.rstrip() for line in (text or "").replace("\r\n", "\n").split("\n") if line.strip())


def shots_of(action: str) -> list[tuple[int, str]]:
    """[(shot number, text of that shot)] in order."""
    parts = re.split(r"(?=\[Shot \d+\])", action or "")
    out = []
    for part in parts:
        m = re.match(r"\[Shot (\d+)\]", part)
        if m:
            out.append((int(m.group(1)), part))
    return out


def shot_times(action: str) -> list[tuple[int, float]]:
    out = []
    for number, text in shots_of(action):
        m = re.match(r"\[Shot \d+\]\s*At (\d+):(\d+(?:\.\d+)?)", text)
        out.append((number, int(m.group(1)) * 60 + float(m.group(2)) if m else 0.0))
    return out


def timestamp(seconds) -> str:
    try:
        seconds = max(0.0, float(seconds or 0))
    except (TypeError, ValueError):
        seconds = 0.0
    minutes = int(seconds // 60)
    return f"{minutes:02d}:{seconds - minutes * 60:06.3f}"


def task_prefix(media: list[Media], form: dict) -> str:
    roles = {m.role for m in media}
    tasks = []
    if "continue" in roles:
        tasks.append("video continuation")
    if roles & {"start", "end", "injected"}:
        tasks.append("keyframe completion")
    tasks.append("reference generation")
    used_audio = any(m.kind == "audio" for m in media) and any(s.get("voice") for s in form["subjects"])
    if used_audio or any(m.kind == "audio" and m.role != "mod" for m in media):
        tasks.append("audio reference")
    return "[" + " + ".join(tasks) + "]"


def subject_definitions(form: dict, media: list[Media]) -> str:
    by_key = media_by_key(media)
    sids = speaker_ids(form["action"], form["subjects"], True)
    lines = []
    for n, subject in enumerate(form["subjects"], 1):
        tag = f"<Subject {n}>"
        looks, voice = subject_media(subject, by_key)
        desc = describe(subject)
        kind = subject.get("kind") or "Character"
        sid = f" ({sids[n]})" if n in sids else ""
        if kind == "Character" and looks:
            parts = subject.get("parts") or list(DEFAULT_PARTS)
            full = set(PARTS) <= set(parts) and not subject.get("sheet")
            phrase = "visual identity, facial features and body type" if full else _parts_phrase(parts)
            pics = join_labels(looks)
            if subject.get("sheet"):
                who = _s(subject.get("name")) or "figure"
                line = (f"{tag}: {pics} {'is' if len(looks) == 1 else 'are'} a multi-view reference sheet of one "
                        f"single {gender_noun(subject)}, providing the {phrase} of {tag}. One single {who} stands "
                        "in any frame and the sheet's panel layout never appears as a frame.")
            else:
                line = (f"{tag}: {pics} {'is the source picture' if len(looks) == 1 else 'are the source pictures'}"
                        f" providing the {phrase} of {tag}.")
            if voice:
                line += (f" {voice} is the audio source providing the specific timbre, pitch and vocal character "
                         f"of {tag}{sid}.")
            if desc:
                line += f" {desc[0].upper() + desc[1:]}."
                if not full:
                    where = "from one panel of " + pics if subject.get("sheet") else "from " + pics
                    line += (f" The {_parts_phrase(parts)} come {where}, exactly as they appear there; everything "
                             "else comes from the visual description.")
        elif kind == "Character":
            who = _s(subject.get("name")) or "a character"
            line = f"{tag} is {who}, whose facial identity, build and clothing come from the visual description"
            rest = desc[len(_s(subject.get("name"))):].lstrip(", ") if desc.startswith(_s(subject.get("name"))) \
                and _s(subject.get("name")) else desc
            line += (f": {rest}." if rest else ".")
            if voice:
                line += (f" {voice} is the audio source providing the specific timbre, pitch and vocal character "
                         f"of {tag}{sid}.")
        elif looks:
            line = (f"{tag}: {join_labels(looks)} {'is the source picture' if len(looks) == 1 else 'are the source pictures'}"
                    f" providing the {_what_for(kind)} of {tag}." + (f" {desc[0].upper() + desc[1:]}." if desc else ""))
        else:
            line = f"{tag} is {desc or 'described in the shots'}."
        lines.append(line)
    return "\n".join(lines)


def retention_lines(form: dict, media: list[Media]) -> str:
    by_key = media_by_key(media)
    lines, covered = [], set()
    for n, subject in enumerate(form["subjects"], 1):
        tag = f"<Subject {n}>"
        kind = subject.get("kind") or "Character"
        looks, voice = subject_media(subject, by_key)
        if looks:
            parts = subject.get("parts") or list(DEFAULT_PARTS)
            for label in looks:
                covered.add(label)
                if kind != "Character":
                    lines.append(f"{label}: fully_preserved. The {_what_for(kind)} of {tag} are kept.")
                elif subject.get("sheet"):
                    lines.append(f"{label}: partially_preserved. The {_parts_phrase(parts)} of {tag} are taken from "
                                 "one panel of the reference sheet; everything else follows the description.")
                elif set(PARTS) <= set(parts):
                    lines.append(f"{label}: fully_preserved. {tag} is kept as shown, including the clothing.")
                else:
                    tail = ("the clothing follows the description" if "clothing" not in parts
                            else "everything else follows the description")
                    lines.append(f"{label}: partially_preserved. The {_parts_phrase(parts)} of {tag} are kept; {tail}.")
        else:
            shots = [f"[Shot {num}]" for num, text in shots_of(form["action"]) if tag in text
                     or (_s(subject.get("name")) and _s(subject.get("name")) in text)]
            if shots:
                lines.append(f"{tag} (appears in {', '.join(shots)}): fully_preserved - follows the visual "
                             "description.")
        if voice:
            covered.add(voice)
            lines.append(f"{voice}: reference. Provides the voice timbre, pitch and vocal character of {tag} without "
                         f"copying the original signal, used only for {pronoun(subject)} lines.")
    return "\n".join(lines)


def keyframe_line(mode: str, form: dict) -> str:
    shots = shots_of(form["action"])
    last = shots[-1][0] if shots else 1
    seconds = f"{float(form['duration'] or 0):.2f}"
    if mode == "I2VA":
        return "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
    if mode == "FL2VA":
        return ("How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the "
                f"0.00-second mark of the target video; Picture 2 (from Shot {last}) aligns with the {seconds}-second "
                "mark of the target video.")
    if mode == "L2VA":
        return (f"How the reference pictures align with the target video — <Picture 1> (from [Shot {last}]) aligns "
                f"with the {seconds}-second mark of the target video.")
    return ""


def assemble(form: dict, media: list[Media], mode: str) -> str:
    form = clean_form(form)
    action = no_blank_lines(form["action"])
    style = _s(form["style"])
    sound = no_blank_lines(form["sound"]) or "N/A"
    music = no_blank_lines(form["music"]) or "N/A"
    if mode == "Reference":
        body = "\n".join(b for b in (style, action) if b)
        sections = ["subject_definitions:", subject_definitions(form, media) or "N/A",
                    "summary:", f"{task_prefix(media, form)} {_s(form['summary'])}".strip(),
                    "retention_analysis:", retention_lines(form, media) or "N/A",
                    "detailed_description:", body,
                    f"overall_soundscape: {sound}", f"non_diegetic_music: {music}"]
        return no_blank_lines("\n".join(sections))
    lines = []
    instruction = keyframe_line(mode, form)
    if instruction:
        lines.append(instruction)
    body = " ".join(b for b in (style, action) if b)
    lines.append(f"integrated_multimodal_description: {body}")
    lines.append(f"overall_soundscape: {sound}")
    lines.append(f"non_diegetic_music: {music}")
    return no_blank_lines("\n".join(lines))


# -- checks ------------------------------------------------------------------------

VOICE_WORDS = re.compile(r"\b(voice|voices|speech|speaks|speaking|dialogue|whisper\w*|murmur\w*|says|talk\w*)\b", re.I)


def checks(form: dict, media: list[Media], mode: str, text: str, detected: str, model: dict,
           lint_check=None) -> dict:
    """{"errors": [...], "warnings": [...], "info": [...]}: what is wrong,
    what is worth a look, and the counts against H3's limits."""
    form = clean_form(form)
    errors, warnings, info = [], [], []
    by_kind = {k: [m for m in media if m.kind == k] for k in ("picture", "video", "audio")}
    sent = {label for m in media for label in m.labels}

    if lint_check is not None and _s(form["action"]):
        try:
            report = lint_check(text, "Ref2VA" if mode == "Reference" else mode, float(form["duration"] or 0) or None, 1)
            errors += [e.replace("Window 1: ", "") for e in report.get("errors", [])]
            for w in report.get("warnings", []):
                w = w.replace("Window 1: ", "")
                # The guide's default format keys retention by <Picture N> / <Audio N>,
                # so a subject whose pictures have their lines needs no line of its own.
                if w.startswith("retention_analysis has no line for <Subject"):
                    keyed = {n for n, s in enumerate(form["subjects"], 1) if s.get("look")}
                    missing = [int(x) for x in re.findall(r"<Subject (\d+)>", w)]
                    if all(n in keyed for n in missing):
                        continue
                if "words; 350-500 is normal" in w:
                    info.append(w)
                    continue
                warnings.append(w)
        except Exception as exc:                      # noqa: BLE001
            warnings.append(f"the format check could not run ({type(exc).__name__})")

    cited = set(re.findall(r"<(?:Picture|Video|Audio) \d+>", text))
    if mode == "Reference":
        defined = subject_definitions(form, media)
        for label in sorted(cited - sent):
            errors.append(f"{label} is in the prompt but nothing loaded or armed will get that label")
        for m in media:
            if m.role in ("start", "continue", "end"):
                continue
            loose = [label for label in m.labels if label in form["action"] and label not in defined]
            if loose:
                warnings.append(f"{join_labels(loose)} ({m.name}) is used in the action but belongs to no subject: "
                                "add it as a subject (a Prop or Location) so it gets a definition")
            unused = [label for label in m.labels if label not in cited]
            if unused:
                warnings.append(f"{join_labels(unused)} ({m.name}) is sent but never used in the prompt: it still "
                                "loads and can show up")
    if mode != AUTO and mode != detected and form["mode"] != AUTO:
        warnings.append(f"the mode is set to {mode} but what's loaded looks like {detected}")

    if mode == "Reference":
        cap = model.get("image_cap") or PICTURE_CAP_REF2VA
        pictures = sum(len(m.labels) for m in by_kind["picture"])
        if pictures > cap:
            warnings.append(f"{pictures} pictures is more than the {cap} this model was trained on")
        if len(by_kind["video"]) > VIDEO_CAP:
            warnings.append(f"{len(by_kind['video'])} videos: only {VIDEO_CAP} get a label")
        if len(by_kind["audio"]) > AUDIO_CAP:
            warnings.append(f"{len(by_kind['audio'])} audio references: H3 takes {AUDIO_CAP}")
        info.append(f"{pictures} of {cap} pictures · {len(by_kind['video'])} of {VIDEO_CAP} videos · "
                    f"{len(by_kind['audio'])} of {AUDIO_CAP} audio")

    sids = speaker_ids(form["action"], form["subjects"], mode == "Reference")
    for n, subject in enumerate(form["subjects"], 1):
        name = display_name(subject, n)
        if not describe(subject) and not subject.get("look"):
            warnings.append(f"subject {n} has no description and no picture")
        if subject.get("voice") and n not in sids:
            warnings.append(f"{name} has a voice but no line yet")
        if mode == "Reference" and f"<Subject {n}>" not in form["action"]:
            warnings.append(f"<Subject {n}> ({name}) is defined but never appears in the action")

    times = shot_times(form["action"])
    duration = float(form["duration"] or 0)
    if times:
        stamps = [t for _, t in times[1:]]
        if any(b <= a for a, b in zip([0.0] + stamps, stamps)):
            errors.append("shot times must go up from one shot to the next")
        if stamps and duration and stamps[-1] >= duration:
            errors.append(f"[Shot {times[-1][0]}] starts at {timestamp(stamps[-1])}, past the {duration:g} s length")
        info.append(f"{len(times)} shot{'s' if len(times) != 1 else ''} in {duration:g} s")
    words = sum(len(line.split()) for line in re.findall(r"<d>\s*(?:\[[^\]]*\])?(.*?)</d>", form["action"], re.S))
    if words and duration:
        seconds = words / WORDS_PER_SECOND
        if seconds > duration - 0.5:
            warnings.append(f"the dialogue needs about {seconds:.1f} s at {WORDS_PER_SECOND} words a second, which "
                            f"doesn't fit in {duration:g} s")
    if VOICE_WORDS.search(form["sound"] or ""):
        warnings.append("the sound box mentions voices or speech: keep it to ambience and effects, since the "
                        "model places any voice named there")
    if mode == "Reference" and len(re.findall(r"[.!?](\s|$)", _s(form["summary"]))) > 2:
        warnings.append("keep the summary to one or two sentences: who, where and the situation")
    if len(text) > PROMPT_CHAR_LIMIT:
        warnings.append(f"{len(text):,} characters is past H3's {PROMPT_CHAR_LIMIT:,}")
    info.append(f"{len(text):,} of {PROMPT_CHAR_LIMIT:,} characters")
    return {"errors": _dedupe(errors), "warnings": _dedupe(warnings), "info": info}


def _dedupe(items):
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


# -- what the insert buttons write -------------------------------------------------

def shot_snippet(action: str, at) -> str:
    shots = shots_of(action)
    if not shots:
        return "[Shot 1] "
    return f"[Shot {shots[-1][0] + 1}] At {timestamp(at)}, the camera cuts to "


def camera_snippet(move: str, amplitude: str = "", speed: str = "") -> str:
    verb = CAMERA_MOVES.get(move, "")
    if not verb:
        return ""
    return " ".join(b for b in ("The camera", verb, amplitude, speed) if b) + " "


def subject_snippet(subjects: list, index: int, mode: str, action: str) -> str:
    """<Subject N> in Reference mode. In the base modes there are no subject
    labels, so the first mention writes the description and later ones the
    name; at the start of a sentence it gets a capital."""
    if not (1 <= index <= len(subjects)):
        return ""
    subject = subjects[index - 1]
    if mode == "Reference":
        return f"<Subject {index}>"
    name = _s(subject.get("name"))
    if name and name in (action or ""):
        text = name
    else:
        desc = describe(subject)
        text = (desc + ",") if desc and desc != name else (name or f"Subject {index}")
    tail = (action or "").rstrip()
    if not tail or tail.endswith(("]", ".", "!", "?", ":")):
        text = text[:1].upper() + text[1:]
    return text


def dialogue_snippet(subjects: list, index: int, media: list[Media], mode: str, action: str, tone: str,
                     language: str, voiceover: bool, line: str, at=None) -> str:
    if not (1 <= index <= len(subjects)):
        return ""
    subject = subjects[index - 1]
    reference = mode == "Reference"
    sids = speaker_ids(action, subjects, reference)
    sid = sids.get(index) or next_speaker_id(action)
    _, voice = subject_media(subject, media_by_key(media))
    who = f"<Subject {index}>" if reference else (_s(subject.get("name")) or f"the {gender_noun(subject)}")
    tone = _s(tone).rstrip(".")
    accent = _s(subject.get("accent"))
    bits = [f"{who} ({sid})"]
    if voice and reference:
        delivery = f"in the voice following {voice}"
        if tone:
            delivery += f", with a {tone} tone"
    else:
        if reference and _s(subject.get("name")):
            bits.append(_s(subject.get("name")))
        delivery = f"a {gender_noun(subject)} speaking" + (f" with a {tone} tone" if tone else "")
    if accent:
        delivery += f", in {'an' if accent[:1].lower() in 'aeiou' else 'a'} {accent} accent"
    bits.append(delivery)
    lead = ", ".join(bits)
    words = f"<d>[{_s(language) or 'English'}] {_s(line)}</d>"
    if voiceover:
        text = f"{lead}, says in an off-screen voiceover: {words} while {pronoun(subject)} lips remain completely closed."
    elif voice and reference:
        text = f"{lead}, says: {words}"
    else:
        text = f"{lead}, says, {pronoun(subject)} lips moving: {words}"
    if at not in (None, "") and float(at or 0) > 0:
        text = f"At {timestamp(at)}, {text}"
    return text + " "


# -- reading what older builders saved -----------------------------------------------

def subject_from_library(blob: dict) -> dict:
    """A saved subject, from this builder (format 5) or the 4.x one."""
    if not isinstance(blob, dict):
        return new_subject()
    if isinstance(blob.get("subject"), dict):
        return clean_subject(blob["subject"])
    fields = blob.get("fields") if isinstance(blob.get("fields"), dict) else {}
    out = new_subject()
    mapping = {"char_name": "name", "char_gender": "gender", "char_age": "age", "char_ethnicity": "ethnicity",
               "char_height": "height", "char_build": "build", "char_hairstyle": "hairstyle",
               "char_haircolor": "haircolor", "char_eyecolor": "eyecolor", "char_clothing": "clothing",
               "accent": "accent"}
    for old, new in mapping.items():
        if _s(fields.get(old)):
            out[new] = _s(fields.get(old))
    if not out["gender"] and _s(fields.get("gender")):
        out["gender"] = _s(fields.get("gender")).lower()
    if out["gender"] not in GENDERS:
        out["gender"] = {"female": "woman", "male": "man"}.get(out["gender"], "")
    if not out["age"] and _s(fields.get("age")):
        out["age"] = _s(fields.get("age"))
    out["details"] = _s(fields.get("desc"))
    return out


def form_from_v4(d: dict) -> dict:
    """A 4.x form, as the 4.x builder's _unpack reads it, mapped across."""
    form = new_form()
    style_bits = [d.get(k) for k in ("style", "grading", "camera_type", "location", "time_of_day", "lighting",
                                     "atmosphere")]
    form["style"] = ", ".join(_s(b) for b in style_bits if _s(b))
    form["summary"] = _s(d.get("summary_text"))
    form["action"] = _s(d.get("action"))
    form["sound"] = _s(d.get("soundscape"))
    form["music"] = _s(d.get("music")) or "N/A"
    try:
        form["duration"] = float(d.get("duration") or 10)
    except (TypeError, ValueError):
        pass
    if d.get("ref_mode"):
        form["mode"] = "Reference"
    for entry in (d.get("entries") or [])[:int(d.get("entry_count") or 0)]:
        if not _s(entry.get("desc")):
            continue
        subject = new_subject()
        subject["details"] = _s(entry.get("desc"))
        subject["gender"] = _s(entry.get("gender")).lower() if _s(entry.get("gender")).lower() in GENDERS else ""
        subject["age"] = _s(entry.get("age"))
        subject["accent"] = _s(entry.get("accent"))
        form["subjects"].append(subject)
    return form
