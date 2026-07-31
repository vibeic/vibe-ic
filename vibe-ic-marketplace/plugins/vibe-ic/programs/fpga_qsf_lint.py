#!/usr/bin/env python3
"""Deterministic QSF lint: validate Quartus project files.

Checks:
  1. Every VERILOG_FILE listed actually exists on disk.
  2. PIN assignments don't conflict (no two signals on same pin).
  3. TOP_LEVEL_ENTITY is set and matches a module in the RTL.
  4. IO_STANDARD is set for every pin assignment.

Exit: 0 = PASS, 1 = FAIL.

CLI:
  python3 fpga_qsf_lint.py --qsf-file project.qsf --rtl-dir ./rtl/ --out-dir /tmp/lint
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

def parse_qsf(qsf_path: Path) -> dict:
    """Parse a Quartus QSF file and return structured data.

    Returns dict with keys:
      verilog_files: list of str  (paths from set_global_assignment -name VERILOG_FILE ...)
      top_level_entity: str | None
      pin_assignments: list of (signal, pin)  from set_location_assignment
      io_standards: dict of signal -> standard  from set_instance_assignment -name IO_STANDARD
      raw_lines: list of str
    """
    verilog_files: List[str] = []
    top_level_entity: str | None = None
    pin_assignments: List[Tuple[str, str]] = []
    io_standards: Dict[str, str] = {}
    raw_lines: List[str] = []

    text = qsf_path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        stripped = line.strip()
        raw_lines.append(stripped)

        # Skip comments and blank lines
        if not stripped or stripped.startswith("#"):
            continue

        # VERILOG_FILE
        m = re.match(
            r'set_global_assignment\s+-name\s+(?:SYSTEM)?VERILOG_FILE\s+"?([^"]+)"?',
            stripped, re.IGNORECASE,
        )
        if m:
            verilog_files.append(m.group(1).strip())
            continue

        # TOP_LEVEL_ENTITY
        m = re.match(
            r'set_global_assignment\s+-name\s+TOP_LEVEL_ENTITY\s+"?([^"]+)"?',
            stripped, re.IGNORECASE,
        )
        if m:
            top_level_entity = m.group(1).strip()
            continue

        # PIN assignment: set_location_assignment PIN_XX -to signal_name
        m = re.match(
            r'set_location_assignment\s+(PIN_\w+)\s+-to\s+"?([^"]+)"?',
            stripped, re.IGNORECASE,
        )
        if m:
            pin_assignments.append((m.group(2).strip(), m.group(1).strip()))
            continue

        # IO_STANDARD: set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to signal
        m = re.match(
            r'set_instance_assignment\s+-name\s+IO_STANDARD\s+"?([^"]+)"?\s+-to\s+"?([^"]+)"?',
            stripped, re.IGNORECASE,
        )
        if m:
            io_standards[m.group(2).strip()] = m.group(1).strip()
            continue

    return {
        "verilog_files": verilog_files,
        "top_level_entity": top_level_entity,
        "pin_assignments": pin_assignments,
        "io_standards": io_standards,
        "raw_lines": raw_lines,
    }


def find_module_names(rtl_dir: Path) -> set:
    """Scan RTL directory for Verilog/SystemVerilog module declarations."""
    modules = set()
    if not rtl_dir.is_dir():
        return modules
    for ext in ("*.v", "*.sv"):
        for fpath in rtl_dir.rglob(ext):
            try:
                text = fpath.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in re.finditer(r'\bmodule\s+(\w+)', text):
                modules.add(m.group(1))
    return modules


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_verilog_files_exist(
    verilog_files: List[str], qsf_dir: Path, rtl_dir: Path
) -> List[dict]:
    """Check that every VERILOG_FILE listed in the QSF actually exists."""
    findings = []
    for vf in verilog_files:
        vf_path = Path(vf)
        # Try relative to QSF dir, then absolute, then relative to rtl_dir
        candidates = [
            qsf_dir / vf_path,
            vf_path,
            rtl_dir / vf_path.name,
        ]
        if not any(c.exists() for c in candidates):
            findings.append({
                "rule": "missing-verilog-file",
                "severity": "ERROR",
                "message": f"VERILOG_FILE '{vf}' not found on disk",
                "file": vf,
            })
    return findings


def check_pin_conflicts(pin_assignments: List[Tuple[str, str]]) -> List[dict]:
    """Check that no two signals are assigned to the same physical pin."""
    findings = []
    pin_to_signals: Dict[str, List[str]] = {}
    for signal, pin in pin_assignments:
        pin_to_signals.setdefault(pin, []).append(signal)
    for pin, signals in pin_to_signals.items():
        if len(signals) > 1:
            findings.append({
                "rule": "pin-conflict",
                "severity": "ERROR",
                "message": f"Pin {pin} assigned to multiple signals: {', '.join(signals)}",
                "pin": pin,
                "signals": signals,
            })
    return findings


def check_top_entity(
    top_level_entity: str | None, rtl_modules: set
) -> List[dict]:
    """Check TOP_LEVEL_ENTITY is set and matches an RTL module."""
    findings = []
    if not top_level_entity:
        findings.append({
            "rule": "missing-top-entity",
            "severity": "ERROR",
            "message": "TOP_LEVEL_ENTITY is not set in QSF",
        })
        return findings
    if rtl_modules and top_level_entity not in rtl_modules:
        findings.append({
            "rule": "top-entity-mismatch",
            "severity": "ERROR",
            "message": (
                f"TOP_LEVEL_ENTITY '{top_level_entity}' not found in RTL modules: "
                f"{', '.join(sorted(rtl_modules))}"
            ),
            "entity": top_level_entity,
            "available_modules": sorted(rtl_modules),
        })
    return findings


def check_io_standards(
    pin_assignments: List[Tuple[str, str]], io_standards: Dict[str, str]
) -> List[dict]:
    """Check that every pin-assigned signal has an IO_STANDARD."""
    findings = []
    for signal, pin in pin_assignments:
        if signal not in io_standards:
            findings.append({
                "rule": "missing-io-standard",
                "severity": "ERROR",
                "message": f"Signal '{signal}' on {pin} has no IO_STANDARD assignment",
                "signal": signal,
                "pin": pin,
            })
    return findings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def lint_qsf(qsf_path: Path, rtl_dir: Path) -> Tuple[List[dict], dict]:
    """Run all QSF checks; return (findings, what was examined).

    The counts are returned rather than left for the caller to re-derive,
    because `PASS: QSF lint clean` said nothing about how much was linted — a
    QSF with no assignments at all produced the same sentence and the same rc
    as a fully populated one that checked out (#559).
    """
    parsed = parse_qsf(qsf_path)
    qsf_dir = qsf_path.parent
    rtl_modules = find_module_names(rtl_dir)
    examined = {
        "verilog_files": len(parsed["verilog_files"]),
        "pin_assignments": len(parsed["pin_assignments"]),
        "io_standards": len(parsed["io_standards"]),
        "rtl_modules": len(rtl_modules),
    }

    findings: List[dict] = []
    findings.extend(check_verilog_files_exist(
        parsed["verilog_files"], qsf_dir, rtl_dir,
    ))
    findings.extend(check_pin_conflicts(parsed["pin_assignments"]))
    findings.extend(check_top_entity(parsed["top_level_entity"], rtl_modules))
    findings.extend(check_io_standards(
        parsed["pin_assignments"], parsed["io_standards"],
    ))
    return findings, examined


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic QSF lint for FPGA project files",
    )
    parser.add_argument("--qsf-file", required=True, help="Path to QSF file")
    parser.add_argument("--rtl-dir", required=True, help="Path to RTL directory")
    parser.add_argument("--out-dir", default=".", help="Output directory for report")
    args = parser.parse_args(argv)

    qsf_path = Path(args.qsf_file)
    rtl_dir = Path(args.rtl_dir)
    out_dir = Path(args.out_dir)

    if not qsf_path.exists():
        # rc 2, not 1: a QSF that is not there is "could not check", not "found
        # a violation". rc 1 is a defect verdict, and the P0 umbrella reads the
        # exit code — a missing input would have been recorded as a real QSF
        # lint failure against the design (#559).
        print(f"VACUOUS_PASS: fpga_qsf_lint examined nothing "
              f"(reason: QSF file not found: {qsf_path}) — not a clean lint",
              file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)

    findings, examined = lint_qsf(qsf_path, rtl_dir)

    # Write JSON report
    report_path = out_dir / "fpga_qsf_lint.json"
    report = {
        "tool": "fpga_qsf_lint",
        "qsf_file": str(qsf_path),
        "rtl_dir": str(rtl_dir),
        "total_findings": len(findings),
        "examined": examined,
        "status": "FAIL" if findings else "PASS",
        "findings": findings,
    }
    report_path.write_text(json.dumps(report, indent=2))

    # Console output
    if findings:
        print(f"FAIL: {len(findings)} finding(s)")
        for f in findings:
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    else:
        print(f"PASS: QSF lint clean "
              f"(examined {examined['verilog_files']} verilog file(s), "
              f"{examined['pin_assignments']} pin assignment(s), "
              f"{examined['rtl_modules']} RTL module(s))")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
