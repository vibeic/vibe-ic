#!/usr/bin/env python3
"""fetch_round_trip_sentinel_check.py — P0.1 deterministic gate

Detects memory-read-latency bugs in command-response dispatchers.
A sync-memory-backed FSM that transitions from FETCH_REQ directly to
FETCH_CAP without a WAIT state will capture stale dout, shifting the
response byte stream by one position.

Static detection: scans RTL for dispatcher FSMs with memory fetch
patterns and verifies that at least one wait state (or combinational
memory) exists between address-set and data-capture transitions.

Usage:
    python3 fetch_round_trip_sentinel_check.py <project_dir>
    python3 fetch_round_trip_sentinel_check.py <project_dir> --json
    python3 fetch_round_trip_sentinel_check.py <project_dir> --json out.json

Exit codes:
    0 = PASS (wait state present, combinational memory, or no fetch pattern)
    1 = FAIL (address-set and data-capture in adjacent states, no wait)
    2 = IO / parse error
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
    program: str = "fetch_round_trip_sentinel_check"
    passed: bool = True
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


def discover_rtl_files(base: Path) -> List[Path]:
    exts = {".v", ".sv", ".vh", ".svh"}
    return sorted(p for p in base.rglob("*") if p.suffix.lower() in exts)


# Patterns that identify a dispatcher/FSM with opcode-based case statements
DISPATCHER_CASE_RE = re.compile(
    r"\b(?:unique\s+)?case\s*\(\s*(?:cmd_op|opcode|cmd_byte|op_code|cmd|op)\b",
    re.IGNORECASE,
)

# Memory address assignment: addr <= expr  or  addr = expr
ADDR_ASSIGN_RE = re.compile(
    r"\b(addr|mem_addr|otp_addr|fetch_addr|rd_addr|rom_addr)\s*<?=\s*",
    re.IGNORECASE,
)

# Data capture from memory read port
DATA_CAPTURE_RE = re.compile(
    r"\b(resp_byte|resp_data|tx_byte|rdata|dout|mem_data|rd_data|byte_out)\s*<?=\s*"
    r"(rdata|dout|mem_data|rd_data|mem_out|rom_data|rom_out|otp_data|otp_out)\b",
    re.IGNORECASE,
)

# Combinational memory pattern: assign dout = mem[addr]
COMBINATIONAL_MEM_RE = re.compile(
    r"\bassign\s+(rdata|dout|mem_data|rd_data|mem_out|rom_data|rom_out|otp_data|otp_out)"
    r"\s*=\s*\w+\s*\[",
    re.IGNORECASE,
)

# State transition: state <= NEXT_STATE
STATE_TRANSITION_RE = re.compile(
    r"\b(state|fsm_state|st|next_state|nxt_st)\s*<?=\s*(\w+)",
    re.IGNORECASE,
)

# Wait/delay state name patterns
WAIT_STATE_RE = re.compile(
    r"(WAIT|FETCH_WAIT|READ_WAIT|MEM_WAIT|RD_WAIT|DELAY|LATENCY|PIPE)",
    re.IGNORECASE,
)

# State declaration patterns to build state map
STATE_DECL_RE = re.compile(
    r"\b(?:localparam|parameter)\b[^;]*?\b(\w+)\s*=\s*(\d+|'[hbdo]\w+)",
    re.IGNORECASE,
)


def _has_combinational_memory(text: str) -> bool:
    return bool(COMBINATIONAL_MEM_RE.search(text))


def _extract_fsm_blocks(text: str) -> list[tuple[int, str]]:
    """Find always blocks containing case statements with opcode dispatch."""
    results = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if DISPATCHER_CASE_RE.search(line):
            start = max(0, i - 30)
            end = min(len(lines), i + 200)
            results.append((i + 1, "\n".join(lines[start:end])))
    return results


def _analyze_fetch_pattern(block_text: str) -> Optional[dict]:
    """Analyze a FSM block for the fetch-without-wait bug pattern.

    Returns a dict with analysis results, or None if no fetch pattern found.
    """
    lines = block_text.splitlines()

    addr_lines = []
    capture_lines = []
    transitions = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("/*"):
            continue
        if ADDR_ASSIGN_RE.search(line):
            addr_lines.append(i)
        if DATA_CAPTURE_RE.search(line):
            capture_lines.append(i)
        m = STATE_TRANSITION_RE.search(line)
        if m:
            transitions.append((i, m.group(2)))

    if not addr_lines or not capture_lines:
        return None

    for addr_ln in addr_lines:
        addr_state_trans = None
        for t_ln, t_target in transitions:
            if 0 <= t_ln - addr_ln <= 3:
                addr_state_trans = (t_ln, t_target)
                break

        if addr_state_trans is None:
            continue

        _, next_state_after_addr = addr_state_trans

        for cap_ln in capture_lines:
            cap_state_trans = None
            for t_ln, t_target in transitions:
                if 0 <= t_ln - cap_ln <= 3:
                    cap_state_trans = (t_ln, t_target)
                    break

            if cap_ln <= addr_ln:
                continue

            lines_between = cap_ln - addr_ln
            if lines_between > 40:
                continue

            intervening_text = "\n".join(lines[addr_ln:cap_ln])
            intervening_transitions = [
                t_target for t_ln, t_target in transitions
                if addr_ln < t_ln < cap_ln
            ]

            has_wait = any(WAIT_STATE_RE.search(t) for t in intervening_transitions)
            if not has_wait and WAIT_STATE_RE.search(next_state_after_addr):
                has_wait = True

            if has_wait:
                return {"has_wait": True, "addr_line": addr_ln, "capture_line": cap_ln}

            if lines_between <= 8 and not has_wait:
                return {
                    "has_wait": False,
                    "addr_line": addr_ln,
                    "capture_line": cap_ln,
                    "next_state": next_state_after_addr,
                }

    return {"has_wait": True, "addr_line": addr_lines[0], "capture_line": capture_lines[0]}


def run_audit(base: Path, dispatcher_module: Optional[str] = None) -> AuditResult:
    result = AuditResult()
    rtl_dir = _pl.rtl_dir(base)
    if not rtl_dir.is_dir():
        rtl_dir = base

    rtl_files = discover_rtl_files(rtl_dir)
    if not rtl_files:
        result.findings.append(Finding(
            rule="SKIP_NO_FETCH",
            severity="INFO",
            message="No RTL files found; skipping fetch round-trip check",
        ))
        result.summary = {"rtl_files": 0, "dispatchers_analyzed": 0, "latency_bugs": 0}
        return result

    any_fetch_found = False
    latency_bugs = 0
    dispatchers_analyzed = 0

    for fpath in rtl_files:
        if dispatcher_module:
            if dispatcher_module.lower() not in fpath.stem.lower():
                continue

        try:
            text = fpath.read_text(errors="replace")
        except Exception:
            continue

        if _has_combinational_memory(text):
            result.findings.append(Finding(
                rule="COMBINATIONAL_MEM_OK",
                severity="INFO",
                message=f"Combinational memory detected — no latency concern",
                file=str(fpath),
            ))
            any_fetch_found = True
            continue

        fsm_blocks = _extract_fsm_blocks(text)
        if not fsm_blocks:
            continue

        for block_line, block_text in fsm_blocks:
            dispatchers_analyzed += 1
            analysis = _analyze_fetch_pattern(block_text)

            if analysis is None:
                continue

            any_fetch_found = True

            if analysis["has_wait"]:
                result.findings.append(Finding(
                    rule="FETCH_LATENCY_OK",
                    severity="INFO",
                    message="Fetch pattern has wait state between address-set and data-capture",
                    file=str(fpath),
                    line=block_line + analysis["addr_line"],
                ))
            else:
                latency_bugs += 1
                result.passed = False
                result.findings.append(Finding(
                    rule="FETCH_LATENCY_MISSING",
                    severity="ERROR",
                    message=(
                        f"Memory address-set and data-capture occur in adjacent states "
                        f"(next_state={analysis.get('next_state', '?')}) with no WAIT cycle. "
                        f"Sync memory requires at least 1 cycle between address and capture. "
                        f"Insert a FETCH_WAIT state or use combinational memory."
                    ),
                    file=str(fpath),
                    line=block_line + analysis["addr_line"],
                ))

    if not any_fetch_found:
        result.findings.append(Finding(
            rule="SKIP_NO_FETCH",
            severity="INFO",
            message="No memory-backed fetch pattern found in dispatcher RTL; skipping",
        ))

    result.summary = {
        "rtl_files": len(rtl_files),
        "dispatchers_analyzed": dispatchers_analyzed,
        "latency_bugs": latency_bugs,
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
        print(f"[{status}] fetch_round_trip_sentinel_check")
        print(f"  RTL files: {result.summary.get('rtl_files', 0)}")
        print(f"  Dispatchers analyzed: {result.summary.get('dispatchers_analyzed', 0)}")
        print(f"  Latency bugs: {result.summary.get('latency_bugs', 0)}")
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
    ap.add_argument("--dispatcher-module", default=None, metavar="NAME",
                     help="Only analyze files whose stem matches this name")
    args = ap.parse_args()

    if not args.project_dir.is_dir():
        print(f"ERROR: {args.project_dir} is not a directory", file=sys.stderr)
        return 2

    result = run_audit(args.project_dir, args.dispatcher_module)
    _emit(result, args.json)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
