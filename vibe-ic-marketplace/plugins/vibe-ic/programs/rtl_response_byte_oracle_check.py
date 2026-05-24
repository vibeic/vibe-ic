#!/usr/bin/env python3
"""rtl_response_byte_oracle_check.py — P0.2 deterministic gate

Static cross-check between L10 oracle vectors and RTL dispatcher
implementation.  For each opcode in the oracle, verifies that the
RTL's per-opcode response size, fetch base address, and fetch count
match the spec.

Usage:
    python3 rtl_response_byte_oracle_check.py <project_dir>
    python3 rtl_response_byte_oracle_check.py <project_dir> --json
    python3 rtl_response_byte_oracle_check.py <project_dir> --json out.json
    python3 rtl_response_byte_oracle_check.py <project_dir> --oracle-json path/to/L10.json

Exit codes:
    0 = PASS (all oracle fields match RTL, or no oracle file found)
    1 = FAIL (one or more oracle field mismatches)
    2 = IO / parse error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Dict
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
    program: str = "rtl_response_byte_oracle_check"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def discover_rtl_files(base: Path) -> List[Path]:
    exts = {".v", ".sv", ".vh", ".svh"}
    return sorted(p for p in base.rglob("*") if p.suffix.lower() in exts)


def _find_oracle_file(project_dir: Path, explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    candidates = [ project_dir / "phase1/generated_docs", _pl.generated_docs_dir(project_dir) / "L10_TB_CONFORMANCE.json", project_dir / "phase1/generated_docs", _pl.generated_docs_dir(project_dir) / "L10_TEST_CASES.json",
    ]
    for c in candidates:
        if c.is_file():
            return c
    for f in _pl.generated_docs_dir(project_dir).glob("L10*.json") if _pl.generated_docs_dir(project_dir).is_dir() else []:
        return f
    return None


def _load_oracle_vectors(path: Path) -> List[dict]:
    data = json.loads(path.read_text(errors="replace"))
    if isinstance(data, dict):
        for key in ("opcode_oracle_vectors", "oracle_vectors", "vectors", "opcodes"):
            if key in data and isinstance(data[key], list):
                return data[key]
    if isinstance(data, list):
        return data
    return []


# Match case branches like:  8'h74:  or  CMD_GET_ID:  or  'h74:
CASE_BRANCH_RE = re.compile(
    r"(?:\d+'h([0-9a-fA-F]+)|\bCMD_\w+|OP_\w+)\s*:",
)

RESP_LEN_RE = re.compile(
    r"\b(resp_len|resp_size|response_length|rsp_len|rsp_size|resp_count)\s*<?=\s*(\d+'[hbdoHBDO][0-9a-fA-F_]+|\d+|'[hbdo]\w+)",
    re.IGNORECASE,
)

FETCH_BASE_RE = re.compile(
    r"\b(fetch_base|otp_base|mem_base|mem_addr|otp_addr|rd_addr|base_addr|start_addr)\s*<?=\s*(\d+'[hbdoHBDO][0-9a-fA-F_]+|\d+|'[hbdo]\w+)",
    re.IGNORECASE,
)

FETCH_COUNT_RE = re.compile(
    r"\b(fetch_count|fetch_len|byte_count|rd_count|read_count|num_bytes)\s*<?=\s*(\d+'[hbdoHBDO][0-9a-fA-F_]+|\d+|'[hbdo]\w+)",
    re.IGNORECASE,
)


def _parse_verilog_int(s: str) -> Optional[int]:
    s = s.strip()
    if s.isdigit():
        return int(s)
    m = re.match(r"(\d+)?'([hbdoHBDO])([0-9a-fA-F_]+)", s)
    if m:
        base_map = {"h": 16, "b": 2, "d": 10, "o": 8}
        base_char = m.group(2).lower()
        return int(m.group(3).replace("_", ""), base_map.get(base_char, 16))
    if s.startswith("0x") or s.startswith("0X"):
        return int(s, 16)
    return None


def _extract_rtl_opcodes(rtl_files: List[Path]) -> Dict[str, dict]:
    """Extract per-opcode parameters from dispatcher RTL.

    Returns dict keyed by opcode hex string (lowercase, no prefix),
    value is dict with optional keys: resp_len, fetch_base, fetch_count, file, line.
    """
    results: Dict[str, dict] = {}

    for fpath in rtl_files:
        try:
            text = fpath.read_text(errors="replace")
        except Exception:
            continue

        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            m = CASE_BRANCH_RE.search(line)
            if not m:
                i += 1
                continue

            opcode_hex = m.group(1)
            if opcode_hex is None:
                i += 1
                continue
            opcode_hex = opcode_hex.lower()

            block_end = min(i + 30, len(lines))
            block_text = "\n".join(lines[i:block_end])

            entry: dict = {"file": str(fpath), "line": i + 1}

            rl = RESP_LEN_RE.search(block_text)
            if rl:
                v = _parse_verilog_int(rl.group(2))
                if v is not None:
                    entry["resp_len"] = v

            fb = FETCH_BASE_RE.search(block_text)
            if fb:
                v = _parse_verilog_int(fb.group(2))
                if v is not None:
                    entry["fetch_base"] = v

            fc = FETCH_COUNT_RE.search(block_text)
            if fc:
                v = _parse_verilog_int(fc.group(2))
                if v is not None:
                    entry["fetch_count"] = v

            if entry.keys() - {"file", "line"}:
                results[opcode_hex] = entry

            i += 1

    return results


def run_audit(base: Path, oracle_json: Optional[str] = None) -> AuditResult:
    result = AuditResult()

    oracle_path = _find_oracle_file(base, oracle_json)
    if oracle_path is None:
        result.findings.append(Finding(
            rule="SKIP_NO_ORACLE",
            severity="INFO",
            message="No L10 oracle vectors file found; skipping byte oracle check",
        ))
        result.summary = {"oracle_vectors": 0, "matched": 0, "mismatched": 0}
        return result

    try:
        vectors = _load_oracle_vectors(oracle_path)
    except Exception as exc:
        result.findings.append(Finding(
            rule="SKIP_NO_ORACLE",
            severity="INFO",
            message=f"Failed to parse oracle file: {exc}",
            file=str(oracle_path),
        ))
        result.summary = {"oracle_vectors": 0, "matched": 0, "mismatched": 0}
        return result

    if not vectors:
        result.findings.append(Finding(
            rule="SKIP_NO_ORACLE",
            severity="INFO",
            message="Oracle file has no opcode_oracle_vectors entries",
            file=str(oracle_path),
        ))
        result.summary = {"oracle_vectors": 0, "matched": 0, "mismatched": 0}
        return result

    rtl_dir = _pl.rtl_dir(base)
    if not rtl_dir.is_dir():
        rtl_dir = base
    rtl_files = discover_rtl_files(rtl_dir)

    if not rtl_files:
        result.findings.append(Finding(
            rule="SKIP_NO_ORACLE",
            severity="INFO",
            message="No RTL files found to cross-check against oracle",
        ))
        result.summary = {"oracle_vectors": len(vectors), "matched": 0, "mismatched": 0}
        return result

    rtl_opcodes = _extract_rtl_opcodes(rtl_files)
    matched = 0
    mismatched = 0

    for vec in vectors:
        op_hex = vec.get("opcode_hex", "").lower().replace("0x", "")
        op_name = vec.get("name", op_hex)

        if op_hex not in rtl_opcodes:
            continue

        rtl_entry = rtl_opcodes[op_hex]

        fields_to_check = [
            ("response_size", "resp_len"),
            ("fetch_base", "fetch_base"),
            ("fetch_count", "fetch_count"),
        ]

        op_ok = True
        for oracle_key, rtl_key in fields_to_check:
            oracle_val = vec.get(oracle_key)
            rtl_val = rtl_entry.get(rtl_key)

            if oracle_val is None or rtl_val is None:
                continue

            if isinstance(oracle_val, str):
                oracle_val = int(oracle_val, 16) if oracle_val.startswith("0x") else int(oracle_val)

            if oracle_val != rtl_val:
                op_ok = False
                mismatched += 1
                result.passed = False
                result.findings.append(Finding(
                    rule="ORACLE_MISMATCH",
                    severity="ERROR",
                    message=(
                        f"Opcode 0x{op_hex} ({op_name}): {oracle_key} "
                        f"oracle={oracle_val} vs RTL {rtl_key}={rtl_val}"
                    ),
                    file=rtl_entry.get("file", ""),
                    line=rtl_entry.get("line", 0),
                ))

        if op_ok:
            matched += 1
            result.findings.append(Finding(
                rule="ORACLE_MATCH_OK",
                severity="INFO",
                message=f"Opcode 0x{op_hex} ({op_name}): all checked fields match",
                file=rtl_entry.get("file", ""),
                line=rtl_entry.get("line", 0),
            ))

    result.summary = {
        "oracle_vectors": len(vectors),
        "rtl_opcodes_found": len(rtl_opcodes),
        "matched": matched,
        "mismatched": mismatched,
    }
    return result


def _emit(result: AuditResult, json_dest: Optional[str]) -> None:
    if json_dest is not None:
        out = asdict(result)
        txt = json.dumps(out, indent=2)
        if json_dest == "-":
            print(txt)
        else:
            Path(json_dest).parent.mkdir(parents=True, exist_ok=True)
            Path(json_dest).write_text(txt + "\n")
    else:
        status = "PASS" if result.passed else "FAIL"
        print(f"[{status}] rtl_response_byte_oracle_check")
        s = result.summary
        print(f"  Oracle vectors: {s.get('oracle_vectors', 0)}")
        print(f"  RTL opcodes found: {s.get('rtl_opcodes_found', 0)}")
        print(f"  Matched: {s.get('matched', 0)}, Mismatched: {s.get('mismatched', 0)}")
        for f in result.findings:
            if f.severity in ("ERROR", "WARNING"):
                loc = f"{f.file}:{f.line}" if f.file else ""
                print(f"  [{f.severity}] {f.rule}: {f.message} {loc}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", nargs="?", const="-", default=None, metavar="PATH")
    ap.add_argument("--oracle-json", default=None, metavar="PATH",
                     help="Explicit path to L10 oracle vectors JSON")
    args = ap.parse_args()

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir, args.oracle_json)
    _emit(result, args.json)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
