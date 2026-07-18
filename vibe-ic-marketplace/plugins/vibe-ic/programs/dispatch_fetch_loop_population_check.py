#!/usr/bin/env python3
"""
dispatch_fetch_loop_population_check.py — Stub multi-frame fetch loop detector.

Generic pattern (applies to any protocol dispatcher FSM):
  When a protocol declares multiple response frames per command
  (rsp_total > 1), the RTL dispatcher FSM needs a fetch loop that
  iterates over each frame.  A common fresh-agent bug is to implement
  a "stub D_FETCH" state that only fetches one frame regardless of
  rsp_total, causing truncated multi-frame responses.

Detection heuristic
-------------------
For each module that declares a register/wire matching a multi-frame
total pattern (rsp_total, resp_total, frame_count, num_responses,
rsp_cnt_max, total_frames):

  1. Check whether a loop / counter-decrement / state re-entry exists
     that compares an index against the total before exiting.
  2. FLAG if the total register exists but no iteration logic is found.
  3. PASS silently if no multi-frame registers found (single-frame
     protocol — not applicable).

Usage
-----
    dispatch_fetch_loop_population_check.py <rtl_dir> [--json [PATH]]

Exit codes
----------
    0 = PASS (all multi-frame dispatchers properly iterate, or not applicable)
    1 = FAIL (stub fetch detected)
    2 = IO / argument error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

# Kimi-scale fix — this gate audits AUTHORED RTL SOURCE. Collection routes
# through the shared collector (canonical phase2/stage1/rtl preferred;
# generated netlist/sim/verify outputs + >8MB files excluded on fallback) so a
# 342 MB emitted netlist can never enter the char-level comment strip again
# (see _specrtl_common.rtl_source_files for the full scale rationale).
try:
    from _specrtl_common import rtl_source_files
except ImportError:                      # packaged relative import
    from ._specrtl_common import rtl_source_files


@dataclass
class Finding:
    severity: str
    rule: str
    file: str
    line: int
    register: str
    message: str


MULTI_FRAME_TOTAL_RE = re.compile(
    r"\b(rsp_total|resp_total|frame_count|num_responses|rsp_cnt_max|total_frames"
    r"|response_count|rsp_num|frame_total|nframes)\b",
    re.IGNORECASE,
)

ITERATION_PATTERNS = [
    re.compile(r"\b(rsp_idx|rsp_index|frame_idx|frame_index|resp_idx|fetch_cnt"
               r"|fetch_count|rsp_cnt|frame_cnt|resp_cnt|rsp_step)\b", re.IGNORECASE),
    re.compile(r"<=\s*\w+\s*[\-\+]\s*1\b"),
    re.compile(r"<\s*(rsp_total|resp_total|frame_count|num_responses|rsp_cnt_max"
               r"|total_frames|response_count|rsp_num|frame_total|nframes)\b",
               re.IGNORECASE),
    re.compile(r"!=\s*(rsp_total|resp_total|frame_count|num_responses|rsp_cnt_max"
               r"|total_frames|response_count|rsp_num|frame_total|nframes)\b",
               re.IGNORECASE),
    re.compile(r"\bfor\b\s*\(", re.IGNORECASE),
    re.compile(r"\bwhile\b\s*\(", re.IGNORECASE),
]


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _line_number_of(src: str, offset: int) -> int:
    return src.count("\n", 0, offset) + 1


def _find_module_blocks(src: str):
    """Yield (module_name, body_start, body_end) for each module."""
    for m in re.finditer(r"\bmodule\s+(\w+)", src):
        name = m.group(1)
        start = m.end()
        em = re.search(r"\bendmodule\b", src[start:])
        if em:
            yield name, start, start + em.start()


def check_file(path: Path) -> list[Finding]:
    raw = path.read_text(errors="replace")
    src = _strip_comments(raw)
    findings: list[Finding] = []

    for mod_name, ms, me in _find_module_blocks(src):
        body = src[ms:me]

        total_matches = list(MULTI_FRAME_TOTAL_RE.finditer(body))
        if not total_matches:
            continue

        has_iteration = any(
            pat.search(body) for pat in ITERATION_PATTERNS
        )

        if not has_iteration:
            first = total_matches[0]
            line_no = _line_number_of(src, ms + first.start())
            reg_name = first.group(1)
            findings.append(Finding(
                severity="ERROR",
                rule="stub_fetch_loop",
                file=str(path),
                line=line_no,
                register=reg_name,
                message=(
                    f"Module `{mod_name}` declares multi-frame total "
                    f"register `{reg_name}` but no fetch loop / counter "
                    f"iteration found. The dispatcher likely fetches only "
                    f"one frame regardless of {reg_name}, causing truncated "
                    f"multi-frame responses. Add a fetch index that counts "
                    f"up to {reg_name} with a state re-entry or loop."
                ),
            ))

    return findings


def collect_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    # Kimi-scale fix: shared authored-RTL collector. This gate has always
    # also scanned *.vh headers, so the suffix set is widened accordingly.
    return rtl_source_files(path, exts=("*.v", "*.sv", "*.vh"))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Detect stub multi-frame fetch loops in RTL dispatchers.",
    )
    ap.add_argument("target", help="RTL file or directory.")
    ap.add_argument("--json", nargs="?", const="-", default=None, metavar="PATH",
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
        txt = json.dumps({
            "target": str(target),
            "scanned": len(files),
            "total_findings": len(all_findings),
            "errors": len(errors),
            "findings": [asdict(f) for f in all_findings],
            "verdict": "PASS" if not errors else "FAIL",
        }, indent=2)
        if args.json == "-":
            print(txt)
        else:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(txt + "\n")
    else:
        for f in all_findings:
            print(f"[{f.severity}] {f.rule} @ {f.file}:{f.line} ({f.register})")
            print(f"        {f.message}")
        print(f"\n{len(errors)} error(s) across {len(files)} file(s)")
        print("PASS" if not errors else "FAIL")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
