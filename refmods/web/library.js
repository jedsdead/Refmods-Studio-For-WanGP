/* Refmods Studio: the Library page. Python does the work (refmods/library_service.py). */
(function () {
  "use strict";
  const RS = window.RS, $ = RS.$, esc = RS.esc, enc = RS.enc, api = RS.api, act = RS.act, toast = RS.toast;
  const S = {
    items: [], folders: { h3: [], flux: [] },
    filter: "", kind: "", concept: "", q: "", sort: "name",
    open: null, detail: null, picked: new Set(), lastClicked: null,
    secs: new Set(["edit", "stored"]), frameShown: null, pv: 0, edit: null,
  };
  const byId = (id) => S.items.find((i) => i.id === id);
  const thumbUrl = (it, big) => `api/thumb?id=${enc(it.id)}&big=${big ? 1 : 0}&v=${Math.round(it.mtime)}${it.custom_preview ? "c" : ""}${S.pv}`;
  RS.library = { items: () => S.items, thumbUrl, load: (keep) => loadMods(keep), open: (id) => { RS.show("library"); openMod(id); } };

  async function loadMods(keepOpen) {
    const data = await api("mods");
    S.items = data.items; S.folders = data.folders;
    for (const id of [...S.picked]) if (!byId(id)) S.picked.delete(id);
    if (S.open && !byId(S.open)) { S.open = null; S.detail = null; }
    renderSide(); renderGrid(); renderBulk();
    if (keepOpen && S.open) await openMod(S.open, true);
    else if (!S.open) renderDetail();
  }

  // ---------------------------------------------------------------- folders
  function inFolder(it, f) {
    if (!f) return true;
    if (f.startsWith("pack:")) return it.packs.includes(f.slice(5));
    const [model, ...rest] = f.split("/"); const sub = rest.join("/");
    if (it.model !== model) return false;
    return !sub || it.folder === sub || it.folder.startsWith(sub + "/");
  }
  function renderSide() {
    const side = $("side");
    const fold = (value, label, depth, removable) => {
      const n = S.items.filter((it) => inFolder(it, value)).length;
      return `<div class="fold${S.filter === value ? " on" : ""}" data-f="${esc(value)}" style="padding-left:${8 + depth * 14}px">
        <span>${esc(label)}</span><span class="n">${n}</span>${removable && !n ? `<span class="x" data-del="${esc(value)}" title="Delete this empty folder">×</span>` : ""}</div>`;
    };
    const tree = (model, title, subs) => fold(model, title, 0, false) +
      subs.map((s) => fold(`${model}/${s}`, s.split("/").pop(), s.split("/").length, true)).join("");
    const packs = [...new Set(S.items.flatMap((it) => it.packs))].sort((a, b) => a.localeCompare(b));
    side.innerHTML = fold("", "All mods", 0, false) +
      `<div class="cap">MiniMax H3</div>` + tree("h3", "H3", S.folders.h3 || []) +
      ((S.folders.flux || []).length || S.items.some((i) => i.model === "flux")
        ? `<div class="cap">Flux 2</div>` + tree("flux", "Flux", S.folders.flux || []) : "") +
      (packs.length ? `<div class="cap">Packs</div>` + packs.map((p) => fold("pack:" + p, p, 0, false)).join("") : "") +
      `<div class="cap">New folder</div><div class="newfold"><input id="newFolder" placeholder="characters/heroes" title="A / nests it. Start with flux/ for a Flux folder."><button id="newFolderBtn" class="small">Add</button></div>`;
    side.querySelectorAll(".fold").forEach((el) => {
      el.addEventListener("click", (e) => {
        if (e.target.dataset.del) return delFolder(e.target.dataset.del);
        S.filter = el.dataset.f; renderSide(); renderGrid();
      });
      if (el.dataset.f.startsWith("pack:") || !el.dataset.f) return;
      el.addEventListener("dragover", (e) => { e.preventDefault(); el.classList.add("drop"); });
      el.addEventListener("dragleave", () => el.classList.remove("drop"));
      el.addEventListener("drop", (e) => {
        e.preventDefault(); el.classList.remove("drop");
        let ids = [];
        try { ids = JSON.parse(e.dataTransfer.getData("text/plain")); } catch (_) { return; }
        if (Array.isArray(ids) && ids.length) moveTo(ids, el.dataset.f);
      });
    });
    $("newFolderBtn").addEventListener("click", newFolder);
    $("newFolder").addEventListener("keydown", (e) => { if (e.key === "Enter") newFolder(); });
  }
  async function newFolder() {
    let raw = $("newFolder").value.trim().replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
    if (!raw) return;
    let model = "h3";
    const head = raw.split("/")[0].toLowerCase();
    if (head === "flux" || head === "h3") { model = head; raw = raw.split("/").slice(1).join("/"); }
    if (!raw) return toast("Type the folder's name after " + model + "/.", true);
    await act(api("folder", { model, path: raw }), () => loadMods(true));
  }
  async function delFolder(value) {
    const [model, ...rest] = value.split("/");
    await act(api("folder", { model, path: rest.join("/"), delete: true }), async () => {
      if (S.filter === value) S.filter = model;
      await loadMods(true);
    });
  }
  async function moveTo(ids, destination) {
    await act(api("move", { ids, destination }), () => loadMods(true));
  }

  // ---------------------------------------------------------------- the mods
  function shown() {
    const words = S.q.toLowerCase().trim().split(/\s+/).filter(Boolean);
    const list = S.items.filter((it) => inFolder(it, S.filter) && (!S.kind || it.kind === S.kind) &&
      (!S.concept || it.concept === S.concept) &&
      words.every((w) => (it.name + " " + it.description + " " + it.concept + " " + it.packs.join(" ")).toLowerCase().includes(w)));
    const cmp = { name: (a, b) => a.name.localeCompare(b.name), new: (a, b) => b.mtime - a.mtime,
                  size: (a, b) => b.size_mb - a.size_mb, tokens: (a, b) => b.tokens - a.tokens }[S.sort];
    return list.sort(cmp);
  }
  RS.cardPic = function (it, big) {
    if (it.thumb) return `<img loading="lazy" src="${thumbUrl(it, big)}" alt="">`;
    if (it.kind === "audio") return `<div class="ph"><b>♪</b>${big ? "voice" : ""}</div>`;
    return `<div class="ph"><b>▢</b>${big ? "no stored frames" : ""}</div>`;
  };
  function renderGrid() {
    const list = shown();
    $("count").textContent = `${list.length} of ${S.items.length} mod${S.items.length === 1 ? "" : "s"}`;
    const grid = $("grid");
    grid.classList.toggle("picking", S.picked.size > 0);
    if (!list.length) {
      grid.innerHTML = `<div class="nothing">${S.items.length ? "Nothing matches. Clear the search or pick another folder." :
        "No mods yet. Make some on the Create page."}</div>`;
      return;
    }
    grid.innerHTML = list.map((it) => {
      const badges = [it.model === "flux" ? `<span class="badge flux">Flux</span>` : `<span class="badge ${it.kind}">${it.kind === "image" ? "pic" : it.kind}</span>`];
      if (it.has_audio && it.kind !== "audio") badges.push(`<span class="badge snd" title="Has a soundtrack">♪</span>`);
      if (it.model === "h3" && it.kind !== "audio" && !it.frames) badges.push(`<span class="badge warn" title="No stored encoder frames">!</span>`);
      if (!it.usable) badges.push(`<span class="badge warn" title="Won't load">✕</span>`);
      return `<div class="card${S.open === it.id ? " open" : ""}${S.picked.has(it.id) ? " picked" : ""}" data-id="${esc(it.id)}" draggable="true" title="${esc(it.description || it.name)}">
        <div class="pic">${RS.cardPic(it, true)}</div>
        <input type="checkbox" class="tick" aria-label="Select ${esc(it.leaf)}"${S.picked.has(it.id) ? " checked" : ""}>
        <div class="badges">${badges.join("")}</div>
        <div class="txt"><span class="nm">${esc(it.leaf)}</span>
          <span class="sub">${esc([it.concept !== "generic" ? RS.label(it.concept) : "", it.length, it.tokens.toLocaleString() + " tok"].filter(Boolean).join(" · "))}</span>
          ${it.folder ? `<span class="sub">${esc(it.folder)}</span>` : ""}</div></div>`;
    }).join("");
    grid.querySelectorAll(".card").forEach((card) => {
      const id = card.dataset.id;
      card.addEventListener("click", (e) => {
        if (e.target.classList.contains("tick")) { togglePick(id, e.shiftKey); return; }
        if (e.ctrlKey || e.metaKey || e.shiftKey || S.picked.size) { e.preventDefault(); togglePick(id, e.shiftKey); return; }
        openMod(id);
      });
      card.addEventListener("dragstart", (e) => {
        const ids = S.picked.has(id) ? [...S.picked] : [id];
        e.dataTransfer.setData("text/plain", JSON.stringify(ids)); e.dataTransfer.effectAllowed = "move";
      });
    });
  }
  function togglePick(id, range) {
    if (range && S.lastClicked) {
      const ids = shown().map((i) => i.id);
      const a = ids.indexOf(S.lastClicked), b = ids.indexOf(id);
      if (a >= 0 && b >= 0) ids.slice(Math.min(a, b), Math.max(a, b) + 1).forEach((x) => S.picked.add(x));
    } else if (S.picked.has(id)) S.picked.delete(id); else S.picked.add(id);
    S.lastClicked = id;
    renderGrid(); renderBulk();
  }

  // ---------------------------------------------------------------- several at once
  function destinations() {
    return [["h3", "H3 (top)"]].concat((S.folders.h3 || []).map((f) => ["h3/" + f, "H3/" + f]),
      [["flux", "Flux (top)"]], (S.folders.flux || []).map((f) => ["flux/" + f, "Flux/" + f]));
  }
  function renderBulk() {
    const n = S.picked.size;
    $("bulk").hidden = n === 0;
    if (!n) return;
    $("bulkCount").textContent = `${n} selected`;
    const keep = $("bulkDest").value;
    RS.options($("bulkDest"), destinations(), keep || "h3");
    const picked = [...S.picked].map(byId).filter(Boolean);
    $("bulkFrames").disabled = !picked.some((i) => i.model === "h3" && i.kind !== "audio");
    $("bulkClean").disabled = !picked.some((i) => i.has_audio);
    $("bulkPack").disabled = !picked.some((i) => i.model === "h3");
  }
  RS.addToPack = async function (ids) {
    const packs = (await api("packs")).packs.map((p) => p.name);
    const dlg = $("packDlg");
    RS.options($("packDlgSel"), [["", "A new pack…"]].concat(packs.map((p) => [p, p])), "");
    $("packDlgNew").value = ""; $("packDlgNewWrap").hidden = false;
    $("packDlgSel").onchange = () => { $("packDlgNewWrap").hidden = !!$("packDlgSel").value; };
    $("packDlgCancel").onclick = () => dlg.close();
    $("packDlgOk").onclick = async () => {
      const existing = $("packDlgSel").value, name = existing || $("packDlgNew").value.trim();
      if (!name) return toast("Type a name for the new pack.", true);
      dlg.close();
      await act(api("packs/add", { name, ids, new: !existing }), async () => { await loadMods(true); if (RS.packs) RS.packs.reload(); });
    };
    dlg.showModal();
  };
  function wireBulk() {
    $("bulkMove").addEventListener("click", () => moveTo([...S.picked], $("bulkDest").value));
    $("bulkPack").addEventListener("click", () => RS.addToPack([...S.picked]));
    $("bulkFrames").addEventListener("click", () => RS.job("store_frames", { ids: [...S.picked].filter((i) => i.startsWith("h3:")) }));
    $("bulkClean").addEventListener("click", () => RS.job("clean_audio", { ids: [...S.picked].filter((i) => (byId(i) || {}).has_audio), as_copy: true }));
    $("bulkHint").addEventListener("click", () => copyHint([...S.picked]));
    RS.armed($("bulkDelete"), async () => {
      await act(api("delete", { ids: [...S.picked] }), async () => { S.picked.clear(); await loadMods(true); });
    });
    $("bulkClear").addEventListener("click", () => { S.picked.clear(); renderGrid(); renderBulk(); });
  }
  async function copyHint(ids) {
    const r = await act(api("hint", { ids }));
    if (!r) return;
    if (!r.text) return toast("None of these mods has a description to build a hint from.", true);
    try { await navigator.clipboard.writeText(r.text); toast("Prompt hint copied: " + r.text); }
    catch (_) { toast(r.text); }
  }

  // ---------------------------------------------------------------- one mod
  async function openMod(id, quiet) {
    if (S.open !== id) S.edit = null;
    S.open = id;
    if (!quiet) { S.frameShown = null; renderGrid(); }
    try { S.detail = await api("mod?id=" + enc(id)); }
    catch (e) { S.detail = null; toast(e.message, true); }
    renderDetail();
  }
  const sec = (key, title, hint, body) =>
    `<details class="sec" data-sec="${key}"${S.secs.has(key) ? " open" : ""}><summary>${esc(title)}${hint ? ` <span class="hint">${esc(hint)}</span>` : ""}</summary><div class="secbody">${body}</div></details>`;
  const outUrl = (it, f, strength) => `api/output?id=${enc(it.id)}&file=${enc(f)}${strength ? "&strength=1" : ""}&v=${S.pv}`;

  function renderDetail() {
    const box = $("details");
    const d = S.detail;
    if (!d) { box.innerHTML = `<div class="empty-detail">Pick a mod to see what's inside it.</div>`; return; }
    const it = d.item, h3 = it.model === "h3", visual = it.kind !== "audio";
    const heroSrc = S.frameShown != null ? `api/frame?id=${enc(it.id)}&i=${S.frameShown}` : (it.thumb ? thumbUrl(it, true) : "");
    const hero = heroSrc ? `<img id="heroImg" src="${heroSrc}" alt="">` :
      `<div class="ph"><b>${visual ? "▢" : "♪"}</b>${visual ? "No stored frames. Store them below, or set a preview." : "A voice. Set a picture for it with Replace preview."}</div>`;
    const strip = d.frames.length > 1 ? `<div class="strip">${d.frames.map((f) =>
      `<img src="api/frame?id=${enc(it.id)}&i=${f.index}" data-i="${f.index}" title="${esc(f.label)}" class="${S.frameShown === f.index ? "on" : ""}" alt="${esc(f.label)}">`).join("")}</div>` : "";
    const concepts = h3 ? RS.session.concepts : RS.session.flux_concepts;
    const out = d.outputs;
    const decoded = out.pictures.length + out.videos.length + out.audios.length;
    const audioFile = out.audios[0];
    const busy = (op) => RS.running(op, it.id);

    let html = `<div class="hero${heroSrc ? "" : " short"}">${hero}</div>${strip}
      <div class="row"><button id="pvReplace" class="small">Replace preview</button>
        ${it.custom_preview ? `<button id="pvReset" class="small">Use the mod's own frame</button>` : ""}
        <span class="muted small">${it.custom_preview ? "Custom preview" : ""}</span></div>
      <div class="title">${esc(it.leaf)}</div>
      <div class="muted small">${esc((h3 ? "H3" : "Flux") + (it.folder ? " / " + it.folder : ""))}</div>`;

    html += sec("edit", "Name and description", "", `
      <label class="fld">Name (a path moves it: characters/tanya)<input id="edName" value="${esc(it.name)}"></label>
      <label class="fld">Description (for prompt hints and search)<textarea id="edDesc" rows="2">${esc(it.description)}</textarea></label>
      <label class="fld">Concept<select id="edConcept">${concepts.map((c) => `<option value="${esc(c)}"${c === it.concept ? " selected" : ""}>${esc(RS.label(c))}</option>`).join("")}</select></label>
      <div class="row"><button id="edSave" class="primary">Save</button><button id="edCopy" title="A copy with the same latent, to edit or experiment on">Save as copy</button>
        <span class="grow"></span><button id="edDelete" class="danger">Delete</button></div>`);

    html += sec("stored", "What's stored", "", `<dl class="facts">${d.facts.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
      ${d.tags.length ? `<div class="chips">${d.tags.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>` : ""}
      <div class="row"><span class="explain">${it.packs.length ? "In packs:" : "In no pack."}</span>
        ${it.packs.map((p) => `<span class="chip pack" data-pack="${esc(p)}" title="Open this pack">${esc(p)}</span>`).join("")}
        ${h3 ? `<button id="toPack" class="small">Add to pack</button>` : ""}</div>`);

    if (h3 && d.pictures > 1) {
      if (!S.edit || S.edit.id !== it.id) S.edit = { id: it.id, order: [...Array(d.pictures).keys()], off: new Set() };
      const e = S.edit;
      html += sec("pictures", "Edit pictures", "no re-encoding", `
        <p class="explain">Switch pictures off or move them, then save. Each picture is stored on its own, so nothing is encoded again.</p>
        <div class="editpics">${e.order.map((i, pos) => `<div class="ep${e.off.has(i) ? " off" : ""}" data-i="${i}">
          ${i < d.frames.length ? `<img src="api/frame?id=${enc(it.id)}&i=${i}" alt="">` : `<div class="ph">picture ${i + 1}</div>`}
          <div class="bar"><input type="checkbox" class="epOn" ${e.off.has(i) ? "" : "checked"} title="Keep this picture"><span class="grow">${pos + 1}</span>
            <button class="epL" ${pos ? "" : "disabled"} title="Earlier">◀</button><button class="epR" ${pos < e.order.length - 1 ? "" : "disabled"} title="Later">▶</button></div></div>`).join("")}</div>
        <div class="row"><button id="epCopy" class="primary">Save as copy</button><button id="epSave">Save over this mod</button><button id="epReset" class="small">Undo changes</button></div>`);
    }

    if (h3 && it.has_audio) {
      const len = d.audio_seconds || 0;
      html += sec("voice", visual ? "Soundtrack" : "Voice", len ? `${len.toFixed(1)}s` : "", `
        ${audioFile ? `<audio id="voicePlayer" controls preload="none" src="${outUrl(it, audioFile)}"></audio>`
          : `<p class="explain">The sound is stored as a latent. Decode it to listen.</p>
             <div class="row"><button data-job="decompile">${busy("decompile") ? "Decoding…" : "Decode to listen"}</button></div>`}
        <div class="row"><label class="inline">Keep from <input type="number" id="trA" class="num" min="0" max="${len}" step="0.1" value="0"></label>
          <label class="inline">to <input type="number" id="trB" class="num" min="0" max="${len}" step="0.1" value="${len}"> s</label>
          ${audioFile ? `<button id="trMark" class="small" title="Set the start or end to where the player is">Use player time</button>` : ""}</div>
        <div class="row"><button id="trCopy">Trim as copy</button><button id="trSave">Trim this mod</button><span class="muted small">no re-encoding · at least 2 s</span></div>
        <div class="row"><button data-job="clean_audio" title="Keeps voices only; music and effects go">Clean audio</button>
          <label class="inline"><input type="checkbox" id="cleanCopy" checked> as a copy</label>
          ${visual ? `<span class="grow"></span><button id="sndRemove" class="danger">Remove soundtrack</button>` : ""}</div>`);
    }
    if (h3 && visual) {
      html += sec("sound", it.has_audio ? "Replace the soundtrack" : "Add a soundtrack", "", `
        <p class="explain">A soundtrack is the mod's own &lt;Audio N&gt;, for a voice. A video file's sound is used.</p>
        <div class="row"><button id="sndPick">Choose a file</button><span class="muted small" id="sndName">${esc(S.sndName || "")}</span></div>
        <div class="row"><label class="inline">Seconds <input id="sndSecs" type="number" class="num" min="2" max="15" step="0.5" value="4"></label>
          <label class="inline"><input type="checkbox" id="sndClean"> remove music and noise</label></div>
        <div class="row"><button id="sndApply" class="primary">Apply</button></div>`);
      html += sec("strength", "Strength preview", "decodes the first picture", `
        <p class="explain">The first picture as the model gets it at each strength. Below 1 it softens; above 1 it sharpens past what was stored.</p>
        <div class="row">${[0.5, 1, 1.5].map((v) => `<input type="number" class="num stv" min="0.05" max="2" step="0.05" value="${v}">`).join("")}
          <button data-job="strength">${busy("strength") ? "Working…" : "Preview"}</button></div>
        ${d.strength.length ? `<div class="pics">${d.strength.map((s) => `<figure><img src="${outUrl(it, s.file, true)}" alt="">${esc(s.strength)}
          <button data-usepv="${esc(s.file)}" data-strength="1">Use as preview</button></figure>`).join("")}</div>` : ""}`);
    }
    if (h3) {
      html += sec("decode", "Decompile", decoded ? "decoded" : "", `
        <p class="explain">Rebuilds the pictures, video and sound as files. These are reconstructions, not the originals.</p>
        <div class="row"><button data-job="decompile">${busy("decompile") ? "Decoding…" : decoded ? "Decompile again" : "Decompile"}</button>
          ${visual && !it.frames ? `<button data-job="store_frames" title="So they aren't decoded every session">Store encoder frames</button>` : ""}</div>
        ${out.pictures.length ? `<div class="pics">${out.pictures.map((f) => `<figure><img src="${outUrl(it, f)}" alt="">${esc(f)}
          <button data-usepv="${esc(f)}">Use as preview</button></figure>`).join("")}</div>` : ""}
        ${out.videos.map((f) => `<video controls preload="metadata" src="${outUrl(it, f)}"></video>`).join("")}
        ${visual && out.audios.length ? out.audios.map((f) => `<audio controls preload="none" src="${outUrl(it, f)}"></audio>`).join("") : ""}`);
    }
    if (h3 && it.kind === "image" && (RS.session.models.flux || []).length) {
      html += sec("flux", "Convert to Flux", "", `
        <p class="explain">Decodes the pictures with the H3 model, then encodes them with a Flux model. The H3 mod stays.</p>
        <label class="fld">Flux model<select id="fxModel">${RS.session.models.flux.map(([l, t]) => `<option value="${esc(t)}">${esc(l)}</option>`).join("")}</select></label>
        <div class="row"><select id="fxBudget">${RS.session.budgets.map(([l, v]) => `<option value="${esc(v)}"${v === RS.session.budget_default ? " selected" : ""}>${esc(l)}</option>`).join("")}</select>
          <select id="fxLayout">${RS.session.layouts.map(([l, v]) => `<option value="${esc(v)}"${v === RS.session.layout_default ? " selected" : ""}>${esc(l)}</option>`).join("")}</select></div>
        <div class="row"><button data-job="convert" class="primary">Convert</button></div>`);
    }
    box.innerHTML = html;
    wireDetail(it, d);
  }
  function wireDetail(it, d) {
    const box = $("details");
    box.querySelectorAll("details.sec").forEach((el) => el.addEventListener("toggle", () => {
      if (el.open) S.secs.add(el.dataset.sec); else S.secs.delete(el.dataset.sec);
    }));
    box.querySelectorAll(".strip img").forEach((img) => img.addEventListener("click", () => {
      S.frameShown = S.frameShown === +img.dataset.i ? null : +img.dataset.i; renderDetail();
    }));
    box.querySelectorAll(".pics img, #heroImg, .ep img").forEach((img) => img.addEventListener("click", () => RS.zoom(img.src)));
    $("pvReplace").addEventListener("click", () => $("pickPreview").click());
    if ($("pvReset")) $("pvReset").addEventListener("click", () => act(api("preview?clear=1&id=" + enc(it.id), {}), afterChange));
    box.querySelectorAll("[data-usepv]").forEach((b) => b.addEventListener("click", () =>
      act(api(`preview?id=${enc(it.id)}&output=${enc(b.dataset.usepv)}&strength=${b.dataset.strength ? 1 : 0}`, {}), afterChange)));
    box.querySelectorAll("[data-pack]").forEach((c) => c.addEventListener("click", () => { if (RS.packs) RS.packs.open(c.dataset.pack); }));
    if ($("toPack")) $("toPack").addEventListener("click", () => RS.addToPack([it.id]));
    $("edSave").addEventListener("click", () => act(api("save", { id: it.id, name: $("edName").value,
      description: $("edDesc").value, concept: $("edConcept").value }), async (r) => { if (r && r.id) S.open = r.id; await loadMods(true); }));
    $("edCopy").addEventListener("click", () => act(api("copy", { id: it.id }), async (r) => { if (r && r.id) S.open = r.id; await loadMods(true); }));
    RS.armed($("edDelete"), () => act(api("delete", { ids: [it.id] }), async () => { S.open = null; S.detail = null; await loadMods(); }));
    box.querySelectorAll("[data-job]").forEach((b) => b.addEventListener("click", () => {
      const op = b.dataset.job, extra = {};
      if (op === "clean_audio") extra.as_copy = $("cleanCopy") ? $("cleanCopy").checked : true;
      if (op === "strength") extra.strengths = [...box.querySelectorAll(".stv")].map((x) => +x.value).filter((v) => v > 0);
      if (op === "convert") Object.assign(extra, { flux_model: $("fxModel").value, budget: +$("fxBudget").value, layout: $("fxLayout").value });
      RS.job(op, Object.assign({ ids: [it.id] }, extra)).then(() => renderDetail());
    }));
    // pictures
    if (S.edit && $("epSave")) {
      const e = S.edit;
      box.querySelectorAll(".ep").forEach((el) => {
        const i = +el.dataset.i, pos = e.order.indexOf(i);
        el.querySelector(".epOn").addEventListener("change", (ev) => { if (ev.target.checked) e.off.delete(i); else e.off.add(i); renderDetail(); });
        el.querySelector(".epL").addEventListener("click", () => { e.order.splice(pos, 1); e.order.splice(pos - 1, 0, i); renderDetail(); });
        el.querySelector(".epR").addEventListener("click", () => { e.order.splice(pos, 1); e.order.splice(pos + 1, 0, i); renderDetail(); });
      });
      const keep = () => e.order.filter((i) => !e.off.has(i));
      $("epReset").addEventListener("click", () => { S.edit = null; renderDetail(); });
      $("epCopy").addEventListener("click", () => act(api("edit_pictures", { id: it.id, keep: keep(), as_copy: true }), afterEdit));
      RS.armed($("epSave"), () => act(api("edit_pictures", { id: it.id, keep: keep(), as_copy: false }), afterEdit));
    }
    // voice
    if ($("trSave")) {
      const trim = (copy) => act(api("trim_audio", { id: it.id, start: +$("trA").value, end: +$("trB").value, as_copy: copy }), afterEdit);
      $("trCopy").addEventListener("click", () => trim(true));
      RS.armed($("trSave"), () => trim(false));
      if ($("trMark")) $("trMark").addEventListener("click", () => {
        const t = +$("voicePlayer").currentTime.toFixed(1);
        if (t < +$("trB").value / 2 || !+$("trA").value) $("trA").value = t; else $("trB").value = t;
      });
      if ($("sndRemove")) RS.armed($("sndRemove"), () => act(api("trim_audio", { id: it.id, remove: true, as_copy: false }), afterEdit));
    }
    if ($("sndPick")) {
      $("sndPick").addEventListener("click", () => $("pickAudio").click());
      $("sndApply").addEventListener("click", () => {
        if (!S.sndToken) return toast("Choose an audio or video file first.", true);
        RS.job("soundtrack", { ids: [it.id], upload: S.sndToken, seconds: +$("sndSecs").value, clean: $("sndClean").checked });
      });
    }
  }
  async function afterChange() { S.pv = Date.now(); await loadMods(true); }
  async function afterEdit(r) { S.edit = null; S.pv = Date.now(); if (r && r.id) S.open = r.id; await loadMods(true); }

  // ---------------------------------------------------------------- start
  RS.jobDone.push(async () => { S.pv = Date.now(); if (RS.current === "library" || S.items.length) await loadMods(true); });
  RS.views.library = {
    init() {
      RS.options($("concept"), [["", "Any concept"]].concat(RS.session.concepts.map((c) => [c, RS.label(c)])), "");
      $("search").addEventListener("input", (e) => { S.q = e.target.value; renderGrid(); });
      $("kinds").addEventListener("click", (e) => {
        const b = e.target.closest("button"); if (!b) return;
        S.kind = b.dataset.kind; $("kinds").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b)); renderGrid();
      });
      $("concept").addEventListener("change", (e) => { S.concept = e.target.value; renderGrid(); });
      $("sort").addEventListener("change", (e) => { S.sort = e.target.value; renderGrid(); });
      const menu = $("menuList");
      $("menuBtn").addEventListener("click", (e) => { e.stopPropagation(); menu.hidden = !menu.hidden; $("menuBtn").setAttribute("aria-expanded", String(!menu.hidden)); });
      document.addEventListener("click", () => { menu.hidden = true; });
      menu.addEventListener("click", async (e) => {
        const a = e.target.dataset.act; if (!a) return;
        menu.hidden = true;
        if (a === "refresh") { await loadMods(true); toast("Refreshed."); }
        if (a === "reclassify") await act(api("reclassify", {}), () => loadMods(true));
        if (a === "frames-all") RS.job("store_frames", { ids: [], all_missing: true }, "every mod missing them");
      });
      $("pickPreview").addEventListener("change", async (e) => {
        const f = e.target.files[0]; e.target.value = "";
        if (!f || !S.open) return;
        await act(api("preview?id=" + enc(S.open), f, true), afterChange);
      });
      $("pickAudio").addEventListener("change", async (e) => {
        const f = e.target.files[0]; e.target.value = "";
        if (!f) return;
        toast("Uploading " + f.name + "…");
        const r = await act(RS.upload(f));
        if (r && r.token) { S.sndToken = r.token; S.sndName = f.name; if ($("sndName")) $("sndName").textContent = f.name; toast("Ready: " + f.name); }
      });
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && RS.current === "library" && S.picked.size && !document.querySelector(".zoom")) { S.picked.clear(); renderGrid(); renderBulk(); }
      });
      wireBulk();
    },
    show() { loadMods(true); },
    refresh() { loadMods(true); },
    jobs() { if (S.detail) renderDetail(); },
  };
})();
