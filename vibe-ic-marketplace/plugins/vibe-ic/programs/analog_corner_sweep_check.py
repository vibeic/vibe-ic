#!/usr/bin/env python3
"""analog_corner_sweep_check.py — deterministic gate for PVT corner coverage

Validates that analog block corner sweep results cover sufficient PVT
space and all specs pass across corners.

For each analog/<block>/corner_results.json, checks:
  1. Minimum 9 corners (3 process × 3 temps)
  2. No missing results (results_found == total_corners)
  3. All spec_results entries pass (no status: "FAIL")

Self-skips when:
  - No analog/*/corner_results.json files found

Usage:
    python3 analog_corner_sweep_check.py <project_dir>
    python3 analog_corner_sweep_check.py <project_dir> --json reports/gates/analog_corners.json

Exit codes:
    0 = PASS: corner_results.json was read for at least one block and the
        PVT coverage + spec results in it are sufficient
    1 = FAIL (insufficient corners or spec violation)
    2 = VACUOUS: nothing was examined — no analog/ directory, or no
        analog/*/corner_results.json at all. #521: both used to be rc 0, so a
        PVT-coverage gate that read no corner was credited in the plain PASS
        tier. Also rc 2 for an IO / parse error.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional
import _path_layout as _pl
import _vacuous_exit as _vx
import _analog_a_check_common as _acc
from _analog_stub_marker import is_stub_json  # v1.6.177 (#72 P1-6)
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

MIN_CORNERS = 9


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "analog_corner_sweep_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _load_json(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return None


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()

    analog_dir = _pl.analog_dir(project)
    if not analog_dir.is_dir():
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG_DIR",
            severity="INFO",
            message="No analog/ directory; skipping corner sweep check",
        ))
        result.summary = {"skipped": True, "reason": "no_analog_dir"}
        return result

    corner_files = sorted(analog_dir.glob("*/corner_results.json"))

    if not corner_files:
        result.findings.append(Finding(
            rule="SKIP_NO_CORNER_DATA",
            severity="INFO",
            message="No analog/*/corner_results.json files found; skipping",
        ))
        result.summary = {"skipped": True, "reason": "no_corner_data"}
        return result

    blocks_checked = 0
    blocks_pass = 0
    blocks_stub = 0   # v1.6.177 (#72 P1-6)
    blocks_derived = 0  # v0.2.68 (#438a)
    blocks_structure_only: list = []
    block_details = []

    for cf in corner_files:
        block_name = cf.parent.name
        blocks_checked += 1
        data = _load_json(cf)

        if data is None:
            result.findings.append(Finding(
                rule="CORNER_PARSE_ERROR",
                severity="ERROR",
                message=f"Cannot parse {cf.relative_to(project)}",
                file=str(cf.relative_to(project)),
            ))
            result.passed = False
            continue

        # v1.6.177 (#72 P1-6) — honor deterministic-stub marker:
        # PASS_WITH_STUB tier instead of FAIL on insufficient
        # corners. Stub schemas use the 3-corner shape (tt/ss/ff)
        # to demonstrate flow, not to assert real PVT coverage.
        if is_stub_json(data):
            blocks_stub += 1
            blocks_pass += 1
            result.findings.append(Finding(
                rule="CORNER_SWEEP_STUB_ACCEPTED",
                severity="INFO",
                message=(f"Block '{block_name}': deterministic-stub "
                         f"corner_results accepted (PASS_WITH_STUB tier)"),
                file=str(cf.relative_to(project)),
            ))
            block_details.append({"block": block_name, "pass": True,
                                   "stub": True})
            continue

        # v1.6.228 — when `total_corners` is absent, derive from
        # len(corners[]). analog_real_corner_sweep.py (v1.6.222)
        # emits `corners: [{...}]` without the legacy summary fields.
        total = data.get("total_corners")
        if total is None:
            corners_list = data.get("corners")
            total = len(corners_list) if isinstance(corners_list, list) else 0
        found = data.get("results_found", total)

        if total < MIN_CORNERS:
            result.findings.append(Finding(
                rule="INSUFFICIENT_CORNERS",
                severity="ERROR",
                message=(
                    f"Block '{block_name}': only {total} corners "
                    f"(minimum {MIN_CORNERS} required = 3 process × 3 temps)"
                ),
                file=str(cf.relative_to(project)),
            ))
            result.passed = False
            block_details.append({"block": block_name, "pass": False,
                                  "reason": "insufficient_corners",
                                  "total": total, "min": MIN_CORNERS})
            continue

        if found < total:
            result.findings.append(Finding(
                rule="MISSING_CORNER_RESULTS",
                severity="ERROR",
                message=(
                    f"Block '{block_name}': {found}/{total} corner results "
                    f"present ({total - found} missing)"
                ),
                file=str(cf.relative_to(project)),
            ))
            result.passed = False
            block_details.append({"block": block_name, "pass": False,
                                  "reason": "missing_results",
                                  "found": found, "total": total})
            continue

        # ORGANIC-20260606 #438(a) — executed-vs-derived accounting. A
        # corner is DERIVED when it says so (simulator_run=false,
        # _provenance=DERIVED, or a non-empty derived_from field — the
        # last catches the legacy mislabel where every corner carried
        # simulator_run=true while derived_from admitted the scaling).
        # A sweep with fewer executed corners than MIN_CORNERS cannot
        # claim a full PVT sweep: tier downgrades, counts are surfaced.
        # All-derived (zero executed) is fabricated coverage → FAIL.
        corners_list = data.get("corners") if isinstance(
            data.get("corners"), list) else []
        derived_n = sum(
            1 for c in corners_list if isinstance(c, dict)
            and (c.get("simulator_run") is False
                 or str(c.get("_provenance", "")).upper() == "DERIVED"
                 or bool(c.get("derived_from"))))
        executed_n = (len(corners_list) - derived_n) if corners_list else None
        if corners_list and executed_n == 0:
            result.findings.append(Finding(
                rule="ALL_CORNERS_DERIVED",
                severity="ERROR",
                message=(f"Block '{block_name}': all {len(corners_list)} "
                         f"corners are arithmetic derivations — no corner "
                         f"was simulated; derived data is not PVT "
                         f"coverage (#438a)"),
                file=str(cf.relative_to(project)),
            ))
            result.passed = False
            block_details.append({"block": block_name, "pass": False,
                                  "reason": "all_corners_derived",
                                  "corners_executed": 0,
                                  "corners_derived": derived_n})
            continue

        spec_results = data.get("spec_results", [])
        failed_specs = [s for s in spec_results
                        if isinstance(s, dict) and s.get("status") == "FAIL"]

        if failed_specs:
            for fs in failed_specs:
                spec_name = fs.get("spec", fs.get("name", "?"))
                corner = fs.get("corner", "?")
                result.findings.append(Finding(
                    rule="SPEC_FAIL_AT_CORNER",
                    severity="ERROR",
                    message=(
                        f"Block '{block_name}': spec '{spec_name}' FAIL "
                        f"at corner {corner}"
                    ),
                    file=str(cf.relative_to(project)),
                ))
            result.passed = False
            block_details.append({"block": block_name, "pass": False,
                                  "reason": "spec_fail",
                                  "failed_count": len(failed_specs),
                                  "total_corners": total})
            continue

        mc_yield = data.get("mc_yield_pct")
        if mc_yield is not None and mc_yield < 95.0:
            result.findings.append(Finding(
                rule="LOW_MC_YIELD",
                severity="ERROR",
                message=(
                    f"Block '{block_name}': Monte Carlo yield {mc_yield:.1f}% "
                    f"(minimum 95% required)"
                ),
                file=str(cf.relative_to(project)),
            ))
            result.passed = False
            block_details.append({"block": block_name, "pass": False,
                                  "reason": "low_mc_yield",
                                  "mc_yield_pct": mc_yield})
            continue

        # ── WHAT THE SWEEP SWEPT ──────────────────────────────────────────
        # THE RULE, with no tool or block name in it: a gate that certifies a
        # measurement must read what was measured, and an artefact that
        # declines to say what it contains must not certify.
        #
        # This gate counts corners and grades specs; both are true of a
        # library nominal exactly as they are of a design sized to its spec,
        # and until this branch it said the same `[PASS]` for either. Ranked
        # so that disclosure is never the expensive answer: an artefact that
        # names a library default certifies in its own tier, and one that
        # names nothing does not certify at all.
        content = _acc.classify_design_content(data.get("design_content"))
        if content == _acc.CONTENT_UNDISCLOSED:
            result.findings.append(Finding(
                rule="CORNER_SUBJECT_UNDECLARED",
                severity="ERROR",
                message=(f"Block '{block_name}': {total} corners and every "
                         f"spec clean, and the artefact records no answer to "
                         f"what circuit produced them (`design_content` "
                         f"{data.get('design_content')!r}). Naming a library "
                         f"default certifies in its own tier; declining to "
                         f"answer does not, or saying nothing would cost less "
                         f"than saying so."),
                file=str(cf.relative_to(project)),
            ))
            result.passed = False
            block_details.append({"block": block_name, "pass": False,
                                  "reason": "design_content_undeclared",
                                  "total_corners": total})
            continue

        blocks_pass += 1
        if content == _acc.CONTENT_STRUCTURE_ONLY:
            blocks_structure_only.append(block_name)
            result.findings.append(Finding(
                rule="CORNER_SWEEP_STRUCTURE_ONLY",
                severity="WARNING",
                message=(f"Block '{block_name}': {total} corners are real "
                         f"measurements OF A LIBRARY TOPOLOGY — the artefact "
                         f"records that its circuit class came from a topology "
                         f"library and that no bound input reached any device "
                         f"parameter. Not missing (re-running produces the "
                         f"same artefact) and not a design-bound pass."),
                file=str(cf.relative_to(project)),
            ))
        if derived_n:
            # #438(a): tier-relevant disclosure — executed base sims are
            # genuine and PASS, but the block must never read as a fully
            # EXECUTED PVT sweep.
            blocks_derived += 1
            result.findings.append(Finding(
                rule="CORNER_SWEEP_DERIVED_DISCLOSED",
                severity="WARNING",
                message=(f"Block '{block_name}': {executed_n} executed / "
                         f"{derived_n} derived corner(s) — fewer than "
                         f"{MIN_CORNERS} executed corners cannot claim a "
                         f"full PVT sweep (#438a)"),
                file=str(cf.relative_to(project)),
            ))
        result.findings.append(Finding(
            rule="CORNER_SWEEP_OK",
            severity="INFO",
            message=(
                f"Block '{block_name}': {total} corners, all specs pass"
                + (f" ({executed_n} executed / {derived_n} derived)"
                   if corners_list else "")
                + (f", MC yield {mc_yield:.1f}%" if mc_yield is not None else "")
            ),
        ))
        block_details.append({"block": block_name, "pass": True,
                              "total_corners": total,
                              "corners_executed": executed_n,
                              "corners_derived": derived_n
                              if corners_list else None})

    # v1.6.177 (#72 P1-6) — verdict tier.
    # v0.2.68 (#438a) — PASS_WITH_DERIVED_CORNERS tier: passing blocks
    # whose PVT grid is partly arithmetic derivation never present as a
    # plain executed-sweep PASS.
    verdict_tier = "PASS"
    if result.passed and blocks_stub and blocks_stub == blocks_checked:
        verdict_tier = "PASS_WITH_STUB"
    elif result.passed and blocks_stub:
        verdict_tier = "PASS_WITH_STUB_PARTIAL"
    elif result.passed and blocks_structure_only:
        # Ahead of the derived tier on purpose: "which circuit" outranks "how
        # many of its corners were arithmetic". A sweep of a library nominal
        # is not this design's sweep however many corners it executed.
        verdict_tier = "PASS_STRUCTURE_ONLY"
    elif result.passed and blocks_derived:
        verdict_tier = "PASS_WITH_DERIVED_CORNERS"

    result.summary = {
        "skipped": False,
        "blocks_checked": blocks_checked,
        "blocks_pass": blocks_pass,
        "blocks_stub": blocks_stub,
        "blocks_with_derived_corners": blocks_derived,  # #438(a)
        "blocks_structure_only": len(blocks_structure_only),
        "structure_only_blocks": blocks_structure_only,
        "blocks_fail": blocks_checked - blocks_pass,
        "min_corners_required": MIN_CORNERS,
        "details": block_details,
        "pass": result.passed,
        "verdict_tier": verdict_tier,
    }
    return result


def main(argv: list = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)

    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(Path(args.json), out)

    # #521 — routed from the gate's OWN `summary["skipped"]`, never from text.
    skipped = _vx.summary_is_skipped(result.summary)
    reason = _vx.skip_reason(result.summary)

    so_blocks = (result.summary or {}).get("structure_only_blocks") or []
    if not args.json:
        # The tier travels on the verdict WORD — `pass_token` is the seam
        # `_vacuous_exit` already provides for it — so a reader of the one
        # line can tell a design's sweep from a library topology's.
        print(_vx.verdict_line(
            "analog_corner_sweep_check", result.passed, skipped, reason,
            pass_token=((result.summary or {}).get("verdict_tier") or "PASS")))
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.passed and skipped:
        _vx.announce_vacuous(result.program, reason)
    # LAST, SHORT, and on every path — the disclosure the flow auditor reads
    # from a fixed-width tail of this stream, whatever the verdict was.
    if so_blocks:
        names = ", ".join(str(b) for b in so_blocks)
        if len(names) > 60:
            names = f"{names[:57]}..."
        print(f"{_acc.STRUCTURE_ONLY_TOKEN} {len(so_blocks)} "
              f"corner_results.json artefact(s) ({names}) came from a library "
              f"default, not a bound input [analog_corner_sweep_check]",
              file=sys.stderr)
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
