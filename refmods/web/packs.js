/* Refmods Studio: the Packs page. A pack is a set of mods, each with its role and the settings it's armed with.
   The Refmods panel's Add pack loads the members that are on; the Prompt Builder reads their roles. */
(function () {
  "use strict";
  const RS = window.RS, $ = RS.$, esc = RS.esc, api = RS.api, act = RS.act, toast = RS.toast;
  const S = { packs: [], roles: [], kinds: [], edit: null, original: null, dirty: false, q: "", mq: "" };
  const SEND_AS = [["pictures", "pictures"], ["video", "one video"], ["sheet", "contact sheet"]];
  // The Prompt Builder's character creator, saved with the pack.
  const CHARACTER = [["name", "Name"], ["gender", "Gender"], ["age", "Age"], ["ethnicity", "Ethnicity"], ["height", "Height"],
                     ["build", "Build"], ["hairstyle", "Hairstyle"], ["haircolor", "Hair colour"], ["eyecolor", "Eye colour"],
                     ["accent", "Accent"], ["clothing", "Clothing"], ["details", "Other details"]];
  const GENDERS = ["", "woman", "man", "girl", "boy", "person"];
  let charOpen = false;

  async function reload(keepName) {
    const data = await api("packs");
    S.packs = data.packs; S.roles = data.roles; S.kinds = data.kinds;
    if (!RS.library.items().length) { try { await RS.library.load(); } catch (_) { /* empty library */ } }
    const name = keepName !== undefined ? keepName : (S.edit && S.original);
    if (name && !S.dirty) { const p = S.packs.find((x) => x.name === name); S.edit = p ? clone(p) : null; S.original = p ? p.name : null; }
    renderList(); renderEditor(); renderPicker();
  }
  const clone = (p) => JSON.parse(JSON.stringify(p));
  const item = (mod) => RS.library.items().find((i) => i.id === "h3:" + mod);

  // ---------------------------------------------------------------- the list
  function renderList() {
    const q = S.q.toLowerCase();
    const list = S.packs.filter((p) => !q || (p.name + " " + (p.subject_name || "") + " " + p.members.map((m) => m.mod).join(" ")).toLowerCase().includes(q));
    $("pList").innerHTML = list.length ? list.map((p) => {
      const on = p.members.filter((m) => m.on !== false).length;
      return `<div class="pitem${S.original === p.name ? " on" : ""}" data-name="${esc(p.name)}"><b>${esc(p.name)}</b>
        <span>${esc(p.kind)} · ${on}${on !== p.members.length ? ` of ${p.members.length}` : ""} mod${p.members.length === 1 ? "" : "s"}${p.from_preset ? " · from a preset" : ""}</span></div>`;
    }).join("") : `<div class="empty-detail">${S.packs.length ? "No pack matches." : "No packs yet. Make one with New, or select mods in the Library and use Add to pack."}</div>`;
    $("pList").querySelectorAll(".pitem").forEach((el) => el.addEventListener("click", () => open(el.dataset.name)));
  }
  function open(name) {
    if (S.dirty && !confirmLeave()) return;
    const p = S.packs.find((x) => x.name === name);
    S.edit = p ? clone(p) : null; S.original = p ? p.name : null; S.dirty = false;
    RS.show("packs");
    renderList(); renderEditor(); renderPicker();
  }
  function confirmLeave() {
    toast("Save or undo your changes to this pack first.", true);
    return false;
  }

  // ---------------------------------------------------------------- the editor
  function touch() { S.dirty = true; $("pSave").disabled = false; $("pUndo").disabled = false; }
  function renderEditor() {
    const box = $("pEditor"), p = S.edit;
    $("view-packs").querySelector(".packs").classList.toggle("nopicker", !p);
    $("pPicker").hidden = !p;
    if (!p) { box.innerHTML = `<div class="empty-detail">Pick a pack, or make a new one.</div>`; return; }
    const head = `<div class="mhead cap"><span></span><span></span><span>Mod</span><span>Role</span><span>Strength</span><span>Send as</span><span>Sound</span><span>On</span><span></span></div>`;
    const rows = p.members.map((m, i) => {
      const it = item(m.mod);
      const multi = it && it.kind === "image" && /^\d+ pictures$/.test(it.length);
      const sendAs = m.send_as === "sheet" ? "sheet" : m.as_video ? "video" : "pictures";
      return `<div class="member${m.on === false ? " off" : ""}${it ? "" : " missing"}" data-i="${i}" draggable="true">
        <span class="grip" title="Drag to reorder">⋮⋮</span>
        ${it ? RS.cardPic(it) : `<div class="ph">?</div>`}
        <div style="min-width:0"><div class="nm" title="${esc(m.mod)}">${esc(m.mod.split("/").pop())}</div>
          <div class="sub">${it ? esc([it.kind === "image" ? "pictures" : it.kind, it.length].join(" · ")) : "not in your mods folder"}</div></div>
        <select class="mRole">${S.roles.map((r) => `<option value="${esc(r)}"${r === (m.role || "generic") ? " selected" : ""}>${esc(RS.label(r))}</option>`).join("")}</select>
        <input type="number" class="mStr" min="0" max="2" step="0.05" value="${m.strength != null ? m.strength : 1}" title="0 to 2; above 1 sharpens past what was stored">
        ${multi ? `<select class="mSend">${SEND_AS.map(([v, l]) => `<option value="${v}"${v === sendAs ? " selected" : ""}>${l}</option>`).join("")}</select>` : `<span class="muted small">—</span>`}
        ${it && it.has_audio && it.kind !== "audio" ? `<label class="inline"><input type="checkbox" class="mSnd"${m.use_audio === false ? "" : " checked"}> on</label>` : `<span class="muted small">—</span>`}
        <label class="onsw" title="Off keeps it in the pack but leaves it out when the pack is added"><input type="checkbox" class="mOn"${m.on === false ? "" : " checked"}></label>
        <div class="tools"><button class="mDel" title="Take it out of the pack">×</button></div></div>`;
    }).join("");
    box.innerHTML = `
      <div class="grid2"><label class="fld">Pack name<input id="pName" value="${esc(p.name || "")}" placeholder="Jodi"></label>
        <label class="fld">Kind<select id="pKind">${S.kinds.map((k) => `<option value="${esc(k)}"${k === (p.kind || "mixed") ? " selected" : ""}>${esc(k)}</option>`).join("")}</select></label></div>
      <div class="grid2"><label class="fld">Subject name in the Prompt Builder<input id="pSubject" value="${esc(p.subject_name || "")}" placeholder="${esc(p.name || "the pack's name")}"></label>
        <label class="fld">Description<input id="pDesc" value="${esc(p.description || "")}"></label></div>
      <p class="explain">In the Refmods panel, <b>Add pack</b> loads the mods that are on, with these settings. In the Prompt Builder, <b>Draft subjects</b> turns a character pack into one subject, each mod providing what its role says. A mixed pack is just a set of mods.</p>
      <details class="sec" id="pChar"${charOpen ? " open" : ""}><summary>Character <span class="hint">${p.subject && Object.keys(p.subject).length ? "filled in" : "for the Prompt Builder's Load pack"}</span></summary><div class="secbody">
        <p class="explain">What <b>Load pack</b> in the Prompt Builder fills in. Save a subject there as a pack to fill this from the character creator.</p>
        <div class="grid3">${CHARACTER.map(([k, label]) => k === "gender"
          ? `<label class="fld">${label}<select data-ch="gender">${GENDERS.map((g) => `<option value="${g}"${g === ((p.subject || {}).gender || "") ? " selected" : ""}>${g || "—"}</option>`).join("")}</select></label>`
          : `<label class="fld"${k === "details" || k === "clothing" ? ' style="grid-column: span 3"' : ""}>${label}<input data-ch="${k}" value="${esc((p.subject || {})[k] || "")}"></label>`).join("")}</div>
      </div></details>
      <div class="members">${p.members.length ? head + rows : `<div class="empty-detail">No mods yet. Click mods on the right to add them.</div>`}</div>
      <div class="row"><button id="pSave" class="primary"${S.dirty || !S.original ? "" : " disabled"}>Save</button>
        <button id="pUndo"${S.dirty ? "" : " disabled"}>Undo changes</button>
        <button id="pDup"${S.original ? "" : " disabled"}>Duplicate</button>
        <button id="pShow"${S.original ? "" : " disabled"}>Show in the Library</button>
        <span class="grow"></span><button id="pDelete" class="danger"${S.original ? "" : " disabled"}>Delete pack</button></div>`;
    $("pName").addEventListener("input", (e) => { p.name = e.target.value; touch(); });
    $("pKind").addEventListener("change", (e) => { p.kind = e.target.value; touch(); });
    $("pSubject").addEventListener("input", (e) => { p.subject_name = e.target.value; touch(); });
    $("pDesc").addEventListener("input", (e) => { p.description = e.target.value; touch(); });
    $("pChar").addEventListener("toggle", (e) => { charOpen = e.target.open; });
    box.querySelectorAll("[data-ch]").forEach((el) => el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => {
      p.subject = Object.assign({}, p.subject || {}, { [el.dataset.ch]: el.value });
      if (!p.subject.kind) p.subject.kind = { location: "Location", prop: "Prop", style: "Style" }[p.kind] || "Character";
      touch();
    }));
    box.querySelectorAll(".member").forEach((el) => {
      const i = +el.dataset.i, m = p.members[i];
      el.querySelector(".mRole").addEventListener("change", (e) => { m.role = e.target.value; touch(); });
      el.querySelector(".mStr").addEventListener("change", (e) => { m.strength = Math.max(0, Math.min(2, +e.target.value || 0)); e.target.value = m.strength; touch(); });
      if (el.querySelector(".mSend")) el.querySelector(".mSend").addEventListener("change", (e) => {
        m.as_video = e.target.value === "video"; if (e.target.value === "sheet") m.send_as = "sheet"; else delete m.send_as; touch(); });
      if (el.querySelector(".mSnd")) el.querySelector(".mSnd").addEventListener("change", (e) => { m.use_audio = e.target.checked; touch(); });
      el.querySelector(".mOn").addEventListener("change", (e) => { if (e.target.checked) delete m.on; else m.on = false; el.classList.toggle("off", !e.target.checked); touch(); });
      el.querySelector(".mDel").addEventListener("click", () => { p.members.splice(i, 1); touch(); renderEditor(); renderPicker(); });
      el.addEventListener("dragstart", (e) => { el.classList.add("dragging"); e.dataTransfer.setData("text/x-member", String(i)); });
      el.addEventListener("dragend", () => el.classList.remove("dragging"));
      el.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("text/x-member")) { e.preventDefault(); el.classList.add("over"); } });
      el.addEventListener("dragleave", () => el.classList.remove("over"));
      el.addEventListener("drop", (e) => {
        el.classList.remove("over");
        const from = e.dataTransfer.getData("text/x-member"); if (from === "") return;
        e.preventDefault();
        const [moved] = p.members.splice(+from, 1); p.members.splice(i, 0, moved); touch(); renderEditor();
      });
    });
    $("pSave").addEventListener("click", save);
    $("pUndo").addEventListener("click", () => { S.dirty = false; const o = S.packs.find((x) => x.name === S.original); S.edit = o ? clone(o) : null; renderEditor(); renderPicker(); });
    $("pDup").addEventListener("click", () => {
      let n = 2; while (S.packs.some((x) => x.name === `${S.edit.name} ${n}`)) n++;
      S.edit = { ...clone(S.edit), name: `${S.edit.name} ${n}` }; S.original = null; S.dirty = true; renderList(); renderEditor(); renderPicker();
    });
    $("pShow").addEventListener("click", () => { RS.show("library"); const f = document.querySelector(`.fold[data-f="pack:${CSS.escape(S.original)}"]`); if (f) f.click(); });
    RS.armed($("pDelete"), () => act(api("packs/delete", { name: S.original }), async () => {
      S.edit = null; S.original = null; S.dirty = false; await reload(null); RS.library.load(true);
    }));
  }
  async function save() {
    const p = S.edit;
    if (!String(p.name || "").trim()) return toast("Give the pack a name.", true);
    const r = await act(api("packs/save", { pack: p, old_name: S.original }));
    if (r && r.ok) { S.dirty = false; S.original = r.name; await reload(r.name); RS.library.load(true); }
  }

  // ---------------------------------------------------------------- adding mods
  function renderPicker() {
    if (!S.edit) return;
    const have = new Set(S.edit.members.map((m) => m.mod));
    const words = S.mq.toLowerCase().split(/\s+/).filter(Boolean);
    const list = RS.library.items().filter((it) => it.model === "h3" &&
      words.every((w) => (it.name + " " + it.description + " " + it.concept).toLowerCase().includes(w)));
    $("pMods").innerHTML = list.length ? list.map((it) => `<div class="pmod${have.has(it.name) ? " in" : ""}" data-mod="${esc(it.name)}" title="${esc(it.description || it.name)}">
      ${RS.cardPic(it)}<div class="t"><b>${esc(it.leaf)}</b><span>${esc([RS.label(it.concept), it.length, it.folder].filter(Boolean).join(" · "))}</span></div></div>`).join("")
      : `<div class="empty-detail">No mods match.</div>`;
    $("pMods").querySelectorAll(".pmod:not(.in)").forEach((el) => el.addEventListener("click", () => {
      const it = item(el.dataset.mod);
      const role = it.kind === "audio" ? "voice" : (S.roles.includes(it.concept) ? it.concept : "generic");
      S.edit.members.push({ mod: el.dataset.mod, role, strength: 1.0 });
      touch(); renderEditor(); renderPicker();
    }));
  }

  // ---------------------------------------------------------------- start
  RS.packs = { open, reload: () => reload() };
  RS.views.packs = {
    init() {
      $("pSearch").addEventListener("input", (e) => { S.q = e.target.value; renderList(); });
      $("pModSearch").addEventListener("input", (e) => { S.mq = e.target.value; renderPicker(); });
      $("pNew").addEventListener("click", () => {
        if (S.dirty && !confirmLeave()) return;
        S.edit = { name: "", kind: "character", subject_name: "", description: "", members: [] };
        S.original = null; S.dirty = true; renderList(); renderEditor(); renderPicker();
        $("pName").focus();
      });
    },
    show() { reload(); },
    refresh() { reload(); },
  };
})();
