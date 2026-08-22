#!/usr/bin/env python3
"""tx_abort_during_transmission_check.py — Verify TX modules do not abort/reset
during active bit-serial transmission.

THE PROBLEM
-----------
In half-duplex protocols, the DUT's TX module drives the shared bus
bit-by-bit. If an external event (break, timeout, etc.) triggers a
transition to IDLE during active transmission, the bit-serial output is
truncated mid-byte — producing invalid pulses and corrupting the response.

The v0.108 <chip-class> run hit exactly this: tx_cmd.v's break handler fired
during S_TX_DATA, aborting every transmission before completion.

HEURISTIC
---------
1. Find TX modules (filenames ``tx_*``, or modules with ``tx_start`` /
   ``tx_done`` ports).
2. Identify TX-active states (names containing ``TX_BIT``, ``TX_DATA``,
   ``TX_BYTE``, ``SEND``, ``XMIT``, ``TX_CRC``, ``TX_BREAK``).
3. Find event-driven transitions to idle:
   ``state <= S_IDLE`` conditioned on break/timeout/external signal
   (NOT on tx_done / bit completion).
4. If such transition can fire during TX-active states → FAIL.

USAGE
-----
    python3 tx_abort_during_transmission_check.py <rtl_dir> [--json report.json]

EXIT CODES
----------
    0 — PASS: TX modules were examined and none aborts mid-transmission
    1 — FAIL (TX abort during active transmission)
    2 — VACUOUS: nothing was examined — no RTL directory, or no TX module in
        it, so there is no transmission this gate could have audited. #515:
        this used to be rc 0, which credited the gate in the plain PASS tier
        for designs that contain no TX module at all.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

import _vacuous_exit as _vx


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "tx_abort_during_transmission_check"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


TX_ACTIVE_STATE_RE = re.compile(
    r"\b\w*(?:TX_BIT|TX_DATA|TX_BYTE|TX_CRC|TX_BREAK|TX_LOW|SEND|XMIT)\w*\b", re.I
)
BREAK_EVENT_RE = re.compile(r"\b(rx_break|brk|break_detect|break_seen)\b", re.I)
IDLE_TRANSITION_RE = re.compile(
    r"\b(\w+)\s*<=\s*(\w*(?:IDLE|DONE|WAIT_CMD|READY)\w*)\b", re.I
)


def _is_tx_module(path: Path) -> bool:
    name = path.stem.lower()
    if name.startswith("tx_") or name.endswith("_tx"):
        return True
    try:
        txt = path.read_text(errors="replace")
    except OSError:
        return False
    return bool(re.search(r"\btx_start\b", txt) and re.search(r"\btx_done\b", txt))


def audit(rtl_dir: Path) -> AuditResult:
    result = AuditResult()
    if not rtl_dir.is_dir():
        result.summary = {"skipped": True, "reason": "not_a_directory"}
        return result

    files = sorted(list(rtl_dir.rglob("*.v")) + list(rtl_dir.rglob("*.sv")))
    tx_files = [f for f in files if _is_tx_module(f)]

    if not tx_files:
        result.summary = {"skipped": True, "reason": "no_tx_modules"}
        result.findings.append(Finding(
            "SKIP", "INFO", "No TX modules detected.",
        ))
        return result

    result.summary = {"skipped": False, "tx_files": [str(f.name) for f in tx_files]}

    for f in tx_files:
        try:
            raw = f.read_text(errors="replace")
        except OSError:
            continue
        text = _strip_comments(raw)
        lines = text.splitlines()

        case_depth = 0
        current_state_label = ""
        in_default = False

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            if re.match(r"\bcase\s*\(", stripped):
                case_depth += 1
                in_default = False
                current_state_label = ""
                continue

            if stripped.startswith("endcase"):
                case_depth -= 1
                in_default = False
                current_state_label = ""
                continue

            if case_depth > 0:
                state_match = re.match(r"(\w+)\s*:", stripped)
                if state_match and not stripped.startswith("default"):
                    current_state_label = state_match.group(1)
                    in_default = False
                elif stripped.startswith("default"):
                    in_default = True
                    current_state_label = "default"

            if not BREAK_EVENT_RE.search(line):
                continue
            if not IDLE_TRANSITION_RE.search(line):
                continue

            is_in_active = False
            if current_state_label and TX_ACTIVE_STATE_RE.match(current_state_label):
                is_in_active = True
            elif in_default:
                any_active = any(
                    TX_ACTIVE_STATE_RE.search(l)
                    for l in lines
                    if re.search(r"\w+\s*:", l.strip())
                )
                if any_active:
                    is_in_active = True
            elif case_depth == 0:
                if any(TX_ACTIVE_STATE_RE.search(l) for l in lines):
                    is_in_active = True

            if is_in_active:
                result.passed = False
                ctx = f"state={current_state_label}" if current_state_label else "global scope"
                result.findings.append(Finding(
                    "TX_ABORT_DURING_TRANSMISSION", "ERROR",
                    f"Break/event handler at {ctx} can abort TX during active "
                    f"transmission. Mid-byte abort produces invalid pulses. "
                    f"Guard with ``if (state == IDLE)`` or move to idle-only states.",
                    file=str(f.name), line=i,
                ))

    if result.passed:
        result.findings.append(Finding(
            "PASS", "INFO", "TX modules do not abort during active transmission.",
        ))

    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("rtl_dir", help="RTL directory to scan")
    ap.add_argument("--json", nargs="?", const="-", default=None, metavar="PATH")
    args = ap.parse_args(argv)

    target = Path(args.rtl_dir)
    if not target.exists():
        print(f"error: not found: {target}", file=sys.stderr)
        return _vx.RC_VACUOUS

    result = audit(target)
    report = {
        "program": result.program,
        "passed": result.passed,
        "findings": [asdict(f) for f in result.findings],
        "summary": result.summary,
    }

    if args.json:
        txt = json.dumps(report, indent=2)
        if args.json == "-":
            print(txt)
        else:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(txt + "\n")
    else:
        for f in result.findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line}: {f.message}")
        errors = [f for f in result.findings if f.severity == "ERROR"]
        verdict = ("FAIL" if errors
                   else "VACUOUS (nothing examined)"
                   if _vx.summary_is_skipped(result.summary) else "PASS")
        print(f"\n{len(errors)} error(s); verdict: {verdict}")

    # #515 — routed from the gate's OWN `summary["skipped"]`, never from the
    # printed text. `no_tx_modules` is the dominant outcome across the tracked
    # corpus (320 of 327 project roots); every one of those was being counted
    # as a real pass over a transmission path that does not exist.
    skipped = _vx.summary_is_skipped(result.summary)
    if result.passed and skipped:
        _vx.announce_vacuous(result.program,
                             str(result.summary.get("reason", "unspecified")))
    return _vx.exit_code(result.passed, skipped)


if __name__ == "__main__":
    sys.exit(main())
