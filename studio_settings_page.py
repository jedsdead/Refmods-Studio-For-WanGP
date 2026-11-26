"""
Refmods Studio's Settings subtab: a small web page served by the host plugin itself, so it is there whichever
half is turned off. It turns the halves on and off and says what didn't load.
"""

from __future__ import annotations

import html

from fastapi import Body, FastAPI
from fastapi.responses import HTMLResponse

WEB_PATH = "/refmods_settings"

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Refmods Studio settings</title>
<style>
:root { --bg: #0b0f19; --panel: #111827; --panel2: #0f1522; --line: #1f2937; --line2: #374151;
  --text: #e5e7eb; --muted: #9ca3af; --accent: #6366f1; --err: #f87171; --ok: #4ade80; }
:root[data-theme="light"] { --bg: #ffffff; --panel: #f9fafb; --panel2: #f3f4f6; --line: #e5e7eb; --line2: #d1d5db;
  --text: #111827; --muted: #4b5563; --accent: #4f46e5; --err: #b91c1c; --ok: #15803d; }
[hidden] { display: none !important; }
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
#app { padding: 12px 16px 40px; max-width: 760px; }
header { display: flex; align-items: center; gap: 12px; white-space: nowrap; margin-bottom: 14px; }
header h1 { font-size: 16px; margin: 0; } .grow { flex: 1; }
.muted { color: var(--muted); } .small { font-size: 12px; }
button { font: inherit; color: var(--text); background: var(--panel2); border: 1px solid var(--line2); border-radius: 6px; padding: 5px 12px; cursor: pointer; }
button:hover { border-color: var(--accent); } button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; margin-bottom: 12px; }
.card h2 { font-size: 13px; text-transform: uppercase; letter-spacing: .05em; color: var(--muted); margin: 0 0 8px; }
.half { display: flex; gap: 10px; align-items: flex-start; padding: 8px 0; border-top: 1px solid var(--line); }
.half:first-of-type { border-top: 0; } .half input { margin-top: 3px; width: 16px; height: 16px; }
.half b { display: block; }
.row { display: flex; gap: 10px; align-items: center; margin-top: 10px; }
.err { color: var(--err); } .ok { color: var(--ok); }
code { font-size: 12px; }
.seg { display: none; gap: 4px; } .rs-full .seg { display: inline-flex; }
.seg button.on { background: var(--accent); border-color: var(--accent); color: #fff; }
.fsbox { display: inline-flex; }
</style>
</head>
<body>
<div id="app">
  <header>
    <h1>Refmods Studio <span class="muted small">__VERSION__</span></h1>
    <span class="grow"></span>
    <div class="seg" id="subSwitch" title="Switch page"></div>
    <span id="fsBox" class="fsbox"></span>
  </header>

  <section class="card">
    <h2>Parts</h2>
    <p class="muted small" style="margin-top:0">Turn a part off to hide it completely. A part that's off isn't loaded at all, so
      turning off Refmods also removes its pipeline hooks; the other part keeps working. This page stays either way.
      <b>Restart WanGP</b> after saving.</p>
    <label class="half"><input type="checkbox" id="refmods"><span><b>Refmods</b>
      <span class="muted small">The mod library, Create, Packs and Setup, and the Refmods panel on the Generator page.</span></span></label>
    <label class="half"><input type="checkbox" id="builder"><span><b>Prompt Builder</b>
      <span class="muted small">Writes H3 prompts from what the Generator page sends. Without Refmods it works the same,
      minus packs and armed mods.</span></span></label>
    <div class="row"><button class="primary" id="save">Save</button><span id="note" class="small"></span></div>
  </section>

  <section class="card" id="problemsCard" hidden>
    <h2>Not loaded this session</h2>
    <div id="problems" class="err small"></div>
    <p class="muted small">The console has the details.</p>
  </section>

  <section class="card">
    <h2>Where the settings are kept</h2>
    <code id="path"></code>
  </section>
</div>
<script>
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (t) => String(t == null ? "" : t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const api = async (path, body) => {
    const res = await fetch("api/" + path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    return res.json();
  };
  function theme() {
    let dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    try {
      const doc = window.parent !== window ? window.parent.document : null;
      if (doc) dark = doc.body.classList.contains("dark") || doc.documentElement.classList.contains("dark") ||
        !!doc.querySelector("gradio-app.dark, .gradio-container.dark");
    } catch (_) { /* opened on its own */ }
    document.documentElement.dataset.theme = dark ? "dark" : "light";
  }
  async function load() {
    const st = await api("settings");
    $("refmods").checked = !!st.refmods; $("builder").checked = !!st.builder;
    $("path").textContent = st.path || "";
    $("problemsCard").hidden = !(st.problems || []).length;
    $("problems").innerHTML = (st.problems || []).map((p) => `<div>${esc(p)}</div>`).join("");
  }
  $("save").addEventListener("click", async () => {
    const r = await api("settings", { refmods: $("refmods").checked, builder: $("builder").checked });
    $("note").textContent = r.note || ""; $("note").className = "small " + (r.ok ? "ok" : "err");
  });
  // Full screen and, inside it, a switch to the other subtabs (WanGP's subtab bar is hidden there).
  function fullscreen() {
    const SVG = (d) => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${d}"/></svg>`;
    const EXPAND = SVG("M14 4h6v6M10 20H4v-6M20 4l-7 7M4 20l7-7"), EXIT = SVG("M10 4H5v16h5M14 8l4 4-4 4M18 12H9");
    let button = null, pdoc = null;
    try {
      const nav = window.parent !== window && window.frameElement && window.parent.WanGPAddonNavigation;
      if (!nav) return;
      const box = $("fsBox"), before = box.children.length;
      nav.headerButton(window.frameElement, box, "fsbtn");
      button = box.children.length > before ? box.lastElementChild : null;
      pdoc = window.parent.document;
    } catch (_) { return; }
    const paint = () => {
      const on = pdoc.documentElement.classList.contains("wangp-addon-fullscreen-open");
      document.documentElement.classList.toggle("rs-full", on);
      if (button) { button.title = on ? "Back to WanGP (Esc)" : "Open Full Screen"; button.innerHTML = on ? EXIT : EXPAND; }
      const tabs = [...pdoc.querySelectorAll(".rs-studio-tabs button[role=tab]")];
      $("subSwitch").innerHTML = tabs.map((t) => `<button data-sub="${esc(t.textContent.trim())}" class="${t.textContent.trim() === "Settings" ? "on" : ""}">${esc(t.textContent.trim())}</button>`).join("");
    };
    new MutationObserver(paint).observe(pdoc.documentElement, { attributes: true, attributeFilter: ["class"] });
    paint();
    $("subSwitch").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-sub]"); if (!b) return;
      const tab = [...pdoc.querySelectorAll(".rs-studio-tabs button[role=tab]")].find((t) => t.textContent.trim() === b.dataset.sub);
      if (tab) tab.click();
    });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && button && document.documentElement.classList.contains("rs-full")) button.click(); });
  }
  theme();
  try { new MutationObserver(theme).observe(window.parent.document.body, { attributes: true, attributeFilter: ["class"] }); } catch (_) { /* on its own */ }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { theme(); load(); } });
  fullscreen();
  load();
})();
</script>
</body>
</html>
"""


def create_app(host):
    app = FastAPI(title="Refmods Studio settings", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index():
        page = PAGE.replace("__VERSION__", html.escape(str(host.studio_settings().get("version", ""))))
        return HTMLResponse(page, headers={"Cache-Control": "no-cache"})

    @app.get("/api/settings")
    def settings():
        return host.studio_settings()

    @app.post("/api/settings")
    def save(payload: dict = Body(...)):
        return host.save_studio_settings(bool(payload.get("refmods", True)), bool(payload.get("builder", True)))

    return app
