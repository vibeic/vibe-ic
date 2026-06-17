#!/usr/bin/env python3
"""kmap_truth_table_oracle_check.py — prompt-disclosed combinational oracle gate.

WHY (ORGANIC #716 — Prob122_kmap4 scored FAIL, plugin program-first absorption):
A VerilogEval-class prompt that hands the design a FULLY-SPECIFIED K-map or
truth table IS a complete functional oracle: every input combination's required
output is disclosed in the prompt itself, blind. Yet the Shape-C emit gate
(`gates_atomic.py`) only ran phase1 + iverilog-compile + structural lints — no
step ever simulated the authored RTL against that prompt-disclosed oracle. So a
careless K-map misread shipped: Prob122_kmap4's author wrote `out = a ^ b ^ d`
("independent of c") when the K-map decodes to `out = a ^ b ^ c ^ d`; the design
compiled clean, passed every structural rule, emitted, and then FAILED the hidden
TB 121/232. An independent prompt-only blind solve gets `a^b^c^d` (0/232), and the
dataset golden is self-consistent — so this is NOT a floor and NOT a dataset
defect: it is a recoverable authoring slip whose general, no-cheat fix is to make
the prompt's own oracle an EMIT GATE.

WHAT this program does — given the prompt + the authored RTL:
  1. Parse a HIGH-CONFIDENCE, COMPLETE, UNAMBIGUOUS oracle from the prompt
     (truth-table OR standard Gray-code K-map with scalar 1-bit named axes and
     a single 1-bit output that is a DIRECT function of the table value).
  2. Build a tiny exhaustive testbench over all 2^N input combinations and run
     `iverilog`/`vvp`; compare the DUT output to the oracle.
  3. BLOCK (rc=1) on any mismatch; PASS (rc=0) on a clean match.

§4.05 SAFETY — the gate must NEVER false-block a correct design, so it builds an
oracle ONLY when it can do so unambiguously, and SKIPs (rc=0, advisory) otherwise:
  - single 1-bit output only (multi-bit output / mux-selector transform such as
    Prob093 ece241_2014_q3 where the output is `mux_in` NOT the K-map value → SKIP);
  - inputs all 1-bit SCALARS whose names are the K-map axes (a multi-bit bus axis
    like `x[0]x[1]` is SKIPped in this conservative cut — Prob113/Prob116);
  - K-map columns/rows in standard 2-var Gray order (00,01,11,10) — a reordered
    header (Prob125_kmap3's `01 00 10 11`) → SKIP;
  - NO don't-care ('d'/'x') cells — a minimized correct design may legally drop a
    variable when don't-cares are present (Prob125_kmap3 / Prob116_m2014_q3) → SKIP;
  - the parsed table must be COMPLETE (every 2^N combination exactly once) → else SKIP.
A SKIP is always non-blocking. A BLOCK fires only when the parsed oracle is exact
(validated: the oracle reconstructed for Prob122_kmap4 / Prob057_kmap2 matches the
dataset golden truth-table 16/16). Under-firing (a safe SKIP) is always preferred
over any risk of a false block.

chip-AGNOSTIC, prompt-blind (reads only the prompt the author already reads),
deterministic.

CLI:
    python3 kmap_truth_table_oracle_check.py --prompt <prompt.txt> --rtl <sample.sv> \
        [--top TopModule] [--json out.json]
Exit codes:
    0 = PASS or SKIP (non-blocking)
    1 = BLOCK (care-cell mismatch vs prompt oracle)
    2 = tool/usage error (disclosed, non-blocking — caller's hard iverilog gate still applies)
"""
from __future__ import annotations
import argparse
import itertools
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

GRAY2 = ["00", "01", "11", "10"]  # standard 2-var Gray column/row order


def parse_ports(prompt: str):
    ins, outs = [], []
    for m in re.finditer(
        r"^\s*-\s*(input|output)\s+(\w+)(\s*\(\s*(\d+)\s*bits?\s*\))?", prompt, re.M
    ):
        d, name, _, w = m.groups()
        width = int(w) if w else 1
        (ins if d == "input" else outs).append((name, width))
    return ins, outs


def _is_kmap_prompt(prompt: str) -> bool:
    return bool(re.search(r"karnaugh map|k-?map", prompt, re.I))


def _is_truthtable_prompt(prompt: str) -> bool:
    return bool(re.search(r"truth table", prompt, re.I))


def parse_truth_table(prompt: str, ins, outs):
    """Clean column-style truth table: header 'x3 | x2 | x1 | f' then 0/1 rows."""
    if len(outs) != 1 or outs[0][1] != 1:
        return None
    if any(w != 1 for _, w in ins):
        return None
    in_names = [n for n, _ in ins]
    out_name = outs[0][0]
    lines = prompt.splitlines()
    hdr_idx = None
    order = None
    for i, ln in enumerate(lines):
        cells = [c.strip() for c in ln.split("|")]
        if set(in_names) | {out_name} <= set(cells):
            hdr_idx, order = i, cells
            break
    if hdr_idx is None:
        return None
    col_for = {name: order.index(name) for name in in_names + [out_name]}
    table = {}
    for ln in lines[hdr_idx + 1:]:
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) < len(order):
            continue
        try:
            invals = tuple(int(cells[col_for[n]]) for n in in_names)
            outval = cells[col_for[out_name]]
        except (ValueError, IndexError, KeyError):
            continue
        if outval not in ("0", "1"):
            return None  # don't-care / garbage → SKIP
        if any(v not in (0, 1) for v in invals):
            continue
        table[invals] = int(outval)
    if len(table) != 2 ** len(in_names):
        return None  # incomplete → SKIP
    return ("table", in_names, out_name, table)


def parse_kmap(prompt: str, ins, outs):
    """Standard Gray K-map, scalar 1-bit named axes, single 1-bit output, no
    don't-cares, complete. SKIP on anything else."""
    if len(outs) != 1 or outs[0][1] != 1:
        return None
    if any(w != 1 for _, w in ins):
        return None  # bus axis → SKIP
    if re.search(r"don'?t.?care|\bd is\b", prompt, re.I):
        return None  # don't-cares → SKIP
    if re.search(r"multiplexer|\bmux\b", prompt, re.I):
        return None  # transform problem → SKIP
    in_names = [n for n, _ in ins]
    out_name = outs[0][0]
    lines = prompt.splitlines()
    row_axis = col_axis = None
    hdr_idx = None
    for i, ln in enumerate(lines):
        toks = ln.split()
        nums = [t for t in toks if re.fullmatch(r"[01]{2}", t)]
        if len(nums) == 4 and nums == GRAY2:
            lead = [t for t in toks if not re.fullmatch(r"[01]{2}", t)]
            if lead:
                row_axis = lead[0]
            hdr_idx = i
            for j in range(i - 1, max(-1, i - 4), -1):
                cand = lines[j].strip()
                if cand and "|" not in cand:
                    col_axis = cand
                    break
            break
    if hdr_idx is None or not col_axis or not row_axis:
        return None
    col_vars = list(col_axis)
    row_vars = list(row_axis)
    if sorted(col_vars + row_vars) != sorted(in_names):
        return None  # axes must exactly partition the scalar inputs
    if len(col_vars) != 2 or len(row_vars) != 2:
        return None  # this cut handles only the 4x4 (2-var x 2-var) Gray form
    table = {}
    for ln in lines[hdr_idx + 1:]:
        if "|" not in ln:
            continue
        m = re.match(r"\s*([01]{2})\s*\|(.+)\|", ln)
        if not m:
            continue
        rlabel = m.group(1)
        cells = [c.strip() for c in m.group(2).split("|")]
        if len(cells) != 4:
            return None
        if rlabel not in GRAY2:
            return None
        for ci, cell in enumerate(cells):
            if cell not in ("0", "1"):
                return None  # don't-care slipped through → SKIP
            clabel = GRAY2[ci]
            assign = {}
            for k, v in enumerate(row_vars):
                assign[v] = int(rlabel[k])
            for k, v in enumerate(col_vars):
                assign[v] = int(clabel[k])
            invals = tuple(assign[n] for n in in_names)
            table[invals] = int(cell)
    if len(table) != 2 ** len(in_names):
        return None
    return ("kmap", in_names, out_name, table)


def build_oracle(prompt: str):
    ins, outs = parse_ports(prompt)
    if not ins or not outs:
        return None
    if _is_truthtable_prompt(prompt):
        r = parse_truth_table(prompt, ins, outs)
        if r:
            return r
    if _is_kmap_prompt(prompt):
        r = parse_kmap(prompt, ins, outs)
        if r:
            return r
    return None


def simulate(rtl_path: str, top: str, in_names, out_name, table):
    n = len(in_names)
    tb = ["`timescale 1ns/1ps", "module _kmap_tb;"]
    for nm in in_names:
        tb.append(f"  reg {nm};")
    tb.append(f"  wire {out_name};")
    portmap = ", ".join(f".{nm}({nm})" for nm in in_names) + f", .{out_name}({out_name})"
    tb.append(f"  {top} dut({portmap});")
    tb.append("  reg [31:0] errs;")
    tb.append("  initial begin errs=0;")
    for combo in itertools.product([0, 1], repeat=n):
        assigns = " ".join(f"{nm}={v};" for nm, v in zip(in_names, combo))
        exp = table[combo]
        idx = "".join(str(b) for b in combo)
        tb.append(f"    {assigns} #1;")
        tb.append(
            f"    if ({out_name} !== 1'b{exp}) begin errs=errs+1; "
            f'$display("MISMATCH in={idx} got=%b exp={exp}", {out_name}); end'
        )
    tb.append('    if (errs==0) $display("ORACLE_PASS");')
    tb.append('    else $display("ORACLE_FAIL %0d", errs);')
    tb.append("    $finish; end")
    tb.append("endmodule")
    with tempfile.TemporaryDirectory() as td:
        tbp = Path(td) / "tb.sv"
        tbp.write_text("\n".join(tb) + "\n")
        binp = Path(td) / "a.out"
        cp = subprocess.run(
            ["iverilog", "-g2012", "-o", str(binp), str(rtl_path), str(tbp)],
            capture_output=True, text=True,
        )
        if cp.returncode != 0:
            return ("TOOL_ERR", cp.stderr[-400:])
        cp = subprocess.run(["vvp", str(binp)], capture_output=True, text=True)
        out = cp.stdout
        if "ORACLE_PASS" in out:
            return ("PASS", out.strip()[-600:])
        if "ORACLE_FAIL" in out:
            return ("BLOCK", out.strip()[-600:])
        return ("TOOL_ERR", out.strip()[-400:])


def check(prompt_text: str, rtl_path: str, top: str = "TopModule"):
    """Return (verdict, detail). verdict in PASS|SKIP|BLOCK|TOOL_ERR."""
    oracle = build_oracle(prompt_text)
    if not oracle:
        return ("SKIP", {"reason": "no high-confidence complete oracle parseable from prompt"})
    kind, in_names, out_name, table = oracle
    verdict, log = simulate(rtl_path, top, in_names, out_name, table)
    detail = {"kind": kind, "inputs": in_names, "output": out_name,
              "cells": len(table), "log": log}
    return (verdict, detail)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--rtl", required=True)
    ap.add_argument("--top", default="TopModule")
    ap.add_argument("--json", default="")
    a = ap.parse_args()
    pp, rp = Path(a.prompt), Path(a.rtl)
    if not pp.is_file() or not rp.is_file():
        print(f"kmap_truth_table_oracle_check: missing prompt/rtl", file=sys.stderr)
        return 2
    verdict, detail = check(pp.read_text(errors="replace"), str(rp), a.top)
    payload = {"verdict": verdict, "rule": "kmap-truth-table-oracle-mismatch", **detail}
    if a.json:
        Path(a.json).write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))
    if verdict == "BLOCK":
        return 1
    if verdict == "TOOL_ERR":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
