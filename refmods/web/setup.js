/* Refmods Studio: the Setup page. Checks that the hooks are in place for the chosen model, and shows what
   Showrunner, Deepy and API tasks get when they bring no mods. */
(function () {
  "use strict";
  const RS = window.RS, $ = RS.$, esc = RS.esc, api = RS.api, act = RS.act;

  // The plugin writes a little Markdown (bold, italics, line breaks); show just that.
  const md = (t) => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\*(.+?)\*/g, "<i>$1</i>").replace(/`(.+?)`/g, "<code>$1</code>").replace(/ {2}\n|\n/g, "<br>");

  async function render() {
    const box = $("setup");
    box.innerHTML = `<div class="muted">Checking…</div>`;
    let d;
    try { d = await api("setup?model=" + RS.enc(RS.model())); } catch (e) { box.innerHTML = `<div class="err">${esc(e.message)}</div>`; return; }
    const m = RS.session.models || {};
    box.innerHTML = `
      <h3>This model</h3>
      <p class="explain">Checks that Refmods is hooked into the MiniMax H3 model picked at the top. Run it if mods seem to have no effect.</p>
      <ul class="checks">${(d.lines || []).map((l) => `<li>${md(l)}</li>`).join("")}</ul>
      <div class="row"><button id="sRecheck">Check again</button><button id="sModels">Refresh the model lists</button>
        <span class="muted small">${(m.h3 || []).length} MiniMax H3 and ${(m.flux || []).length} Flux model${(m.flux || []).length === 1 ? "" : "s"} found</span></div>

      <h3>Mods for Showrunner, Deepy and API tasks</h3>
      <p class="explain">They can't pick mods themselves, so a MiniMax H3 generation that arrives with none armed uses these. Set them in the <b>Refmods: MiniMax H3</b> panel on the Generator page: arm mods there and tick <i>Also use these for Showrunner, Deepy and API tasks</i>. Your own generations are never affected.</p>
      <div class="box">${md(d.autoarm || "")}</div>
      ${d.autoarm_on ? `<div class="row"><button id="sOff">Turn it off</button><span class="muted small">Keeps the mods, so ticking the box in the panel again brings them back.</span></div>` : ""}

      <h3>Where things are</h3>
      <div class="box">${(d.paths || []).map(([k, v]) => `<div><b>${esc(k)}</b>: <code>${esc(v)}</code></div>`).join("")}</div>
      ${(d.errors || []).map((e) => `<div class="err">${esc(e)}</div>`).join("")}`;
    $("sRecheck").addEventListener("click", render);
    $("sModels").addEventListener("click", async () => {
      RS.session = await api("session");
      const h3 = (RS.session.models.h3 || []).map(([l, t]) => [t, l]);
      const keep = RS.model();
      RS.options($("model"), h3.length ? h3 : [["", "No MiniMax H3 Ref2VA model found"]], h3.some(([t]) => t === keep) ? keep : RS.session.models.h3_default);
      render();
    });
    if ($("sOff")) $("sOff").addEventListener("click", () => act(api("autoarm_off", {}), render));
  }

  RS.views.setup = { show: render, model() { if (RS.current === "setup") render(); } };
})();
