#!/usr/bin/env python3
"""prompt_example_selftest.py — RUN the prompt's own worked examples as a blind,
deterministic, scorer-independent pre-emit self-test against the authored RTL.

WHY (legitimate — NOT cheating)
  The worked example is IN THE PROMPT; the blind author sees it. Most CVDP /
  doc->RTL prompts embed deterministic input->output evidence — an
  "Observed vs Expected" / cycle-by-cycle waveform table, or a worked-arithmetic
  line ("0x57 * 0x13 = 0xFE", "11 / 3 => quotient 3 remainder 2"). Today nothing
  RUNS those rows against the authored RTL, so a functionally-wrong first draft
  that contradicts the prompt's OWN stated example can still emit. This gate
  EXTRACTS those rows from the prompt prose and RUNS them as an iverilog
  self-testbench, BLOCKING emit on a clean, fully-mapped mismatch — forcing the
  design to reproduce the prompt's own evidence before it can ship.

  Sibling `spec_example_smoke_tb.py` (#728/#738) already runs the COMBINATIONAL
  `a=3,b=4 -> sum=7` row and the register-map indirection golden. THIS program is
  the additive complement: (1) SEQUENTIAL cycle / waveform / "Observed-Expected"
  TABLES driven on a real clock with a reset + latency-convention sweep, and
  (2) worked-ARITHMETIC operator lines (`A op B = C`, division quotient/remainder)
  mapped positionally to the RTL's data ports. The core logic is benchmark-
  agnostic — it operates on (prompt_text, rtl_source, module_name); no CVDP
  literal appears in it.

CONSERVATISM (HARD — a false BLOCK on a misparsed example is worse than a SKIP)
  * NEVER recompute the arithmetic. The prompt STATES the result; we drive the
    operands and assert the STATED result. (`*` in a Galois-field prompt is GF
    multiply, not integer `*` — recomputing would false-block a correct design.)
  * "Observed"/"Actual"/"Got"/"Buggy" table columns carry the WRONG value — they
    are dropped; only "Expected"/"Golden"/"Correct" (or unmarked) output columns
    are asserted.
  * A table is only run when EVERY module input is driven (a table column, a
    clk/reset/enable we handle, or a prose-stated CONSTANT mapped by exact port
    name); if any module input is unlisted the output may depend on it -> SKIP.
  * A column / example value is read in its column's base — bare hex (`A1B2C3D4`)
    and zero-padded binary (`0011` BCD) are detected so they are NOT misread as
    decimal; the prompt's STATED value is asserted, never recomputed.
  * If a mapped port has a PARAMETER-derived width, the example may assume
    non-default parameters (we instantiate with defaults) -> SKIP, never block.
  * A clocked arithmetic example with an un-timed start/valid handshake whose
    pulse we cannot reproduce -> SKIP.
  * A sparse / non-consecutive cycle column (10,20,30) cannot be reproduced cycle
    by cycle -> SKIP.
  * Ambiguous sampling timing / reset polarity -> try the small set of canonical
    conventions and PASS if ANY fully matches; FAIL only when ALL mismatch.
  * iverilog absent, no extractable example, ports don't map, or the TB does not
    compile against the RTL -> SKIP (advisory, never block).
  FAIL (block, exit 1) is reserved for a CLEAN, fully-mapped vector set that
  simulates and mismatches under every attempted convention.

VERDICT  {ran:bool, vectors:int, failures:[...], verdict:PASS|FAIL|SKIP, ...}
CLI      prompt_example_selftest.py --prompt P --rtl R [--top NAME] [--latency N]
         [--warn] [--json OUT]   exit 0 = PASS/SKIP, exit 1 = FAIL
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Reuse the canonical Spec<->RTL port parser (module name + direction + width) —
# the SAME structural primitive spec_example_smoke_tb / spec_coverage_check use.
try:
    import _specrtl_common as _SRC
except ImportError:  # packaged
    from . import _specrtl_common as _SRC  # type: ignore


# ---------------------------------------------------------------------------
# Generic (chip-AGNOSTIC) signal-role name sets — never a chip SKU.
# ---------------------------------------------------------------------------
# A clock input (drives the sequential TB).
_CLK_NAMES = re.compile(r"^(?:clk|clock|clki|iclk|clkin|clk_in|sysclk)$", re.I)
# A reset input (handled by the reset sequence, not a data column). General
# naming: an optional a/n/async/sync prefix, the rst|reset core, an optional
# async/sync infix, and an optional active-low _n/_b suffix — so rst_async_n,
# rst_sync_n, async_rst_n, resetb, arst_n, ... all read as the reset (anchored,
# so a data port like `reset_value`, `first`, or `burst` never matches).
_RST_NAMES = re.compile(
    r"^(?:"
    r"(?:a|n|async_?|sync_?)?(?:rst|reset)(?:_?(?:async|sync))?(?:_?[nb])?"
    r"|nrst|nreset|arst|arstn"
    r"|clr|clear|por"
    r")$", re.I)
# Enable-type inputs default to ASSERTED (1) when a table does not list them
# (the universal "the module is enabled" reading). 'start'/'valid' are NOT here:
# their timing matters, so an unlisted one forces a SKIP.
_ENABLE_NAMES = re.compile(r"^(?:en|ena|enable|ce|clken|clk_en|clock_enable|"
                           r"i_enable|en_in)$", re.I)
# Trigger / handshake inputs whose TIMING matters (a start pulse, a valid beat,
# a load strobe). When a CLOCKED design exposes one of these and the example is
# an arithmetic / named line (NOT a per-cycle table), we cannot know when to
# pulse it -> SKIP rather than mis-drive. In a cycle TABLE these are listed with
# explicit per-cycle values, so they ARE driven there.
_TRIGGER_NAMES = re.compile(
    r"^(?:start|valid|ready|load|go|ack|req|stb|strobe|begin|launch|trigger|"
    r"kick|fire|wr|rd|write|read|push|pop|sample|capture|shift)$", re.I)


def _strip_io_prefix(name: str) -> str:
    """Drop a conventional i_/o_/in_/out_ direction prefix for role matching."""
    return re.sub(r"^(?:i|o|in|out)_", "", name, flags=re.I)


def _role_match(rx: "re.Pattern", name: str) -> bool:
    return bool(rx.match(name) or rx.match(_strip_io_prefix(name)))


def _is_clk(name: str) -> bool:
    return _role_match(_CLK_NAMES, name)


def _is_rst(name: str) -> bool:
    return _role_match(_RST_NAMES, name)


def _is_enable(name: str) -> bool:
    return _role_match(_ENABLE_NAMES, name)


def _is_trigger(name: str) -> bool:
    return _role_match(_TRIGGER_NAMES, name)


def _is_ctrl_input(name: str) -> bool:
    """Control inputs excluded from the arithmetic "data operand" count (so a
    2-input adder maps cleanly; a `mode`/`sel`/`op` input is NOT control -> it
    stays counted, the operand count != 2, and we SKIP rather than guess)."""
    return (_is_clk(name) or _is_rst(name) or _is_enable(name)
            or _is_trigger(name))
# Status / handshake outputs excluded from the arithmetic "data result" count.
_STATUS_OUTPUT = re.compile(r"^(?:valid|ready|done|busy|ack|error|err|o_ready|"
                            r"o_valid|o_done|empty|full)$", re.I)
# Table header tokens that name a cycle/time index column (not a port).
_CYCLE_HDR = re.compile(r"^(?:cycle|cycles|clk|clock|time|t|step|tick|n|index)$",
                        re.I)
# Header markers that distinguish a GOLDEN column from a WRONG ("observed") one.
_EXPECTED_MARK = re.compile(r"\b(?:expected|golden|correct|should|reference|"
                            r"ref|gold)\b", re.I)
_OBSERVED_MARK = re.compile(r"\b(?:observed|actual|got|current|buggy|wrong|"
                            r"erroneous|incorrect|measured)\b", re.I)
# Cell don't-care markers.
_DONTCARE = re.compile(r"^(?:-+|x+|\?+|n/?a|dc|don'?t\s*care|unchanged|—|–)$",
                       re.I)


def _norm(s: str) -> str:
    """Case/underscore-insensitive port-name key."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


# ---------------------------------------------------------------------------
# Numeric-literal parsing.  We NEVER compute arithmetic — we only read the
# values the prompt itself states (operands AND result).
# ---------------------------------------------------------------------------
_LIT_RE = re.compile(
    r"[+-]?(?:"
    r"\d*\s*'\s*[sS]?[bBoOdDhH][0-9a-fA-FxXzZ_]+"   # sized Verilog 8'hFF / 'b10
    r"|0[xX][0-9a-fA-F_]+"                            # 0x57
    r"|0[bB][01_]+"                                   # 0b1010
    r"|\d[\d_]*"                                      # decimal
    r")")


def _lit_to_int(tok: str) -> Optional[int]:
    """Parse a single numeric literal to int. x/z (unknown) -> None."""
    t = tok.strip().replace(" ", "")
    neg = t.startswith("-")
    t = t.lstrip("+-")
    m = re.match(r"^(\d*)'([sS]?)([bBoOdDhH])([0-9a-fA-FxXzZ_]+)$", t)
    if m:
        base = {"b": 2, "o": 8, "d": 10, "h": 16}[m.group(3).lower()]
        digits = m.group(4).replace("_", "")
        if re.search(r"[xXzZ]", digits):
            return None  # unknown bits — not a concrete vector value
        try:
            val = int(digits, base)
        except ValueError:
            return None
        return -val if neg else val
    t = t.replace("_", "")
    try:
        if t[:2].lower() == "0x":
            val = int(t, 16)
        elif t[:2].lower() == "0b":
            val = int(t, 2)
        else:
            val = int(t, 10)
    except ValueError:
        return None
    return -val if neg else val


_BARE_HEX_RE = re.compile(r"[0-9a-fA-F][0-9a-fA-F_]*$")


def _cell_value(cell: str, base: str = "dec"):
    """A table cell -> int (the single distinct literal), 'DONTCARE', or None.

    A cell with prose AND one literal ("Updated (0x02)") yields that literal.
    A cell with two DIFFERENT literals is ambiguous -> None (drop).

    `base` is the COLUMN base inferred by `_column_base`: 'hex' reads a bare
    all-hex-digit token base-16 (so `FFFFFFFE`/`A1B2C3D4`/`00000000` are
    consistent); 'bin' reads a bare 0/1 token base-2 (so a `0011`/`1100` BCD
    column is 3/12, not decimal 11/1100). Cells that already self-declare a base
    (0x.., 0b.., N'h..) are untouched."""
    s = cell.strip()
    if not s or _DONTCARE.match(s):
        return "DONTCARE"
    if not re.search(r"0[xXbB]|'", s):
        if base == "hex" and _BARE_HEX_RE.fullmatch(s):
            return _lit_to_int("0x" + s.replace("_", ""))
        if base == "bin" and re.fullmatch(r"[01][01_]*", s):
            return _lit_to_int("0b" + s.replace("_", ""))
    vals = []
    for m in _LIT_RE.finditer(s):
        v = _lit_to_int(m.group(0))
        if v is not None:
            vals.append(v)
    distinct = set(vals)
    if len(distinct) == 1:
        return vals[0]
    return None


def _column_base(cells: List[str], width: int) -> str:
    """Infer a table column's numeric base from its cells -> 'hex'|'bin'|'dec'.

    HEX  : a bare token carries an a-f/A-F digit (e.g. `A1B2C3D4`).
    BIN  : every bare cell is 0/1-only AND looks like fixed-width binary — either
           each cell has exactly `width` digits, or some cell would OVERFLOW the
           port read as decimal while ALL fit read as binary (`1000` on a 4-bit
           port is binary 8, never decimal 1000).
    DEC  : otherwise (plain decimal).
    Self-declared (0x../0b../N'h..) and prose cells are ignored for the vote."""
    bare: List[str] = []
    has_letter = False
    for c in cells:
        s = c.strip()
        if not s or _DONTCARE.match(s):
            continue
        if re.search(r"0[xXbB]|'", s):
            continue  # self-declared base — parsed directly, no hint needed
        if not _BARE_HEX_RE.fullmatch(s):
            continue  # prose / non-numeric — let _LIT_RE handle it
        bare.append(s.replace("_", ""))
        if re.search(r"[a-fA-F]", s):
            has_letter = True
    if not bare:
        return "dec"
    if has_letter:
        return "hex"
    if width and width > 1 and all(re.fullmatch(r"[01]+", s) for s in bare):
        cap = (1 << width) - 1
        looks_bin = (all(len(s) == width for s in bare)
                     or any(int(s, 10) > cap for s in bare))
        if looks_bin and all(int(s, 2) <= cap for s in bare):
            return "bin"
    return "dec"


# ---------------------------------------------------------------------------
# RTL port model
# ---------------------------------------------------------------------------
@dataclass
class PortModel:
    name: str
    width: int            # parsed literal width; 1 = scalar OR unknown/param
    wide_unknown: bool    # range was a non-literal expression (param) -> wide


def _strip_comments(t: str) -> str:
    """Drop // line and /* */ block comments so a phrase like `module name` in a
    header comment cannot be mis-read as the module declaration (it would make
    the TB instantiate a non-existent module and SKIP on a compile error)."""
    t = re.sub(r"/\*.*?\*/", "", t, flags=re.S)
    t = re.sub(r"//[^\n]*", "", t)
    return t


def _build_port_models(rtl_text: str, top: Optional[str]
                       ) -> Tuple[str, List[PortModel], List[PortModel]]:
    """(module_name, inputs, outputs).  wide_unknown flags a parameterized range
    so the comparison width is not truncated below the value's own bit-length."""
    rtl_text = _strip_comments(rtl_text)
    name, ports = _SRC.parse_rtl_ports(rtl_text, top)
    ins: List[PortModel] = []
    outs: List[PortModel] = []
    for p in ports:
        # A port whose declared range is a PARAMETER EXPRESSION (`[W-1:0]`,
        # `[SIZE:0]`) is wide_unknown whether or not a default value happened to
        # resolve it to a literal width: the example may assume non-default
        # parameters (we instantiate with defaults), and a width-1 literal parse
        # would also truncate a wide value to 1 bit. Detect it structurally for
        # EVERY port — not only the p.width==1 unresolved case — so the verdict
        # SKIPs (advisory) rather than false-PASS a parameterized module against
        # a default-parameter run.
        m = re.search(
            r"(input|output|inout)\b[^;()]*?(\[[^\]]*\])\s*"
            r"(?:reg|wire|logic|signed|unsigned|\s)*\b" + re.escape(p.name)
            + r"\b", rtl_text)
        wide = bool(m and not _SRC._LITERAL_RANGE.fullmatch(m.group(2).strip()))
        pm = PortModel(p.name, max(1, p.width), wide)
        if p.direction == "input":
            ins.append(pm)
        elif p.direction == "output":
            outs.append(pm)
    return name, ins, outs


# ---------------------------------------------------------------------------
# A runnable vector
# ---------------------------------------------------------------------------
@dataclass
class Vector:
    inputs: Dict[str, int]       # port -> driven value
    expected: Dict[str, int]     # port -> asserted value
    label: str                   # human description for the failure line


# ---------------------------------------------------------------------------
# Extraction (a): cycle / Observed-Expected / waveform markdown|ascii TABLE
# ---------------------------------------------------------------------------
def _split_row(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_sep_row(cells: List[str]) -> bool:
    """A markdown/ascii delimiter row: every cell is dashes/colons/plus/blank."""
    return all(re.fullmatch(r"[-:=+\s]*", c) is not None for c in cells)


def _find_tables(text: str) -> List[List[List[str]]]:
    """Return contiguous pipe-delimited blocks as lists of cell-rows."""
    tables, cur = [], []
    for line in text.splitlines():
        if "|" in line and line.count("|") >= 2:
            cur.append(_split_row(line))
        else:
            if len(cur) >= 2:
                tables.append(cur)
            cur = []
    if len(cur) >= 2:
        tables.append(cur)
    return tables


@dataclass
class _ColMap:
    cycle_col: Optional[int]
    in_cols: Dict[int, str]      # col index -> input port name
    out_cols: Dict[int, str]     # col index -> output port name (golden only)


def _header_token_port(cell: str, by_norm: Dict[str, str]) -> Optional[str]:
    """Map a header cell to a port whose normalized name equals one of the
    cell's word tokens (token boundary — never a substring of a longer word)."""
    for tok in re.findall(r"[A-Za-z_]\w*", cell):
        p = by_norm.get(_norm(tok))
        if p is not None:
            return p
    return None


def _map_columns(header: List[str],
                 in_by_norm: Dict[str, str],
                 out_by_norm: Dict[str, str]) -> Optional[_ColMap]:
    """Classify each header column. Returns None (SKIP) on an ambiguous mapping
    (the same output port mapped by two unmarked columns, etc.)."""
    cycle_col: Optional[int] = None
    in_cols: Dict[int, str] = {}
    # candidate output columns: port -> list of (col, is_expected, is_observed)
    out_cand: Dict[str, List[Tuple[int, bool, bool]]] = {}
    for i, cell in enumerate(header):
        ip = _header_token_port(cell, in_by_norm)
        op = _header_token_port(cell, out_by_norm)
        if ip is not None and op is None:
            if _is_clk(ip):
                # A column that maps to the clock port is a clock-EDGE indicator
                # ("Rising"/"Falling"/"posedge"), not a driven data column — the
                # TB supplies the clock. Ignore it (and let it serve as the
                # implicit time index).
                if cycle_col is None:
                    cycle_col = i
                continue
            if ip in in_cols.values():
                return None  # same input port mapped twice -> ambiguous
            in_cols[i] = ip
        elif op is not None:
            is_exp = bool(_EXPECTED_MARK.search(cell))
            is_obs = bool(_OBSERVED_MARK.search(cell))
            out_cand.setdefault(op, []).append((i, is_exp, is_obs))
        else:
            # not a port: maybe the cycle/time index column
            for tok in re.findall(r"[A-Za-z_]\w*", cell):
                if _CYCLE_HDR.match(tok):
                    cycle_col = i
                    break
    # Resolve each output port to ONE golden column (drop observed/actual).
    out_cols: Dict[int, str] = {}
    for port, cands in out_cand.items():
        non_obs = [c for c in cands if not c[2]]
        if not non_obs:
            continue  # every column for this port is "observed" -> drop entirely
        if len(non_obs) == 1:
            out_cols[non_obs[0][0]] = port
            continue
        marked = [c for c in non_obs if c[1]]
        if len(marked) == 1:
            out_cols[marked[0][0]] = port
        else:
            return None  # >1 unmarked golden column for one port -> ambiguous
    if not in_cols or not out_cols:
        return None
    return _ColMap(cycle_col, in_cols, out_cols)


def extract_table_vectors(text: str,
                          ins: List[PortModel],
                          outs: List[PortModel],
                          consts: Optional[Dict[str, int]] = None
                          ) -> Tuple[List[Vector], List[str]]:
    """Extract cycle/Observed-Expected table vectors. Returns (vectors, skips)
    where `skips` records why a candidate table was rejected (for the report).
    `consts` are prose-stated constant inputs that satisfy an otherwise-unlisted
    column and are driven (held) on every row. Conservative — see module
    docstring."""
    consts = consts or {}
    in_by_norm = {_norm(p.name): p.name for p in ins}
    out_by_norm = {_norm(p.name): p.name for p in outs}
    data_in_names = {p.name for p in ins
                     if not _is_clk(p.name)
                     and not _is_rst(p.name)
                     and not _is_enable(p.name)}
    skips: List[str] = []
    for tbl in _find_tables(text):
        rows = [r for r in tbl if not _is_sep_row(r)]
        if len(rows) < 2:
            continue
        header, data = rows[0], rows[1:]
        cmap = _map_columns(header, in_by_norm, out_by_norm)
        if cmap is None:
            continue
        ncol = len(header)
        # GUARD: every data-bearing module input must be a driven table column
        # OR a prose-stated constant (else the listed output may depend on an
        # unlisted input -> mis-drive).
        listed = set(cmap.in_cols.values()) | set(consts)
        missing = data_in_names - listed
        if missing:
            skips.append(f"table skipped: module input(s) {sorted(missing)} "
                         "not in the table and not a stated constant (output may "
                         "depend on them)")
            continue
        # GUARD: a cycle column, if present, must be consecutive (step 1) so we
        # can reproduce it cycle-by-cycle.
        cyc_vals: List[Optional[int]] = []
        if cmap.cycle_col is not None:
            for r in data:
                if cmap.cycle_col < len(r):
                    v = _cell_value(r[cmap.cycle_col])
                    cyc_vals.append(v if isinstance(v, int) else None)
                else:
                    cyc_vals.append(None)
            concrete = [v for v in cyc_vals if v is not None]
            if len(concrete) >= 2:
                steps = {concrete[i + 1] - concrete[i]
                         for i in range(len(concrete) - 1)}
                if steps != {1}:
                    skips.append("table skipped: cycle column is not "
                                 "consecutive (cannot reproduce intervening "
                                 "cycles)")
                    continue
        # Per-column base detection (hex / binary / decimal), width-aware so a
        # bare `0011` BCD column reads binary and a bare `A1B2C3D4` column reads
        # hex — consistently for every cell in that column.
        pwidth = {}
        for ci, pn in cmap.in_cols.items():
            pwidth[ci] = next((p.width for p in ins if p.name == pn), 1)
        for ci, pn in cmap.out_cols.items():
            pwidth[ci] = next((p.width for p in outs if p.name == pn), 1)
        col_base = {ci: _column_base([r[ci] for r in data if ci < len(r)],
                                     pwidth.get(ci, 1))
                    for ci in list(cmap.in_cols) + list(cmap.out_cols)}
        # Build vectors with hold-last input semantics (waveform convention:
        # only changed signals are re-listed each row). Stated constants are
        # held on every row (a table column for the same port still overrides).
        held: Dict[str, int] = {n: v for n, v in consts.items()
                                if n in data_in_names}
        vectors: List[Vector] = []
        bad = False
        for r in data:
            if len(r) != ncol:
                # ragged row (e.g. a stray separator we already filtered out) —
                # tolerate by padding, but if it loses a needed column, drop.
                if len(r) < ncol:
                    r = r + [""] * (ncol - len(r))
            # update held inputs
            for ci, pname in cmap.in_cols.items():
                cv = _cell_value(r[ci], col_base.get(ci, "dec")) if ci < len(r) else None
                if cv == "DONTCARE":
                    continue  # keep previous held value
                if cv is None:
                    bad = True
                    break
                held[pname] = cv
            if bad:
                break
            exp: Dict[str, int] = {}
            for ci, pname in cmap.out_cols.items():
                cv = _cell_value(r[ci], col_base.get(ci, "dec")) if ci < len(r) else None
                if cv == "DONTCARE" or cv is None:
                    continue  # nothing asserted this row for this output
                exp[pname] = cv
            if not exp:
                continue  # row asserts nothing -> nothing to check
            # require every driven data input to have a (held) value
            if not data_in_names.issubset(held.keys()):
                continue
            label = (", ".join(f"{k}={held[k]}" for k in sorted(held))
                     + " -> "
                     + ", ".join(f"{k}={exp[k]}" for k in sorted(exp)))
            vectors.append(Vector(dict(held), exp, label))
        if bad:
            skips.append("table skipped: an input cell did not parse to a "
                         "single value")
            continue
        if vectors:
            return vectors, skips
    return [], skips


# ---------------------------------------------------------------------------
# Extraction (b): worked-ARITHMETIC operator lines + (c) inline named examples
# ---------------------------------------------------------------------------
_OPS_COMMUTATIVE = {"+", "*", "&", "|", "^"}
_OP_CANON = {
    "*": "*", "×": "*", "·": "*",
    "+": "+",
    "-": "-", "−": "-", "–": "-",
    "/": "/", "÷": "/",
    "%": "%",
    "<<": "<<", ">>": ">>",
    "&": "&", "|": "|", "^": "^",
}
_OP_CLASS = "|".join(re.escape(o) for o in
                     ["<<", ">>", "*", "×", "·", "+", "-", "−", "–",
                      "/", "÷", "%", "&", "|", "^"])
# A op B = C   /   A op B => C   /   A op B -> C
_ARITH_RE = re.compile(
    r"(?P<a>[+-]?(?:\d*\s*'\s*[sS]?[bodhBODH][0-9a-fA-FxXzZ_]+|0[xX][0-9a-fA-F_]+"
    r"|0[bB][01_]+|\d[\d_]*))"
    r"\s*(?P<op>" + _OP_CLASS + r")\s*"
    r"(?P<b>[+-]?(?:\d*\s*'\s*[sS]?[bodhBODH][0-9a-fA-FxXzZ_]+|0[xX][0-9a-fA-F_]+"
    r"|0[bB][01_]+|\d[\d_]*))"
    r"\s*(?:=>|->|=|→|\bis\b|\bequals\b)\s*"
    r"(?P<c>[+-]?(?:\d*\s*'\s*[sS]?[bodhBODH][0-9a-fA-FxXzZ_]+|0[xX][0-9a-fA-F_]+"
    r"|0[bB][01_]+|\d[\d_]*))")

# division with explicit quotient + remainder
_DIVREM_RE = re.compile(
    r"(?P<a>[+-]?(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d[\d_]*))"
    r"\s*(?:/|÷|\bdivided by\b|\bdiv\b)\s*"
    r"(?P<b>[+-]?(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d[\d_]*))"
    r".*?\bquotient\b\D*?(?P<q>[+-]?(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d[\d_]*))"
    r".*?\bremainder\b\D*?(?P<r>[+-]?(?:0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d[\d_]*))",
    re.I | re.S)

# inline named example:  if a=3 (and) b=4, then sum=7  /  a=3, b=4 -> sum=7
_NAMED_ASSIGN = re.compile(
    r"([A-Za-z_]\w*)\s*=\s*"
    r"([+-]?(?:\d*\s*'\s*[sS]?[bodhBODH][0-9a-fA-FxXzZ_]+|0[xX][0-9a-fA-F_]+"
    r"|0[bB][01_]+|\d[\d_]*))")


# A single numeric literal (sub-pattern, for embedding in larger regexes).
_LIT_PAT = (r"[+-]?(?:\d*\s*'\s*[sS]?[bodhBODH][0-9a-fA-FxXzZ_]+"
            r"|0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d[\d_]*)")
# Prose verbs that pin a signal to a CONSTANT for the whole example. We require
# an explicit "fixed/constant/held/tied/set/configured" word so an ordinary
# example operand assignment ("a = 3") is NOT mistaken for a held constant.
_CONST_VERB = (r"(?:is|are|was|were|be|=|:)?\s*"
               r"(?:fixed(?:\s+(?:at|to|as))?|set\s+to|configured\s+(?:to|as)|"
               r"held\s+(?:at|to)|tied\s+(?:to|high|low)|kept\s+(?:at|constant)|"
               r"constant(?:\s+(?:at|value\s+of|of))?|hardcoded\s+to|preset\s+to|"
               r"programmed\s+to|initiali[sz]ed\s+to|driven\s+(?:to|with)|"
               r"remains?\s+(?:at|fixed\s+at))")
_STATED_CONST_RE = re.compile(
    _CONST_VERB + r"\s+(?P<val>" + _LIT_PAT + r")", re.I)


def extract_stated_constants(text: str,
                             ins: List["PortModel"]) -> Dict[str, int]:
    """Inputs the prose pins to a constant for the WHOLE example
    ('`i_cfg` is fixed at 3', 'the mode set to 2', 'enable tied high').

    The value is mapped to a port ONLY by an EXACT (normalized) port-name token
    appearing in the same sentence before the verb. No fuzzy / descriptor match —
    a wrongly-mapped constant would false-block a correct design, which is worse
    than a SKIP. Returns {port_name: value}."""
    consts: Dict[str, int] = {}
    by_norm = {_norm(p.name): p for p in ins}
    for sent in re.split(r"(?<=[.\n])", text):
        for m in _STATED_CONST_RE.finditer(sent):
            val = _lit_to_int(m.group("val"))
            if val is None:
                continue
            pre = sent[:m.start()]
            # nearest port-name token to the verb wins (handles "the KEY is ...")
            for tok in reversed(re.findall(r"[A-Za-z_]\w*", pre)):
                p = by_norm.get(_norm(tok))
                if p is not None:
                    consts.setdefault(p.name, val)
                    break
    return consts


def _data_ports(ins, outs):
    di = [p for p in ins if not _is_ctrl_input(p.name)]
    do = [p for p in outs if not _STATUS_OUTPUT.match(p.name)]
    return di, do


def _match_named_output(port_names: List[str], *keys: str) -> Optional[str]:
    for p in port_names:
        n = _norm(p)
        for k in keys:
            if k in n:
                return p
    return None


def extract_arith_vectors(text: str,
                          ins: List[PortModel],
                          outs: List[PortModel],
                          consts: Optional[Dict[str, int]] = None
                          ) -> Tuple[List[Vector], List[str], bool]:
    """Worked-arithmetic + inline named examples -> vectors.
    Returns (vectors, skips, needs_ordering_sweep). The bool requests a try-both-
    operand-orderings sweep for an unnamed, non-commutative op (so a correct
    `b-a`-ordered design is never false-blocked). `consts` are prose-stated
    constant inputs (e.g. a key / config operand) that are driven alongside the
    two arithmetic operands and DO NOT count toward the 2-operand shape."""
    consts = consts or {}
    di, do = _data_ports(ins, outs)
    # A stated-constant input is a configured operand, not one of the two
    # arithmetic operands — exclude it from the operand count so a `c = a op b`
    # design with an extra fixed config/key input still maps cleanly.
    di = [p for p in di if p.name not in consts]
    skips: List[str] = []
    needs_sweep = False
    out_names = [p.name for p in do]

    # (c) inline named example wins when the names resolve to real ports.
    in_by_norm = {_norm(p.name): p.name for p in ins}
    out_by_norm = {_norm(p.name): p.name for p in outs}
    # Treat a sentence as a named example only when it carries a clear
    # '... -> ...' / '... then ...' separator so we know which side is output.
    for sent in re.split(r"[\n;.]", text):
        if not re.search(r"->|=>|→|\bthen\b|\bresult\b|\boutput\b", sent, re.I):
            continue
        parts = re.split(r"->|=>|→|\bthen\b", sent, maxsplit=1, flags=re.I)
        if len(parts) != 2:
            continue
        lhs, rhs = parts
        in_vals: Dict[str, int] = {}
        for nm, raw in _NAMED_ASSIGN.findall(lhs):
            p = in_by_norm.get(_norm(nm))
            v = _lit_to_int(raw)
            if p is not None and v is not None:
                in_vals[p] = v
        out_vals: Dict[str, int] = {}
        for nm, raw in _NAMED_ASSIGN.findall(rhs):
            p = out_by_norm.get(_norm(nm))
            v = _lit_to_int(raw)
            if p is not None and v is not None:
                out_vals[p] = v
        if in_vals and out_vals:
            for k, v in consts.items():
                in_vals.setdefault(k, v)
            label = (", ".join(f"{k}={in_vals[k]}" for k in sorted(in_vals))
                     + " -> "
                     + ", ".join(f"{k}={out_vals[k]}" for k in sorted(out_vals)))
            return [Vector(in_vals, out_vals, label)], skips, False

    # (b) division with quotient + remainder
    mdr = _DIVREM_RE.search(text)
    if mdr and len(di) == 2:
        a = _lit_to_int(mdr.group("a")); b = _lit_to_int(mdr.group("b"))
        q = _lit_to_int(mdr.group("q")); r = _lit_to_int(mdr.group("r"))
        qp = _match_named_output(out_names, "quot", "quotient")
        rp = _match_named_output(out_names, "remainder", "rem", "mod")
        if None not in (a, b, q, r) and qp and rp and qp != rp:
            # dividend/divisor order: map by name if possible, else declaration.
            dvd = _match_named_output([p.name for p in di],
                                      "dividend", "num", "a")
            dvs = _match_named_output([p.name for p in di],
                                      "divisor", "den", "b")
            if dvd and dvs and dvd != dvs:
                in_vals = {dvd: a, dvs: b}
            else:
                in_vals = {di[0].name: a, di[1].name: b}
                needs_sweep = True
            for k, v in consts.items():
                in_vals.setdefault(k, v)
            label = f"{a} / {b} -> quotient {q}, remainder {r}"
            return ([Vector(in_vals, {qp: q, rp: r}, label)],
                    skips, needs_sweep)
        skips.append("division quotient/remainder example present but the RTL "
                     "does not expose 2 data inputs + named quotient & remainder "
                     "outputs -> skipped")

    # (b) generic binary  A op B = C
    for m in _ARITH_RE.finditer(text):
        a = _lit_to_int(m.group("a")); b = _lit_to_int(m.group("b"))
        c = _lit_to_int(m.group("c"))
        op = _OP_CANON.get(m.group("op"))
        if None in (a, b, c) or op is None:
            continue
        if len(di) != 2 or len(do) != 1:
            skips.append(f"worked example `{m.group(0).strip()}` present but the "
                         f"RTL exposes {len(di)} data input(s) / {len(do)} data "
                         "output(s), not 2->1 -> skipped (ambiguous mapping)")
            continue
        in_vals = {di[0].name: a, di[1].name: b}
        for k, v in consts.items():
            in_vals.setdefault(k, v)
        if op not in _OPS_COMMUTATIVE:
            needs_sweep = True
        label = f"{a} {m.group('op')} {b} -> {do[0].name}={c}"
        return [Vector(in_vals, {do[0].name: c}, label)], skips, needs_sweep

    return [], skips, False


# ---------------------------------------------------------------------------
# Testbench generation
# ---------------------------------------------------------------------------
def _cmp_width(pm: PortModel, value: int) -> int:
    """Comparison width: never truncate below the value's own bit-length (so a
    parameterized port is not masked to 1 bit)."""
    vbits = max(1, abs(value).bit_length())
    if pm.wide_unknown:
        return max(pm.width, vbits)
    return max(pm.width, vbits, 1)


def _reg_width(pm: PortModel, value: int) -> int:
    return _cmp_width(pm, value)


def _detect_reset_polarity(rtl_text: str, rst: str) -> Optional[bool]:
    """True=active-low, False=active-high, None=ambiguous (sweep both)."""
    low = re.search(r"negedge\s+" + re.escape(rst) + r"\b", rtl_text)
    high = re.search(r"posedge\s+" + re.escape(rst) + r"\b", rtl_text)
    if low and not high:
        return True
    if high and not low:
        return False
    # name hint: trailing _n / n -> active-low
    if re.search(r"(_n$|n$|^n)", rst.lower()) and not high:
        return True
    return None


def _check_block(out_pm: Dict[str, PortModel], exp: Dict[str, int],
                 vi: int, label: str, indent: str) -> List[str]:
    out: List[str] = []
    safe_label = label.replace('"', "'")
    for port, val in exp.items():
        pm = out_pm[port]
        w = _cmp_width(pm, val)
        masked = val & ((1 << w) - 1)
        out.append(f"{indent}if ({port} !== {w}'d{masked}) begin")
        out.append(
            f'{indent}  $display("EXAMPLE_FAIL vec {vi} [{safe_label}] port '
            f'{port}: expected {masked} (0x%0h) got %0d (0x%0h)", '
            f"{w}'d{masked}, {port}, {port});")
        out.append(f"{indent}  __errors = __errors + 1;")
        out.append(f"{indent}end")
    return out


def build_comb_tb(top: str, vectors: List[Vector],
                  in_pm: Dict[str, PortModel],
                  out_pm: Dict[str, PortModel],
                  all_inputs: List[PortModel]) -> str:
    driven_w: Dict[str, int] = {}
    for v in vectors:
        for nm, val in v.inputs.items():
            driven_w[nm] = max(driven_w.get(nm, 1), _reg_width(in_pm[nm], val))
    checked = sorted({p for v in vectors for p in v.expected})
    L = ["`timescale 1ns/1ps", "module tb_prompt_example_selftest;",
         "  integer __errors = 0;"]
    # declare a reg for EVERY module input (drive defaults so nothing floats)
    for p in all_inputs:
        w = driven_w.get(p.name, max(1, p.width))
        rng = "" if w <= 1 else f"[{w-1}:0] "
        L.append(f"  reg {rng}{p.name};")
    for nm in checked:
        pm = out_pm[nm]
        w = max(pm.width, max((_cmp_width(pm, v.expected.get(nm, 0))
                               for v in vectors if nm in v.expected), default=1))
        rng = "" if w <= 1 else f"[{w-1}:0] "
        L.append(f"  wire {rng}{nm};")
    conns = [f".{p.name}({p.name})" for p in all_inputs] + \
            [f".{nm}({nm})" for nm in checked]
    L.append(f"  {top} dut({', '.join(conns)});")
    L.append("  initial begin")
    for vi, v in enumerate(vectors):
        for p in all_inputs:
            if p.name in v.inputs:
                L.append(f"    {p.name} = {v.inputs[p.name]};")
            elif _is_enable(p.name):
                L.append(f"    {p.name} = 1;")
            else:
                L.append(f"    {p.name} = 0;")
        L.append("    #2;")
        L.extend(_check_block(out_pm, v.expected, vi, v.label, "    "))
    L.append("    if (__errors != 0) $display("
             '"PROMPT_EXAMPLE_SELFTEST=FAIL errors=%0d", __errors);')
    L.append('    else $display("PROMPT_EXAMPLE_SELFTEST=PASS");')
    L.append("    $finish;")
    L.append("  end")
    L.append("endmodule")
    return "\n".join(L) + "\n"


def build_clocked_tb(top: str, vectors: List[Vector],
                     in_pm: Dict[str, PortModel],
                     out_pm: Dict[str, PortModel],
                     all_inputs: List[PortModel],
                     clk: str, rst: Optional[str],
                     rst_active_low: Optional[bool],
                     sample_after_edge: bool) -> str:
    driven_w: Dict[str, int] = {}
    for v in vectors:
        for nm, val in v.inputs.items():
            driven_w[nm] = max(driven_w.get(nm, 1), _reg_width(in_pm[nm], val))
    checked = sorted({p for v in vectors for p in v.expected})
    L = ["`timescale 1ns/1ps", "module tb_prompt_example_selftest;",
         "  integer __errors = 0;", f"  reg {clk} = 0;"]
    for p in all_inputs:
        if p.name == clk:
            continue
        w = driven_w.get(p.name, max(1, p.width))
        rng = "" if w <= 1 else f"[{w-1}:0] "
        L.append(f"  reg {rng}{p.name};")
    for nm in checked:
        pm = out_pm[nm]
        w = max(pm.width, max((_cmp_width(pm, v.expected.get(nm, 0))
                               for v in vectors if nm in v.expected), default=1))
        rng = "" if w <= 1 else f"[{w-1}:0] "
        L.append(f"  wire {rng}{nm};")
    conns = [f".{p.name}({p.name})" for p in all_inputs] + \
            [f".{nm}({nm})" for nm in checked]
    L.append(f"  {top} dut({', '.join(conns)});")
    L.append(f"  always #5 {clk} = ~{clk};")
    L.append("  initial begin")
    # init: reset asserted, data 0, enables asserted
    for p in all_inputs:
        if p.name == clk:
            continue
        if rst is not None and p.name == rst:
            assert_val = 0 if rst_active_low else 1
            L.append(f"    {p.name} = {assert_val};")
        elif _is_enable(p.name):
            L.append(f"    {p.name} = 1;")
        else:
            L.append(f"    {p.name} = 0;")
    L.append(f"    @(negedge {clk}); @(negedge {clk});")
    if rst is not None:
        deassert = 1 if rst_active_low else 0
        L.append(f"    {rst} = {deassert};")
        L.append(f"    @(negedge {clk});")
    for vi, v in enumerate(vectors):
        L.append(f"    @(negedge {clk});")
        for nm, val in v.inputs.items():
            L.append(f"    {nm} = {val};")
        for p in all_inputs:
            if _is_enable(p.name) and p.name not in v.inputs:
                L.append(f"    {p.name} = 1;")
        if sample_after_edge:
            L.append(f"    @(posedge {clk}); #1;")
            L.extend(_check_block(out_pm, v.expected, vi, v.label, "    "))
        else:
            L.append("    #1;")
            L.extend(_check_block(out_pm, v.expected, vi, v.label, "    "))
            L.append(f"    @(posedge {clk});")
    L.append("    if (__errors != 0) $display("
             '"PROMPT_EXAMPLE_SELFTEST=FAIL errors=%0d", __errors);')
    L.append('    else $display("PROMPT_EXAMPLE_SELFTEST=PASS");')
    L.append("    $finish;")
    L.append("  end")
    L.append("  initial begin #100000; "
             '$display("PROMPT_EXAMPLE_SELFTEST=TIMEOUT"); $finish; end')
    L.append("endmodule")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------------------
# Compile + run
# ---------------------------------------------------------------------------
def _compile_run(tb_text: str, rtl_text: str, rtl_suffix: str
                 ) -> Tuple[str, str]:
    """('pass'|'fail'|'nocompile'|'timeout', log)."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        tb = tdp / "tb_prompt_example_selftest.v"
        dut = tdp / ("dut" + (rtl_suffix or ".v"))
        out = tdp / "sim.vvp"
        tb.write_text(tb_text)
        dut.write_text(rtl_text)
        # watchdog-exempt: bounded single-file iverilog compile (elaboration/sim build); fixed budget adequate — not an open-ended EDA generator
        comp = subprocess.run(["iverilog", "-g2012", "-o", str(out),
                               str(tb), str(dut)],
                              capture_output=True, text=True)
        if comp.returncode != 0:
            return "nocompile", (comp.stdout + comp.stderr).strip()
        try:
            sim = subprocess.run(["vvp", str(out)], capture_output=True,
                                 text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return "timeout", "vvp timed out"
        log = (sim.stdout + sim.stderr).strip()
    if "PROMPT_EXAMPLE_SELFTEST=PASS" in log:
        return "pass", log
    if "PROMPT_EXAMPLE_SELFTEST=TIMEOUT" in log:
        return "timeout", log
    return "fail", log


def _parse_failures(log: str) -> List[str]:
    return [ln.strip() for ln in log.splitlines()
            if ln.strip().startswith("EXAMPLE_FAIL")]


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------
@dataclass
class SelfTestResult:
    verdict: str                       # PASS / FAIL / SKIP
    reason: str
    ran: bool = False
    vectors: int = 0
    shape: str = ""                    # table / arithmetic / none
    failures: List[str] = field(default_factory=list)
    skips: List[str] = field(default_factory=list)
    extracted: List[str] = field(default_factory=list)
    sim_log: str = ""


def run_selftest(prompt_text: str, rtl_source: str,
                 module_name: Optional[str] = None,
                 latency: Optional[int] = None,
                 warn: bool = False) -> SelfTestResult:
    """Benchmark-AGNOSTIC core. Operates only on the prompt + authored RTL."""
    top, ins, outs = _build_port_models(rtl_source, module_name)
    if not top:
        return SelfTestResult("SKIP", "no module found in the RTL", shape="none")
    if not ins or not outs:
        return SelfTestResult(
            "SKIP", "RTL has no resolvable input and output ports", shape="none")

    in_pm = {p.name: p for p in ins}
    out_pm = {p.name: p for p in outs}

    # ---- extract ----
    consts = extract_stated_constants(prompt_text, ins)
    shape = "none"
    vectors, t_skips = extract_table_vectors(prompt_text, ins, outs, consts)
    a_skips: List[str] = []
    needs_sweep = False
    if vectors:
        shape = "table"
    else:
        vectors, a_skips, needs_sweep = extract_arith_vectors(
            prompt_text, ins, outs, consts)
        if vectors:
            shape = "arithmetic"
    skips = t_skips + a_skips

    if not vectors:
        return SelfTestResult(
            "SKIP",
            "no cleanly-mappable worked example, cycle table, or arithmetic "
            "vector in the prompt — nothing to execute",
            shape="none", skips=skips)

    # GUARD (PARAMETER MISMATCH): a cycle table / example is authored for a
    # SPECIFIC parameterization, and the table's stated widths encode it. We
    # instantiate the module with its DEFAULT parameters, so if any mapped port
    # has a parameter-derived (non-literal) width the example may have been
    # generated for different parameters — running with defaults would
    # false-block a correct design. SKIP (advisory) rather than risk it.
    mapped = {p for v in vectors for p in v.inputs} | \
             {p for v in vectors for p in v.expected}
    param_ports = sorted(
        n for n in mapped
        if (in_pm.get(n) or out_pm.get(n)) is not None
        and (in_pm.get(n) or out_pm.get(n)).wide_unknown)
    if param_ports:
        return SelfTestResult(
            "SKIP",
            f"example maps to parameter-width port(s) {param_ports} — the "
            "example may assume non-default parameters; running with defaults "
            "could false-block, so SKIP (advisory)",
            shape=shape, vectors=len(vectors), skips=skips,
            extracted=[v.label for v in vectors])

    extracted = [v.label for v in vectors]

    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        return SelfTestResult(
            "SKIP", f"iverilog/vvp not on PATH ({len(vectors)} vector(s) were "
            "extractable)", shape=shape, vectors=len(vectors),
            skips=skips, extracted=extracted)

    clk = next((p.name for p in ins if _is_clk(p.name)), None)
    rst = next((p.name for p in ins if _is_rst(p.name)), None)
    rtl_suffix = ".sv" if re.search(r"\blogic\b|always_ff|always_comb|::",
                                    rtl_source) else ".v"

    # ---- run ----
    if clk is None:
        # combinational
        if shape == "arithmetic" and needs_sweep:
            # unnamed non-commutative operands: try both orderings, PASS if
            # either (never false-block a correct b-op-a-ordered design).
            variants = [vectors, _swap_two_inputs(vectors)]
        else:
            variants = [vectors]
        return _run_variants(
            [("comb", build_comb_tb(top, vv, in_pm, out_pm, ins))
             for vv in variants],
            rtl_source, rtl_suffix, shape, len(vectors), extracted, skips, warn)

    # clocked
    # GUARD (UNTIMED TRIGGER): a single arithmetic / named example gives no
    # per-cycle timing. If the CLOCKED design has a start/valid/load handshake
    # whose pulse timing we cannot infer, driving it statically would never fire
    # the operation -> false-block. SKIP. (A cycle TABLE lists the trigger per
    # cycle, so it is exempt from this guard.)
    if shape == "arithmetic":
        trig = next((p.name for p in ins if _is_trigger(p.name)), None)
        if trig is not None:
            return SelfTestResult(
                "SKIP", f"worked-arithmetic example on a CLOCKED design with a "
                f"handshake input `{trig}` whose pulse timing is not stated — "
                "cannot reproduce the protocol -> skip", shape=shape,
                vectors=len(vectors), skips=skips, extracted=extracted)
    if shape == "arithmetic" and latency is None:
        m = re.search(r"latency\s+(?:of|is|=|:)\s*(\d+)|(\d+)[- ]cycle\s+latency|"
                      r"after\s+(\d+)\s+(?:clock\s+)?cycles|"
                      r"(\d+)\s+(?:clock\s+)?cycles?\s+after|"
                      r"total\s+latency\s*(?:=|is|of|:)\s*(\d+)",
                      prompt_text, re.I)
        if m:
            latency = int(next(g for g in m.groups() if g))
    if shape == "arithmetic" and latency is None:
        return SelfTestResult(
            "SKIP", "worked-arithmetic example on a CLOCKED design with no "
            "stated latency — cannot know when to sample (use --latency) -> skip",
            shape=shape, vectors=len(vectors), skips=skips, extracted=extracted)

    pol = _detect_reset_polarity(rtl_source, rst) if rst else None
    polarities = [True, False] if (rst and pol is None) else [pol]
    if shape == "arithmetic":
        lat_conventions = [latency]
    else:
        lat_conventions = [True, False]  # sample_after_edge True(L1)/False(L0)

    tbs: List[Tuple[str, str]] = []
    for p in polarities:
        for lat in lat_conventions:
            if shape == "arithmetic":
                vv = _hold_arith_for_latency(vectors, lat)
                sample = True
                tb = build_clocked_tb(top, vv, in_pm, out_pm, ins, clk, rst,
                                      p, True)
                tbs.append((f"pol={p},lat={lat}", tb))
            else:
                tb = build_clocked_tb(top, vectors, in_pm, out_pm, ins, clk,
                                      rst, p, lat)
                tbs.append((f"pol={p},sample_after_edge={lat}", tb))
    return _run_variants(tbs, rtl_source, rtl_suffix, shape, len(vectors),
                         extracted, skips, warn)


def _swap_two_inputs(vectors: List[Vector]) -> List[Vector]:
    out = []
    for v in vectors:
        keys = list(v.inputs.keys())
        if len(keys) == 2:
            ni = {keys[0]: v.inputs[keys[1]], keys[1]: v.inputs[keys[0]]}
        else:
            ni = dict(v.inputs)
        out.append(Vector(ni, dict(v.expected), v.label + " (swapped)"))
    return out


def _hold_arith_for_latency(vectors: List[Vector], latency: int) -> List[Vector]:
    """Repeat the single arithmetic vector `latency-1` extra hold cycles so the
    output is sampled `latency` edges after the operands are applied (inputs are
    held; intermediate rows assert nothing)."""
    if not vectors:
        return vectors
    v = vectors[0]
    n = max(1, latency)
    rows = [Vector(dict(v.inputs), {}, v.label + f" (hold {i})")
            for i in range(n - 1)]
    rows.append(Vector(dict(v.inputs), dict(v.expected), v.label))
    return rows


def _run_variants(tbs: List[Tuple[str, str]], rtl_text: str, rtl_suffix: str,
                  shape: str, nvec: int, extracted: List[str],
                  skips: List[str], warn: bool) -> SelfTestResult:
    ran = False
    last_fail_log = ""
    nocompile_log = ""
    for tag, tb in tbs:
        status, log = _compile_run(tb, rtl_text, rtl_suffix)
        if status == "pass":
            return SelfTestResult(
                "PASS", f"all {nvec} prompt example vector(s) reproduce in the "
                f"RTL ({shape}; convention {tag})", ran=True, vectors=nvec,
                shape=shape, extracted=extracted, skips=skips, sim_log=log)
        if status == "nocompile":
            nocompile_log = log
            continue
        if status == "timeout":
            last_fail_log = log
            ran = True
            continue
        # fail
        ran = True
        last_fail_log = log
    if not ran:
        # never simulated — only compile failures. Interface mismatch could be a
        # TB-wiring artifact; per the HARD rule, SKIP rather than false-block.
        return SelfTestResult(
            "SKIP", "the example self-test TB did not compile against the RTL "
            "(stated example ports/widths do not connect) — advisory, not a "
            "block", ran=False, vectors=nvec, shape=shape, extracted=extracted,
            skips=skips, sim_log=nocompile_log)
    verdict = "FAIL" if not warn else "PASS"
    return SelfTestResult(
        verdict, f"at least one prompt example vector mismatched the RTL under "
        f"every attempted convention ({shape}) — functionally-wrong RTL",
        ran=True, vectors=nvec, shape=shape,
        failures=_parse_failures(last_fail_log), extracted=extracted,
        skips=skips, sim_log=last_fail_log)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run the prompt's own worked examples / cycle tables / "
                    "arithmetic as a blind iverilog self-test against the RTL.")
    ap.add_argument("--prompt", required=True,
                    help="prompt text file (the ONLY source of example vectors)")
    ap.add_argument("--rtl", required=True, help="authored RTL under test")
    ap.add_argument("--top", default=None,
                    help="top module name (default: first module in the RTL)")
    ap.add_argument("--latency", type=int, default=None,
                    help="cycles from operands to result for a CLOCKED "
                         "arithmetic example (else auto-detected or SKIP)")
    ap.add_argument("--warn", action="store_true",
                    help="WARN-only: report a mismatch but exit 0")
    ap.add_argument("--json", default=None, help="write the result JSON here")
    args = ap.parse_args(argv)

    prompt = Path(args.prompt)
    rtl = Path(args.rtl)
    if not prompt.is_file():
        print(f"[prompt_example_selftest] ERROR: prompt not found: {prompt}",
              file=sys.stderr)
        return 2
    if not rtl.is_file():
        print(f"[prompt_example_selftest] ERROR: rtl not found: {rtl}",
              file=sys.stderr)
        return 2

    res = run_selftest(prompt.read_text(errors="replace"),
                       rtl.read_text(errors="replace"),
                       args.top, args.latency, args.warn)

    if args.json:
        try:
            Path(args.json).write_text(json.dumps(asdict(res), indent=2))
        except OSError as e:
            print(f"[prompt_example_selftest] WARN: could not write json: {e}",
                  file=sys.stderr)

    print(f"[prompt_example_selftest] {res.verdict}: {res.reason}")
    if res.extracted:
        print(f"[prompt_example_selftest] extracted {res.vectors} "
              f"vector(s) ({res.shape}):")
        for lab in res.extracted[:12]:
            print(f"    | {lab}")
    for f in res.failures[:12]:
        print(f"    ! {f}")
    for s in res.skips[:6]:
        print(f"    ~ {s}")

    return 1 if res.verdict == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
