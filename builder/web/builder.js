/* Refmods Studio: the Prompt Builder page.
   Python does the work (labels, the prompt in the H3 guide's format, the checks, saving, the prompt enhancer);
   this file draws the form and keeps it in step. The page runs in a frame on the Prompt Builder tab, on WanGP's own
   origin, so it writes into the Generator page's prompt box directly. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const BOXES = ["summary", "style", "action", "sound", "music"];
  const SCENE = [["scStyle", "style"], ["scLoc", "location"], ["scTime", "time"], ["scLight", "lighting"],
                 ["scAir", "atmosphere"], ["scGrade", "grade"], ["scBody", "body"]];
  const S = {
    session: null, vocab: null, selected: 0, lastBox: "action", actionUsed: false,
    undo: {}, preview: null, timers: {}, capturedAt: 0,
    form: { mode: "Auto", duration: 10, window_duration: false, summary: "", style: "", action: "", sound: "",
            music: "N/A", subjects: [] },
  };

  // ---------------------------------------------------------------- helpers
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  async function api(path, body) {
    const opts = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const res = await fetch("api/" + path, opts);
    if (!res.ok) throw new Error(res.status + " " + res.statusText);
    return res.json();
  }
  function status(text) { $("status").textContent = text || ""; }
  function later(name, fn, ms) { clearTimeout(S.timers[name]); S.timers[name] = setTimeout(fn, ms); }
  function options(select, items, value) {
    select.innerHTML = items.map((it) => {
      const [v, label] = Array.isArray(it) ? it : [it, it === "" ? "—" : it];
      return `<option value="${esc(v)}"${String(v) === String(value) ? " selected" : ""}>${esc(label)}</option>`;
    }).join("");
  }
  function newSubject(kind) {
    return { kind: kind || "Character", name: "", gender: "", age: "", ethnicity: "", height: "", build: "",
             hairstyle: "", haircolor: "", eyecolor: "", clothing: "", details: "", look: [],
             parts: (S.vocab ? S.vocab.default_parts : []).slice(), sheet: false, voice: "", accent: "" };
  }
  function changed() { later("preview", refreshPreview, 200); later("draft", saveDraft, 1500); }

  // ---------------------------------------------------------------- theme: follow WanGP
  function theme() {
    let dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    try {
      const doc = window.parent && window.parent !== window ? window.parent.document : null;
      if (doc) dark = doc.body.classList.contains("dark") || doc.documentElement.classList.contains("dark") ||
        !!doc.querySelector("gradio-app.dark, .gradio-container.dark");
    } catch (_) { /* opened on its own */ }
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }

  // ---------------------------------------------------------------- the Generator page's prompt box
  function promptBox() {
    try {
      const doc = window.parent.document;
      for (const id of ["wangp-prompt-advanced", "wangp-prompt-wizard"]) {
        const box = doc.querySelector(`#${id} textarea`);
        if (box && box.offsetParent !== null) return box;
      }
      return doc.querySelector("#wangp-prompt-advanced textarea") || doc.querySelector("#wangp-prompt-wizard textarea");
    } catch (_) { return null; }
  }
  function setPrompt(text) {
    const box = promptBox();
    if (!box) { status("Couldn't reach the Generator page's prompt box."); return false; }
    box.value = text;
    const Ev = (box.ownerDocument.defaultView || window).Event;
    box.dispatchEvent(new Ev("input", { bubbles: true }));
    return true;
  }
  function appendWindow(current, text, cut) {
    current = (current || "").replace(/\s+$/, "");
    if (!text.trim()) return null;
    if (!current) return text;
    if (cut) {
      if (text.startsWith("[/")) { const end = text.indexOf("]"); text = text.slice(0, end) + ",/new_shot" + text.slice(end); }
      else text = "[/new_shot]\n" + text;
    }
    return current + "\n\n" + text;
  }

  // ---------------------------------------------------------------- inserting at the cursor
  function insertInto(id, text, atEnd) {
    const el = $(id);
    if (!el || !text) return;
    let start = el.selectionStart, end = el.selectionEnd;
    if (atEnd || start == null) { start = end = el.value.length; }
    const before = el.value.slice(0, start);
    // A sentence from a button starts with a capital, unless it follows a comma or a lowercase word.
    if (/^(The (camera|shot|frame)|Shot (on|using)|An? |At \d)/.test(text)) {
      const tail = before.replace(/\s+$/, "");
      if (/[,;:]$|[a-z]$/.test(tail)) text = text[0].toLowerCase() + text.slice(1);
    }
    const pad = before && !/\s$/.test(before) && !/^\s/.test(text) ? " " : "";
    el.setRangeText(pad + text, start, end, "end");
    el.focus();
    S.form[id] = el.value;
    changed();
  }
  async function snippet(kind) {
    const args = {
      at: parseFloat($("at").value) || 0, move: $("camMove").value, amplitude: $("camAmp").value, speed: $("camSpeed").value,
      framing: $("camFraming").value, rig: $("camRig").value, lens: $("camLens").value, of: $("camOf").value, verb: $("camVerb").value,
      body: $("scBody").value,
      index: kind === "line" ? parseInt($("dWho").value || "0", 10) : parseInt($("subjSel").value || "0", 10),
      tone: $("dTone").value, language: $("dLang").value, voiceover: $("dVo").checked, line: $("dLine").value,
      delivery: $("dAct").value, same_as: $("dSame").value, cutoff: $("dCut").checked, carry: $("dCarry").value,
      style: $("scStyle").value, location: $("scLoc").value, time: $("scTime").value, lighting: $("scLight").value,
      atmosphere: $("scAir").value, grade: $("scGrade").value, text: $("sndPreset").value,
      instruments: $("muInst").value, tempo: $("muTempo").value, dynamics: $("muDyn").value,
      kind: $("txKind").value, words: $("txWords").value,
    };
    if ((kind === "subject" || kind === "line") && !args.index) { status("Add a subject first."); return; }
    if (kind === "line" && !args.line.trim()) { status("Type the line first."); $("dLine").focus(); return; }
    const { text } = await api("snippet", { kind, form: S.form, args });
    if (!text) {
      if (kind === "camera") status("Pick a framing, rig, lens, what's in frame or a move first.");
      if (kind === "scene") status("Fill in at least one of the scene's boxes first.");
      return;
    }
    if (kind === "scene") { addSentence("style", text); return; }
    if (kind === "sound" || kind === "music") { addSentence(kind, text); return; }
    if (kind === "subject") insertInto(S.lastBox, text, false);
    else insertInto("action", text, !S.actionUsed);
    if (kind === "line") { $("dLine").value = ""; $("dAct").value = ""; $("dSame").value = ""; $("dCut").checked = false; $("dCarry").value = ""; }
    if (kind === "text") $("txWords").value = "";
  }
  // Add buttons build a box up: a sentence already there isn't added twice, and N/A gives way.
  function addSentence(id, text) {
    const el = $(id);
    const cur = el.value.trim();
    text = text.trim();
    if (cur.replace(/\.$/, "").toLowerCase().includes(text.replace(/\.$/, "").toLowerCase())) { status("That's already there."); return; }
    el.value = (/^n\/a\.?$/i.test(cur) || !cur) ? text : cur + " " + text;
    S.form[id] = el.value;
    changed();
  }
  // Times of the lines already written, offered for "same voice as line at".
  function lineStamps() {
    const stamps = [...new Set(((S.form.action || "").match(/\bAt (\d\d:\d\d\.\d{3})/g) || []).map((t) => t.slice(3)))];
    $("lsStamps").innerHTML = stamps.map((t) => `<option value="${t}">`).join("");
  }

  // ---------------------------------------------------------------- header, chips
  function drawModes(detected) {
    const modes = ["Auto"].concat(S.vocab.modes);
    $("modes").innerHTML = modes.map((m) => {
      const on = S.form.mode === m;
      const auto = m !== "Auto" && m === detected ? '<span class="auto">auto</span>' : "";
      return `<button type="button" data-mode="${m}" class="${on ? "on" : ""} ${m === detected ? "detected" : ""}" aria-pressed="${on}">${m}${auto}</button>`;
    }).join("");
  }
  function drawChips(unused) {
    const media = (S.session && S.session.media) || [];
    const skip = new Set(unused || []);
    if (!media.length) {
      $("chips").innerHTML = '<span class="muted small">Nothing loaded on the Generator page gets a label: no start or end image, references or armed mods.</span>';
      return;
    }
    $("chips").innerHTML = media.filter((m) => m.labels && m.labels.length).map((m) => {
      const kind = m.kind === "audio" ? "aud" : (m.source === "mod" ? "mod" : "gen");
      const text = m.labels.length > 1 ? m.labels.slice(0, -1).join(", ") + " and " + m.labels[m.labels.length - 1] : m.labels[0];
      const what = { start: "start frame", continue: "continued video", end: "end frame", injected: "injected", ref: "ref",
                     refvideo: "ref video", refaudio: "ref audio", soundtrack: "soundtrack", mod: "mod" }[m.role] || m.role;
      const thumb = m.kind === "picture" && m.source === "gen" ? `<img src="api/thumb/${encodeURIComponent(m.key)}" alt="" onerror="this.replaceWith(Object.assign(document.createElement('span'),{className:'ph'}))">` : '<span class="ph"></span>';
      return `<button type="button" class="chip ${kind}${skip.has(m.key) ? " unused" : ""}" data-insert="${esc(text)}" title="Insert ${esc(text)}">${thumb}${esc(text)} <small>${esc(what)} · ${esc(m.name)}</small></button>`;
    }).join("");
  }
  function captureNote() {
    const s = S.session;
    let note = "";
    if (!s || !s.captured) note = "Open the Video Generator tab, load your references and arm any mods, then come back: the builder reads them each time you open this tab.";
    else {
      const when = new Date(s.captured_at * 1000).toLocaleTimeString();
      note = `Read from the Generator page at ${when}${s.model && s.model.name ? " · " + s.model.name : ""}. It updates each time you open this tab.`;
      if (s.model && !s.model.h3) note += " The selected model isn't MiniMax H3.";
      if (s.error) note += " " + s.error;
    }
    $("captureNote").textContent = note;
  }

  // ---------------------------------------------------------------- subjects
  function mediaChoices(kinds, none) {
    const media = (S.session && S.session.media) || [];
    const out = [["", none]];
    for (const m of media) {
      if (!kinds.includes(m.kind) || ["start", "continue", "end"].includes(m.role) || !m.labels.length) continue;
      const label = m.labels.length > 1 ? m.labels[0] + "–" + m.labels[m.labels.length - 1] : m.labels[0];
      out.push([m.key, `${label} · ${m.name}`]);
    }
    return out;
  }
  function subjectName(s, n) { return (s.name || "").trim() || `Subject ${n}`; }
  function drawCards() {
    const count = S.form.subjects.length;
    $("subCount").textContent = count ? `(${count})` : "";
    const subs = S.form.subjects;
    if (!subs.length) {
      $("cards").innerHTML = '<div class="empty">No subjects yet. Press <b>+ New subject</b> to start one.</div>';
    } else {
      $("cards").innerHTML = subs.map((s, i) => {
        const n = i + 1;
        const looks = (s.look || []).filter((l) => l.key).length;
        const look = looks ? `${looks} source${looks > 1 ? "s" : ""}` : "description only";
        const voice = s.voice ? "voice from a reference" : "gender and tone";
        return `<div class="scard${i === S.selected ? " on" : ""}" data-card="${i}" role="button" tabindex="0">
          <div class="top"><strong>${n} · ${esc(subjectName(s, n))}</strong><span class="muted small">${esc(s.kind)}</span>
          <span class="tools"><span data-move="${i}:-1" title="Move up">↑</span><span data-move="${i}:1" title="Move down">↓</span><span data-remove="${i}" title="Remove">✕</span></span></div>
          <div class="sub">Look: ${look}${(s.kind || "Character") === "Character" ? " · Voice: " + voice : ""}</div></div>`;
      }).join("");
    }
    const choices = subs.length ? subs.map((s, i) => [i + 1, `${i + 1} · ${subjectName(s, i + 1)}`]) : [["", "no subjects yet"]];
    options($("subjSel"), choices, $("subjSel").value || 1);
    options($("dWho"), choices, $("dWho").value || 1);
  }
  function drawEditor() {
    const s = S.form.subjects[S.selected];
    if (!s) { $("editor").innerHTML = ""; return; }
    const v = S.vocab;
    const field = (key, label, ph) => `<label class="fld">${label}<input data-f="${key}" value="${esc(s[key])}" placeholder="${esc(ph || "")}"></label>`;
    const select = (key, label, items) => `<label class="fld">${label}<select data-f="${key}">${items.map((it) => {
      const [val, text] = Array.isArray(it) ? it : [it, it || "—"];
      return `<option value="${esc(val)}"${String(val) === String(s[key] || "") ? " selected" : ""}>${esc(text)}</option>`;
    }).join("")}</select></label>`;
    const character = (s.kind || "Character") === "Character";
    const looks = (s.look || []).slice();
    if (looks.length < v.max_looks) looks.push({ key: "", parts: v.default_parts.slice(), sheet: false });   // one free row
    const visual = mediaChoices(["picture", "video"], "none");
    const rows = looks.map((l, i) => `<div class="look" data-look="${i}">
        <span class="muted small">Source ${i + 1}</span>
        <select data-lk="key">${visual.map(([val, text]) => `<option value="${esc(val)}"${val === l.key ? " selected" : ""}>${esc(text)}</option>`).join("")}</select>
        ${character ? `<span class="muted small">provides</span>
        ${v.parts.map((p) => `<button type="button" class="toggle" data-part="${p}" aria-pressed="${(l.parts || []).includes(p)}">${p}</button>`).join("")}
        <label class="inline small"><input type="checkbox" data-lk="sheet"${l.sheet ? " checked" : ""}> reference sheet</label>`
        : `<input type="checkbox" data-lk="sheet" hidden>${(l.parts || []).map((p) => `<button type="button" data-part="${p}" aria-pressed="true" hidden></button>`).join("")}`}
      </div>`).join("");
    const people = character ? `
      <div class="grid5">${select("kind", "Kind", v.kinds)}${field("name", "Name")}${select("gender", "Gender", v.genders)}${field("age", "Age", "34, thirties")}${field("ethnicity", "Ethnicity")}
        ${field("height", "Height")}${field("build", "Build")}${field("hairstyle", "Hairstyle")}${field("haircolor", "Hair colour")}${field("eyecolor", "Eye colour")}</div>
      ${field("clothing", "Clothing")}
      ${field("details", "Anything else the camera sees")}
      <div class="grid3">${select("voice", "Voice comes from", mediaChoices(["audio"], "nothing: gender and tone only"))}${field("accent", "Accent (only if wanted)", "Irish")}<span></span></div>
      <div class="muted small">Look comes from: pick each picture, video or mod this subject uses and tick what it provides. Leaving out clothing makes it partially preserved. Leave the sources on none for description only.</div>`
      : `
      <div class="grid3">${select("kind", "Kind", v.kinds)}${field("name", "Name")}<span></span></div>
      ${field("details", "Description", "What the camera sees")}
      <div class="muted small">Look comes from: the pictures or mods showing it. Leave on none to describe it in words only.</div>`;
    $("editor").innerHTML = `
      <div class="card-head"><span class="cap">Subject ${S.selected + 1} · ${character ? "character creator" : esc(s.kind.toLowerCase())}</span><span class="muted small">Leave a field blank to skip it.</span><span class="grow"></span>
        <label class="inline small" title="Off leaves this subject's line out of subject_definitions"><input type="checkbox" data-sw="def_off"${s.def_off ? "" : " checked"}> definition line</label>
        <label class="inline small" title="Off leaves this subject's rows out of retention_analysis"><input type="checkbox" data-sw="ret_off"${s.ret_off ? "" : " checked"}> retention rows</label>
        <button type="button" class="small" id="btnLibSave">Save to library</button></div>
      ${people}
      ${rows}`;
  }
  function editorInput(e) {
    const s = S.form.subjects[S.selected];
    if (!s) return;
    const t = e.target;
    if (t.dataset.sw) { s[t.dataset.sw] = !t.checked; changed(); return; }
    if (t.dataset.f) {
      s[t.dataset.f] = t.value;
      if (t.dataset.f === "name" || t.dataset.f === "kind") drawCards();
      if (t.dataset.f === "kind") drawEditor();
    } else if (t.dataset.lk) {
      const row = t.closest("[data-look]");
      const i = parseInt(row.dataset.look, 10);
      readLooks();
      void i;
      drawCards();
      if (t.dataset.lk === "key" && e.type === "change") drawEditor();   // a free row for the next source
    } else return;
    changed();
  }
  function readLooks() {
    const s = S.form.subjects[S.selected];
    const looks = [];
    document.querySelectorAll("#editor [data-look]").forEach((row) => {
      const key = row.querySelector('[data-lk="key"]').value;
      const parts = [...row.querySelectorAll("[data-part]")].filter((b) => b.getAttribute("aria-pressed") === "true").map((b) => b.dataset.part);
      const sheet = row.querySelector('[data-lk="sheet"]').checked;
      looks.push({ key, parts, sheet });
    });
    s.look = looks.filter((l) => l.key);
  }

  // ---------------------------------------------------------------- the form
  function loadForm(form, note) {
    S.form = Object.assign({ mode: "Auto", duration: 10, window_duration: false, summary: "", style: "", action: "",
                             sound: "", music: "N/A", subjects: [], off: [], ref_layout: false, scene: {} }, form || {});
    S.selected = 0;
    S.tagUndo = null; $("tagUndo").hidden = true;   // an undo belongs to the prompt it was made in
    $("duration").value = S.form.duration;
    $("winDur").checked = !!S.form.window_duration;
    $("refLayout").checked = !!S.form.ref_layout;
    $("scratch").value = S.form.scratch || "";
    for (const [id, key] of SCENE) $(id).value = (S.form.scene || {})[key] || "";
    if (S.form.scratch) $("scratchBox").open = true;
    for (const id of BOXES) $(id).value = S.form[id] || "";
    drawCards(); drawEditor(); refreshPreview();
    if (note) status(note);
  }
  async function refreshPreview() {
    try {
      const out = await api("preview", { form: S.form });
      S.preview = out;
      $("preview").innerHTML = highlight(out.text);
      hlAll();
      drawSections();
      $("detected").textContent = `Picked from the Generator page: ${out.summary} → ${out.detected}` +
        (S.form.mode !== "Auto" ? ` · writing ${out.mode}` : "");
      drawModes(out.detected);
      const base = S.form.mode === "Auto" ? out.detected : S.form.mode;
      $("refLayoutBox").hidden = base === "Reference";
      drawChips(out.unused);
      drawChecks($("checks"), out.checks);
    } catch (err) { status("Preview failed: " + err.message); }
  }
  function drawChecks(list, c) {
    const items = [].concat((c.errors || []).map((t) => ["e", "Error: " + t]), (c.warnings || []).map((t) => ["w", t]), (c.info || []).map((t) => ["i", t]));
    list.innerHTML = (items.length ? items : [["i", "Nothing to fix."]]).map(([k, t]) => `<li class="${k}">${esc(t)}</li>`).join("");
  }
  function highlight(text) {
    let h = esc(text);
    h = h.replace(/^(\[\/[^\]]*\])/gm, '<span class="cmd">$1</span>');
    h = h.replace(/&lt;(\/?)(subject_definitions|summary|retention_analysis|detailed_description|overall_soundscape|non_diegetic_music)&gt;/g, '<span class="tag">&lt;$1$2&gt;</span>');
    h = h.replace(/&lt;d&gt;([\s\S]*?)&lt;\/d&gt;/g, '<span class="d">&lt;d&gt;$1&lt;/d&gt;</span>');
    h = h.replace(/\[Shot \d+\]( At \d+:\d+\.\d+)?/g, '<span class="shot">$&</span>');
    h = h.replace(/&lt;Subject \d+&gt;/g, '<span class="s">$&</span>').replace(/&lt;Picture \d+&gt;/g, '<span class="p">$&</span>')
         .replace(/&lt;Video \d+&gt;/g, '<span class="v">$&</span>').replace(/&lt;Audio \d+&gt;/g, '<span class="a">$&</span>');
    return h;
  }
  async function saveDraft() {
    try { const r = await api("draft", { form: S.form }); status(r.note); } catch (_) { /* next change tries again */ }
  }

  // ---------------------------------------------------------------- the prompt enhancer
  async function runJob(payload, onDone, button) {
    if (button) button.disabled = true;
    try {
      const { id } = await api("jobs", payload);
      S.job = id;
      for (;;) {
        await new Promise((r) => setTimeout(r, 600));
        const st = await api("jobs/" + id);
        if (st.progress && st.progress.total) status(`${st.progress.desc || "Enhancing"} ${st.progress.done}/${st.progress.total}`);
        if (st.done) {
          if (st.error) status("Nothing written: " + st.error); else onDone(st);
          break;
        }
      }
    } catch (err) { status("The enhancer failed: " + err.message); }
    if (button) button.disabled = false;
    S.job = null;
  }
  function enhance(part, button) {
    status(`Asking the prompt enhancer for the ${part}…`);
    runJob({ kind: "enhance", part, form: S.form, think: $("think").checked }, (st) => {
      S.undo[part] = $(part).value;
      $(part).value = st.text; S.form[part] = st.text; changed(); status(st.note);
    }, button);
  }

  // ---------------------------------------------------------------- tags: swap, remove, renumber
  const TAG_RE = /<(Subject|Picture|Video|Audio) (\d+)>|\(S(\d+)\)/g;
  const tagText = (kind, n) => (kind === "S" ? `(S${n})` : `<${kind} ${n}>`);
  function tagAt(text, pos) {
    TAG_RE.lastIndex = 0;
    let m;
    while ((m = TAG_RE.exec(text))) {
      if (pos >= m.index && pos <= m.index + m[0].length) return { kind: m[1] || "S", n: +(m[2] || m[3]), start: m.index, end: m.index + m[0].length, text: m[0] };
    }
    return null;
  }
  function mapTags(fn, boxes) {
    for (const b of boxes) {
      const v = S.form[b] || "";
      const nv = v.replace(TAG_RE, (m0, k, n1, n2) => { const r = fn(k || "S", +(n1 || n2)); return r === undefined ? m0 : r; })
        .replace(/[ \t]{2,}/g, " ").replace(/ +([,.;:!?])/g, "$1");
      if (nv !== v) { S.form[b] = nv; $(b).value = nv; }
    }
  }
  const swapTags = (kind, a, b, boxes) => mapTags((k, n) => (k !== kind ? undefined : n === a ? tagText(kind, b) : n === b ? tagText(kind, a) : undefined), boxes);
  function swapSubjects(a, b) {
    if (a === b) return;
    swapTags("Subject", a, b, BOXES);
    const s = S.form.subjects; [s[a - 1], s[b - 1]] = [s[b - 1], s[a - 1]];
  }
  function removeSubject(n) {
    mapTags((k, m) => (k !== "Subject" ? undefined : m === n ? "" : m > n ? tagText("Subject", m - 1) : undefined), BOXES);
    S.form.subjects.splice(n - 1, 1);
    S.selected = Math.min(S.selected, Math.max(0, S.form.subjects.length - 1));
  }
  function mediaOf(kind, n) {
    return ((S.session && S.session.media) || []).find((m) => (m.labels || []).includes(tagText(kind, n)));
  }
  function candidates(kind) {
    if (kind === "Subject") return S.form.subjects.map((s, i) => [i + 1, subjectName(s, i + 1)]);
    if (kind === "S") {
      const ids = new Set();
      BOXES.forEach((b) => (S.form[b] || "").replace(/\(S(\d+)\)/g, (_, d) => { ids.add(+d); return _; }));
      for (let i = 1; i <= ids.size + 1; i++) ids.add(i);
      return [...ids].sort((a, b) => a - b).map((i) => [i, "speaker"]);
    }
    const out = [];
    ((S.session && S.session.media) || []).forEach((m) => (m.labels || []).forEach((l) => {
      const mm = l.match(/^<(\w+) (\d+)>$/);
      if (mm && mm[1] === kind) out.push([+mm[2], m.name]);
    }));
    return out;
  }
  // Snapshots, so a tag change can be undone in one click.
  const snap = () => JSON.stringify({ boxes: Object.fromEntries(BOXES.map((b) => [b, S.form[b] || ""])), subjects: S.form.subjects });
  function done(before, note) {
    S.tagUndo = before;
    $("tagUndo").hidden = false;
    drawCards(); drawEditor(); changed(); status(note);
  }
  function undoTags() {
    if (!S.tagUndo) return;
    const d = JSON.parse(S.tagUndo);
    BOXES.forEach((b) => { S.form[b] = d.boxes[b]; $(b).value = d.boxes[b]; });
    S.form.subjects = d.subjects;
    S.selected = Math.min(S.selected, Math.max(0, S.form.subjects.length - 1));
    S.tagUndo = null; $("tagUndo").hidden = true;
    drawCards(); drawEditor(); changed(); status("Undone.");
  }
  function closeMenu() { $("ctx").hidden = true; }
  function tagMenu(e, box) {
    const el = $(box), sel = el.value.slice(el.selectionStart, el.selectionEnd);
    const tag = tagAt(el.value, el.selectionStart);
    if (!tag && !sel.trim()) return;                 // the browser's own menu
    e.preventDefault();
    let scope = tag && (tag.kind === "Subject" || tag.kind === "S") ? "all" : "all";
    const name = tag ? (tag.kind === "Subject" ? (S.form.subjects[tag.n - 1] ? subjectName(S.form.subjects[tag.n - 1], tag.n) : "no such subject")
      : tag.kind === "S" ? "speaker ID" : ((mediaOf(tag.kind, tag.n) || {}).name || "not sent")) : "";
    const others = tag ? candidates(tag.kind).filter(([n]) => n !== tag.n) : [];
    const menu = $("ctx");
    menu.innerHTML = (tag ? `<div class="h">${esc(tag.text)} · ${esc(name)}</div>
      <div class="scope">${[["one", "Here"], ["box", "This box"], ["all", "Everywhere"]].map(([v, l]) => `<button data-scope="${v}" class="${v === scope ? "on" : ""}">${l}</button>`).join("")}</div>
      ${others.map(([n, label]) => `<button data-swap="${n}">Swap with ${esc(tagText(tag.kind, n))}${label ? ` <span class="muted small">${esc(label)}</span>` : ""}</button>`).join("")}
      <button data-act="remove">Remove ${esc(tag.text)}</button>` : "") +
      (sel.trim() ? `${tag ? "<hr>" : ""}<button data-act="phrase">Save as phrase</button><button data-act="copy">Copy</button><button data-act="cut">Cut</button><button data-act="delete">Remove the selection</button>` : "") +
      `<hr><div class="h" style="text-transform:none;letter-spacing:0;font-weight:400">Shift+right-click for the browser's menu</div>`;
    menu.hidden = false;
    const r = menu.getBoundingClientRect();
    menu.style.left = Math.min(e.clientX, innerWidth - r.width - 8) + "px";
    menu.style.top = Math.min(e.clientY, innerHeight - r.height - 8) + "px";
    menu.onclick = async (ev) => {
      const b = ev.target.closest("button"); if (!b) return;
      if (b.dataset.scope) { scope = b.dataset.scope; menu.querySelectorAll("[data-scope]").forEach((x) => x.classList.toggle("on", x === b)); return; }
      closeMenu();
      const before = snap();
      if (b.dataset.act === "phrase") { openPhrases(sel); return; }
      if (b.dataset.act === "copy" || b.dataset.act === "cut") { try { await navigator.clipboard.writeText(sel); } catch (_) { /* no clipboard here */ } }
      if (b.dataset.act === "cut" || b.dataset.act === "delete") {
        el.setRangeText("", el.selectionStart, el.selectionEnd, "start"); S.form[box] = el.value; done(before, b.dataset.act === "cut" ? "Cut." : "Removed."); return;
      }
      if (b.dataset.act === "copy") { status("Copied."); return; }
      if (!tag) return;
      const where = scope === "one" ? "here" : scope === "box" ? `in ${box}` : "everywhere";
      if (b.dataset.swap) {
        const to = +b.dataset.swap;
        if (scope === "one") { el.setRangeText(tagText(tag.kind, to), tag.start, tag.end, "end"); S.form[box] = el.value; }
        else if (scope === "box") swapTags(tag.kind, tag.n, to, [box]);
        else if (tag.kind === "Subject") swapSubjects(tag.n, to);
        else swapTags(tag.kind, tag.n, to, BOXES);
        done(before, `Swapped ${tag.text} and ${tagText(tag.kind, to)} ${where}` + (scope === "all" && tag.kind === "Subject" ? ", with their subjects." : "."));
        return;
      }
      if (b.dataset.act === "remove") {
        let note = `Removed ${tag.text} ${where}.`;
        if (scope === "one") { el.setRangeText("", tag.start, tag.end, "start"); S.form[box] = el.value; mapTags(() => undefined, [box]); }
        else if (scope === "box") mapTags((k, n) => (k === tag.kind && n === tag.n ? "" : undefined), [box]);
        else if (tag.kind === "Subject") { removeSubject(tag.n); note = `Removed ${tag.text} and its subject; the later subjects moved up.`; }
        else {
          mapTags((k, n) => (k === tag.kind && n === tag.n ? "" : undefined), BOXES);
          const m = tag.kind !== "S" && mediaOf(tag.kind, tag.n);
          if (m && (m.labels || []).length === 1) {          // its definition and retention lines go too
            S.form.subjects.forEach((s) => { s.look = (s.look || []).filter((l) => l.key !== m.key); if (s.voice === m.key) s.voice = ""; });
            note += " It's no longer a source for any subject.";
          }
        }
        done(before, note);
      }
    };
  }

  // ---------------------------------------------------------------- !Name: a subject by name
  const sug = { box: null, items: [], i: 0, start: 0 };
  function nameSuggest(box) {
    const el = $(box), pos = el.selectionStart, before = el.value.slice(0, pos);
    const m = before.match(/(^|[^\w])!([A-Za-z][\w' -]*)?$/);
    const names = S.form.subjects.map((s, i) => (s.name || "").trim()).filter(Boolean);
    if (!m || !names.length) { hideSuggest(); return; }
    const part = (m[2] || "").toLowerCase();
    const items = names.filter((n) => n.toLowerCase().startsWith(part) && n.toLowerCase() !== part);
    if (!items.length) { hideSuggest(); return; }
    Object.assign(sug, { box, items, i: 0, start: pos - (m[2] || "").length });
    const r = el.getBoundingClientRect(), list = $("suggest");
    list.innerHTML = items.map((n, i) => `<div data-i="${i}" class="${i === 0 ? "on" : ""}">!${esc(n)}</div>`).join("") +
      `<div class="muted small" style="cursor:default">Tab completes · Esc closes</div>`;
    list.hidden = false;
    list.style.left = r.left + 8 + "px"; list.style.top = Math.min(r.bottom + 2, innerHeight - list.offsetHeight - 6) + "px";
    list.onmousedown = (e) => { const d = e.target.closest("[data-i]"); if (d) { e.preventDefault(); sug.i = +d.dataset.i; completeName(); } };
  }
  function hideSuggest() { $("suggest").hidden = true; sug.box = null; }
  function completeName() {
    const el = $(sug.box), name = sug.items[sug.i];
    el.setRangeText(name, sug.start, el.selectionStart, "end");
    S.form[sug.box] = el.value; hideSuggest(); changed();
  }
  function suggestKeys(e) {
    if (!sug.box || $("suggest").hidden) return false;
    if (e.key === "Tab" || e.key === "Enter") { e.preventDefault(); completeName(); return true; }
    if (e.key === "Escape") { e.preventDefault(); hideSuggest(); return true; }
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault(); sug.i = (sug.i + (e.key === "ArrowDown" ? 1 : sug.items.length - 1)) % sug.items.length;
      $("suggest").querySelectorAll("[data-i]").forEach((d) => d.classList.toggle("on", +d.dataset.i === sug.i)); return true;
    }
    return false;
  }

  // ---------------------------------------------------------------- phrases
  const PH = { items: [], target: "action" };
  async function openPhrases(text) {
    PH.target = S.lastBox;
    try { PH.items = (await api("phrases")).phrases; } catch (_) { PH.items = []; }
    $("phText").value = text || "";
    drawPhrases();
    $("phraseDlg").showModal();
    (text ? $("phNewCat") : $("phSearch")).focus();
  }
  function drawPhrases() {
    const cats = [...new Set(PH.items.map((p) => p.category || "General"))].sort();
    options($("phCat"), [["", "All categories"]].concat(cats.map((c) => [c, c])), $("phCat").value);
    $("phCats").innerHTML = cats.map((c) => `<option value="${esc(c)}">`).join("");
    const q = $("phSearch").value.toLowerCase(), cat = $("phCat").value;
    const list = PH.items.filter((p) => (!cat || p.category === cat) && (!q || p.text.toLowerCase().includes(q) || (p.category || "").toLowerCase().includes(q)));
    $("phList").innerHTML = list.length ? list.map((p) => `<div class="ph" data-id="${esc(p.id)}"><span class="t">${esc(p.text)}</span><span class="c">${esc(p.category || "")}</span><span class="x" data-del="${esc(p.id)}" title="Delete">✕</span></div>`).join("")
      : `<div class="empty">${PH.items.length ? "No phrase matches." : "No phrases yet. Select text in a box and press Ctrl+Enter, or type one below."}</div>`;
  }
  async function savePhrase() {
    const r = await api("phrases", { text: $("phText").value, category: $("phNewCat").value });
    status(r.note);
    if (r.ok) { PH.items = r.phrases; $("phText").value = ""; drawPhrases(); }
  }

  // ---------------------------------------------------------------- section switches
  const SECTIONS = ["subject_definitions", "summary", "retention_analysis", "overall_soundscape", "non_diegetic_music"];
  function drawSections() {
    const reference = !S.preview || S.preview.mode === "Reference";
    const shown = reference ? SECTIONS : SECTIONS.slice(3);
    const off = S.form.off || [];
    $("sections").innerHTML = shown.map((name) => `<button type="button" data-sec="${name}" aria-pressed="${!off.includes(name)}" title="${off.includes(name) ? "Off: left out of the prompt" : "On"}">${name}</button>`).join("");
  }

  // ---------------------------------------------------------------- packs
  // The Refmods panel on the Generator page has a hidden box; writing a pack's name there runs its Add pack.
  function armPack(name) {
    try {
      const doc = window.parent.document;
      const box = doc.querySelector("#rs-pack-bridge textarea") || doc.querySelector("#rs-pack-bridge input");
      if (!box) return false;
      const W = box.ownerDocument.defaultView;
      const proto = box.tagName === "TEXTAREA" ? W.HTMLTextAreaElement.prototype : W.HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(proto, "value").set.call(box, JSON.stringify({ name, replace: false, at: Date.now() }));
      box.dispatchEvent(new W.Event("input", { bubbles: true }));
      box.dispatchEvent(new W.Event("change", { bubbles: true }));
      return true;
    } catch (_) { return false; }
  }
  let packNames = "";
  async function loadPacks() {
    try {
      const r = await api("packs");
      const sig = JSON.stringify(r.packs);
      if (sig === packNames) return;
      packNames = sig;
      options($("packSel"), [["", "packs"]].concat(r.packs.map((p) => [p.name, p.name + (p.character ? "" : " (no character yet)")])), $("packSel").value);
    } catch (_) { /* Refmods is off */ }
  }
  async function loadPack() {
    const name = $("packSel").value;
    if (!name) { status("Pick a pack first."); return; }
    const arming = armPack(name);
    status(arming ? `Arming ${name} in the Refmods panel…` : "Couldn't reach the Refmods panel on the Generator page.");
    let r = null;
    for (let i = 0; i < (arming ? 14 : 1); i++) {
      if (i) await new Promise((ok) => setTimeout(ok, 500));
      try { r = await api("pack/load", { name, form: S.form }); } catch (err) { status(err.message); return; }
      if (!r.ok || r.armed) break;
    }
    if (!r.ok) { status(r.note); return; }
    S.form.subjects = r.form.subjects; S.selected = r.selected;
    drawCards(); drawEditor(); changed(); loadSession(false); status(r.note);
  }
  async function savePack() {
    const subject = S.form.subjects[S.selected];
    if (!subject) { status("Pick or make a subject first."); return; }
    const r = await api("pack/save", { name: $("packSel").value || subject.name, subject });
    status(r.note);
    if (r.ok) { packNames = ""; await loadPacks(); $("packSel").value = r.name; }
  }

  // ---------------------------------------------------------------- full screen (WanGP's own, as the Video Editor uses)
  function fullscreen() {
    const SVG = (d) => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${d}"/></svg>`;
    const EXPAND = SVG("M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"), EXIT = SVG("M10 4H5v16h5M14 8l4 4-4 4M18 12H9");
    const box = $("fsBox");
    let button = null, pdoc = null;
    try {
      const nav = window.parent !== window && window.frameElement && window.parent.WanGPAddonNavigation;
      if (!nav) return;
      const before = box.children.length;
      nav.headerButton(window.frameElement, box, "fsbtn");
      button = box.children.length > before ? box.lastElementChild : null;
      pdoc = window.parent.document;
    } catch (_) { return; }
    const paint = () => {
      const on = pdoc.documentElement.classList.contains("wangp-addon-fullscreen-open");
      document.documentElement.classList.toggle("rs-full", on);
      if (button) { button.title = on ? "Back to WanGP (Esc)" : "Open Full Screen"; button.setAttribute("aria-label", button.title); button.innerHTML = on ? EXIT : EXPAND; }
    };
    new MutationObserver(paint).observe(pdoc.documentElement, { attributes: true, attributeFilter: ["class"] });
    paint();
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !e.defaultPrevented && button && document.documentElement.classList.contains("rs-full") &&
          !document.querySelector("dialog[open]") && $("ctx").hidden && $("suggest").hidden) button.click();
    });
    $("subSwitch").querySelectorAll("button[data-sub]").forEach((b) => b.addEventListener("click", () => {
      const tab = [...pdoc.querySelectorAll(".rs-studio-tabs button[role=tab]")].find((t) => t.textContent.trim() === b.dataset.sub);
      if (tab) tab.click();
    }));
  }

  // ---------------------------------------------------------------- session
  async function loadSession(first) {
    try {
      const s = await api("session");
      const fresh = s.captured_at !== S.capturedAt;
      S.session = s; S.vocab = s.vocab; S.capturedAt = s.captured_at;
      if (first) {
        options($("camMove"), [["", "move"]].concat(S.vocab.camera.map((m) => [m, m])), "");
        options($("camVerb"), [["", "Auto"]].concat(S.vocab.cuts.map((v) => [v, v.replace("the ", "")]), S.vocab.continues.map((v) => [v, v.replace("the ", "")])), "");
        const list = (id, items) => { $(id).innerHTML = items.filter(Boolean).map((v) => `<option value="${esc(v)}">`).join(""); };
        list("lsFraming", S.vocab.framings); list("lsRig", S.vocab.rigs); list("lsLens", S.vocab.lenses); list("lsBody", S.vocab.bodies);
        options($("camAmp"), S.vocab.amplitudes.map((a) => [a, a || "amplitude"]), "");
        options($("camSpeed"), S.vocab.speeds.map((a) => [a, a || "speed"]), "");
        options($("dLang"), S.vocab.languages, "English");
        options($("dCarry"), [["", "line ends in its shot"]].concat(S.vocab.carries.map((c) => [c, "carries: " + c])), "");
        list("lsStyle", S.vocab.styles); list("lsLoc", S.vocab.locations); list("lsTime", S.vocab.times);
        list("lsLight", S.vocab.lighting); list("lsAir", S.vocab.atmospheres); list("lsGrade", S.vocab.grades);
        list("lsSound", S.vocab.soundscapes); list("lsInst", S.vocab.instruments); list("lsTempo", S.vocab.tempos);
        list("lsDyn", S.vocab.dynamics); list("lsTextKind", S.vocab.text_kinds);
      }
      options($("loadSel"), [["", "saved prompts"]].concat(s.lists.prompts), $("loadSel").value);
      options($("libSel"), [["", "saved subjects"]].concat(s.lists.subjects), $("libSel").value);
      loadPacks();
      captureNote();
      if (fresh || first) { drawEditor(); refreshPreview(); }
    } catch (err) { status("Couldn't reach the builder's server: " + err.message); }
  }

  // ---------------------------------------------------------------- coloured tag chips
  // A layer behind each box draws the tags in colour; the box itself stays a plain textarea.
  const HL = [
    [/&lt;Subject \d+&gt;/g, "k-s"], [/&lt;Picture \d+&gt;/g, "k-p"], [/&lt;Video \d+&gt;/g, "k-v"], [/&lt;Audio \d+&gt;/g, "k-a"],
    [/\[Shot \d+\]|\bAt \d\d:\d\d\.\d{3}/g, "k-shot"], [/&lt;(scenetrans|cutoff)&gt;/g, "k-x"], [/![A-Za-z][\w'-]*/g, "k-n"],
  ];
  function hlHtml(text) {
    let h = esc(text);
    h = h.replace(/&lt;d&gt;[\s\S]*?&lt;\/d&gt;/g, (m) => `\u0001d\u0002${m}\u0003`);
    for (const [re, cls] of HL) h = h.replace(re, (m) => `\u0001${cls}\u0002${m}\u0003`);
    return h.replace(/\u0001([\w-]+)\u0002/g, (_, c) => `<mark class="${c === "d" ? "k-d" : c}">`).replace(/\u0003/g, "</mark>") + "\n ";
  }
  function hlInit() {
    for (const id of BOXES.concat(["scratch"])) {
      const ta = $(id);
      if (!ta || ta.parentNode.classList.contains("hlwrap")) continue;
      const wrap = document.createElement("div");
      wrap.className = "hlwrap";
      ta.parentNode.insertBefore(wrap, ta);
      const back = document.createElement("div");
      back.className = "hlback";
      back.setAttribute("aria-hidden", "true");
      wrap.appendChild(back); wrap.appendChild(ta);
      ta.addEventListener("input", () => hlSync(id));
      ta.addEventListener("scroll", () => { back.scrollTop = ta.scrollTop; });
      if (window.ResizeObserver) new ResizeObserver(() => hlSync(id)).observe(ta);
    }
    hlAll();
  }
  function hlSync(id) {
    const ta = $(id), back = ta && ta.previousSibling;
    if (!back || !back.classList || !back.classList.contains("hlback")) return;
    const cs = getComputedStyle(ta);
    Object.assign(back.style, {
      top: ta.offsetTop + ta.clientTop + "px", left: ta.offsetLeft + ta.clientLeft + "px",
      width: ta.clientWidth + "px", height: ta.clientHeight + "px",
      padding: cs.padding, font: cs.font, lineHeight: cs.lineHeight, letterSpacing: cs.letterSpacing, tabSize: cs.tabSize,
    });
    back.innerHTML = hlHtml(ta.value);
    back.scrollTop = ta.scrollTop;
  }
  function hlAll() { for (const id of BOXES.concat(["scratch"])) hlSync(id); }

  // ---------------------------------------------------------------- prompt library
  let libItems = [];
  async function openLibrary() {
    try { libItems = (await api("library")).items || []; } catch (err) { status(err.message); return; }
    const cats = [...new Set(libItems.map((p) => p.category).filter(Boolean))].sort();
    options($("libCat"), [["", "all categories"]].concat(cats), cats.includes($("libCat").value) ? $("libCat").value : "");
    drawLibrary();
    $("libDlg").showModal();
    $("libSearch").focus();
  }
  function drawLibrary() {
    const q = $("libSearch").value.trim().toLowerCase(), cat = $("libCat").value, fav = $("libFav").checked;
    const cats = [...new Set(libItems.map((p) => p.category).filter(Boolean))];
    const shown = libItems.filter((p) => (!cat || p.category === cat) && (!fav || p.fav) &&
      (!q || (p.name + " " + p.text + " " + p.category + " " + p.packs.join(" ")).toLowerCase().includes(q)));
    $("libList").innerHTML = shown.length ? shown.map((p) => `<div class="item" data-name="${esc(p.name)}">
        <button class="star" data-star title="${p.fav ? "Unstar" : "Star"}">${p.fav ? "★" : "☆"}</button>
        <div class="body" data-open><b>${esc(p.name)}</b> <span class="muted small">${esc(p.mode || "")} · ${esc(p.saved)}${p.packs.length ? " · packs: " + esc(p.packs.join(", ")) : ""}</span>
          <div class="t">${esc(p.text) || "<i>empty</i>"}</div></div>
        <input class="cat small" data-cat list="libCats" value="${esc(p.category)}" placeholder="category" aria-label="Category">
        <button class="small" data-open>Load</button>${p.packs.length ? '<button class="small" data-arm title="Load it and arm its packs in the Refmods panel">Load + arm packs</button>' : ""}
        <button class="small" data-del title="Moves it to prompts/deleted">Delete</button></div>`).join("")
      + `<datalist id="libCats">${cats.map((c) => `<option value="${esc(c)}">`).join("")}</datalist>`
      : '<div class="muted small">No saved prompts match.</div>';
  }
  async function libraryClick(e) {
    const item = e.target.closest(".item");
    if (!item) return;
    const name = item.dataset.name, p = libItems.find((x) => x.name === name);
    if (e.target.closest("[data-star]")) {
      p.fav = !p.fav; await api("library/meta", { name, fav: p.fav }); drawLibrary(); return;
    }
    if (e.target.closest("[data-del]")) {
      if (!item.dataset.sure) { item.dataset.sure = "1"; e.target.textContent = "Sure?"; return; }
      const r = await api("library/delete", { name }); status(r.note);
      libItems = libItems.filter((x) => x.name !== name); drawLibrary(); loadSession(false); return;
    }
    const arm = e.target.closest("[data-arm]");
    if (arm || e.target.closest("[data-open]")) {
      const r = await api("prompts/" + encodeURIComponent(name));
      if (!r.ok) { status(r.note); return; }
      $("promptName").value = name; loadForm(r.form, r.note); $("libDlg").close();
      if (arm) {
        for (const [i, pack] of (r.packs || []).entries()) {
          if (i) await new Promise((ok) => setTimeout(ok, 900));
          if (!armPack(pack)) { status("Couldn't reach the Refmods panel on the Generator page."); return; }
        }
        status(`Loaded ${name} and armed ${r.packs.join(", ")} in the Refmods panel.`);
        setTimeout(() => loadSession(false), 1500);
      }
    }
  }

  // ---------------------------------------------------------------- events
  function wire() {
    for (const id of BOXES) {
      const el = $(id);
      el.addEventListener("focus", () => { S.lastBox = id; if (id === "action") S.actionUsed = true; });
      el.addEventListener("input", () => { S.form[id] = el.value; changed(); nameSuggest(id); });
      el.addEventListener("contextmenu", (e) => { if (!e.shiftKey) tagMenu(e, id); });
      el.addEventListener("keydown", (e) => {
        if (suggestKeys(e)) return;
        if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); openPhrases(el.value.slice(el.selectionStart, el.selectionEnd)); }
      });
      el.addEventListener("blur", () => setTimeout(hideSuggest, 150));
    }
    // The menu closes on any press outside it (including in another box), on scrolling, and when the page
    // loses focus (a click elsewhere in WanGP).
    document.addEventListener("mousedown", (e) => { if (!e.target.closest("#ctx")) closeMenu(); }, true);
    document.addEventListener("scroll", closeMenu, true);
    window.addEventListener("blur", closeMenu);
    window.addEventListener("resize", closeMenu);
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("ctx").hidden) { e.preventDefault(); closeMenu(); } });
    $("tagUndo").addEventListener("click", undoTags);
    $("sections").addEventListener("click", (e) => {
      const b = e.target.closest("[data-sec]"); if (!b) return;
      const off = new Set(S.form.off || []);
      if (off.has(b.dataset.sec)) off.delete(b.dataset.sec); else off.add(b.dataset.sec);
      S.form.off = [...off]; drawSections(); changed();
    });
    $("btnPhrases").addEventListener("click", () => openPhrases(""));
    $("phClose").addEventListener("click", () => $("phraseDlg").close());
    $("phSave").addEventListener("click", savePhrase);
    $("phText").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); savePhrase(); } });
    $("phSearch").addEventListener("input", drawPhrases);
    $("phCat").addEventListener("change", drawPhrases);
    $("phList").addEventListener("click", async (e) => {
      const del = e.target.closest("[data-del]");
      if (del) { const r = await api("phrases/delete", { id: del.dataset.del }); PH.items = r.phrases; drawPhrases(); return; }
      const row = e.target.closest("[data-id]"); if (!row) return;
      const p = PH.items.find((x) => x.id === row.dataset.id);
      $("phraseDlg").close();
      if (p) insertInto(PH.target, p.text, false);
    });
    $("duration").addEventListener("input", () => { S.form.duration = parseFloat($("duration").value) || 10; changed(); });
    $("winDur").addEventListener("change", () => { S.form.window_duration = $("winDur").checked; changed(); });
    $("refLayout").addEventListener("change", () => { S.form.ref_layout = $("refLayout").checked; changed(); });
    // The scene boxes are kept with the prompt, so Draft can use where and when.
    for (const [id, key] of SCENE) $(id).addEventListener("input", () => {
      S.form.scene = Object.assign({}, S.form.scene || {}, { [key]: $(id).value }); later("draft", saveDraft, 1500);
    });
    const fold = (open) => {
      $("subBody").hidden = !open; $("subFold").setAttribute("aria-expanded", String(open));
      try { localStorage.setItem("rs-subjects-open", open ? "1" : "0"); } catch (_) { /* no storage here */ }
    };
    $("subFold").addEventListener("click", () => fold($("subBody").hidden));
    try { if (localStorage.getItem("rs-subjects-open") === "0") fold(false); } catch (_) { /* no storage here */ }
    $("btnLibrary").addEventListener("click", openLibrary);
    $("libClose").addEventListener("click", () => $("libDlg").close());
    $("libSearch").addEventListener("input", drawLibrary);
    $("libCat").addEventListener("change", drawLibrary);
    $("libFav").addEventListener("change", drawLibrary);
    $("libList").addEventListener("click", libraryClick);
    $("libList").addEventListener("change", async (e) => {
      const box = e.target.closest("[data-cat]"); if (!box) return;
      const name = box.closest(".item").dataset.name, p = libItems.find((x) => x.name === name);
      p.category = box.value.trim(); await api("library/meta", { name, category: p.category }); status(`${name} is in ${p.category || "no category"}.`);
    });
    $("scratch").addEventListener("input", () => { S.form.scratch = $("scratch").value; later("draft", saveDraft, 1500); });
    $("btnPull").addEventListener("click", () => {
      const cur = $("scratch").value.trim();
      $("scratch").value = (cur ? cur + "\n\n" : "") + $("action").value; S.form.scratch = $("scratch").value; hlSync("scratch"); later("draft", saveDraft, 1500);
    });
    $("btnCommit").addEventListener("click", () => {
      if (!$("scratch").value.trim()) { status("The scratchpad is empty."); return; }
      S.undo.action = $("action").value; $("action").value = $("scratch").value; S.form.action = $("action").value; changed();
      status("The action is now the scratchpad's text. Undo on Action brings the old one back.");
    });
    $("btnScratchClear").addEventListener("click", () => { $("scratch").value = ""; S.form.scratch = ""; hlSync("scratch"); later("draft", saveDraft, 1500); });
    $("dSame").addEventListener("focus", lineStamps);
    $("btnRecent").addEventListener("click", async () => { const r = await api("prompts_recent"); if (r.ok) { if (r.form) loadForm(r.form, r.note); } else status(r.note); });
    $("btnFile").addEventListener("click", () => { $("fileIn").value = ""; $("fileIn").click(); });
    $("fileIn").addEventListener("change", async () => {
      const f = $("fileIn").files[0];
      if (!f) return;
      if (f.size > 2000000) { status(f.name + " is too big to be a prompt."); return; }
      const r = await api("prompts_import", { filename: f.name, text: await f.text() });
      if (r.ok) { $("promptName").value = f.name.replace(/\.[^.]+$/, ""); loadForm(r.form, r.note); } else status(r.note);
    });
    $("modes").addEventListener("click", (e) => { const b = e.target.closest("[data-mode]"); if (b) { S.form.mode = b.dataset.mode; changed(); refreshPreview(); } });
    $("chips").addEventListener("click", (e) => { const b = e.target.closest("[data-insert]"); if (b) insertInto(S.lastBox, b.dataset.insert, false); });
    document.querySelectorAll("[data-snip]").forEach((b) => b.addEventListener("click", () => snippet(b.dataset.snip)));
    document.querySelectorAll("[data-enhance]").forEach((b) => b.addEventListener("click", () => enhance(b.dataset.enhance, b)));
    document.querySelectorAll("[data-undo]").forEach((b) => b.addEventListener("click", () => {
      const part = b.dataset.undo;
      if (S.undo[part] === undefined) { status("Nothing to undo."); return; }
      const now = $(part).value; $(part).value = S.undo[part]; S.undo[part] = now; S.form[part] = $(part).value; changed();
    }));
    document.querySelector('[data-draft="summary"]').addEventListener("click", async () => {
      const { text } = await api("snippet", { kind: "summary", form: S.form });
      if (!text) { status("Add a subject or a scene location first: the summary is drafted from them."); return; }
      S.undo.summary = $("summary").value; $("summary").value = text; S.form.summary = text; changed();
      status("Summary drafted from the subjects, the scene and what happens. Adjust the situation if needed.");
    });

    // subjects
    $("btnNewSubject").addEventListener("click", () => { S.form.subjects.push(newSubject()); S.selected = S.form.subjects.length - 1; drawCards(); drawEditor(); changed(); });
    $("cards").addEventListener("click", (e) => {
      const mv = e.target.closest("[data-move]"), rm = e.target.closest("[data-remove]"), card = e.target.closest("[data-card]");
      const subs = S.form.subjects;
      if (mv) {   // the <Subject N> tags in the text move with their subjects
        const [i, step] = mv.dataset.move.split(":").map(Number); const j = Math.max(0, Math.min(subs.length - 1, i + step));
        if (i === j) return;
        const before = snap(); swapSubjects(i + 1, j + 1); S.selected = j;
        done(before, `Moved ${subjectName(subs[j], j + 1)} to ${j + 1}; its tags in the text moved with it.`); return;
      } else if (rm) {
        const i = Number(rm.dataset.remove);
        if (!confirm(`Remove ${subjectName(subs[i], i + 1)}? Its <Subject ${i + 1}> tags go from the text and the later subjects move up.`)) return;
        const before = snap(); removeSubject(i + 1);
        done(before, `Removed subject ${i + 1}.`); return;
      } else if (card) { S.selected = Number(card.dataset.card); }
      else return;
      drawCards(); drawEditor(); changed();
    });
    $("editor").addEventListener("input", editorInput);
    $("editor").addEventListener("change", editorInput);
    $("editor").addEventListener("click", async (e) => {
      const t = e.target.closest("[data-part]");
      if (t) { t.setAttribute("aria-pressed", t.getAttribute("aria-pressed") === "true" ? "false" : "true"); readLooks(); drawCards(); changed(); return; }
      if (e.target.id === "btnLibSave") {
        const r = await api("subjects", { subject: S.form.subjects[S.selected] }); status(r.note); loadSession(false);
      }
    });
    $("btnLibLoad").addEventListener("click", async () => {
      const name = $("libSel").value; if (!name) { status("Pick a saved subject first."); return; }
      const r = await api("subjects/" + encodeURIComponent(name)); if (!r.ok) { status(r.note); return; }
      const cur = S.form.subjects[S.selected];
      if (cur) { r.subject.look = cur.look; r.subject.voice = cur.voice; S.form.subjects[S.selected] = r.subject; }
      else { S.form.subjects.push(r.subject); S.selected = S.form.subjects.length - 1; }
      drawCards(); drawEditor(); changed(); status(r.note);
    });
    $("btnPackLoad").addEventListener("click", loadPack);
    $("btnPackSave").addEventListener("click", savePack);
    $("btnDraftSubjects").addEventListener("click", async () => {
      const r = await api("draft_subjects", { form: S.form });
      S.form.subjects = r.form.subjects; drawCards(); drawEditor(); changed(); status(r.note);
    });

    // toolbar
    $("btnInsert").addEventListener("click", () => { if (S.preview && setPrompt(S.preview.text)) status("Prompt replaced on the Generator page."); });
    $("btnAppend").addEventListener("click", () => { const box = promptBox(); const t = S.preview && appendWindow(box ? box.value : "", S.preview.text, false); if (t && setPrompt(t)) status("Appended as the next window. Use the paragraph-per-sliding-window setting."); });
    $("btnScene").addEventListener("click", () => { const box = promptBox(); const t = S.preview && appendWindow(box ? box.value : "", S.preview.text, true); if (t && setPrompt(t)) status("Appended as a new scene."); });
    $("btnSave").addEventListener("click", async () => { const r = await api("prompts", { name: $("promptName").value, form: S.form }); status(r.note); loadSession(false); });
    $("btnLoad").addEventListener("click", async () => { const n = $("loadSel").value; if (!n) { status("Pick a saved prompt first."); return; } const r = await api("prompts/" + encodeURIComponent(n)); if (r.ok) { $("promptName").value = n; loadForm(r.form, r.note); } else status(r.note); });
    $("btnRestore").addEventListener("click", async () => { const r = await api("draft"); if (r.ok) loadForm(r.form, r.note); else status(r.note); });
    $("btnClear").addEventListener("click", () => { if (confirm("Clear the whole form?")) { loadForm(null, "Cleared."); saveDraft(); } });
    $("btnCopy").addEventListener("click", () => { navigator.clipboard && navigator.clipboard.writeText(S.preview ? S.preview.text : ""); status("Copied."); });
    $("btnCheck").addEventListener("click", async () => {
      const box = promptBox(); const text = box ? box.value : (S.session && S.session.prompt) || "";
      drawChecks($("checkOut"), await api("check", { text })); $("checkDlg").showModal();
    });
    $("btnWrite").addEventListener("click", () => $("writeDlg").showModal());
    $("wGo").addEventListener("click", () => {
      $("wNote").textContent = "Writing…";
      runJob({ kind: "write", idea: $("wIdea").value, think: $("wThink").checked, form: S.form },
             (st) => { $("wOut").value = st.text; $("wNote").textContent = st.note; }, $("wGo"));
    });
    $("wStop").addEventListener("click", () => { if (S.job) api("jobs/" + S.job + "/stop", {}); });
    $("wInsert").addEventListener("click", () => { if ($("wOut").value.trim() && setPrompt($("wOut").value)) $("wNote").textContent = "Prompt replaced on the Generator page."; });
    $("wAppend").addEventListener("click", () => { const box = promptBox(); const t = appendWindow(box ? box.value : "", $("wOut").value, false); if (t && setPrompt(t)) $("wNote").textContent = "Appended."; });

    // pick up a new capture when the tab is opened again, and WanGP's theme
    setInterval(() => loadSession(false), 2000);
    document.addEventListener("visibilitychange", () => { if (!document.hidden) { theme(); loadSession(false); } });
    try { new MutationObserver(theme).observe(window.parent.document.body, { attributes: true, attributeFilter: ["class"] }); } catch (_) { /* on its own */ }
  }

  async function start() {
    theme();
    wire();
    hlInit();
    fullscreen();
    await loadSession(true);
    const draft = await api("draft").catch(() => ({ ok: false }));
    if (draft.ok) loadForm(draft.form, draft.note); else loadForm(null, "");
  }
  start();
})();
