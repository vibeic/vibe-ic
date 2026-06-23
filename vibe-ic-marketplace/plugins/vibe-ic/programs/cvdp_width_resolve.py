#!/usr/bin/env python3
"""cvdp_width_resolve.py — SHARED parameterized-width reader for the CVDP layer.

WHY (owner directive 2026-06-23): the dominant CVDP EXTRACTION_GAP types are ports
whose WIDTH is stated as a PARAMETER EXPRESSION the literal `[\\d+:\\d+]` reader
cannot resolve:

  * param_expression_width  — `[N-1:0]`, `[M-2:0]`, `[N*IN_WIDTH-1:0]`,
                              `[$clog2(DEPTH)-1:0]`, `[DATA_WIDTH-1:0]`
  * range_before_name       — `[1:0] resp_o` (literal range PRECEDES the name)
  * param_override_width    — a width stated as `NUM_INPUTS * C_AXIS_DATA_WIDTH`
                              with the parameter defaults declared in a `#(...)`
                              block / prose "Default: 32" / a parameter table.

The width IS in the prompt (the harness binds the port), so a SKIP is a missed
fact, not a §3.9 spec-absent. This module reads those forms WITHOUT reading any
golden RTL body: it parses

  (1) the PARAMETER TABLE of defaults — from the partial module header stub the
      submitter completes (a `module M #( parameter N = 8, ... )` / `parameter
      DATA_WIDTH = 8` line that is part of the PROMPT, never the empty
      output.context skeleton), from prose ("default value is `32`" / "Default:
      32" / "default value of 8 bits"), and from a `| NAME | ... | <default> |`
      markdown parameter table; and

  (2) the SYMBOLIC WIDTH of a port — the `[hi:lo]` span tied to the port name (in
      either declaration order), kept as a STRING expression PLUS a resolved
      integer DEFAULT obtained by safely evaluating the expression against the
      parameter table.

§4.05 NO-CHEAT (binding):
  * A width is resolved to an integer default ONLY when every identifier in the
    span has a derivable default in the parameter table. If ANY identifier is
    unbound (no stated default and the harness does not pin it), `resolve()`
    returns None — the caller keeps it a GAP and NEVER fabricates a width.
  * The expression evaluator accepts only `+ - * / **`, parentheses, integer
    literals, the parameter identifiers, and `$clog2(...)` — never arbitrary
    Python. `$clog2(x)` is the SystemVerilog ceil-log2 of a positive integer.
  * No golden RTL body is ever read. The `parameter NAME = N` line is the partial
    module header in the PROMPT (submitter-visible); in CVDP v1.1.0 the
    output.context skeleton is empty, so there is nothing to leak.

chip-AGNOSTIC: every regex keys on the universal Verilog parameter / range shape,
never on a design name, a problem id, or a SKU literal.

API
    param_defaults(prompt, tb="") -> Dict[str, int]
    symbolic_width(prompt, name, params) -> Optional[Tuple[str, int]]
        # (symbolic_expr like "N-1:0" or "DATA_WIDTH-1:0", resolved_default_int)
    eval_width_expr(expr, params) -> Optional[int]
"""
from __future__ import annotations

import math
import re
from typing import Dict, Optional, Tuple

# An identifier token (a Verilog parameter name). Used to decide whether a `[..]`
# span is a literal range or a parameter expression, and to harvest the names a
# width expression depends on.
_IDENT = re.compile(r"[A-Za-z_]\w*")

# Tokens that appear inside a width expression but are NOT parameter identifiers we
# must resolve from the table — `clog2` is the SV system function we evaluate.
_EXPR_FUNCS = {"clog2"}


# --------------------------------------------------------------------------- #
# (1) parameter-default table
# --------------------------------------------------------------------------- #
# `parameter [type] NAME = <int>` — the partial module header stub in the PROMPT.
# Accepts an optional `integer`/`int`/`logic`/width-prefix and a trailing comma.
_CODE_PARAM_RE = re.compile(
    r"\bparameter\b\s*(?:integer|int|logic|reg|signed|unsigned|\[[^\]]*\]|\s)*?"
    r"([A-Za-z_]\w*)\s*=\s*(\d+|0[xX][0-9A-Fa-f]+)")
# `localparam NAME = <int>` — a derived constant, equally usable as a default.
_LOCALPARAM_RE = re.compile(
    r"\blocalparam\b\s*(?:integer|int|logic|reg|signed|unsigned|\[[^\]]*\]|\s)*?"
    r"([A-Za-z_]\w*)\s*=\s*(\d+|0[xX][0-9A-Fa-f]+)")
# `parameter/localparam NAME = <EXPRESSION>` where the RHS is a DERIVED expression
# over OTHER params (a ternary `(A>B)?A:B`, an arithmetic `A*B`, a `$clog2(D)`),
# not a bare literal. Captured up to the line-terminating comma / comment / newline.
_DERIVED_PARAM_RE = re.compile(
    r"\b(?:local)?parameter\b\s*(?:integer|int|logic|reg|signed|unsigned|\[[^\]]*\]|\s)*?"
    r"([A-Za-z_]\w*)\s*=\s*([^,\n/]+)")
# prose: "`NAME` ... default value is `32`" / "default value of 8 bits".
_PROSE_DEFAULT_RE = re.compile(
    r"`?([A-Z][A-Z0-9_]*)`?[^\n]{0,80}?\bdefault\s+value\s+(?:is|of)\b[^\n]{0,20}?"
    r"`?(\d+)`?", re.I)
# prose / list: "`NAME` (Default: 32)" or "- `NAME` (Default 32)".
_PAREN_DEFAULT_RE = re.compile(
    r"`?([A-Z][A-Z0-9_]*)`?[^\n]{0,40}?\(\s*Default\s*[:=]?\s*(\d+)\s*\)", re.I)
# a markdown parameter table row: | `NAME` | ... | <default-int> |  (default cell).
_PARAM_TABLE_ROW = re.compile(
    r"^\s*\|\s*`?([A-Za-z_]\w*)`?\s*\|.*?\|\s*`?(\d+|0[xX][0-9A-Fa-f]+)`?\s*\|?\s*$",
    re.M)


def _as_int(tok: str) -> int:
    return int(tok, 16) if tok.lower().startswith("0x") else int(tok)


def param_defaults(prompt: str, tb: str = "") -> Dict[str, int]:
    """The parameter -> default-int table, harvested from every submitter-visible
    source: the partial `module #(parameter ...)` header / a `parameter NAME = N`
    line in the prompt, prose "default value is N" / "(Default: N)", and a
    markdown parameter table's default column. NEVER reads a golden RTL body.

    A later, more-specific source does not overwrite an earlier code-declared
    default (the code `parameter NAME = N` is authoritative); first-wins per name.
    """
    out: Dict[str, int] = {}

    def _add(name: str, tok: str):
        if name and name not in out:
            try:
                out[name] = _as_int(tok)
            except ValueError:
                pass

    # code `parameter NAME = N` / `localparam NAME = N` (most authoritative).
    for m in _CODE_PARAM_RE.finditer(prompt):
        _add(m.group(1), m.group(2))
    for m in _LOCALPARAM_RE.finditer(prompt):
        _add(m.group(1), m.group(2))
    # DERIVED params: `parameter NAME = (A>B)?A:B` / `A*B` / `$clog2(D)`. Resolve
    # over the literal params already in `out` (iterate to a fixed point so a
    # chain of derivations settles). §4.05: only added when the expression fully
    # resolves to an int from KNOWN params — never a fabricated default.
    derived = [(m.group(1), m.group(2).strip()) for m in _DERIVED_PARAM_RE.finditer(prompt)
               if m.group(1) not in out]
    for _ in range(len(derived) + 1):
        progressed = False
        for nm, expr in derived:
            if nm in out:
                continue
            val = eval_width_expr(expr, out)
            if val is not None:
                out[nm] = val
                progressed = True
        if not progressed:
            break
    # a markdown parameter table only when the prompt actually frames a parameter
    # section (avoids harvesting a generic numeric table as a param default).
    if re.search(r"(?i)\bparameter", prompt):
        for m in _PARAM_TABLE_ROW.finditer(prompt):
            nm = m.group(1)
            if nm.lower() in ("parameter", "name", "description", "signal", "width"):
                continue
            _add(nm, m.group(2))
    # prose defaults.
    for m in _PROSE_DEFAULT_RE.finditer(prompt):
        _add(m.group(1), m.group(2))
    for m in _PAREN_DEFAULT_RE.finditer(prompt):
        _add(m.group(1), m.group(2))
    return out


# --------------------------------------------------------------------------- #
# (2) safe width-expression evaluator
# --------------------------------------------------------------------------- #
def eval_width_expr(expr: str, params: Dict[str, int]) -> Optional[int]:
    """Evaluate a Verilog width expression to an integer given the parameter table.
    Returns None (§4.05) when any identifier is unbound, or the expression is not a
    width form built from the vetted token set.

    Accepts ONLY integer literals, the parameter identifiers, parentheses,
    `+ - * / // **`, the relational/equality operators `> < >= <= == !=`, a Verilog
    ternary `cond ? a : b`, and `$clog2(...)`. Never evaluates arbitrary Python.
    """
    s = expr.strip()
    if not s:
        return None
    # normalize the SV ceil-log2 system function to a python-callable token.
    s = re.sub(r"\$\s*clog2", "clog2", s)
    # translate a Verilog ternary `cond ? a : b` to python `(a) if (cond) else (b)`.
    # done only when both `?` and `:` are present and balanced (a single ternary).
    s = _ternary_to_python(s)
    if s is None:
        return None
    # every identifier must be either a known param or the clog2 function.
    for tok in set(_IDENT.findall(s)):
        if tok in _EXPR_FUNCS or tok in ("if", "else"):
            continue
        if tok not in params:
            return None  # unbound identifier -> cannot resolve (keep it a gap)
    # the surviving expression must be only the allowed character class.
    if not re.fullmatch(r"[\w\s()+\-*/<>=!]+", s):
        return None

    def _clog2(x):
        x = int(x)
        if x <= 1:
            return 0
        return int(math.ceil(math.log2(x)))

    env = {"__builtins__": {}, "clog2": _clog2}
    env.update({k: int(v) for k, v in params.items()})
    try:
        val = eval(s, env, {})  # noqa: S307 — sandboxed: no builtins, vetted token set
    except Exception:
        return None
    if isinstance(val, bool):
        val = int(val)
    if not isinstance(val, (int, float)):
        return None
    iv = int(val)
    return iv if iv >= 0 else None


def _ternary_to_python(s: str) -> Optional[str]:
    """Rewrite a single Verilog ternary `cond ? a : b` to `((a) if (cond) else (b))`.
    Returns the string unchanged if there is no `?`; None if a `?` is present but the
    `?`/`:` are unbalanced (not a clean single ternary we can safely rewrite)."""
    if "?" not in s:
        return s
    # exactly one ternary, top-level: split on the first `?` and the matching `:`.
    qi = s.find("?")
    cond = s[:qi]
    rest = s[qi + 1:]
    ci = rest.find(":")
    if ci < 0:
        return None
    a = rest[:ci]
    b = rest[ci + 1:]
    # disallow nested ternaries (out of scope; keep it a gap rather than mis-parse).
    if "?" in rest:
        return None
    return f"(({a}) if ({cond}) else ({b}))"


# --------------------------------------------------------------------------- #
# (3) symbolic width of a named port (the three gap forms)
# --------------------------------------------------------------------------- #
def _span_to_symbolic(hi: str, lo: str, params: Dict[str, int]
                      ) -> Optional[Tuple[str, int]]:
    """Turn a `[hi:lo]` bound pair into (symbolic "hi:lo", resolved width int).
    Width = |eval(hi) - eval(lo)| + 1. None if either bound is unresolvable."""
    hv = eval_width_expr(hi, params)
    lv = eval_width_expr(lo, params)
    if hv is None or lv is None:
        return None
    width = abs(hv - lv) + 1
    if width <= 0:
        return None
    sym = f"{hi.strip()}:{lo.strip()}"
    return sym, width


def _has_ident_span(span_inner: str) -> bool:
    """True if a `hi:lo` inner carries a parameter identifier (so it is a param
    expression, not a pure literal `7:0`)."""
    parts = span_inner.split(":", 1)
    if len(parts) != 2:
        return False
    return bool(_IDENT.search(parts[0]) or _IDENT.search(parts[1]))


def symbolic_width(prompt: str, name: str, params: Dict[str, int]
                   ) -> Optional[Tuple[str, int, str]]:
    """Resolve a port's width when it is stated as a parameter expression, a
    range-before-name literal, or a param-override expression.

    Returns (symbolic_expr, resolved_default_int, source_tag) or None when no such
    form is tied to the name OR the expression cannot be resolved from the
    parameter table (§4.05 — never fabricate a width).

    source_tag in {param_expression_width, range_before_name, param_override_width}.
    """
    esc = re.escape(name)

    # (A) param-expression / param-override range tied to the name, EITHER order:
    #     `name [hi:lo]`  OR  `[hi:lo] name`  (the `[..]` carries an identifier).
    #     This also covers `[N*IN_WIDTH-1:0]` and `[$clog2(DEPTH)-1:0]`.
    for pat, sym_grp in (
        (rf"\b{esc}\b[^\n|]{{0,40}}?\[\s*([^\]]*?)\s*\]", 1),     # name first
        (rf"\[\s*([^\]]*?)\s*\]\s*{esc}\b", 1),                   # range first
    ):
        for m in re.finditer(pat, prompt):
            inner = m.group(sym_grp)
            if ":" not in inner or not _has_ident_span(inner):
                continue
            hi, lo = inner.split(":", 1)
            res = _span_to_symbolic(hi, lo, params)
            if res:
                sym, width = res
                tag = "param_override_width" if re.search(r"[*/]", inner) \
                    else "param_expression_width"
                return sym, width, tag

    # (B) a width cell in a markdown signal table: `| name | NUM_INPUTS * WIDTH |`.
    #     The cell is a bare expression (no brackets) — a param-override form.
    for rm in re.finditer(
            rf"^\s*\|\s*`?{esc}`?\s*\|\s*`?([^|`]+?)`?\s*[|(]", prompt, re.M):
        cell = rm.group(1).strip()
        # a pure parameter-arithmetic cell (identifiers + * / + - and digits)
        if _IDENT.search(cell) and re.fullmatch(r"[\w\s()+\-*/]+", cell) \
                and re.search(r"[*/+\-]", cell):
            val = eval_width_expr(cell, params)
            if val is not None and val > 0:
                return cell.strip(), val, "param_override_width"

    # (C) range-before-name LITERAL `[1:0] name` (already a constant, but our
    #     name-first reader missed it). Width is literal — no param needed.
    m = re.search(rf"\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*{esc}\b", prompt)
    if m:
        hi, lo = int(m.group(1)), int(m.group(2))
        return f"{hi}:{lo}", abs(hi - lo) + 1, "range_before_name"

    return None


# A port DECLARED with a scalar type but NO bracket range is explicitly 1-bit —
# the width IS stated (a 1-bit declaration), not absent. Two declaration shapes:
#   prose:   **`name`** (logic): ...        /  - `name` (wire) ...
#   header:  input  logic  name,            /  output reg name
# A `[...]` range anywhere between the type and the name disqualifies it (then it
# is a bus whose width the symbolic/literal readers handle).
def scalar_one_bit(prompt: str, name: str) -> bool:
    """True iff `name` is declared as a scalar (typed, no bracket range) — an
    explicitly-1-bit port. §4.05: a STATED 1-bit width, not a convention guess."""
    esc = re.escape(name)
    # prose: `name` immediately annotated with a bare scalar type in parens, e.g.
    # **`i_shift_direction`** (logic): ...   — NO `[` inside the parens.
    if re.search(rf"`?{esc}`?\s*\(\s*(?:logic|wire|reg|bit)\s*\)", prompt):
        return True
    # header: `input/output [dir] <type> name` with NO `[range]` before the name.
    if re.search(
            rf"\b(?:input|output|inout)\b\s+(?:wire|reg|logic|bit|signed|unsigned|\s)*"
            rf"{esc}\b\s*(?:,|;|\)|//|$)", prompt, re.M):
        # but reject if a `[..]` range precedes the name on the same declaration.
        if not re.search(
                rf"\b(?:input|output|inout)\b[^\n,;]*\[[^\]]*\][^\n,;]*\b{esc}\b",
                prompt):
            return True
    return False
