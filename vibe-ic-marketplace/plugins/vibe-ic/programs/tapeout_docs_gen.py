#!/usr/bin/env python3
"""tapeout_docs_gen.py — emit the release documents for a tape-out candidate.

ENFORCEMENT: blocking — the phase-3 runner dispatches this program through
``step_tapeout_docs_gen`` on canonical step 37.5ic, before the compliance
auditor consumes the produced documents. The step's blocking
``program_exit_zero`` clause then consumes this program's rc inside an
``all_of`` with ``tapeout_precheck``; rc 1 means NOT RELEASABLE and cannot
advance as a passing 37.5ic verdict. This token names that measured runner/flow
control path, not finding severity.

A GENERATOR *AND* A CHECKER, WHICH IS WHY IT STAYS IN THE GATE POPULATION
========================================================================
The name says generator, so the third answer — "this is not a gate, take it out
of the flow's gate population" — has to be considered and is REFUTED by
measurement on this tree, from one metrics file differing in one number:

    every sign-off property clean                 -> rc 0, both documents written
    the same file, timing__setup__ws = -1.53      -> rc 1, NOT RELEASABLE, and
                                                     no document written at all

`release_blockers()` IS that verdict, over the 17 declared sign-off properties
in `MANUFACTURABILITY + ELECTRICAL`, decided from artefacts. rc 1 rather than
rc 2 is deliberate — see the comment at the `SystemExit(1)` below, which records
a MEASURED false VACUOUS_PASS on origin/main 69ce9260d for exactly a
`timing__setup__ws = -1.53` run. Dropping this clause from the gate population
would delete the only place that verdict is consumed and reinstate the defect
that comment was written to remove. So it stays, and it declares.

WHY THE PRODUCER ROW AND BLOCKING CLAUSE BOTH EXIST
===================================================
``step_tapeout_docs_gen`` is the producer dispatch: it runs after artefact
canonicalisation so the HTML inputs already exist. It does not replace the
canonical gate clause. Step 37.5ic re-runs its release checks through
``program_exit_zero`` with ``--check-only`` and checks the required document
globs; that is where the release verdict blocks the flow. The consumer leaves
producer-owned HTML bytes unchanged so their original citations remain valid. Keeping both paths prevents the compliance
auditor from becoming the first producer of the artefacts it is judging while
still consuming rc 1 as a refusal.

WHAT THIS IS FOR
================
Step 37.5ic (submission precheck) already produces every fact these documents
state — per-checker verdicts, per-corner timing, die geometry, the precheck's own
stage results. Until now they stayed as JSON in a run directory, so the only way
to answer "what did we actually sign off?" was to read a metrics file. This turns
the step's own artefacts into the three documents an IC release needs.

Emits, per (design, pdk):
  * SIGNOFF_<design>_<pdk>.html   — what was checked, what passed, WHAT DID NOT
  * BRIEF_<design>_<pdk>.html     — the one-page evaluation summary

THE RULE THAT MATTERS
=====================
**Every number is read from an artefact, or it is NOT_MEASURED.** There is no
default, no "typical", no carried-over figure from another run. A document that
fills a gap with a plausible number is worse than one with a hole in it, because
the hole is visible and the plausible number is not.

And a sign-off report that only lists what passed is not a sign-off report. The
`## What is NOT signed off` section is mandatory and is rendered even when empty
(saying so explicitly), because its absence is indistinguishable from cleanliness.
"""
from __future__ import annotations
import argparse, html, json, re, sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

NOT_MEASURED = "NOT_MEASURED"
TPE = timezone(timedelta(hours=8))


def load_metrics(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def measurement_scope(project: Path | None, *, html_format=False) -> str:
    """Render the selected rows' own scope disclosures without judging them."""
    disclosures = set()
    def collect(value, source, owner):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('unmeasured_obligations', 'unmeasured', 'limitations', 'unsupported_scope') and child:
                    for text in child if isinstance(child, list) else [child]:
                        if isinstance(text, str):
                            label = 'NOT_MEASURED: ' if key.startswith('unmeasured') else 'Scope: '
                            disclosures.add((owner + label + text, source))
                elif key.endswith('_status') and child == NOT_MEASURED:
                    disclosures.add((owner + key.removesuffix('_status').replace('_', ' ') + ': NOT_MEASURED', source))
                elif isinstance(child, (dict, list)):
                    collect(child, source, owner)
        elif isinstance(value, list):
            for child in value:
                collect(child, source, owner)
    if project is not None:
        plan = load_metrics(project / 'reports/flow109/plan.json')
        for row in plan.get('rows', []):
            source = f"reports/flow109/default_rows/{row['id']}.json"
            owner = f"Step {row['position']} — {row['name']}: "
            collect(load_metrics(project / source), source, owner)
    notice = ('This document records only the cited design-verification results. '
              'It is not a tape-out approval and does not demonstrate a manufactured part, '
              'silicon characterization, reliability qualification or manufacturing yield. '
              'CVC electrical-rule checks do not establish ESD simulation or device-physics qualification.')
    if html_format:
        items = ''.join(f'<li>{html.escape(text)} — <code>{html.escape(source)}</code></li>'
                        for text, source in sorted(disclosures))
        return f'<h2>Measurement scope and limitations</h2><p>{html.escape(notice)}</p><ul>{items}</ul>'
    items = '\n'.join(f'- {text} — `{source}`' for text, source in sorted(disclosures))
    return notice + ('\n\n' + items if items else '')


def g(m: dict, key: str, fmt=None):
    """Read a metric or return NOT_MEASURED. Never a default."""
    if key not in m or m[key] is None:
        return NOT_MEASURED
    v = m[key]
    return fmt(v) if fmt else v


def corners(m: dict, prefix: str) -> list[tuple[str, float]]:
    out = []
    for k, v in m.items():
        if k.startswith(prefix + "__corner:") and isinstance(v, (int, float)):
            out.append((k.split("__corner:", 1)[1], v))
    return sorted(out)


def die_geometry(m: dict):
    bbox = m.get("design__die__bbox")
    if not isinstance(bbox, str):
        return NOT_MEASURED, NOT_MEASURED, NOT_MEASURED
    try:
        x0, y0, x1, y1 = (float(t) for t in bbox.split())
    except Exception:
        return NOT_MEASURED, NOT_MEASURED, NOT_MEASURED
    return round(x1 - x0, 1), round(y1 - y0, 1), bbox


# ── the sign-off table: (label, metric key, "clean" predicate) ───────────────
MANUFACTURABILITY = [
    ("Routing DRC",            "route__drc_errors",                 lambda v: v == 0),
    ("Magic DRC",              "magic__drc_error__count",           lambda v: v == 0),
    ("KLayout DRC",            "klayout__drc_error__count",         lambda v: v == 0),
    ("Density",                "klayout__density_error__count",     lambda v: v == 0),
    ("Antenna — violating nets", "antenna__violating__nets",        lambda v: v == 0),
    ("Antenna — violating pins", "antenna__violating__pins",        lambda v: v == 0),
    ("LVS errors",             "design__lvs_error__count",          lambda v: v == 0),
    ("LVS unmatched devices",  "design__lvs_unmatched_device__count", lambda v: v == 0),
    ("LVS unmatched nets",     "design__lvs_unmatched_net__count",  lambda v: v == 0),
    ("LVS unmatched pins",     "design__lvs_unmatched_pin__count",  lambda v: v == 0),
    ("GDS vs layout XOR",      "design__xor_difference__count",     lambda v: v == 0),
]
ELECTRICAL = [
    ("Setup worst slack (ns)", "timing__setup__ws",  lambda v: v >= 0),
    ("Setup total neg slack",  "timing__setup__tns", lambda v: v >= 0),
    ("Hold worst slack (ns)",  "timing__hold__ws",   lambda v: v >= 0),
    ("Hold total neg slack",   "timing__hold__tns",  lambda v: v >= 0),
    ("Max-slew violations",    "design__max_slew_violation__count", lambda v: v == 0),
    ("Max-cap violations",     "design__max_cap_violation__count",  lambda v: v == 0),
]


CSS = """
@page{size:A4;margin:18mm 16mm 20mm}
:root{--ink:#14202e;--sub:#5b6b7d;--line:#d3dbe4;--accent:#0b5fa5;--ok:#137a4a;--bad:#b3261e;--warn:#b9761f}
body{font-family:"Noto Sans CJK TC","PingFang TC","Microsoft JhengHei",-apple-system,sans-serif;
     color:var(--ink);line-height:1.72;font-size:10.5pt;margin:0}
.doc{max-width:190mm;margin:0 auto;padding:0 2mm}
header.an{border-bottom:2.5px solid var(--accent);padding-bottom:10px;margin-bottom:16px}
.an-kind{font-size:9pt;letter-spacing:.16em;color:var(--accent);font-weight:700}
h1{font-size:18pt;margin:4px 0 2px}
.an-sub{font-size:11.5pt;color:var(--sub);margin:0 0 8px}
.an-meta{display:flex;gap:24px;flex-wrap:wrap;font-size:8.6pt;color:var(--sub)}
.an-meta b{color:var(--ink);font-weight:600}
h2{font-size:13pt;margin:24px 0 8px;padding-bottom:4px;border-bottom:1px solid var(--line);page-break-after:avoid}
h3{font-size:11pt;margin:16px 0 6px;color:var(--accent)}
table{border-collapse:collapse;width:100%;margin:10px 0 4px;font-size:9.4pt}
th,td{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
th{background:#eef3f8;font-weight:600}
td.n{text-align:right;font-variant-numeric:tabular-nums}
code{font-family:"DejaVu Sans Mono",monospace;font-size:9pt;background:#f2f5f8;padding:1px 4px;border-radius:3px}
.ok{color:var(--ok);font-weight:700}.bad{color:var(--bad);font-weight:700}.wn{color:var(--warn);font-weight:700}
.nm{color:var(--sub);font-style:italic}
.verdict{border:2px solid var(--line);border-radius:6px;padding:14px 18px;margin:14px 0}
.verdict.part{border-color:var(--warn);background:#fdf6ec}
.verdict.clean{border-color:var(--ok);background:#f1f8f4}
.verdict h3{margin:0 0 6px;color:inherit;font-size:12pt}
.note{border-left:3px solid var(--accent);background:#f4f8fc;padding:9px 14px;margin:12px 0;font-size:9.6pt}
.warn{border-left:3px solid var(--warn);background:#fdf6ec;padding:9px 14px;margin:12px 0;font-size:9.6pt}
.cap{font-size:8.8pt;color:var(--sub);margin:2px 0 14px}.cap b{color:var(--ink)}
footer.an{margin-top:24px;padding-top:8px;border-top:1px solid var(--line);font-size:8.2pt;color:var(--sub)}
"""


def cell(val, ok_pred):
    """Render a measured value with its verdict, or an explicit NOT_MEASURED."""
    if val == NOT_MEASURED:
        return '<td class="n nm">NOT_MEASURED</td>', None
    try:
        good = ok_pred(val)
    except Exception:
        good = None
    txt = f"{val:g}" if isinstance(val, float) else str(val)
    if good is True:
        return f'<td class="n"><span class="ok">{txt}</span></td>', True
    if good is False:
        return f'<td class="n"><span class="bad">{txt}</span></td>', False
    return f'<td class="n">{txt}</td>', None


def rows_for(m, spec):
    html_rows, clean, dirty, unknown = [], 0, 0, 0
    for label, key, pred in spec:
        v = g(m, key)
        td, good = cell(v, pred)
        if good is True: clean += 1
        elif good is False: dirty += 1
        else: unknown += 1
        html_rows.append(f"<tr><td>{html.escape(label)}</td>{td}<td><code>{html.escape(key)}</code></td></tr>")
    return "\n".join(html_rows), clean, dirty, unknown


# ── THE RELEASE GATE ────────────────────────────────────────────────────────
# Owner, 2026-08-20: 「一定要全部 pass 才會開始生成」.
#
# A release document for a run that did not pass is worse than no document. A
# sign-off report that says NOT SIGNED OFF is a status line wearing a
# document's clothes, and a Product Brief for a failing die describes a part
# nobody can order. Worse, both are FILES -- they get copied, attached and
# quoted long after the run they came from is forgotten, and nothing in the
# copy says it was provisional.
#
# So generation is GATED, not annotated. If the run is not clean the program
# writes NOTHING and says exactly which properties are not clean. The absence
# of the documents IS the signal.
#
# NOT_MEASURED blocks generation too, and that is deliberate: "we did not look"
# and "we looked and it was fine" must never produce the same artefact.

def release_blockers(m: dict) -> list[str]:
    """Everything standing between this run and a releasable document."""
    out = []
    for label, key, pred in MANUFACTURABILITY + ELECTRICAL:
        v = g(m, key)
        if v == NOT_MEASURED:
            out.append(f"{label}: NOT_MEASURED ({key})")
            continue
        try:
            ok = pred(v)
        except Exception:
            out.append(f"{label}: unreadable value {v!r} ({key})")
            continue
        if not ok:
            out.append(f"{label}: {v} ({key})")
    return out


def build_signoff(m, design, pdk, plugin_ver, run_id, precheck, scope=None):
    w, h, bbox = die_geometry(m)
    man_rows, man_ok, man_bad, man_unk = rows_for(m, MANUFACTURABILITY)
    ele_rows, ele_ok, ele_bad, ele_unk = rows_for(m, ELECTRICAL)
    stamp = datetime.now(TPE).strftime("%Y-%m-%d %H:%M")

    # THE VERDICT IS COMPUTED, NEVER TYPED. A report whose headline is written by
    # hand can disagree with its own table; this one cannot.
    if man_bad == 0 and ele_bad == 0 and man_unk == 0 and ele_unk == 0:
        vclass, vtitle = "clean", "MEASURED CHECKS PASS — limited to the reported properties"
    elif man_bad == 0:
        vclass, vtitle = "part", "PARTIAL — reported checks incomplete or outside limits"
    else:
        vclass, vtitle = "part", "NOT SIGNED OFF — a manufacturability check is failing"

    setup_c = corners(m, "timing__setup__ws")
    hold_c = corners(m, "timing__hold__ws")
    corner_rows = ""
    for name, val in setup_c:
        hv = dict(hold_c).get(name)
        sc = "bad" if val < 0 else "ok"
        hc = "bad" if (hv is not None and hv < 0) else "ok"
        hs = f'<span class="{hc}">{hv:g}</span>' if hv is not None else '<span class="nm">NOT_MEASURED</span>'
        corner_rows += (f'<tr><td><code>{html.escape(name)}</code></td>'
                        f'<td class="n"><span class="{sc}">{val:g}</span></td><td class="n">{hs}</td></tr>')
    if not corner_rows:
        corner_rows = '<tr><td colspan="3" class="nm">NOT_MEASURED in this document: the cited metrics summary carries no per-corner slack.</td></tr>'

    pre_rows = ""
    for stage, res in (precheck or []):
        pre_rows += f'<tr><td>{html.escape(stage)}</td><td>{res}</td></tr>'
    pre_block = (f"<h2>4. 送件預檢（主辦方自己的容器）</h2><table>"
                 f"<thead><tr><th>階段</th><th>結果</th></tr></thead><tbody>{pre_rows}</tbody></table>"
                 if pre_rows else
                 "<h2>4. 送件預檢</h2><p class='nm'>NOT_MEASURED — 本次執行未附預檢結果。</p>")

    not_signed = []
    if ele_bad:
        not_signed.append(f"<li><b>電氣品質有 {ele_bad} 項未達標</b>（見第 3 節），其中 setup 時序為負值。</li>")
    if man_unk or ele_unk:
        not_signed.append(f"<li><b>{man_unk + ele_unk} 項未量測</b>，以 <code>NOT_MEASURED</code> 標示，"
                          f"未以任何預設值填補。</li>")
    # These two are SCOPE, not disclaimer: they name checks that were never run,
    # which is exactly what this section is for. Kept short.
    not_signed.append("<li><b>矽上量測</b>：未進行。無特性化時序、無功耗量測、無溫度範圍、無良率。</li>")
    not_signed.append("<li><b>功能正確性</b>：請查閱本次執行的功能驗證結果；本報告只列出表中已量測的檢查。</li>")

    return f"""<meta charset="utf-8"><title>Design verification {design} × {pdk}</title><style>{CSS}</style>
<div class="doc">
<header class="an">
  <div class="an-kind">DESIGN VERIFICATION REPORT</div>
  <h1>{html.escape(design)} — 設計驗證報告</h1>
  <p class="an-sub">製程 {html.escape(pdk)}</p>
  <div class="an-meta">
    <span>文件編號 <b>SO-{html.escape(design)}-{html.escape(pdk)}</b></span>
    <span>產生於 <b>{stamp} (UTC+8)</b></span>
    <span>流程版本 <b>{html.escape(str(plugin_ver))}</b></span>
    <span>執行 <b>{html.escape(str(run_id))}</b></span>
  </div>
</header>

<div class="verdict {vclass}"><h3>{vtitle}</h3>
製造性 {man_ok} 項通過 / {man_bad} 項未過 / {man_unk} 項未量測　·　
電氣品質 {ele_ok} 項通過 / {ele_bad} 項未過 / {ele_unk} 項未量測
</div>
<div class="note">
本報告的判定是<b>由表格算出來的，不是寫上去的</b>。每一個數字都讀自本次執行自己的
<code>metrics.json</code>；讀不到的一律標 <code>NOT_MEASURED</code>，不以預設值填補。
</div>

<h2>1. 受檢對象</h2>
<table><tbody>
<tr><th>設計</th><td><code>{html.escape(design)}</code></td></tr>
<tr><th>製程</th><td><code>{html.escape(pdk)}</code></td></tr>
<tr><th>晶粒尺寸</th><td>{w} × {h} µm　<span class="nm">（bbox {html.escape(str(bbox))}）</span></td></tr>
<tr><th>核心利用率</th><td>{g(m,'design__instance__utilization')}</td></tr>
<tr><th>標準元件利用率</th><td>{g(m,'design__instance__utilization__stdcell')}</td></tr>
<tr><th>總功耗（估算）</th><td>{g(m,'power__total')} W　<span class="nm">— 工具估算，非矽上量測</span></td></tr>
</tbody></table>

<h2>2. 幾何與連接檢查</h2>
<p>以下每一項都必須為 0 才算通過。</p>
<table><thead><tr><th>檢查</th><th>值</th><th>指標名稱</th></tr></thead><tbody>{man_rows}</tbody></table>
<p class="cap"><b>表 2.1</b>　製造性檢查。指標名稱一併列出，讓任何人都能回到原始 JSON 覆核。</p>

<h2>3. 電氣品質</h2>
<table><thead><tr><th>項目</th><th>值</th><th>指標名稱</th></tr></thead><tbody>{ele_rows}</tbody></table>
<p class="cap"><b>表 3.1</b>　電氣品質。slack 為負代表違規。</p>
<h3>3.1 各製程角落的時序裕度</h3>
<table><thead><tr><th>角落</th><th>Setup WS (ns)</th><th>Hold WS (ns)</th></tr></thead><tbody>{corner_rows}</tbody></table>
<p class="cap"><b>表 3.2</b>　逐角落最差裕度。單一數字會掩蓋角落之間的差異，所以逐一列出。</p>

{pre_block}

<h2>5. 未簽核的部分</h2>
<ul>{''.join(not_signed)}</ul>
{scope if scope is not None else measurement_scope(None, html_format=True)}

<footer class="an">
本報告由 Vibe-IC 設計文件產生器產生。每一個數值都可追溯到該次執行自己的
產物；讀不到的一律標示 <code>NOT_MEASURED</code>，未以任何預設值填補。
</footer>
</div>"""


def build_brief(m, design, pdk, plugin_ver, summary, ports, scope=None):
    w, h, bbox = die_geometry(m)
    stamp = datetime.now(TPE).strftime("%Y-%m-%d")
    man_bad = sum(1 for _, k, p in MANUFACTURABILITY
                  if g(m, k) != NOT_MEASURED and not p(g(m, k)))
    ele_bad = sum(1 for _, k, p in ELECTRICAL
                  if g(m, k) != NOT_MEASURED and not p(g(m, k)))
    port_rows = "".join(
        f"<tr><td><code>{html.escape(n)}</code></td><td class='n'>{wd}</td>"
        f"<td>{html.escape(d)}</td></tr>" for n, wd, d in ports)
    status = ("已量測的幾何檢查通過；電氣檢查尚有未達標項目"
              if man_bad == 0 and ele_bad else
              "表中已量測的檢查通過；請參閱量測範圍與限制" if man_bad == 0 and ele_bad == 0 else
              "尚有製造性檢查未通過")
    return f"""<meta charset="utf-8"><title>Product Brief {design}</title><style>{CSS}</style>
<div class="doc">
<header class="an">
  <div class="an-kind">PRODUCT BRIEF</div>
  <h1>{html.escape(design)}</h1>
  <p class="an-sub">{html.escape(summary)}</p>
  <div class="an-meta">
    <span>文件編號 <b>PB-{html.escape(design)}</b></span>
    <span>日期 <b>{stamp}</b></span>
    <span>製程 <b>{html.escape(pdk)}</b></span>
    <span>流程版本 <b>{html.escape(str(plugin_ver))}</b></span>
  </div>
</header>

<h2>這是什麼</h2>
<p>{html.escape(summary)}</p>

<h2>對外介面</h2>
<table><thead><tr><th>訊號</th><th>寬度</th><th>說明</th></tr></thead><tbody>{port_rows}</tbody></table>

<h2>實體</h2>
<table><tbody>
<tr><th>製程</th><td><code>{html.escape(pdk)}</code></td></tr>
<tr><th>晶粒尺寸</th><td>{w} × {h} µm</td></tr>
<tr><th>核心利用率</th><td>{g(m,'design__instance__utilization')}</td></tr>
<tr><th>功耗</th><td>{g(m,'power__total')} W　<span class="nm">工具估算</span></td></tr>
</tbody></table>

<h2>目前狀態</h2>
<div class="verdict {'part' if ele_bad or man_bad else 'clean'}">
<h3>{status}</h3>
製造性未過 {man_bad} 項　·　電氣品質未過 {ele_bad} 項
</div>

{scope if scope is not None else measurement_scope(None, html_format=True)}
<footer class="an">
由 Vibe-IC 設計文件產生器產生。數值讀自該次執行自己的產物，未量測者標
<code>NOT_MEASURED</code>。
</footer>
</div>"""


def from_project(project: Path, ic_name: str | None = None):
    """Resolve every input from ONE project tree, so a document cannot mix runs.

    Returns (metrics_path, design, pdk, run_id) or raises. The alternative --
    passing each path on the command line -- is how two different dies end up in
    one report: they are both 'spm on gf180mcuD' and nothing in the filenames
    says which slot they were built for.
    """
    m = project / "phase3" / "final" / "metrics.json"
    if not m.is_file():
        cand = sorted(project.glob("**/final/metrics.json"))
        if len(cand) != 1:
            raise SystemExit(
                f"refusing to guess which run to document: found {len(cand)} "
                f"metrics.json under {project}. A document assembled from more "
                f"than one run is worse than none.")
        m = cand[0]
    pre = project / "reports" / "phase3" / "shuttle_precheck.json"
    run_id = NOT_MEASURED
    if pre.is_file():
        try:
            run_id = json.loads(pre.read_text()).get("run_id", NOT_MEASURED)
        except Exception:
            pass
    design, pdk = identity(project, ic_name)
    return m, design, pdk, run_id


# `input/project.json` is where this flow already records which design and which
# PDK a run is for -- `pdk_consistency_check` and `declared_pdk_is_the_pdk_used_check`
# both read exactly these keys. Reading them here is what lets the gate clause be
# the chip-AGNOSTIC `--project .` the flow yaml declares: the two identities are
# properties OF the run, so demanding them on the command line made the only
# declared invocation one this program refuses (rc=2, which
# `flow_compliance_check` reads as the input-missing skip -- a gate that passes
# vacuously forever).
_DESIGN_KEYS = ("design", "design_name", "top", "top_module")
_PDK_KEYS = ("pdk", "target_pdk", "pdk_target")

# U19 (IC_BLOCKER_AUDIT 2026-09-29). MEASURED on an IC/DIE run of the flow's
# own front door: no `input/project.json` exists there, so both documents were
# written as `*_NOT_MEASURED_NOT_MEASURED.html` while the same tree held the
# design's L1 identity and the PDK the sign-off tools actually ran on. These
# are the run's own records, read in this order; a source that is absent is
# NAMED, never replaced by a default.
_PROJECT_JSON = "input/project.json"
_L1_DOC = "phase1/generated_docs/L1_DATASHEET.json"
_L1_KEYS = ("ic_name", "part_number")
# Written by `librelane_contract.pdk_root_resolution` for every run that
# resolved a PDK tree for its layout/sign-off tools: the PDK that was USED.
_SIGNOFF_PDK_RECORD = "phase3/librelane_pdk_root.provenance.json"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def _read_json(path: Path) -> dict:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _first(doc: dict, keys) -> str:
    for k in keys:
        v = doc.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _signoff_pdk(project: Path) -> str:
    rec = _read_json(project / _SIGNOFF_PDK_RECORD)
    for holder in (rec, rec.get("derivation") if isinstance(rec.get("derivation"), dict) else {}):
        v = holder.get("pdk")
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def resolve_identity(project: Path, ic_name: str | None = None) -> dict:
    """{'design': (value, source), 'pdk': (value, source)}; value NOT_MEASURED
    with source naming every place looked when nothing declares it."""
    pj = _read_json(project / _PROJECT_JSON)
    design = pdk = None
    if ic_name and ic_name.strip():
        design = (ic_name.strip(), "--ic-name")
    elif _first(pj, _DESIGN_KEYS):
        design = (_first(pj, _DESIGN_KEYS), _PROJECT_JSON)
    elif _first(_read_json(project / _L1_DOC), _L1_KEYS):
        design = (_first(_read_json(project / _L1_DOC), _L1_KEYS), _L1_DOC)
    if _signoff_pdk(project):
        pdk = (_signoff_pdk(project), _SIGNOFF_PDK_RECORD)
    elif _first(pj, _PDK_KEYS):
        pdk = (_first(pj, _PDK_KEYS), _PROJECT_JSON)
    design = design or (NOT_MEASURED, "absent: --ic-name, "
                        f"{_PROJECT_JSON} {'/'.join(_DESIGN_KEYS)}, "
                        f"{_L1_DOC} {'/'.join(_L1_KEYS)}")
    pdk = pdk or (NOT_MEASURED, f"absent: {_SIGNOFF_PDK_RECORD} pdk, "
                  f"{_PROJECT_JSON} {'/'.join(_PDK_KEYS)}")
    # the value becomes part of a FILENAME; keep the file where it was asked for
    return {k: (_SAFE_NAME.sub("-", v).strip("-") or NOT_MEASURED, src)
            for k, (v, src) in (("design", design), ("pdk", pdk))}


def identity(project: Path, ic_name: str | None = None) -> tuple[str, str]:
    """Read (design, pdk) off the project, or NOT_MEASURED. Never a default.

    A guessed design name is the same failure as a guessed number: it makes a
    document that names the wrong chip, and nothing in the file says it was a
    guess.
    """
    got = resolve_identity(project, ic_name)
    return got["design"][0], got["pdk"][0]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--metrics", type=Path)
    ap.add_argument("--project", type=Path,
                    help="resolve metrics + run id from ONE project tree")
    ap.add_argument("--design", default=None,
                    help="design name; read off --project when not given")
    ap.add_argument("--ic-name", default=None,
                    help="design identity (the runner's --ic-name); outranks "
                         "input/project.json and L1 when --design is not given")
    ap.add_argument("--pdk", default=None,
                    help="PDK name; read off --project when not given")
    ap.add_argument("--plugin-version", default=NOT_MEASURED)
    ap.add_argument("--run-id", default=NOT_MEASURED)
    ap.add_argument("--summary", default="")
    ap.add_argument("--ports-json", type=Path)
    ap.add_argument("--precheck-json", type=Path)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--allow-incomplete", action="store_true",
                    help="write a DRAFT for a run that is not clean; every "
                         "document is stamped DRAFT and says why")
    ap.add_argument("--check-only", action="store_true",
                    help="check the run's release conditions without writing documents")
    a = ap.parse_args()

    if a.project and not a.metrics:
        a.metrics, design, pdk, rid = from_project(a.project, a.ic_name)
        for k, (v, src) in resolve_identity(a.project, a.ic_name).items():
            if getattr(a, k) is None:
                print(f"identity {k}={v} ({src})")
        if a.run_id == NOT_MEASURED:
            a.run_id = rid
        if a.design is None:
            a.design = design
        if a.pdk is None:
            a.pdk = pdk
    if a.design is None and a.ic_name:
        a.design = a.ic_name
    if a.design is None:
        a.design = NOT_MEASURED
    if a.pdk is None:
        a.pdk = NOT_MEASURED
    if not a.metrics:
        raise SystemExit('--metrics or --project is required')
    m = load_metrics(a.metrics)
    if not m:
        raise SystemExit(f"refusing to write a document from an unreadable metrics file: {a.metrics}")
    ports = json.loads(a.ports_json.read_text()) if a.ports_json and a.ports_json.is_file() else []
    pre = json.loads(a.precheck_json.read_text()) if a.precheck_json and a.precheck_json.is_file() else []

    # ── DOES THIS STEP APPLY TO THIS DESIGN AT ALL? ────────────────────────
    #
    # ONE GATE CLAUSE, TWO PROGRAMS, AND ONLY ONE OF THEM WAS ASKING
    # (2026-09-15, icspm2). Step 37.5ic's clause runs `tapeout_precheck` and
    # this program inside one `all_of`. MEASURED on a gf180mcuD run of `spm`,
    # a HARDMACRO delivery:
    #
    #     tapeout_precheck . --json …   -> PASS, step_applies false,
    #         "step 37.5ic does not apply to this design: step 0.5ic routed it
    #          to the IP/hardmacro terminal … which delivers LEF/Liberty/GDS/
    #          Verilog and no die. There is no submission, so there is no
    #          tape-out precheck to pass"
    #     phase3_one_shot_runner.step_tapeout_docs_gen -> SKIP, from
    #         `_canonical_step_condition(project, "37.5ic")`
    #     tapeout_docs_gen …            -> rc 1, NOT RELEASABLE, refusing the
    #         design on five DIE metrics an IP delivery has no die to measure
    #
    # Two of the three sites knew; this one asked nothing. The flow's own
    # structural condition cannot separate them — step 0.5ic writes
    # `input/submission_template/slots/*.yaml` on EVERY route — so the question
    # has to be asked where the answer lives, which is the design's own
    # declaration.
    #
    # THE SAME READER AND THE SAME CHANNEL as the sibling program, deliberately:
    # `tapeout_precheck.delivery_route` (which consults
    # `submission_template_check.catalogue_selects_ip`, never a filename), and
    # the rc-0 NOT_APPLICABLE channel whose comment in that program says why it
    # is not `_vacuous_exit.RC_VACUOUS`: "rc 2 … `_DECLARED_SIGNOFF_GATES`
    # reads as an ERROR outright".
    #
    # ONLY THE IP ROUTE. `delivery_route` answers ROUTE_UNDECLARED — not
    # ROUTE_IP — when nobody declared one, and its own docstring says why:
    # "0.5ic failing is the one circumstance in which a CHIP most needs this
    # step, and reading its silence as 'must be an IP' would let the failure
    # delete the check that would have reported it." A CHIP with unmeasured DRC
    # is still rc 1 NOT RELEASABLE, unchanged.
    #
    # AND NO DOCUMENT IS WRITTEN. The anti-fabrication rule this program is
    # built on is untouched: a run that is not documented here is not
    # documented at all.
    if a.project is not None:
        try:
            import tapeout_precheck as _tp                   # noqa: PLC0415
            route, route_evidence = _tp.delivery_route(a.project)
        except Exception as exc:                             # noqa: BLE001
            route, route_evidence = "", f"route not read: {exc}"
        if route and route == getattr(_tp, "ROUTE_IP", object()):
            print(f"NOT_APPLICABLE — no documents written. Step 37.5ic does "
                  f"not apply to this design: step 0.5ic routed it to the "
                  f"IP/hardmacro terminal ({route_evidence}), which delivers "
                  f"LEF/Liberty/GDS/Verilog and no die. These are DIE release "
                  f"documents; there is no die to describe, and this is NOT a "
                  f"statement that a layout was examined. The IP terminal's "
                  f"own documents are step 37.5ip's "
                  f"(`ip_release_docs_gen`).")
            raise SystemExit(0)

    blockers = release_blockers(m)
    if blockers and (a.check_only or not a.allow_incomplete):
        print("NOT RELEASABLE — no documents written. "
              f"{len(blockers)} propert(ies) are not clean:", file=sys.stderr)
        for b in blockers:
            print(f"  - {b}", file=sys.stderr)
        print("\nA release document for a run that did not pass is worse than no "
              "document: it becomes a file that outlives the run it came from. "
              "Fix the run, or pass --allow-incomplete to write a DRAFT.", file=sys.stderr)
        # rc=1, NOT 2. In this flow rc==2 is the "input-missing skip" convention
        # and `flow_compliance_check` promotes it to VACUOUS_PASS -- a PASS tier.
        # Exiting 2 here meant step 37.5ic's gate reported a pass on precisely
        # the runs this program had just refused to document: MEASURED on
        # origin/main 69ce9260d, a project whose only defect was
        # timing__setup__ws = -1.53 returned `ok = True` from
        # `_check_program_exit_zero`, tagged `__VACUOUS_HINT__`. A run that is
        # NOT RELEASABLE is a content-earned FAIL and must be scored as one.
        raise SystemExit(1)

    if a.check_only:
        print("RELEASABLE — release conditions checked; no documents written")
        return

    a.out_dir.mkdir(parents=True, exist_ok=True)
    so = a.out_dir / f"SIGNOFF_{a.design}_{a.pdk}.html"
    pb = a.out_dir / f"BRIEF_{a.design}_{a.pdk}.html"
    draft = bool(blockers)
    scope = measurement_scope(a.project, html_format=True)
    so_html = build_signoff(m, a.design, a.pdk, a.plugin_version, a.run_id, pre, scope)
    pb_html = build_brief(m, a.design, a.pdk, a.plugin_version, a.summary, ports, scope)
    if draft:
        # A DRAFT that only says so on the console is not a draft -- the FILE is
        # what gets copied and quoted. Stamp the document itself.
        banner = ('<div class="verdict part"><h3>DRAFT — 這份文件不可發布</h3>'
                  f'本次執行有 {len(blockers)} 項未達標，文件僅供內部檢視。'
                  '<ul>' + "".join(f"<li>{html.escape(b)}</li>" for b in blockers) + '</ul></div>')
        so_html = so_html.replace('<div class="verdict', banner + '<div class="verdict', 1)
        pb_html = pb_html.replace('<h2>這是什麼</h2>', banner + '<h2>這是什麼</h2>', 1)
    so.write_text(so_html, encoding="utf-8")
    pb.write_text(pb_html, encoding="utf-8")
    print(f"wrote {so}")
    print(f"wrote {pb}")


if __name__ == "__main__":
    main()
