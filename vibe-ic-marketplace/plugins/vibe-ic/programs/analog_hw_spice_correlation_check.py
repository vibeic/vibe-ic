#!/usr/bin/env python3
"""analog_hw_spice_correlation_check.py — deterministic gate for HW-vs-SPICE correlation

Validates that hardware measurements (from scope / ADC / bench instruments)
correlate with SPICE simulation predictions within acceptable tolerance.

For each measurement in hw_measurements.json that has a matching SPICE
measurement in corner_results.json:
  - <10 % discrepancy → INFO (IDEAL — HW_SPICE_IDEAL)
  - ≤20 % discrepancy → INFO (acceptable)
  - >20 % discrepancy → WARNING
  - >30 % discrepancy → ERROR (model accuracy critical)

The IDEAL tier is INFO-only granularity: <10 % was already acceptable, so
adding it does NOT change the PASS/FAIL verdict.

Self-skips when:
  - No analog/ directory, or no analog/*/hw_measurements.json files found

Usage:
    python3 analog_hw_spice_correlation_check.py <project_dir>
    python3 analog_hw_spice_correlation_check.py <project_dir> --json reports/gates/hw_spice_corr.json

Exit codes:
    0 = PASS: bench data was read and every measurement correlates with its
        SPICE prediction inside tolerance
    1 = FAIL (critical discrepancy)
    2 = VACUOUS: nothing was examined — no analog/ directory, or no bench
        measurement at all, so no hardware number was correlated against any
        model. #521: both used to be rc 0, which is the shape that makes a
        simulation-only close read as a bench-verified one. Also rc 2 for an
        IO / parse error.
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
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "analog_hw_spice_correlation_check"
    version: str = "1.1.0"
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
            message="No analog/ directory; skipping HW-SPICE correlation check",
        ))
        result.summary = {"skipped": True, "reason": "no_analog_dir"}
        return result

    hw_files = sorted(analog_dir.glob("*/hw_measurements.json"))
    if not hw_files:
        result.findings.append(Finding(
            rule="SKIP_NO_HW_DATA",
            severity="INFO",
            message="No hw_measurements.json found; hardware verification not performed",
        ))
        result.summary = {"skipped": True, "reason": "no_hw_data"}
        return result

    total_compared = 0
    errors = 0
    ideal = 0
    max_discrepancy = 0.0

    for hw_path in hw_files:
        block = hw_path.parent.name
        hw_data = _load_json(hw_path)
        if not hw_data or "measurements" not in hw_data:
            result.findings.append(Finding(
                rule="HW_DATA_PARSE_ERROR",
                severity="WARNING",
                message=f"Cannot parse hw_measurements.json for block '{block}'",
                file=str(hw_path),
            ))
            continue

        corner_path = hw_path.parent / "corner_results.json"
        corner_data = _load_json(corner_path)

        spice_meas = {}
        if corner_data and "pvt_results" in corner_data:
            for _tag, meas in corner_data["pvt_results"].items():
                if isinstance(meas, dict):
                    for k, v in meas.items():
                        if k not in spice_meas:
                            spice_meas[k] = v

        spec_path = hw_path.parent / "spec.json"
        spec_data = _load_json(spec_path)
        spec_limits = {}
        if spec_data and "specs" in spec_data:
            spec_limits = spec_data["specs"]

        for name, hw_val in hw_data["measurements"].items():
            if not isinstance(hw_val, (int, float)):
                continue

            if name in spice_meas:
                spice_val = spice_meas[name]
                if spice_val == 0:
                    continue
                pct = abs(hw_val - spice_val) / abs(spice_val) * 100
                max_discrepancy = max(max_discrepancy, pct)
                total_compared += 1

                if pct > 30:
                    errors += 1
                    result.findings.append(Finding(
                        rule="HW_SPICE_CRITICAL_MISMATCH",
                        severity="ERROR",
                        message=(
                            f"Block '{block}' measurement '{name}': "
                            f"HW={hw_val} vs SPICE={spice_val} "
                            f"({pct:.1f}% discrepancy — model accuracy critical)"
                        ),
                    ))
                elif pct > 20:
                    result.findings.append(Finding(
                        rule="HW_SPICE_WARNING_MISMATCH",
                        severity="WARNING",
                        message=(
                            f"Block '{block}' measurement '{name}': "
                            f"HW={hw_val} vs SPICE={spice_val} "
                            f"({pct:.1f}% discrepancy)"
                        ),
                    ))
                elif pct < 10:
                    ideal += 1
                    result.findings.append(Finding(
                        rule="HW_SPICE_IDEAL",
                        severity="INFO",
                        message=(
                            f"Block '{block}' measurement '{name}': "
                            f"HW={hw_val} vs SPICE={spice_val} "
                            f"({pct:.1f}% — ideal correlation). OK."
                        ),
                    ))
                else:
                    result.findings.append(Finding(
                        rule="HW_SPICE_CORRELATED",
                        severity="INFO",
                        message=(
                            f"Block '{block}' measurement '{name}': "
                            f"HW={hw_val} vs SPICE={spice_val} "
                            f"({pct:.1f}% — within tolerance). OK."
                        ),
                    ))

            if name in spec_limits:
                lim = spec_limits[name]
                if isinstance(lim, dict):
                    lo = lim.get("min")
                    hi = lim.get("max")
                    if lo is not None and hw_val < lo:
                        errors += 1
                        result.findings.append(Finding(
                            rule="HW_BELOW_SPEC",
                            severity="ERROR",
                            message=(
                                f"Block '{block}' measurement '{name}': "
                                f"HW={hw_val} < spec min={lo}"
                            ),
                        ))
                    if hi is not None and hw_val > hi:
                        errors += 1
                        result.findings.append(Finding(
                            rule="HW_ABOVE_SPEC",
                            severity="ERROR",
                            message=(
                                f"Block '{block}' measurement '{name}': "
                                f"HW={hw_val} > spec max={hi}"
                            ),
                        ))

    if errors:
        result.passed = False

    # ORGANIC-20260606 #438(c): a COMPARISON gate cannot PASS having
    # compared NOTHING. hw_measurements.json existed (we are past the
    # self-skip) but zero HW/SPICE key overlaps were found — that is a
    # broken comparison, not a clean one.
    if total_compared == 0:
        result.passed = False
        result.findings.append(Finding(
            rule="HW_SPICE_ZERO_COMPARED",
            severity="ERROR",
            message=("hw_measurements.json present but 0 measurements "
                     "were compared against SPICE — a comparison gate "
                     "must FAIL (or self-skip), never PASS, with "
                     "items_compared==0 (#438c)"),
        ))

    ideal_pct = (ideal / total_compared * 100) if total_compared else 0.0

    result.summary = {
        "skipped": False,
        "hw_files_found": len(hw_files),
        "measurements_compared": total_compared,
        "max_discrepancy_pct": max_discrepancy,
        "ideal_count": ideal,
        "ideal_pct": ideal_pct,
        "errors": errors,
        "pass": result.passed,
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

    if not args.json:
        print(_vx.verdict_line("analog_hw_spice_correlation_check",
                               result.passed, skipped, reason))
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.passed and skipped:
        _vx.announce_vacuous(result.program, reason)
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
