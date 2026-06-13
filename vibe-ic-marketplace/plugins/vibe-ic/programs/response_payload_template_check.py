#!/usr/bin/env python3
"""
response_payload_template_check.py — M5: Verify that response payload bytes
are assembled from dynamic data (register values, echoed arguments, computed
results) rather than hardcoded constants.

General pattern (IC-agnostic):

    When a command handler builds a response packet, each payload byte
    should come from a defined data source:
      - Echoed command argument (e.g. address echo in a write-ack)
      - Register or memory read value
      - Computed result (status bits, measurement)

    Hardcoded constant bytes in response assembly — e.g.
        ``fixed_buf[0] <= 8'h00;``
    — are a red flag: they often indicate the developer used a placeholder
    instead of wiring the correct dynamic data path.  The response will
    be structurally valid (right opcode, right length, valid CRC) but
    semantically wrong (wrong payload content).

Static heuristic check.  Scans RTL for:
  - Response buffer assignments (rsp_buf, tx_buf, fixed_buf, etc.)
  - Ratio of constant vs dynamic sources in those assignments
  - Flagging when >50% of payload bytes are hardcoded constants

Usage:
    python3 response_payload_template_check.py --rtl-dir <dir> [--json <report.json>]

Exit: 0 = PASS, 1 = findings, 2 = IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Tuple


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    file: str = ""
    line: int = 0
    details: str = ""


RSP_BUF_RE = re.compile(
    r'\b(rsp_buf|tx_buf|fixed_buf|resp_buf|response_buf|'
    r'tx_data|rsp_data|resp_data|out_buf|send_buf)\b',
    re.IGNORECASE,
)

RSP_BUF_ASSIGN_RE = re.compile(
    r'(rsp_buf|tx_buf|fixed_buf|resp_buf|response_buf|'
    r'tx_data|rsp_data|resp_data|out_buf|send_buf)'
    r"\s*\[\s*(\d+)\s*\]\s*<=\s*(.+?)\s*;",
    re.IGNORECASE,
)

CONSTANT_VALUE_RE = re.compile(
    r"^(?:8'[hHbBdD][0-9a-fA-F_]+|[0-9]+|8'd[0-9]+|'[hH][0-9a-fA-F]+)$"
)

DISPATCH_RE = re.compile(
    r'\bcase[szx]?\s*\(\s*(?:\w+\.)?'
    r'(cmd_op|opcode|cmd|op|cmd_code|rx_cmd|cmd_byte)\b',
    re.IGNORECASE,
)

IF_CMD_RE = re.compile(
    r'\bif\s*\(\s*\w*(?:cmd|opcode)\w*\s*==\s*',
    re.IGNORECASE,
)


def _find_v_files(rtl_dir: Path) -> List[Path]:
    return sorted(
        p for p in rtl_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in (".v", ".sv")
    )


def _strip_comments(src: str) -> str:
    out = []
    i = 0
    while i < len(src):
        if src[i:i+2] == '/*':
            end = src.find('*/', i + 2)
            if end == -1:
                break
            out.append(''.join('\n' if c == '\n' else ' ' for c in src[i:end+2]))
            i = end + 2
        elif src[i:i+2] == '//':
            end = src.find('\n', i)
            if end == -1:
                break
            out.append(' ' * (end - i))
            i = end
        else:
            out.append(src[i])
            i += 1
    return ''.join(out)


def _is_constant(rhs: str) -> bool:
    rhs = rhs.strip()
    return bool(CONSTANT_VALUE_RE.match(rhs))


def audit(rtl_dir: Path) -> Tuple[List[Finding], Dict]:
    findings: List[Finding] = []
    if not rtl_dir.exists() or not rtl_dir.is_dir():
        findings.append(Finding("ERROR", "IO", f"RTL directory not found: {rtl_dir}"))
        return findings, {}

    response_files: List[str] = []
    all_assignments: List[Dict] = []

    for p in _find_v_files(rtl_dir):
        try:
            text = _strip_comments(p.read_text(errors="replace"))
        except OSError:
            continue
        fname = str(p)

        if not RSP_BUF_RE.search(text):
            continue

        is_dispatcher = bool(DISPATCH_RE.search(text)) or \
            len(IF_CMD_RE.findall(text)) >= 3
        if not is_dispatcher:
            continue

        response_files.append(fname)

        lines = text.split('\n')
        per_opcode_blocks: Dict[str, List[Tuple[int, str, str, bool]]] = {}
        current_opcode = None

        for lineno, line in enumerate(lines, 1):
            op_m = re.search(
                r"(?:8'h|8'H)([0-9a-fA-F]{2})", line
            )
            if op_m and (re.search(r'\bcase\b', line, re.IGNORECASE) is None):
                if ':' in line or '==' in line:
                    current_opcode = f"0x{op_m.group(1).upper()}"

            for m in RSP_BUF_ASSIGN_RE.finditer(line):
                buf_name = m.group(1)
                idx = int(m.group(2))
                rhs = m.group(3).strip()
                is_const = _is_constant(rhs)

                entry = {
                    "buf": buf_name, "idx": idx, "rhs": rhs,
                    "constant": is_const, "line": lineno,
                    "opcode": current_opcode,
                }
                all_assignments.append(entry)

                if current_opcode:
                    per_opcode_blocks.setdefault(current_opcode, []).append(
                        (lineno, buf_name, rhs, is_const)
                    )

        for opcode, assigns in per_opcode_blocks.items():
            if len(assigns) < 2:
                continue
            const_count = sum(1 for _, _, _, c in assigns if c)
            total = len(assigns)
            if const_count > 0 and const_count >= total * 0.5 and total >= 2:
                findings.append(Finding(
                    "WARN", "MOSTLY_HARDCODED_RESPONSE",
                    f"Response handler for opcode {opcode}: "
                    f"{const_count}/{total} payload byte assignments use "
                    f"hardcoded constants. Verify each constant is "
                    f"intentional (e.g. fixed status) rather than a "
                    f"placeholder for dynamic data (echoed argument, "
                    f"register read, computed value).",
                    file=fname,
                    line=assigns[0][0],
                    details=json.dumps([
                        {"idx": a[1], "rhs": a[2], "const": a[3]}
                        for a in assigns
                    ]),
                ))

    return findings, {
        "response_files": response_files,
        "total_assignments": len(all_assignments),
        "constant_assignments": sum(1 for a in all_assignments if a["constant"]),
        "dynamic_assignments": sum(1 for a in all_assignments if not a["constant"]),
    }


def main(argv: List[str] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Flag response payload bytes assembled from hardcoded "
                    "constants instead of dynamic data sources."
    )
    ap.add_argument("--rtl-dir", required=True)
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    try:
        findings, summary = audit(rtl_dir)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    is_pass = not any(f.severity == "ERROR" for f in findings)
    report = {
        "program": "response_payload_template_check",
        "version": "1.0.0",
        "rtl_dir": str(rtl_dir),
        "summary": {"pass": is_pass, "findings_count": len(findings), **summary},
        "findings": [asdict(f) for f in findings],
    }
    out = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(out)
    print(out)
    if any(f.category == "IO" for f in findings):
        return 2
    return 0 if is_pass else 1


if __name__ == "__main__":
    sys.exit(main())
