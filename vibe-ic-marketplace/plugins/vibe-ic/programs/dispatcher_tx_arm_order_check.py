#!/usr/bin/env python3
"""
dispatcher_tx_arm_order_check.py — TX handshake arm-before-data race.

Generic pattern (applies to any FSM-to-PHY handshake):
  When an FSM asserts a TX handshake signal (`tx_arm`, `tx_start`,
  `tx_valid`, `tx_en`, `tx_trigger`, `phy_start`) in the SAME state
  and SAME always block where the TX data registers (`tx_byte`,
  `tx_data`, `tx_len`, `tx_payload`, `phy_data`) are assigned via
  NBA (`<=`), the PHY may latch stale data.

  Verilog NBA semantics: all `<=` in the same always evaluation
  update simultaneously at end-of-timestep. The PHY sees `tx_arm`
  go high on the SAME edge the data changes — but its own posedge
  sampling captures the PREVIOUS data values. The fix is to load
  data in state S_LOAD and assert arm in the NEXT state S_TX.

Rule enforced (heuristic)
-------------------------
In each always block:
  1. Find assignments to a TX-arm signal (`<arm> <= 1`).
  2. Find assignments to TX-data registers (`<data> <= ...`).
  3. If both appear in the same case-branch (same FSM state),
     flag as ERROR — the data and arm are in the same NBA group.
  4. PASS if arm is in a different state than all data assignments,
     or if no arm signal exists.

Silence with `// tx-arm-order-ok` on the arm assignment line.

Usage
-----
    dispatcher_tx_arm_order_check.py <rtl_file_or_dir> [--json]

Exit codes
----------
    0 = PASS
    1 = FAIL (arm-before-data race detected)
    2 = IO / argument error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class Finding:
    severity: str
    rule: str
    file: str
    line: int
    arm_signal: str
    data_signals: list[str]
    message: str


_ARM_TOKENS = (
    "tx_arm", "tx_start", "tx_valid", "tx_en", "tx_trigger",
    "phy_start", "phy_arm", "phy_valid",
)

_DATA_TOKENS = (
    "tx_byte", "tx_data", "tx_len", "tx_payload", "tx_frame",
    "phy_data", "phy_byte", "rsp_byte", "rsp_data",
)

ALWAYS_HEAD_RE = re.compile(
    r"always\s*@\s*\(\s*posedge\b[^)]*\)\s*begin\b",
)

SILENCE_RE = re.compile(r"//\s*tx-arm-order-ok\b")

ARM_ASSERT_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _ARM_TOKENS) + r")\s*<=\s*1\b"
)

DATA_ASSIGN_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _DATA_TOKENS) +
    r"(?:\[[^\]]*\])?)\s*<=\s*"
)


def _find_always_blocks(src: str):
    for head in ALWAYS_HEAD_RE.finditer(src):
        body_start = head.end()
        depth = 1
        pos = body_start
        for tok in re.finditer(r"\b(begin|end)\b", src[pos:]):
            if tok.group(1) == "begin":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    yield body_start, pos + tok.start()
                    break


def _find_case_branches(body: str):
    """Yield (branch_start, branch_end) for each case item in a case block."""
    case_re = re.compile(r"\bcase\s*\(", re.IGNORECASE)
    item_re = re.compile(
        r"(?:^|\n)\s*(?:[A-Za-z_][A-Za-z0-9_]*|'[hbdHBD][0-9a-fA-F_]+|[0-9]+)\s*:\s*",
    )
    default_re = re.compile(r"(?:^|\n)\s*default\s*:\s*")
    endcase_re = re.compile(r"\bendcase\b")

    for cm in case_re.finditer(body):
        case_start = cm.end()
        ecm = endcase_re.search(body, case_start)
        if not ecm:
            continue
        case_body = body[case_start:ecm.start()]
        items = list(item_re.finditer(case_body))
        defaults = list(default_re.finditer(case_body))
        all_items = sorted(items + defaults, key=lambda m: m.start())
        for i, it in enumerate(all_items):
            branch_start = it.end()
            if i + 1 < len(all_items):
                branch_end = all_items[i + 1].start()
            else:
                branch_end = len(case_body)
            yield case_start + branch_start, case_start + branch_end


def _line_number_of(src: str, offset: int) -> int:
    return src.count("\n", 0, offset) + 1


def _strip_comments(src: str) -> tuple[str, set[int]]:
    src_no_block = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    silence_lines = set()
    for i, line in enumerate(src_no_block.splitlines(), start=1):
        if SILENCE_RE.search(line):
            silence_lines.add(i)
    analysis = re.sub(r"//[^\n]*", "", src_no_block)
    return analysis, silence_lines


def check_file(path: Path) -> list[Finding]:
    raw = path.read_text(errors="replace")
    src, silence_lines = _strip_comments(raw)

    findings: list[Finding] = []

    for bs, be in _find_always_blocks(src):
        body = src[bs:be]

        arm_matches = list(ARM_ASSERT_RE.finditer(body))
        data_matches = list(DATA_ASSIGN_RE.finditer(body))

        if not arm_matches or not data_matches:
            continue

        branches = list(_find_case_branches(body))
        if not branches:
            for am in arm_matches:
                arm_line = _line_number_of(src, bs + am.start())
                if arm_line in silence_lines:
                    continue
                data_names = sorted(set(dm.group(1) for dm in data_matches))
                findings.append(Finding(
                    "ERROR", "tx_arm_data_same_block",
                    str(path), arm_line, am.group(1), data_names,
                    f"`{am.group(1)}` asserted in the same always block as "
                    f"data assignments ({', '.join(data_names)}) with no FSM "
                    f"state structure — arm and data are in the same NBA group.",
                ))
            continue

        for am in arm_matches:
            arm_offset = am.start()
            arm_line = _line_number_of(src, bs + arm_offset)
            if arm_line in silence_lines:
                continue

            arm_branch = None
            for b_start, b_end in branches:
                if b_start <= arm_offset < b_end:
                    arm_branch = (b_start, b_end)
                    break

            if arm_branch is None:
                continue

            collocated_data = []
            for dm in data_matches:
                if arm_branch[0] <= dm.start() < arm_branch[1]:
                    collocated_data.append(dm.group(1))

            if collocated_data:
                data_names = sorted(set(collocated_data))
                findings.append(Finding(
                    "ERROR", "tx_arm_data_same_state",
                    str(path), arm_line, am.group(1), data_names,
                    f"`{am.group(1)} <= 1` is in the same FSM state as "
                    f"data assignments ({', '.join(data_names)}). The PHY "
                    f"latches stale data because NBA updates are simultaneous. "
                    f"Fix: load data in state S_LOAD, assert arm in S_TX.",
                ))

    return findings


def collect_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(
            p for p in path.rglob("*")
            if p.is_file() and p.suffix in (".v", ".sv", ".vh")
        )
    return []


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Lint for TX arm-before-data races in RTL FSMs.",
    )
    ap.add_argument("target", help="RTL file or directory.")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH',
                    help="Emit JSON. Bare flag prints to stdout; with PATH writes to file.")
    args = ap.parse_args()

    target = Path(args.target)
    if not target.exists():
        print(f"error: not found: {target}", file=sys.stderr)
        return 2

    files = collect_files(target)
    if not files:
        print(f"error: no .v/.sv/.vh files under {target}", file=sys.stderr)
        return 2

    all_findings: list[Finding] = []
    for f in files:
        all_findings.extend(check_file(f))
    errors = [f for f in all_findings if f.severity == "ERROR"]

    if args.json:
        _txt = json.dumps({
            "target": str(target),
            "scanned": len(files),
            "total_findings": len(all_findings),
            "errors": len(errors),
            "findings": [asdict(f) for f in all_findings],
            "verdict": "PASS" if not errors else "FAIL",
        }, indent=2)
        if args.json == '-':
            print(_txt)
        else:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(_txt + "\n")
    else:
        for f in all_findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line} ({f.arm_signal})")
            print(f"        {f.message}")
        print(f"\n{len(errors)} error(s) across {len(files)} file(s)")
        print("PASS" if not errors else "FAIL")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
