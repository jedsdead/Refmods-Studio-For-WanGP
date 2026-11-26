/* Refmods Studio: what the Refmods pages share. Helpers, the theme, the subtabs, the MiniMax H3 model picker and
   the jobs that run on the model. Each page (library.js, create.js, packs.js, setup.js) registers itself in RS.views. */
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const RS = window.RS = { $, views: {}, session: null, jobDone: [], watch: {} };

  RS.esc = (t) => String(t == null ? "" : t).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  RS.enc = encodeURIComponent;
  RS.api = async function (path, body, raw) {
    const opts = body === undefined ? {} : raw ? { method: "POST", body } :
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const res = await fetch("api/" + path, opts);
    let data = null;
    try { data = await res.json(); } catch (_) { data = null; }
    if (!res.ok || (data && data.ok === false && data.message && res.status >= 400)) {
      throw new Error((data && data.message) || res.status + " " + res.statusText);
    }
    return data;
  };
  let toastTimer = 0;
  RS.toast = function (text, bad) {
    const t = $("toast");
    t.textContent = text || ""; t.className = "toast show" + (bad ? " err" : "");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.className = "toast"; }, bad ? 6000 : 3500);
  };
  RS.act = async function (promise, after) {
    try {
      const r = await promise;
      if (r && r.message) RS.toast(r.message, r.ok === false);
      if (after) await after(r);
      return r;
    } catch (e) { RS.toast(e.message, true); return null; }
  };
  RS.store = function (key, value) {
    try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch (_) { /* no storage here */ }
    return null;
  };
  RS.options = function (select, items, value) {
    select.innerHTML = items.map((it) => {
      const [v, label] = Array.isArray(it) ? it : [it, it];
      return `<option value="${RS.esc(v)}"${String(v) === String(value) ? " selected" : ""}>${RS.esc(label)}</option>`;
    }).join("");
  };
  // A button that asks for a second click before doing something that can't be undone.
  RS.armed = function (button, fn) {
    button.addEventListener("click", () => {
      if (button.classList.contains("armed")) { button.classList.remove("armed"); button.textContent = button.dataset.label; fn(); return; }
      button.dataset.label = button.textContent; button.classList.add("armed"); button.textContent = "Click again";
      setTimeout(() => { if (button.classList.contains("armed")) { button.classList.remove("armed"); button.textContent = button.dataset.label; } }, 3000);
    });
  };
  RS.zoom = function (src) {
    const z = document.createElement("div"); z.className = "zoom"; z.innerHTML = `<img src="${src}" alt="">`;
    z.addEventListener("click", () => z.remove()); document.body.appendChild(z);
  };
  RS.label = (c) => String(c || "").replace("_", " & ");
  RS.size = (bytes) => bytes >= 1048576 ? (bytes / 1048576).toFixed(bytes >= 10485760 ? 0 : 1) + " MB" : Math.max(1, Math.round(bytes / 1024)) + " KB";
  RS.upload = async function (file) {
    return RS.api("upload?name=" + RS.enc(file.name), file, true);
  };

  // ---------------------------------------------------------------- the trim editor (videos and sound)
  // RS.trim({src, kind: "video"|"audio", title, start, end, min}) -> Promise<{start, end} | null>
  RS.trim = function (opts) {
    return new Promise((resolve) => {
      const dlg = $("trimDlg"), box = $("trimMedia"), tl = $("trimTl"), canvas = $("trimWave");
      const media = document.createElement(opts.kind === "video" ? "video" : "audio");
      media.src = opts.src; media.preload = "auto"; media.playsInline = true;
      box.innerHTML = ""; box.appendChild(media);
      $("trimTitle").textContent = opts.title || "Trim";
      const min = opts.min || 0.1;
      let dur = 0, a = +opts.start || 0, b = +opts.end || 0, stopAt = null, raf = 0, drag = null, done = false;
      const fmt = (t) => (Math.round(t * 10) / 10).toFixed(1) + " s";
      const pct = (t) => (dur ? (t / dur) * 100 : 0) + "%";
      const draw = () => {
        $("trimSel").style.left = pct(a); $("trimSel").style.width = (dur ? ((b - a) / dur) * 100 : 0) + "%";
        $("trimIn").style.left = pct(a); $("trimOut").style.left = pct(b);
        $("trimHead").style.left = pct(media.currentTime || 0);
        $("trimNow").textContent = fmt(media.currentTime || 0) + " of " + fmt(dur);
        $("trimInfo").textContent = `Keeping ${fmt(a)} to ${fmt(b)} (${fmt(b - a)})`;
        if (document.activeElement !== $("trimA")) $("trimA").value = a.toFixed(1);
        if (document.activeElement !== $("trimB")) $("trimB").value = b.toFixed(1);
        $("trimPP").textContent = media.paused ? "Play" : "Pause";
        $("trimOk").disabled = b - a < min - 0.001;
      };
      const tick = () => {
        if (stopAt != null && media.currentTime >= stopAt) { media.pause(); stopAt = null; }
        draw();
        if (!media.paused) raf = requestAnimationFrame(tick);
      };
      const timeAt = (e) => { const r = tl.getBoundingClientRect(); return Math.max(0, Math.min(dur, ((e.clientX - r.left) / r.width) * dur)); };
      const setA = (t) => { a = Math.max(0, Math.min(t, b - min)); draw(); };
      const setB = (t) => { b = Math.min(dur, Math.max(t, a + min)); draw(); };
      media.addEventListener("loadedmetadata", () => {
        dur = media.duration && isFinite(media.duration) ? media.duration : (+opts.duration || 0);
        if (!b || b > dur) b = dur;
        a = Math.min(a, Math.max(0, b - min));
        media.currentTime = a;
        draw();
      });
      media.addEventListener("play", () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(tick); });
      media.addEventListener("pause", draw);
      media.addEventListener("seeked", draw);
      // A waveform for sound, so you can see where the words are.
      const ctx2 = canvas.getContext("2d");
      ctx2.clearRect(0, 0, canvas.width, canvas.height);
      if (opts.kind !== "video") {
        fetch(opts.src).then((r) => r.arrayBuffer()).then((buf) => new (window.AudioContext || window.webkitAudioContext)().decodeAudioData(buf)).then((audio) => {
          const w = canvas.width = tl.clientWidth * 2, h = canvas.height = tl.clientHeight * 2, data = audio.getChannelData(0);
          const step = Math.max(1, Math.floor(data.length / w));
          ctx2.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--muted") || "#9ca3af";
          for (let x = 0; x < w; x++) {
            let peak = 0;
            for (let i = x * step, end = Math.min(data.length, i + step); i < end; i += 4) peak = Math.max(peak, Math.abs(data[i]));
            const bar = Math.max(1, peak * h * 0.9);
            ctx2.fillRect(x, (h - bar) / 2, 1, bar);
          }
        }).catch(() => { /* no waveform, still trimmable */ });
      }
      tl.onpointerdown = (e) => {
        e.preventDefault(); tl.setPointerCapture(e.pointerId);
        drag = e.target === $("trimIn") ? "in" : e.target === $("trimOut") ? "out" : "seek";
        tl.onpointermove(e);
      };
      tl.onpointermove = (e) => {
        if (!drag) return;
        const t = timeAt(e);
        if (drag === "in") { setA(t); media.currentTime = a; }
        else if (drag === "out") { setB(t); media.currentTime = b; }
        else { media.currentTime = t; draw(); }
      };
      tl.onpointerup = () => { drag = null; };
      $("trimPP").onclick = () => { stopAt = null; if (media.paused) media.play(); else media.pause(); };
      $("trimPlaySel").onclick = () => { media.currentTime = a; stopAt = b; media.play(); };
      $("trimSetIn").onclick = () => setA(media.currentTime || 0);
      $("trimSetOut").onclick = () => setB(media.currentTime || 0);
      $("trimA").onchange = (e) => setA(+e.target.value || 0);
      $("trimB").onchange = (e) => setB(+e.target.value || dur);
      const keys = (e) => {
        if (e.target.tagName === "INPUT") return;
        if (e.key === " ") { e.preventDefault(); $("trimPP").click(); }
        else if (e.key === "i" || e.key === "I") $("trimSetIn").click();
        else if (e.key === "o" || e.key === "O") $("trimSetOut").click();
      };
      const finish = (result) => {
        if (done) return; done = true;
        media.pause(); cancelAnimationFrame(raf); dlg.removeEventListener("keydown", keys);
        if (dlg.open) dlg.close();
        box.innerHTML = "";
        resolve(result);
      };
      dlg.addEventListener("keydown", keys);
      dlg.onclose = () => finish(null);
      $("trimCancel").onclick = () => finish(null);
      $("trimOk").onclick = () => finish({ start: Math.round(a * 100) / 100, end: Math.round(b * 100) / 100 });
      dlg.showModal();
    });
  };

  // ---------------------------------------------------------------- theme: follow WanGP
  RS.theme = function () {
    let dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    try {
      const doc = window.parent && window.parent !== window ? window.parent.document : null;
      if (doc) dark = doc.body.classList.contains("dark") || doc.documentElement.classList.contains("dark") ||
        !!doc.querySelector("gradio-app.dark, .gradio-container.dark");
    } catch (_) { /* opened on its own */ }
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  };

  // ---------------------------------------------------------------- subtabs
  RS.current = null;
  RS.show = function (name, arg) {
    if (!RS.views[name]) name = "library";
    RS.current = name;
    document.querySelectorAll(".view").forEach((v) => { v.hidden = v.id !== "view-" + name; });
    document.querySelectorAll("#tabs button").forEach((b) => b.classList.toggle("on", b.dataset.view === name));
    RS.store("refmods.view", name);
    const view = RS.views[name];
    if (view && view.show) view.show(arg);
  };

  // ---------------------------------------------------------------- the model
  RS.model = () => $("model").value;
  async function loadSession() {
    RS.session = await RS.api("session");
    const m = RS.session.models || {};
    const saved = RS.store("refmods.model");
    const h3 = (m.h3 || []).map(([label, type]) => [type, label]);
    RS.options($("model"), h3.length ? h3 : [["", "No MiniMax H3 Ref2VA model found"]],
      h3.some(([t]) => t === saved) ? saved : m.h3_default);
  }

  // ---------------------------------------------------------------- jobs
  const JOB_NAMES = { decompile: "Decompile", strength: "Strength preview", store_frames: "Encoder frames",
                      soundtrack: "Soundtrack", clean_audio: "Clean audio", convert: "Convert to Flux", create: "Create" };
  RS.running = (op, id) => Object.values(RS.watch).some((j) => j.op === op && (!id || (j.ids || []).includes(id)) &&
                                                           (j.state === "running" || j.state === "waiting"));
  RS.job = async function (op, payload, label) {
    const model = payload.model !== undefined ? payload.model : RS.model();
    if (!model) { RS.toast("Pick a MiniMax H3 model at the top first.", true); return null; }
    const r = await RS.act(RS.api("jobs", Object.assign({ op, model }, payload)));
    if (!r) return null;
    RS.watch[r.id] = { id: r.id, op, ids: payload.ids || [], label: label || "", state: "waiting", message: "Waiting for WanGP…" };
    renderJobs(); poll();
    Object.values(RS.views).forEach((v) => v.jobs && v.jobs());
    return r.id;
  };
  let polling = false;
  async function poll() {
    if (polling) return; polling = true;
    try {
      while (Object.values(RS.watch).some((j) => j.state === "waiting" || j.state === "running")) {
        await new Promise((r) => setTimeout(r, 1200));
        for (const j of Object.values(RS.watch)) {
          if (j.state !== "waiting" && j.state !== "running") continue;
          let s;
          try { s = await RS.api("jobs/" + j.id); } catch (_) { continue; }
          const was = j.state;
          Object.assign(j, { state: s.state === "missing" ? "error" : s.state, message: s.message || j.message, made: s.made, lines: s.lines });
          if (was !== j.state && (j.state === "done" || j.state === "error")) {
            setTimeout(() => { delete RS.watch[j.id]; renderJobs(); }, j.state === "done" ? 8000 : 20000);
            for (const fn of RS.jobDone) { try { await fn(j); } catch (e) { console.error(e); } }
          }
        }
        renderJobs();
      }
    } finally { polling = false; }
  }
  function renderJobs() {
    $("jobs").innerHTML = Object.values(RS.watch).map((j) => {
      const who = j.label || (j.ids || []).map((i) => i.split(":").pop().split("/").pop()).join(", ");
      return `<div class="job ${j.state}"><b>${RS.esc(JOB_NAMES[j.op] || j.op)}${who ? ": " + RS.esc(who) : ""}</b>${RS.esc(j.message || "")}</div>`;
    }).join("");
  }

  // ---------------------------------------------------------------- full screen (WanGP's own, as the Video Editor uses)
  const SVG = (d) => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${d}"/></svg>`;
  const EXPAND = SVG("M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"), EXIT = SVG("M10 4H5v16h5M14 8l4 4-4 4M18 12H9");
  RS.fullscreen = function (container, switcher) {
    let button = null, pdoc = null;
    try {
      const nav = window.parent !== window && window.frameElement && window.parent.WanGPAddonNavigation;
      if (!nav) return;
      const before = container.children.length;
      nav.headerButton(window.frameElement, container, "fsbtn");
      button = container.children.length > before ? container.lastElementChild : null;
      pdoc = window.parent.document;
    } catch (_) { return; }                        // opened on its own, or an older WanGP
    // Both Refmods Studio pages have a button, so each keeps its own icon in step.
    const paint = () => {
      const on = pdoc.documentElement.classList.contains("wangp-addon-fullscreen-open");
      document.documentElement.classList.toggle("rs-full", on);
      if (button) { button.title = on ? "Back to WanGP (Esc)" : "Open Full Screen"; button.setAttribute("aria-label", button.title); button.innerHTML = on ? EXIT : EXPAND; }
    };
    new MutationObserver(paint).observe(pdoc.documentElement, { attributes: true, attributeFilter: ["class"] });
    paint();
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !e.defaultPrevented && button && document.documentElement.classList.contains("rs-full") &&
          !document.querySelector("dialog[open], .zoom")) button.click();
    });
    // In full screen the frame covers WanGP's subtab bar, so the page offers the switch itself.
    if (switcher) switcher.querySelectorAll("button[data-sub]").forEach((b) => b.addEventListener("click", () => {
      const tab = [...pdoc.querySelectorAll(".rs-studio-tabs button[role=tab]")].find((t) => t.textContent.trim() === b.dataset.sub);
      if (tab) tab.click();
    }));
  };

  // ---------------------------------------------------------------- start
  async function start() {
    RS.theme();
    document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => RS.show(b.dataset.view)));
    $("model").addEventListener("change", (e) => { RS.store("refmods.model", e.target.value); Object.values(RS.views).forEach((v) => v.model && v.model()); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") { const z = document.querySelector(".zoom"); if (z) { z.remove(); e.preventDefault(); } } });
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) { RS.theme(); const v = RS.views[RS.current]; if (v && v.refresh) v.refresh(); }
    });
    try { new MutationObserver(RS.theme).observe(window.parent.document.body, { attributes: true, attributeFilter: ["class"] }); } catch (_) { /* on its own */ }
    try { await loadSession(); } catch (e) { RS.toast("Could not reach the plugin: " + e.message, true); }
    for (const v of Object.values(RS.views)) { try { if (v.init) await v.init(); } catch (e) { console.error(e); } }
    RS.fullscreen($("fsBox"), $("subSwitch"));
    const hash = location.hash.replace("#", "");
    RS.show(RS.views[hash] ? hash : (RS.store("refmods.view") || "library"));
    try {
      const active = (await RS.api("jobs")).jobs || [];
      active.forEach((j) => { RS.watch[j.id] = j; });
      if (active.length) { renderJobs(); poll(); }
    } catch (_) { /* none */ }
  }
  window.addEventListener("DOMContentLoaded", start);
})();
