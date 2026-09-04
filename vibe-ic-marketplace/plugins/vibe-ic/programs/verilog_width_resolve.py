#!/usr/bin/env python3
"""verilog_width_resolve.py — SHARED parameterized-width reader (Verilog/SystemVerilog spec prose). chip-AGNOSTIC: any benchmark (CVDP/VerilogEval/RTLLM) or Phase-1 design doc.

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
# must resolve from the table — these are all ceil-log2 width FUNCTIONS evaluated as
# the SV `$clog2`. `clog2`/`$clog2` is the canonical SystemVerilog system function;
# `log2ceil` and `clogb2` are the common user-function synonyms RTL authors define
# (a `function integer log2ceil;` body the prompt ships) — all compute ceil(log2(x)),
# so a port sized `[log2ceil(MaxRatio_g)-1:0]` resolves exactly like `[$clog2(..)-1:0]`.
_EXPR_FUNCS = {"clog2", "log2ceil", "clogb2"}


# --------------------------------------------------------------------------- #
# (1) parameter-default table
# --------------------------------------------------------------------------- #
# `parameter [type] NAME = <int>` — the partial module header stub in the PROMPT.
# Accepts an optional `integer`/`int`/`logic`/width-prefix and a trailing comma.
# §4.05 BARE-LITERAL ONLY: the integer must be the WHOLE right-hand side — i.e.
# followed by an end-of-statement boundary (`,`, `;`, `)`, newline, or whitespace-
# then-comment), NEVER by an arithmetic operator. `parameter NBW = 2*DATA_WIDTH+1`
# previously matched the leading `2` and mis-bound NBW to 2; an EXPRESSION RHS must
# be left for `_DERIVED_PARAM_RE` + the fixed-point loop to compute (2*16+1 = 33).
# The trailing `(?=...)` lookahead asserts the boundary WITHOUT consuming it.
_RHS_END = r"(?=\s*(?:[,;)]|//|/\*|$))"
_CODE_PARAM_RE = re.compile(
    r"\bparameter\b\s*(?:integer|int|logic|reg|signed|unsigned|\[[^\]]*\]|\s)*?"
    r"([A-Za-z_]\w*)\s*=\s*(\d+|0[xX][0-9A-Fa-f]+)" + _RHS_END, re.M)
# A Verilog parameter HEADER list shares ONE `parameter` keyword across
# comma-separated items: `#(parameter ADDR_WIDTH = 8, PAGE_WIDTH = 8, TLB_SIZE = 4)`.
# _CODE_PARAM_RE only captures the FIRST item (the one right after `parameter`);
# the comma-continued siblings have no keyword of their own and were dropped, so a
# port sized by `[PAGE_WIDTH-1:0]` stayed a `param_expression_width` gap even though
# its default IS stated in the same header. This captures every `NAME = <int>` item
# inside a `#( … )` parameter block. chip-AGNOSTIC: pure Verilog-header parse.
_PARAM_HEADER_BLOCK_RE = re.compile(r"#\s*\((?P<body>[^)]*\bparameter\b[^)]*)\)", re.S)
_PARAM_HEADER_ITEM_RE = re.compile(
    r"(?:\bparameter\b\s*(?:integer|int|logic|reg|signed|unsigned|\[[^\]]*\]|\s)*?)?"
    r"\b([A-Za-z_]\w*)\s*=\s*(0[xX][0-9A-Fa-f]+|\d+)")
# `localparam NAME = <int>` — a literal-valued constant, equally usable as a
# default. §4.05 BARE-LITERAL ONLY (same boundary as `_CODE_PARAM_RE`): the integer
# must be the WHOLE RHS. `localparam NBW_PRED = 2*DATA_WIDTH + 1;` previously matched
# the leading `2`, wrongly binding NBW_PRED to 2 (a false-COMPLETE); an EXPRESSION
# RHS is now left for `_DERIVED_PARAM_RE` + the fixed-point loop (here it resolves to
# 33). A genuine `localparam X = 8;` still binds to 8 (`8` IS the whole RHS).
_LOCALPARAM_RE = re.compile(
    r"\blocalparam\b\s*(?:integer|int|logic|reg|signed|unsigned|\[[^\]]*\]|\s)*?"
    r"([A-Za-z_]\w*)\s*=\s*(\d+|0[xX][0-9A-Fa-f]+)" + _RHS_END, re.M)
# `parameter/localparam NAME = <EXPRESSION>` where the RHS is a DERIVED expression
# over OTHER params (a ternary `(A>B)?A:B`, an arithmetic `A*B`, a `$clog2(D)`),
# not a bare literal. Captured up to the line-terminating comma / comment / newline.
# NOTE: the keyword alternation is `(?:localparam|parameter)` — NOT
# `(?:local)?parameter`, which would match `localparameter`/`parameter` but MISS
# the real Verilog `localparam` keyword (a derived `localparam X = (A+$clog2(B))`
# was silently dropped, so a port sized by that derived constant stayed a gap).
_DERIVED_PARAM_RE = re.compile(
    r"\b(?:localparam|parameter)\b\s*(?:integer|int|logic|reg|signed|unsigned|\[[^\]]*\]|\s)*?"
    r"([A-Za-z_]\w*)\s*=\s*([^,\n/]+)")
# The NAME of a prose-stated default is anchored line-by-line in `param_defaults`
# (the line's LEADING param token), so these readers do NOT carry their own name
# group — that previously let a nearby lowercase word win over the real ALL-CAPS
# parameter when the name sat >40 chars before the "default" phrase. We match only
# the "default ... <int>" PHRASE here and bind the name from the line head.
#   "default value is `32`" / "default value of 8 bits" / "default value 4" /
#   "default 4" / "default is **8 bits**"  (markdown bold/code around the int is
#   tolerated — `**`/`` ` `` are presentation, not part of the value).
_PROSE_DEFAULT_PHRASE_RE = re.compile(
    # "default value: 5" / "default value is 5" / "default is 5" / "default 5".
    # After the optional "value", accept EITHER whitespace OR an immediate
    # `:`/`=` separator ("value: 5" with no space) before the int — the latter was
    # missed by the previous `\s+`-mandatory form (comparator's `WIDTH` default).
    r"\bdefault(?:\s+value)?(?:\s+|\s*[:=]\s*)(?:is\s+|of\s+|=\s*|:\s*)?[`*]{0,2}(\d+)",
    re.I)
# "(Default: 32)" / "(Default 32)" / "(Default 4, must be > 0)" — the int may be
# followed by a comma / qualifying clause before the closing paren (the original
# reader required the `)` to follow the int immediately and so missed
# "(Default 4, must be greater than 0)").
_PAREN_DEFAULT_PHRASE_RE = re.compile(
    r"\(\s*Default\s*[:=]?\s*(\d+)\b", re.I)
# A Verilog parameter token at (or near) the head of a bullet line, tolerant of
# markdown bold/code decoration and the two parameter-naming conventions in this
# dataset — ALL-CAPS (`GPIO_WIDTH`, `ROW_A`, `INPUT_WIDTH`) and a lowercase
# `p_`-prefixed name (`p_data_width`, `p_max_set_bit_count_width`):
#   "- **`GPIO_WIDTH`** ..."  /  "8. `INPUT_WIDTH`: ..."  /  "- `p_data_width`: ..."
# Used to bind a line's prose/paren default to the RIGHT parameter name.
# The token is anchored with a trailing word boundary so a mixed-case word like
# "Default" matches only the first capital letter (and is rejected by the caller's
# fullmatch guard) — it must NOT be accepted as a parameter name.
_PARAM_TOKEN = r"(?:[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*|p_[a-z0-9]+(?:_[a-z0-9]+)*)"
_LINE_HEAD_PARAM_RE = re.compile(
    r"^\s*(?:[-*]|\d+[.)])?\s*(?:\*\*\s*)?`?(" + _PARAM_TOKEN + r")\b`?")
# An inline-code parameter assignment annotated as a default:
#   "- `GPIO_WIDTH = 8` (default, configurable)."  — a real `NAME = <int>` token
#   inside backticks (NOT a `parameter`-keyword line) that the prose explicitly
#   calls a default. §4.05: a STATED default, anchored to the literal assignment.
_INLINE_CODE_DEFAULT_RE = re.compile(
    r"`\s*([A-Z][A-Z0-9_]*)\s*=\s*(\d+|0[xX][0-9A-Fa-f]+)\s*`[^\n]{0,30}?\bdefault\b",
    re.I)
# a markdown parameter table row: | `NAME` | ... | <default-int> |  (default cell).
_PARAM_TABLE_ROW = re.compile(
    r"^\s*\|\s*`?([A-Za-z_]\w*)`?\s*\|.*?\|\s*`?(\d+|0[xX][0-9A-Fa-f]+)`?\s*\|?\s*$",
    re.M)
# a STANDALONE markdown bullet/line that is itself a parameter default assignment:
#   "- **WIDTH = 32**"  /  "* `DATA_WIDTH = 16`"  — an ALL-CAPS parameter NAME set to
# an integer literal, alone on the line (optional list marker + markdown bold/code).
# Anchored to the WHOLE line so a mid-prose "x = 5" never matches; the ALL-CAPS name
# requirement keeps it to parameter-style identifiers. chip-AGNOSTIC.
_BULLET_PARAM_DEFAULT_RE = re.compile(
    r"^\s*(?:[-*]|\d+[.)])?\s*\*{0,2}`?([A-Z][A-Z0-9_]*)`?\s*=\s*"
    r"`?(\d+|0[xX][0-9A-Fa-f]+)`?\*{0,2}\s*$", re.M)
# a PROSE-DERIVED parameter — a line that NAMES an ALL-CAPS parameter at its head
# (bullet bold `- **ENCODED_DATA**:` or a table cell `| `NBW_PRED` |`) and states its
# value as an arithmetic EXPRESSION over OTHER params inside backticks, introduced by
# a derivation phrase:
#   "- **ENCODED_DATA**: Calculated as the sum of `PARITY_BIT + DATA_WIDTH + 1`"
#   "| `NBW_PRED` | ... It is defined as `2 * DATA_WIDTH + 1` ... |"
# The NAME is bound from the LINE HEAD (not the loose `\bNAME\b` that grabbed `Bit`
# of "Bit-width"); the EXPR is resolved by eval_width_expr against the known params,
# so a non-arithmetic prose value ("the minimum number of bits to index ENCODED_DATA")
# never resolves and is dropped. §4.05: the binding is added ONLY when the expression
# evaluates to an int from STATED params — never fabricated. chip-AGNOSTIC.
_DERIV_PHRASE = (r"(?:calculated\s+as|defined\s+as|computed\s+as|equal\s+to|"
                 r"is\s+the\s+sum\s+of|given\s+by|set\s+to)")
_PROSE_DERIVED_HEAD_RE = re.compile(
    r"^\s*(?:[-*]|\d+[.)])?\s*\|?\s*\*{0,2}`?([A-Z][A-Z0-9_]{2,})`?\*{0,2}\s*[:|]")
_PROSE_DERIVED_EXPR_RE = re.compile(_DERIV_PHRASE + r"[^`\n]*?`([^`\n]+)`", re.I)
# lowercase parameter names (`data_width`, `shift_bits_width`) are common in CVDP
# prompts that describe parameter defaults in prose rather than code. Bind the literal
# default ONLY when the line explicitly names the parameter in backticks near the word
# "default" — never a stray nearby word. chip-AGNOSTIC.
_LOWERCASE_DEFAULT_RE = re.compile(
    r"\bdefault(?:\s+value)?(?:\s+|\s*[:=]\s*)(?:is\s+|of\s+|=\s*|:\s*)?"
    r"[^\n]{0,60}?`([a-z][a-z0-9_]*\w*)`[^\n]{0,30}?(\d+)", re.I)


def _as_int(tok: str) -> int:
    return int(tok, 16) if tok.lower().startswith("0x") else int(tok)


def _header_default_table(prompt: str) -> Dict[str, int]:
    """Read parameter defaults from a markdown table that has an explicit
    `| Parameter | Description | Default | Constraints |` header — the default
    value sits in the COLUMN under the `Default` (or `Value`) header, which may NOT
    be the last column (the `_PARAM_TABLE_ROW` last-cell heuristic misses it). We
    locate the `Default`-header column index from the header row and read that exact
    cell of each subsequent data row, until the table ends (a non-`|` line).
    §4.05: a value is bound ONLY from the Default-header column of a row whose first
    cell is a parameter NAME and whose Default cell is a bare integer literal —
    never a width-expression cell, never a guessed column. chip-AGNOSTIC."""
    out: Dict[str, int] = {}
    lines = prompt.splitlines()
    for i, ln in enumerate(lines):
        cells = [c.strip() for c in ln.split("|")]
        # header detection: a `| Parameter | ... | Default | ... |` row.
        lc = [c.lower() for c in cells]
        if "default" not in lc and "value" not in lc:
            continue
        if not any(c in ("parameter", "name", "param") for c in lc):
            continue
        di = lc.index("default") if "default" in lc else lc.index("value")
        ni = next((j for j, c in enumerate(lc)
                   if c in ("parameter", "name", "param")), None)
        if ni is None:
            continue
        # walk the data rows beneath this header (skip the `|---|---|` separator).
        for dl in lines[i + 1:]:
            if "|" not in dl:
                break
            dc = [c.strip() for c in dl.split("|")]
            if len(dc) <= max(di, ni):
                continue
            if set(dc[di].replace("-", "").replace(":", "")) <= set():
                continue  # separator row
            nm = dc[ni].strip("`* ")
            val = dc[di].strip("`* ")
            if re.fullmatch(r"[A-Za-z_]\w*", nm) and \
                    re.fullmatch(r"\d+|0[xX][0-9A-Fa-f]+", val):
                out.setdefault(nm, _as_int(val))
    return out


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
    # comma-separated siblings inside a `#(parameter A = 1, B = 2, …)` header that
    # share the single `parameter` keyword — _CODE_PARAM_RE caught only the first.
    for blk in _PARAM_HEADER_BLOCK_RE.finditer(prompt):
        for im in _PARAM_HEADER_ITEM_RE.finditer(blk.group("body")):
            _add(im.group(1), im.group(2))
    # DERIVED params: `parameter NAME = (A>B)?A:B` / `A*B` / `$clog2(D)`, AND
    # prose-derived ("ENCODED_DATA: Calculated as `PARITY_BIT + DATA_WIDTH + 1`").
    # COLLECTED here, but RESOLVED at the very end (after every LITERAL default
    # source has populated `out`), iterating to a fixed point so a chain settles.
    # §4.05: only added when the expression fully resolves to an int from KNOWN
    # params — never a fabricated default.
    # The RHS span `[^,\n/]+` includes a trailing `;` statement terminator (and any
    # trailing whitespace); strip both so `2*DATA_WIDTH + 1;` evaluates as the bare
    # `2*DATA_WIDTH + 1` (the `;` is not in the evaluator's vetted char class).
    derived = [(m.group(1), m.group(2).strip().rstrip(";").strip())
               for m in _DERIVED_PARAM_RE.finditer(prompt)
               if m.group(1) not in out]
    # PROSE-derived params: a line whose HEAD names an ALL-CAPS parameter and states
    # its value as an arithmetic EXPRESSION over other params. Bind name from the line
    # head, expr from the backticked span; only kept if it later resolves (a
    # non-arithmetic prose value drops at resolution time).
    for line in prompt.splitlines():
        hm = _PROSE_DERIVED_HEAD_RE.match(line)
        if not hm:
            continue
        nm = hm.group(1)
        if nm in out or any(nm == d[0] for d in derived):
            continue
        em = _PROSE_DERIVED_EXPR_RE.search(line)
        if em and any(c in em.group(1) for c in "+-*/"):  # must be an EXPRESSION
            derived.append((nm, em.group(1).strip()))
    # a markdown parameter table only when the prompt actually frames a parameter
    # section (avoids harvesting a generic numeric table as a param default).
    if re.search(r"(?i)\bparameter", prompt):
        for m in _PARAM_TABLE_ROW.finditer(prompt):
            nm = m.group(1)
            if nm.lower() in ("parameter", "name", "description", "signal", "width"):
                continue
            _add(nm, m.group(2))
    # a parameter table with an explicit `Default`-header column that is NOT the last
    # column (the last-cell heuristic above misses it) — read the value from the cell
    # under the `Default` header of each row.
    for nm, val in _header_default_table(prompt).items():
        _add(nm, str(val))
    # inline-code assignment annotated as a default — `NAME = 8` (default ...).
    # Anchored to the literal assignment, so the name is never guessed.
    for m in _INLINE_CODE_DEFAULT_RE.finditer(prompt):
        _add(m.group(1), m.group(2))
    # prose / paren defaults — bound LINE-BY-LINE to the line's leading ALL-CAPS
    # parameter token, so the name can never be a stray nearby lowercase word.
    # A line states a default ONLY when it both names a parameter at its head AND
    # carries a "default ... <int>" (or "(Default <int>...)" ) phrase.
    #
    # Separated Default sub-bullets: a parameter is introduced on the parent bullet
    # (`- WIDTH: Specifies ...`) and its default sits on an indented child line
    # (`  - Default: 32`). The child line's own head is "Default", not a parameter
    # token. When that happens we walk BACK to the most recent line that named a
    # parameter and bind the default there. The walk is bounded to the current
    # bullet block (never crosses a blank line or a de-dented sibling).
    lines = prompt.splitlines()
    last_param_line = -1
    last_param_name = None
    for i, line in enumerate(lines):
        hm = _LINE_HEAD_PARAM_RE.match(line)
        if hm:
            nm = hm.group(1)
            if nm not in ("DEFAULT", "NOTE", "BITS", "INPUTS", "OUTPUTS"):
                last_param_line = i
                last_param_name = nm
        pm = _PROSE_DEFAULT_PHRASE_RE.search(line) or _PAREN_DEFAULT_PHRASE_RE.search(line)
        if not pm:
            continue
        # Directly-named parameter line: bind normally.
        if hm and hm.group(1) not in ("DEFAULT", "NOTE", "BITS", "INPUTS", "OUTPUTS"):
            nm = hm.group(1)
            if nm not in out:
                _add(nm, pm.group(1))
            continue
        # Indented Default sub-bullet under a preceding parameter line.
        if last_param_name and last_param_line >= 0:
            # bound: within the same bullet block (no blank line since the param line)
            block = lines[last_param_line:i + 1]
            if all(ln.strip() for ln in block[:-1]):  # no blank line between
                # require the default line to be MORE indented than the param line
                param_indent = len(lines[last_param_line]) - len(lines[last_param_line].lstrip())
                def_indent = len(line) - len(line.lstrip())
                if def_indent > param_indent:
                    _add(last_param_name, pm.group(1))
    # A standalone bullet/line `- **WIDTH = 32**` is a weaker declaration than an
    # explicit phrase saying "default value = N": the same document can later use
    # `- WIDTH = 3` in a worked example without changing its declared default.
    # Read standalone assignments only after explicit defaults so `_add` preserves
    # the stronger fact. The whole-line anchor + ALL-CAPS name still keeps this
    # fallback from harvesting a mid-prose `x = 5`.
    for m in _BULLET_PARAM_DEFAULT_RE.finditer(prompt):
        _add(m.group(1), m.group(2))
    # lowercase parameter default phrases such as
    #   "The default value of the `data_width` is 16".
    # Only bound when the literal backtick parameter name appears within 60 chars
    # before the int and the word "default" is present — never fabricated.
    for m in _LOWERCASE_DEFAULT_RE.finditer(prompt):
        _add(m.group(1), m.group(2))
    # RESOLVE the derived/prose-derived params now that every literal default is in
    # `out`. Iterate to a fixed point (a chain like NBW_DELTA -> NBW_ERROR -> NBW_PRED
    # settles); only bind when the expression fully resolves to an int from KNOWN
    # params (a non-arithmetic prose value never resolves and is silently dropped).
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
    return out


def context_param_defaults(record: dict) -> Dict[str, int]:
    """Parameter -> default-int harvested from the PROVIDED `input['context']` RTL
    (the `parameter NAME = N` / `localparam NAME = N` declarations of the surrounding
    design files the submitter is given).

    §3.9 + §4.05: a parameter's DECLARED DEFAULT is part of the interface/config
    contract the spec hands the author — NOT the functional answer — so reading it
    from the provided context is the same header-level recovery the bridge already
    performs on the skeleton header. We read ONLY `parameter`/`localparam = <int>`
    declarations (never the body), and the caller merges these BELOW the
    prompt/testbench defaults (a value the prompt states is never overridden). This
    resolves `[DATA_WIDTH-1:0]`-style widths whose default lives only in the
    provided RTL (closing the `param_expression_width` extraction gap honestly —
    the value IS in the spec chain, just in the context file rather than the prose).
    """
    out: Dict[str, int] = {}
    if not isinstance(record, dict):
        return out
    ctx = (record.get("input") or {}).get("context") or {}
    if not isinstance(ctx, dict):
        return out
    derived: list[Tuple[str, str]] = []
    for k, v in ctx.items():
        if not (isinstance(v, str) and (k.endswith(".v") or k.endswith(".sv"))):
            continue
        # (a) bare-literal `parameter/localparam NAME = <int>` defaults.
        for rx in (_CODE_PARAM_RE, _LOCALPARAM_RE):
            for m in rx.finditer(v):
                nm, tok = m.group(1), m.group(2)
                if nm and nm not in out:
                    try:
                        out[nm] = _as_int(tok)
                    except ValueError:
                        pass
        # (b) DERIVED `parameter/localparam NAME = <EXPRESSION>` header declarations
        # (`parameter NWIDTH = $clog2(N)`, `TWIDTH = $clog2(N*R)`) — the SAME
        # param_expression_width gap class, just rooted in the provided context RTL.
        # §4.05 + §3.9: only the `parameter`/`localparam` HEADER keyword is read (never
        # a body `assign`); each is resolved BELOW the literals against the known param
        # table, so a value is bound only when the chain fully resolves to an int.
        for m in _DERIVED_PARAM_RE.finditer(v):
            nm = m.group(1)
            expr = m.group(2).strip().rstrip(";").strip()
            if nm and nm not in out and not nm.isdigit():
                derived.append((nm, expr))
    # resolve the derived context params to a fixed point (a chain like
    # TWIDTH -> N,R settles), seeded by the literal context defaults harvested above.
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
    # strip markdown code decoration that wraps identifiers INSIDE a stated width
    # expression — e.g. `[(`IN_DATA_WIDTH` + $clog2(`IN_DATA_NS`)) - 1 : 0]`. The
    # backtick is presentation, not an operator; removing it exposes the plain
    # `(IN_DATA_WIDTH + $clog2(IN_DATA_NS)) - 1` the evaluator understands. (Only the
    # backtick — NOT `**`, which is the power operator the evaluator accepts.)
    s = s.replace("`", "")
    # normalize the SV ceil-log2 system function to a python-callable token.
    s = re.sub(r"\$\s*clog2", "clog2", s)
    # the user-function synonyms `log2ceil`/`clogb2` compute the SAME ceil-log2; map
    # them onto `clog2` so a `[log2ceil(MaxRatio_g)-1:0]` width resolves identically.
    # \b-anchored so a parameter name merely CONTAINING the substring is untouched.
    s = re.sub(r"\b(?:log2ceil|clogb2)\b", "clog2", s)
    # normalize a SPEC-NOTATION multiply: a whitespace-delimited `x` or a `×`
    # between two operands means multiplication (e.g. `ROW_A x COL_A x WIDTH`,
    # `4 × 4 × 8`). Both sides must be whitespace so a hex `0x..` or an identifier
    # bearing an `x` is never touched. §4.05: only an unambiguous operator `x`/`×`
    # standing alone is rewritten — never a letter inside a token.
    s = s.replace("×", "*")            # the unicode multiplication sign
    s = re.sub(r"(?<=[\w\)])\s+[xX]\s+(?=[\w\(])", "*", s)
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


def has_param_expr_width(prompt: str, name: str) -> bool:
    """True iff a PARAMETER-EXPRESSION width is DECLARED for `name` — a bracket
    range carrying an identifier in EITHER order (`name [P-1:0]` / `[P-1:0] name`)
    or a markdown table width-cell with a param-arithmetic expression
    (`| name | N*W |`). This is the STRUCTURAL presence of the declaration,
    independent of whether the parameter table can RESOLVE it to an int. The
    caller uses it to refuse a coincidental same-line prose `N bits` literal for a
    port that is genuinely param-width: if the expression cannot be resolved the
    width is UNKNOWN (a gap), never the neighbour's literal (§4.05)."""
    esc = re.escape(name)
    for pat in (rf"\b{esc}\b[^\n|]{{0,40}}?\[\s*([^\]]*?)\s*\]",
                rf"\[\s*([^\]]*?)\s*\]\s*{esc}\b"):
        for m in re.finditer(pat, prompt):
            inner = m.group(1)
            if ":" in inner and _has_ident_span(inner):
                return True
    for rm in re.finditer(rf"^\s*\|\s*`?{esc}`?\s*\|\s*`?([^|`]+?)`?\s*[|(]",
                          prompt, re.M):
        cell = rm.group(1).strip()
        if _IDENT.search(cell) and re.fullmatch(r"[\w\s()+\-*/]+", cell) \
                and re.search(r"[*/+\-]", cell):
            return True
    return False


# words that appear inside a width expression but are NOT parameters (functions /
# numeric literals' stray letters). `$clog2`/`clog2`/`log2` are width FUNCTIONS.
_NON_PARAM_TOKENS = {"clog2", "log2ceil", "clogb2", "log2", "ceil", "floor", "x"}


def param_expr_idents(prompt: str, name: str) -> set:
    """The set of IDENTIFIERS appearing in `name`'s param-expression width (the
    bracket range in either order, or a table width-cell), excluding width
    functions (clog2/log2). Empty when no param-expression width is tied to the
    name. The caller decides whether every identifier is a KNOWN config parameter
    — if so the port is COMPLETELY specified as parameterised (the AI writes
    `[PARAM-1:0]`, correct under every harness override), not an extraction gap."""
    esc = re.escape(name)
    inners = []
    for pat in (rf"\b{esc}\b[^\n|]{{0,40}}?\[\s*([^\]]*?)\s*\]",
                rf"\[\s*([^\]]*?)\s*\]\s*{esc}\b"):
        for m in re.finditer(pat, prompt):
            inner = m.group(1)
            if ":" in inner and _has_ident_span(inner):
                inners.append(inner)
    for rm in re.finditer(rf"^\s*\|\s*`?{esc}`?\s*\|\s*`?([^|`]+?)`?\s*[|(]",
                          prompt, re.M):
        cell = rm.group(1).strip()
        if _IDENT.search(cell) and re.fullmatch(r"[\w\s()+\-*/]+", cell) \
                and re.search(r"[*/+\-]", cell):
            inners.append(cell)
    if not inners:
        return set()
    idents = set()
    for inner in inners:
        for tok in re.findall(r"[A-Za-z_]\w*", inner):
            if tok not in _NON_PARAM_TOKENS:
                idents.add(tok)
    return idents


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

    # (D) a PARENTHETICAL param-bits width annotation tied to the name (no bracket
    #     range): "`o_data_out` (`p_data_width` bit)" / "`o_set_bit_count`
    #     (`p_max_set_bit_count_width` bits)" / "`bus` (DATA_WIDTH bits)". The width
    #     is the named PARAMETER's default (or a literal `(8 bits)`). §4.05: resolved
    #     only when the parameter's default is in the table; else None (stays a gap).
    pm = re.search(
        rf"`?{esc}`?\s*\(\s*`?([A-Za-z_]\w*|\d+)`?\s*-?\s*bits?\b", prompt)
    if pm:
        tok = pm.group(1)
        if tok.isdigit():
            w = int(tok)
            if w > 0:
                return f"{tok} bits", w, "param_expression_width"
        elif tok in params:
            w = params[tok]
            if w > 0:
                return f"{tok} bits", w, "param_expression_width"

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
