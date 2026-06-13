#!/usr/bin/env python3
"""analog_hw_tb_de10lite_budget_check.py — DE10-Lite board-budget gate.

Extracted from the `analog-hw-testbench-gen` skill's "Do not exceed DE10-Lite
GPIO count (36 GPIO + 10 Arduino header)" rule, which was previously an
agent-honour-system bullet. This program makes the numeric board ceiling
DETERMINISTIC.

This is a BOARD check (DE10-Lite / Terasic MAX10 10M50DAF484C7G), chip-AGNOSTIC.
The `fpga_qsf_lint.py` shared lint checks generic pin CONFLICTS + IO_STANDARD
presence + VERILOG_FILE existence, but never enforces the DE10-Lite
36-GPIO + 10-Arduino external-I/O budget. This program closes that gap.

SCOPE GATE
----------
The skill rule is explicitly DE10-Lite-specific, so this program only judges a
QSF that targets the DE10-Lite (FAMILY "MAX 10" + DEVICE 10M50DAF484C7G, or no
device line but DE10-Lite signal names like CLOCK_50/GPIO_0/Arduino_IO present).
A QSF for any other board (DE10-Nano Cyclone V, MAX1000, generic Cyclone, …)
is correctly using a different pin map and is reported NO_DATA (out of scope) —
never FAIL. This prevents false-firing on legitimately-non-DE10-Lite QSFs in
the corpus.

CHECKS (only on in-scope DE10-Lite QSFs)
----------------------------------------
  1. external-io-budget — count the DISTINCT physical pins assigned to the
     GPIO_0 2x20 header OR the Arduino Uno R3 header. The skill ceiling is
     36 GPIO + 10 Arduino = 46. FAIL if the count exceeds 46. Uses only the
     GPIO_0 + Arduino pin tables (verbatim from the manual), so it is exact
     and does not depend on an exhaustive board catalogue.
  2. pin-double-assignment — no two distinct signals on the same physical pin
     (a board short). Structural and board-agnostic.

NOTE on dropped check: an "every PIN_ must exist on the board" check was
deliberately NOT implemented, because the DE10-Lite has ~180 physical pins
(CLOCK/KEY/SW/LEDR + 36 GPIO + 16 Arduino + 48 HEX + VGA + SDRAM + G-sensor +
analog) and the manual tables for HEX/VGA/SDRAM are not embedded here. Firing
on an "unknown" pin with a partial catalogue would false-fire on legitimate
HEX/VGA/SDRAM assignments — so that clause is left to the agent / a future
program that ingests the full manual pin-out table.

Pin tables sourced verbatim from "DE10-Lite User Manual v1.2" §3.5 (2x20 GPIO,
GPIO_0..35) and §3.6 (Arduino Uno R3 header). No invented values; the budget
46 = 36 + 10 is the literal skill ceiling, not an invented threshold.

Honesty:
  - QSF file/dir missing or unreadable          -> exit 2 (cannot judge).
  - QSF does not target DE10-Lite (other board) -> exit 2 NO_DATA (out of scope).
  - An in-scope DE10-Lite QSF with ZERO pin
    assignments                                 -> FAIL (vacuous-pass guard).

CLI:
  python3 analog_hw_tb_de10lite_budget_check.py <qsf_file_or_dir> [--json]

Exit codes:
  0  PASS (all checks clean)
  1  FAIL (>=1 finding)
  2  missing / unreadable / out-of-scope data (cannot judge)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# DE10-Lite (Terasic, MAX10 10M50DAF484C7G) external-I/O pin catalogue.
# Sourced verbatim from "DE10-Lite User Manual v1.2" §3.5 (2x20 GPIO header,
# GPIO_0[0..35]) and §3.6 (Arduino Uno R3 header). Chip-AGNOSTIC board data.
# ---------------------------------------------------------------------------

# §3.5 — 2x20 GPIO header (JP1), GPIO_0[0..35] : 36 external-I/O pins.
_GPIO0_PINS: Dict[str, str] = {
    "GPIO_0[0]": "PIN_V10", "GPIO_0[1]": "PIN_W10", "GPIO_0[2]": "PIN_V9",
    "GPIO_0[3]": "PIN_W9", "GPIO_0[4]": "PIN_V8", "GPIO_0[5]": "PIN_W8",
    "GPIO_0[6]": "PIN_V7", "GPIO_0[7]": "PIN_W7", "GPIO_0[8]": "PIN_W6",
    "GPIO_0[9]": "PIN_V5", "GPIO_0[10]": "PIN_W5", "GPIO_0[11]": "PIN_AA15",
    "GPIO_0[12]": "PIN_AA14", "GPIO_0[13]": "PIN_W13", "GPIO_0[14]": "PIN_W12",
    "GPIO_0[15]": "PIN_AB13", "GPIO_0[16]": "PIN_AB12", "GPIO_0[17]": "PIN_Y11",
    "GPIO_0[18]": "PIN_AB11", "GPIO_0[19]": "PIN_W11", "GPIO_0[20]": "PIN_AB10",
    "GPIO_0[21]": "PIN_AA10", "GPIO_0[22]": "PIN_AA9", "GPIO_0[23]": "PIN_Y8",
    "GPIO_0[24]": "PIN_AA8", "GPIO_0[25]": "PIN_Y7", "GPIO_0[26]": "PIN_AA7",
    "GPIO_0[27]": "PIN_Y6", "GPIO_0[28]": "PIN_AA6", "GPIO_0[29]": "PIN_Y5",
    "GPIO_0[30]": "PIN_AA5", "GPIO_0[31]": "PIN_Y4", "GPIO_0[32]": "PIN_AB3",
    "GPIO_0[33]": "PIN_Y3", "GPIO_0[34]": "PIN_AB2", "GPIO_0[35]": "PIN_AA2",
}

# §3.6 — Arduino Uno R3 header: 16 digital I/O + ARDUINO_RESET_N.
_ARDUINO_PINS: Dict[str, str] = {
    "Arduino_IO0": "PIN_AB5", "Arduino_IO1": "PIN_AB6", "Arduino_IO2": "PIN_AB7",
    "Arduino_IO3": "PIN_AB8", "Arduino_IO4": "PIN_AB9", "Arduino_IO5": "PIN_Y10",
    "Arduino_IO6": "PIN_AA11", "Arduino_IO7": "PIN_AA12", "Arduino_IO8": "PIN_AB17",
    "Arduino_IO9": "PIN_AA17", "Arduino_IO10": "PIN_AB19", "Arduino_IO11": "PIN_AA19",
    "Arduino_IO12": "PIN_Y19", "Arduino_IO13": "PIN_AB20", "Arduino_IO14": "PIN_AB21",
    "Arduino_IO15": "PIN_AA20", "ARDUINO_RESET_N": "PIN_F16",
}

# Physical pins that count toward the external-I/O budget (GPIO header + Arduino).
_EXTERNAL_IO_PINS = set(_GPIO0_PINS.values()) | set(_ARDUINO_PINS.values())

# Skill budget: 36 GPIO + 10 Arduino header = 46 external-I/O pins.
_EXTERNAL_IO_BUDGET = 46

# DE10-Lite identity: MAX10 10M50DAF484C7G.
_DE10LITE_DEVICE_RE = re.compile(r"10M50DAF484C7G", re.IGNORECASE)
_MAX10_FAMILY_RE = re.compile(r'FAMILY\s+"?MAX\s*10"?', re.IGNORECASE)
# DE10-Lite-distinctive board signal names (used only when no DEVICE line).
_DE10LITE_SIGNAL_RE = re.compile(
    r"-to\s+\"?(GPIO_0\[|Arduino_IO\d|MAX10_CLK1_50|ARDUINO_RESET_N)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_pin_assignments(qsf_text: str) -> List[Tuple[str, str]]:
    """Return [(signal, PIN_xx), ...] from set_location_assignment lines.

    Comments (# ...) are ignored. PIN_ tokens are upper-cased.
    """
    out: List[Tuple[str, str]] = []
    for line in qsf_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(
            r'set_location_assignment\s+(PIN_\w+)\s+-to\s+"?([^"\s]+)"?',
            stripped, re.IGNORECASE,
        )
        if m:
            signal = m.group(2).strip()
            pin = "PIN_" + m.group(1).strip()[4:].upper()
            out.append((signal, pin))
    return out


def is_de10lite_qsf(qsf_text: str) -> bool:
    """True iff the QSF targets the DE10-Lite (MAX10 10M50DAF484C7G).

    Primary signal: an explicit DEVICE 10M50DAF484C7G line.
    Secondary (when device line is absent): FAMILY "MAX 10" together with a
    DE10-Lite-distinctive board signal name. A QSF that names a DIFFERENT
    device is treated as out-of-scope even if it happens to mention MAX 10
    in a comment.
    """
    m = re.search(
        r'set_global_assignment\s+-name\s+DEVICE\s+"?([\w-]+)"?',
        qsf_text, re.IGNORECASE,
    )
    if m:
        return bool(_DE10LITE_DEVICE_RE.fullmatch(m.group(1).strip())
                    or _DE10LITE_DEVICE_RE.search(m.group(1).strip()))
    # No DEVICE line: fall back to FAMILY + distinctive board signals.
    if _MAX10_FAMILY_RE.search(qsf_text) and _DE10LITE_SIGNAL_RE.search(qsf_text):
        return True
    return False


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_pin_double_assignment(
    assignments: List[Tuple[str, str]]
) -> List[dict]:
    findings = []
    pin_to_signals: Dict[str, List[str]] = {}
    for signal, pin in assignments:
        pin_to_signals.setdefault(pin, []).append(signal)
    for pin, signals in pin_to_signals.items():
        distinct = sorted(set(signals))
        if len(distinct) > 1:
            findings.append({
                "rule": "pin-double-assignment",
                "severity": "ERROR",
                "message": (
                    f"Physical pin {pin} assigned to multiple signals: "
                    f"{', '.join(distinct)} (board short)"
                ),
                "pin": pin,
                "signals": distinct,
            })
    return findings


def check_external_io_budget(
    assignments: List[Tuple[str, str]]
) -> List[dict]:
    findings = []
    external_pins = sorted({
        pin for _, pin in assignments if pin in _EXTERNAL_IO_PINS
    })
    if len(external_pins) > _EXTERNAL_IO_BUDGET:
        findings.append({
            "rule": "external-io-budget",
            "severity": "ERROR",
            "message": (
                f"{len(external_pins)} distinct external-I/O pins assigned "
                f"(GPIO header + Arduino), exceeds DE10-Lite budget of "
                f"{_EXTERNAL_IO_BUDGET} (36 GPIO + 10 Arduino)"
            ),
            "external_io_pins_used": len(external_pins),
            "budget": _EXTERNAL_IO_BUDGET,
        })
    return findings


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _find_qsf_files(target: Path) -> List[Path]:
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(target.rglob("*.qsf"))
    return []


def run_check(target: Path) -> dict:
    """Return a report dict. status is PASS / FAIL / NO_DATA."""
    qsf_files = _find_qsf_files(target)
    if not qsf_files:
        return {
            "tool": "analog_hw_tb_de10lite_budget_check",
            "target": str(target),
            "status": "NO_DATA",
            "message": f"no .qsf file found at {target}",
            "findings": [],
        }

    all_findings: List[dict] = []
    files_report = []
    total_assignments = 0
    in_scope_files = 0

    for qsf in qsf_files:
        try:
            text = qsf.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return {
                "tool": "analog_hw_tb_de10lite_budget_check",
                "target": str(target),
                "status": "NO_DATA",
                "message": f"cannot read {qsf}: {e}",
                "findings": [],
            }

        if not is_de10lite_qsf(text):
            files_report.append({
                "file": str(qsf),
                "in_scope": False,
                "reason": "not a DE10-Lite (MAX10 10M50DAF484C7G) QSF",
            })
            continue

        in_scope_files += 1
        assignments = parse_pin_assignments(text)
        total_assignments += len(assignments)
        f: List[dict] = []
        if not assignments:
            f.append({
                "rule": "no-pin-assignments",
                "severity": "ERROR",
                "message": (
                    f"{qsf.name}: DE10-Lite QSF with no set_location_assignment "
                    f"— a testbench top with no pin map is not a PASS"
                ),
                "file": str(qsf),
            })
        else:
            f.extend(check_pin_double_assignment(assignments))
            f.extend(check_external_io_budget(assignments))
        for item in f:
            item.setdefault("file", str(qsf))
        all_findings.extend(f)
        files_report.append({
            "file": str(qsf),
            "in_scope": True,
            "pin_assignments": len(assignments),
            "findings": len(f),
        })

    # If NO file in the target was a DE10-Lite QSF, we cannot judge.
    if in_scope_files == 0:
        return {
            "tool": "analog_hw_tb_de10lite_budget_check",
            "target": str(target),
            "status": "NO_DATA",
            "message": (
                "no in-scope DE10-Lite (MAX10 10M50DAF484C7G) QSF found "
                "— out of scope for this board-budget check"
            ),
            "files": files_report,
            "findings": [],
        }

    return {
        "tool": "analog_hw_tb_de10lite_budget_check",
        "target": str(target),
        "board": "DE10-Lite (MAX10 10M50DAF484C7G)",
        "external_io_budget": _EXTERNAL_IO_BUDGET,
        "in_scope_files": in_scope_files,
        "files": files_report,
        "total_assignments": total_assignments,
        "total_findings": len(all_findings),
        "status": "FAIL" if all_findings else "PASS",
        "findings": all_findings,
    }


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="DE10-Lite external-I/O budget + pin-short check for QSF",
    )
    parser.add_argument(
        "target",
        help="QSF file, or a directory to recursively scan for *.qsf",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    args = parser.parse_args(argv)

    target = Path(args.target)
    report = run_check(target)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        status = report["status"]
        if status == "NO_DATA":
            print(f"NO_DATA: {report['message']}")
        elif status == "PASS":
            print(
                f"PASS: DE10-Lite budget clean "
                f"({report['total_assignments']} pin assignment(s) across "
                f"{report['in_scope_files']} in-scope QSF, "
                f"budget {report['external_io_budget']})"
            )
        else:
            print(f"FAIL: {report['total_findings']} finding(s)")
            for fnd in report["findings"]:
                print(f"  [{fnd['severity']}] {fnd['rule']}: {fnd['message']}")

    if report["status"] == "NO_DATA":
        return 2
    return 1 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
