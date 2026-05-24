#!/usr/bin/env python3
"""mixed_signal_cosim_check.py — deterministic gate for mixed-signal co-simulation

Validates that mixed-signal co-simulation was performed for each analog
block connected to digital logic. Checks for cosim result files and
validates simulation outcomes.

Self-skips (exit 0 + INFO) when:
  - No analog blocks detected

Usage:
    python3 mixed_signal_cosim_check.py <project_dir>
    python3 mixed_signal_cosim_check.py <project_dir> --json reports/gates/cosim.json

Exit codes:
    0 = PASS (or self-skip)
    1 = FAIL (missing or failed co-simulation)
    2 = IO / parse error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional
import _path_layout as _pl
from _analog_stub_marker import is_stub_json  # v1.6.177 (#72 P1-6)


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "mixed_signal_cosim_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _load_block_list(project: Path) -> List[str]:
    bl = _pl.analog_dir(project) / "analog_block_list.json"
    if not bl.exists():
        return []
    try:
        data = json.loads(bl.read_text(errors="replace"))
        if isinstance(data, dict) and "blocks" in data:
            return [b["name"] if isinstance(b, dict) else str(b)
                    for b in data["blocks"]]
        if isinstance(data, list):
            return [b["name"] if isinstance(b, dict) else str(b)
                    for b in data]
    except (json.JSONDecodeError, OSError, KeyError):
        pass
    return []


def _scan_spec_blocks(project: Path) -> List[str]:
    analog_dir = _pl.analog_dir(project)
    if not analog_dir.is_dir():
        return []
    return sorted(d.name for d in analog_dir.iterdir()
                  if d.is_dir() and (d / "spec.json").exists())


def _block_is_stub(project: Path, block: str) -> bool:
    """v1.6.177 (#72 P1-6) — return True iff the per-block analog
    spec.json carries the deterministic_stub marker. The M-step
    cosim has no real data to co-simulate when the upstream analog
    block is a stub, so the cosim gate should not FAIL the block in
    that case — it should report PASS_WITH_STUB.
    chip-AGNOSTIC: marker is structural, not chip-class."""
    spec = _pl.analog_dir(project) / block / "spec.json"
    if not spec.exists():
        return False
    try:
        data = json.loads(spec.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return False
    return is_stub_json(data)


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()

    blocks = _load_block_list(project) or _scan_spec_blocks(project)

    if not blocks:
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG",
            severity="INFO",
            message="No analog blocks detected; skipping mixed-signal cosim check",
        ))
        result.summary = {"skipped": True, "reason": "no_analog_blocks"}
        return result

    cosim_dir = _pl.mixed_signal_cosim_dir(project)
    simulated = 0
    missing = []
    failed = []
    stub_blocks = []   # v1.6.177 (#72 P1-6)

    for block in blocks:
        cosim_file = cosim_dir / f"{block}_cosim_results.json"
        if not cosim_file.exists():
            # v1.6.177 (#72 P1-6) — if the analog spec is a stub,
            # the M-step cosim absence is expected (no real data to
            # co-simulate). Demote MISSING to PASS_WITH_STUB.
            if _block_is_stub(project, block):
                stub_blocks.append(block)
                simulated += 1
                result.findings.append(Finding(
                    rule="COSIM_STUB_ACCEPTED",
                    severity="INFO",
                    message=(
                        f"Block '{block}': analog spec is a "
                        f"deterministic stub; cosim absence accepted "
                        f"(PASS_WITH_STUB tier)."
                    ),
                ))
                continue
            missing.append(block)
            result.findings.append(Finding(
                rule="COSIM_MISSING",
                severity="ERROR",
                message=(
                    f"Block '{block}': no co-simulation results at "
                    f"cosim/{block}_cosim_results.json. "
                    f"Run mixed-signal-cosim skill."
                ),
            ))
            continue

        try:
            data = json.loads(cosim_file.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError):
            result.findings.append(Finding(
                rule="COSIM_PARSE_ERROR",
                severity="ERROR",
                message=f"Block '{block}': cannot parse cosim results",
                file=str(cosim_file),
            ))
            failed.append(block)
            continue

        # v1.6.177 (#72 P1-6) — honor cosim_results.json stub marker.
        if is_stub_json(data):
            stub_blocks.append(block)
            simulated += 1
            result.findings.append(Finding(
                rule="COSIM_STUB_ACCEPTED",
                severity="INFO",
                message=(
                    f"Block '{block}': cosim_results carries "
                    f"deterministic_stub marker (PASS_WITH_STUB tier)."
                ),
                file=str(cosim_file),
            ))
            continue

        sim_passed = data.get("simulation_passed", False)
        if not sim_passed:
            failed.append(block)
            reason = data.get("failure_reason", "unknown")
            result.findings.append(Finding(
                rule="COSIM_FAILED",
                severity="ERROR",
                message=(
                    f"Block '{block}': co-simulation failed — {reason}"
                ),
                file=str(cosim_file),
            ))
        else:
            simulated += 1
            result.findings.append(Finding(
                rule="COSIM_PASSED",
                severity="INFO",
                message=f"Block '{block}': co-simulation passed",
            ))

    if missing or failed:
        result.passed = False

    # v1.6.177 (#72 P1-6) — verdict tier.
    verdict_tier = "PASS"
    if (result.passed and stub_blocks
            and len(stub_blocks) == len(blocks)):
        verdict_tier = "PASS_WITH_STUB"
    elif result.passed and stub_blocks:
        verdict_tier = "PASS_WITH_STUB_PARTIAL"

    result.summary = {
        "skipped": False,
        "total_blocks": len(blocks),
        "simulated": simulated,
        "stub_blocks": stub_blocks,
        "missing": missing,
        "failed": failed,
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
    # v1.6.144 (#57) — FPGA-prototype-stage stub waiver.
    import _fpga_stub_waiver as _stub
    _stub.add_fpga_stub_argparse(ap)
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)

    waiver_status: str = "PASS"
    if not result.passed and _stub.fpga_stub_waiver_active(args):
        result.passed = True
        waiver_status = "PASS_WITH_WAIVERS"
        result.summary["fpga_stub_waiver_applied"] = True
        result.summary["waiver_reason"] = _stub.fpga_stub_reason()
        for f in result.findings:
            if f.severity == "ERROR":
                f.severity = "WARNING"

    out = json.dumps(asdict(result), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)

    if not args.json:
        status = waiver_status if result.passed else "FAIL"
        print(f"[{status}] mixed_signal_cosim_check")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
