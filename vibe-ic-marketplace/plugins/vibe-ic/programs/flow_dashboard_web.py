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
import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

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


# Per-IC on-demand full result, pinned until that IC's tree changes. Keyed by
# resolved project path -> (fingerprint_tuple, full_card_dict, full_detail_dict).
# Populated ONLY by the "Run full" button (card_json); read by fleet_json (card)
# AND the drill-down /api/status (detail) so BOTH views stay consistent without
# re-running the gate matrix.
_CARD_FULL_CACHE: dict = {}


def _fp_key(fp):
    """Normalize a card fingerprint (list-of-lists over the wire) to a hashable
    tuple for stable equality across JSON round-trips."""
    try:
        paths, statuses = fp
        return (tuple(paths), tuple(tuple(s) for s in statuses))
    except Exception:
        return None


def fleet_json(root: str, full: bool) -> bytes:
    """Return collect_fleet([], full, root=<root>) as JSON bytes, with any IC
    the user has pinned via "Run full" swapped in from _CARD_FULL_CACHE (while
    that IC's tree is unchanged).

    Same safety contract as status_json(): never raises, always returns a
    200-able JSON body (an ``error`` key on failure). Cards are LIGHTWEIGHT by
    default so the page loads instantly.
    """
    try:
        from flow_dashboard_data import collect_fleet  # local import: fresh per call
    except Exception as exc:  # pragma: no cover - only when provider missing
        payload = {"error": f"flow_dashboard_data.collect_fleet unavailable: {exc}"}
        return json.dumps(payload).encode("utf-8")
    try:
        data = collect_fleet([], full=full, root=root)
    except Exception as exc:  # pragma: no cover - collect_fleet is contractually safe
        payload = {"error": f"collect_fleet() failed: {exc}"}
        return json.dumps(payload).encode("utf-8")
    # Pin any card the user ran full for, as long as its (lightweight)
    # fingerprint still matches — otherwise the build moved and the card falls
    # back to lightweight + button (inviting a fresh full run).
    if not full and _CARD_FULL_CACHE:
        for i, card in enumerate(data.get("fleet", [])):
            pinned = _CARD_FULL_CACHE.get(card.get("project"))
            if pinned is not None and pinned[0] == _fp_key(card.get("fingerprint")):
                data["fleet"][i] = pinned[1]
    try:
        return json.dumps(data, default=str).encode("utf-8")
    except Exception as exc:  # pragma: no cover
        return json.dumps({"error": f"serialization failed: {exc}"}).encode("utf-8")


def card_json(root: str, project: str) -> bytes:
    """Run the AUTHORITATIVE full collect for ONE fleet IC (the "Run full"
    button) and pin BOTH its compact card AND its full detail in
    _CARD_FULL_CACHE (so the fleet card and the drill-down page agree). Returns
    the full card JSON. The caller must already have validated *project* against
    the fleet set. Never raises."""
    try:
        from flow_dashboard_data import collect_card_and_detail  # local import
    except Exception as exc:  # pragma: no cover - only when provider missing
        return json.dumps({"error": f"provider unavailable: {exc}"}).encode("utf-8")
    try:
        card, detail, _fp = collect_card_and_detail(project, full=True)
    except Exception as exc:  # pragma: no cover - contractually safe
        return json.dumps({"error": f"collect_card() failed: {exc}"}).encode("utf-8")
    # Pin only if genuinely authoritative (full ran, no silent fallback).
    if card.get("full") and card.get("fingerprint") is not None:
        _CARD_FULL_CACHE[card.get("project")] = (
            _fp_key(card.get("fingerprint")), card, detail)
    try:
        return json.dumps(card, default=str).encode("utf-8")
    except Exception as exc:  # pragma: no cover
        return json.dumps({"error": f"serialization failed: {exc}"}).encode("utf-8")


def detail_status_json(project: str) -> bytes:
    """Drill-down /api/status for a fleet IC: if the user ran full for it and the
    tree is unchanged, serve the PINNED full detail (so the page matches the
    card); otherwise the fast lightweight status. Never raises."""
    pinned = _CARD_FULL_CACHE.get(str(project))
    if pinned is not None and len(pinned) == 3:
        try:
            from flow_dashboard_data import collect, _fingerprint_from
            light = collect(project, False)
            if pinned[0] == _fp_key(_fingerprint_from(light)):
                return json.dumps(pinned[2], default=str).encode("utf-8")
        except Exception:  # pragma: no cover - fall through to lightweight
            pass
    return status_json(project, False)


def _is_allowed_project(root: str, project: str) -> bool:
    """True iff *project* is one of the fleet children discovered under *root*.

    Guards the fleet server's per-IC drill-down (/ic?project=…, /api/status?
    project=…): a browser can only open a project that actually belongs to this
    fleet, never an arbitrary filesystem path. realpath-compared so symlinks /
    trailing slashes cannot slip past. Never raises."""
    if not project:
        return False
    try:
        from flow_dashboard_data import discover_projects
    except Exception:  # pragma: no cover - only when provider missing
        return False
    try:
        allowed = {os.path.realpath(p) for p in discover_projects(root)}
        return os.path.realpath(os.path.expanduser(project)) in allowed
    except Exception:  # pragma: no cover - defensive
        return False


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
.chip[data-k="pass"]{background:var(--done-bg)} .chip[data-k="pass"] .dot{background:var(--done)}
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
.step[data-s="pass"]{border-left-color:var(--done)}
.step[data-s="skipped"]{border-left-color:var(--skipped)}
.step[data-s="waived"]{border-left-color:var(--waived)}
.step[data-s="fail"]{border-left-color:var(--fail)}
.step[data-s="missing"]{border-left-color:var(--fail)}
.step[data-s="partial"]{border-left-color:var(--partial)}
.step[data-s="na"]{border-left-color:var(--na)}
.step[data-s="external"]{border-left-color:var(--external)}
.step[data-s="running"]{border-left-color:var(--running)}
.sq{width:.62rem; height:.62rem; border-radius:3px; flex:0 0 auto; background:var(--pending)}
.step[data-s="pass"] .sq{background:var(--done)}
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
      <span class="badge" id="modebadge" hidden></span>
      <span class="badge" id="verbadge" hidden></span>
      <a class="tbtn" id="fleetlink" href="/" title="Back to the fleet overview" hidden>← Fleet</a>
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

  <div class="foot">Vibe-IC flow dashboard · whole flow on one page · Done = reached &amp; judged (pass/fail/skip/n-a/external) · hover any step for its outputs · auto-refresh 2s live / 30s idle</div>
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
  var STATUSES = ["pass","skipped","waived","fail","missing","running","partial","na","external","pending"];
  var CHIP_ORDER = ["pass","running","partial","pending","na","external","skipped","waived","fail","missing"];
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
  var pollMs = 2000;         // current adaptive poll cadence
  function updateAgo(){
    var u = document.getElementById("updated");
    if(!lastServerTs){ return; }
    var secs = Math.max(0, Math.round(Date.now()/1000 - lastServerTs));
    var cadence = pollMs >= 30000 ? "idle · 30s poll" : "live · 2s poll";
    u.textContent = "updated " + secs + "s ago · " + cadence;
  }

  function renderSummary(d){
    var s = d.summary || {};
    setText(document.getElementById("pname"), d.project_name || d.project || "Vibe-IC Flow");
    var mb = document.getElementById("modebadge");
    // Only surface the AUTHORITATIVE mode; a plain lightweight view shows no
    // "lightweight" label (it is the default, unremarkable state).
    if(String(d.mode || "").indexOf("full") >= 0){ setText(mb, "full"); mb.hidden = false; }
    else { mb.hidden = true; }
    var vb = document.getElementById("verbadge");
    // Show the shipped vibe-ic PLUGIN version (what the user runs), not the
    // internal flow-schema version. Fall back to flow_version only if absent.
    if(d.plugin_version){ setText(vb, "vibe-ic v" + d.plugin_version); vb.hidden = false; }
    else if(d.flow_version){ setText(vb, "flow v" + d.flow_version); vb.hidden = false; }
    else { vb.hidden = true; }

    var total = s.total || 0;
    // DONE = reached & judged (any verdict) = resolved, NOT just the PASS subset.
    var done = (s.resolved != null ? s.resolved : (s.done || 0));
    setText(document.getElementById("progtxt"), "Done " + done + " / " + total);
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
      // 📂 open this step's output subfolder (steps/<id>_<slug>/)
      var pq = new URLSearchParams(location.search).get("project");
      var a = el("a","sfolder");
      a.href = "/step?id=" + encodeURIComponent(step.id)
             + (pq ? "&project=" + encodeURIComponent(pq) : "");
      a.target = "_blank";
      a.title = "open this step's output folder (steps/" + step.id + "_…/)";
      a.style.marginLeft = "6px";
      a.style.textDecoration = "none";
      a.style.cursor = "pointer";
      setText(a, "📂");
      a.addEventListener("click", function(e){ e.stopPropagation(); });
      box.appendChild(a);
    }
    return box;
  }

  function renderPhase(ph){
    var sec = el("section","phase");
    var head = el("div","phead");
    var ic = el("span","picon"); setText(ic, ph.icon || "•"); head.appendChild(ic);
    var lab = el("span","plabel"); setText(lab, ph.label || ph.key || ""); head.appendChild(lab);
    var total = ph.total || (ph.steps ? ph.steps.length : 0);
    var done = (ph.resolved != null ? ph.resolved : (ph.done || 0));
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

  // ---- adaptive poll loop ----
  // Fast (2s) while ANY step is RUNNING so a live build ticks in real time;
  // back off to 30s when the flow is quiescent/finished so a completed
  // dashboard does not hammer the server (and the "updated Ns ago" counter
  // reflects the real cadence).
  var inflight = false;
  var FAST_MS = 2000, IDLE_MS = 30000;
  var pollTimer = null;
  function scheduleNext(ms){
    if(pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(tick, ms);
  }
  // When this page is opened from the fleet (/ic?project=…) the project rides
  // in the query string; forward it to the status endpoint and reveal the
  // "← Fleet" back link. In stand-alone single-IC mode the search is empty and
  // the server serves its fixed project, so this is a harmless no-op.
  var SEARCH = window.location.search || "";
  (function(){
    try{
      if(new URLSearchParams(SEARCH).get("project")){
        var fl = document.getElementById("fleetlink");
        if(fl) fl.hidden = false;
      }
    }catch(e){}
  })();

  function tick(){
    if(inflight){ scheduleNext(FAST_MS); return; }
    inflight = true;
    fetch("/api/status" + SEARCH, {cache:"no-store"}).then(function(r){ return r.json(); }).then(function(d){
      lastServerTs = Date.now()/1000;
      render(d);
      var running = (d.summary && d.summary.running) || 0;
      pollMs = running > 0 ? FAST_MS : IDLE_MS;
      updateAgo();
      scheduleNext(pollMs);
    }).catch(function(e){
      var errEl = document.getElementById("err");
      errEl.hidden = false;
      setText(errEl, "⚠ fetch failed: " + e);
      scheduleNext(FAST_MS);
    }).finally(function(){ inflight = false; });
  }
  tick();
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
# FLEET page — many ICs at a glance (multi-IC / multi-subagent overview)
# ---------------------------------------------------------------------------
# Self-contained, theme-aware, one card per IC. The status colour palette is
# the SAME CSS-variable set as the single-IC page (kept in sync deliberately);
# a fleet card is a compact roll-up (summary chips + per-phase mini bars +
# running-step line), NOT the full 59-step grid — that lives on the single-IC
# dashboard for a chosen project.
_FLEET_PAGE = r"""<!-- Vibe-IC FLEET dashboard — self-contained, theme-aware, auto-refreshing -->
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
  --partial:#b989f2; --partial-bg:#2a1a3d;
  --na:#8b96ab; --na-bg:#1b2231;
  --external:#bb9a68; --external-bg:#2b2416;
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
.bar-track{flex:1 1 240px; height:12px; background:var(--track); border-radius:999px; overflow:hidden; min-width:160px}
.bar-fill{height:100%; width:0%; background:var(--accent); border-radius:999px; transition:width .5s ease}
.chips{display:flex; gap:.4rem; flex-wrap:wrap; margin-top:.65rem}
.chip{display:inline-flex; align-items:center; gap:.35rem; font-size:.74rem; font-weight:700;
  padding:.2rem .55rem; border-radius:999px; border:1px solid var(--border); white-space:nowrap}
.chip .dot{width:.55rem; height:.55rem; border-radius:50%}
.chip .n{font-variant-numeric:tabular-nums}
.chip[data-k="pass"]{background:var(--done-bg)} .chip[data-k="pass"] .dot{background:var(--done)}
.chip[data-k="skipped"]{background:var(--skipped-bg)} .chip[data-k="skipped"] .dot{background:var(--skipped)}
.chip[data-k="waived"]{background:var(--waived-bg)} .chip[data-k="waived"] .dot{background:var(--waived)}
.chip[data-k="fail"]{background:var(--fail-bg)} .chip[data-k="fail"] .dot{background:var(--fail)}
.chip[data-k="missing"]{background:var(--fail-bg)} .chip[data-k="missing"] .dot{background:var(--fail)}
.chip[data-k="running"]{background:var(--running-bg)} .chip[data-k="running"] .dot{background:var(--running)}
.chip[data-k="partial"]{background:var(--partial-bg)} .chip[data-k="partial"] .dot{background:var(--partial)}
.chip[data-k="na"]{background:var(--na-bg)} .chip[data-k="na"] .dot{background:var(--na)}
.chip[data-k="external"]{background:var(--external-bg)} .chip[data-k="external"] .dot{background:var(--external)}
.chip[data-k="pending"]{background:var(--pending-bg)} .chip[data-k="pending"] .dot{background:var(--pending)}
.errbox{border:1px solid var(--fail); background:var(--fail-bg); color:var(--fail);
  border-radius:10px; padding:.7rem .9rem; margin-bottom:1rem; font-weight:600}

/* One card per IC; the whole fleet fits on one page. Each card is a LINK to
   that IC's full 59-step page (/ic?project=…). */
main#fleet{display:grid; gap:.8rem; align-items:start;
  grid-template-columns:repeat(auto-fill, minmax(340px, 1fr))}
.ic{display:block; text-decoration:none; color:inherit; cursor:pointer;
  background:var(--panel); border:1px solid var(--border); border-radius:12px;
  box-shadow:var(--shadow); padding:.7rem .8rem .75rem; break-inside:avoid;
  border-left:4px solid var(--pending); transition:border-color .15s ease, transform .1s ease}
.ic:hover{border-color:var(--accent)}
.ic:active{transform:translateY(1px)}
.ic[data-run="1"]{border-left-color:var(--running)}
.ic[data-done="1"]{border-left-color:var(--done)}
.ic .opencue{font-size:.7rem; color:var(--accent); white-space:nowrap; opacity:0; transition:opacity .15s ease}
.ic:hover .opencue{opacity:1}
.ichead{display:flex; align-items:center; gap:.5rem; flex-wrap:wrap}
.icname{font-weight:800; font-size:.95rem; flex:1 1 auto; min-width:0;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis}
.icrun{display:inline-flex; align-items:center; gap:.3rem; font-size:.72rem; font-weight:700;
  color:var(--running); background:var(--running-bg); border:1px solid var(--border);
  padding:.1rem .45rem; border-radius:999px}
.icrun .rdot{width:.5rem; height:.5rem; border-radius:50%; background:var(--running);
  animation:pulse 1.1s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1} 50%{opacity:.3}}
.icprog{display:flex; align-items:center; gap:.55rem; margin-top:.55rem}
.icprog .t{font-variant-numeric:tabular-nums; font-weight:700; font-size:.8rem; white-space:nowrap}
.icbar{flex:1 1 auto; height:9px; background:var(--track); border-radius:999px; overflow:hidden; min-width:80px}
.icbar > i{display:block; height:100%; width:0%; background:var(--accent); border-radius:999px; transition:width .5s ease}
.icchips{display:flex; gap:.3rem; flex-wrap:wrap; margin-top:.5rem}
.icchips .chip{font-size:.68rem; padding:.12rem .42rem}
/* per-phase mini bars: 6 tiny segments, icon-labelled, so you see WHERE each IC is */
.phmini{display:flex; gap:.3rem; margin-top:.55rem; flex-wrap:wrap}
.phseg{display:flex; align-items:center; gap:.25rem; font-size:.66rem; color:var(--muted)}
.phseg .pi{font-size:.8rem; line-height:1}
.phseg .pb{width:34px; height:5px; background:var(--track); border-radius:999px; overflow:hidden}
.phseg .pb > i{display:block; height:100%; width:0%; background:var(--accent); border-radius:999px}
.phseg .pn{font-variant-numeric:tabular-nums}
.icsteps{margin-top:.5rem; font-size:.72rem; color:var(--running); display:flex; align-items:flex-start; gap:.35rem}
.icsteps .m{flex:0 0 auto} .icsteps .s{min-width:0}
/* per-IC "Run full" trigger + authoritative / busy indicators */
.ic .runbtn{cursor:pointer; border:1px solid var(--accent); background:var(--accent); color:var(--accent-fg);
  border-radius:8px; padding:.16rem .5rem; font-size:.68rem; font-weight:800; line-height:1.25; white-space:nowrap}
.ic .runbtn:hover{filter:brightness(1.08)}
.ic .fulltag{font-size:.66rem; font-weight:800; color:var(--done); background:var(--done-bg);
  border:1px solid var(--border); border-radius:999px; padding:.1rem .48rem; white-space:nowrap}
.ic .busytag{display:inline-flex; align-items:center; gap:.32rem; font-size:.68rem; font-weight:700; color:var(--running);
  background:var(--running-bg); border:1px solid var(--border); border-radius:999px; padding:.1rem .48rem; white-space:nowrap}
.ic .busytag .rdot{width:.5rem; height:.5rem; border-radius:50%; background:var(--running); animation:pulse 1.1s ease-in-out infinite}
.ic.busy{opacity:.9}
.foot{margin-top:1rem; text-align:center; color:var(--muted); font-size:.72rem}
.loading{color:var(--muted); padding:2rem 0; text-align:center}
</style>

<div class="wrap">
  <header class="bar">
    <div class="hrow">
      <span class="title"><span class="logo">🔬</span> Vibe-IC Fleet</span>
      <span class="badge" id="cntbadge">…</span>
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
  <main id="fleet"><div class="loading">Loading fleet status…</div></main>

  <div class="foot">Vibe-IC fleet · loads instantly · <b>Run full</b> on any card for authoritative gate verdicts · click a card → its full 59-step view · Done = reached &amp; judged (pass/fail/skip/n-a/external)</div>
</div>

<script>
"use strict";
(function(){
  var LS = "vibeic_flow_theme";
  var root = document.documentElement;
  try{
    var saved = localStorage.getItem(LS);
    if(saved === "light" || saved === "dark"){ root.setAttribute("data-theme", saved); }
  }catch(e){}
  function toggleTheme(){
    var cur = root.getAttribute("data-theme");
    if(!cur){
      var dark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
      cur = dark ? "dark" : "light";
    }
    var next = (cur === "dark") ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try{ localStorage.setItem(LS, next); }catch(e){}
  }
  var tb = document.getElementById("themebtn");
  if(tb){ tb.addEventListener("click", toggleTheme); }

  var CHIP_ORDER = ["pass","running","partial","pending","na","external","skipped","waived","fail","missing"];
  function el(tag, cls){ var e = document.createElement(tag); if(cls) e.className = cls; return e; }
  function setText(e, t){ e.textContent = (t === null || t === undefined) ? "" : String(t); }
  function num(v){ return (v === null || v === undefined || isNaN(v)) ? 0 : v; }
  function resolvedOf(s){ return (s && s.resolved != null) ? s.resolved : ((s && s.done) || 0); }

  var lastServerTs = 0;
  var pollMs = 2000;
  var lastData = null;                 // last fleet dict, for re-render on button
  var pendingFull = new Set();         // projects whose full run is in flight
  function updateAgo(){
    var u = document.getElementById("updated");
    if(!lastServerTs){ return; }
    var secs = Math.max(0, Math.round(Date.now()/1000 - lastServerTs));
    var cadence = pollMs >= 30000 ? "idle · 30s poll" : "live · 2s poll";
    u.textContent = "updated " + secs + "s ago · " + cadence;
  }

  // Per-IC "Run full": kick the authoritative gate run for ONE IC. The card
  // shows a "running full…" spinner meanwhile; the server pins the result so
  // the next poll shows it authoritative (button gone).
  function runFull(project){
    if(!project || pendingFull.has(project)) return;
    pendingFull.add(project);
    if(lastData) render(lastData);     // flip that card to busy immediately
    fetch("/api/card?project=" + encodeURIComponent(project), {cache:"no-store"})
      .then(function(r){ return r.json(); })
      .then(function(card){
        pendingFull.delete(project);
        if(card && card.error){
          var errEl = document.getElementById("err");
          errEl.hidden = false; setText(errEl, "⚠ Run full: " + card.error);
        }
        tick();                        // refresh now — server has pinned it full
      })
      .catch(function(e){
        pendingFull.delete(project);
        var errEl = document.getElementById("err");
        errEl.hidden = false; setText(errEl, "⚠ Run full failed: " + e);
        if(lastData) render(lastData);
      });
  }

  function chip(k, n){
    var c = el("span","chip"); c.setAttribute("data-k", k);
    c.appendChild(el("span","dot"));
    var lab = el("span"); setText(lab, k); c.appendChild(lab);
    var nn = el("span","n"); setText(nn, n); c.appendChild(nn);
    return c;
  }

  function renderAgg(d){
    var a = d.agg || {};
    var cnt = num(a.ic_count), run = num(a.ic_running), done = num(a.ic_done);
    setText(document.getElementById("cntbadge"),
      cnt + " IC" + (cnt===1?"":"s") + " · " + run + " running · " + done + " done");
    var vb = document.getElementById("verbadge");
    if(d.plugin_version){ setText(vb, "vibe-ic v" + d.plugin_version); vb.hidden = false; }
    else { vb.hidden = true; }

    var total = num(a.total), rdone = num(a.resolved);
    setText(document.getElementById("progtxt"), "Done " + rdone + " / " + total + " steps");
    document.getElementById("progfill").style.width = (total ? Math.round(100*rdone/total) : 0) + "%";

    var chips = document.getElementById("chips");
    chips.textContent = "";
    CHIP_ORDER.forEach(function(k){ var n = num(a[k]); if(n) chips.appendChild(chip(k, n)); });
  }

  function cardNav(c){ return "/ic?project=" + encodeURIComponent(c.project || ""); }

  function renderCard(c){
    var s = c.summary || {};
    var total = num(s.total), done = resolvedOf(s), running = num(s.running);
    var busy = pendingFull.has(c.project);
    // The card is a container; clicking it (except the Run-full button) opens
    // that IC's full 59-step page.
    var sec = el("section", busy ? "ic busy" : "ic");
    if(running > 0) sec.setAttribute("data-run","1");
    else if(total && done >= total) sec.setAttribute("data-done","1");
    sec.addEventListener("click", function(){ window.location = cardNav(c); });

    var head = el("div","ichead");
    var nm = el("span","icname"); setText(nm, c.project_name || c.project || "(ic)"); head.appendChild(nm);
    var cue = el("span","opencue"); setText(cue, "open 59 steps →"); head.appendChild(cue);
    if(running > 0){
      var r = el("span","icrun"); r.appendChild(el("span","rdot"));
      var rt = el("span"); setText(rt, running + " running"); r.appendChild(rt); head.appendChild(r);
    }
    // authoritative indicator (ran full) · busy (running full now) · or the
    // per-IC "Run full" trigger. NOTE: a plain lightweight card shows NO mode
    // text — just the button.
    if(busy){
      var bt = el("span","busytag"); bt.appendChild(el("span","rdot"));
      var btx = el("span"); setText(btx, "running full…"); bt.appendChild(btx); head.appendChild(bt);
    } else if(c.full){
      var ft = el("span","fulltag"); setText(ft, "✓ full"); head.appendChild(ft);
    } else if(!c.error){
      var rb = el("button","runbtn"); setText(rb, "Run full");
      rb.title = "Run the authoritative gate verdicts for this IC (~seconds)";
      rb.addEventListener("click", function(ev){
        ev.stopPropagation(); ev.preventDefault(); runFull(c.project);
      });
      head.appendChild(rb);
    }
    sec.appendChild(head);

    if(c.error){
      var eb = el("div","icsteps"); eb.style.color = "var(--fail)";
      setText(eb, "⚠ " + c.error); sec.appendChild(eb); return sec;
    }

    var prog = el("div","icprog");
    var pt = el("span","t"); setText(pt, "Done " + done + "/" + total); prog.appendChild(pt);
    var bar = el("div","icbar"); var fill = el("i");
    fill.style.width = (total ? Math.round(100*done/total) : 0) + "%";
    bar.appendChild(fill); prog.appendChild(bar);
    sec.appendChild(prog);

    var chips = el("div","icchips");
    CHIP_ORDER.forEach(function(k){ var n = num(s[k]); if(n) chips.appendChild(chip(k, n)); });
    sec.appendChild(chips);

    var pm = el("div","phmini");
    (c.phases_mini || []).forEach(function(ph){
      var seg = el("span","phseg");
      var pi = el("span","pi"); setText(pi, ph.icon || "•"); seg.appendChild(pi);
      var pb = el("span","pb"); var pf = el("i");
      var pt2 = num(ph.total), pr = num(ph.resolved);
      pf.style.width = (pt2 ? Math.round(100*pr/pt2) : 0) + "%";
      pb.appendChild(pf); seg.appendChild(pb);
      var pn = el("span","pn"); setText(pn, pr + "/" + pt2); seg.appendChild(pn);
      seg.title = (ph.label || ph.key || "") + ": " + pr + "/" + pt2;
      pm.appendChild(seg);
    });
    sec.appendChild(pm);

    var rs = c.running_steps || [];
    if(rs.length){
      var line = el("div","icsteps");
      var mk = el("span","m"); setText(mk, "▸"); line.appendChild(mk);
      var names = rs.slice(0,3).map(function(x){ return "#" + x.id + " " + (x.name||""); }).join(", ");
      if(rs.length > 3) names += " +" + (rs.length - 3);
      var sp = el("span","s"); setText(sp, names); line.appendChild(sp);
      sec.appendChild(line);
    }
    return sec;
  }

  function render(d){
    var errEl = document.getElementById("err");
    if(d.error){ errEl.hidden = false; setText(errEl, "⚠ " + d.error); return; }
    errEl.hidden = true;
    renderAgg(d);
    var y = window.scrollY;
    var host = document.getElementById("fleet");
    var frag = document.createDocumentFragment();
    var fleet = d.fleet || [];
    if(!fleet.length){
      var empty = el("div","loading");
      setText(empty, "No Vibe-IC projects found under this directory.");
      frag.appendChild(empty);
    } else {
      fleet.forEach(function(c){ frag.appendChild(renderCard(c)); });
    }
    host.textContent = "";
    host.appendChild(frag);
    window.scrollTo(0, y);
  }

  var inflight = false;
  var FAST_MS = 2000, IDLE_MS = 30000;
  var pollTimer = null;
  function scheduleNext(ms){ if(pollTimer) clearTimeout(pollTimer); pollTimer = setTimeout(tick, ms); }
  function tick(){
    if(inflight){ scheduleNext(FAST_MS); return; }
    inflight = true;
    fetch("/api/fleet", {cache:"no-store"}).then(function(r){ return r.json(); }).then(function(d){
      lastServerTs = Date.now()/1000;
      lastData = d;
      render(d);
      var running = (d.agg && d.agg.ic_running) || 0;
      pollMs = running > 0 ? FAST_MS : IDLE_MS;
      updateAgo();
      scheduleNext(pollMs);
    }).catch(function(e){
      var errEl = document.getElementById("err");
      errEl.hidden = false; setText(errEl, "⚠ fetch failed: " + e);
      scheduleNext(FAST_MS);
    }).finally(function(){ inflight = false; });
  }
  tick();
  setInterval(updateAgo, 1000);
})();
</script>
"""


def build_fleet_page() -> str:
    """Return the full self-contained FLEET HTML document (pure)."""
    return _HEAD + _FLEET_PAGE + _TAIL


# ---------------------------------------------------------------------------
# Per-step output subfolder browsing (the "📂 open" link on every step)
# ---------------------------------------------------------------------------
# The canonical phaseN/… tree stays authoritative; step_output_collector
# materializes <project>/steps/<id>_<slug>/ as SYMLINK views. These routes
# list + serve those folders read-only, guarded against path traversal.
_STEP_TEXT_SUFFIXES = {
    ".v", ".sv", ".vh", ".json", ".rpt", ".log", ".md", ".txt", ".tcl", ".sdc",
    ".def", ".spef", ".lef", ".lib", ".cfg", ".yaml", ".yml", ".sva", ".sdf",
    ".map", ".sp", ".cir", ".flag", ".done", ".csv", ".xml",
}
_STEP_FILE_MAX_INLINE = 5 * 1024 * 1024   # >5 MB → force download, never inline


def _steps_root(project: str) -> Path:
    return Path(project).expanduser().resolve() / "steps"


def _ensure_steps(project: str) -> dict:
    """Materialize the per-step folders (idempotent) + return steps/index.json."""
    try:
        import step_output_collector as _soc
        _soc.materialize(Path(project))
    except Exception:
        pass
    try:
        return json.loads((_steps_root(project) / "index.json").read_text())
    except Exception:
        return {"steps": []}


def _step_listing_html(project: str, sid: str, proj_q: str = "") -> bytes:
    """HTML directory listing of one step's output subfolder."""
    data = _ensure_steps(project)
    rec = next((s for s in data.get("steps", [])
                if str(s.get("id")) == str(sid)), None)
    pq = ("&project=" + quote(proj_q)) if proj_q else ""
    if rec is None:
        return (f"<!doctype html><meta charset=utf-8><title>step {html.escape(sid)}"
                f"</title><body style='font-family:system-ui;padding:2rem'>"
                f"<p>Unknown step id: <b>{html.escape(sid)}</b></p>").encode("utf-8")
    folder = str(rec.get("folder", ""))
    sdir = _steps_root(project) / folder
    rows = []
    if sdir.is_dir():
        for f in sorted(sdir.iterdir()):
            if f.name == "outputs.json":
                continue
            try:
                real = f.resolve()
                size = real.stat().st_size if real.exists() else 0
                tgt = str(real)
            except OSError:
                size, tgt = 0, ""
            href = (f"/stepfile?folder={quote(folder)}&name={quote(f.name)}{pq}")
            rows.append(
                f"<li><a href='{href}' target='_blank'>{html.escape(f.name)}</a>"
                f" <span style='color:#888'>{size:,} B</span>"
                f"<div style='color:#aaa;font-size:.8em'>&larr; {html.escape(tgt)}</div>"
                f"</li>")
    body = (
        f"<!doctype html><meta charset=utf-8>"
        f"<title>step {html.escape(sid)} — {html.escape(str(rec.get('name','')))}</title>"
        f"<body style='font-family:system-ui;max-width:60rem;margin:2rem auto;padding:0 1rem'>"
        f"<h2>Step {html.escape(sid)} · {html.escape(str(rec.get('name','')))}</h2>"
        f"<p>status: <b>{html.escape(str(rec.get('status','')))}</b> · "
        f"phase: {html.escape(str(rec.get('phase','')))} · "
        f"folder: <code>steps/{html.escape(folder)}/</code></p>"
        f"<ul>{''.join(rows) or '<li><i>no outputs produced for this step</i></li>'}</ul>"
        f"</body>")
    return body.encode("utf-8")


def _step_file_response(project: str, folder: str, name: str):
    """Return (bytes, ctype) for a file inside <project>/steps/<folder>/, or
    None on a bad/traversing/oversized path. Path-traversal guarded.

    `folder` is a MULTI-SEGMENT relative path since step_output_collector
    nests it phase/stage/id_slug (owner directive), so a blanket "no slash"
    rejection would refuse every legitimate step — it did, until this fix;
    caught by test_web_stepfile_path_traversal_guarded exercising a real
    materialized index rather than a hand-picked flat folder string. Each
    segment is checked individually so traversal embedded at any depth
    (`a/../../..`, a leading `/`, a bare `..` segment) is still rejected,
    and the resolved directory is re-verified to still be inside `steps/`
    as a second, path-independent guard.
    """
    if not folder or not name or "\\" in name or "/" in name or ".." in name:
        return None
    segs = folder.split("/")
    if any((not s) or s in (".", "..") or "\\" in s for s in segs):
        return None
    root = _steps_root(project)
    target = (root / folder / name)
    try:
        real = target.resolve()
        # the symlink target may live outside steps/, but the LINK itself must
        # be directly inside steps/<folder>/ (guards traversal via the request).
        link_parent = (root / folder).resolve()
        if not str(link_parent).startswith(str(root.resolve()) + "/"):
            return None
        if link_parent != target.parent.resolve() or not real.exists() \
                or real.is_dir():
            return None
        size = real.stat().st_size
        if size > _STEP_FILE_MAX_INLINE:
            return None
        raw = real.read_bytes()
    except OSError:
        return None
    suffix = real.suffix.lower()
    if suffix in _STEP_TEXT_SUFFIXES:
        ctype = "text/plain; charset=utf-8"
    else:
        ctype = "application/octet-stream"
    return raw, ctype


# ---------------------------------------------------------------------------
# HTTP handler + server
# ---------------------------------------------------------------------------
def make_handler(project: str, full: bool, fleet: str = ""):
    """Return a BaseHTTPRequestHandler subclass.

    Single-IC mode (fleet=="") serves the single-project page at "/" and
    collect(project) JSON at /api/status. FLEET mode (fleet=<root dir>) serves
    the fleet page at "/" and collect_fleet(root) JSON at /api/fleet — *project*
    is ignored in that mode — plus /api/card?project=<abs> for the per-IC
    "Run full" button and /ic?project=<abs> for the drill-down page.
    """
    is_fleet = bool(fleet)
    page_bytes = (build_fleet_page() if is_fleet else build_page()).encode("utf-8")
    # In fleet mode the SAME server also serves the single-IC drill-down page.
    ic_page_bytes = build_page().encode("utf-8") if is_fleet else page_bytes

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
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/" or path == "/index.html":
                self._send(200, page_bytes, "text/html; charset=utf-8")
                return
            if is_fleet:
                if path == "/api/fleet":
                    self._send(200, fleet_json(fleet, full),
                               "application/json; charset=utf-8")
                    return
                # per-card "Run full": authoritative full run for ONE IC,
                # validated against the fleet set + pinned server-side.
                if path == "/api/card":
                    proj = (parse_qs(parsed.query).get("project") or [""])[0]
                    if _is_allowed_project(fleet, proj):
                        self._send(200, card_json(fleet, proj),
                                   "application/json; charset=utf-8")
                    else:
                        self._send(404,
                                   json.dumps({"error": "unknown or unlisted project"}).encode("utf-8"),
                                   "application/json; charset=utf-8")
                    return
                # drill-down: /ic?project=<abs> serves the single-IC page; its
                # /api/status?project=<abs> is validated against the fleet set.
                if path == "/ic":
                    self._send(200, ic_page_bytes, "text/html; charset=utf-8")
                    return
                if path == "/api/status":
                    proj = (parse_qs(parsed.query).get("project") or [""])[0]
                    if _is_allowed_project(fleet, proj):
                        # serve the PINNED full detail when the user ran full for
                        # this IC (keeps the drill-down consistent with the card)
                        self._send(200, detail_status_json(proj),
                                   "application/json; charset=utf-8")
                    else:
                        self._send(404,
                                   json.dumps({"error": "unknown or unlisted project"}).encode("utf-8"),
                                   "application/json; charset=utf-8")
                    return
            else:
                if path == "/api/status":
                    self._send(200, status_json(project, full),
                               "application/json; charset=utf-8")
                    return
            # Per-step output subfolder: listing + read-only file serving.
            if path in ("/step", "/stepfile"):
                q = parse_qs(parsed.query)
                proj_q = (q.get("project") or [""])[0]
                if is_fleet:
                    if not _is_allowed_project(fleet, proj_q):
                        self._send(404, b"unknown or unlisted project",
                                   "text/plain; charset=utf-8")
                        return
                    proj = proj_q
                else:
                    proj = project
                if path == "/step":
                    sid = (q.get("id") or [""])[0]
                    self._send(200,
                               _step_listing_html(proj, sid,
                                                  proj_q if is_fleet else ""),
                               "text/html; charset=utf-8")
                    return
                # /stepfile
                resp = _step_file_response(proj,
                                           (q.get("folder") or [""])[0],
                                           (q.get("name") or [""])[0])
                if resp is None:
                    self._send(404, b"not found", "text/plain; charset=utf-8")
                    return
                raw, ctype = resp
                self._send(200, raw, ctype)
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


def serve(project: str, port: int = 8787, full: bool = False, host: str = "127.0.0.1",
          fleet: bool = False) -> None:
    """Run the ThreadingHTTPServer on host:port until Ctrl-C.

    When *fleet* is True, *project* is treated as a PARENT directory and every
    child Vibe-IC project is shown on one page (the fleet overview); each card
    loads lightweight and offers a per-IC "Run full" button."""
    project = os.path.abspath(project)
    name = os.path.basename(project.rstrip("/")) or project
    mode = "full" if full else "lightweight"
    handler = make_handler(project, full, fleet=project if fleet else "")
    # v1.3.83 — port-conflict resilience. A stale daemon from a PREVIOUS
    # run/project commonly still holds the default port: the new daemon then
    # dies on bind while the launcher prints the requested URL — which
    # silently serves the OLD project's dashboard. Retry the next ports and
    # RECORD the actually-bound URL under <project>/reports/ so launchers
    # print the truth, never the request.
    httpd = None
    bound_port = port
    last_exc = None
    for cand in range(port, port + 21):
        try:
            httpd = ThreadingHTTPServer((host, cand), handler)
            # #204 — read the ACTUALLY-bound port from the socket, never the
            # requested one. This makes `--port 0` (OS-assigned — the robust
            # answer for N concurrent runs) work: the recorded/printed URL is
            # always the real port, never ':0'. For a fixed port it equals cand.
            bound_port = httpd.server_address[1]
            break
        except OSError as exc:
            last_exc = exc
        if cand == 0:
            break  # port 0 can't be busy; a failure here is not a port clash
    if httpd is None:
        raise last_exc  # every candidate port busy — surface the real error
    # Show 127.0.0.1 in the clickable line even when bound to 0.0.0.0.
    shown = "127.0.0.1" if host in ("0.0.0.0", "", "::") else host
    try:
        _url_f = Path(project) / "reports" / "dashboard_web.url"
        _url_f.parent.mkdir(parents=True, exist_ok=True)
        _url_f.write_text("http://%s:%d\n" % (shown, bound_port))
    except Exception:
        pass
    label = "fleet root" if fleet else "project"
    kind = "fleet dashboard" if fleet else "flow dashboard"
    print(
        "Vibe-IC %s → http://%s:%d  (%s: %s, mode: %s)  Ctrl-C to stop"
        % (kind, shown, bound_port, label, name, mode),
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
    p.add_argument("project", help="path to the project directory (or, with --fleet, a parent dir)")
    p.add_argument("--port", type=int, default=8787, help="port to serve on (default 8787)")
    p.add_argument("--full", action="store_true", help="use the full (not lightweight) collect")
    p.add_argument("--host", default="127.0.0.1", help="host/interface to bind (default 127.0.0.1)")
    p.add_argument("--fleet", action="store_true",
                   help="treat PROJECT as a parent dir; show ALL child projects on one page")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    serve(args.project, port=args.port, full=args.full, host=args.host,
          fleet=args.fleet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
