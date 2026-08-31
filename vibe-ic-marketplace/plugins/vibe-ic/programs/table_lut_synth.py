#!/usr/bin/env python3
"""table_lut_synth.py — a DETERMINISTIC solver for the CVDP TABLE-DRIVEN
COMBINATIONAL family: a combinational function FULLY specified by an enumerated
table stated IN THE PROMPT — a truth table, an input->output mapping table, a
ROM/LUT with stated contents, a seven-segment / BCD-to-X code map, a stated
case/lookup.

WHY: when a CVDP "code generation" prompt embeds a COMPLETE enumerated table, the
answer is fully determined by the prompt, blind: every input combination maps to a
stated literal output (a truth table), OR the listed codes map to literal outputs
and the prose states ONE default for every other code (a case/LUT/7-seg map). Such
a function is a pure `case` over the inputs — zero authoring variance. The shipped
registry's arithmetic ops (`+`/`-`/`*`/...) would MIS-EMIT it (a truth table is not
an arithmetic identity), and the existing `oracle_table_synth` only parses the
VerilogEval single-output truth-table / K-map dialect, so the CVDP markdown forms
(multi-output, multi-bit columns, code-keyed maps with a default, hex/0x literals)
slip through. This solver EMITS the table directly: a combinational `case` (truth
table / map) honoring the stated default.

REUSE: the shipped `record_prompt_context_bridge` supplies the INTERFACE — `toplevel_name`
(the harness `.env` TOPLEVEL the testbench binds). We import + reuse it; we never
re-derive the harness plumbing. (We do NOT edit the bridge — this solver is a
standalone family solver exposing the same `solve(record)->Optional[str]` shape as
the other `cvdp_*_synth` modules.) The literal-cell / table-row grammar is composed
HERE, extending the markdown forms `spec_enumset_extract` / `oracle_table_synth`
miss (multi-output literal columns + a per-table input/output split).

§4.05 PARSE-OR-SKIP / NO-CHEAT (binding):
  * EMIT only a COMPLETE enumerated table — one that is fully determined:
      (a) a TRUTH TABLE: the input columns enumerate EVERY combination exactly once
          (rows == 2**sum(input-col widths), all input keys distinct); OR
      (b) a CASE/LUT/7-seg MAP: the listed codes map to literal outputs AND the
          prose states a single outside-the-set / default behavior (a literal
          default value) covering every unlisted code.
  * SKIP (return None) an INCOMPLETE table (missing rows AND no stated default),
    an ambiguous / parametric mapping, a non-literal output cell (a symbolic
    bit-slice expression like `{D6, D5, ...}` — that is a composite router, not a
    LUT), a SEQUENTIAL / waveform / test-vector table (clock / cycle / reset /
    previous-state / Expected-vs-Actual columns), or a composite wrapper.
  * NEVER interpolate a missing row, NEVER guess a width, NEVER read the golden RTL.
    A complete table is emitted EXACTLY; an incomplete one is SKIPPED — a wrong or
    interpolated emit is far worse than an honest skip.

API: solve(record: dict) -> Optional[str]   # emitted RTL (module == TOPLEVEL) | None
chip-AGNOSTIC (no design-name keys), pure-function, deterministic.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import record_prompt_context_bridge as _bridge  # noqa: E402  harness TOPLEVEL / interface plumbing

Port = Tuple[str, int]  # (name, width)


# --------------------------------------------------------------------------- #
# §4.05 up-front SKIP cues
# --------------------------------------------------------------------------- #
# A SEQUENTIAL / waveform / test-vector table column — its presence in a table
# HEADER means the table is a clock-by-clock trace or a TB Expected/Actual vector
# set, NOT a combinational input->output enumeration. chip-AGNOSTIC.
_SEQ_HEADER_RE = re.compile(
    r"(?i)\b(clock|cycle|reset|rst|clk|iteration|count|time|step|state|"
    r"previous|expected|actual|received|got|observed|status|pass|fail|"
    r"result|dut|module\s+output)\b|\(t\)|\(t\+1\)|t\+1")
# A composite / non-atomic design cue — reuse the bridge's own SKIP envelope so a
# protocol / bus / memory / CPU wrapper is never mistaken for a flat LUT.
_COMPOSITE_RE = _bridge._COMPOSITE_RE
# Sequential-state PROSE cue (a "holds its previous value" / "on the rising edge"
# next-state table is a flip-flop, not a combinational LUT — SKIP).
_SEQ_PROSE_RE = re.compile(
    r"(?i)\b(rising\s+edge|falling\s+edge|posedge|negedge|next[-\s]?state|"
    r"holds?\s+(?:its\s+)?previous|previous\s+state|flip[-\s]?flop|sequential|"
    r"clocked)\b|q\s*\(\s*t\s*\)")


# --------------------------------------------------------------------------- #
# literal-cell grammar (chip-AGNOSTIC, pure Verilog/markdown literal shapes)
# --------------------------------------------------------------------------- #
def _parse_literal(cell: str) -> Optional[Tuple[int, int]]:
    """Parse a single table cell as a numeric literal -> (value, bit_width), or
    None if it is not a self-contained numeric literal (a symbolic expression, a
    name, a `{a,b}` concat, prose, ...). The width is the cell's OWN stated width
    (sized literal width / hex-digit*4 / binary-digit count). A bare decimal yields
    width 0 (== "width resolved from the column max-value"). chip-AGNOSTIC."""
    c = cell.strip().strip("`*").strip()
    if not c:
        return None
    # sized binary  N'bXXXX
    m = re.fullmatch(r"(\d+)'[bB]([01_]+)", c)
    if m:
        return (int(m.group(2).replace("_", ""), 2), int(m.group(1)))
    # sized hex     N'hXX
    m = re.fullmatch(r"(\d+)'[hH]([0-9A-Fa-f_]+)", c)
    if m:
        return (int(m.group(2).replace("_", ""), 16), int(m.group(1)))
    # sized decimal N'dD
    m = re.fullmatch(r"(\d+)'[dD]([0-9_]+)", c)
    if m:
        return (int(m.group(2).replace("_", "")), int(m.group(1)))
    # 0x hex        0xFB  -> width = hex-digit count * 4
    m = re.fullmatch(r"0[xX]([0-9A-Fa-f]+)", c)
    if m:
        return (int(m.group(1), 16), len(m.group(1)) * 4)
    # bare binary   0010  (>=2 bits; width = digit count).
    if re.fullmatch(r"[01]{2,}", c):
        return (int(c, 2), len(c))
    # bare single bit 0 / 1 (1-bit).
    if c in ("0", "1"):
        return (int(c), 1)
    # bare decimal  12  -> width is UNKNOWN from the cell alone (resolved by column)
    if re.fullmatch(r"\d+", c):
        return (int(c), 0)  # width 0 == "decimal, width from column max-value"
    return None


# --------------------------------------------------------------------------- #
# markdown table extraction
# --------------------------------------------------------------------------- #
def _markdown_tables(prompt: str) -> List[Tuple[List[str], List[List[str]]]]:
    """Every GitHub-flavored markdown table: (header_cells, [row_cells, ...]).
    A table is a `| ... |` header line FOLLOWED by a `|---|---|` delimiter line,
    then `| ... |` body rows. chip-AGNOSTIC pure-markdown grammar."""
    lines = prompt.splitlines()
    out: List[Tuple[List[str], List[List[str]]]] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ("|" in ln and ln.strip().startswith("|") and i + 1 < len(lines)
                and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1])
                and "-" in lines[i + 1]):
            hdr = [c.strip().strip("`*").strip()
                   for c in ln.strip().strip("|").split("|")]
            rows: List[List[str]] = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                cells = [c.strip().strip("`*").strip()
                         for c in lines[j].strip().strip("|").split("|")]
                if len(cells) == len(hdr):
                    rows.append(cells)
                j += 1
            out.append((hdr, rows))
            i = j
        else:
            i += 1
    return out


def _header_is_output(name: str) -> Optional[bool]:
    """Best-effort: True if a header names an OUTPUT, False if an INPUT, None if
    unknown. Keyed on generic role vocabulary (o_/out/result/sum vs i_/in), never
    on a design name. Used only to ANCHOR the input/output split when the literal
    structure alone is ambiguous. chip-AGNOSTIC."""
    n = name.lower()
    if re.match(r"^(o_|out_|out\b)", n) or re.search(
            r"\b(out|output|result|sum|cout|carry[-_\s]?out|generate|propagate|"
            r"excess|gray|code_?out|seg|display|data_?out)\b", n):
        return True
    if re.match(r"^(i_|in_|in\b)", n) or re.search(
            r"\b(in|input|sel|cin|carry[-_\s]?in|addr|address|code_?in|"
            r"data_?in|bcd|binary)\b", n):
        return False
    return None


# --------------------------------------------------------------------------- #
# input/output column split + completeness
# --------------------------------------------------------------------------- #
def _resolve_col_widths(parsed: List[List[Optional[Tuple[int, int]]]], ncol: int
                        ) -> Optional[List[int]]:
    """Per-column bit-width: the max stated cell width in the column; for a column
    of bare-decimals (stated width 0) the width is ceil(log2(maxval+1)) (>=1).
    None if any cell in any column failed to parse (a non-literal table -> SKIP)."""
    widths: List[int] = []
    for c in range(ncol):
        col = [parsed[r][c] for r in range(len(parsed))]
        if any(x is None for x in col):
            return None
        stated = [w for (_v, w) in col if w > 0]  # type: ignore[misc]
        if stated:
            widths.append(max(stated))
        else:
            maxv = max(v for (v, _w) in col)  # type: ignore[misc]
            widths.append(max(1, maxv.bit_length()))
    return widths


def _split_in_out(headers: List[str],
                  parsed: List[List[Tuple[int, int]]],
                  colw: List[int]) -> Optional[Tuple[int, str]]:
    """Decide the input|output column split.

    Returns (k, mode) where k = number of INPUT columns (the first k columns) and
    mode is 'truth' (rows enumerate 2**in_w, fully complete) or 'map' (a code-keyed
    map; completeness then requires a stated default). None if no clean split.

    Strategy: input columns are a PREFIX of the columns (the conventional table
    layout: inputs left, outputs right). We try each prefix length k in 1..ncol-1
    and prefer:
      * a TRUTH-TABLE split: the k input columns' keys are all-distinct AND number
        2**(sum of their widths) (every combination once) — fully complete;
      * else a MAP split: exactly ONE input column (k==1) whose keys are distinct
        (a code -> outputs lookup), completeness deferred to a stated default.
    The header role hint (`_header_is_output`) breaks ties: a split is rejected if
    it puts an output-styled header in the input prefix or an input-styled header
    in the output suffix when the literal structure does not force it."""
    ncol = len(headers)
    nrow = len(parsed)
    roles = [_header_is_output(h) for h in headers]

    def _role_ok(k: int) -> bool:
        # no clearly-OUTPUT header inside the input prefix; no clearly-INPUT header
        # inside the output suffix (a None role never blocks).
        if any(roles[c] is True for c in range(k)):
            return False
        if any(roles[c] is False for c in range(k, ncol)):
            return False
        return True

    # 1) TRUTH-TABLE split — the strongest completeness proof.
    best_truth: Optional[int] = None
    for k in range(1, ncol):
        in_w = sum(colw[:k])
        if in_w == 0 or in_w > 16:
            continue
        keys = {tuple(parsed[r][c][0] for c in range(k)) for r in range(nrow)}
        if len(keys) == nrow == (1 << in_w) and _role_ok(k):
            # prefer the split with the FEWEST input columns that still enumerates
            # (a stable, unambiguous choice).
            if best_truth is None or k < best_truth:
                best_truth = k
    if best_truth is not None:
        return best_truth, "truth"

    # 2) MAP split — a single code column keying literal outputs (k==1).
    if ncol >= 2 and nrow >= 3:
        keys = [parsed[r][0][0] for r in range(nrow)]
        if len(set(keys)) == nrow and _role_ok(1):
            return 1, "map"
    return None


# --------------------------------------------------------------------------- #
# stated default (outside-the-set) literal value, per output column
# --------------------------------------------------------------------------- #
_DEFAULT_CLAUSE_RE = re.compile(
    r"(?i)\b(any\s+other|all\s+other|otherwise|unsupported|unrecognized|"
    r"unlisted|invalid|reserved|illegal|not\s+(?:in|listed|valid|defined)|"
    r"outside|out[- ]of[- ]range|default)\b")


def _stated_default_value(prompt: str, out_w: int) -> Optional[int]:
    """A stated single default value for unlisted codes, e.g. 'invalid inputs ...
    output is set to 0' / 'defaults to 8'hFF'. Returns the literal value (masked to
    out_w) ONLY when the prose unambiguously states ONE default value AND the
    boundary clause is present; else None. The common 'set to 0' / 'output 0' case
    is honored. chip-AGNOSTIC: generic boundary + value grammar, no design literal.

    §4.05: this is the load-bearing completeness anchor for a MAP — without a
    stated default a code-keyed map is INCOMPLETE and must SKIP. So the bar is
    strict: a boundary token MUST co-occur with an explicit resulting value."""
    if not _DEFAULT_CLAUSE_RE.search(prompt):
        return None
    # scan each boundary token; within the SAME sentence look for a stated value:
    # an explicit literal (N'h.. / 0x.. / sized / >=2-bit binary) or a zero default.
    for tok in _DEFAULT_CLAUSE_RE.finditer(prompt):
        lo = max(prompt.rfind(".", 0, tok.start()),
                 prompt.rfind("\n\n", 0, tok.start()))
        lo = 0 if lo < 0 else lo
        hi = prompt.find(".", tok.end())
        hi = len(prompt) if hi < 0 else hi
        clause = prompt[lo:hi]
        # explicit literal value tied to a result verb.
        m = re.search(
            r"(?:set\s+to|output\w*\s+(?:is\s+|to\s+)?|defaults?\s+to|=|->|→)\s*"
            r"(`?)((?:\d+'[bBhHdD][0-9A-Fa-f_xXzZ]+)|0[xX][0-9A-Fa-f]+|[01]{2,})\1",
            clause)
        if m:
            lit = _parse_literal(m.group(2))
            if lit is not None:
                return lit[0] & ((1 << out_w) - 1)
        # zero default ('set to 0', 'output 0', 'output is zero', 'are zero').
        if re.search(r"(?i)\b(set\s+to|output\w*(?:\s+is|\s+to)?|are|to|be|"
                     r"defaults?\s+to)\s+(?:`?0`?|zero)\b", clause):
            return 0
        if re.search(r"(?i)\bzero\b", clause) and re.search(
                r"(?i)\b(output|outputs?|result)\b", clause):
            return 0
    return None


# --------------------------------------------------------------------------- #
# RTL emit
# --------------------------------------------------------------------------- #
def _verilog_width_decl(name: str, w: int, direction: str, reg: bool = False) -> str:
    kw = f"{direction} reg" if reg else direction
    if w > 1:
        return f"    {kw} [{w-1}:0] {name}"
    return f"    {kw} {name}"


def _sanitize_name(raw: str) -> Optional[str]:
    """A header cell -> a legal Verilog identifier, or None if it is not a clean
    single signal name (a parenthetical gloss / multi-word phrase is rejected so we
    never emit a malformed port). chip-AGNOSTIC."""
    n = raw.strip().strip("`*").strip()
    # drop a trailing parenthetical gloss: 'o_Cout (carry-out)' -> 'o_Cout'
    n = re.sub(r"\s*\(.*$", "", n).strip()
    if re.fullmatch(r"[A-Za-z_]\w*", n):
        return n
    return None


def _emit_case_rtl(top: str, in_cols: List[Tuple[str, int]],
                   out_cols: List[Tuple[str, int]],
                   rows_keys: List[Tuple[int, ...]],
                   rows_outs: List[Tuple[int, ...]],
                   mode: str, default_vals: List[int]) -> str:
    """Emit a combinational `always @(*) case({inputs}) ... endcase` that assigns
    each output column. For a 'truth' table every combination is a case label and
    the (unreachable) default is the stated default or 0. For a 'map' the listed
    codes are case labels and the default is the STATED default (required)."""
    in_w = sum(w for _, w in in_cols)
    decls = [_verilog_width_decl(n, w, "input") for n, w in in_cols]
    decls += [_verilog_width_decl(n, w, "output", reg=True) for n, w in out_cols]
    cat = ("{" + ", ".join(n for n, _ in in_cols) + "}"
           if len(in_cols) > 1 else in_cols[0][0])

    lines = [
        "// program-SOLVED from the prompt's own enumerated table; deterministic, no AI.",
        f"module {top} (",
        ",\n".join(decls),
        ");",
        "    always @(*) begin",
    ]
    # default assignments first (so every output is always assigned on every path).
    for oi, (on, ow) in enumerate(out_cols):
        lines.append(f"        {on} = {ow}'d{default_vals[oi]};")
    lines.append(f"        case ({cat})")
    for ri, key in enumerate(rows_keys):
        if len(in_cols) > 1:
            label = f"{in_w}'b" + "".join(
                format(key[ci], f"0{in_cols[ci][1]}b") for ci in range(len(in_cols)))
        else:
            label = f"{in_w}'d{key[0]}"
        assigns = "; ".join(
            f"{out_cols[oi][0]} = {out_cols[oi][1]}'d{rows_outs[ri][oi]}"
            for oi in range(len(out_cols)))
        lines.append(f"            {label}: begin {assigns}; end")
    dflt = "; ".join(
        f"{out_cols[oi][0]} = {out_cols[oi][1]}'d{default_vals[oi]}"
        for oi in range(len(out_cols)))
    lines.append(f"            default: begin {dflt}; end")
    lines += ["        endcase", "    end", "endmodule", ""]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# table -> (interface + rows), the core parse
# --------------------------------------------------------------------------- #
def _solve_table(prompt: str, top: str) -> Optional[Tuple[str, str]]:
    """Try every markdown table in the prompt; return (rtl, mode) for the FIRST
    that is a complete enumerated combinational function. None if none qualifies
    (§4.05 SKIP)."""
    for headers, rows in _markdown_tables(prompt):
        ncol = len(headers)
        nrow = len(rows)
        if ncol < 2 or nrow < 3:
            continue
        # SKIP a sequential / waveform / TB-vector table outright.
        if any(_SEQ_HEADER_RE.search(h) for h in headers):
            continue
        # parse every cell as a literal; a single non-literal cell disqualifies the
        # whole table (a symbolic-expression output column is a router, not a LUT).
        parsed: List[List[Optional[Tuple[int, int]]]] = [
            [_parse_literal(c) for c in row] for row in rows]
        if any(any(x is None for x in row) for row in parsed):
            continue
        colw = _resolve_col_widths(parsed, ncol)  # type: ignore[arg-type]
        if colw is None:
            continue
        split = _split_in_out(headers, parsed, colw)  # type: ignore[arg-type]
        if split is None:
            continue
        k, mode = split
        # build column ports; every header must sanitize to a legal identifier.
        names = [_sanitize_name(h) for h in headers]
        if any(n is None for n in names):
            continue
        in_cols = [(names[c], colw[c]) for c in range(k)]
        out_cols = [(names[c], colw[c]) for c in range(k, ncol)]
        if not in_cols or not out_cols:
            continue
        # de-dup guard: every name distinct.
        all_names = [n for n, _ in in_cols + out_cols]
        if len(set(all_names)) != len(all_names):
            continue

        rows_keys = [tuple(parsed[r][c][0] for c in range(k)) for r in range(nrow)]
        rows_outs = [tuple(parsed[r][c][0] for c in range(k, ncol))
                     for r in range(nrow)]

        if mode == "truth":
            # fully complete: emit with a benign default (unreachable).
            rtl = _emit_case_rtl(top, in_cols, out_cols, rows_keys, rows_outs,
                                 mode, default_vals=[0] * len(out_cols))
            return rtl, "truth"

        # mode == "map": if the single input column already enumerates its full
        # domain (rows == 2**in_w, keys distinct) it is complete WITHOUT a default
        # -> treat it as a truth table.
        in_w = in_cols[0][1]
        keyset = {kk[0] for kk in rows_keys}
        if len(keyset) == nrow == (1 << in_w) and in_w <= 16:
            rtl = _emit_case_rtl(top, in_cols, out_cols, rows_keys, rows_outs,
                                 "truth", default_vals=[0] * len(out_cols))
            return rtl, "truth"
        # else require a stated default value per output column (the §4.05 anchor).
        default_vals: List[int] = []
        ok = True
        for _on, ow in out_cols:
            dv = _stated_default_value(prompt, ow)
            if dv is None:
                ok = False
                break
            default_vals.append(dv)
        if not ok:
            continue  # incomplete map, no stated default -> SKIP this table
        rtl = _emit_case_rtl(top, in_cols, out_cols, rows_keys, rows_outs,
                             "map", default_vals=default_vals)
        return rtl, "map"
    return None


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def solve(record: dict) -> Optional[str]:
    """Emit deterministic combinational RTL (module named per harness TOPLEVEL) for
    a CVDP problem whose function is FULLY specified by an enumerated table in the
    prompt, or None (§4.05 SKIP)."""
    res = _solve_with_mode(record)
    return res[0] if res else None


def _solve_with_mode(record: dict) -> Optional[Tuple[str, str]]:
    if not isinstance(record, dict):
        return None
    top = _bridge.toplevel_name(record)
    if not top:
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None
    # §4.05 up-front SKIP: a composite / protocol / bus / CPU wrapper, or a
    # clearly-sequential (clocked next-state) design, is never a flat combinational
    # LUT — SKIP rather than emit a combinational table for a sequential function.
    if _COMPOSITE_RE.search(prompt) or _SEQ_PROSE_RE.search(prompt):
        return None
    return _solve_table(prompt, top)


def variant_of(record: dict) -> Optional[str]:
    """The table variant this solver emitted ('truth' | 'map'), for reporting.
    None if the record was SKIPPED."""
    res = _solve_with_mode(record)
    return res[1] if res else None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jsonl", required=True, help="CVDP code-generation jsonl")
    ap.add_argument("--id", help="solve only this record id")
    ap.add_argument("--emit", action="store_true", help="print emitted RTL")
    a = ap.parse_args(argv)
    recs = [json.loads(l) for l in open(a.jsonl)]
    n_emit = 0
    fam: Dict[str, int] = {}
    for r in recs:
        if a.id and r.get("id") != a.id:
            continue
        res = _solve_with_mode(r)
        if res:
            n_emit += 1
            k = res[1]
            fam[k] = fam.get(k, 0) + 1
            if a.emit or a.id:
                print(f"=== {r.get('id')}  variant={k} ===")
                print(res[0])
    print(f"emitted={n_emit}/{len(recs)}  variants={fam}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
