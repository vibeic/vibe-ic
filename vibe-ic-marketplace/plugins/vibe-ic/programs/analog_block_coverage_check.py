#!/usr/bin/env python3
"""analog_block_coverage_check.py — deterministic gate for analog block design coverage

Validates that every declared analog block has a corresponding design
directory under analog/<block>/ with the required deliverables:
  - spec.json (extracted spec from L1/L5)
  - *.sp (SPICE netlist)
  - corner_results.json (PVT corner sweep results)

The explicit analog/analog_block_list.json emitted by analog-spec-extract is
the authoritative roster when present.  The RTL module-name heuristic is a
fallback only when that list is absent.  Heuristic hits outside an explicit
roster are reported as WARNINGs because a digital product/top name can contain
an analog class token without itself being an analog implementation block.

ENFORCEMENT: blocking — missing deliverables on rostered blocks fail the
completion audit.  A heuristic-only hit outside an explicit roster is
ADVISORY and cannot fail the gate.

Self-skips when:
  - No analog modules detected in RTL AND no analog_block_list.json, or
  - A valid explicit analog_block_list.json declares no blocks

Usage:
    python3 analog_block_coverage_check.py <project_dir>
    python3 analog_block_coverage_check.py <project_dir> --json reports/gates/analog_coverage.json

Exit codes:
    0 = PASS: analog blocks were found and every one has its deliverables
    1 = FAIL (uncovered analog blocks)
    2 = VACUOUS: nothing was examined — this project declares no analog block
        at all, so there was no coverage to measure. #521: this used to be
        rc 0, which credited the gate in the plain PASS tier on 183 of the 200
        tracked project roots, including a mixed-signal design's own results
        directory. Also rc 2 for an IO / parse error on the argument.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional
import _path_layout as _pl
import _vacuous_exit as _vx
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


ANALOG_MODULE_PATTERNS = re.compile(
    r"(ldo|pll|vco|osc|oscillat|bandgap|bgr|adc|dac|comparator|"
    r"charge.?pump|bias|regulator|opamp|ota|tia)",
    re.IGNORECASE,
)


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "analog_block_coverage_check"
    version: str = "1.0.0"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _detect_analog_modules(project: Path) -> List[str]:
    rtl_dir = _pl.rtl_dir(project)
    if not rtl_dir.is_dir():
        return []

    found = set()
    module_re = re.compile(r"^\s*module\s+(\w+)", re.MULTILINE)

    for ext in ("*.v", "*.sv", "*.vh", "*.svh"):
        for f in rtl_dir.glob(ext):
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
            for m in module_re.finditer(text):
                name = m.group(1)
                if ANALOG_MODULE_PATTERNS.search(name):
                    found.add(name)

    return sorted(found)


def _load_block_list(project: Path) -> Optional[List[str]]:
    bl = _pl.analog_dir(project) / "analog_block_list.json"
    if not bl.exists():
        return None
    try:
        data = json.loads(bl.read_text(errors="replace"))
        if isinstance(data, dict) and "blocks" in data:
            data = data["blocks"]
        if not isinstance(data, list):
            return None
        return [b["name"] if isinstance(b, dict) else str(b)
                for b in data]
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return None


def run_audit(project: Path) -> AuditResult:
    result = AuditResult()

    rtl_modules = _detect_analog_modules(project)
    block_list_present = (
        _pl.analog_dir(project) / "analog_block_list.json"
    ).is_file()
    loaded_blocks = _load_block_list(project)
    explicit_blocks = loaded_blocks or []

    if block_list_present and loaded_blocks is None:
        result.passed = False
        result.findings.append(Finding(
            rule="ANALOG_BLOCK_LIST_INVALID",
            severity="ERROR",
            message=(
                "analog_block_list.json exists but is not readable as a JSON "
                "list or an object containing a blocks list; refusing to "
                "infer an authoritative roster."
            ),
        ))
        result.summary = {
            "skipped": False,
            "total_blocks": 0,
            "covered": 0,
            "uncovered": [],
            "from_rtl": rtl_modules,
            "from_block_list": [],
            "roster_source": "invalid_analog_block_list",
            "rtl_name_hints_not_in_block_list": [],
            "pass": False,
        }
        return result

    if block_list_present:
        all_blocks = sorted(set(explicit_blocks))
        ignored_rtl_hints = sorted(set(rtl_modules) - set(explicit_blocks))
    else:
        all_blocks = sorted(set(rtl_modules))
        ignored_rtl_hints = []

    for module in ignored_rtl_hints:
        result.findings.append(Finding(
            rule="RTL_ANALOG_NAME_NOT_IN_BLOCK_LIST",
            severity="WARNING",
            message=(
                f"RTL module '{module}' matched the analog name heuristic but "
                "is not declared in analog_block_list.json; the explicit block "
                "list is authoritative, so no analog deliverables are required "
                "for this module."
            ),
        ))

    if not all_blocks:
        result.findings.append(Finding(
            rule="SKIP_NO_ANALOG",
            severity="INFO",
            message=(
                "analog_block_list.json declares no analog blocks; skipping"
                if block_list_present else
                "No analog modules detected in RTL and no "
                "analog_block_list.json; skipping"
            ),
        ))
        result.summary = {
            "skipped": True,
            "reason": "no_analog_blocks",
            "from_rtl": rtl_modules,
            "from_block_list": explicit_blocks,
            "roster_source": (
                "analog_block_list" if block_list_present else
                "rtl_name_heuristic"
            ),
            "rtl_name_hints_not_in_block_list": ignored_rtl_hints,
        }
        return result

    analog_dir = _pl.analog_dir(project)
    covered = 0
    uncovered = []

    for block in all_blocks:
        block_dir = analog_dir / block
        missing = []

        if not block_dir.is_dir():
            missing = ["spec.json", "*.sp", "corner_results.json"]
        else:
            if not (block_dir / "spec.json").exists():
                missing.append("spec.json")
            if not list(block_dir.glob("*.sp")):
                missing.append("*.sp (SPICE netlist)")
            if not (block_dir / "corner_results.json").exists():
                missing.append("corner_results.json")

        if missing:
            uncovered.append(block)
            result.findings.append(Finding(
                rule="ANALOG_BLOCK_UNCOVERED",
                severity="ERROR",
                message=(
                    f"Analog block '{block}' missing deliverables: "
                    f"{', '.join(missing)}. "
                    f"Run analog-spec-extract → analog-sizing-loop to produce them."
                ),
            ))
        else:
            covered += 1
            result.findings.append(Finding(
                rule="ANALOG_BLOCK_COVERED",
                severity="INFO",
                message=f"Analog block '{block}' has spec.json + netlist + corner results",
            ))

    if uncovered:
        result.passed = False

    result.summary = {
        "skipped": False,
        "total_blocks": len(all_blocks),
        "covered": covered,
        "uncovered": uncovered,
        "from_rtl": rtl_modules,
        "from_block_list": explicit_blocks,
        "roster_source": (
            "analog_block_list" if block_list_present else
            "rtl_name_heuristic"
        ),
        "rtl_name_hints_not_in_block_list": ignored_rtl_hints,
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
    # v1.6.144 (#57) — accept FPGA-prototype-stage stub waiver.
    import _fpga_stub_waiver as _stub
    _stub.add_fpga_stub_argparse(ap)
    args = ap.parse_args(argv)

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir)

    # v1.6.144 (#57) — demote missing-per-block-artifact failures to
    # PASS_WITH_WAIVERS at the FPGA prototype stage so phase2.fpga_burn
    # is not blocked while analog A1-A9 is still running. Same gate
    # re-fires without the waiver at phase3.foundry_handoff for tapeout.
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
        atomic_write_text(Path(args.json), out)

    # #521 — the verdict is routed from the gate's OWN structured result. The
    # `skipped: True` branch in run_audit has always known there was no analog
    # block to cover; main() simply never read it back.
    skipped = _vx.summary_is_skipped(result.summary)
    reason = _vx.skip_reason(result.summary)

    if not args.json:
        print(_vx.verdict_line("analog_block_coverage_check", result.passed,
                               skipped, reason, pass_token=waiver_status))
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                print(f"  [{f.severity}] {f.rule}: {f.message}")

    if result.passed and skipped:
        _vx.announce_vacuous(result.program, reason)
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
