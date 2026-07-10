"""flow_dashboard_web.py — a localhost WEB dashboard for the Vibe-IC flow.

Renders the Phase 1/2/3 (+ Analog A1-A9, Mixed-Signal M1-M4, Manufacturing
40-44) flow executing step-by-step: each step's status and WHERE its output is.
This module is the PRESENTATION half only; all the actual flow-state derivation
lives in the sibling provider `flow_dashboard_data.collect(project, full)`,
whose JSON shape is treated here as a fixed contract (see the module docstring
of flow_dashboard_data for the schema).

STDLIB ONLY. The page is fully self-contained: inline HTML/CSS/JS, no external
CDN, fonts, or frameworks. The browser polls GET /api/status every 2s and the
server recomputes collect() FRESH per request, so the page live-updates as the
runner produces outputs.

Usage:
    python3 flow_dashboard_web.py <project> [--port 8787] [--full] [--host 127.0.0.1]

Structure (for testability):
    build_page() -> str                     # pure: the full self-contained HTML
    status_json(project, full) -> bytes     # pure: collect() -> json bytes (never raises)
    make_handler(project, full)             # -> BaseHTTPRequestHandler subclass
    serve(project, port, full, host)        # runs the ThreadingHTTPServer
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# ---------------------------------------------------------------------------
# Pure data endpoint
# ---------------------------------------------------------------------------
# TTL cache — ONLY for full mode. Lightweight collect is a fast file-stat and
# is always recomputed (so a live build shows instantly). Full mode runs the
# whole flow_compliance gate matrix (~tens of seconds), so a 2s browser poll
# would pile up overlapping runs; we reuse the authoritative result for
# _FULL_TTL seconds. The result still refreshes on its own — just at a sane
# cadence, not every poll.
_FULL_TTL = 15.0
_status_cache: dict = {}  # (project, full) -> (monotonic_ts, bytes)


def status_json(project: str, full: bool) -> bytes:
    """Return collect(project, full) as JSON bytes.

    Never raises: on ANY failure (including collect not being importable yet
    because the sibling provider is still landing) it returns a JSON object
    carrying an ``error`` key so the UI can surface it — the caller always gets
    a 200-able body, never a 500 stacktrace to the browser.

    Full mode is TTL-cached (_FULL_TTL) so repeated fast polls don't re-run the
    authoritative gate matrix on every request.
    """
    import time as _time

    key = (str(project), bool(full))
    if full:
        hit = _status_cache.get(key)
        if hit is not None and (_time.monotonic() - hit[0]) < _FULL_TTL:
            return hit[1]
    try:
        from flow_dashboard_data import collect  # local import: fresh per call
    except Exception as exc:  # pragma: no cover - only when provider missing
        payload = {"error": f"flow_dashboard_data.collect unavailable: {exc}"}
        return json.dumps(payload).encode("utf-8")
    try:
        data = collect(project, full)
    except Exception as exc:
        payload = {"error": f"collect() failed: {exc}"}
        return json.dumps(payload).encode("utf-8")
    try:
        body = json.dumps(data, default=str).encode("utf-8")
    except Exception as exc:  # pragma: no cover - collect returns JSON-able dicts
        return json.dumps({"error": f"serialization failed: {exc}"}).encode("utf-8")
    if full:
        _status_cache[key] = (_time.monotonic(), body)
    return body


# ---------------------------------------------------------------------------
# The self-contained HTML page
# ---------------------------------------------------------------------------
_PAGE = r"""<!-- Vibe-IC flow dashboard — self-contained, theme-aware, auto-refreshing -->
<style>
:root{
  --bg:#f4f6fa; --panel:#ffffff; --panel2:#f0f3f8; --border:#dde3ec;
  --fg:#1c2430; --muted:#68748a; --track:#e3e8f0;
  --accent:#3d6bff; --accent-fg:#ffffff;
  --done:#1a9e57; --done-bg:#e3f6ec;
  --skipped:#0d9aa8; --skipped-bg:#def4f6;
  --waived:#c78a12; --waived-bg:#fbf1d8;
  --fail:#d8382f; --fail-bg:#fbe6e5;
  --running:#2f6bff; --running-bg:#e5edff;
  --partial:#9b51e0; --partial-bg:#f0e6fb;
  --na:#7c869a; --na-bg:#eceef2;
  --external:#9a7d55; --external-bg:#f4eede;
  --pending:#8a94a6; --pending-bg:#eceff4;
  --chip-bg:#eef1f7; --chip-fg:#38445a; --shadow:0 1px 3px rgba(20,30,50,.08);
}
@media (prefers-color-scheme: dark){
  :root{
    --bg:#0e1420; --panel:#161e2c; --panel2:#1b2536; --border:#28344a;
    --fg:#e6ecf5; --muted:#8a97ad; --track:#232f45;
    --accent:#5b82ff; --accent-fg:#ffffff;
    --done:#3ddb8a; --done-bg:#12321f;
    --skipped:#39d3e3; --skipped-bg:#0c2b30;
    --waived:#f0b843; --waived-bg:#332612;
    --fail:#ff6a5f; --fail-bg:#331715;
    --running:#6f9bff; --running-bg:#152645;
    --partial:#b989f2; --partial-bg:#2a1a3d;
    --na:#8b96ab; --na-bg:#1b2231;
    --external:#bb9a68; --external-bg:#2b2416;
    --pending:#9aa5ba; --pending-bg:#1c2536;
    --chip-bg:#1e2839; --chip-fg:#b7c2d6; --shadow:0 1px 3px rgba(0,0,0,.35);
  }
}
/* Manual toggle wins in BOTH directions. */
:root[data-theme="light"]{
  --bg:#f4f6fa; --panel:#ffffff; --panel2:#f0f3f8; --border:#dde3ec;
  --fg:#1c2430; --muted:#68748a; --track:#e3e8f0;
  --accent:#3d6bff; --accent-fg:#ffffff;
  --done:#1a9e57; --done-bg:#e3f6ec;
  --skipped:#0d9aa8; --skipped-bg:#def4f6;
  --waived:#c78a12; --waived-bg:#fbf1d8;
  --fail:#d8382f; --fail-bg:#fbe6e5;
  --running:#2f6bff; --running-bg:#e5edff;
  --partial:#9b51e0; --partial-bg:#f0e6fb;
  --na:#7c869a; --na-bg:#eceef2;
  --external:#9a7d55; --external-bg:#f4eede;
  --pending:#8a94a6; --pending-bg:#eceff4;
  --chip-bg:#eef1f7; --chip-fg:#38445a; --shadow:0 1px 3px rgba(20,30,50,.08);
}
:root[data-theme="dark"]{
  --bg:#0e1420; --panel:#161e2c; --panel2:#1b2536; --border:#28344a;
  --fg:#e6ecf5; --muted:#8a97ad; --track:#232f45;
  --accent:#5b82ff; --accent-fg:#ffffff;
  --done:#3ddb8a; --done-bg:#12321f;
  --skipped:#39d3e3; --skipped-bg:#0c2b30;
  --waived:#f0b843; --waived-bg:#332612;
  --fail:#ff6a5f; --fail-bg:#331715;
  --running:#6f9bff; --running-bg:#152645;
  --pending:#9aa5ba; --pending-bg:#1c2536;
  --chip-bg:#1e2839; --chip-fg:#b7c2d6; --shadow:0 1px 3px rgba(0,0,0,.35);
}
*{box-sizing:border-box}
html,body{margin:0;padding:0;overflow-x:hidden;max-width:100%}
body{
  background:var(--bg); color:var(--fg);
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,"PingFang TC","Microsoft JhengHei",sans-serif;
  font-size:14px; line-height:1.45;
}
a{color:var(--accent)}
.wrap{max-width:1720px; margin:0 auto; padding:1rem 1.1rem 2rem}

/* Header */
header.bar{
  position:sticky; top:0; z-index:20; background:var(--panel);
  border:1px solid var(--border); border-radius:14px; box-shadow:var(--shadow);
  padding:.85rem 1.1rem; margin-bottom:1.1rem;
}
.hrow{display:flex; align-items:center; gap:.7rem; flex-wrap:wrap}
.title{font-size:1.15rem; font-weight:700; letter-spacing:.2px}
.title .logo{opacity:.9}
.badge{
  font-size:.72rem; font-weight:700; text-transform:uppercase; letter-spacing:.5px;
  padding:.16rem .5rem; border-radius:999px; background:var(--chip-bg); color:var(--chip-fg);
  border:1px solid var(--border);
}
.spacer{flex:1 1 auto}
.updated{font-size:.74rem; color:var(--muted); white-space:nowrap}
.tbtn{
  cursor:pointer; border:1px solid var(--border); background:var(--panel2); color:var(--fg);
  border-radius:9px; padding:.32rem .6rem; font-size:.8rem; font-weight:600; line-height:1;
}
.tbtn:hover{border-color:var(--accent)}
.progline{display:flex; align-items:center; gap:.7rem; margin-top:.7rem; flex-wrap:wrap}
.progtxt{font-variant-numeric:tabular-nums; font-weight:700; font-size:.95rem; white-space:nowrap}
.bar-track{
  flex:1 1 240px; height:12px; background:var(--track);
  border-radius:999px; overflow:hidden; min-width:160px;
}
.bar-fill{height:100%; width:0%; background:var(--accent); border-radius:999px; transition:width .5s ease}
.chips{display:flex; gap:.4rem; flex-wrap:wrap; margin-top:.65rem}
.chip{
  display:inline-flex; align-items:center; gap:.35rem; font-size:.74rem; font-weight:700;
  padding:.2rem .55rem; border-radius:999px; border:1px solid var(--border); white-space:nowrap;
}
.chip .dot{width:.55rem; height:.55rem; border-radius:50%}
.chip .n{font-variant-numeric:tabular-nums}
.chip[data-k="done"]{background:var(--done-bg)} .chip[data-k="done"] .dot{background:var(--done)}
.chip[data-k="skipped"]{background:var(--skipped-bg)} .chip[data-k="skipped"] .dot{background:var(--skipped)}
.chip[data-k="waived"]{background:var(--waived-bg)} .chip[data-k="waived"] .dot{background:var(--waived)}
.chip[data-k="fail"]{background:var(--fail-bg)} .chip[data-k="fail"] .dot{background:var(--fail)}
.chip[data-k="missing"]{background:var(--fail-bg)} .chip[data-k="missing"] .dot{background:var(--fail)}
.chip[data-k="running"]{background:var(--running-bg)} .chip[data-k="running"] .dot{background:var(--running)}
.chip[data-k="partial"]{background:var(--partial-bg)} .chip[data-k="partial"] .dot{background:var(--partial)}
.chip[data-k="na"]{background:var(--na-bg)} .chip[data-k="na"] .dot{background:var(--na)}
.chip[data-k="external"]{background:var(--external-bg)} .chip[data-k="external"] .dot{background:var(--external)}
.chip[data-k="pending"]{background:var(--pending-bg)} .chip[data-k="pending"] .dot{background:var(--pending)}

.errbox{
  border:1px solid var(--fail); background:var(--fail-bg); color:var(--fail);
  border-radius:10px; padding:.7rem .9rem; margin-bottom:1rem; font-weight:600;
}

/* Phases laid out as side-by-side cards so the WHOLE 59-step flow fits on one
   screen. Each phase is a compact card; each step is a single dense line. */
main#phases{
  display:grid; gap:.8rem; align-items:start;
  grid-template-columns:repeat(auto-fill, minmax(300px, 1fr));
}
section.phase{
  background:var(--panel); border:1px solid var(--border); border-radius:12px;
  box-shadow:var(--shadow); padding:.6rem .65rem .7rem; break-inside:avoid;
}
.phead{display:flex; align-items:center; gap:.45rem; flex-wrap:wrap}
.picon{font-size:1.05rem; line-height:1}
.plabel{font-weight:700; font-size:.86rem}
.pcount{font-variant-numeric:tabular-nums; color:var(--muted); font-weight:700; font-size:.76rem}
.pmini{flex:1 1 70px; height:6px; background:var(--track); border-radius:999px; overflow:hidden; min-width:60px}
.pmini > i{display:block; height:100%; width:0%; background:var(--accent); border-radius:999px; transition:width .5s ease}

.steps{margin-top:.5rem; display:flex; flex-direction:column; gap:.18rem}
/* one dense line per step: colored status square + id + truncated name.
   Full name + status + output location live in the native hover tooltip. */
.step{
  display:flex; align-items:center; gap:.4rem; cursor:default;
  padding:.16rem .3rem; border-radius:6px; border-left:3px solid var(--pending);
  background:var(--panel2);
}
.step:hover{background:var(--chip-bg)}
.step[data-s="done"]{border-left-color:var(--done)}
.step[data-s="skipped"]{border-left-color:var(--skipped)}
.step[data-s="waived"]{border-left-color:var(--waived)}
.step[data-s="fail"]{border-left-color:var(--fail)}
.step[data-s="missing"]{border-left-color:var(--fail)}
.step[data-s="partial"]{border-left-color:var(--partial)}
.step[data-s="na"]{border-left-color:var(--na)}
.step[data-s="external"]{border-left-color:var(--external)}
.step[data-s="running"]{border-left-color:var(--running)}
.sq{width:.62rem; height:.62rem; border-radius:3px; flex:0 0 auto; background:var(--pending)}
.step[data-s="done"] .sq{background:var(--done)}
.step[data-s="skipped"] .sq{background:var(--skipped)}
.step[data-s="waived"] .sq{background:var(--waived)}
.step[data-s="fail"] .sq{background:var(--fail)}
.step[data-s="missing"] .sq{background:var(--fail)}
.step[data-s="partial"] .sq{background:var(--partial)}
.step[data-s="na"] .sq{background:var(--na)}
.step[data-s="external"] .sq{background:var(--external)}
.step[data-s="running"] .sq{background:var(--running); animation:pulse 1.1s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1} 50%{opacity:.35}}
.sid{font-variant-numeric:tabular-nums; font-weight:800; color:var(--muted);
  min-width:1.9rem; text-align:right; flex:0 0 auto; font-size:.72rem}
.sname{font-weight:600; font-size:.76rem; flex:1 1 auto; min-width:0;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
.sout{font-size:.64rem; color:var(--muted); flex:0 1 auto; min-width:0;
  max-width:8.5rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}

.foot{margin-top:1rem; text-align:center; color:var(--muted); font-size:.72rem}
.loading{color:var(--muted); padding:2rem 0; text-align:center}
</style>

<div class="wrap">
  <header class="bar">
    <div class="hrow">
      <span class="title"><span class="logo">🔬</span> <span id="pname">Vibe-IC Flow</span></span>
      <span class="badge" id="modebadge">…</span>
      <span class="badge" id="verbadge" hidden></span>
      <span class="spacer"></span>
      <span class="updated" id="updated">connecting…</span>
      <button class="tbtn" id="themebtn" title="Toggle light / dark" aria-label="Toggle theme">◐ Theme</button>
    </div>
    <div class="progline">
      <span class="progtxt" id="progtxt">0 / 0</span>
      <div class="bar-track"><div class="bar-fill" id="progfill"></div></div>
    </div>
    <div class="chips" id="chips"></div>
  </header>

  <div id="err" class="errbox" hidden></div>
  <main id="phases"><div class="loading">Loading flow status…</div></main>

  <div class="foot">Vibe-IC flow dashboard · whole flow on one page · hover any step for its outputs &amp; location · auto-refreshes every 2s</div>
</div>

<script>
"use strict";
(function(){
  // ---- theme: manual toggle persisted in localStorage; wins in both dirs ----
  var LS = "vibeic_flow_theme";
  var root = document.documentElement;
  try{
    var saved = localStorage.getItem(LS);
    if(saved === "light" || saved === "dark"){ root.setAttribute("data-theme", saved); }
  }catch(e){}
  function toggleTheme(){
    var cur = root.getAttribute("data-theme");
    if(!cur){
      // no explicit choice yet -> derive current effective, flip it
      var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      cur = dark ? "dark" : "light";
    }
    var next = (cur === "dark") ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try{ localStorage.setItem(LS, next); }catch(e){}
  }
  var tb = document.getElementById("themebtn");
  if(tb){ tb.addEventListener("click", toggleTheme); }

  // ---- helpers ----
  var STATUSES = ["done","skipped","waived","fail","missing","running","partial","na","external","pending"];
  var CHIP_ORDER = ["done","running","partial","pending","na","external","skipped","waived","fail","missing"];
  function fmtSize(n){
    if(n === null || n === undefined || isNaN(n)) return "";
    if(n < 1024) return n + " B";
    if(n < 1024*1024) return (n/1024).toFixed(n < 10240 ? 1 : 0) + " KB";
    if(n < 1024*1024*1024) return (n/1048576).toFixed(1) + " MB";
    return (n/1073741824).toFixed(1) + " GB";
  }
  function el(tag, cls){ var e = document.createElement(tag); if(cls) e.className = cls; return e; }
  function setText(e, t){ e.textContent = (t === null || t === undefined) ? "" : String(t); }

  // ---- render ----
  var lastServerTs = 0;      // seconds since epoch of last successful fetch
  function updateAgo(){
    var u = document.getElementById("updated");
    if(!lastServerTs){ return; }
    var secs = Math.max(0, Math.round(Date.now()/1000 - lastServerTs));
    u.textContent = "updated " + secs + "s ago";
  }

  function renderSummary(d){
    var s = d.summary || {};
    setText(document.getElementById("pname"), d.project_name || d.project || "Vibe-IC Flow");
    var mb = document.getElementById("modebadge");
    setText(mb, d.mode || "");
    var vb = document.getElementById("verbadge");
    if(d.flow_version){ setText(vb, "v" + d.flow_version); vb.hidden = false; }
    else { vb.hidden = true; }

    var total = s.total || 0;
    var done = s.done || 0;
    setText(document.getElementById("progtxt"), done + " / " + total);
    var pct = total ? Math.round(100*done/total) : 0;
    document.getElementById("progfill").style.width = pct + "%";

    var chips = document.getElementById("chips");
    chips.textContent = "";
    CHIP_ORDER.forEach(function(k){
      var n = s[k] || 0;
      if(!n) return;               // hide empty buckets to keep it 一目瞭然
      var c = el("span", "chip"); c.setAttribute("data-k", k);
      var dot = el("span","dot"); c.appendChild(dot);
      var lab = el("span"); setText(lab, k); c.appendChild(lab);
      var num = el("span","n"); setText(num, n); c.appendChild(num);
      chips.appendChild(c);
    });
  }

  // Full step detail (name, status, every output + where it lives, gate,
  // blocks_on) folded into the native hover tooltip so the on-screen line
  // stays a single dense row — the whole 59-step flow fits on one page.
  function stepTooltip(step){
    var L = [];
    L.push("#" + step.id + "  " + (step.name || ""));
    L.push("status: " + (step.status_label || step.status || "").toUpperCase());
    if(step.detail) L.push(step.detail);
    var outs = step.outputs || [];
    if(outs.length){
      L.push("outputs:");
      outs.forEach(function(o){
        var where = o.rel || o.abs || "(output)";
        var tail = o.exists
          ? ((o.size || o.size === 0) ? "  (" + fmtSize(o.size) + ")" : "")
          : "  (expected)";
        L.push("  " + (o.exists ? "✓" : "•") + " " + where + tail);
      });
    }
    if(step.gate) L.push("gate: " + step.gate);
    if(step.blocks_on && step.blocks_on.length)
      L.push("blocks_on: " + step.blocks_on.join(", "));
    return L.join("\n");
  }

  function renderStep(step){
    var st = (step.status || "pending").toLowerCase();
    if(STATUSES.indexOf(st) < 0) st = "pending";
    var box = el("div","step");
    box.setAttribute("data-s", st);
    box.title = stepTooltip(step);

    box.appendChild(el("span","sq"));
    var sid = el("span","sid"); setText(sid, step.id); box.appendChild(sid);
    var sname = el("span","sname"); setText(sname, step.name || ""); box.appendChild(sname);

    // compact "where's the output" hint: basename of the first EXISTING output.
    var outs = step.outputs || [];
    var firstEx = null;
    for(var i=0;i<outs.length;i++){ if(outs[i].exists){ firstEx = outs[i]; break; } }
    if(firstEx){
      var rel = firstEx.rel || firstEx.abs || "";
      var base = rel.split("/").pop();
      var so = el("span","sout"); setText(so, base); box.appendChild(so);
    }
    return box;
  }

  function renderPhase(ph){
    var sec = el("section","phase");
    var head = el("div","phead");
    var ic = el("span","picon"); setText(ic, ph.icon || "•"); head.appendChild(ic);
    var lab = el("span","plabel"); setText(lab, ph.label || ph.key || ""); head.appendChild(lab);
    var total = ph.total || (ph.steps ? ph.steps.length : 0);
    var done = ph.done || 0;
    var cnt = el("span","pcount"); setText(cnt, done + "/" + total); head.appendChild(cnt);
    var mini = el("div","pmini"); var fill = el("i");
    fill.style.width = (total ? Math.round(100*done/total) : 0) + "%";
    mini.appendChild(fill); head.appendChild(mini);
    sec.appendChild(head);

    var steps = el("div","steps");
    (ph.steps || []).forEach(function(s){ steps.appendChild(renderStep(s)); });
    sec.appendChild(steps);
    return sec;
  }

  function render(d){
    var errEl = document.getElementById("err");
    if(d.error){
      errEl.hidden = false;
      setText(errEl, "⚠ " + d.error);
      // keep last-good phases on screen; just surface the error banner
      return;
    }
    errEl.hidden = true;
    renderSummary(d);

    // preserve scroll position across full re-render
    var y = window.scrollY;
    var host = document.getElementById("phases");
    var frag = document.createDocumentFragment();
    (d.phases || []).forEach(function(ph){ frag.appendChild(renderPhase(ph)); });
    host.textContent = "";
    host.appendChild(frag);
    window.scrollTo(0, y);
  }

  // ---- poll loop ----
  var inflight = false;
  function tick(){
    if(inflight) return;
    inflight = true;
    fetch("/api/status", {cache:"no-store"}).then(function(r){ return r.json(); }).then(function(d){
      lastServerTs = Date.now()/1000;
      updateAgo();
      render(d);
    }).catch(function(e){
      var errEl = document.getElementById("err");
      errEl.hidden = false;
      setText(errEl, "⚠ fetch failed: " + e);
    }).finally(function(){ inflight = false; });
  }
  tick();
  setInterval(tick, 2000);
  setInterval(updateAgo, 1000);
})();
</script>
"""


_HEAD = (
    "<!doctype html>\n"
    '<html lang="en">\n'
    "<head>\n"
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    "<title>Vibe-IC Flow Dashboard</title>\n"
    # A self-contained emoji favicon (data URI) — no external asset.
    '<link rel="icon" '
    'href="data:image/svg+xml,'
    "%3Csvg%20xmlns='http%3A//www.w3.org/2000/svg'%20viewBox='0%200%20100%20100'"
    "%3E%3Ctext%20y='.9em'%20font-size='90'%3E%F0%9F%94%AC%3C/text%3E%3C/svg%3E\">\n"
    "</head>\n"
    "<body>\n"
)
_TAIL = "\n</body>\n</html>\n"


def build_page() -> str:
    """Return the full self-contained HTML document (pure)."""
    return _HEAD + _PAGE + _TAIL


# ---------------------------------------------------------------------------
# HTTP handler + server
# ---------------------------------------------------------------------------
def make_handler(project: str, full: bool):
    """Return a BaseHTTPRequestHandler subclass bound to (project, full)."""
    page_bytes = build_page().encode("utf-8")

    class _Handler(BaseHTTPRequestHandler):
        server_version = "VibeICFlowDash/1.0"
        protocol_version = "HTTP/1.1"

        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.end_headers()
            if body:
                self.wfile.write(body)

        def do_GET(self):  # noqa: N802 (stdlib naming)
            path = self.path.split("?", 1)[0]
            if path == "/" or path == "/index.html":
                self._send(200, page_bytes, "text/html; charset=utf-8")
                return
            if path == "/api/status":
                body = status_json(project, full)
                self._send(200, body, "application/json; charset=utf-8")
                return
            if path == "/favicon.ico":
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._send(404, b"not found", "text/plain; charset=utf-8")

        def log_message(self, fmt, *args):  # quiet the default per-request stderr spam
            return

    return _Handler


def serve(project: str, port: int = 8787, full: bool = False, host: str = "127.0.0.1") -> None:
    """Run the ThreadingHTTPServer on host:port until Ctrl-C."""
    project = os.path.abspath(project)
    name = os.path.basename(project.rstrip("/")) or project
    mode = "full" if full else "lightweight"
    handler = make_handler(project, full)
    httpd = ThreadingHTTPServer((host, port), handler)
    # Show 127.0.0.1 in the clickable line even when bound to 0.0.0.0.
    shown = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    print(
        "Vibe-IC flow dashboard → http://%s:%d  (project: %s, mode: %s)  Ctrl-C to stop"
        % (shown, port, name, mode),
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard…", flush=True)
    finally:
        httpd.shutdown()
        httpd.server_close()


def _parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="flow_dashboard_web.py",
        description="Localhost web dashboard for the Vibe-IC Phase 1/2/3 (+Analog/Mixed/Mfg) flow.",
    )
    p.add_argument("project", help="path to the project directory")
    p.add_argument("--port", type=int, default=8787, help="port to serve on (default 8787)")
    p.add_argument("--full", action="store_true", help="use the full (not lightweight) collect")
    p.add_argument("--host", default="127.0.0.1", help="host/interface to bind (default 127.0.0.1)")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    serve(args.project, port=args.port, full=args.full, host=args.host)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
