#!/usr/bin/env python3
"""sdd_atpg_run.py — REAL Small-Delay-Defect (SDD) ATPG grade. FUSES OpenSTA
per-path SLACK (the timing margin) with the DT2 per-path LOC SAT sensitisation
so that at-speed transition-fault detection is graded by the TIGHTNESS of the
path it is detected through — exactly what a commercial SDD flow
(TetraMAX/Tessent) reports, and the tier DT1 (logic-graded TDF) and DT2
(binary path-delay coverage) each stop short of.

THE SDD INSIGHT (why binary "is the transition detected" is not enough):
  the QUALITY of a transition-fault detection depends on the SLACK of the path
  through which it is detected. A fault detected only through a HIGH-slack
  (loose) path is a WEAK detection — a small delay defect there is masked by the
  timing margin and never fails at-speed. A fault detected through a LOW-slack
  (tight) path is a STRONG detection — a small delay is observable at the rated
  clock. Commercial SDD ATPG therefore targets detection through the SMALLEST-
  slack path so a defect that only matters on a critical path is caught.

──────────────────────────────────────────────────────────────────────────
THE FUSION (OpenSTA slack ⊗ DT2 per-path SAT — NO new miter, NO name map):

  We already have BOTH ingredients and DT2 already binds them SOUNDLY at the
  scan-flop level (the ONLY name-space common to the routed-netlist STA world
  and the gate-levelised SAT world — internal combinational cell names differ
  between the two and are deliberately NEVER matched):

    1. SLACK  — DT2's OpenSTA K-longest enumeration gives, per timing-critical
       path, its endpoint, its launch/capture EDGE (→ the STR/STF transition it
       tests) and its real post-layout SLACK. The K LONGEST paths ARE the K
       LOWEST-slack ones — the tightest, most delay-defect-prone.
    2. SENSITISATION — DT2's per-path launch-off-capture SAT proves a REAL
       2-pattern launches that path's start transition AND captures a resulting
       transition at its critical endpoint (nr_verdict=='DET'). A false / held /
       PI-launched path is 'not sensitisable' and never credited.

  SDD reuses those DT2 per-path records verbatim (import `run_pdf_atpg` + the
  pure helpers; it does NOT duplicate the miter) and adds ONE layer: grade each
  sensitisable timing-critical path by its slack against a DISCLOSED small-delay
  MARGIN window.

  Per SDD fault record (one per DT2 top-K path — the capture-endpoint transition
  it tests, at exactly that path's slack):
    detecting_path_slack_ns = the STA slack of the path (the timing margin).
    sensitizable            = DT2 nr_verdict == 'DET' (a real 2-pattern exists).
    bucket:
      STRONG  — sensitizable AND slack <= margin  (a small (<=margin) delay
                defect on this tight path IS observable at-speed).
      WEAK    — sensitizable AND slack  > margin  (a small delay is masked by
                the margin; only a LARGER (>=slack) defect would fail).
      UNDETECTED-AT-SPEED — not sensitizable (no at-speed 2-pattern).

  DISCLOSED margin window: margin_ns = margin_fraction × clock_period
  (default fraction 0.10 = the largest delay we still call "small", i.e. a path
  with slack within 10 % of the period catches a small delay). NEVER a silent
  knob — margin_fraction AND margin_ns are both written into the JSON.

  slack-weighted SDD coverage = mean over graded paths of a slack-detectability
  WEIGHT w(slack): 1.0 for STRONG (catches a defect as small as the margin),
  margin/slack ∈ (0,1) for WEAK (only covers the fraction of the small-delay
  window a defect >= slack would need), 0 for undetected. A slack-rich design
  scores LOW — the honest statement that its detections cover only LARGE defects.

──────────────────────────────────────────────────────────────────────────
FALSE-CLEAN-PROOF (the crux — the sibling gate `sdd_coverage_check.py` is
AUTHORITATIVE and INDEPENDENTLY re-derives every bucket from the slack list):
  * A path is NEVER 'strong' unless its RECORDED detecting-path slack is <=
    the RECOMPUTED margin (margin_ns == period × fraction, re-derived by the
    gate — a doctored margin_ns is caught). A high-slack path marked 'strong'
    FAILS the gate.
  * A path is NEVER counted (strong OR weak) unless it is sensitizable — a real
    DT2 SAT 2-pattern. undetected/aborted are excluded from the numerator.
  * The reported slack-weighted / strong coverage may not EXCEED the gate's
    independent recount.
  This is a DESCRIPTIVE, anti-fabrication grade — NOT a coverage floor: a
  slack-rich design HONESTLY reports low SDD coverage and that is a PASS.

HONEST RESIDUAL (written into the JSON): this grades each detection by the
real STA path SLACK (the timing margin) — it is NOT a per-defect-SIZE timing-
simulation credit against a defect-size distribution the way a full commercial
SDD flow is (which SPICE-grades each pattern for the smallest catchable defect
per defect-size statistics). The slack IS the sound at-speed margin (small
defect masked ⟺ slack large), and the tightest-path attribution is exact at the
scan-flop endpoint; per-intermediate-cell defect-size grading is a finer,
deferred tier. The transition-fault POPULATION (DT1) is folded in as context
with a SOUND design-wide lower bound (no fault can be strong if NO sensitizable
path is within margin), never over-credited.

Usage:
    python3 sdd_atpg_run.py <project_dir> --clock clk \\
        [--margin-fraction 0.10] [--margin-ns 1.0] \\
        [--dt2-json reports/phase2/dft/path_delay_coverage.json] \\
        [--dt1-json reports/phase2/dft/transition_coverage.json] \\
        [ ... same --sta-netlist/--spef/--sdc/--liberty/--k as DT2 ... ] \\
        [--json OUT]

Exit 0 = SDD grade produced + self-consistent (any coverage number, incl low),
         OR NOT_APPLICABLE (DT2 N/A: no timing model / no scan / no LOC path).
Exit 1 = the SDD grade could not be produced (DT2 unavailable and un-runnable).
Exit 2 = usage / IO error.

chip-AGNOSTIC — no design-specific knowledge, no vendor/SKU/IC literals.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import _path_layout as _pl  # type: ignore
except Exception:  # pragma: no cover
    _pl = None

# Reuse DT2's OpenSTA K-longest infra + per-path LOC SAT (import its pure
# helpers; do NOT duplicate the miter). DT2 in turn reuses DT1's cut/gate-
# levelise/SAT-verdict helpers, so the whole stack is shared.
try:
    import path_delay_fault_atpg_run as _pdf  # type: ignore
except Exception:  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import path_delay_fault_atpg_run as _pdf  # type: ignore

try:
    import transition_fault_atpg_run as _tdf  # type: ignore  (DT1 population)
except Exception:  # pragma: no cover
    _tdf = None  # type: ignore


_PROGRAM = "sdd_atpg_run"
_VERSION = "1.0.0"

# DISCLOSED small-delay window as a fraction of the clock period. A path whose
# slack is within this fraction of the period catches a "small" (<= that size)
# delay defect at-speed → STRONG. Chosen, DISCLOSED, configurable. NEVER silent.
SDD_MARGIN_FRACTION_DEFAULT = 0.10
# Sanity cap on the disclosed fraction — a "small-delay" window larger than the
# whole period is not a small delay; the gate enforces this too.
SDD_MARGIN_FRACTION_CAP = 1.0

_DISCLOSURE = (
    "SDD (small-delay-defect) grade: each DT2 top-K sensitisable timing path is "
    "graded by its REAL OpenSTA post-layout SLACK against a DISCLOSED small-"
    "delay margin (margin_ns = margin_fraction × clock_period). STRONG = "
    "sensitisable AND slack <= margin (a small delay is observable at-speed); "
    "WEAK = sensitisable AND slack > margin (masked by margin); UNDETECTED-AT-"
    "SPEED = no real LOC 2-pattern. slack-weighted coverage = mean slack-"
    "detectability weight (1 strong, margin/slack weak, 0 undetected). This is "
    "STA-slack-graded, NOT a per-defect-SIZE timing-simulation credit like a "
    "full commercial SDD flow — disclosed. A slack-rich design HONESTLY scores "
    "low (its detections cover only LARGE defects); this is descriptive, not a "
    "floor. The gate re-derives every bucket from the slack list (false-clean-"
    "proof: a high-slack path marked strong FAILS)."
)


# ══════════════════════════════════════════════════════════════════════════
# PURE helpers — SDD slack bucketing / weighting / math (unit-tested; no IO)
# ══════════════════════════════════════════════════════════════════════════

def sdd_margin_ns(period_ns, margin_fraction):
    """The DISCLOSED "small delay" detectable window in ns = margin_fraction ×
    clock_period. A path whose slack <= this margin catches a small (<= margin)
    delay defect at-speed. Returns None if the period is unknown. Pure."""
    if (period_ns is None or period_ns <= 0
            or margin_fraction is None or margin_fraction < 0):
        return None
    return round(float(period_ns) * float(margin_fraction), 6)


def transition_of_edge(end_edge: str) -> str:
    """The capture-endpoint transition a path tests: a RISING capture (`^`)
    tests a slow-to-rise (STR) fault; a FALLING capture (`v`) a slow-to-fall
    (STF). Pure."""
    return "STR" if end_edge == "^" else "STF"


def slack_bucket(slack, sensitizable: bool, margin_ns) -> str:
    """Fold (detecting-path slack, sensitizable, margin) into an SDD bucket —
    the SINGLE classification the gate independently re-derives. Pure.

      not sensitizable / slack None / margin None -> 'undetected_at_speed'
      sensitizable AND slack <= margin            -> 'strong'
      sensitizable AND slack  > margin            -> 'weak'

    A path is NEVER 'strong' unless it is detected through a path whose slack
    is within the small-delay window (<= margin) — the false-clean invariant."""
    if not sensitizable or slack is None or margin_ns is None:
        return "undetected_at_speed"
    return "strong" if float(slack) <= float(margin_ns) else "weak"


def sdd_weight(slack, sensitizable: bool, margin_ns) -> float:
    """Slack-detectability weight in [0,1] — how SMALL a delay defect this
    detection can catch. Pure, monotone non-increasing in slack.

      undetected                 -> 0.0
      slack <= margin (STRONG)   -> 1.0  (catches a defect as small as margin,
                                          incl. a slack<=0 timing violation)
      slack  > margin (WEAK)     -> margin/slack in (0,1) — only catches a
                                    LARGER (>= slack) defect; the fraction of
                                    the small-delay window it covers."""
    if (not sensitizable or slack is None or margin_ns is None
            or float(margin_ns) <= 0):
        return 0.0
    s = float(slack)
    if s <= float(margin_ns):
        return 1.0
    return round(float(margin_ns) / s, 6)


def grade_path_records(dt2_records: list, margin_ns) -> list:
    """Map each DT2 top-K path record to an SDD per-fault record: its detecting-
    path slack (the STA timing margin of that path), whether it is sensitizable
    (a REAL LOC 2-pattern — DT2 nr_verdict=='DET'), and its slack bucket +
    weight. Reuses DT2's SAT verdict verbatim — builds NO miter. Pure.
    chip-AGNOSTIC."""
    out = []
    for r in dt2_records:
        if not isinstance(r, dict):
            continue
        loc = bool(r.get("loc_testable"))
        sens = loc and (r.get("nr_verdict") == "DET")
        slack = r.get("slack")
        out.append({
            "source": "sta_path",
            "idx": r.get("idx"),
            "startpoint": r.get("startpoint"),
            "endpoint": r.get("endpoint"),
            "direction": transition_of_edge(r.get("end_edge")),
            "arrival_ns": r.get("arrival"),
            "detecting_path_slack_ns": slack,
            "loc_testable": loc,
            "sensitizable": sens,
            "robust": (r.get("robust_verdict") == "DET"),
            "nr_verdict": r.get("nr_verdict"),
            "robust_verdict": r.get("robust_verdict"),
            "sdd_bucket": slack_bucket(slack, sens, margin_ns),
            "sdd_weight": sdd_weight(slack, sens, margin_ns),
        })
    return out


def sdd_coverage_math(sdd_records: list, margin_ns, period_ns) -> dict:
    """Recompute the SDD grade from per-fault records (independently redone by
    the gate). Pure. chip-AGNOSTIC.

    Denominator = graded (loc_testable timing paths). Within graded:
      strong / weak / undetected_at_speed        per-bucket counts
      sdd_binary_strong_coverage_pct  = strong / graded (the at-speed hit)
      sdd_slack_weighted_coverage_pct = mean(sdd_weight) × 100 — reflects that a
        slack-rich design's detections cover only LARGE defects (a low %)."""
    graded = [r for r in sdd_records if r.get("loc_testable")]
    strong = [r for r in graded if r.get("sdd_bucket") == "strong"]
    weak = [r for r in graded if r.get("sdd_bucket") == "weak"]
    undet = [r for r in graded if r.get("sdd_bucket") == "undetected_at_speed"]
    n = len(graded)
    strong_pct = (100.0 * len(strong) / n) if n else None
    wsum = sum(float(r.get("sdd_weight") or 0.0) for r in graded)
    weighted_pct = (100.0 * wsum / n) if n else None
    with_slack = [r for r in graded
                  if r.get("detecting_path_slack_ns") is not None]
    tightest = (min(with_slack, key=lambda r: r["detecting_path_slack_ns"])
                if with_slack else None)
    return {
        "graded_faults": n,
        "strong": len(strong),
        "weak": len(weak),
        "undetected_at_speed": len(undet),
        "sdd_binary_strong_coverage_pct": (round(strong_pct, 4)
                                           if strong_pct is not None else None),
        "sdd_slack_weighted_coverage_pct": (round(weighted_pct, 4)
                                            if weighted_pct is not None else None),
        "margin_ns": margin_ns,
        "clock_period_ns": period_ns,
        "tightest_path": ({
            "startpoint": tightest["startpoint"],
            "endpoint": tightest["endpoint"],
            "direction": tightest["direction"],
            "detecting_path_slack_ns": tightest["detecting_path_slack_ns"],
            "arrival_ns": tightest.get("arrival_ns"),
            "sdd_bucket": tightest["sdd_bucket"],
        } if tightest else None),
    }


def design_small_delay_bound(sdd_records: list, margin_ns) -> dict:
    """SOUND design-wide lower bound: the tightest sensitizable path's slack is
    a lower bound on the detecting-path slack of EVERY transition fault (no
    fault can be detected through a path tighter than the design's tightest
    sensitizable one). If that minimum slack > margin, NO fault can be strong →
    every logic-detected transition fault is small-delay-WEAK at-speed. Pure."""
    sens = [r["detecting_path_slack_ns"] for r in sdd_records
            if r.get("sensitizable")
            and r.get("detecting_path_slack_ns") is not None]
    if not sens:
        return {"min_sensitizable_slack_ns": None,
                "any_sensitizable_path_within_margin": False}
    mn = min(sens)
    return {
        "min_sensitizable_slack_ns": mn,
        "any_sensitizable_path_within_margin": (margin_ns is not None
                                                and mn <= float(margin_ns)),
    }


def transition_population_summary(dt1_faults: list) -> dict:
    """Summarise the DT1 transition-fault population as SDD context. Pure.
      total, logic_detected (DT1 'DET'), redundant (DT1 'RED'), aborted."""
    total = len(dt1_faults)
    det = sum(1 for f in dt1_faults if f.get("verdict") == "DET")
    red = sum(1 for f in dt1_faults if f.get("verdict") == "RED")
    return {"total": total, "logic_detected": det, "redundant": red,
            "aborted": total - det - red}


# ══════════════════════════════════════════════════════════════════════════
# DT2 / DT1 acquisition (consume the emitted report, else produce it — real)
# ══════════════════════════════════════════════════════════════════════════

def _load_json(path: Path):
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def _resolve_report(project: Path, override, name: str):
    cands = []
    if override:
        cands.append(Path(override) if Path(override).is_absolute()
                     else project / override)
    else:
        if _pl is not None:
            cands.append(_pl.report_path(project, f"dft/{name}"))
        cands.append(project / f"reports/phase2/dft/{name}")
        cands.append(project / f"reports/dft/{name}")
    return next((p for p in cands if p.is_file()), None)


def _acquire_dt2(project: Path, args, pdk_dir) -> tuple[dict | None, str]:
    """Consume an existing DT2 path_delay_coverage.json, else RUN DT2's real
    producer (`_pdf.run_pdf_atpg`) to create one. Returns (dt2_blob, note)."""
    path = _resolve_report(project, args.dt2_json, "path_delay_coverage.json")
    if path is not None:
        blob = _load_json(path)
        if blob is not None:
            return blob, f"reused existing DT2 report: {path.name}"
    # Produce it (real engine — same inputs DT2 would take).
    _ec, blob = _pdf.run_pdf_atpg(
        project, netlist_rel=args.netlist, cut_rel=args.cut_netlist,
        flat_rel=args.flat_core, sta_netlist=args.sta_netlist, sdc=args.sdc,
        spef=args.spef, liberty=args.liberty, top=args.top, clock=args.clock,
        dff_cells=args.dff_cells, k=args.k, floor=0.0,
        timing_fraction=_pdf.TIMING_FRACTION_DEFAULT, pdk_dir=pdk_dir,
        timeout=args.timeout)
    return blob, "produced DT2 report via path_delay_fault_atpg_run.run_pdf_atpg"


def _acquire_dt1(project: Path, args, pdk_dir) -> tuple[list, str]:
    """Best-effort DT1 transition-fault population for SDD context. Consume an
    existing transition_coverage.json; if absent, try to produce it. Population
    context only — SDD's slack grade does not depend on it. Returns
    (fault_list, note)."""
    path = _resolve_report(project, args.dt1_json, "transition_coverage.json")
    if path is not None:
        blob = _load_json(path)
        if blob is not None and isinstance(blob.get("fault_list"), list):
            return blob["fault_list"], f"reused existing DT1 report: {path.name}"
    if _tdf is not None and not args.no_run_dt1:
        try:
            _ec, blob = _tdf.run_tdf_atpg(
                project, netlist_rel=args.netlist, cut_rel=args.cut_netlist,
                liberty=args.liberty, top=args.top, clock=args.clock,
                dff_cells=args.dff_cells, floor=0.0,
                max_faults=args.max_faults, pdk_dir=pdk_dir,
                timeout=args.timeout)
            fl = blob.get("fault_list")
            if isinstance(fl, list):
                return fl, "produced DT1 population via transition_fault_atpg_run"
        except Exception as exc:  # pragma: no cover
            return [], f"DT1 population unavailable ({exc})"
    return [], "DT1 population unavailable (no report; run skipped)"


# ══════════════════════════════════════════════════════════════════════════
# Orchestration
# ══════════════════════════════════════════════════════════════════════════

def run_sdd_atpg(project: Path, args, pdk_dir) -> tuple[int, dict]:
    """Full SDD producer. Returns (exit_code, report_dict). chip-AGNOSTIC."""
    margin_fraction = min(max(float(args.margin_fraction), 0.0),
                          SDD_MARGIN_FRACTION_CAP)
    base = {
        "program": _PROGRAM, "version": _VERSION,
        "tool": "OpenSTA slack (DT2 K-longest) ⊗ vibeic/yosys LOC SAT "
                "(DT2 per-path sensitisation)",
        "fault_model": "small-delay-defect (slack-graded at-speed transition)",
        "clock": args.clock, "top": args.top,
        "margin_fraction": margin_fraction,
        "margin_fraction_cap": SDD_MARGIN_FRACTION_CAP,
        "disclosure": _DISCLOSURE,
    }

    dt2, dt2_note = _acquire_dt2(project, args, pdk_dir)
    base["dt2_source"] = dt2_note
    if dt2 is None:
        base.update({"verdict": "ERROR", "status": "ERROR",
                     "reasons": ["could not obtain DT2 path-delay coverage "
                                 "(path_delay_coverage.json absent and its "
                                 "producer could not run) — SDD needs DT2's "
                                 "per-path slack + SAT records"]})
        return 1, base

    # DT2 self-skip (no timing model / no scan / no LOC path) ⇒ SDD N/A.
    if dt2.get("verdict") == "NOT_APPLICABLE":
        base.update({
            "verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
            "scan_flops": dt2.get("scan_flops", 0),
            "reasons": ["DT2 path-delay coverage is NOT_APPLICABLE (no timing "
                        "model / no scan flops / no LOC-launchable path) — SDD "
                        "at-speed slack grading not applicable: "
                        + "; ".join(dt2.get("reasons", [])[:1])]})
        return 0, base
    if dt2.get("verdict") == "ERROR":
        base.update({"verdict": "ERROR", "status": "ERROR",
                     "reasons": ["DT2 producer recorded ERROR: "
                                 + "; ".join(dt2.get("reasons", [])[:2])]})
        return 1, base

    records = dt2.get("path_records")
    if not isinstance(records, list) or not records:
        base.update({"verdict": "NOT_APPLICABLE", "status": "NOT_APPLICABLE",
                     "reasons": ["DT2 produced no per-path records — no timing-"
                                 "critical path to SDD-grade"]})
        return 0, base

    period_ns = dt2.get("clock_period_ns")
    margin_ns = (float(args.margin_ns) if args.margin_ns is not None
                 else sdd_margin_ns(period_ns, margin_fraction))
    base.update({
        "clock_period_ns": period_ns,
        "margin_ns": margin_ns,
        "margin_ns_derivation": ("explicit --margin-ns"
                                 if args.margin_ns is not None
                                 else "margin_fraction × clock_period"),
        "k_selected": dt2.get("k_selected"),
        "dt2_longest_arrival_ns": dt2.get("longest_arrival_ns"),
    })

    sdd_records = grade_path_records(records, margin_ns)
    cov = sdd_coverage_math(sdd_records, margin_ns, period_ns)
    base.update(cov)
    base["sdd_records"] = sdd_records

    # SOUND per-fault-population framing (context; grade does not depend on it).
    dt1_faults, dt1_note = _acquire_dt1(project, args, pdk_dir)
    base["dt1_source"] = dt1_note
    pop = transition_population_summary(dt1_faults)
    bound = design_small_delay_bound(sdd_records, margin_ns)
    base["transition_population"] = pop
    base["transition_population_sdd_bound"] = bound
    if pop["total"] and not bound["any_sensitizable_path_within_margin"]:
        base["transition_population_sdd_note"] = (
            f"the tightest sensitizable path slack "
            f"({bound['min_sensitizable_slack_ns']} ns) exceeds the small-delay "
            f"margin ({margin_ns} ns), so NO transition fault can be strong: all "
            f"{pop['logic_detected']} logic-detected faults are small-delay-WEAK "
            f"at-speed (a small delay is masked by >= "
            f"{bound['min_sensitizable_slack_ns']} ns of margin), and the "
            f"{pop['redundant']} redundant faults are undetected-at-speed too")

    base.update({
        "verdict": "PASS", "status": "PASS", "reasons": [],
        "note": ("descriptive SDD grade — a low coverage on a slack-rich design "
                 "is the HONEST result, not a failure (no floor). The gate "
                 "verifies self-consistency (anti-fabrication)."),
    })
    return 0, base


def _augment_defaults(project: Path, args) -> int:
    """chip-AGNOSTIC auto-discovery for omitted DT2/DT1 inputs (mirrors DT2) —
    only needed if a report must be produced. Returns 0 or a nonzero errno."""
    def _first_rel(pat: str, fallback: str) -> str:
        hits = sorted(project.glob(pat))
        return str(hits[0].relative_to(project)) if hits else fallback

    if args.sta_netlist is None:
        args.sta_netlist = _first_rel("phase3/stage3/pnr/*_pnr.v",
                                      "phase3/stage3/pnr/pnr.v")
    if args.spef is None:
        args.spef = _first_rel("phase3/stage3/extracted/*.spef",
                               "phase3/stage3/extracted/design.spef")
    if args.netlist is None:
        # Prefer a genuinely TECH-MAPPED netlist (shared resolver with DT1/DT2);
        # a generic `$_DFF_*` netlist is skipped so the SDD grade never inherits
        # a 0-pair cut from the pre-map netlist.
        args.netlist = _tdf.discover_mapped_netlist(project)
    if args.liberty is None:
        args.liberty = _first_rel("input/pdk/liberty/*typ*.lib",
                                  "input/pdk/liberty/typ.lib")
    if args.top is None:
        stem = Path(args.sta_netlist).stem
        if stem.endswith("_pnr"):
            args.top = stem[: -len("_pnr")]
        else:
            _nl = project / args.sta_netlist
            _m = (re.search(r"(?m)^\s*module\s+([A-Za-z_]\w*)",
                            _nl.read_text(errors="replace"))
                  if _nl.is_file() else None)
            if not _m:
                # top only strictly needed if a report must be produced; leave
                # None and let the producer error clearly if it is reached.
                args.top = stem or "top"
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Small-delay-defect (SDD) ATPG — slack-weighted at-speed "
                    "transition-fault grade fusing OpenSTA path slack with the "
                    "DT2 per-path LOC SAT sensitisation")
    p.add_argument("project_dir")
    p.add_argument("--clock", required=True, help="Functional clock name")
    p.add_argument("--margin-fraction", type=float,
                   default=SDD_MARGIN_FRACTION_DEFAULT,
                   help=f"DISCLOSED small-delay window as a fraction of the "
                        f"clock period (default {SDD_MARGIN_FRACTION_DEFAULT}; "
                        f"capped at {SDD_MARGIN_FRACTION_CAP}). A path with "
                        f"slack <= fraction×period is STRONG (small delay "
                        f"observable at-speed)")
    p.add_argument("--margin-ns", type=float, default=None,
                   help="Explicit small-delay margin in ns (overrides "
                        "--margin-fraction; DISCLOSED)")
    p.add_argument("--dt2-json", default=None,
                   help="Existing DT2 path_delay_coverage.json to reuse "
                        "(auto-discovered under reports/phase2/dft/)")
    p.add_argument("--dt1-json", default=None,
                   help="Existing DT1 transition_coverage.json for population "
                        "context (auto-discovered under reports/phase2/dft/)")
    p.add_argument("--no-run-dt1", action="store_true",
                   help="Do not run DT1 if its report is absent (skip the "
                        "population context rather than launch the heavy run)")
    # DT2/DT1 pass-through inputs (used only if a report must be produced).
    p.add_argument("--sta-netlist", default=None)
    p.add_argument("--spef", default=None)
    p.add_argument("--sdc", default="phase3/stage3/pnr/constraint.sdc")
    p.add_argument("--liberty", default=None)
    p.add_argument("--netlist", default=None)
    p.add_argument("--cut-netlist", default="phase2/stage2/dft/cut_netlist.v")
    p.add_argument("--flat-core", default="phase2/stage2/dft/tdf/flat_core.v")
    p.add_argument("--top", default=None)
    p.add_argument("--dff-cells", default=None)
    p.add_argument("--k", type=int, default=_pdf.DEFAULT_K,
                   help=f"K longest paths to grade (DISCLOSED; default "
                        f"{_pdf.DEFAULT_K}; passed to DT2 if it must run)")
    p.add_argument("--max-faults", type=int, default=_tdf.DEFAULT_MAX_FAULTS
                   if _tdf is not None else 400,
                   help="DT1 population sample size (if DT1 must run)")
    p.add_argument("--pdk-dir", default=None,
                   help="PDK dir mounted at /pdk (default ../shared_pdk)")
    p.add_argument("--timeout", type=int, default=1800)
    p.add_argument("--json", default=None,
                   help="Report path (default reports/phase2/dft/"
                        "sdd_coverage.json)")
    args = p.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"{_PROGRAM}: not a directory: {project}", file=sys.stderr)
        return 2

    _augment_defaults(project, args)

    pdk_dir = None
    if args.pdk_dir:
        pdk_dir = Path(args.pdk_dir).resolve()
    else:
        cand = project.parent / "shared_pdk"
        if cand.exists():
            pdk_dir = cand

    exit_code, report = run_sdd_atpg(project, args, pdk_dir)

    if args.json:
        json_path = Path(args.json)
    elif _pl is not None:
        json_path = _pl.report_path(project, "dft/sdd_coverage.json")
    else:
        json_path = project / "reports/phase2/dft/sdd_coverage.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    v = report.get("verdict")
    print(f"{_PROGRAM}: verdict={v} "
          f"strong={report.get('strong')} weak={report.get('weak')} "
          f"undetected_at_speed={report.get('undetected_at_speed')} "
          f"graded={report.get('graded_faults')} "
          f"strong_cov={report.get('sdd_binary_strong_coverage_pct')}% "
          f"slack_weighted_cov={report.get('sdd_slack_weighted_coverage_pct')}% "
          f"margin_ns={report.get('margin_ns')}")
    if exit_code != 0 and v != "NOT_APPLICABLE":
        print(f"  (see {json_path})", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
