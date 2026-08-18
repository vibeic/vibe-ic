#!/usr/bin/env python3
"""
dispatcher_response_size_table_audit.py — v0.114 (BACKLOG-v7 P2.1).

Cross-check `cmd_dispatch.sv` (or any command-response dispatcher RTL)
per-opcode `resp_len` / `rsp_total` assignments against L9 declared
response sizes. Catches off-by-one or wrong size in dispatcher RTL —
one of the v0.108 <benchmark> round-1 bug classes that slipped through.

Why this exists: byte-stream oracle (v0.106 P0.2) checks the actual
response BYTE STREAM matches; this gate is upstream — it checks the
dispatcher's declared `resp_len` per opcode matches the L9 spec
BEFORE simulation. Cheap fast-fail.

Static check (chip-AGNOSTIC):

  1. Find a dispatcher RTL file: `*dispatch*.{v,sv}` containing
     `case (cmd_op | opcode | op_q | cmd_byte ...)` with per-opcode
     resp_len / rsp_total assignments.
  2. Extract per-opcode `resp_len <= N'dM` (or `rsp_total <= N'dM`)
     pairs.
  3. Read L9_INTEGRATION_SPEC.json for `supported_opcodes[].response_size`.
  4. Compare. Mismatches → ERROR with diff table.

Skips gracefully if either source is absent (warning).

Usage:
  python3 dispatcher_response_size_table_audit.py <project_dir> [--json [PATH]]
Exit 0 PASS, 1 FAIL, 2 IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import _path_layout as _pl


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


_OPCODE_CASE_RE = re.compile(
    r"\bcase\s*\(\s*(?:\w+\s*\.\s*)?(cmd_op|opcode|op|op_q|cmd_byte|cmd_code)\b",
    re.IGNORECASE,
)
_RESP_LEN_RE = re.compile(
    r"\b(resp_len|rsp_total|response_len|rsp_len)\s*<=?\s*(\d+)\s*'?[dD]?(\d+)?",
)
_OPCODE_LITERAL_RE = re.compile(r"\b(?:8|7)\s*'\s*[hH]\s*([0-9a-fA-F]+)")


def _find_dispatcher(project: Path) -> Optional[Path]:
    rtl_dir = _pl.rtl_dir(project)
    if not rtl_dir.is_dir():
        return None
    for path in sorted(rtl_dir.rglob("*")):
        if path.suffix.lower() not in (".v", ".sv"):
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        if _OPCODE_CASE_RE.search(text):
            return path
    return None


def _extract_resp_table(rtl_text: str) -> Dict[str, int]:
    """Walk RTL line-by-line. When inside a case branch beginning at
    '8'hXX' / 'CMD_GET_*' label, capture next resp_len assignment."""
    table: Dict[str, int] = {}
    cur_opcode: Optional[str] = None
    for raw in rtl_text.splitlines():
        line = raw.strip()
        # opcode label "8'h74:" or "CMD_GET_ID:"
        op_match = _OPCODE_LITERAL_RE.search(line)
        if op_match:
            cur_opcode = "0x" + op_match.group(1).upper().lstrip("0").rjust(2, "0")
        else:
            cmd_label = re.match(r"^(CMD_[A-Z0-9_]+)\s*:", line)
            if cmd_label:
                cur_opcode = cmd_label.group(1)
        # resp_len assignment
        rl = _RESP_LEN_RE.search(line)
        if rl and cur_opcode:
            # Try to parse the literal — handles `5'd8`, `5'd 8`, `8`
            literal = rl.group(3) or rl.group(2)
            try:
                size = int(literal)
                # Avoid trivial bus-width capture (e.g. 5'd8 captures the 5)
                # The pattern's group(3) is the actual value when "N'dM" form.
                if rl.group(3) is None:
                    size = int(rl.group(2))
                table.setdefault(cur_opcode, size)
            except (TypeError, ValueError):
                pass
    return table


def _load_l9_table(project: Path) -> Dict[str, int]:
    candidates = [
        _pl.generated_docs_dir(project) / "L9_INTEGRATION_SPEC.json",
        _pl.generated_docs_dir(project) / "L9.json",
    ]
    for p in candidates:
        if not p.exists():
            continue
        try:
            d = json.loads(p.read_text())
        except Exception:
            continue
        ops = d.get("supported_opcodes") or d.get("opcodes") or []
        out: Dict[str, int] = {}
        for op in ops:
            if not isinstance(op, dict):
                continue
            code = op.get("opcode") or op.get("code") or op.get("cmd")
            size = op.get("response_size") or op.get("resp_len") or op.get("rsp_total")
            if code is not None and isinstance(size, int):
                # normalise opcode: int → "0xXX", str → upper hex
                if isinstance(code, int):
                    key = f"0x{code:02X}"
                elif isinstance(code, str):
                    key = code.upper().strip()
                    if not key.startswith("0X") and re.fullmatch(r"[0-9A-Fa-f]+", key):
                        key = "0x" + key.zfill(2)
                else:
                    continue
                out[key] = size
        if out:
            return out
    return {}


def main():
    ap = argparse.ArgumentParser(description=(
        "Cross-check dispatcher RTL resp_len per opcode against L9 spec."
    ))
    ap.add_argument("project_dir")
    ap.add_argument("--json", nargs="?", const="-", default=None)
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2

    findings: List[Finding] = []

    dispatcher = _find_dispatcher(project)
    if dispatcher is None:
        # Skip gracefully — no dispatcher means this audit doesn't apply.
        result = {
            "program": "dispatcher_response_size_table_audit",
            "version": "1.0.0",
            "project": str(project),
            "summary": {"skip": True, "reason": "no dispatcher RTL found", "pass": True},
            "findings": [],
        }
        if args.json is None:
            print("[PASS] dispatcher_response_size_table_audit (skip — no dispatcher)")
        elif args.json == "-":
            print(json.dumps(result, indent=2))
        else:
            Path(args.json).write_text(json.dumps(result, indent=2))
            print(f"json: {args.json}")
        return 0

    rtl_text = dispatcher.read_text(errors="replace")
    rtl_table = _extract_resp_table(rtl_text)

    l9_table = _load_l9_table(project)

    if not l9_table:
        result = {
            "program": "dispatcher_response_size_table_audit",
            "version": "1.0.0",
            "project": str(project),
            "summary": {
                "skip": True,
                "reason": "L9 has no supported_opcodes[].response_size table",
                "pass": True,
            },
            "findings": [],
        }
        if args.json is None:
            print("[PASS] dispatcher_response_size_table_audit (skip — no L9 size table)")
        elif args.json == "-":
            print(json.dumps(result, indent=2))
        else:
            Path(args.json).write_text(json.dumps(result, indent=2))
            print(f"json: {args.json}")
        return 0

    diffs: List[Tuple[str, int, int]] = []
    for opcode, l9_size in l9_table.items():
        rtl_size = rtl_table.get(opcode)
        if rtl_size is None:
            findings.append(Finding(
                severity="WARN",
                category="OPCODE_NOT_IN_RTL",
                message=f"L9 declares opcode {opcode} (resp_len={l9_size}) but dispatcher RTL has no resp_len assignment matching",
            ))
        elif rtl_size != l9_size:
            diffs.append((opcode, l9_size, rtl_size))
            findings.append(Finding(
                severity="ERROR",
                category="RESP_LEN_MISMATCH",
                message=f"opcode {opcode}: L9 response_size={l9_size} but dispatcher resp_len={rtl_size}",
            ))

    pass_flag = not any(f.severity == "ERROR" for f in findings)
    result = {
        "program": "dispatcher_response_size_table_audit",
        "version": "1.0.0",
        "project": str(project),
        "summary": {
            "dispatcher_file": str(dispatcher.relative_to(project)),
            "rtl_opcodes_found": len(rtl_table),
            "l9_opcodes_declared": len(l9_table),
            "mismatches": len(diffs),
            "pass": pass_flag,
        },
        "findings": [asdict(f) for f in findings],
    }

    if args.json is None:
        verdict = "PASS" if pass_flag else "FAIL"
        print(f"[{verdict}] dispatcher_response_size_table_audit")
        print(f"  dispatcher: {dispatcher.relative_to(project)}")
        print(f"  RTL opcodes: {len(rtl_table)}, L9 opcodes: {len(l9_table)}")
        print(f"  mismatches: {len(diffs)}")
        for f in findings:
            print(f"  [{f.severity}] {f.category}: {f.message}")
    elif args.json == "-":
        print(json.dumps(result, indent=2))
    else:
        Path(args.json).write_text(json.dumps(result, indent=2))
        print(f"json: {args.json}")

    return 0 if pass_flag else 1


if __name__ == "__main__":
    sys.exit(main())
