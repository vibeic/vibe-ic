#!/usr/bin/env python3
"""
dispatch_register_default_reset_check.py — Response register reset at frame boundaries.

Generic pattern (applies to any multi-frame FSM dispatcher):
  When an FSM dispatches multiple response frames, registers used to
  build the response (rsp_data, rsp_len, rsp_crc, tx_byte, frame_*,
  resp_*) may leak values from a previous frame into the next if they
  are not explicitly reset at the start of each new dispatch cycle.

Real occurrence (v103 fresh-agent run):
  dispatcher.v had `rsp_total` set to 4 in the E0-handler but the
  D_FETCH loop only ran once because `rsp_idx` was never cleared
  between frames. The second E0 response reused stale rsp_bytes from
  the first, producing a wrong CRC → tester FAIL.

Rule enforced (heuristic)
-------------------------
For each module, find response-building registers:
  - Names matching: rsp_*, tx_*, resp_*, frame_*
  - That appear on the LHS of NBA assignments (`<=`)
For each such register, verify at least one of:
  1. It gets an explicit reset in the synchronous reset block
     (`if (!rst_n)` or `if (rst)` → reg <= 0/default)
  2. It has a default assignment at the top of the always block
     before any case/if branches
If neither is found, the register may leak across frames.

This is a lint heuristic, not a formal proof. Silence individual
findings with a `// dispatch-reset-ok` trailing comment on the
register declaration.

Usage
-----
    dispatch_register_default_reset_check.py <rtl_file_or_dir> [--json]

Exit codes
----------
    0 = no suspicious patterns (PASS)
    1 = one or more unresettable response registers (FAIL)
    2 = IO / argument error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gate_utils import dir_parts_excluded  # shared RTL-scope contract


@dataclass
class Finding:
    severity: str
    rule: str
    file: str
    line: int
    register: str
    message: str


RSP_REG_RE = re.compile(
    r"\b((?:rsp|resp|tx|frame)_[a-zA-Z0-9_]*)\b"
)

NBA_ASSIGN_RE = re.compile(
    r"\b((?:rsp|resp|tx|frame)_[a-zA-Z0-9_]*)\s*<="
)

ALWAYS_HEAD_RE = re.compile(
    r"always\s*@\s*\(\s*posedge\b[^)]*\)\s*begin\b",
)

SYNC_RESET_RE = re.compile(
    r"if\s*\(\s*!?\s*(?:rst_n|rst|reset_n|reset|rstn)\s*\)"
)

SILENCE_RE = re.compile(r"//\s*dispatch-reset-ok\b")


def _strip_comments(src: str) -> tuple[str, set[int]]:
    src_no_block = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    silence_lines = set()
    for i, line in enumerate(src_no_block.splitlines(), start=1):
        if SILENCE_RE.search(line):
            silence_lines.add(i)
    analysis = re.sub(r"//[^\n]*", "", src_no_block)
    return analysis, silence_lines


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


def _line_number_of(src: str, offset: int) -> int:
    return src.count("\n", 0, offset) + 1


def _find_reset_block_regs(body: str) -> set[str]:
    """Find registers that are assigned inside a synchronous reset block."""
    regs = set()
    for m in SYNC_RESET_RE.finditer(body):
        rst_start = m.end()
        depth = 0
        in_block = False
        for tok in re.finditer(r"\b(begin|end)\b|;", body[rst_start:]):
            if tok.group(0) == "begin":
                depth += 1
                in_block = True
            elif tok.group(0) == "end":
                depth -= 1
                if depth <= 0 and in_block:
                    block_end = rst_start + tok.end()
                    rst_body = body[rst_start:block_end]
                    for a in NBA_ASSIGN_RE.finditer(rst_body):
                        regs.add(a.group(1))
                    break
            elif tok.group(0) == ";" and depth == 0 and not in_block:
                rst_body = body[rst_start:rst_start + tok.end()]
                for a in NBA_ASSIGN_RE.finditer(rst_body):
                    regs.add(a.group(1))
                break
    return regs


def _find_default_assigned_regs(body: str) -> set[str]:
    """Find registers with default assignments before any case/if."""
    regs = set()
    first_branch = len(body)
    for kw in (r"\bcase\b", r"\bcasez\b", r"\bcasex\b", r"\bif\b"):
        m = re.search(kw, body)
        if m and m.start() < first_branch:
            first_branch = m.start()
    preamble = body[:first_branch]
    for a in NBA_ASSIGN_RE.finditer(preamble):
        regs.add(a.group(1))
    return regs


def check_file(path: Path) -> list[Finding]:
    raw = path.read_text(errors="replace")
    src, silence_lines = _strip_comments(raw)

    findings: list[Finding] = []

    silenced_regs = set()
    for i, line in enumerate(raw.splitlines(), start=1):
        if SILENCE_RE.search(line):
            for m in RSP_REG_RE.finditer(line):
                silenced_regs.add(m.group(1))

    for bs, be in _find_always_blocks(src):
        body = src[bs:be]

        assigned_regs = set()
        reg_first_line = {}
        for m in NBA_ASSIGN_RE.finditer(body):
            reg = m.group(1)
            assigned_regs.add(reg)
            if reg not in reg_first_line:
                reg_first_line[reg] = _line_number_of(src, bs + m.start())

        if not assigned_regs:
            continue

        reset_regs = _find_reset_block_regs(body)
        default_regs = _find_default_assigned_regs(body)
        safe_regs = reset_regs | default_regs

        for reg in sorted(assigned_regs - safe_regs - silenced_regs):
            line_no = reg_first_line.get(reg, _line_number_of(src, bs))
            findings.append(Finding(
                "ERROR", "dispatch_register_no_reset",
                str(path), line_no, reg,
                f"Response register `{reg}` is assigned in FSM states "
                f"but has no reset in the synchronous reset block and "
                f"no default assignment before case/if branches. Values "
                f"may leak across dispatch frames. Fix: add `{reg} <= 0;` "
                f"(or appropriate default) in the reset block, or add a "
                f"default assignment at the top of the always block. "
                f"Silence with `// dispatch-reset-ok` on the reg declaration.",
            ))

    return findings


def collect_files(path: Path) -> list[Path]:
    """RTL sources under `path`, skipping the flow's own build/output trees.

    This walked `path.rglob("*")` with NO exclusion of any kind. Given a PROJECT
    directory — which is how the phase-2 umbrella invokes it — that reads every
    emitted netlist in the tree.

    MEASURED, edge_llm_accel x nangate45, this collector against the SAME
    project as the tree's two other RTL collectors, at the same moment:

        rtl_scan_scope.authoritative_rtl_files      6 files       51,587 bytes
        gate_utils.find_rtl_files                  11 files  696,685,033 bytes
        collect_files (here)                       35 files  1,735,802,924 bytes

    A factor of 33,647. The 348 MB gate-level netlist is read FOUR times — as
    `phase2/stage2/synth/netlist.v`, as `netlist_yosys.v` beside it, and once
    more under each of the two `steps/` publication copies. Standalone,
    `/usr/bin/time`: 39.0 s and 2.33 GB RSS to lint 3 files' worth of real RTL.
    Under the umbrella's per-gate budget it TIMED OUT, and the phase-2 umbrella
    FAIL halted the flow before place-and-route.

    It is also semantically wrong for this consumer: a reset gap in a response
    register is a property of authored RTL, and a flattened NAND/NOR/DFF netlist
    has no such register to examine. The gate was paying 33,000x to read files
    that cannot answer the question it asks.

    Exclusion is delegated to `gate_utils.dir_parts_excluded` rather than to a
    fourth private copy — three collectors with three different policies is how
    this defect survived the fix that added `steps` to only one of them. An
    explicit FILE argument is still honored verbatim, so pointing the gate at a
    netlist on purpose still works.
    """
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(
            p for p in path.rglob("*")
            if p.is_file() and p.suffix in (".v", ".sv", ".vh")
            and not dir_parts_excluded(p.relative_to(path).parts[:-1])
        )
    return []


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Lint for response-register reset gaps in RTL FSMs.",
    )
    ap.add_argument("target", help="RTL file or directory.")
    ap.add_argument("--json", nargs='?', const='-', default=None, metavar='PATH',
                    help="Emit JSON. With PATH writes to file; bare flag prints to stdout.")
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
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line} ({f.register})")
            print(f"        {f.message}")
        print(f"\n{len(errors)} error(s) across {len(files)} file(s)")
        print("PASS" if not errors else "FAIL")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
