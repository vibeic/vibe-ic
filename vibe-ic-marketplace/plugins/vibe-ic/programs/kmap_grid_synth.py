#!/usr/bin/env python3
"""kmap_grid_synth.py — DETERMINISTIC Karnaugh-map → RTL synthesizer
(v1.1.38 clean-room §4.2 absorption).

THE GAP THIS CLOSES
-------------------
VerilogEval K-map prompts ("implement the function shown in the Karnaugh map
below") embed a LITERAL grid that, when it contains NO don't-cares, is a complete
truth table — the answer is the exact sum-of-products, with zero ambiguity and no
oracle. Yet a blind author re-derives the boolean function by eye and FLIPS the
column/row axis mapping per round (Prob113, Prob050, Prob122 alternate PASS/FAIL =
single-shot variance). Per open-benchmark-methodology §4.2, a GENERAL no-cheat
recovery MUST be absorbed as a deterministic PROGRAM. This is that absorption.

§4.05 NO-LEAK — EXACT (don't-care-FREE) GRIDS ONLY
--------------------------------------------------
A K-map containing a don't-care cell (`d`/`-`) is UNDER-DETERMINED: the golden
picks ONE of many valid functions, which the prompt never pins, so reproducing it
needs the oracle — that is a genuine FLOOR, not a program-absorbable case. This
synthesizer FIRES only on a fully-specified (0/1-only) grid and SKIPs (emits
nothing) on any grid with a don't-care, a mux-decomposition output (`mux_in[..]`),
an unparseable header, or anything outside its proven-faithful envelope. So it can
never ship an under-determined guess.

USAGE
-----
    python3 kmap_grid_synth.py --prompt <prompt.txt> --top TopModule [--out s.sv]

EXIT CODES
----------
    0  synthesized + emitted (exact don't-care-free grid)
    2  SKIP — outside the envelope (don't-care / unparseable / not a K-map)

chip-AGNOSTIC: pure boolean synthesis from the prompt's own grid; no chip / SKU /
oracle / hidden-testbench data.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import waveform_truth_table_synth as _wsynth  # reuse parse_ports  # noqa: E402

parse_ports = _wsynth.parse_ports

# A grid row: a leading bit-label (e.g. `00`, `1`) then `| v | v | ...|`.
_GRID_ROW = re.compile(r"^\s*([01]+)\s*\|\s*(.+?)\s*\|?\s*$")


def _label_bits(label: str) -> Optional[List[str]]:
    """Parse a K-map axis label into ordered bit-select tokens (MSB→LSB as written).
    `x[0]x[1]` -> ['x[0]','x[1]']; `ab` -> ['a','b']; `a` -> ['a']; `cd` -> ['c','d'].
    Returns None for an unrecognized label."""
    label = label.strip()
    if not label:
        return None
    # bracketed form: name[idx] repeated
    br = re.findall(r"[A-Za-z_]\w*\[\d+\]", label)
    if br and "".join(br).replace(" ", "") == label.replace(" ", ""):
        return br
    # bare single-letter run: `ab`, `cd`, `a`
    if re.fullmatch(r"[A-Za-z]+", label):
        return list(label)
    return None


def _parse_kmap(prompt: str) -> Optional[Tuple[List[str], List[str], List[str], List[List[str]]]]:
    """Return (col_bits, row_bits, col_codes, grid) or None.
    col_codes[j] is the column header code (e.g. '01'); grid[i] is the row's cells."""
    lines = prompt.splitlines()
    # find the grid rows (contiguous block of `<bits> | .. |`)
    grid_idx = [i for i, ln in enumerate(lines) if _GRID_ROW.match(ln)]
    if len(grid_idx) < 2:
        return None
    # contiguous block
    start = grid_idx[0]
    block = []
    for i in range(start, len(lines)):
        m = _GRID_ROW.match(lines[i])
        if m:
            block.append((m.group(1), [c.strip() for c in m.group(2).split("|")]))
        elif block:
            break
    if len(block) < 2:
        return None
    # the column-code line is the non-grid line just above `start` that holds the
    # column codes (e.g. `cd   00  01  11  10` or `bc   0   1`); the token(s) before
    # the codes are the ROW-axis label, the line above is the COLUMN-axis label.
    hdr_i = start - 1
    while hdr_i >= 0 and not lines[hdr_i].strip():
        hdr_i -= 1
    if hdr_i < 0:
        return None
    hdr_toks = lines[hdr_i].split()
    # split header into [row-label] + [col codes...]; col codes are pure binary tokens
    col_codes = [t for t in hdr_toks if re.fullmatch(r"[01]+", t)]
    row_label_toks = [t for t in hdr_toks if not re.fullmatch(r"[01]+", t)]
    if not col_codes:
        return None
    row_label = "".join(row_label_toks)
    # column-axis label is the nearest non-empty line above the header
    col_i = hdr_i - 1
    while col_i >= 0 and not lines[col_i].strip():
        col_i -= 1
    col_label = lines[col_i].strip() if col_i >= 0 else ""
    col_bits = _label_bits(col_label)
    row_bits = _label_bits(row_label)
    code_w = len(col_codes[0])
    # COMPRESSED layout (VE-v2 twin): the code line carries NO row label (just the
    # column codes), and the line above lists ALL axis bits as ONE combined label
    # (e.g. `x[1]x[2]x[3]x[4]` over a `00 01 11 10` code line). The standard K-map
    # reading is column-axis = the FIRST code_w bits, row-axis = the REMAINING bits.
    # We only take this branch when the separate row label is absent and the combined
    # label has more bits than the column-code width (so the split is unambiguous);
    # the row-code-width validation below still cross-checks the split.
    if (not row_bits) and col_bits and len(col_bits) > code_w \
            and all(len(c) == code_w for c in col_codes):
        row_bits = col_bits[code_w:]
        col_bits = col_bits[:code_w]
    if not col_bits or not row_bits:
        return None
    # validate widths: each col code length == #col_bits; each row label len == #row_bits
    if any(len(c) != len(col_bits) for c in col_codes):
        return None
    grid = []
    row_codes = []
    for rcode, cells in block:
        if len(rcode) != len(row_bits) or len(cells) != len(col_codes):
            return None
        row_codes.append(rcode)
        grid.append(cells)
    return col_bits, row_bits, col_codes, (row_codes, grid)


def _synth_mux_decomp(prompt: str, top: str, ports, out: str, out_w: int):
    """K-map -> external-mux DECOMPOSITION (Shannon expansion).

    Some K-map prompts do not ask for the function itself but for the DATA
    INPUTS of an external multiplexer whose SELECT lines are the K-map's
    column-axis variables. The output is then a vector with one bit per
    selector value, and each bit is the K-map COLUMN for that value, read as a
    function of the remaining (row-axis) variables.

    THE TRAP THIS CLOSES.  A K-map's columns are printed in GRAY order
    (00 01 11 10), while the mux data input index is the plain BINARY value of
    the selector. Reading the columns left-to-right into out[0..3] therefore
    swaps the last two data inputs and yields a function that is wrong in
    exactly the two cells where the Gray and binary orders disagree. We index
    each column by ``int(code, 2)`` — the selector's own binary value — so the
    print order of the grid cannot influence the result.

    ENVELOPE (all checks are structural and prompt-derived; SKIP otherwise):
      * grid parses, and is don't-care FREE (an under-determined grid is a
        FLOOR, never absorbable — §4.05);
      * the ROW-axis variables are all declared input ports;
      * the COLUMN-axis variables are NOT declared ports (they are the external
        mux's selectors) — this is what distinguishes the decomposition family
        from an ordinary K-map, where every axis variable is a port;
      * the output width equals 2**(number of column-axis bits), and the column
        codes' binary values are exactly {0 .. width-1} (MEMBERSHIP, not count),
        so every data input is driven exactly once.
    chip-AGNOSTIC: pure boolean decomposition of the prompt's own grid.
    """
    parsed = _parse_kmap(prompt)
    if not parsed:
        return None
    col_bits, row_bits, col_codes, (row_codes, grid) = parsed
    if not col_bits or not row_bits:
        return None
    _in_orig = {orig for (d, _w, orig) in ports.values() if d == "input"}

    def _axis_base(tok: str) -> str:
        mm = re.match(r"([A-Za-z_]\w*)", tok)
        return mm.group(1) if mm else tok
    # row axis must be ports; column axis must NOT be (they are mux selects)
    if any(_axis_base(b) not in _in_orig for b in row_bits):
        return None
    if any(_axis_base(b) in _in_orig for b in col_bits):
        return None
    if out_w != 2 ** len(col_bits):
        return None
    try:
        idx = [int(c, 2) for c in col_codes]
    except ValueError:
        return None
    if sorted(idx) != list(range(out_w)):   # membership, not count
        return None
    # each data input = the column's own function of the row variables
    terms_by_idx = {}
    for j, ccode in enumerate(col_codes):
        prods = []
        for i, rcode in enumerate(row_codes):
            v = grid[i][j].lower()
            if v in ("d", "-", "x"):
                return None      # under-determined -> FLOOR (§4.05)
            if v not in ("0", "1"):
                return None
            if v == "1":
                lits = [(b if val == "1" else f"~{b}")
                        for b, val in zip(row_bits, rcode)]
                prods.append("(" + " & ".join(lits) + ")")
        terms_by_idx[int(ccode, 2)] = " | ".join(prods) if prods else "1'b0"
    decl = []
    for nm, (d, w, orig) in ports.items():
        rng = _decl_range(prompt, orig, w)
        decl.append(f"    {d:<6} {rng}{orig}")
    body = "\n".join(f"  assign {out}[{k}] = {terms_by_idx[k]};"
                      for k in range(out_w))
    return f"module {top} (\n" + ",\n".join(decl) + "\n);\n\n" + body + "\nendmodule\n"


def synth(prompt: str, top: str = "TopModule") -> Optional[str]:
    if "karnaugh" not in prompt.lower():
        return None
    ports = parse_ports(prompt)
    if not ports:
        return None
    outs = [n for n, v in ports.items() if v[0] == "output"]
    if len(outs) != 1:
        return None  # multi-output (mux decomposition) -> out of envelope
    out = ports[outs[0]][2]  # original-case output name
    out_w = ports[outs[0]][1]
    if out_w != 1:
        # A MULTI-BIT output is a K-map only in the mux-DECOMPOSITION family,
        # where the output vector carries one data input per value of the
        # selector variables. _synth_mux_decomp validates that reading against
        # the grid's own axes and returns None if it does not hold; anything
        # else multi-bit stays SKIPped (a 1-bit SOP driving `output [3:0] q`
        # compiles clean and PASSes spec_conformance while being wrong).
        # (Step-2.7 §4.05 — never emit a wrong sample.)
        return _synth_mux_decomp(prompt, top, ports, out, out_w)
    parsed = _parse_kmap(prompt)
    if not parsed:
        return None
    col_bits, row_bits, col_codes, (row_codes, grid) = parsed
    # Every K-map axis bit must be a DECLARED input port (matching the waveform
    # synth's own all-columns-are-ports guard). The axis labels are read purely
    # from the grid LAYOUT, so a case-mismatched (`A`/`B` vs ports `a`/`b`) or a
    # stray bare-word header makes the emitted SOP reference UNDECLARED signals
    # (the real ports go unused) — a wrong sample the synth must not author. A
    # bracketed bit-select `x[0]` is valid iff its base `x` is a declared port.
    # (Step-2.7 §4.05.) chip-AGNOSTIC: structural name/width checks only.
    _in_orig = {orig for (d, _w, orig) in ports.values() if d == "input"}

    def _axis_base(tok: str) -> str:
        mm = re.match(r"([A-Za-z_]\w*)", tok)
        return mm.group(1) if mm else tok
    if any(_axis_base(b) not in _in_orig for b in (list(row_bits) + list(col_bits))):
        return None
    # build minterms (1-cells); SKIP on any don't-care
    minterms: List[Dict[str, str]] = []
    for i, rcode in enumerate(row_codes):
        for j, ccode in enumerate(col_codes):
            v = grid[i][j].lower()
            if v in ("d", "-", "x"):
                return None  # under-determined -> FLOOR, not absorbable (§4.05)
            if v not in ("0", "1"):
                return None
            if v == "1":
                m: Dict[str, str] = {}
                for bit, val in zip(row_bits, rcode):
                    m[bit] = val
                for bit, val in zip(col_bits, ccode):
                    m[bit] = val
                minterms.append(m)
    all_bits = list(row_bits) + list(col_bits)
    if not minterms:
        sop = "1'b0"
    else:
        terms = []
        for m in minterms:
            lits = [(b if m[b] == "1" else f"~{b}") for b in all_bits]
            terms.append("(" + " & ".join(lits) + ")")
        sop = " | ".join(terms)
    # emit module with the prompt's exact (original-case) port list. PRESERVE the
    # declared bit RANGE verbatim (`[hi:lo]`) rather than normalising to `[w-1:0]`:
    # the K-map axis labels (and hence the emitted SOP) use the prompt's own bit
    # indices — a 1-based `input [4:1] x` (VE-v2 twin) means the SOP references
    # x[1..4], which a normalised `[3:0]` decl would push out of range. The host
    # connects a same-width net LSB-aligned, so any contiguous range works.
    decl = []
    for nm, (d, w, orig) in ports.items():
        rng = _decl_range(prompt, orig, w)
        decl.append(f"    {d:<6} {rng}{orig}")
    body = f"  assign {out} = {sop};"
    return f"module {top} (\n" + ",\n".join(decl) + "\n);\n\n" + body + "\nendmodule\n"


def _decl_range(prompt: str, port: str, width: int) -> str:
    """The original `[hi:lo] ` range string for `port` as declared in the prompt's
    module header, or `[width-1:0] ` (falling back to the parsed width) when no
    explicit range is found, or `""` for a scalar. Preserves a non-zero-LSB range
    (e.g. `[4:1]`) so emitted bit-selects stay in range."""
    if width <= 1:
        return ""
    m = re.search(r"\b(?:input|output)\b\s+(?:wire|reg|logic)?\s*"
                  r"\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*" + re.escape(port) + r"\b",
                  prompt)
    if m:
        return f"[{m.group(1)}:{m.group(2)}] "
    return f"[{width-1}:0] "


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: outside the don't-care-free K-map synth envelope", file=sys.stderr)
        return 2
    if a.out:
        Path(a.out).write_text(rtl)
    sys.stdout.write(rtl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
