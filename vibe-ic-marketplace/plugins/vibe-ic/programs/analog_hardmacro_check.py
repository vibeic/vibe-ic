#!/usr/bin/env python3
"""analog_hardmacro_check.py — deterministic gate for analog hardmacro deliverables

Validates that each analog block has a complete hardmacro package under
hardmacro/<block>/ containing:
  - <block>.gds  (non-empty)
  - <block>.lef  (contains MACRO and PIN keywords)
  - <block>.lib  (contains cell keyword)
  - <block>.v    (contains module definition)

Self-skips (exit 0 + INFO) when:
  - No analog blocks detected (no analog_block_list.json or empty)

Usage:
    python3 analog_hardmacro_check.py <project_dir>
    python3 analog_hardmacro_check.py <project_dir> --json reports/gates/hardmacro.json

Exit codes:
    0 = PASS (or self-skip)
    1 = FAIL (missing or corrupt hardmacro files)
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
from _analog_stub_marker import is_stub_text  # v1.6.177 (#72 P1-6)


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "analog_hardmacro_check"
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
    found = []
    for spec in sorted(analog_dir.glob("*/spec.json")):
        found.append(spec.parent.name)
    return found


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()

    blocks = _load_block_list(project) or _scan_spec_blocks(project)

    if not blocks:
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG",
            severity="INFO",
            message="No analog blocks detected; skipping hardmacro check",
        ))
        result.summary = {"skipped": True, "reason": "no_analog_blocks"}
        return result

    hardmacro_dir = _pl.hardmacro_dir(project)
    complete = 0
    stub_blocks = 0   # v1.6.177 (#72 P1-6)
    incomplete = []

    for block in blocks:
        block_dir = hardmacro_dir / block
        missing = []

        gds = block_dir / f"{block}.gds"
        lef = block_dir / f"{block}.lef"
        lib = block_dir / f"{block}.lib"
        verilog = block_dir / f"{block}.v"

        # v1.6.177 (#72 P1-6) — honor deterministic-stub marker. If
        # ANY of the three textual artefacts (LEF/LIB/V) carries
        # the marker, the whole hardmacro is treated as a stub and
        # the GDS-presence + LEF/LIB content requirements are
        # relaxed (A7 stub deliberately omits .gds — replacing it
        # with a real one is the A5 magic-layout step's job).
        # chip-AGNOSTIC: marker is structural, not chip-class.
        stub_match = False
        for cand in (lef, lib, verilog):
            try:
                if cand.exists() and is_stub_text(
                        cand.read_text(errors="replace")):
                    stub_match = True
                    break
            except OSError:
                continue
        if stub_match:
            stub_blocks += 1
            complete += 1
            result.findings.append(Finding(
                rule="HARDMACRO_STUB_ACCEPTED",
                severity="INFO",
                message=(f"Block '{block}' hardmacro is a "
                         f"deterministic stub (PASS_WITH_STUB tier); "
                         f"GDS + content requirements relaxed."),
            ))
            continue

        if not gds.exists() or gds.stat().st_size == 0:
            missing.append(f"{block}.gds")

        if not lef.exists():
            missing.append(f"{block}.lef")
        elif lef.exists():
            try:
                text = lef.read_text(errors="replace")
                if "MACRO" not in text:
                    result.findings.append(Finding(
                        rule="HARDMACRO_LEF_NO_MACRO",
                        severity="ERROR",
                        message=f"Block '{block}': LEF file missing MACRO keyword",
                        file=str(lef),
                    ))
                    missing.append(f"{block}.lef (no MACRO)")
                elif "PIN" not in text:
                    result.findings.append(Finding(
                        rule="HARDMACRO_LEF_NO_PIN",
                        severity="ERROR",
                        message=f"Block '{block}': LEF file missing PIN keyword",
                        file=str(lef),
                    ))
                    missing.append(f"{block}.lef (no PIN)")
            except OSError:
                missing.append(f"{block}.lef (unreadable)")

        if not lib.exists():
            missing.append(f"{block}.lib")
        elif lib.exists():
            try:
                text = lib.read_text(errors="replace")
                if "cell" not in text.lower():
                    result.findings.append(Finding(
                        rule="HARDMACRO_LIB_NO_CELL",
                        severity="ERROR",
                        message=f"Block '{block}': Liberty file missing cell definition",
                        file=str(lib),
                    ))
                    missing.append(f"{block}.lib (no cell)")
            except OSError:
                missing.append(f"{block}.lib (unreadable)")

        if not verilog.exists():
            missing.append(f"{block}.v")
        elif verilog.exists():
            try:
                text = verilog.read_text(errors="replace")
                if f"module" not in text:
                    result.findings.append(Finding(
                        rule="HARDMACRO_V_NO_MODULE",
                        severity="ERROR",
                        message=f"Block '{block}': Verilog file missing module definition",
                        file=str(verilog),
                    ))
                    missing.append(f"{block}.v (no module)")
            except OSError:
                missing.append(f"{block}.v (unreadable)")

        if missing:
            incomplete.append(block)
            result.findings.append(Finding(
                rule="HARDMACRO_INCOMPLETE",
                severity="ERROR",
                message=(
                    f"Block '{block}' hardmacro incomplete: "
                    f"missing {', '.join(missing)}"
                ),
            ))
        else:
            complete += 1
            result.findings.append(Finding(
                rule="HARDMACRO_COMPLETE",
                severity="INFO",
                message=f"Block '{block}' hardmacro complete (GDS+LEF+LIB+V)",
            ))

    if incomplete:
        result.passed = False

    # v1.6.177 (#72 P1-6) — verdict tier.
    total = len(blocks)
    verdict_tier = "PASS"
    if result.passed and stub_blocks and stub_blocks == total:
        verdict_tier = "PASS_WITH_STUB"
    elif result.passed and stub_blocks:
        verdict_tier = "PASS_WITH_STUB_PARTIAL"

    result.summary = {
        "skipped": False,
        "total_blocks": total,
        "complete": complete,
        "stub_blocks": stub_blocks,
        "incomplete": incomplete,
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

    # v1.6.144 (#57) — demote missing-per-block-artifact failures to
    # PASS_WITH_WAIVERS at the FPGA prototype stage. Same gate re-fires
    # without the waiver at phase3.foundry_handoff for tapeout signoff.
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
        print(f"[{status}] analog_hardmacro_check")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
