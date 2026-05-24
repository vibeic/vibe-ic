#!/usr/bin/env python3
"""analog_flow_compliance_check.py — analog track compliance gate (A1-A8)

Validates that all 8 analog track steps have been completed for every
block listed in analog/analog_block_list.json:

  A1: analog/<block>/spec.json
  A2: analog/<block>/topology.md
  A3: analog/<block>/*.sp
  A4: analog/<block>/corner_results.json
  A5: analog/<block>/layout.mag OR analog/<block>/*.gds
  A6: analog/<block>/pre_vs_post.json
  A7: hardmacro/<block>/<block>.lef
  A8: cosim/<block>_cosim_results.json OR analog/<block>/hw_measurements.json

Steps may be waived via analog/waivers.json.

Self-skips (exit 0 + INFO) when:
  - No analog_block_list.json or empty block list

Usage:
    python3 analog_flow_compliance_check.py <project_dir>
    python3 analog_flow_compliance_check.py <project_dir> --json reports/gates/analog_compliance.json

Exit codes:
    0 = PASS (or self-skip)
    1 = FAIL (missing steps)
    2 = IO / parse error
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import _path_layout as _pl


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "analog_flow_compliance_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


ANALOG_STEPS = [
    ("A1", "Spec Extraction"),
    ("A2", "Topology Selection"),
    ("A3", "Netlist Generation"),
    ("A4", "Corner Sweep"),
    ("A5", "Analog Layout"),
    ("A6", "Post-Layout Resim"),
    ("A7", "Hardmacro Gen"),
    ("A8", "Co-Sim / HW Verify"),
]


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


def _load_waivers(project: Path) -> Set[Tuple[str, str]]:
    wf = _pl.analog_dir(project) / "waivers.json"
    if not wf.exists():
        return set()
    try:
        data = json.loads(wf.read_text(errors="replace"))
        waivers = data.get("analog_waivers", [])
        return {(w["block"], w["step"]) for w in waivers
                if isinstance(w, dict) and "block" in w and "step" in w}
    except (json.JSONDecodeError, OSError, KeyError):
        return set()


def _check_step(project: Path, block: str, step_id: str) -> bool:
    analog_dir = _pl.analog_dir(project) / block

    if step_id == "A1":
        return (analog_dir / "spec.json").exists()
    elif step_id == "A2":
        return (analog_dir / "topology.md").exists()
    elif step_id == "A3":
        return bool(list(analog_dir.glob("*.sp"))) if analog_dir.is_dir() else False
    elif step_id == "A4":
        return (analog_dir / "corner_results.json").exists()
    elif step_id == "A5":
        if not analog_dir.is_dir():
            return False
        return ((analog_dir / "layout.mag").exists() or
                bool(list(analog_dir.glob("*.gds"))))
    elif step_id == "A6":
        return (analog_dir / "pre_vs_post.json").exists()
    elif step_id == "A7":
        hm = _pl.hardmacro_dir(project) / block / f"{block}.lef"
        return hm.exists()
    elif step_id == "A8":
        cosim = _pl.mixed_signal_cosim_dir(project) / f"{block}_cosim_results.json"
        hw = analog_dir / "hw_measurements.json"
        return cosim.exists() or hw.exists()
    return False


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()

    blocks = _load_block_list(project)

    if not blocks:
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG",
            severity="INFO",
            message="No analog_block_list.json or empty; skipping analog flow compliance",
        ))
        result.summary = {"skipped": True, "reason": "no_analog_blocks"}
        return result

    waivers = _load_waivers(project)

    matrix: Dict[str, Dict[str, str]] = {}
    total_missing = 0

    for block in blocks:
        matrix[block] = {}
        for step_id, step_name in ANALOG_STEPS:
            if _check_step(project, block, step_id):
                matrix[block][step_id] = "PASS"
                result.findings.append(Finding(
                    rule=f"ANALOG_{step_id}_PASS",
                    severity="INFO",
                    message=f"Block '{block}' step {step_id} ({step_name}): PASS",
                ))
            elif (block, step_id) in waivers:
                matrix[block][step_id] = "WAIVED"
                result.findings.append(Finding(
                    rule=f"ANALOG_{step_id}_WAIVED",
                    severity="INFO",
                    message=f"Block '{block}' step {step_id} ({step_name}): WAIVED",
                ))
            else:
                matrix[block][step_id] = "MISSING"
                total_missing += 1
                result.findings.append(Finding(
                    rule=f"ANALOG_{step_id}_MISSING",
                    severity="ERROR",
                    message=(
                        f"Block '{block}' step {step_id} ({step_name}): MISSING. "
                        f"Run the corresponding skill or add a waiver."
                    ),
                ))

    if total_missing > 0:
        result.passed = False

    result.summary = {
        "skipped": False,
        "total_blocks": len(blocks),
        "total_steps": len(ANALOG_STEPS),
        "matrix": matrix,
        "total_missing": total_missing,
        "total_waived": sum(1 for b in matrix.values()
                           for s in b.values() if s == "WAIVED"),
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
        print(f"[{status}] analog_flow_compliance_check")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
