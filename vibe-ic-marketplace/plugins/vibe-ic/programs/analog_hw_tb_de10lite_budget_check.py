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
  1. pin-double-assignment — no two distinct signals on the same physical pin
     (a board short). Structural and board-agnostic.
  2. no-pin-assignments — the TARGET as a whole contains at least one
     `set_location_assignment` across its in-scope DE10-Lite QSFs. A DE10-Lite
     testbench top with no pin map anywhere is not a PASS. Evaluated at target
     level, not per file: a settings-only .qsf beside a pin-map .qsf is a
     normal Quartus project split, and firing per-file turned that split into
     a project-wide FAIL (measured).

The external-I/O count is MEASURED AND DISCLOSED (`external_io_pins_used` in
the JSON report, and on the PASS line) but is NOT a verdict — see below.

WITHDRAWN CHECK: external-io-budget, and why
--------------------------------------------
This program shipped a third rule: FAIL when the distinct physical pins landing
on the GPIO_0 header or the Arduino header exceed 46 ("36 GPIO + 10 Arduino",
the literal prose ceiling in skills/analog-hw-testbench-gen/SKILL.md). It is
withdrawn, for a reason that is a property of its construction, not a
preference:

  * Its DENOMINATOR and its CEILING come from the same table. The rule counts
    only pins that are IN this file's catalogue, and that catalogue holds 53
    pins (36 GPIO + 16 Arduino digital I/O + ARDUINO_RESET_N — all enumerated
    below, all physically present on the board). So the count can never exceed
    53 no matter how over-budget a design is: a design that genuinely needs
    more external I/O than the board offers must assign the surplus to pins
    OUTSIDE the catalogue, which the rule does not count.
  * Below 53 the ceiling of 46 only fires on legal pin maps. MEASURED: a
    physically valid map using all 36 GPIO_0 pins plus 11 of the board's 16
    Arduino digital I/Os -> `47 distinct external-I/O pins assigned, exceeds
    DE10-Lite budget of 46`. Those 47 pins all exist on the board and none is
    assigned twice. The "10" is a prose bullet that this file's own §3.6 table
    (17 entries) contradicts.

So the rule could only produce false positives, and could never produce the
true positive it was named for. It is removed rather than re-thresholded:
setting the ceiling to the catalogue's own 53 would leave a rule that is
arithmetically incapable of firing, which is a worse kind of check than none.
A real external-I/O budget needs the FULL manual pin-out table (so that
off-catalogue pins can be attributed to a header rather than ignored); that is
a separate piece of work, tracked in the PR that withdrew this rule.

NOTE on a check that was never implemented, and still is not: "every PIN_ must
exist on the board". The DE10-Lite has ~180 physical pins (CLOCK/KEY/SW/LEDR +
36 GPIO + 16 Arduino + 48 HEX + VGA + SDRAM + G-sensor + analog) and the manual
tables for HEX/VGA/SDRAM are not embedded here. Firing on an "unknown" pin with
a partial catalogue would false-fire on legitimate HEX/VGA/SDRAM assignments.

Pin tables sourced verbatim from "DE10-Lite User Manual v1.2" §3.5 (2x20 GPIO,
GPIO_0..35) and §3.6 (Arduino Uno R3 header). No invented values.

RELATIONSHIP TO fpga_qsf_lint
-----------------------------
`pin-double-assignment` duplicates `fpga_qsf_lint`'s `pin-conflict` rule —
byte-for-byte the same defect, measured on the same fixture. It is kept because
`fpga_qsf_lint` requires `--qsf-file --rtl-dir` and is listed in
`flow_compliance_check.KNOWN_NOT_INVOCABLE` ("driven from the FPGA-compile step
that emits the .qsf" — a step that does not name it), so on a real project the
duplicate is the only copy that runs. The UNIQUE rule here is
`no-pin-assignments`: measured, `fpga_qsf_lint` on a DE10-Lite QSF with zero
pin assignments returns `PASS: QSF lint clean (… 0 pin assignment(s) …)` — a
clean bill of health over an empty denominator.

Honesty:
  - QSF file/dir missing or unreadable          -> exit 2 (cannot judge).
  - QSF does not target DE10-Lite (other board) -> exit 2 NO_DATA (out of scope).
  - No in-scope DE10-Lite QSF anywhere in the
    target has a pin assignment                 -> FAIL (vacuous-pass guard).

CLI:
  python3 analog_hw_tb_de10lite_budget_check.py <qsf_file_or_dir> [--json [PATH]]

  `--json` with no value prints the report to stdout (unchanged). `--json PATH`
  WRITES the report to PATH — the house style every flow-YAML gate command uses.
  Before this, `--json` was `action="store_true"`, so the house-style invocation
  `... . --json reports/…/de10.json` died in argparse with exit 2, and exit 2 is
  this repo's disclosed cannot-judge tier: a one-token typo bought a permanent,
  undisclosed pass.

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
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

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

# Physical external-I/O pins the board offers on the two user headers
# (36 GPIO_0 + 16 Arduino digital I/O + ARDUINO_RESET_N = 53). MEASURED AND
# DISCLOSED per target; deliberately NOT a threshold — see the module docstring
# section "WITHDRAWN CHECK: external-io-budget, and why".
_EXTERNAL_IO_PINS = set(_GPIO0_PINS.values()) | set(_ARDUINO_PINS.values())

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


def external_io_pins_used(
    assignments: List[Tuple[str, str]]
) -> List[str]:
    """DISCLOSURE ONLY — the distinct header pins this QSF consumes.

    Returns the sorted list; produces NO finding. The withdrawn
    `external-io-budget` rule turned this same number into a verdict against a
    ceiling below the catalogue it was drawn from; see the module docstring for
    the measurement. Reporting the number without judging it keeps the
    observation and drops the false positive.
    """
    return sorted({pin for _, pin in assignments if pin in _EXTERNAL_IO_PINS})


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
    in_scope_paths: List[Path] = []
    external_pins_all: set = set()

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
        in_scope_paths.append(qsf)
        assignments = parse_pin_assignments(text)
        total_assignments += len(assignments)
        ext = external_io_pins_used(assignments)
        external_pins_all.update(ext)
        # Per-file rules. `no-pin-assignments` is NOT one of them: see below.
        f: List[dict] = list(check_pin_double_assignment(assignments))
        for item in f:
            item.setdefault("file", str(qsf))
        all_findings.extend(f)
        files_report.append({
            "file": str(qsf),
            "in_scope": True,
            "pin_assignments": len(assignments),
            "external_io_pins_used": len(ext),
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

    # `no-pin-assignments` is a TARGET-level rule, not a per-file one. A
    # settings-only .qsf beside a pin-map .qsf is a normal Quartus project
    # split; firing per-file made that split a project-wide FAIL (measured:
    # one valid 2-pin map + one settings-only DE10 QSF -> FAIL). The defect
    # this guards is "a DE10-Lite target with no pin map at all", which is
    # exactly `total_assignments == 0`.
    if total_assignments == 0:
        all_findings.append({
            "rule": "no-pin-assignments",
            "severity": "ERROR",
            "message": (
                f"no set_location_assignment in any of the "
                f"{in_scope_files} in-scope DE10-Lite QSF(s) "
                f"({', '.join(p.name for p in in_scope_paths)}) "
                f"— a testbench top with no pin map is not a PASS"
            ),
            "file": str(in_scope_paths[0]),
        })

    return {
        "tool": "analog_hw_tb_de10lite_budget_check",
        "target": str(target),
        "board": "DE10-Lite (MAX10 10M50DAF484C7G)",
        # Disclosure, not a threshold — see the module docstring section
        # "WITHDRAWN CHECK: external-io-budget, and why".
        "external_io_pins_available": len(_EXTERNAL_IO_PINS),
        "external_io_pins_used": len(external_pins_all),
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
    # `nargs="?"` keeps the documented bare `--json` (report to stdout) working
    # AND accepts the flow-YAML house style `--json <path>`. It used to be
    # `action="store_true"`, so the house-style form died in argparse with
    # exit 2 — this repo's disclosed cannot-judge tier, which
    # `flow_compliance_check` records as a pass. A gate must not be one token
    # away from a permanent silent pass.
    parser.add_argument(
        "--json", nargs="?", const="-", default=None, metavar="PATH",
        help="write the JSON report to PATH (bare --json prints to stdout)",
    )
    args = parser.parse_args(argv)

    target = Path(args.target)
    report = run_check(target)

    if args.json == "-":
        print(json.dumps(report, indent=2))
    elif args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out, json.dumps(report, indent=2) + "\n")

    if args.json != "-":
        status = report["status"]
        if status == "NO_DATA":
            print(f"NO_DATA: {report['message']}")
        elif status == "PASS":
            print(
                f"PASS: DE10-Lite QSF pin map clean "
                f"({report['total_assignments']} pin assignment(s) across "
                f"{report['in_scope_files']} in-scope QSF; "
                f"{report['external_io_pins_used']} of "
                f"{report['external_io_pins_available']} header external-I/O "
                f"pins used — DISCLOSED, not judged)"
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
