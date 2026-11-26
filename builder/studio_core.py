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
PARTS = ("face", "hair", "skin", "body type", "clothing", "movement")
IDENTITY = ("face", "hair", "skin", "body type", "clothing")
MAX_LOOKS = 4
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

FORM_KEYS = ("mode", "duration", "summary", "style", "action", "sound", "music", "subjects", "window_duration")


def _s(value) -> str:
    return str(value or "").strip()


def new_subject(kind="Character") -> dict:
    return {"kind": kind, "name": "", "gender": "", "age": "", "ethnicity": "", "height": "", "build": "",
            "hairstyle": "", "haircolor": "", "eyecolor": "", "clothing": "", "details": "", "look": [],
            "parts": list(DEFAULT_PARTS), "sheet": False, "voice": "", "accent": ""}


def new_form() -> dict:
    return {"mode": AUTO, "duration": 10.0, "summary": "", "style": "", "action": "", "sound": "",
            "music": "N/A", "subjects": [], "window_duration": False}


def clean_look(item, parts=None, sheet=False) -> dict:
    """One look source: {"key": media key, "parts": what it provides, "sheet": bool}.
    Older saves held a plain key, with one set of parts for the whole subject."""
    if isinstance(item, dict):
        key = str(item.get("key") or "")
        got = [p for p in (item.get("parts") or []) if p in PARTS]
        return {"key": key, "parts": got or list(DEFAULT_PARTS), "sheet": bool(item.get("sheet"))}
    got = [p for p in (parts or []) if p in PARTS]
    return {"key": str(item or ""), "parts": got or list(DEFAULT_PARTS), "sheet": bool(sheet)}


def clean_subject(data) -> dict:
    out = new_subject()
    if isinstance(data, dict):
        for key in SUBJECT_KEYS:
            if key in data and data[key] is not None:
                out[key] = data[key]
    out["parts"] = [p for p in (out["parts"] or []) if p in PARTS]
    out["sheet"] = bool(out["sheet"])
    out["look"] = [clean_look(i, out["parts"], out["sheet"]) for i in (out["look"] or [])]
    out["look"] = [l for l in out["look"] if l["key"]][:MAX_LOOKS]
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
    form["window_duration"] = bool(form["window_duration"])
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
    concept: str = ""          # the mod's concept type
    pack: str = ""             # the armed pack it came from, if any
    pack_kind: str = ""
    pack_subject: str = ""
    pack_role: str = ""        # its role in that pack (identity, clothing, voice...)

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
    for attr in ("path", "image", "video", "name", "filename"):
        inner = getattr(item, attr, None)
        if isinstance(inner, str) and inner:
            return inner
        if inner and not isinstance(inner, (int, float)):
            return _one_path(inner)
    if hasattr(item, "size") and hasattr(item, "mode"):
        return "image"                    # a picture held in memory, with no file name
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
                         mod.get("label") or None, bool(mod.get("sheet")), str(mod.get("description") or ""),
                         concept=str(mod.get("concept") or ""), pack=str(mod.get("pack") or ""),
                         pack_kind=str(mod.get("pack_kind") or ""), pack_subject=str(mod.get("pack_subject") or ""),
                         pack_role=str(mod.get("role") or "")))
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


def auto_mode(media: list[Media], model: dict | None = None) -> str:
    """Reference whenever references or mods are sent, and always on a Ref2VA
    model: with nothing loaded it still takes the six sections, with subjects
    defined by their descriptions."""
    roles = {m.role for m in media}
    if roles & {"ref", "refvideo", "refaudio", "soundtrack", "mod"} or (model or {}).get("ref2va"):
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
    """([(labels, kind, parts, sheet)] for each look source that is sent, voice label)."""
    looks = []
    for item in subject.get("look") or []:
        item = clean_look(item)
        m = media.get(item["key"])
        if m and m.kind in ("picture", "video") and m.labels:
            looks.append((list(m.labels), m.kind, item["parts"], item["sheet"]))
    voice = media.get(subject.get("voice") or "")
    return looks, (voice.labels[0] if voice and voice.kind == "audio" and voice.labels else "")


PART_NAMES = {"face": "facial features", "hair": "hair", "skin": "skin", "body type": "body type",
              "clothing": "clothing", "movement": "movement"}


def _parts_phrase(parts) -> str:
    return join_labels([PART_NAMES[p] for p in PARTS if p in (parts or [])]) or "visual identity"


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


def _look_sentence(tag: str, subject: dict, labels: list, kind: str, parts: list, sheet: bool) -> str:
    """What one look source provides, in the guide's wording."""
    text = join_labels(labels)
    many = len(labels) > 1
    noun = ("source videos" if many else "source video") if kind == "video" else \
        ("source pictures" if many else "source picture")
    verb = "are" if many else "is"
    pron = pronoun(subject)
    if set(IDENTITY) <= set(parts) and not sheet:
        phrase = "visual identity, facial features and body type"
    else:
        phrase = _parts_phrase(parts)
    only = "only the " if "face" not in parts else "the "
    if sheet:
        who = _s(subject.get("name")) or "figure"
        return (f"{text} {verb} a multi-view reference sheet of one single {gender_noun(subject)}, providing "
                f"{only}{phrase} of {tag}. One single {who} stands in any frame and the sheet's panel layout never "
                "appears as a frame.")
    line = f"{text} {verb} the {noun} providing {only}{phrase} of {tag}"
    if kind == "video" and "movement" not in parts:
        line += (f"; only {pron} appearance is taken from it, and {pron} pose, movement and surroundings follow the "
                 "visual description")
    return line + "."


def _attribution(looks) -> str:
    """'The facial features and hair come from <Video 1>, and the clothing from <Picture 1>'."""
    bits = []
    for labels, _kind, parts, sheet in looks:
        shown = [p for p in parts if p != "movement"]
        if not shown:
            continue
        where = ("one panel of " if sheet else "") + join_labels(labels)
        bits.append((_parts_phrase(shown), where))
    if not bits:
        return ""
    many = " and " in bits[0][0] or "," in bits[0][0]
    first = f"The {bits[0][0]} {'come' if many else 'comes'} from {bits[0][1]}"
    rest = [f"the {p} from {w}" for p, w in bits[1:]]
    return (first + (", and " + ", and ".join(rest) if rest else "")
            + ", exactly as they appear there; everything else comes from the visual description.")


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
        voice_text = (f" {voice} is the audio source providing the specific timbre, pitch and vocal character of "
                      f"{tag}{sid}.") if voice else ""
        if kind == "Character" and looks:
            line = f"{tag}: " + " ".join(_look_sentence(tag, subject, *look) for look in looks) + voice_text
            if desc:
                line += f" {desc[0].upper() + desc[1:]}."
                single_full = len(looks) == 1 and set(IDENTITY) <= set(looks[0][2]) and not looks[0][3]
                if not single_full:
                    line += " " + _attribution(looks)
        elif kind == "Character":
            who = _s(subject.get("name")) or "a character"
            line = f"{tag} is {who}, whose facial identity, build and clothing come from the visual description"
            name = _s(subject.get("name"))
            rest = desc[len(name):].lstrip(", ") if name and desc.startswith(name) else desc
            line += (f": {rest}." if rest else ".") + voice_text
        elif looks:
            sentences = []
            for labels, mkind, _parts, _sheet in looks:
                many = len(labels) > 1
                noun = "source video" if mkind == "video" else ("source pictures" if many else "source picture")
                sentences.append(f"{join_labels(labels)} {'are' if many else 'is'} the {noun} providing the "
                                 f"{_what_for(kind)} of {tag}.")
            line = f"{tag}: " + " ".join(sentences) + (f" {desc[0].upper() + desc[1:]}." if desc else "")
        else:
            line = f"{tag} is {desc or 'described in the shots'}."
        lines.append(line)
    return "\n".join(lines)


def retention_lines(form: dict, media: list[Media]) -> str:
    by_key = media_by_key(media)
    lines = []
    for n, subject in enumerate(form["subjects"], 1):
        tag = f"<Subject {n}>"
        kind = subject.get("kind") or "Character"
        looks, voice = subject_media(subject, by_key)
        for i, (labels, _mkind, parts, sheet) in enumerate(looks):
            others = [(l, p) for j, (l, _k, p, _s2) in enumerate(looks) if j != i]
            for label in labels:
                if kind != "Character":
                    lines.append(f"{label}: fully_preserved. The {_what_for(kind)} of {tag} are kept.")
                    continue
                shown = [p for p in parts if p != "movement"]
                if not shown and "movement" in parts:
                    lines.append(f"{label}: transferred. Only the movement of {tag} follows it; "
                                 f"{pronoun(subject)} appearance comes from elsewhere.")
                    continue
                if set(IDENTITY) <= set(parts) and not sheet:
                    lines.append(f"{label}: fully_preserved. {tag} is kept as shown, including the clothing.")
                    continue
                verb = "are" if len(shown) > 1 else "is"
                kept = f"The {_parts_phrase(shown)} of {tag} " + (
                    f"{verb} taken from one panel of the reference sheet" if sheet else f"{verb} kept")
                elsewhere = []
                for other_labels, other_parts in others:
                    extra = [p for p in other_parts if p not in parts and p != "movement"]
                    if extra:
                        elsewhere.append(f"the {_parts_phrase(extra)} {'come' if len(extra) > 1 else 'comes'} "
                                         f"from {join_labels(other_labels)}")
                missing_clothing = "clothing" not in parts and not any("clothing" in p for _l, p in others)
                if missing_clothing:
                    elsewhere.append("the clothing follows the description")
                tail = "; ".join(elsewhere) or "everything else follows the description"
                lines.append(f"{label}: partially_preserved. {kept}; {tail}.")
        if not looks:
            shots = [f"[Shot {num}]" for num, text in shots_of(form["action"]) if tag in text
                     or (_s(subject.get("name")) and _s(subject.get("name")) in text)]
            if shots:
                lines.append(f"{tag} (appears in {', '.join(shots)}): fully_preserved - follows the visual "
                             "description.")
        if voice:
            lines.append(f"{voice}: reference. Provides the voice timbre, pitch and vocal character of {tag} without "
                         f"copying the original signal, used only for {pronoun(subject)} lines.")
    return "\n".join(lines)


def draft_summary(form: dict, mode: str) -> str:
    """A first summary from the form, in the guide's shape: who and where, for
    you to finish with the situation. Never the dialogue, events or shots."""
    form = clean_form(form)
    reference = mode == "Reference"
    people, places = [], []
    for n, s in enumerate(form["subjects"], 1):
        name = _s(s.get("name"))
        label = f"<Subject {n}>" if reference else (name or f"a {gender_noun(s)}")
        (places if s.get("kind") == "Location" else people).append((label, s))
    if not people and not places:
        return ""
    text = join_labels([p for p, _ in people])
    if places:
        label, place = places[0]
        detail = _s(place.get("details")).rstrip(".")
        if not reference:
            label = detail or label
            detail = ""
        text = (text + " in " if text else "") + label + (f", {detail}" if detail else "")
    return text[0].upper() + text[1:] + "."


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


def duration_command(form: dict) -> str:
    """WanGP's window command for this window's length, e.g. [/duration=10s]."""
    return f"[/duration={float(form['duration'] or 0):g}s]" if form.get("window_duration") else ""


def assemble(form: dict, media: list[Media], mode: str) -> str:
    text = _assemble(clean_form(form), media, mode)
    command = duration_command(clean_form(form))
    return f"{command}\n{text}" if command else text


def _assemble(form: dict, media: list[Media], mode: str) -> str:
    action = no_blank_lines(form["action"])
    style = _s(form["style"])
    sound = no_blank_lines(form["sound"]) or "N/A"
    music = no_blank_lines(form["music"]) or "N/A"
    if mode == "Reference":
        # The guide's default format: each section between its own tags.
        body = "\n".join(b for b in (style, action) if b)
        parts = [("subject_definitions", subject_definitions(form, media) or "N/A"),
                 ("summary", f"{task_prefix(media, form)} {_s(form['summary'])}".strip()),
                 ("retention_analysis", retention_lines(form, media) or "N/A"),
                 ("detailed_description", body),
                 ("overall_soundscape", sound), ("non_diegetic_music", music)]
        return no_blank_lines("\n".join(f"<{name}>\n{text}\n</{name}>" for name, text in parts))
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
        claimed = {}
        for item in subject.get("look") or []:
            item = clean_look(item)
            label = media_by_key(media).get(item["key"])
            where = label.label_text if label else item["key"]
            for part in item["parts"]:
                if part in claimed and claimed[part] != where:
                    warnings.append(f"{name}'s {PART_NAMES[part]} come from both {claimed[part]} and {where}: "
                                    "untick it on one of them")
                claimed.setdefault(part, where)
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


# -- packs and roles into subjects ------------------------------------------------

ROLE_PARTS = {"identity": ["face", "hair", "skin", "body type"], "clothing": ["clothing"],
              "reference sheet": ["clothing"], "pose_motion": ["movement"],
              "generic": ["face", "hair", "skin", "body type"]}
ROLE_KINDS = {"background": "Location", "style": "Style"}


def _short(name: str) -> str:
    return name.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("_", " ")


def subjects_from_media(media: list, existing: list) -> list:
    """New subjects for what's sent and not used by a subject yet.

    An armed character pack becomes one subject: each member a look source
    providing what its role says (a face, a costume sheet, the movement), and
    its voice the subject's voice. A location, prop or style pack becomes one
    subject of that kind. Anything else, mixed packs included, gets a subject
    per picture or video, with a mod's own soundtrack as its voice."""
    used = {l["key"] for s in existing for l in clean_subject(s)["look"]} | {s.get("voice") for s in existing}
    fresh = [m for m in media if m.key not in used and m.labels and m.role not in ("start", "continue", "end")]
    out, done = [], set()
    packs = {}
    for m in fresh:
        if m.pack and m.pack_kind in ("character", "location", "prop", "style"):
            packs.setdefault(m.pack, []).append(m)
    for name, members in packs.items():
        kind = members[0].pack_kind
        subject = new_subject({"character": "Character", "location": "Location", "prop": "Prop",
                               "style": "Style"}[kind])
        subject["name"] = members[0].pack_subject or name
        for m in members:
            done.add(m.key)
            if m.kind == "audio":
                if kind == "character" and not subject["voice"]:
                    subject["voice"] = m.key
                continue
            role = m.pack_role or m.concept or "generic"
            if kind == "character" and role in ROLE_KINDS:
                extra = new_subject(ROLE_KINDS[role])
                extra["name"] = _short(m.name)
                extra["look"] = [{"key": m.key, "parts": list(DEFAULT_PARTS), "sheet": False}]
                out.append(extra)
                continue
            parts = ROLE_PARTS.get(role, list(DEFAULT_PARTS)) if kind == "character" else list(DEFAULT_PARTS)
            subject["look"].append({"key": m.key, "parts": list(parts),
                                    "sheet": role == "reference sheet" or m.sheet})
        subject["look"] = subject["look"][:MAX_LOOKS]
        out.insert(0, subject)
    for m in fresh:
        if m.key in done or m.kind not in ("picture", "video"):
            continue
        role = m.pack_role or m.concept or "generic"
        subject = new_subject(ROLE_KINDS.get(role, "Character"))
        subject["name"] = _short(m.name)
        parts = ROLE_PARTS.get(role, list(DEFAULT_PARTS))
        subject["look"] = [{"key": m.key, "parts": list(parts), "sheet": role == "reference sheet" or m.sheet}]
        voice = next((a for a in fresh if a.kind == "audio" and a.key == f"{m.key}:audio"), None)
        if voice and subject["kind"] == "Character":
            subject["voice"] = voice.key
            done.add(voice.key)
        out.append(subject)
    return out
