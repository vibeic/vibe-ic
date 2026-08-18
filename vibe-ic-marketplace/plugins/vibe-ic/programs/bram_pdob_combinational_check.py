#!/usr/bin/env python3
"""bram_pdob_combinational_check.py — BACKLOG-v11 P1.3 (WARNING-class).

Detect BRAM wrappers whose registered output is consumed same-cycle by
an FSM doing `rd_data <= data_out;` — non-blocking semantics give
`rd_data` the OLD value, producing an off-by-one stale read.

Motivation
==========

v0.116 <benchmark> wrote:

    // BRAM wrapper
    always_ff @(posedge clk)
      if (otp_prd) otp_pdob <= q_int;     // registered output

    // consuming FSM
    always_ff @(posedge clk)
      if (otp_seq_st == FETCH) rd_data <= otp_pdob;

Both `<=` non-blocking — at the same posedge, `rd_data` captures the
PREVIOUS cycle's `otp_pdob`, giving a 1-cycle stale read. In v0.116
the original `$readmemh`-init bug masked this (BRAM was uninitialised
LUT-of-X anyway), but once the init was fixed the off-by-one still
broke OTP reads.

Verdict policy
==============

WARNING-class (does NOT fail flow_compliance). Cross-module data-flow
inference from regex is brittle, so this gate is intentionally
conservative: we surface candidate offenders with file/line evidence
and let the engineer decide. Use `--strict` to upgrade to ERROR.

Detection
=========

Two halves must hold:

  Half A — BRAM wrapper module:
    - Has either `reg [W-1:0] mem [0:N-1]` (inferred BRAM) OR
      instantiates `altsyncram` / `xpm_memory_*` megafunction.
    - Has an output port `<sig>` registered via
      `<sig> <= mem[<addr_q>];` inside an `always_ff` block.

  Half B — Consuming FSM (in another module):
    - Has `<rd_data> <= <inst>.<sig>;` (or `<rd_data> <= <sig>;`
      where the port wiring matches) inside an `always_ff` block.
    - The same FSM has just asserted the read enable / address
      one or two cycles before.

Heuristic match: when a BRAM wrapper named `*<bram>*` registers
output `<port>`, look for any other module that has `<rd_data> <=
<port>` (port name match, not full hierarchical) inside an FSM body.

False-alert guards
==================

  - Silent if wrapper drives the output combinationally
    (`assign <sig> = mem[<addr>];` or
    `<sig> = mem[<addr>];` in `always_comb`).
  - Silent if consumer uses blocking assignment
    (`rd_data = <port>;` in `always_comb`).
  - Silent if L6 control-logic spec declares an explicit BRAM-read
    wait state for the consuming FSM
    (`bram_read_wait_states: [{module: <name>, cycles: <int>}]`).
  - Silent if the wrapper module has the
    `// BRAM_OUTPUT_REGISTER_ACKNOWLEDGED` literal comment (engineer
    override).
  - Silent if no inferred BRAM / megafunction in any module.

Exit codes: 0 PASS / 1 FAIL (only with --strict) / 2 skip
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from gate_utils import find_modules, find_rtl_files as _rtl_files
from gate_utils import parse_io_ports, read_text as _read


@dataclass
class Finding:
    severity: str
    rule: str
    message: str
    file: str = ""
    line: int = 0


# Match `reg [W-1:0] mem [0:N-1]` style inferred BRAM.
_INFERRED_BRAM_RE = re.compile(
    r"\b(?:reg|logic)\s*(?:\[[^\]]+\])?\s*(\w+)\s*\[\s*0\s*:",
)
# Megafunction instantiation
_MEGAFUNC_RE = re.compile(
    r"\b(altsyncram|altera_syncram|xpm_memory_\w+)\b", re.IGNORECASE)
# Registered output: `<sig> <= mem[<addr>]` inside always_ff
_REG_OUTPUT_RE = re.compile(
    r"(\w+)\s*<=\s*(\w+)\s*\[\s*(\w+)\s*\]\s*;",
)
# Combinational output: `assign <sig> = mem[...]`
_COMB_OUTPUT_RE = re.compile(
    r"assign\s+(\w+)\s*=\s*\w+\s*\[",
)
# Override marker
_OVERRIDE_RE = re.compile(
    r"//\s*BRAM_OUTPUT_REGISTER_ACKNOWLEDGED", re.IGNORECASE)


def _l6_wait_states(project: Path) -> set[str]:
    """Return set of module names that L6 declares have BRAM-read
    wait states."""
    out: set[str] = set()
    for cand in (
        list(project.glob("phase1/generated_docs/L6*.json"))
        + list(project.glob("L6*.json"))
        + list(project.glob("input/docs/L6*.json"))
    ):
        try:
            data = json.loads(_read(cand) or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        ws = data.get("bram_read_wait_states") or []
        if isinstance(ws, list):
            for entry in ws:
                if isinstance(entry, dict):
                    m = entry.get("module")
                    if isinstance(m, str):
                        out.add(m)
    return out


def _is_always_ff_section(body: str, offset: int) -> bool:
    """Return True if the offset in `body` falls inside an always_ff /
    always @(posedge ...) block."""
    # Find the closest preceding `always_ff` / `always @(posedge ...)`
    # AND ensure no `always_comb` / `always @*` is closer.
    pos_ff = max(
        body.rfind("always_ff", 0, offset),
        body.rfind("always @(posedge", 0, offset),
        body.rfind("always @ (posedge", 0, offset),
    )
    pos_comb = max(
        body.rfind("always_comb", 0, offset),
        body.rfind("always @*", 0, offset),
        body.rfind("always @ *", 0, offset),
        body.rfind("always_latch", 0, offset),
    )
    return pos_ff > pos_comb and pos_ff != -1


def _bram_wrapper_outputs(rtl_files: list[Path]
                          ) -> dict[str, list[tuple[str, str, Path]]]:
    """Return {output_port: [(module_name, mem_name, file)]} for every
    output port that's driven `<= mem[addr]` inside always_ff in a
    module containing inferred BRAM or megafunction instantiation."""
    out: dict[str, list[tuple[str, str, Path]]] = {}
    for f in rtl_files:
        rtl = _read(f)
        # Override marker can appear anywhere in the file (typically
        # in a header comment above the module declaration), so check
        # whole file content not just module body.
        if _OVERRIDE_RE.search(rtl):
            continue
        for spec in find_modules(rtl):
            body = spec.body
            mems: set[str] = set()
            for m in _INFERRED_BRAM_RE.finditer(body):
                mems.add(m.group(1))
            has_mega = bool(_MEGAFUNC_RE.search(body))
            if not mems and not has_mega:
                continue
            _, outputs, _ = parse_io_ports(spec.header)
            comb_outs = {m.group(1) for m in _COMB_OUTPUT_RE.finditer(body)}
            for m in _REG_OUTPUT_RE.finditer(body):
                sig, mem, _addr = m.group(1), m.group(2), m.group(3)
                if sig not in outputs:
                    continue
                if sig in comb_outs:
                    continue
                if mem not in mems and not has_mega:
                    continue
                if not _is_always_ff_section(body, m.start()):
                    continue
                out.setdefault(sig, []).append((spec.name, mem, f))
    return out


def _consumer_captures(rtl_files: list[Path], port: str
                       ) -> list[tuple[str, str, Path, int]]:
    """Return [(module_name, rd_data, file, lineno)] for every place
    a consumer module non-blocking-captures the BRAM output `port`.

    Match either `<rd> <= <port>;` (direct same-name port wire) or
    `<rd> <= <inst>.<port>;` (hierarchical reference).
    """
    pat = re.compile(
        rf"(\w+)\s*<=\s*(?:\w+\s*\.\s*)?{re.escape(port)}\s*;",
    )
    out: list[tuple[str, str, Path, int]] = []
    for f in rtl_files:
        rtl = _read(f)
        for spec in find_modules(rtl):
            body = spec.body
            if _OVERRIDE_RE.search(body):
                continue
            for m in pat.finditer(body):
                # Skip self-references (port → port latch in the
                # producer module itself)
                rd = m.group(1)
                if rd == port:
                    continue
                if not _is_always_ff_section(body, m.start()):
                    continue
                line_no = (spec.start
                           + body[:m.start()].count("\n") + 1)
                # Approximate line — use rtl-relative line count
                whole_line = (
                    rtl[:spec.start + m.start()].count("\n") + 1
                )
                out.append((spec.name, rd, f, whole_line))
    return out


def inspect(project: Path) -> tuple[list[Finding], dict]:
    findings: list[Finding] = []
    summary: dict = {
        "wrapper_outputs": [],
        "consumer_captures": [],
        "l6_wait_modules": [],
        "skipped_reason": "",
    }

    rtl_files = _rtl_files(project)
    if not rtl_files:
        summary["skipped_reason"] = "no RTL files"
        return findings, summary

    wrappers = _bram_wrapper_outputs(rtl_files)
    if not wrappers:
        summary["skipped_reason"] = (
            "no inferred BRAM / megafunction wrappers with registered "
            "outputs detected"
        )
        return findings, summary

    l6_wait = _l6_wait_states(project)
    summary["l6_wait_modules"] = sorted(l6_wait)

    for port, drivers in wrappers.items():
        for src_mod, mem, src_file in drivers:
            captures = _consumer_captures(rtl_files, port)
            for cons_mod, rd_sig, cons_file, lineno in captures:
                if cons_mod == src_mod:
                    continue
                summary["wrapper_outputs"].append(
                    f"{src_mod}.{port} (via {mem}@{src_file.relative_to(project)})"
                )
                summary["consumer_captures"].append(
                    f"{cons_mod}.{rd_sig} <= {port} "
                    f"@{cons_file.relative_to(project)}:{lineno}"
                )
                if cons_mod in l6_wait:
                    continue  # L6 declared wait state — exempt
                findings.append(Finding(
                    severity="WARNING",
                    rule="BRAM_PDOB_OFF_BY_ONE_RISK",
                    message=(
                        f"BRAM wrapper `{src_mod}` registers output "
                        f"`{port}` (via mem `{mem}`); module "
                        f"`{cons_mod}` non-blocking-captures it as "
                        f"`{rd_sig} <= {port};` inside always_ff at "
                        f"line {lineno}. Both `<=` non-blocking — "
                        f"`{rd_sig}` will receive the PREVIOUS cycle's "
                        f"`{port}` value (off-by-one stale read). "
                        f"Either (a) make `{port}` combinational "
                        f"(assign), or (b) declare a wait state in "
                        f"L6 (`bram_read_wait_states: [{{module: "
                        f"\"{cons_mod}\", cycles: 1}}]`), or (c) add "
                        f"`// BRAM_OUTPUT_REGISTER_ACKNOWLEDGED` to "
                        f"the wrapper to acknowledge the latency."
                    ),
                    file=str(cons_file.relative_to(project)),
                    line=lineno,
                ))
    if not findings and not summary["wrapper_outputs"]:
        summary["skipped_reason"] = (
            "BRAM wrappers detected but no cross-module consumers"
        )
    return findings, summary


def main() -> int:
    ap = argparse.ArgumentParser(prog="bram_pdob_combinational_check")
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true",
                    help="Upgrade WARNING to ERROR")
    args = ap.parse_args()

    project = args.project_dir.resolve()
    if not project.is_dir():
        print(f"[error] project not found: {project}", file=sys.stderr)
        return 2

    findings, summary = inspect(project)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps({
            "program": "bram_pdob_combinational_check",
            "passed": not findings or not args.strict,
            "summary": summary,
            "findings": [f.__dict__ for f in findings],
        }, indent=2))

    print(f"=== bram_pdob_combinational_check ({project.name}) ===")
    if summary["skipped_reason"]:
        print(f"  [skipped] {summary['skipped_reason']}")
        return 2
    if not findings:
        print("  [PASS] no off-by-one BRAM-read patterns detected")
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
