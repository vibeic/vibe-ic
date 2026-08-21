#!/usr/bin/env python3
"""semantic_spec_floor_check.py — SEMANTIC dataset-defect floor detection.

The existing Tier-5 floor detector (`floor_evidence`) only proves a STRUCTURAL
floor: it renames the golden to the top module and scores it against the
problem's OWN hidden testbench. Because that testbench is GENERATED FROM the
golden, "golden vs its own test" is a tautology — it can never catch a golden
that is internally self-consistent yet CONTRADICTS the problem prompt's own
stated, machine-extractable spec.

This program closes that gap for the deterministically-extractable spec class:
a **Karnaugh-map grid** in the prompt (optionally feeding an external N:1 mux the
prompt describes). It builds an INDEPENDENT oracle from the PROMPT, simulates the
golden over the full input space with iverilog, and reports a SEMANTIC FLOOR with
a cited (input, golden, spec) triple iff the golden disagrees with the
prompt-stated truth on any DEFINED (non-don't-care) cell.

Zero-false-positive by construction: it fires ONLY when it can fully and
unambiguously extract the K-map AND map every K-map variable to a module port (or
a prompt-described mux select). Any ambiguity -> returns None (NOT a floor).

CLI:
    python3 semantic_spec_floor_check.py --prompt P.txt --ref R.sv [--json OUT]
    exit 0 = no semantic floor found ; exit 3 = SEMANTIC FLOOR (with evidence)
"""
from __future__ import annotations
import argparse, itertools, json, re, subprocess, sys, tempfile, os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DONTCARE = {"d", "x", "-"}


# --------------------------------------------------------------------------- #
# (1) K-map grid extraction — the header rows give the EXACT bit-combos, so we
#     never assume Gray order; we read the literal column/row labels.
# --------------------------------------------------------------------------- #
def extract_kmap(prompt: str) -> Optional[dict]:
    """Return {col_vars, row_vars, cells:{(assign tuple of (var,val)) : val_or_None}}
    or None if no single unambiguous K-map grid is present.

    A grid looks like (col header line of variable letters, then a label row, then
    `<rowlabel> | v | v | ...` rows whose leading text starts with the row vars):

              ab
       cd   00  01  11  10
       00 | 1 | 1 | 0 | 1 |
    """
    lines = prompt.splitlines()
    # find every grid row: "<label> | a | b | ..."
    grid_rows = []
    grid_idx = []
    for i, ln in enumerate(lines):
        m = re.match(r"\s*([01]+)\s*\|\s*([01dxDX\-](?:\s*\|\s*[01dxDX\-])*)\s*\|?\s*$", ln)
        if m:
            label = m.group(1)
            cells = [c.strip().lower() for c in re.split(r"\|", m.group(2)) if c.strip() != ""]
            grid_rows.append((label, cells, i))
    if len(grid_rows) < 2:
        return None
    # the rows must be contiguous and same width
    width = len(grid_rows[0][1])
    if any(len(c) != width for _, c, _ in grid_rows):
        return None
    first_row_line = grid_rows[0][2]
    # the column-label line is the line just above the first grid row: it holds the
    # column labels (e.g. "cd   00  01  11  10" where 'cd' are the ROW vars and the
    # numbers are the COLUMN labels), OR for a 1-var column "a\n  0  1".
    if first_row_line < 1:
        return None
    header_line = lines[first_row_line - 1]
    col_labels = re.findall(r"\b([01]+)\b", header_line)
    if len(col_labels) != width:
        return None
    # row vars come from the leading token on the column-label header line (the
    # letters before the column numbers), e.g. "cd   00 01 11 10" -> row vars 'cd'.
    rv = re.match(r"\s*([a-z]+)\s", header_line)
    row_vars = rv.group(1) if rv else ""
    # col vars: the variable-letters line above the column-label header line.
    col_vars = ""
    for j in range(first_row_line - 2, max(-1, first_row_line - 5), -1):
        if j < 0:
            break
        t = lines[j].strip()
        if re.fullmatch(r"[a-z]+", t):
            col_vars = t
            break
    if not col_vars or not row_vars:
        return None
    # label widths must match var counts
    if any(len(cl) != len(col_vars) for cl in col_labels):
        return None
    if any(len(rl) != len(row_vars) for rl, _, _ in grid_rows):
        return None
    cells: Dict[Tuple[Tuple[str, int], ...], Optional[int]] = {}
    for rlabel, cvals, _ in grid_rows:
        for cl, val in zip(col_labels, cvals):
            assign = tuple(sorted([(v, int(b)) for v, b in zip(col_vars, cl)] +
                                  [(v, int(b)) for v, b in zip(row_vars, rlabel)]))
            cells[assign] = None if val in DONTCARE else int(val)
    return {"col_vars": list(col_vars), "row_vars": list(row_vars),
            "vars": sorted(set(col_vars) | set(row_vars)), "cells": cells}


# --------------------------------------------------------------------------- #
# (2) module port parsing (golden RefModule)
# --------------------------------------------------------------------------- #
_PORT_RE = re.compile(
    r"\b(input|output)\b\s*(?:reg|wire|logic)?\s*(\[\s*(\d+)\s*:\s*(\d+)\s*\])?\s*([A-Za-z_]\w*)")


def parse_ports(ref_text: str) -> Tuple[List[dict], bool]:
    """Return (ports, is_sequential). ports = [{name,dir,width,msb,lsb}]."""
    body = ref_text
    m = re.search(r"module\s+\w+\s*\((.*?)\)\s*;", body, re.S)
    seg = m.group(1) if m else body
    ports = []
    for mm in _PORT_RE.finditer(seg):
        d, _rng, msb, lsb, name = mm.group(1), mm.group(2), mm.group(3), mm.group(4), mm.group(5)
        if msb is not None:
            w = abs(int(msb) - int(lsb)) + 1
        else:
            w = 1
        ports.append({"name": name, "dir": d, "width": w,
                      "msb": int(msb) if msb is not None else 0,
                      "lsb": int(lsb) if lsb is not None else 0})
    seq = bool(re.search(r"\bposedge\b|\bnegedge\b|\bclk\b", ref_text))
    return ports, seq


# --------------------------------------------------------------------------- #
# (3) simulate the golden over the full input space (combinational only)
# --------------------------------------------------------------------------- #
def simulate_golden(ref_text: str, in_ports: List[dict], out_ports: List[dict],
                    timeout: int = 60) -> Optional[Dict[Tuple[int, ...], Dict[str, int]]]:
    """Enumerate every input combination, return {in_tuple : {out_name: value}}.
    in_tuple is ordered as in_ports. Returns None on any tool failure."""
    total_in_bits = sum(p["width"] for p in in_ports)
    if total_in_bits > 12:          # keep enumeration bounded
        return None
    # build a TB that drives each input and $displays inputs+outputs
    decl_in = "\n".join(f"  reg [{p['width']-1}:0] {p['name']};" for p in in_ports)
    decl_out = "\n".join(f"  wire [{p['width']-1}:0] {p['name']};" for p in out_ports)
    conns = ", ".join(f".{p['name']}({p['name']})" for p in in_ports + out_ports)
    in_names = [p["name"] for p in in_ports]
    out_names = [p["name"] for p in out_ports]
    disp_fmt = " ".join(["%0d"] * (len(in_names) + len(out_names)))
    disp_args = ", ".join(in_names + out_names)
    # nested loops over each input port's range
    loops_open, loops_close, idx = "", "", 0
    for p in in_ports:
        v = f"i_{p['name']}"
        loops_open += f"    for ({v}=0; {v} < {1<<p['width']}; {v}={v}+1) begin\n"
        loops_open += f"      {p['name']} = {v};\n"
        loops_close = "    end\n" + loops_close
    intdecl = " ".join(f"integer i_{p['name']};" for p in in_ports)
    golden_top = re.sub(r"\bRefModule\b", "DUT", ref_text)
    tb = f"""{golden_top}
module tb;
{decl_in}
{decl_out}
  {intdecl}
  DUT dut({conns});
  initial begin
{loops_open}      #1 $display("{disp_fmt}", {disp_args});
{loops_close}    $finish;
  end
endmodule
"""
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "g.sv"
        f.write_text(tb)
        binp = Path(td) / "g.out"
        try:
            # watchdog-exempt: bounded single-file iverilog compile (elaboration/sim build); fixed budget adequate — not an open-ended EDA generator
            c = subprocess.run(["iverilog", "-g2012", "-o", str(binp), str(f)],
                               capture_output=True, text=True, timeout=timeout)
            if c.returncode != 0:
                return None
            r = subprocess.run(["vvp", str(binp)], capture_output=True, text=True,
                               timeout=timeout, cwd=td)
        except Exception:
            return None
    res = {}
    nin = len(in_names)
    for ln in r.stdout.splitlines():
        toks = ln.split()
        if len(toks) != nin + len(out_names):
            continue
        try:
            ivals = tuple(int(t) for t in toks[:nin])
            ovals = {nm: int(toks[nin + k]) for k, nm in enumerate(out_names)}
        except ValueError:
            continue
        res[ivals] = ovals
    return res or None


# --------------------------------------------------------------------------- #
# (4) the semantic-floor decision
# --------------------------------------------------------------------------- #
def _mux_index_map(prompt: str, n_sel: int) -> Dict[Tuple[int, ...], int]:
    """Default binary mapping {(a,b):2a+b}. Honour explicit 'ab=XX ... mux_in[Y]'
    statements if present."""
    combos = list(itertools.product([0, 1], repeat=n_sel))
    idx = {c: sum(b << (n_sel - 1 - k) for k, b in enumerate(c)) for c in combos}
    for mm in re.finditer(r"ab\s*=\s*([01]{%d}).{0,40}?mux_in\s*\[\s*(\d+)\s*\]" % n_sel,
                          prompt, re.I | re.S):
        bits = tuple(int(x) for x in mm.group(1))
        idx[bits] = int(mm.group(2))
    return idx


def semantic_floor_evidence(prompt: str, ref_text: str,
                            timeout: int = 60) -> Optional[str]:
    """Return a CITED reason iff the golden contradicts the prompt's K-map on a
    defined cell; else None. Never raises — any uncertainty returns None."""
    try:
        r = _semantic_floor_evidence(prompt, ref_text, timeout)
        if r:
            return r
    except Exception:
        pass
    try:
        return embedded_mux_polarity_floor(prompt, ref_text, timeout)
    except Exception:
        return None


def _semantic_floor_evidence(prompt: str, ref_text: str, timeout: int) -> Optional[str]:
    km = extract_kmap(prompt)
    if not km:
        return None
    ports, seq = parse_ports(ref_text)
    if seq:
        return None                       # combinational K-map class only
    in_ports = [p for p in ports if p["dir"] == "input"]
    out_ports = [p for p in ports if p["dir"] == "output"]
    in_names = {p["name"] for p in in_ports}
    if not out_ports:
        return None
    kvars = km["vars"]
    sim = simulate_golden(ref_text, in_ports, out_ports, timeout)
    if sim is None:
        return None

    # --- case DIRECT: every K-map var is a 1-bit module input, single scalar out
    if set(kvars) <= in_names and len(out_ports) == 1 and out_ports[0]["width"] == 1:
        outp = out_ports[0]["name"]
        order = [p["name"] for p in in_ports]
        for assign, want in km["cells"].items():
            if want is None:
                continue
            d = dict(assign)
            it = tuple(d.get(nm, 0) for nm in order)
            if it not in sim:
                return None
            got = sim[it][outp]
            if got != want:
                cite = ", ".join(f"{k}={v}" for k, v in assign)
                return (f"golden contradicts the prompt's Karnaugh map: at ({cite}) "
                        f"the K-map states {outp}={want} but the golden outputs {got}; "
                        f"a spec-faithful answer can never match this golden")
        return None

    # --- case MUX: K-map has extra vars (an external N:1 mux select the prompt
    #     describes); module outputs the mux DATA lines as a vector.
    extra = [v for v in kvars if v not in in_names]
    data = [p for p in out_ports if p["width"] == len(km_cols_pow(extra))] if extra else []
    if extra and len(data) == 1 and all(len(v) == 1 for v in extra) \
            and set(kvars) - set(extra) <= in_names:
        sel_vars = sorted(extra)
        n_sel = len(sel_vars)
        if (1 << n_sel) != data[0]["width"]:
            return None
        idxmap = _mux_index_map(prompt, n_sel)
        dport = data[0]["name"]
        order = [p["name"] for p in in_ports]
        for assign, want in km["cells"].items():
            if want is None:
                continue
            d = dict(assign)
            it = tuple(d.get(nm, 0) for nm in order)
            if it not in sim:
                return None
            sel = tuple(d[v] for v in sel_vars)
            line = idxmap.get(sel)
            if line is None:
                return None
            full = sim[it][dport]
            got = (full >> line) & 1
            if got != want:
                cite = ", ".join(f"{k}={v}" for k, v in assign)
                return (f"golden contradicts the prompt's full-circuit Karnaugh map: at "
                        f"({cite}) the K-map states output={want} but the golden's "
                        f"{dport}[{line}] (the {''.join(sel_vars)}={''.join(map(str,sel))} "
                        f"mux line) gives {got}; the spec-faithful answer can never match")
        return None
    return None


def km_cols_pow(extra: List[str]) -> List[int]:
    return list(range(1 << len(extra)))


# --------------------------------------------------------------------------- #
# (4b) embedded-snippet floor — a "fix the bug" prompt whose embedded reference
#      snippet is a 2:1-mux sum-of-products idiom `(~sel & a) | (sel & b)` whose
#      ONLY behavioural intent (sel=1 selects b) the golden INVERTS. A width-only
#      fix can never change the select polarity, so an inverted golden contradicts
#      the prompt's sole behavioural hint. Conservative: fires only on the exact
#      idiom + a golden that is a CLEAN but inverted 2:1 mux of the same operands.
# --------------------------------------------------------------------------- #
_MUX_SOP = re.compile(
    r"\(\s*~\s*(\w+)\s*&\s*(\w+)\s*\)\s*\|\s*\(\s*(\w+)\s*&\s*(\w+)\s*\)")


def _probe_golden_mux(ref_text: str, sel: str, a: str, b: str,
                      timeout: int = 60) -> Optional[str]:
    """Drive distinct a/b vectors at sel=0 and sel=1; return 'a'/'b'/None for which
    operand the golden's output FOLLOWS at sel=1 (None if not a clean mux)."""
    ports, seq = parse_ports(ref_text)
    if seq:
        return None
    pmap = {p["name"]: p for p in ports}
    if not all(n in pmap for n in (sel, a, b)):
        return None
    outs = [p for p in ports if p["dir"] == "output"]
    if len(outs) != 1:
        return None
    o = outs[0]
    w = o["width"]
    # distinct bitwise-complementary patterns: a=0xAA.., b=0x55..
    va = int("10" * ((w // 2) + 1), 2) & ((1 << w) - 1)
    vb = (~va) & ((1 << w) - 1)
    golden_top = re.sub(r"\bRefModule\b", "DUT", ref_text)
    decl = (f"  reg [{pmap[sel]['width']-1}:0] {sel};\n"
            f"  reg [{pmap[a]['width']-1}:0] {a};\n"
            f"  reg [{pmap[b]['width']-1}:0] {b};\n"
            f"  wire [{w-1}:0] {o['name']};")
    conns = ", ".join(f".{p['name']}({p['name']})" for p in ports)
    tb = f"""{golden_top}
module tb;
{decl}
  DUT dut({conns});
  initial begin
    {a} = {va}; {b} = {vb};
    {sel} = 0; #1 $display("S0 %0d", {o['name']});
    {sel} = 1; #1 $display("S1 %0d", {o['name']});
    $finish;
  end
endmodule
"""
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "m.sv"; f.write_text(tb)
        binp = Path(td) / "m.out"
        try:
            # watchdog-exempt: bounded single-file iverilog compile (elaboration/sim build); fixed budget adequate — not an open-ended EDA generator
            c = subprocess.run(["iverilog", "-g2012", "-o", str(binp), str(f)],
                               capture_output=True, text=True, timeout=timeout)
            if c.returncode != 0:
                return None
            r = subprocess.run(["vvp", str(binp)], capture_output=True, text=True,
                               timeout=timeout, cwd=td)
        except Exception:
            return None
    s1 = None
    for ln in r.stdout.splitlines():
        if ln.startswith("S1"):
            try:
                s1 = int(ln.split()[1])
            except (ValueError, IndexError):
                return None
    if s1 is None:
        return None
    if s1 == va:
        return "a"
    if s1 == vb:
        return "b"
    return None


def embedded_mux_polarity_floor(prompt: str, ref_text: str,
                                timeout: int = 60) -> Optional[str]:
    if not re.search(r"\bbug\b|\bfix\b", prompt, re.I):
        return None
    m = _MUX_SOP.search(prompt)
    if not m:
        return None
    sel1, a, sel2, b = m.group(1), m.group(2), m.group(3), m.group(4)
    if sel1 != sel2 or len({sel1, a, b}) != 3:
        return None
    # embedded idiom intent: sel=1 -> b. Probe the golden's actual polarity.
    follows = _probe_golden_mux(ref_text, sel1, a, b, timeout)
    if follows == "a":          # golden picks `a` at sel=1 -> inverted vs the snippet
        return (f"golden contradicts the prompt's only behavioural hint: the embedded "
                f"reference `(~{sel1} & {a}) | ({sel1} & {b})` selects `{b}` when "
                f"{sel1}=1, but the golden selects `{a}` when {sel1}=1 (select polarity "
                f"inverted). A width-only bug-fix cannot invert the select; the "
                f"spec-faithful answer can never match this golden")
    return None


# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--ref", required=True)
    ap.add_argument("--timeout", type=int, default=60)
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    prompt = Path(a.prompt).read_text(errors="replace")
    ref = Path(a.ref).read_text(errors="replace")
    reason = semantic_floor_evidence(prompt, ref, a.timeout)
    out = {"semantic_floor": reason is not None, "reason": reason}
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))
    return 3 if reason else 0


if __name__ == "__main__":
    sys.exit(main())
