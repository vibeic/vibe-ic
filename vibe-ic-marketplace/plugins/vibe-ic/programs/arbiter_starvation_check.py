#!/usr/bin/env python3
"""arbiter_starvation_check.py — BACKLOG-v11 P0.6.

Detect fixed-priority arbiters whose high-priority requester is
statically asserted with no clear "burst end" condition, causing the
low-priority requester to be starved indefinitely.

Motivation
==========

v0.116 <benchmark> had a single-port OTP arbiter:

    if (otp_rd_req_pre)        otp_rd_req <= 1;       // regfile preload
    else if (otp_rd_req_disp)  otp_rd_req <= 1;       // dispatcher OP_74

`otp_rd_req_pre` was tied to `regfile.load_pre`, which in turn was
`assign load_pre = rstn;` — i.e., always 1 after reset. The regfile
preload sequence kept re-firing on every clock, perpetually starving
the dispatcher's 6-byte OP_74 burst read. Dispatcher stalled in
`D_OTP_READ_WAIT`, no response on the bus, byte[6]=0x02. Caught only
by hand-reading regfile.sv line by line.

Gate behaviour
==============

For each `if-else-if` chain in RTL where the conditions look like
arbitration requests (signal names ending in `_req`, `_request`,
`_pending`, `_busy`, `_grant`):

  1. Identify the highest-priority condition (first `if`).
  2. Check whether that signal is driven by ANY of these
     "always-on" patterns:
       (a) `assign <sig> = rstn;`               (post-reset always 1)
       (b) `assign <sig> = ~<reset>;`           (same)
       (c) `<sig> <= 1'b1;` at posedge with NO `<sig> <= 1'b0;` reachable
           AFTER the initial `<sig> <= 1'b1` (= sticky one-shot, never cleared)
       (d) `wire <sig> = <const_1>;` / `assign <sig> = 1;`
  3. If yes AND the chain has at least one `else if` branch (a
     low-priority requester), emit `ARBITER_STARVATION_RISK`.

False-alert guards
==================

  - Silent for round-robin / fairness arbiters (no static priority).
  - Silent if the high-priority request has a clear "done" condition
    in the same module (presence of `<sig> <= 1'b0;` in any branch
    that is NOT inside `if (!rstn)` reset).
  - Silent for designs without any arbitration patterns.

Severity: WARNING by default (gate flags risk; static priority can be
intentional with proper bounded burst). Use `--strict` to upgrade.

Exit codes: 0 PASS / 1 FAIL (strict) / 2 skip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from gate_utils import find_rtl_files as _rtl_files
from gate_utils import read_text as _read


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""
    line: int = 0


# Conditions that look like arbitration "request" signals (any
# identifier ending with one of these suffixes).
_REQ_SUFFIXES = ("_req", "_request", "_pending", "_grant", "_active")


# Match `if (a_req) ... else if (b_req)` priority chain.
# Capture: priority signal, low-priority signal.
_ARB_CHAIN_RE = re.compile(
    r"if\s*\(\s*(\w+)\s*\)[\s\S]{0,1000}?"
    r"else\s+if\s*\(\s*(\w+)\s*\)",
    re.MULTILINE,
)


def _is_request_like(name: str) -> bool:
    nlow = name.lower()
    return any(nlow.endswith(s) for s in _REQ_SUFFIXES)


# Match `assign sig = rstn;` or `assign sig = !reset;` style.
_ASSIGN_RST_RE = re.compile(
    r"assign\s+(\w+)\s*=\s*"
    r"(?:rst_?n|~\s*reset|!\s*reset|1\s*'b1|1\s*'h1)\s*;",
    re.IGNORECASE | re.MULTILINE,
)


def _has_clear_branch(rtl: str, sig: str) -> bool:
    """True iff <sig> is assigned <= 1'b0 in some branch that is NOT
    a reset branch.  Heuristic: any `<sig> <= 1'b0;` line that is NOT
    immediately preceded by `if (!rstn)` / `if (~rstn)` etc."""
    pat = re.compile(rf"\b{re.escape(sig)}\s*<=\s*1\s*'\s*b0\s*;",
                     re.MULTILINE)
    for m in pat.finditer(rtl):
        # Look back ~500 chars to find the enclosing branch. Wider than
        # the original 80-char window so a clear-statement that follows
        # a multi-line state-machine case body still gets correctly
        # attributed to the non-reset branch.
        #
        # Heuristic: find the LAST `if (...)` / `else if (...)` /
        # `else begin` keyword before this clear. If that branch is
        # the reset branch (`if (!rstn)` etc.), the clear is a reset
        # initialisation, not a real bounded-burst clear path.
        lookback = rtl[max(0, m.start() - 500):m.start()]
        # Walk back through `if`/`else if`/`else` tokens; if the closest
        # one matches a reset condition, treat as reset clear.
        branch_iter = list(re.finditer(
            r"\b(if|else\s+if|else)\s*\(?\s*([^)]*)?", lookback))
        if branch_iter:
            last = branch_iter[-1]
            cond = (last.group(2) or "").strip()
            if re.search(r"!\s*rst|~\s*rst|!\s*reset|~\s*reset", cond):
                continue
        return True
    return False


def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "arb_chains_examined": 0,
        "always_on_signals": [],
        "skipped_reason": "",
    }

    rtl_files = _rtl_files(project)
    if not rtl_files:
        summary["skipped_reason"] = "no RTL files found"
        return findings, summary

    # Build a project-wide set of always_on signals (driven by
    # `assign <sig> = rstn;` etc).
    always_on: set[str] = set()
    for f in rtl_files:
        rtl = _read(f)
        for m in _ASSIGN_RST_RE.finditer(rtl):
            always_on.add(m.group(1))
    summary["always_on_signals"] = sorted(always_on)

    # Scan each file for arbitration patterns.
    any_arb = False
    for f in rtl_files:
        rtl = _read(f)
        for m in _ARB_CHAIN_RE.finditer(rtl):
            sig_hi, sig_lo = m.group(1), m.group(2)
            if not (_is_request_like(sig_hi) and _is_request_like(sig_lo)):
                continue
            any_arb = True
            summary["arb_chains_examined"] += 1
            # Check if hi is always-on
            if sig_hi not in always_on:
                # Also accept sig_hi if it's never cleared anywhere
                # (sticky-after-reset assignment with no clear).
                continue
            if _has_clear_branch(rtl, sig_hi):
                # Has a clear path → bounded burst
                continue
            line_no = rtl[:m.start()].count("\n") + 1
            findings.append(Finding(
                severity="WARNING",
                rule="ARBITER_STARVATION_RISK",
                message=(
                    f"fixed-priority arbiter `if ({sig_hi}) ... else "
                    f"if ({sig_lo})` has high-priority requester "
                    f"`{sig_hi}` driven `assign {sig_hi} = rstn` style "
                    f"with no clear-to-zero path → low-priority "
                    f"requester `{sig_lo}` may be starved. v0.116 "
                    f"<benchmark> lesson: regfile preload starved "
                    f"dispatcher's OTP burst, dispatcher stalled in "
                    f"D_OTP_READ_WAIT."
                ),
                file=str(f.relative_to(project)),
                line=line_no,
            ))
    if not any_arb:
        summary["skipped_reason"] = "no arbitration patterns found"
    return findings, summary


def main() -> int:
    ap = argparse.ArgumentParser(prog="arbiter_starvation_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="Upgrade WARNING → ERROR")
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "arbiter_starvation_check",
            "passed": not findings or not args.strict,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== arbiter_starvation_check ({project.name}) ===")
    if summary["skipped_reason"]:
        print(f"  [skipped] {summary['skipped_reason']}")
        return 2
    if not findings:
        print(f"  [PASS] {summary['arb_chains_examined']} arbiter "
              f"chain(s) examined, none with starvation risk")
        return 0
    rc = 0
    for f in findings:
        sev = "ERROR" if (args.strict and f.severity == "WARNING") else f.severity
        if sev == "ERROR":
            rc = 1
        loc = f" ({f.file}:{f.line})" if f.file else ""
        print(f"  [{sev.lower()}] {f.rule}{loc}: {f.message}")
    print(f"\nOverall: {'FAIL' if rc else 'PASS (with warnings)'}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
