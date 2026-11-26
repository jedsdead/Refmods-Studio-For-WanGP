/* Refmods Studio: the Prompt Builder page.
   Python does the work (labels, the prompt in the H3 guide's format, the checks, saving, the prompt enhancer);
   this file draws the form and keeps it in step. The page runs in a frame on the Prompt Builder tab, on WanGP's own
   origin, so it writes into the Generator page's prompt box directly. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const BOXES = ["summary", "style", "action", "sound", "music"];
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
    const pad = before && !/\s$/.test(before) && !/^\s/.test(text) ? " " : "";
    el.setRangeText(pad + text, start, end, "end");
    el.focus();
    S.form[id] = el.value;
    changed();
  }
  async function snippet(kind) {
    const args = {
      at: parseFloat($("at").value) || 0, move: $("camMove").value, amplitude: $("camAmp").value, speed: $("camSpeed").value,
      index: kind === "line" ? parseInt($("dWho").value || "0", 10) : parseInt($("subjSel").value || "0", 10),
      tone: $("dTone").value, language: $("dLang").value, voiceover: $("dVo").checked, line: $("dLine").value,
    };
    if ((kind === "subject" || kind === "line") && !args.index) { status("Add a subject first."); return; }
    if (kind === "line" && !args.line.trim()) { status("Type the line first."); $("dLine").focus(); return; }
    const { text } = await api("snippet", { kind, form: S.form, args });
    if (!text) return;
    if (kind === "subject") insertInto(S.lastBox, text, false);
    else insertInto("action", text, !S.actionUsed);
    if (kind === "line") $("dLine").value = "";
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
      <div class="card-head"><span class="cap">Subject ${S.selected + 1} · ${character ? "character creator" : esc(s.kind.toLowerCase())}</span><span class="muted small">Leave a field blank to skip it.</span><span class="grow"></span><button type="button" class="small" id="btnLibSave">Save to library</button></div>
      ${people}
      ${rows}`;
  }
  function editorInput(e) {
    const s = S.form.subjects[S.selected];
    if (!s) return;
    const t = e.target;
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
                             sound: "", music: "N/A", subjects: [] }, form || {});
    S.selected = 0;
    $("duration").value = S.form.duration;
    $("winDur").checked = !!S.form.window_duration;
    for (const id of BOXES) $(id).value = S.form[id] || "";
    drawCards(); drawEditor(); refreshPreview();
    if (note) status(note);
  }
  async function refreshPreview() {
    try {
      const out = await api("preview", { form: S.form });
      S.preview = out;
      $("preview").innerHTML = highlight(out.text);
      $("detected").textContent = `Picked from the Generator page: ${out.summary} → ${out.detected}` +
        (S.form.mode !== "Auto" ? ` · writing ${out.mode}` : "");
      drawModes(out.detected);
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

  // ---------------------------------------------------------------- session
  async function loadSession(first) {
    try {
      const s = await api("session");
      const fresh = s.captured_at !== S.capturedAt;
      S.session = s; S.vocab = s.vocab; S.capturedAt = s.captured_at;
      if (first) {
        options($("camMove"), S.vocab.camera, "Push In");
        options($("camAmp"), S.vocab.amplitudes.map((a) => [a, a || "amplitude"]), "");
        options($("camSpeed"), S.vocab.speeds.map((a) => [a, a || "speed"]), "");
        options($("dLang"), S.vocab.languages, "English");
      }
      options($("loadSel"), [["", "saved prompts"]].concat(s.lists.prompts), $("loadSel").value);
      options($("libSel"), [["", "saved subjects"]].concat(s.lists.subjects), $("libSel").value);
      loadPacks();
      captureNote();
      if (fresh || first) { drawEditor(); refreshPreview(); }
    } catch (err) { status("Couldn't reach the builder's server: " + err.message); }
  }

  // ---------------------------------------------------------------- events
  function wire() {
    for (const id of BOXES) {
      const el = $(id);
      el.addEventListener("focus", () => { S.lastBox = id; if (id === "action") S.actionUsed = true; });
      el.addEventListener("input", () => { S.form[id] = el.value; changed(); });
    }
    $("duration").addEventListener("input", () => { S.form.duration = parseFloat($("duration").value) || 10; changed(); });
    $("winDur").addEventListener("change", () => { S.form.window_duration = $("winDur").checked; changed(); });
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
      if (!text) { status("Add a subject first: the summary is drafted from them."); return; }
      S.undo.summary = $("summary").value; $("summary").value = text; S.form.summary = text; changed();
      status("Summary drafted from the subjects. Add what's happening.");
    });

    // subjects
    $("btnNewSubject").addEventListener("click", () => { S.form.subjects.push(newSubject()); S.selected = S.form.subjects.length - 1; drawCards(); drawEditor(); changed(); });
    $("cards").addEventListener("click", (e) => {
      const mv = e.target.closest("[data-move]"), rm = e.target.closest("[data-remove]"), card = e.target.closest("[data-card]");
      const subs = S.form.subjects;
      if (mv) {
        const [i, step] = mv.dataset.move.split(":").map(Number); const j = Math.max(0, Math.min(subs.length - 1, i + step));
        [subs[i], subs[j]] = [subs[j], subs[i]]; S.selected = j;
      } else if (rm) {
        const i = Number(rm.dataset.remove); if (!confirm(`Remove ${subjectName(subs[i], i + 1)}?`)) return;
        subs.splice(i, 1); S.selected = Math.min(S.selected, Math.max(0, subs.length - 1));
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
    await loadSession(true);
    const draft = await api("draft").catch(() => ({ ok: false }));
    if (draft.ok) loadForm(draft.form, draft.note); else loadForm(null, "");
  }
  start();
})();
