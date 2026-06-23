#!/usr/bin/env python3
"""kmap_sop_synth.py — deterministic Karnaugh-map (K-map) -> RTL SOLVER.

WHY (spec->RTL extraction completeness, ② -> ①):
A VerilogEval-class prompt that hands the design a Karnaugh map IS a complete
combinational specification: every CARE cell discloses the required output for a
fully-determined input combination, blind. Today the K-map machinery in the plugin
(`kmap_truth_table_oracle_check.py`) is an *oracle GATE* — it parses the map and
BLOCKS a mis-authored RTL — but it does not itself EMIT RTL. This program is the
complementary SOLVER: it reads the prompt, parses the K-map grid, and EMITS correct
synthesizable RTL deterministically, or returns None (SKIP) on ANY parse ambiguity.

WHAT it handles (general / chip-AGNOSTIC):
  - scalar named 1-bit axes, header 1-var ("0 1") OR 2-var ("00 01 11 10" Gray, in
    ANY order — e.g. Prob125's reordered "01 00 10 11"); row axis labels likewise in
    any order, validated against the declared axis-variable count;
  - bus-indexed axes (`x[0]x[1]` / `x[3]x[4]`): a single multi-bit input bus whose
    K-map axes are bit-indices of that bus; the distinct indices are mapped to bus
    bits in ascending order (the only convention consistent with a 1-based label set
    like x[1..4] on a 4-bit bus);
  - don't-care cells ('d' or 'x'): assigned the canonical minimal-risk value 0; the
    caller MUST host-verify (the TB checks the function on CARE cells only, so any
    valid cover is accepted — but a chosen don't-care assignment that the TB happens
    to constrain will show as a mismatch and the honest response is to SKIP);
  - emits a FULL truth-table `case` over all 2^N input combinations (deterministic,
    provably correct on every CARE cell — no risky minimization step that could
    drop a variable wrong).

§4.05 NO-LEAK — SKIP (return None) on ANY ambiguity in PARSING the map:
  - cannot locate the column header / row labels / cell grid;
  - axis variables do not partition the declared inputs exactly;
  - a multi-bit output or an explicit transform ("multiplexer"/"mux_in") — the
    output is NOT the K-map value (Prob093) -> SKIP;
  - a cell that is neither 0/1 nor a recognised don't-care token -> SKIP;
  - the reconstructed table is not COMPLETE (every 2^N combination exactly once)
    -> SKIP.
For don't-cares the EMIT itself is unambiguous (we pick 0); whether that emission is
*correct* is decided by the caller's host-score (iverilog+vvp against the TB). If it
mismatches, the TB constrains the don't-cares and the honest floor is to SKIP that
problem rather than guess a different cover.

API:
    synth(prompt_text, top="TopModule") -> str | None

CLI (host-score harness):
    python3 kmap_sop_synth.py --prompt <prompt.txt> [--top TopModule] > dut.sv
    iverilog -g2012 -o a.vvp dut.sv <Prob>_ref.sv <Prob>_test.sv && vvp a.vvp

Reuses parse_ports / parse_kmap heritage from kmap_truth_table_oracle_check.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Reuse the shared port reader (bullet form OR Verilog module header) and the
# K-map keyword test from the existing oracle program — do NOT re-implement them.
from kmap_truth_table_oracle_check import parse_ports, _is_kmap_prompt  # noqa: E402

_DONTCARE = {"d", "x", "X", "-"}
_GRAY2 = ["00", "01", "11", "10"]


def _cell_value(tok: str):
    """Map a grid cell token -> 0 | 1 | 'D' (don't-care) | None (unparseable)."""
    tok = tok.strip()
    if tok in ("0", "1"):
        return int(tok)
    if tok in _DONTCARE:
        return "D"
    return None


def _find_header(lines):
    """Locate the K-map column header line: a TRAILING run of 1-var ('0 1') or
    2-var ('00 01 11 10', any permutation) binary labels. Leading non-binary
    tokens (a row-axis name like 'cd', or 'bc') are allowed before the run.
    Returns (idx, col_labels) or (None, None). Requires the labels to be a clean
    permutation of the canonical set so a stray binary-looking prose line never
    matches, and requires a following '|'-delimited grid row (checked by caller)."""
    for i, ln in enumerate(lines):
        toks = ln.split()
        if not toks:
            continue
        # take the maximal trailing run of equal-width binary tokens
        run = []
        for t in reversed(toks):
            if re.fullmatch(r"[01]+", t) and (not run or len(t) == len(run[0])):
                run.insert(0, t)
            else:
                break
        if not run:
            continue
        w = len(run[0])
        n = len(run)
        if w not in (1, 2):
            continue
        # a 1-var axis header is exactly 2 labels; a 2-var axis header exactly 4.
        if not ((w == 1 and n == 2) or (w == 2 and n == 4)):
            continue
        expect = {format(v, f"0{w}b") for v in range(2 ** w)}
        if set(run) != expect or len(set(run)) != n:
            continue
        # the leading (non-run) tokens must look like a column/row axis spec or be
        # absent — guards against matching an arbitrary line that happens to end in
        # a binary run.
        lead = toks[: len(toks) - n]
        if lead and not all(_axis_vars(t) for t in lead):
            # allow a single concatenated axis token too (handled in caller); but a
            # truly arbitrary leading token disqualifies the line.
            if not (len(lead) == 1 and _axis_vars(lead[0])):
                continue
        return i, run
    return None, None


def _axis_vars(label: str):
    """Parse an axis variable spec into an ordered list of variable tokens.

    Two forms:
      - scalar concatenation:  'ab' -> ['a','b'] ;  'bc' -> ['b','c']
      - bus-indexed:           'x[0]x[1]' -> ['x[0]','x[1]']
    Returns None if the form is not recognised."""
    label = label.strip()
    if not label:
        return None
    # bus-indexed: one or more <name>[<idx>] with no other chars
    idx = re.findall(r"[A-Za-z_]\w*\s*\[\s*\d+\s*\]", label)
    if idx and re.fullmatch(r"(\s*[A-Za-z_]\w*\s*\[\s*\d+\s*\]\s*)+", label):
        return [re.sub(r"\s+", "", t) for t in idx]
    # scalar concatenation: a run of single letters only
    if re.fullmatch(r"[A-Za-z]+", label):
        return list(label)
    return None


def _line_above_axis(lines, hdr_idx):
    """The column-axis spec sits on the nearest preceding non-empty, non-'|',
    non-row-label line above the header (e.g. the 'ab' above 'cd 00 01 11 10').
    Returns that token-joined spec if it parses as an axis, else None."""
    for j in range(hdr_idx - 1, max(-1, hdr_idx - 5), -1):
        cand = lines[j].strip()
        if not cand or "|" in cand or "kmap" in cand.lower():
            continue
        # a single axis token, or a run of single letters joined
        if _axis_vars(cand):
            return cand
        joined = "".join(cand.split())
        if _axis_vars(joined):
            return joined
        return None
    return None


def _header_leftover_axis(lines, hdr_idx, col_labels):
    """The row-axis spec is the leading non-label token(s) on the header line
    (e.g. 'cd' in '   cd   00 01 11 10'). Returns it if it parses, else None."""
    toks = lines[hdr_idx].split()
    lead = toks[: len(toks) - len(col_labels)]
    if not lead:
        return None
    if len(lead) == 1 and _axis_vars(lead[0]):
        return lead[0]
    joined = "".join(lead)
    if _axis_vars(joined):
        return joined
    return None


def _col_axis_label(lines, hdr_idx, col_labels):
    """Column-axis variable spec — on the line ABOVE the column-label header. The
    header line's leading leftover token is the ROW axis, never the column axis,
    so we must NOT use it here."""
    return _line_above_axis(lines, hdr_idx)


def _row_axis_label(lines, hdr_idx, col_labels):
    """Row-axis variable spec — the leading token on the header line (the usual
    '   cd   00 01 11 10' shape). If the header line carries no leftover (the row
    axis sits on a separate preceding line above the column axis), fall back to
    that line. Always returns a spec distinct from the column axis when possible."""
    lo = _header_leftover_axis(lines, hdr_idx, col_labels)
    if lo:
        return lo
    # rare: row axis on a line above the column axis
    col = _line_above_axis(lines, hdr_idx)
    for j in range(hdr_idx - 1, max(-1, hdr_idx - 6), -1):
        cand = lines[j].strip()
        if not cand or "|" in cand:
            continue
        if cand == col:
            continue
        if _axis_vars(cand):
            return cand
    return None


def parse_kmap_grid(prompt: str):
    """Parse a K-map grid from the prompt into a complete care/dont-care table.

    Returns (in_field, out_name, table) where:
      - in_field is either a list of scalar 1-bit names, OR a single ('bus', width,
        {var_label: bus_bit}) descriptor for the bus-indexed form;
      - table maps a tuple key -> 0 | 1 | 'D'.
    Returns None on ANY ambiguity (§4.05 SKIP).
    """
    ins, outs = parse_ports(prompt)
    if not ins or not outs:
        return None
    if len(outs) != 1 or outs[0][1] != 1:
        return None  # multi-bit / transform output -> SKIP (e.g. Prob093 mux_in)
    out_name = outs[0][0]
    if re.search(r"multiplexer|\bmux\b|mux_in", prompt, re.I):
        return None  # explicit transform problem -> SKIP

    lines = prompt.splitlines()
    hdr_idx, col_labels = _find_header(lines)
    if hdr_idx is None:
        return None

    col_label_spec = _col_axis_label(lines, hdr_idx, col_labels)
    row_label_spec = _row_axis_label(lines, hdr_idx, col_labels)
    if not col_label_spec or not row_label_spec:
        return None
    col_vars = _axis_vars(col_label_spec)
    row_vars = _axis_vars(row_label_spec)
    if not col_vars or not row_vars:
        return None
    # a 2-var header demands a 2-var axis; a 1-var header a 1-var axis
    cw = len(col_labels[0])
    if len(col_vars) != cw:
        return None
    if col_vars == row_vars:
        return None  # degenerate

    # ---- read the grid rows: each '<rowlabel> | c0 | c1 | ... |' ----
    row_w = None  # width of row labels, inferred from first grid row
    grid = []  # list of (row_label_str, [cell tokens])
    for ln in lines[hdr_idx + 1:]:
        if "|" not in ln:
            # allow blank lines inside? a blank line terminates the grid.
            if ln.strip() == "":
                if grid:
                    break
                continue
            continue
        m = re.match(r"\s*([01]+)\s*\|(.+\|)\s*$", ln)
        if not m:
            # a line with '|' but no leading binary row label ends the grid
            if grid:
                break
            continue
        rlabel = m.group(1)
        body = m.group(2)
        cells = [c.strip() for c in body.split("|") if c.strip() != ""]
        grid.append((rlabel, cells))

    if not grid:
        return None
    row_w = len(grid[0][0])
    if len(row_vars) != row_w:
        return None
    expect_rows = {format(v, f"0{row_w}b") for v in range(2 ** row_w)}
    seen_rows = {rl for rl, _ in grid}
    if seen_rows != expect_rows or len(grid) != len(expect_rows):
        return None  # rows must be exactly the permutation set, once each

    n_cols = len(col_labels)
    table = {}  # (assignment over col_vars+row_vars) tuple in var-order -> val
    # We key the table by a canonical ordering of ALL axis variables. For scalar
    # axes that's the declared input order; for the bus form it's bit-ascending.
    all_vars = col_vars + row_vars

    # validate axis variables against the declared interface ----------------------
    bus_form = any("[" in v for v in all_vars)
    if bus_form:
        # every axis var must be <bus>[idx] of THE single multi-bit input bus
        buses = [(n, w) for n, w in ins if w > 1]
        scalars = [(n, w) for n, w in ins if w == 1]
        if len(buses) != 1 or scalars:
            return None
        bus_name, bus_w = buses[0]
        idxs = []
        for v in all_vars:
            mm = re.fullmatch(rf"{re.escape(bus_name)}\[(\d+)\]", v)
            if not mm:
                return None  # an axis var that is not a bit of THE bus -> SKIP
            idxs.append(int(mm.group(1)))
        if len(set(idxs)) != len(idxs):
            return None
        if len(idxs) != bus_w:
            return None  # axes must cover exactly the whole bus
        # map distinct indices -> ascending bus bits (handles 0-based x[0..3] and
        # 1-based x[1..4] uniformly: sorted indices -> bits 0..w-1)
        order = sorted(set(idxs))
        bit_of = {ix: pos for pos, ix in enumerate(order)}
        var_bit = {v: bit_of[int(re.fullmatch(rf"{re.escape(bus_name)}\[(\d+)\]", v).group(1))]
                   for v in all_vars}
        # PRESERVE the prompt's DECLARED bus index range instead of normalizing to
        # zero-based [w-1:0]. The K-map axis indices ARE the declared bit indices
        # (x[1]..x[4] => 1-based => [4:1]); a hardcoded [3:0] declaration is an
        # off-by-one vs the prompt and is (correctly) emit-blocked by the
        # `onebased-port-range` conformance guard. `var_bit` already maps the
        # smallest index to bit 0 (the LSB), so a `[hi:lo]` declaration with
        # lo=min(idxs) keeps that index at the LSB — value-consistent with the
        # case table. (0-based axes give lo=0,hi=w-1 => [w-1:0], unchanged.)
        in_field = ("bus", bus_name, bus_w, min(order), max(order))
    else:
        in_names = [n for n, _ in ins]
        if any(w != 1 for _, w in ins):
            return None  # scalar K-map requires all-scalar inputs
        if sorted(all_vars) != sorted(in_names):
            return None  # axes must exactly partition the scalar inputs
        if len(set(all_vars)) != len(all_vars):
            return None
        in_field = in_names

    # ---- fill the table -----------------------------------------------------
    col_index = {lab: i for i, lab in enumerate(col_labels)}
    for rlabel, cells in grid:
        if len(cells) != n_cols:
            return None  # ragged grid -> SKIP
        for clabel in col_labels:
            ci = col_index[clabel]
            val = _cell_value(cells[ci])
            if val is None:
                return None  # unparseable cell -> SKIP
            assign = {}
            for k, v in enumerate(col_vars):
                assign[v] = int(clabel[k])
            for k, v in enumerate(row_vars):
                assign[v] = int(rlabel[k])
            if bus_form:
                bus_val = 0
                for v in all_vars:
                    bus_val |= (assign[v] << var_bit[v])
                key = bus_val
            else:
                key = tuple(assign[n] for n in in_field)
            if key in table:
                return None  # duplicate cell -> SKIP
            table[key] = val

    # completeness
    n_inputs = (in_field[2] if bus_form else len(in_field))
    if len(table) != 2 ** n_inputs:
        return None
    return (in_field, out_name, table)


def _emit_case_rtl(in_field, out_name, table, top: str) -> str:
    """Emit a full truth-table case-statement module. don't-care -> 0."""
    bus_form = isinstance(in_field, tuple) and in_field and in_field[0] == "bus"
    lines = []
    if bus_form:
        # in_field may be the legacy 3-tuple or the range-carrying 5-tuple.
        bus_name, bus_w = in_field[1], in_field[2]
        lo, hi = (in_field[3], in_field[4]) if len(in_field) >= 5 else (0, bus_w - 1)
        lines.append(f"module {top} (")
        lines.append(f"  input [{hi}:{lo}] {bus_name},")
        lines.append(f"  output reg {out_name}")
        lines.append(");")
        lines.append("  always @(*) begin")
        lines.append(f"    case ({bus_name})")
        for k in range(2 ** bus_w):
            v = table[k]
            bit = 0 if v == "D" else v
            lines.append(f"      {bus_w}'d{k}: {out_name} = 1'b{bit};")
        lines.append(f"      default: {out_name} = 1'b0;")
        lines.append("    endcase")
        lines.append("  end")
        lines.append("endmodule")
    else:
        in_names = list(in_field)
        n = len(in_names)
        lines.append(f"module {top} (")
        for nm in in_names:
            lines.append(f"  input {nm},")
        lines.append(f"  output reg {out_name}")
        lines.append(");")
        cat = "{" + ", ".join(in_names) + "}"
        lines.append("  always @(*) begin")
        lines.append(f"    case ({cat})")
        for combo in range(2 ** n):
            key = tuple((combo >> (n - 1 - i)) & 1 for i in range(n))
            v = table[key]
            bit = 0 if v == "D" else v
            lines.append(f"      {n}'d{combo}: {out_name} = 1'b{bit};")
        lines.append(f"      default: {out_name} = 1'b0;")
        lines.append("    endcase")
        lines.append("  end")
        lines.append("endmodule")
    return "\n".join(lines) + "\n"


def synth(prompt_text: str, top: str = "TopModule"):
    """Parse the prompt's K-map and EMIT correct RTL, or return None (SKIP).

    SKIP on: no K-map keyword, unparseable grid/axes, multi-bit/transform output,
    or any §4.05 ambiguity. For don't-cares the emit picks 0 (caller host-verifies)."""
    if not _is_kmap_prompt(prompt_text):
        return None
    parsed = parse_kmap_grid(prompt_text)
    if parsed is None:
        return None
    in_field, out_name, table = parsed
    return _emit_case_rtl(in_field, out_name, table, top)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    pp = Path(a.prompt)
    if not pp.is_file():
        print(f"kmap_sop_synth: missing prompt {a.prompt}", file=sys.stderr)
        return 2
    rtl = synth(pp.read_text(errors="replace"), a.top)
    if rtl is None:
        print("kmap_sop_synth: SKIP (no unambiguous K-map parseable from prompt)",
              file=sys.stderr)
        return 3
    sys.stdout.write(rtl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
