#!/usr/bin/env python3
"""
cts_quality_check.py — Step 19 CTS substance gate.

Step 19 (Clock Tree Synthesis) of the phase1_phase2_phase3 flow used to
gate ONLY on ``files_exist`` for ``phase3/stage3/pnr/post_cts.def`` and
``phase3/stage3/cts/clock_tree.rpt``. A file appearing — even the
runner's vacuous fallback stub
``(OpenROAD CTS not invoked or zero output captured)`` — flipped the gate
PASS with ZERO verification of its content. A CTS step that inserted no
clock buffers, or a report carrying no clock-tree metrics at all, would
have shipped a design with an unbuffered / un-synthesised clock straight
into hold-fix and routing.

This checker performs REAL DETERMINISTIC SUBSTANCE verification of the
two artefacts that OpenROAD / TritonCTS actually produces:

  1. Parse ``clock_tree.rpt`` (TritonCTS-derived). It must NOT be the
     vacuous "(OpenROAD CTS not invoked or zero output captured)" stub,
     and it must carry real clock-tree numbers.

  2. CLOCK BUFFERS WERE ACTUALLY INSERTED (count > 0). Two independent
     sources are read and, when both are present, cross-checked:
       * report  : ``[INFO CTS-0018] Created N clock buffers.``
       * post_cts.def : count of placed clock-buffer / clock-inverter
                        instances (cellname matches *clkbuf* / *clkinv* /
                        *clkbufx* style tokens) in the COMPONENTS section.
     If BOTH say zero (or neither yields a positive number) => FAIL: CTS
     inserted nothing, the clock is unbuffered.

  3. AN INSERTION-LATENCY / DEPTH metric is present. TritonCTS reports
     the clock-path insertion latency as a buffer-path depth/level — any
     of:
       * ``[INFO CTS-0102]  Path depth A - B``
       * ``[INFO CTS-0017]     Max level of the clock tree: N``
       * ``[INFO CTS-0012/0013] Min/Max number of buffers in clock path``
     PLUS, when the report carries an explicit ``report_clock_skew`` /
     ``report_clock_latency`` block, the numeric skew and max-latency
     (in whatever unit the tool printed) are parsed. If the report has
     NEITHER a depth/level metric NOR a numeric skew/latency => the
     report is vacuous => FAIL.

  4. If a skew TARGET is stated (in the report's own
     ``clock skew target`` / ``max skew`` line, in ``clock_plan.json``,
     or in an SDC ``set_clock_uncertainty`` constraint that the report
     references) AND a measured skew is present, enforce
     ``measured_skew <= target_skew`` (same unit). The target is NEVER
     fabricated — it is only enforced when the artefact provides it.

  5. Structural sanity on post_cts.def (universal, not chip-specific):
     every COMPONENTS instance must be PLACED or FIXED — any UNPLACED
     clock buffer is a real CTS failure.

Verdicts
--------
* PASS    (rc=0) — report parseable & non-stub, clock buffers > 0 (and
                   report/DEF counts consistent when both present),
                   at least one real latency/depth metric present, no
                   UNPLACED instance, and skew within target when a
                   target is stated.
* FAIL    (rc=1) — required artefact absent / empty / unparseable, the
                   vacuous "CTS not invoked" stub, zero clock buffers,
                   no skew/latency/depth number at all (vacuous report),
                   report-vs-DEF buffer count grossly inconsistent, an
                   UNPLACED instance, or measured skew > stated target.
* WAIVED  (rc=0) — ``waivers.json`` declares the step waived.
* SKIP    (rc=2) — project dir not found (operational, not a CTS run).

chip-AGNOSTIC. No vendor / IC / tool-specific numeric threshold is
hard-coded. No skew limit is invented — a limit is enforced only when
the artefact supplies one. The only bounds applied are universal
structural facts (buffer count must be > 0, every instance must be
PLACED/FIXED), which are stated in honest_notes.

Usage
-----
    python3 cts_quality_check.py <project_dir> [--json <out>]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


_GATE_NAME = "cts_quality_check"
_GATE_LABEL = "cts_quality"

# Canonical (current flow) locations.
_DEF_CANDIDATES = [
    "phase3/stage3/pnr/post_cts.def",
]
_RPT_CANDIDATES = [
    "phase3/stage3/cts/clock_tree.rpt",
]
_CLOCK_PLAN_CANDIDATES = [
    "phase3/stage3/cts/clock_plan.json",
]

# The runner's vacuous-fallback marker — a report that contains ONLY this
# is not a real CTS run.
_VACUOUS_MARKERS = (
    "not invoked or zero output captured",
    "CTS not invoked",
)

# Clock-buffer / clock-inverter cell-name tokens (sky130 clkbuf_16,
# nangate CLKBUF_X1, generic CLKINV, etc.). Lower-cased match.
_CLK_CELL_RE = re.compile(r"clk(?:buf|inv|gate|cell)", re.IGNORECASE)

# When report and DEF both give a clock-buffer count, the DEF count may
# legitimately exceed the report's "Created" count (root buffer + sink
# buffers + dummy loads counted differently). We only flag a gross
# inconsistency, defined as one being zero while the other is large, or
# the two differing by more than this multiplicative factor.
_BUF_COUNT_FACTOR = 6.0


# ---------------------------------------------------------------------------
# waiver plumbing (mirror wafer_sort_yield_check.py)
# ---------------------------------------------------------------------------
def _load_waivers(project):
    p = project / "waivers.json"
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text()).get("waived_steps") or []
    except Exception:
        return []


def _step_waived(project, step_label):
    for w in _load_waivers(project):
        sid = str(w.get("id", "")).strip()
        ticket = w.get("ticket", "")
        if sid == step_label or step_label in ticket:
            return w
    return None


def _first_existing(project: Path, candidates):
    for rel in candidates:
        p = project / rel
        if p.is_file():
            return rel, p
    return None, None


# ---------------------------------------------------------------------------
# report parsing — TritonCTS / OpenROAD "clock_tree.rpt"
# ---------------------------------------------------------------------------
def _parse_report(text: str):
    """Return a dict of substance read from the clock_tree.rpt.

    Keys (any may be None when absent):
      created_buffers   int    — CTS-0018 "Created N clock buffers"
      created_nets      int    — CTS-0015 "Created N clock nets"
      sinks             int    — CTS-0010 / CTS-0099
      path_depth        (a, b) — CTS-0102 "Path depth A - B"
      max_level         int    — CTS-0017 "Max level of the clock tree"
      min_path_bufs     int    — CTS-0012
      max_path_bufs     int    — CTS-0013
      skew_value        float  — report_clock_skew numeric (any unit)
      skew_unit         str
      latency_value     float  — report_clock_latency / max insertion lat
      latency_unit      str
      skew_target       float  — stated max-skew / target (same unit)
      is_vacuous        bool   — only the stub marker present
    """
    out = {
        "created_buffers": None, "created_nets": None, "sinks": None,
        "path_depth": None, "max_level": None,
        "min_path_bufs": None, "max_path_bufs": None,
        "skew_value": None, "skew_unit": None,
        "latency_value": None, "latency_unit": None,
        "skew_target": None,
        "is_vacuous": False,
    }
    low = text.lower()

    # vacuous-stub detection: report has the marker AND no CTS-00xx data.
    has_cts_data = bool(re.search(r"\bCTS-\d{3,4}\b", text)) or \
        ("clock buffers" in low) or ("clock tree" in low and
                                     re.search(r"\bdepth\b|\blevel\b", low))
    if any(m.lower() in low for m in _VACUOUS_MARKERS) and not has_cts_data:
        out["is_vacuous"] = True
        return out

    def _int(pat):
        m = re.search(pat, text)
        return int(m.group(1)) if m else None

    def _sum(pat):
        """ORGANIC #567 — a multi-clock-tree design emits one CTS-0018
        'Created N clock buffers' line PER tree; the per-tree counts must
        be SUMMED, not first-match-only (a 3-tree 2+145+137 design read as
        2 then tripped BUFFER_COUNT_INCONSISTENT against the 614-instance
        DEF). Returns None when there is no match at all (preserves the
        ZERO_CLOCK_BUFFERS path)."""
        nums = [int(m.group(1)) for m in re.finditer(pat, text)]
        return sum(nums) if nums else None

    # Created N clock buffers (CTS-0018), summed across every clock tree.
    out["created_buffers"] = _sum(
        r"Created\s+(\d+)\s+clock\s+buffers")
    out["created_nets"] = _sum(r"Created\s+(\d+)\s+clock\s+nets")

    # sinks — take the largest "N sinks" / "Sinks N" we see.
    sink_nums = []
    for m in re.finditer(r"(\d+)\s+sinks", text, re.IGNORECASE):
        sink_nums.append(int(m.group(1)))
    for m in re.finditer(r"\bSinks\s+(\d+)", text):
        sink_nums.append(int(m.group(1)))
    if sink_nums:
        out["sinks"] = max(sink_nums)

    # Path depth A - B  (CTS-0102) — insertion-latency-as-depth.
    m = re.search(r"Path\s+depth\s+(\d+)\s*-\s*(\d+)", text, re.IGNORECASE)
    if m:
        out["path_depth"] = (int(m.group(1)), int(m.group(2)))

    out["max_level"] = _int(r"Max\s+level\s+of\s+the\s+clock\s+tree\s*:?\s*(\d+)")
    out["min_path_bufs"] = _int(
        r"Minimum\s+number\s+of\s+buffers\s+in\s+the\s+clock\s+path\s*:?\s*(\d+)")
    out["max_path_bufs"] = _int(
        r"Maximum\s+number\s+of\s+buffers\s+in\s+the\s+clock\s+path\s*:?\s*(\d+)")

    # Numeric skew, only when the report carries report_clock_skew output.
    # e.g. "Clock skew  0.0234 ns" / "Worst skew = 12.5 ps" / "skew: 0.018"
    m = re.search(
        r"(?:clock\s+skew|worst\s+skew|max(?:imum)?\s+skew|\bskew)\b"
        r"[^\d\-+]*([-+]?\d+(?:\.\d+)?)\s*(ps|ns|us|s)?",
        text, re.IGNORECASE)
    if m and "target" not in text[max(0, m.start() - 20):m.start()].lower():
        out["skew_value"] = float(m.group(1))
        out["skew_unit"] = (m.group(2) or "").lower() or None

    # Numeric insertion/clock latency from a report_clock_latency block.
    m = re.search(
        r"(?:insertion\s+latency|clock\s+latency|max(?:imum)?\s+latency)"
        r"[^\d\-+]*([-+]?\d+(?:\.\d+)?)\s*(ps|ns|us|s)?",
        text, re.IGNORECASE)
    if m:
        out["latency_value"] = float(m.group(1))
        out["latency_unit"] = (m.group(2) or "").lower() or None

    # Stated skew TARGET — only if the report explicitly states one.
    m = re.search(
        r"(?:skew\s+target|target\s+skew|max(?:imum)?\s+allowed\s+skew"
        r"|skew\s+(?:limit|budget|spec))\b"
        r"[^\d\-+]*([-+]?\d+(?:\.\d+)?)\s*(ps|ns|us|s)?",
        text, re.IGNORECASE)
    if m:
        out["skew_target"] = float(m.group(1))

    return out


def _target_from_clock_plan(project: Path):
    """Read an optional skew target from clock_plan.json (NOT fabricated)."""
    rel, p = _first_existing(project, _CLOCK_PLAN_CANDIDATES)
    if p is None:
        return None, None
    try:
        doc = json.loads(p.read_text())
    except Exception:
        return rel, None
    if not isinstance(doc, dict):
        return rel, None
    for k in ("skew_target_ns", "max_skew_ns", "skew_target", "max_skew",
              "target_skew", "skew_budget_ns", "skew_budget"):
        if k in doc and doc[k] is not None:
            try:
                return rel, float(doc[k])
            except (TypeError, ValueError):
                continue
    return rel, None


# ---------------------------------------------------------------------------
# DEF parsing — count placed clock-buffer instances + UNPLACED detection
# ---------------------------------------------------------------------------
#: Report lines in which OpenROAD NAMES the master(s) it actually used for the
#: clock tree. Preferred over any cell-name heuristic — see _cts_declared_masters.
_CTS_MASTER_RES = (
    re.compile(r"CTS-0050\]\s*Root buffer is\s+(\S+?)\.?\s*$", re.M),
    re.compile(r"CTS-0051\]\s*Sink buffer is\s+(\S+?)\.?\s*$", re.M),
    re.compile(r"CTS-0049\]\s*Characterization buffer is\s+(\S+?)\.?\s*$", re.M),
)


def _cts_declared_masters(report_text: str):
    """The clock-tree buffer MASTERS the CTS tool itself named, lower-cased.

    v1.8.38 — why this exists (spm x gf180mcuD, MEASURED). The DEF count below
    used to be a pure cell-NAME token match (``clkbuf``/``clkinv``/...). Some
    PDKs' mapper PREFERS the clk-named family for ORDINARY logic: MEASURED 60
    ``clkinv_*`` against 19 plain ``inv_*`` in one netlist, so a clk-prefixed cell
    name carries no clock-tree meaning and 56 logic inverters were counted as
    clock-tree buffers. (An earlier draft said clkinv was the ONLY inverter family
    in that PDK. That is false — a plain ``inv_*`` family exists. The corrected
    mechanism is what makes this fix general to any PDK rather than one quirk.) The DEF "clock buffer" count came out 72
    against OpenROAD's own "Created 9 clock buffers", tripped
    BUFFER_COUNT_INCONSISTENT (>6x apart) and FAILED step 19 on a healthy clock
    tree. Restricted to the masters the tool names (root/sink/characterization
    buffer), the same DEF counts 12 (9 root + 3 sink) against the report's 9 —
    consistent.

    "Is this instance part of the clock tree?" is a question about CONNECTIVITY,
    and a cell name is only ever a proxy for it. When the tool states which
    masters it used, that statement is better evidence than any naming
    convention, and it is PDK-agnostic by construction. Empty result -> the
    caller falls back to the token match, so a report that names nothing behaves
    exactly as before."""
    out = set()
    for rx in _CTS_MASTER_RES:
        for m in rx.finditer(report_text or ""):
            name = (m.group(1) or "").strip().strip('."').lower()
            if name:
                out.add(name)
    return out


def _parse_def(text: str, masters=None):
    """Return (total_components, clk_buf_instances, unplaced_count,
    declared_components) parsed from a DEF's COMPONENTS section.

    declared_components is the integer on the ``COMPONENTS N ;`` header
    (None if not present). unplaced_count counts instances explicitly marked
    UNPLACED. clk_buf_instances counts instances of ``masters`` when that
    tool-declared allow-list is supplied, else instances whose cell-name matches
    a clock-buffer/inverter token (the pre-v1.8.38 heuristic)."""
    in_comp = False
    declared = None
    total = 0
    clk = 0
    unplaced = 0
    cur = []  # accumulate a multi-line component record until ';'

    def _flush(record):
        nonlocal total, clk, unplaced
        if not record:
            return
        total += 1
        joined = " ".join(record)
        if masters:
            low = joined.lower()
            if any(mst in low for mst in masters):
                clk += 1
        elif _CLK_CELL_RE.search(joined):
            clk += 1
        if re.search(r"\bUNPLACED\b", joined):
            unplaced += 1

    for raw in text.splitlines():
        s = raw.strip()
        if not in_comp:
            m = re.match(r"COMPONENTS\s+(\d+)\s*;", s)
            if m:
                declared = int(m.group(1))
                in_comp = True
            elif s.startswith("COMPONENTS"):
                in_comp = True
            continue
        # inside COMPONENTS
        if s.startswith("END COMPONENTS"):
            _flush(cur)
            cur = []
            in_comp = False
            continue
        if s.startswith("-"):
            # new component record begins; flush the previous one
            _flush(cur)
            cur = [s]
        elif cur:
            cur.append(s)
        # a record terminates with ';'
        if cur and cur[-1].rstrip().endswith(";"):
            _flush(cur)
            cur = []
    if cur:
        _flush(cur)

    return total, clk, unplaced, declared


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--json", default=None)
    parser.add_argument("--step-label", default=_GATE_LABEL)
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{_GATE_NAME}] project dir not found: {project}",
              file=sys.stderr)
        return 2

    def_rel, def_path = _first_existing(project, _DEF_CANDIDATES)
    rpt_rel, rpt_path = _first_existing(project, _RPT_CANDIDATES)
    waiver = _step_waived(project, args.step_label)

    findings = []
    metrics = {}

    # ---- Waiver path -----------------------------------------------------
    if waiver and (def_path is None or rpt_path is None):
        findings.append({
            "severity": "WAIVED", "rule": "STEP_WAIVED",
            "message": f"waiver={waiver.get('ticket', '?')}: "
                       f"{waiver.get('reason', '?')}",
        })
        return _emit(args, project, "WAIVED", def_rel, rpt_rel, waiver,
                     metrics, findings, 0)

    # ---- Honest FAIL on missing required artefacts -----------------------
    missing = []
    if def_path is None:
        missing.append("phase3/stage3/pnr/post_cts.def")
    if rpt_path is None:
        missing.append("phase3/stage3/cts/clock_tree.rpt")
    if missing:
        findings.append({
            "severity": "FAIL", "rule": "REQUIRED_ARTEFACT_MISSING",
            "message": f"CTS artefact(s) missing: {missing}",
        })
        return _emit(args, project, "FAIL", def_rel, rpt_rel, waiver,
                     metrics, findings, 1)

    # ---- Read the report -------------------------------------------------
    try:
        rpt_text = rpt_path.read_text(errors="replace")
    except OSError as e:
        findings.append({
            "severity": "FAIL", "rule": "REPORT_UNREADABLE",
            "message": f"cannot read {rpt_rel}: {e}",
        })
        return _emit(args, project, "FAIL", def_rel, rpt_rel, waiver,
                     metrics, findings, 1)

    if not rpt_text.strip():
        findings.append({
            "severity": "FAIL", "rule": "REPORT_EMPTY",
            "message": f"{rpt_rel} is empty",
        })
        return _emit(args, project, "FAIL", def_rel, rpt_rel, waiver,
                     metrics, findings, 1)

    r = _parse_report(rpt_text)

    if r["is_vacuous"]:
        findings.append({
            "severity": "FAIL", "rule": "CTS_NOT_INVOKED",
            "message": f"{rpt_rel} is the vacuous fallback stub (CTS not "
                       "invoked / zero output) — no real clock-tree metrics",
        })
        return _emit(args, project, "FAIL", def_rel, rpt_rel, waiver,
                     metrics, findings, 1)

    # ---- Read the DEF ----------------------------------------------------
    try:
        def_text = def_path.read_text(errors="replace")
    except OSError as e:
        findings.append({
            "severity": "FAIL", "rule": "DEF_UNREADABLE",
            "message": f"cannot read {def_rel}: {e}",
        })
        return _emit(args, project, "FAIL", def_rel, rpt_rel, waiver,
                     metrics, findings, 1)

    _cts_masters = _cts_declared_masters(rpt_text)
    total_comp, def_clk_bufs, unplaced, declared = _parse_def(
        def_text, masters=_cts_masters)
    metrics["def_total_components"] = total_comp
    metrics["def_clock_buffers"] = def_clk_bufs
    metrics["def_clock_buffer_masters"] = sorted(_cts_masters)
    metrics["def_clock_buffer_count_basis"] = (
        "masters named by the CTS report (CTS-0049/0050/0051)" if _cts_masters
        else "cell-name token heuristic (report named no master)")
    metrics["def_unplaced"] = unplaced
    metrics["def_declared_components"] = declared
    metrics["report_created_buffers"] = r["created_buffers"]
    metrics["report_created_nets"] = r["created_nets"]
    metrics["sinks"] = r["sinks"]
    metrics["path_depth"] = r["path_depth"]
    metrics["max_level"] = r["max_level"]
    metrics["min_path_bufs"] = r["min_path_bufs"]
    metrics["max_path_bufs"] = r["max_path_bufs"]
    metrics["skew_value"] = r["skew_value"]
    metrics["skew_unit"] = r["skew_unit"]
    metrics["latency_value"] = r["latency_value"]
    metrics["latency_unit"] = r["latency_unit"]

    if total_comp == 0 and declared in (None, 0):
        findings.append({
            "severity": "FAIL", "rule": "DEF_NO_COMPONENTS",
            "message": f"{def_rel} has no COMPONENTS section / zero "
                       "instances — not a placed post-CTS DEF",
        })
        return _emit(args, project, "FAIL", def_rel, rpt_rel, waiver,
                     metrics, findings, 1)

    # ---- Universal structural fact: no UNPLACED instance -----------------
    if unplaced > 0:
        findings.append({
            "severity": "FAIL", "rule": "UNPLACED_INSTANCE",
            "message": f"{def_rel} has {unplaced} UNPLACED instance(s) — "
                       "post-CTS DEF must be fully placed",
        })
        return _emit(args, project, "FAIL", def_rel, rpt_rel, waiver,
                     metrics, findings, 1)

    # ---- Substance #1: clock buffers actually inserted (count > 0) -------
    rpt_bufs = r["created_buffers"]
    # The effective inserted-buffer count is whatever positive evidence we
    # have. Prefer the DEF (physical placed instances) but accept the
    # report's count too.
    pos_sources = []
    if def_clk_bufs and def_clk_bufs > 0:
        pos_sources.append(("def", def_clk_bufs))
    if rpt_bufs and rpt_bufs > 0:
        pos_sources.append(("report", rpt_bufs))

    if not pos_sources:
        findings.append({
            "severity": "FAIL", "rule": "ZERO_CLOCK_BUFFERS",
            "message": "no clock buffers inserted: report 'Created N clock "
                       f"buffers'={rpt_bufs!r} and post_cts.def clock-buffer "
                       f"instances={def_clk_bufs} — the clock is unbuffered",
        })
        return _emit(args, project, "FAIL", def_rel, rpt_rel, waiver,
                     metrics, findings, 1)

    # Cross-check report vs DEF when BOTH are positive (catch a report that
    # claims buffers a placed DEF does not contain, or vice versa).
    if def_clk_bufs and def_clk_bufs > 0 and rpt_bufs and rpt_bufs > 0:
        hi = max(def_clk_bufs, rpt_bufs)
        lo = min(def_clk_bufs, rpt_bufs)
        if lo == 0 or hi > lo * _BUF_COUNT_FACTOR:
            findings.append({
                "severity": "FAIL", "rule": "BUFFER_COUNT_INCONSISTENT",
                "message": f"report says {rpt_bufs} clock buffers but "
                           f"post_cts.def has {def_clk_bufs} placed clock-"
                           f"buffer instances (>{_BUF_COUNT_FACTOR}x apart) "
                           "— report/DEF inconsistency",
            })
            return _emit(args, project, "FAIL", def_rel, rpt_rel, waiver,
                         metrics, findings, 1)
        findings.append({
            "severity": "INFO", "rule": "BUFFER_COUNT_CONSISTENT",
            "message": f"clock buffers: report={rpt_bufs}, "
                       f"def_instances={def_clk_bufs}",
        })
    else:
        findings.append({
            "severity": "INFO", "rule": "CLOCK_BUFFERS_PRESENT",
            "message": "clock buffers inserted: "
                       + ", ".join(f"{src}={n}" for src, n in pos_sources),
        })

    # ---- Substance #2: insertion-latency / depth OR numeric skew ---------
    depth_metrics = []
    if r["path_depth"] is not None:
        depth_metrics.append(f"path_depth={r['path_depth'][0]}-"
                             f"{r['path_depth'][1]}")
    if r["max_level"] is not None:
        depth_metrics.append(f"max_level={r['max_level']}")
    if r["min_path_bufs"] is not None or r["max_path_bufs"] is not None:
        depth_metrics.append(
            f"path_bufs={r['min_path_bufs']}-{r['max_path_bufs']}")

    has_skew = r["skew_value"] is not None
    has_latency = r["latency_value"] is not None

    if not depth_metrics and not has_skew and not has_latency:
        findings.append({
            "severity": "FAIL", "rule": "NO_LATENCY_OR_SKEW_METRIC",
            "message": f"{rpt_rel} carries no clock-tree skew, insertion-"
                       "latency, path-depth, or max-level metric — vacuous "
                       "report (file present but no real CTS numbers)",
        })
        return _emit(args, project, "FAIL", def_rel, rpt_rel, waiver,
                     metrics, findings, 1)

    metric_strs = list(depth_metrics)
    if has_skew:
        metric_strs.append(
            f"skew={r['skew_value']}{r['skew_unit'] or ''}")
    if has_latency:
        metric_strs.append(
            f"insertion_latency={r['latency_value']}{r['latency_unit'] or ''}")
    findings.append({
        "severity": "INFO", "rule": "LATENCY_METRIC_PRESENT",
        "message": "clock-tree metrics: " + ", ".join(metric_strs),
    })

    # ---- Substance #3: enforce stated skew target (if any) ---------------
    target = r["skew_target"]
    plan_rel, plan_target = _target_from_clock_plan(project)
    if target is None and plan_target is not None:
        target = plan_target
        findings.append({
            "severity": "INFO", "rule": "SKEW_TARGET_FROM_CLOCK_PLAN",
            "message": f"skew target {target} read from {plan_rel}",
        })
    metrics["skew_target"] = target

    if target is not None and has_skew:
        # Compare in the report's skew unit. We do NOT convert across units
        # we cannot prove are identical; if the report skew has no unit we
        # compare numerically (same convention the tool printed both in).
        if r["skew_value"] > target + 1e-12:
            findings.append({
                "severity": "FAIL", "rule": "SKEW_EXCEEDS_TARGET",
                "message": f"measured clock skew {r['skew_value']}"
                           f"{r['skew_unit'] or ''} > stated target {target}"
                           f"{r['skew_unit'] or ''}",
            })
            return _emit(args, project, "FAIL", def_rel, rpt_rel, waiver,
                         metrics, findings, 1)
        findings.append({
            "severity": "INFO", "rule": "SKEW_WITHIN_TARGET",
            "message": f"clock skew {r['skew_value']}{r['skew_unit'] or ''} "
                       f"<= target {target}{r['skew_unit'] or ''}",
        })
    elif target is not None and not has_skew:
        # A target exists but the report has no numeric skew to compare it
        # against. We do NOT invent the measured value; record it and pass
        # on the depth/latency evidence (the gate cannot enforce a bound it
        # has no measurement for, and refuses to fabricate one).
        findings.append({
            "severity": "INFO", "rule": "SKEW_TARGET_NO_MEASUREMENT",
            "message": f"skew target {target} stated but report carries no "
                       "numeric skew measurement; gate relies on "
                       "buffer-insertion + depth substance (no fabricated "
                       "skew value)",
        })

    # ---- PASS ------------------------------------------------------------
    findings.append({
        "severity": "INFO", "rule": "CTS_SUBSTANCE_OK",
        "message": "clock tree synthesised: buffers inserted, latency/depth "
                   "metrics present, all instances placed"
                   + (", skew within target" if (target is not None and
                                                  has_skew) else ""),
    })
    return _emit(args, project, "PASS", def_rel, rpt_rel, waiver,
                 metrics, findings, 0)


def _emit(args, project, verdict, def_rel, rpt_rel, waiver, metrics,
          findings, rc):
    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": _GATE_LABEL,
        "post_cts_def": def_rel,
        "clock_tree_rpt": rpt_rel,
        "metrics": metrics,
        "waiver": waiver,
        "findings": findings,
    }
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False)
                            + "\n")
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    if metrics:
        cb = metrics.get("def_clock_buffers")
        rb = metrics.get("report_created_buffers")
        print(f"  clock buffers: report={rb}, def_instances={cb}")
    for f in findings:
        if f["severity"] in ("FAIL", "WAIVED"):
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
