#!/usr/bin/env python3
"""break_framing_vs_l3_check.py — Verify RX command parser uses break-to-break
framing when L3 CMD_PROTOCOL specifies break-delimited frames.

THE PROBLEM
-----------
Half-duplex single-wire protocols (AID-bus, etc.) delimit frames with break
pulses. A correct RX command parser collects all bytes between two breaks,
validates CRC at the frame boundary, then dispatches. An INCORRECT parser
pre-computes ``expected_len`` per opcode and dispatches when byte count
matches — this silently drops frames whose payload length differs from the
template (e.g. tester sends padding or variable-length payloads).

The v0.108 fresh-agent <chip-class> run hit exactly this: rx_cmd.v used
expected-length framing, silently dropping every <half-duplex-tester> command frame.
RTL compiled, synthesized, passed lint, passed all structural gates, but
returned ``02 02 02 …`` (FAIL) on real hardware.

HEURISTIC
---------
1. Parse ``generated_docs/L3_CMD_PROTOCOL.json`` for break-delimiter
   indication (``"delimiter"`` key containing ``"break"`` or
   ``"frame_format"`` mentioning ``break``).
2. Find the RX command module (filename matching ``rx_cmd*`` or module
   containing ``cmd_valid`` / ``cmd_opcode`` outputs).
3. Anti-pattern scan:
   - ``expected_len`` / ``exp_len`` / ``frame_len`` assigned per-opcode
     (case statement setting a length variable).
   - Frame completion ``byte_count == expected_len`` or
     ``rx_cnt >= exp_len``.
4. Required-pattern scan:
   - Break signal (``rx_break`` / ``brk`` / ``break_detect``) used as
     frame boundary → dispatch / CRC-validate.
5. If anti-pattern found OR required pattern missing → FAIL.

USAGE
-----
    python3 break_framing_vs_l3_check.py <project_dir> [--json report.json]

EXIT CODES
----------
    0 — PASS (break-framing consistent with L3, or not a break-framed protocol)
    1 — FAIL (expected-length framing detected in a break-delimited protocol)
    2 — IO / argument error
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


@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""
    line: int = 0


@dataclass
class AuditResult:
    program: str = "break_framing_vs_l3_check"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _is_break_protocol(l3_path: Path) -> bool:
    try:
        d = json.loads(l3_path.read_text(errors="replace"))
    except (OSError, json.JSONDecodeError):
        return False
    text = json.dumps(d).lower()
    return "break" in text and any(
        kw in text for kw in ("delimiter", "frame_format", "frame_boundary",
                               "break_delimited", "break-to-break")
    )


def _find_rx_cmd_files(rtl_dir: Path) -> List[Path]:
    files = []
    for p in sorted(list(rtl_dir.rglob("*.v")) + list(rtl_dir.rglob("*.sv"))):
        name = p.stem.lower()
        if "rx_cmd" in name or "rx_command" in name or "cmd_parser" in name:
            files.append(p)
    if files:
        return files
    for p in sorted(list(rtl_dir.rglob("*.v")) + list(rtl_dir.rglob("*.sv"))):
        try:
            txt = p.read_text(errors="replace")
        except OSError:
            continue
        if re.search(r"\bcmd_valid\b", txt) and re.search(r"\bcmd_opcode\b", txt):
            files.append(p)
    return files


EXPECTED_LEN_RE = re.compile(
    r"\b(expected_len|exp_len|frame_len|pkt_len|expected_bytes)\b",
    re.IGNORECASE,
)

LEN_COMPARE_RE = re.compile(
    r"\b(byte_count|rx_cnt|byte_cnt|frame_cnt)\s*(==|>=)\s*"
    r"(expected_len|exp_len|frame_len|pkt_len)\b",
    re.IGNORECASE,
)

BREAK_DISPATCH_RE = re.compile(
    r"\b(rx_break|brk|break_detect|break_seen|got_break)\b",
    re.IGNORECASE,
)


def audit(project_dir: Path) -> AuditResult:
    result = AuditResult()
    rtl_dir = _pl.rtl_dir(project_dir)
    if not rtl_dir.is_dir():
        result.summary = {"skipped": True, "reason": "no_rtl_dir"}
        return result

    l3_path = _pl.generated_docs_dir(project_dir) / "L3_CMD_PROTOCOL.json"
    if not l3_path.exists():
        result.summary = {"skipped": True, "reason": "no_L3_json"}
        result.findings.append(Finding(
            "INFO", "SKIP", "No L3_CMD_PROTOCOL.json — cannot determine framing type.",
        ))
        return result

    if not _is_break_protocol(l3_path):
        result.summary = {"skipped": True, "reason": "not_break_protocol"}
        result.findings.append(Finding(
            "INFO", "SKIP", "L3 does not indicate break-delimited framing.",
        ))
        return result

    rx_files = _find_rx_cmd_files(rtl_dir)
    if not rx_files:
        result.summary = {"skipped": True, "reason": "no_rx_cmd_module"}
        result.findings.append(Finding(
            "WARN", "NO_RX_CMD", "Could not find RX command module in RTL.",
        ))
        return result

    result.summary = {"skipped": False, "rx_files": [str(f.name) for f in rx_files]}

    for rx_file in rx_files:
        try:
            raw = rx_file.read_text(errors="replace")
        except OSError:
            continue
        text = _strip_comments(raw)
        lines = text.splitlines()

        for i, line in enumerate(lines, 1):
            if EXPECTED_LEN_RE.search(line):
                result.passed = False
                result.findings.append(Finding(
                    "EXPECTED_LEN_ANTIPATTERN", "ERROR",
                    f"Expected-length variable detected in break-delimited protocol. "
                    f"Use break-to-break framing instead of pre-computed frame length.",
                    file=str(rx_file.name), line=i,
                ))

            if LEN_COMPARE_RE.search(line):
                result.passed = False
                result.findings.append(Finding(
                    "LEN_COMPARE_ANTIPATTERN", "ERROR",
                    f"Frame completion based on byte_count == expected_len. "
                    f"Break-delimited protocols must use break events as frame "
                    f"boundaries, not pre-computed lengths.",
                    file=str(rx_file.name), line=i,
                ))

        has_break_dispatch = bool(BREAK_DISPATCH_RE.search(text))
        if not has_break_dispatch:
            result.passed = False
            result.findings.append(Finding(
                "MISSING_BREAK_DISPATCH", "ERROR",
                f"No break signal reference found in RX command module. "
                f"Break-delimited protocol requires break-to-break framing.",
                file=str(rx_file.name), line=0,
            ))

    if result.passed:
        result.findings.append(Finding(
            "PASS", "INFO", "RX command module uses break-to-break framing.",
        ))

    return result


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--json", nargs="?", const="-", default=None, metavar="PATH")
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"error: not a directory: {project}", file=sys.stderr)
        return 2

    result = audit(project)
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
        print(f"\n{len(errors)} error(s); verdict: {'FAIL' if errors else 'PASS'}")

    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
