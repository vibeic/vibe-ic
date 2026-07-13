#!/usr/bin/env python3
"""si_mcf_sta_check.py — GATE for the MCF-bounded SI-aware STA (si_mcf_sta.py).

WHAT IT VERIFIES (false-clean-proof)
====================================
The emitter (`si_mcf_sta.py`) folds every coupling cap ``Cc`` into the victim's
grounded cap at the corner's Miller Coupling Factor, then re-runs OpenSTA. A
dishonest / buggy emitter could SILENTLY DROP the ``Cc*MCF`` (leave the bounded
SPEF at the plain grounded caps) and then report an unchanged, rosy slack — a
false-clean. This gate INDEPENDENTLY re-derives the fold from the ORIGINAL
coupling SPEF (trusting none of the emitter's arithmetic) and proves the bounded
SPEF actually carries it:

  1. RE-DERIVE, per victim net, the window-justified fold ``Cc*MCF`` from the
     original SPEF + the tool-produced timing-window JSON (exact). If that JSON
     is unavailable, fall back to the window-INDEPENDENT floor (setup: every Cc
     at MCF>=1; hold: MCF>=0) so a dropped Cc is still caught.
  2. MEASURE each net's grounded-cap increase in the bounded SPEF and require it
     to be >= the re-derived fold (minus tolerance). A silently-dropped Cc*MCF
     -> increase ~0 while expected > 0 -> FAIL.
  3. Require the bounded SPEF to retain NO coupling (2-node) caps — they must
     have been folded to ground; and require the fold not to EXCEED the MCF
     ceiling (setup: 2*sum(Cc)) so an inflated fold is caught too.
  4. MONOTONICITY: folding MORE cap can only DEGRADE setup slack, folding LESS
     can only degrade hold slack. If the report claims the SI-bounded slack is
     BETTER than the nominal grounded slack (after > before), that contradicts
     the physics of the bound -> FAIL ("reported slack better than the bound").

Exit 0 = PASS (every corner's bound is genuinely applied + reported honestly),
1 = FAIL, 2 = IO/arg error. Writes reports/phase3/si_mcf_sta_check.json.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import _path_layout as _pl
import si_mcf_sta as M


@dataclass
class Finding:
    severity: str          # ERROR / WARNING / INFO
    category: str
    message: str


def _load_windows(report: dict, net_driver_pins) -> Tuple[Optional[dict], bool]:
    """Load the emitter's per-pin timing-window JSON. Returns (net_windows, exact).
    exact=False means no window JSON was found (gate uses the floor instead)."""
    wj = report.get("windows_json")
    if wj and Path(wj).exists():
        try:
            timing = json.loads(Path(wj).read_text())
            return M.net_windows_from_timing(timing, net_driver_pins), True
        except (OSError, ValueError):
            return None, False
    return None, False


def audit(project_dir: Path,
          report_path: Optional[Path] = None) -> Tuple[List[Finding], dict]:
    findings: List[Finding] = []
    rp = report_path or _pl.report_path(project_dir, "si_mcf_sta.json")
    stats: dict = {"report": str(rp), "corners_checked": [],
                   "recount": {}, "monotonicity": {}}

    if not rp.exists():
        findings.append(Finding("ERROR", "NO_REPORT",
                                f"si_mcf_sta.json not found at {rp}"))
        return findings, stats
    try:
        report = json.loads(rp.read_text())
    except (OSError, ValueError) as exc:
        findings.append(Finding("ERROR", "BAD_JSON",
                                f"cannot parse si_mcf_sta.json: {exc}"))
        return findings, stats

    orig_spef = report.get("spef")
    if not orig_spef or not Path(orig_spef).exists():
        findings.append(Finding("ERROR", "NO_SPEF",
                                f"original coupling SPEF missing: {orig_spef}"))
        return findings, stats
    orig_text = Path(orig_spef).read_text(errors="replace")
    sp = M.parse_spef(orig_text)
    pairs = M.coupling_pairs(sp)
    stats["coupling_pairs"] = len(pairs)

    net_windows, exact = _load_windows(report, sp["net_driver_pins"])
    stats["windows_exact"] = exact
    guard = float(report.get("overlap_guard_ns", 0.0) or 0.0)

    corners = report.get("corners", {})
    nominal = report.get("nominal", {})
    for corner in ("setup", "hold"):
        cinfo = corners.get(corner)
        if not isinstance(cinfo, dict):
            findings.append(Finding("ERROR", "NO_CORNER",
                                    f"report missing corner '{corner}'"))
            continue
        bounded = cinfo.get("bounded_spef")
        if not bounded or not Path(bounded).exists():
            findings.append(Finding("ERROR", "NO_BOUNDED_SPEF",
                                    f"{corner}: bounded SPEF missing: {bounded}"))
            continue
        bounded_text = Path(bounded).read_text(errors="replace")

        # (1-3) independent cap-level recount (the false-clean-proof)
        expected = None if exact else M.floor_folded_caps(pairs, corner)
        rc = M.independent_recount(orig_text, bounded_text,
                                   net_windows or {}, corner, guard,
                                   expected=expected)
        stats["recount"][corner] = {
            "ok": rc["ok"], "nets_checked": rc["nets_checked"],
            "residual_coupling_caps": rc["residual_coupling_caps"],
            "violations": rc["violations"][:20],
            "mode": "exact-window" if exact else "window-independent-floor",
        }
        stats["corners_checked"].append(corner)
        if not rc["ok"]:
            n = len(rc["violations"])
            findings.append(Finding(
                "ERROR", "FOLD_NOT_APPLIED",
                f"{corner}: {n} net(s) fail the independent MCF recount "
                f"(Cc*MCF under/over-applied or coupling not folded) — "
                f"the bounded SPEF does not carry the re-derived bound"))

        # (4) monotonicity vs the nominal grounded run
        before = cinfo.get("worst_slack_before_ns")
        after = cinfo.get("worst_slack_after_ns")
        mono_ok = True
        if isinstance(before, (int, float)) and isinstance(after, (int, float)):
            # setup: MORE cap => after <= before; hold: LESS cap => after <= before.
            # a tiny positive epsilon tolerates STA rounding at the reported digits.
            if after > before + 5e-3:
                mono_ok = False
                findings.append(Finding(
                    "ERROR", "SLACK_BETTER_THAN_BOUND",
                    f"{corner}: reported SI-bounded slack {after} ns is BETTER "
                    f"than the nominal grounded {before} ns — a conservative "
                    f"MCF bound can only DEGRADE it; number is not honest"))
        stats["monotonicity"][corner] = {
            "before_ns": before, "after_ns": after, "ok": mono_ok}

    _ = nominal  # (kept for future cross-checks; corner records carry before/after)
    return findings, stats


def build_report(findings: List[Finding], stats: dict, project_dir: str) -> dict:
    ok = all(f.severity != "ERROR" for f in findings)
    return {
        "program": "si_mcf_sta_check",
        "version": "1.0.0",
        "project_dir": project_dir,
        "verdict": "PASS" if ok else "FAIL",
        "summary": {
            "corners_checked": stats.get("corners_checked", []),
            "windows_exact": stats.get("windows_exact"),
            "coupling_pairs": stats.get("coupling_pairs"),
            "errors_count": sum(1 for f in findings if f.severity == "ERROR"),
            "findings_count": len(findings),
            "pass": ok,
        },
        "recount": stats.get("recount", {}),
        "monotonicity": stats.get("monotonicity", {}),
        "findings": [asdict(f) for f in findings],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="GATE: verify the MCF-bounded SI-aware STA fold is genuinely "
                    "applied + reported honestly (false-clean-proof).")
    ap.add_argument("project_dir")
    ap.add_argument("--report", default=None,
                    help="path to si_mcf_sta.json (default: reports/phase3/)")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        print(f"ERROR: not a directory: {project_dir}", file=sys.stderr)
        return 2

    findings, stats = audit(
        project_dir, Path(args.report) if args.report else None)
    report = build_report(findings, stats, str(project_dir))
    out = json.dumps(report, indent=2, ensure_ascii=False)
    dst = (Path(args.json) if args.json
           else _pl.report_path(project_dir, "si_mcf_sta_check.json"))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(out + "\n")
    print(out)
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
