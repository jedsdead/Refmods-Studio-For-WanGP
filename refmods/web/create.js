/* Refmods Studio: the Create page. Sources are uploaded as they're added; Python works out the estimate
   (refmods/create_service.py) and runs the extraction as a task on the model. */
(function () {
  "use strict";
  const RS = window.RS, $ = RS.$, esc = RS.esc, enc = RS.enc, api = RS.api, toast = RS.toast;
  const S = { family: "h3", mode: "training", split: "all", sources: [], estimate: null, timer: 0, job: null, result: null };
  const FORM_KEY = "refmods.create.options";
  const fileUrl = (token) => "api/upload?token=" + enc(token);

  // ---------------------------------------------------------------- the form
  function form() {
    const num = (id) => +$(id).value;
    return {
      family: S.family, model: S.family === "flux" ? $("cFluxModel").value : RS.model(),
      name: $("cName").value.trim(), concept: $("cConcept").value, description: $("cDesc").value.trim(),
      split: S.split, mode: S.mode, budget: num("cBudget"), layout: $("cLayout").value,
      video_as_pictures: S.family === "flux" || $("cAsPictures").checked, pictures_per_second: num("cPps"),
      audio_seconds: num("cAudioSecs"), use_clip_audio: $("cClipAudio").checked, clean_audio: $("cCleanAudio").checked,
      ref_resolution: num("cRefRes"), enc_resolution: num("cEncRes"), max_tokens: num("cMaxTok"),
      pool_h: num("cPoolH"), pool_w: num("cPoolW"), identity: num("cIdent"), multiplier: num("cMult"),
      merge: $("cMerge").checked, remove_background: $("cRembg").checked, save: !$("cTest").checked,
    };
  }
  const KEPT = ["cPps", "cAudioSecs", "cRefRes", "cEncRes", "cMaxTok", "cPoolH", "cPoolW", "cIdent", "cMult", "cBudget", "cLayout"];
  const KEPT_CHECKS = ["cAsPictures", "cClipAudio", "cCleanAudio", "cMerge", "cRembg"];
  function saveOptions() {
    const o = { family: S.family, mode: S.mode, split: S.split, fluxModel: $("cFluxModel").value };
    KEPT.forEach((id) => { o[id] = $(id).value; });
    KEPT_CHECKS.forEach((id) => { o[id] = $(id).checked; });
    RS.store(FORM_KEY, JSON.stringify(o));
  }
  function loadOptions() {
    let o = {};
    try { o = JSON.parse(RS.store(FORM_KEY) || "{}") || {}; } catch (_) { o = {}; }
    KEPT.forEach((id) => { if (o[id] !== undefined && o[id] !== "") $(id).value = o[id]; });
    KEPT_CHECKS.forEach((id) => { if (o[id] !== undefined) $(id).checked = !!o[id]; });
    if (o.fluxModel && [...$("cFluxModel").options].some((x) => x.value === o.fluxModel)) $("cFluxModel").value = o.fluxModel;
    setSeg("cFamily", "family", o.family || "h3"); setSeg("cMode", "mode", o.mode || "training"); setSeg("cSplit", "split", o.split || "all");
  }
  function setSeg(id, key, value) {
    S[key] = value;
    $(id).querySelectorAll("button").forEach((b) => b.classList.toggle("on", b.dataset[key] === value));
    if (key === "family") {
      $("view-create").classList.toggle("flux", value === "flux");
      const concepts = value === "flux" ? RS.session.flux_concepts : RS.session.concepts;
      const keep = $("cConcept").value;
      RS.options($("cConcept"), concepts.map((c) => [c, RS.label(c)]), concepts.includes(keep) ? keep : (value === "flux" ? "identity" : "generic"));
    }
    if (key === "mode") {
      $("view-create").classList.toggle("encode", value === "encode");
      $("cModeNote").textContent = value === "encode" ? "Exact, best for faces. Bigger." : "Pooled and smaller, for general concepts.";
    }
  }
  function changed() { saveOptions(); clearTimeout(S.timer); S.timer = setTimeout(refreshEstimate, 250); }

  // ---------------------------------------------------------------- sources
  async function addFiles(files) {
    const list = [...files];
    if (!list.length) return;
    let added = 0;
    for (const f of list) {
      if (!/^(image|video|audio)\//.test(f.type) && !/\.(png|jpe?g|webp|bmp|gif|mp4|mov|webm|mkv|avi|m4v|wav|mp3|flac|ogg|m4a|aac|opus)$/i.test(f.name)) {
        toast(`${f.name} isn't a picture, video or audio file.`, true); continue;
      }
      toast(`Uploading ${f.name}…`);
      try {
        const r = await RS.upload(f);
        if (r.probe_error) { toast(`Couldn't read ${f.name}: ${r.probe_error}`, true); continue; }
        S.sources.push({ token: r.token, name: r.name || f.name, kind: r.kind, width: r.width, height: r.height,
                         seconds: r.seconds, start: 0, end: r.seconds || 0 });
        added++;
      } catch (e) { toast(`${f.name}: ${e.message}`, true); }
    }
    if (added) toast(`Added ${added} file${added === 1 ? "" : "s"}.`);
    renderSources(); changed();
  }
  const trimmed = (s) => (+s.start || 0) > 0.01 || ((+s.end || 0) && (+s.end) < (+s.seconds || 0) - 0.05);
  function renderSources() {
    let n = 0;
    $("cSources").innerHTML = S.sources.map((s, i) => {
      const label = s.kind === "audio" ? "♪" : String(++n);
      const pic = s.kind === "image" ? `<img src="${fileUrl(s.token)}" alt="">`
        : s.kind === "video" ? `<video src="${fileUrl(s.token)}#t=${(s.start || 0) + 0.1}" muted preload="metadata"></video>`
        : `<div class="ph"><b>♪</b>audio</div>`;
      const facts = s.kind === "image" ? `${s.width}×${s.height}` : s.kind === "video" ? `${s.width}×${s.height} · ${(+s.seconds || 0).toFixed(1)}s` : `${s.seconds != null ? (+s.seconds).toFixed(1) + "s" : ""}`;
      const edited = s.orig ? `<span class="muted">${s.kind === "video" ? "edited" : "cropped"}</span>` : "";
      const tools = s.kind === "image" ? `<div class="row"><button class="small cCrop">Crop</button><button class="small cSubj" title="Crop to the person or object, found with Wan2GP's background removal">To subject</button><button class="small cBlur" title="Blur everything behind the person or object">Blur back</button>${edited}</div>`
        : s.kind === "video" && S.family === "flux" ? `<div class="row"><span class="muted">the whole video</span><button class="small cCrop" title="Crop, turn or mirror the video">Crop…</button>${edited}</div>`
        : `<div class="trim">Use <input type="number" class="tA" min="0" max="${s.seconds}" step="0.1" value="${(+s.start || 0).toFixed(1)}"> to <input type="number" class="tB" min="0" max="${s.seconds}" step="0.1" value="${(+s.end || 0).toFixed(1)}"> s</div>
           <div class="row"><button class="small cTrim">Trim…</button>${s.kind === "video" ? `<button class="small cCrop" title="Crop, turn or mirror the video">Crop…</button>` : ""}${trimmed(s) ? `<span class="muted">${(s.end - s.start).toFixed(1)}s kept</span>` : ""}${s.kind === "video" ? edited : ""}</div>`;
      return `<div class="src" data-i="${i}" draggable="true"><div class="pic">${pic}</div><span class="n">${label}</span>
        <button class="x" title="Remove">×</button><div class="txt"><span class="nm" title="${esc(s.name)}">${esc(s.name)}</span><span class="muted">${esc(facts)}</span>${tools}</div></div>`;
    }).join("");
    $("cSources").querySelectorAll(".src").forEach((el) => {
      const i = +el.dataset.i, s = S.sources[i];
      el.querySelector(".x").addEventListener("click", () => { S.sources.splice(i, 1); renderSources(); changed(); });
      if (el.querySelector(".cCrop")) el.querySelector(".cCrop").addEventListener("click", () => crop(i));
      for (const [cls, op, done] of [[".cSubj", "subject", "Cropped to the subject."], [".cBlur", "blur", "Blurred the background."]]) {
        const b = el.querySelector(cls);
        if (b) b.addEventListener("click", async () => {
          b.disabled = true; toast(op === "subject" ? "Finding the subject…" : "Blurring the background…");
          try {
            const source = s.orig || s;
            const r = await api("picture_tool", { token: s.token, op });
            S.sources[i] = { ...s, token: r.token, width: r.width, height: r.height, orig: { ...source } };
            renderSources(); changed(); toast(done);
          } catch (e) { toast("Couldn't do that: " + e.message, true); b.disabled = false; }
        });
      }
      if (el.querySelector(".cTrim")) el.querySelector(".cTrim").addEventListener("click", async () => {
        const r = await RS.trim({ src: fileUrl(s.token), kind: s.kind, title: "Trim " + s.name, start: s.start, end: s.end || s.seconds,
                                  duration: s.seconds, min: s.kind === "audio" ? 2 : 0.2,
                                  onFrame: s.kind === "video" ? (blob, t) => useFrame(i, s, blob, t) : null,
                                  onAudio: S.family === "h3" ? (a, b) => useAudio(s, a, b) : null });
        if (r) { s.start = r.start; s.end = r.end; renderSources(); changed(); }
      });
      if (el.querySelector(".tA")) {
        const clamp = (v) => Math.max(0, Math.min(+s.seconds || 0, +v || 0));
        el.querySelector(".tA").addEventListener("change", (e) => { s.start = clamp(e.target.value); if (s.end <= s.start) s.end = +s.seconds || s.start; renderSources(); changed(); });
        el.querySelector(".tB").addEventListener("change", (e) => { s.end = clamp(e.target.value) || (+s.seconds || 0); if (s.end <= s.start) s.start = 0; renderSources(); changed(); });
      }
      el.querySelector(".pic").addEventListener("dblclick", () => { if (s.kind === "image") RS.zoom(fileUrl(s.token)); });
      el.addEventListener("dragstart", (e) => { el.classList.add("dragging"); e.dataTransfer.setData("text/x-src", String(i)); e.dataTransfer.effectAllowed = "move"; });
      el.addEventListener("dragend", () => el.classList.remove("dragging"));
      el.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("text/x-src")) { e.preventDefault(); el.classList.add("over"); } });
      el.addEventListener("dragleave", () => el.classList.remove("over"));
      el.addEventListener("drop", (e) => {
        el.classList.remove("over");
        const from = e.dataTransfer.getData("text/x-src");
        if (from === "") return;
        e.preventDefault(); e.stopPropagation();
        const [moved] = S.sources.splice(+from, 1); S.sources.splice(i, 0, moved);
        renderSources(); changed();
      });
    });
    const kinds = new Set(S.sources.map((s) => s.kind));
    document.querySelectorAll("#view-create .video-opt").forEach((x) => { x.hidden = !kinds.has("video"); });
    document.querySelectorAll("#view-create .audio-opt").forEach((x) => { x.hidden = !kinds.has("audio") && !kinds.has("video"); });
    document.querySelectorAll("#view-create .clip-audio").forEach((x) => { x.hidden = !kinds.has("video") || kinds.has("audio"); });
    $("cAsPictures").closest(".video-opt").querySelector(".pps").hidden = S.family !== "flux" && !$("cAsPictures").checked;
  }

  // The trim editor's Use frame and Use audio: a new source from part of this one.
  async function useFrame(index, s, blob, t) {
    try {
      const file = new File([blob], `${s.name.replace(/\.[^.]+$/, "")}_${t.toFixed(1)}s.png`, { type: "image/png" });
      const r = await RS.upload(file);
      S.sources.splice(index + 1, 0, { token: r.token, name: r.name || file.name, kind: "image", width: r.width, height: r.height, start: 0, end: 0 });
      renderSources(); changed(); toast(`Added the frame at ${t.toFixed(1)} s as a picture.`);
    } catch (e) { toast("Couldn't add the frame: " + e.message, true); }
  }
  async function useAudio(s, a, b) {
    if (S.sources.some((x) => x.kind === "audio") && !confirm("There's already an audio file, and only the first is used. Add this one anyway?")) return;
    try {
      const r = await api("cut_audio", { token: s.token, start: a, end: b });
      S.sources.push({ token: r.token, name: r.name, kind: "audio", seconds: r.seconds, start: 0, end: r.seconds || 0 });
      renderSources(); changed(); toast(`Added ${(b - a).toFixed(1)} s of sound as an audio file.`);
    } catch (e) { toast("Couldn't cut the sound: " + e.message, true); }
  }

  // ---------------------------------------------------------------- crop
  function crop(index) {
    const s = S.sources[index], dlg = $("cropDlg"), img = $("cropImg"), box = $("cropBox");
    const source = s.orig || s;                  // always crop from the original picture
    let ratio = 0, rect = null, scale = 1;
    const place = () => { box.style.left = rect.x + "px"; box.style.top = rect.y + "px"; box.style.width = rect.w + "px"; box.style.height = rect.h + "px";
      $("cropInfo").textContent = `${Math.round(rect.w * scale)} × ${Math.round(rect.h * scale)} px`; };
    const fit = () => {
      const W = img.clientWidth, H = img.clientHeight;
      let w = W, h = H;
      if (ratio) { if (W / H > ratio) w = H * ratio; else h = W / ratio; }
      rect = { x: (W - w) / 2, y: (H - h) / 2, w, h }; place();
    };
    img.onload = () => { scale = img.naturalWidth / img.clientWidth; fit(); };
    const video = source.kind === "video";
    const ops = [];                               // a video's turns and flips, done by ffmpeg on Crop
    if (video) {
      // A video is cropped on one of its frames, then ffmpeg makes the edited copy.
      const v = document.createElement("video");
      v.muted = true; v.preload = "auto"; v.src = fileUrl(source.token);
      v.addEventListener("loadeddata", () => { v.currentTime = Math.min((+s.start || 0) + 0.1, Math.max(0, (v.duration || 1) - 0.05)); }, { once: true });
      v.addEventListener("seeked", () => {
        const c = document.createElement("canvas"); c.width = v.videoWidth; c.height = v.videoHeight;
        c.getContext("2d").drawImage(v, 0, 0); img.src = c.toDataURL("image/png");
      }, { once: true });
    } else img.src = fileUrl(source.token);
    $("cropReset").textContent = video ? "Original video" : "Whole picture";
    $("cropOk").textContent = video ? "Make the copy" : "Crop";
    // Rotate and Mirror make a turned copy of the picture to crop from; the original stays as it was.
    let work = source;
    const transform = (rotate) => {
      if (video) {
        const c = document.createElement("canvas"), w = img.naturalWidth, h = img.naturalHeight;
        c.width = rotate ? h : w; c.height = rotate ? w : h;
        const g = c.getContext("2d");
        if (rotate) { g.translate(h, 0); g.rotate(Math.PI / 2); } else { g.translate(w, 0); g.scale(-1, 1); }
        g.drawImage(img, 0, 0); ops.push(rotate ? "r" : "m"); img.src = c.toDataURL("image/png");
        return;
      }
      const c = document.createElement("canvas"), w = img.naturalWidth, h = img.naturalHeight;
      c.width = rotate ? h : w; c.height = rotate ? w : h;
      const g = c.getContext("2d");
      if (rotate) { g.translate(h, 0); g.rotate(Math.PI / 2); } else { g.translate(w, 0); g.scale(-1, 1); }
      g.drawImage(img, 0, 0);
      c.toBlob(async (blob) => {
        try {
          const r = await RS.upload(new File([blob], (rotate ? "turned_" : "mirrored_") + source.name.replace(/\.[^.]+$/, "") + ".png", { type: "image/png" }));
          work = { ...source, token: r.token, width: c.width, height: c.height };
          img.src = fileUrl(r.token);
        } catch (e) { toast("Couldn't turn it: " + e.message, true); }
      }, "image/png");
    };
    $("cropRotate").onclick = () => transform(true);
    $("cropMirror").onclick = () => transform(false);
    $("cropAspect").querySelectorAll("button").forEach((b) => {
      b.classList.toggle("on", b.dataset.r === "0");
      b.onclick = () => { ratio = +b.dataset.r; $("cropAspect").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b)); fit(); };
    });
    let drag = null;
    box.onpointerdown = (e) => {
      e.preventDefault(); box.setPointerCapture(e.pointerId);
      drag = { mode: e.target.classList.contains("h") ? [...e.target.classList].find((c) => c.length === 2) : "move", x: e.clientX, y: e.clientY, r: { ...rect } };
    };
    box.onpointermove = (e) => {
      if (!drag) return;
      const z = RS.zoom(), W = img.clientWidth, H = img.clientHeight, dx = (e.clientX - drag.x) / z, dy = (e.clientY - drag.y) / z, r = { ...drag.r };
      if (drag.mode === "move") {
        r.x = Math.max(0, Math.min(W - r.w, r.x + dx)); r.y = Math.max(0, Math.min(H - r.h, r.y + dy));
      } else {
        const west = drag.mode.includes("w"), north = drag.mode.includes("n");
        let w = Math.max(24, drag.r.w + (west ? -dx : dx)), h = Math.max(24, drag.r.h + (north ? -dy : dy));
        if (ratio) { if (Math.abs(dx) > Math.abs(dy)) h = w / ratio; else w = h * ratio; }
        const right = drag.r.x + drag.r.w, bottom = drag.r.y + drag.r.h;
        w = Math.min(w, west ? right : W - drag.r.x); h = Math.min(h, north ? bottom : H - drag.r.y);
        if (ratio) { if (w / h > ratio) w = h * ratio; else h = w / ratio; }
        r.w = w; r.h = h; r.x = west ? right - w : drag.r.x; r.y = north ? bottom - h : drag.r.y;
      }
      rect = r; place();
    };
    box.onpointerup = () => { drag = null; };
    $("cropCancel").onclick = () => dlg.close();
    $("cropReset").onclick = () => {
      if (s.orig) { S.sources[index] = { ...s.orig }; renderSources(); changed(); }
      dlg.close();
    };
    $("cropOk").onclick = async () => {
      if (video) {
        const sx = Math.round(rect.x * scale), sy = Math.round(rect.y * scale), sw = Math.round(rect.w * scale), sh = Math.round(rect.h * scale);
        const whole = sw >= img.naturalWidth - 2 && sh >= img.naturalHeight - 2;
        if (whole && !ops.length) { dlg.close(); return; }
        dlg.close(); toast("Making the edited copy of the video…");
        try {
          const r = await api("process_video", { token: source.token, ops, crop: whole ? null : { x: sx, y: sy, w: sw, h: sh } });
          S.sources[index] = { ...s, token: r.token, width: r.width, height: r.height, seconds: r.seconds || s.seconds, orig: { ...source } };
          renderSources(); changed(); toast("Done: the video is now the edited copy.");
        } catch (e) { toast("Couldn't edit the video: " + e.message, true); }
        return;
      }
      const canvas = document.createElement("canvas");
      const sx = Math.round(rect.x * scale), sy = Math.round(rect.y * scale), sw = Math.round(rect.w * scale), sh = Math.round(rect.h * scale);
      canvas.width = sw; canvas.height = sh;
      canvas.getContext("2d").drawImage(img, sx, sy, sw, sh, 0, 0, sw, sh);
      canvas.toBlob(async (blob) => {
        dlg.close();
        try {
          const file = new File([blob], "crop_" + source.name.replace(/\.[^.]+$/, "") + ".png", { type: "image/png" });
          const r = await RS.upload(file);
          S.sources[index] = { ...work, token: r.token, width: sw, height: sh, orig: { ...source } };
          renderSources(); changed();
        } catch (e) { toast("Couldn't crop: " + e.message, true); }
      }, "image/png");
    };
    dlg.showModal();
  }

  // ---------------------------------------------------------------- the estimate and Create
  async function refreshEstimate() {
    const f = form();
    let e;
    try { e = await api("estimate", { form: f, sources: S.sources }); } catch (err) { $("cEstimate").innerHTML = `<span class="err">${esc(err.message)}</span>`; return; }
    S.estimate = e;
    const many = e.mods.length > 1;
    const pictures = e.mods.reduce((a, m) => a + (m.pictures || 0), 0), clip = e.mods.reduce((a, m) => a + (m.clip_seconds || 0), 0);
    $("cEstimate").innerHTML = !S.sources.length ? `<span class="muted">Add sources to see what the mod will cost.</span>` : `
      <div><span class="bignum">${e.tokens.toLocaleString()}</span> tokens</div>
      <div class="muted">about ${RS.size(e.bytes)}${many ? ` in ${e.mods.length} mods` : ""}</div>
      <div class="muted">${[pictures ? `${pictures} picture${pictures === 1 ? "" : "s"}` : "", clip ? `${clip.toFixed(1)}s of video` : ""].filter(Boolean).join(" · ")}</div>
      ${many ? `<div class="mods">${e.mods.map((m) => `<div class="small"><b>${esc(m.name)}</b> <span class="muted">${m.tokens.toLocaleString()} tok · ${RS.size(m.bytes)}</span></div>`).join("")}</div>` : ""}
      ${e.warnings.map((w) => `<div class="warn">${esc(w)}</div>`).join("")}`;
    lockButton();
  }
  function lockButton() {
    const e = S.estimate, running = S.job && RS.running("create");
    $("cGo").disabled = !e || !e.ready || running;
    $("cGo").textContent = running ? "Creating…" : (e && e.mods.length > 1 ? `Create ${e.mods.length} mods` : (form().save ? "Create" : "Test run"));
    $("cBlockers").innerHTML = e && !e.ready ? e.blockers.map((b) => esc(b)).join("<br>") : "";
  }
  async function go() {
    const f = form();
    if (!S.estimate || !S.estimate.ready) return;
    S.result = null; renderResult();
    S.job = await RS.job("create", { model: f.model, form: f, sources: S.sources, ids: [] }, f.name);
    lockButton();
  }
  function renderResult() {
    const r = S.result;
    if (!r) { $("cResult").innerHTML = ""; return; }
    $("cResult").innerHTML = `<div class="result${r.ok ? "" : " bad"}"><span>${esc(r.message)}</span>
      ${(r.made || []).map((id) => `<button class="small cOpen" data-id="${esc(id)}">Open ${esc(id.split(":")[1])} in the Library</button>`).join("")}
      ${r.ok ? `<button class="small" id="cAgain">Start over</button>` : ""}</div>`;
    $("cResult").querySelectorAll(".cOpen").forEach((b) => b.addEventListener("click", async () => { await RS.library.load(); RS.library.open(b.dataset.id); }));
    if ($("cAgain")) $("cAgain").addEventListener("click", reset);
  }
  function reset() {
    S.sources = []; S.result = null; $("cName").value = "my_mod"; $("cDesc").value = "";
    renderSources(); renderResult(); changed();
  }
  RS.jobDone.push(async (j) => {
    if (j.op !== "create" || j.id !== S.job) return;
    S.result = { ok: j.state === "done", message: j.message, made: j.made || [] };
    S.job = null; renderResult(); refreshEstimate();
  });

  // ---------------------------------------------------------------- start
  RS.views.create = {
    init() {
      const m = RS.session.models || {};
      RS.options($("cFluxModel"), (m.flux || []).length ? m.flux.map(([l, t]) => [t, l]) : [["", "No Flux model found"]], (m.flux && m.flux[0]) ? m.flux[0][1] : "");
      RS.options($("cBudget"), RS.session.budgets.map(([l, v]) => [v, l]), RS.session.budget_default);
      RS.options($("cLayout"), RS.session.layouts.map(([l, v]) => [v, l]), RS.session.layout_default);
      $("cEncRes").value = RS.session.enc_default || 1024;
      loadOptions();
      [["cFamily", "family"], ["cMode", "mode"], ["cSplit", "split"]].forEach(([id, key]) => $(id).addEventListener("click", (e) => {
        const b = e.target.closest("button"); if (!b) return;
        setSeg(id, key, b.dataset[key]); renderSources(); changed();
      }));
      document.querySelectorAll("#view-create input, #view-create select").forEach((el) => {
        if (el.id === "cFiles") return;
        el.addEventListener(el.type === "checkbox" || el.tagName === "SELECT" ? "change" : "input", () => {
          if (el.id === "cAsPictures") renderSources();
          changed();
        });
      });
      $("cPick").addEventListener("click", (e) => { e.stopPropagation(); $("cFiles").click(); });
      $("cFiles").addEventListener("change", (e) => { addFiles(e.target.files); e.target.value = ""; });
      const drop = $("cDrop");
      drop.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); drop.classList.add("over"); } });
      drop.addEventListener("dragleave", () => drop.classList.remove("over"));
      drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); addFiles(e.dataTransfer.files); });
      document.addEventListener("paste", (e) => {
        if (RS.current !== "create") return;
        const files = [...(e.clipboardData || {}).files || []];
        if (files.length) addFiles(files);
      });
      $("cGo").addEventListener("click", go);
      $("cReset").addEventListener("click", reset);
      renderSources();
    },
    show() { refreshEstimate(); },
    model() { refreshEstimate(); },
    jobs() { lockButton(); },
  };
})();
