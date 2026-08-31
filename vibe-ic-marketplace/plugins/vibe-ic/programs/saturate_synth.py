#!/usr/bin/env python3
"""saturate_synth.py — deterministic SOLVER for the CVDP SATURATE / CLAMP /
THRESHOLD + SIGN-DATAPATH family the existing solvers miss.

WHY a dedicated CVDP solver (and not the bridge / arith_variants):
  KEY INSIGHT (owner directive 2026-06-23): a whole shape of CVDP "code generation"
  problems is a SINGLE purely-combinational data-mapping function over one or two
  operands — NOT an `a+b`/`a*b` arithmetic op and NOT a registry shape:
    * CLAMP / SATURATE an operand to a STATED [lo, hi] range (out = clip(x,lo,hi));
    * THRESHOLD / comparator-to-FLAG (out = (x >/>=/</<= T) ? .. : ..);
    * ABSOLUTE VALUE of a signed operand (out = |x|);
    * SIGN-EXTEND / ZERO-EXTEND an operand from W to M bits;
    * NEGATE / two's-complement (out = -x = ~x + 1);
    * SIGNED <-> UNSIGNED reinterpret / conditional-select / conditional-clip.

  These are MISSED by the existing solvers:
    * arith_variants_synth only emits when it finds an `a`/`b` operand PAIR and
      an add/sub/mul VERB; a single-operand abs / sign-extend / negate, or a
      clamp-to-explicit-[lo,hi] (not the add-then-saturate it handles), has no `a+b`
      verb and so it returns None.
    * record_prompt_context_bridge SHORT-CIRCUITS `\\bsaturat`/`\\bclamp` to SKIP outright, and
      its registry path has no canonical for "clamp x to [lo,hi]" / "abs(x)" /
      "sign-extend W->M" / "x > T ? p : q", so it emits nothing (or, worse, a
      registry shape that does not match the function).

  This solver fills exactly that gap. It sources the module name + port interface
  ONLY from input.prompt + input.context (via `record_prompt_context_bridge.toplevel_name` /
  `record_prompt_context_bridge.extract_interface`) — the hidden cocotb harness (`dut.<sig>`
  test + `.env` TOPLEVEL / VERILOG_SOURCES) and the golden `output.*` are OFF-LIMITS
  oracle and are NEVER read. It recognizes the FUNCTION, parses the STATED bound /
  threshold / from-to widths / signed-ness from the prompt, and emits a
  functionally-correct COMBINATIONAL datapath.

§4.05 PARSE-OR-SKIP / NO-CHEAT (binding) — return None (SKIP) whenever:
  * the clamp/saturate BOUND ([lo,hi]) is not stated (literal or named param);
  * the THRESHOLD value, the comparison sense (>, >=, <, <=), or the two select
    results are not stated;
  * the operation's SIGNED-NESS is needed (abs / signed clamp / signed compare /
    sign-extend) but not stated (signed vs unsigned semantics differ);
  * the sign-extend / zero-extend FROM-width or TO-width is not stated;
  * the design is composite / sequential / a protocol / memory / a multi-op ALU /
    an FSM-pinned or latency-pinned wrapper / a LINT-or-edit task — i.e. not a
    single recognizable combinational mapping function;
  * the interface cannot be unambiguously extracted from the prompt+context (never
    guess a width, a port, a direction, or a polarity — the bridge returns None);
  * the golden/reference RTL is NEVER read (the harness + `output.*` are oracle;
    the module name + interface come from the prompt+context only).

A wrong clamp / threshold / sign datapath is far worse than an honest skip.

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

import record_prompt_context_bridge as _bridge  # noqa: E402  INTERFACE + module-name source

from _prose_polarity import is_denied, sentence_scope

Port = Tuple[str, int]  # (name, width)


# --------------------------------------------------------------------------- #
# §4.05 SKIP cues (keyed on SEMANTICS / INTERFACE vocabulary, never a design name).
# A composite / protocol / memory / multi-op design is not a single mapping fn.
# --------------------------------------------------------------------------- #
_COMPOSITE_RE = re.compile(
    r"""(?xi)
      \baxi\b | \baxi-?lite\b | \baxi-?stream\b | \baxis\b | \bapb\b | \bahb\b |
      \bwishbone\b | \bavalon\b | \btilelink\b | \buart\b | \bspi\b | \bi2c\b |
      \bi2s\b | \bjtag\b | \bpcie\b | \busb\b |
      \bfifo\b | \blifo\b | \bfilo\b | \bcache\b | \bsram\b | \bdram\b |
      \bregister\s+file\b | \bregfile\b | \bmemory\b | \bram\b | \brom\b |
      \bprocessor\b | \bcpu\b | \balu\b | \bopcode\b | \binstruction\b |
      \bsequencer\b | \bcontroller\b | \bstate\s+machine\b | \bfsm\b |
      \bperceptron\b | \bneuron\b | \bsobel\b | \bgaussian\b | \bconvolution\b |
      \bfir\b | \biir\b | \bfft\b | \bdft\b | \bfilter\b | \bcorrelat |
      \baccumulat | \bmoving\s+average\b | \bwindow\b | \bmatrix\b |
      \bcrc\b | \bscrambl | \bencoder\b | \bdecoder\b | \bmapper\b |
      \belevator\b | \bfan\b | \binterrupt\b | \bsorter\b | \bcounter\b |
      \bdivider\b | \bdivision\b | \bgcd\b | \bjitter\b
    """,
)

# Function-changing special algebra — a plain compare/clamp would be WRONG.
_SPECIAL_ALGEBRA_RE = re.compile(
    r"""(?xi)
      \bgalois\b | \bgf\s*\(\s*2 | \bfinite\s+field\b | \bcarry[-\s]?less\b |
      \bmodular\s+(?:arithmetic|reduction)\b | \bmontgomery\b |
      \bbcd\b | \bbinary[-\s]coded[-\s]decimal\b |
      \bfixed[-\s]?point\b | \bfloating[-\s]?point\b | \bIEEE[-\s]?754\b |
      \bqam\b
    """,
)

# A LINT / debug / "fix the bug" / "complete the partial module" edit-task is NOT a
# clean function emit — we cannot reproduce an unknown partial body. SKIP.
_EDIT_TASK_RE = re.compile(
    r"""(?xi)
      \blint\s+(?:code\s+)?review\b | \bresolve\s+all\s+lint\b |
      \bfix\s+the\s+bug | \bdebug\s+the\b | \bincorrect\s+behavior\b |
      \bexhibits\s+(?:incorrect|wrong)\b | \bedge\s+cases?\b.{0,40}\bbug
    """,
)


# --------------------------------------------------------------------------- #
# SEQUENTIAL detection — a combinational mapping cannot match a clocked design.
# COMPLIANCE: derived from the PROMPT (a clk/reset port in the extracted interface,
# or an explicit clocking cue in the prose) — NEVER from the OFF-LIMITS cocotb
# harness. A phrase that merely NEGATES clocking ("purely combinational", "no
# sequential elements") must not trigger, so we key on POSITIVE clocking cues.
# --------------------------------------------------------------------------- #
_SEQ_CUE_RE = re.compile(
    r"""(?xi)
      \bclock\s+edge\b | \bclocked\b | \bposedge\b | \bnegedge\b |
      \bon\s+the\s+(?:rising|falling)\s+edge\b |
      \bregister(?:s|ed)?\s+the\s+(?:result|output|value|data)\b |
      \bsynchronous(?:ly)?\b
    """,
)


def _is_sequential(prompt: str, ins: List[Port]) -> bool:
    """True if the design is clocked/sequential (not a pure combinational mapping).
    A clk/reset port in the PROMPT-extracted interface (names in the bridge's
    `_SEQ_PORTS`) OR a positive clocking cue in the prose. Reads prompt only."""
    if any(n.lower() in _bridge._SEQ_PORTS for n, _ in ins):
        return True
    return bool(_SEQ_CUE_RE.search(prompt))


# --------------------------------------------------------------------------- #
# parameter DEFAULTS from the prompt (prompt-only; used to resolve a bound /
# threshold stated as a named parameter — NEVER a port source).
# --------------------------------------------------------------------------- #
#: A prompt is written by a person, and a person states a RETIRED value as
#: readily as a live one. `sentence_scope` breaks on ". " and a blank line;
#: a prompt also ends sentences at a line end, so these are ADDED -- it
#: cannot remove from the shared set. Not "\n" alone: a prompt wraps
#: mid-sentence, and breaking there misses a denial written across two
#: lines, which is the under-reach that publishes the denied value.
_PROMPT_LINE_BREAKS = (".\n", "!\n", "?\n")


def _param_defaults(prompt: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    # `WIDTH ... default value of 5` / `... default is 5` / `... default = 5`.
    for m in re.finditer(
            r"`?([A-Z][A-Z0-9_]+)`?[^.\n]{0,80}?default(?:\s+value)?(?:\s+of)?\s*"
            r"(?:is\s+|=\s*)?`?(\d+)`?", prompt):
        lo, hi = sentence_scope(prompt, m.start(), m.end(),
                                extra_breaks=_PROMPT_LINE_BREAKS)
        if is_denied(prompt[lo:hi]):
            continue
        out.setdefault(m.group(1), int(m.group(2)))
    # `WIDTH ... (default value: 5)` / `(default: 5)` (parenthesized colon form).
    for m in re.finditer(
            r"`?([A-Z][A-Z0-9_]+)`?[^.\n]{0,80}?default(?:\s+value)?\s*:\s*`?(\d+)`?",
            prompt):
        lo, hi = sentence_scope(prompt, m.start(), m.end(),
                                extra_breaks=_PROMPT_LINE_BREAKS)
        if is_denied(prompt[lo:hi]):
            continue
        out.setdefault(m.group(1), int(m.group(2)))
    for m in re.finditer(r"parameter\s+(?:int\s+)?([A-Z][A-Z0-9_]+)\s*=\s*(\d+)",
                         prompt):
        lo, hi = sentence_scope(prompt, m.start(), m.end(),
                                extra_breaks=_PROMPT_LINE_BREAKS)
        if is_denied(prompt[lo:hi]):
            continue
        out.setdefault(m.group(1), int(m.group(2)))
    return out


# --------------------------------------------------------------------------- #
# port classification helpers
# --------------------------------------------------------------------------- #
def _find(ports: List[Port], names) -> Optional[Port]:
    low = {n.lower(): (n, w) for n, w in ports}
    for nm in names:
        if nm in low:
            return low[nm]
    return None


def _clk_port(ports):
    return _find(ports, ("clk", "clock", "i_clk", "i_clock"))


def _rst_port(ports):
    for n, w in ports:
        if re.search(r"(?i)(rst|reset|areset)", n):
            return (n, w)
    return None


_X_NAMES = ("x", "in", "a", "i_a", "data", "data_in", "din", "i_data", "in_data",
            "operand", "i_operand", "value", "i_value", "input_value", "i_in",
            "in_value", "d", "i_d")
_Y_NAMES = ("y", "out", "result", "o_result", "o_out", "data_out", "dout",
            "o_data", "out_data", "o_value", "output_value", "o", "q", "o_q",
            "clamped", "saturated", "abs_out", "o_abs", "neg_out", "o_neg",
            "extended", "o_ext", "y_out")


def _signed(name: str, signed: bool) -> str:
    return f"$signed({name})" if signed else name


# --------------------------------------------------------------------------- #
# bound / threshold / width parsing (LITERAL or named-param)
# --------------------------------------------------------------------------- #
def _num(tok: str) -> Optional[int]:
    tok = tok.strip().strip("`")
    neg = False
    if tok.startswith("-"):
        neg = True
        tok = tok[1:].strip()
    m = re.fullmatch(r"(?:0x([0-9a-fA-F]+)|(\d+)\s*'\s*[hH]([0-9a-fA-F]+)|(\d+))", tok)
    if not m:
        # 2^k form
        mm = re.fullmatch(r"2\s*\^\s*(\d+)\s*-\s*1", tok)
        if mm:
            v = (1 << int(mm.group(1))) - 1
            return -v if neg else v
        mm = re.fullmatch(r"2\s*\^\s*(\d+)", tok)
        if mm:
            v = 1 << int(mm.group(1))
            return -v if neg else v
        return None
    if m.group(1) is not None:
        v = int(m.group(1), 16)
    elif m.group(3) is not None:
        v = int(m.group(3), 16)
    else:
        v = int(m.group(4))
    return -v if neg else v


def _parse_value(prompt: str, params: Dict[str, int], frag: str) -> Optional[int]:
    """Resolve a value token to an int: a literal (dec/hex/2^k) or a named
    parameter present in `params`. None if unresolved."""
    frag = frag.strip().strip("`")
    v = _num(frag)
    if v is not None:
        return v
    if frag in params:
        return params[frag]
    return None


_VAL_TOK = r"(-?(?:0x[0-9a-fA-F]+|\d+\s*'\s*[hH][0-9a-fA-F]+|2\s*\^\s*\d+(?:\s*-\s*1)?|\d+)|[A-Z][A-Z0-9_]*)"
_RANGE_RE = re.compile(
    r"(?xi)"
    r"(?:clamp|saturat\w*|clip|bound|limit|constrain)\w*"
    r"[^.\n]{0,40}?"
    r"(?:to\s+(?:the\s+)?(?:range\s+)?|within\s+(?:the\s+)?(?:range\s+)?|between\s+)"
    r"\[?\s*`?" + _VAL_TOK + r"`?\s*"
    r"(?:,|\s+to\s+|\s+and\s+|\s*:\s*)\s*"
    r"`?" + _VAL_TOK + r"`?\s*\]?",
)


def _parse_range(prompt: str, params: Dict[str, int]
                 ) -> Optional[Tuple[int, int]]:
    """Parse a STATED [lo, hi] clamp range. Returns (lo, hi) or None."""
    for m in _RANGE_RE.finditer(prompt):
        lo = _parse_value(prompt, params, m.group(1))
        hi = _parse_value(prompt, params, m.group(2))
        if lo is not None and hi is not None and hi > lo:
            return lo, hi
    # an explicit "(0-15)" / "range 0 to 15" form near a clamp/saturat word.
    for m in re.finditer(
            r"(?i)(?:clamp|saturat\w*|clip|range|valid)[^.\n]{0,30}?"
            r"\(?\s*(\d+)\s*(?:-|to|,)\s*(\d+)\s*\)?", prompt):
        lo, hi = int(m.group(1)), int(m.group(2))
        if hi > lo:
            return lo, hi
    return None


_THRESH_RE = re.compile(
    r"""(?xi)
      (?:if|when|where)?\s*
      `?(\w+)`?\s*
      (>=|<=|>|<)\s*
      `?([0-9][0-9a-fx'^A-F]*|[A-Z][A-Z0-9_]*)`?
    """,
)


# --------------------------------------------------------------------------- #
# RTL emit helpers
# --------------------------------------------------------------------------- #
def _decl(direction: str, name: str, w: int, reg: bool = False) -> str:
    kw = f"{direction} reg" if reg else direction
    return f"    {kw} [{w-1}:0] {name}" if w > 1 else f"    {kw} {name}"


def _module(top: str, in_decls: List[str], out_decls: List[str], body: List[str],
            comment: str) -> str:
    return "\n".join(
        [comment, f"module {top} ("]
        + [",\n".join(in_decls + out_decls), ");"]
        + body + ["endmodule", ""])


def _stated_signed(low: str) -> Optional[bool]:
    """True/False if signed-ness is STATED, else None (unstated)."""
    has_signed = bool(re.search(r"(?<!un)\bsigned\b|two'?s\s+complement|"
                                r"sign\s+bit|signed\s+(?:integer|operand|value|mode)",
                                low))
    has_unsigned = bool(re.search(r"\bunsigned\b|magnitude", low))
    if has_signed and not has_unsigned:
        return True
    if has_unsigned and not has_signed:
        return False
    if has_signed and has_unsigned:
        return None  # both mentioned (dual-mode) — signed-ness is mode-selected
    return None


# =========================================================================== #
# FUNCTION recognition + emit
# =========================================================================== #
def _recognize_and_emit(top: str, prompt: str,
                        ins: List[Port], outs: List[Port],
                        params: Dict[str, int]) -> Optional[str]:
    low = prompt.lower()

    # purely combinational only: a clock among the ports defeats every shape here.
    if _clk_port(ins) or _rst_port(ins):
        return None

    x = _find(ins, _X_NAMES)
    y = _find(outs, _Y_NAMES)

    # Each detector is SPECIFIC (verb-precise) so at most one fires; "negative"
    # (a sign DESCRIPTION) must NOT trigger negate, "magnitude" alone must NOT
    # trigger abs, etc. Detectors are evaluated in structural-specificity order;
    # crucially, dispatch FALLS THROUGH to the next family when an emitter SKIPs,
    # so a keyword that incidentally matches one family but whose interface fits
    # another is still solved (and an unsolvable record SKIPs at the end).
    has_cmp_flags = bool(
        _find(outs, ("o_greater", "greater", "gt", "o_gt", "a_gt_b", "o_a_gt_b"))
        or _find(outs, ("o_less", "less", "lt", "o_lt", "a_lt_b", "o_a_lt_b"))
        or _find(outs, ("o_equal", "equal", "eq", "o_eq", "a_eq_b", "o_a_eq_b")))
    is_clamp = bool(re.search(r"\bclamp\w*|\bsaturat\w*|\bclip\w*|"
                              r"constrain\w*\s+to|bound\w*\s+to", low))
    is_abs = bool(re.search(r"\babsolute\s+value\b|\babs\s*\(|magnitude\s+of\s+"
                            r"(?:the\s+)?(?:signed\s+)?(?:input|operand|value)", low))
    is_neg = bool(re.search(
        r"\bnegate\b|\bnegation\b|two'?s[-\s]complement\s+negat|"
        r"additive\s+inverse|compute\s+the\s+negative\s+of", low))
    is_ext = bool(re.search(r"sign[-\s]?extend\w*|zero[-\s]?extend\w*|"
                            r"sign[-\s]?extension|zero[-\s]?extension", low))
    is_thresh = has_cmp_flags or bool(re.search(
        r"\bthreshold\w*|\bcomparator\w*|\bcompare\w*|greater\s+than|less\s+than|"
        r"\bexceed\w*|\bflag\b[^.\n]{0,40}(?:>=|<=|>|<)|"
        r"(?:>=|<=|>|<)[^.\n]{0,40}\bflag\b", low))

    # structural comparator (gt/lt/eq flag outputs) is the least-ambiguous shape:
    # try it FIRST when those flag ports exist.
    if has_cmp_flags:
        r = _emit_threshold(top, prompt, low, params, ins, outs)
        if r:
            return r
    # dispatch the single-operand mappings; FALL THROUGH on a SKIP.
    if is_ext:
        r = _emit_extend(top, prompt, low, params, ins, outs, x, y)
        if r:
            return r
    if is_clamp:
        r = _emit_clamp(top, prompt, low, params, ins, outs, x, y)
        if r:
            return r
    if is_abs:
        r = _emit_abs(top, prompt, low, ins, outs, x, y)
        if r:
            return r
    if is_neg:
        r = _emit_negate(top, prompt, low, ins, outs, x, y)
        if r:
            return r
    if is_thresh:
        return _emit_threshold(top, prompt, low, params, ins, outs)
    return None


# --------------------------------------------------------------------------- #
# CLAMP / SATURATE x to a STATED [lo, hi].
# --------------------------------------------------------------------------- #
def _emit_clamp(top, prompt, low, params, ins, outs, x, y) -> Optional[str]:
    if not (x and y):
        return None
    rng = _parse_range(prompt, params)
    if rng is None:
        return None  # §4.05: unstated bound -> SKIP
    lo, hi = rng
    signed = _stated_signed(low)
    # signed-ness only matters when lo can be negative; if lo >= 0 and the whole
    # range is non-negative, unsigned compare is correct regardless.
    if lo < 0 and signed is None:
        return None  # §4.05: negative bound but signed-ness unstated -> SKIP
    if lo < 0 and signed is False:
        return None  # contradiction: unsigned port cannot hold a negative bound
    xn, xw = x
    yn, yw = y
    use_signed = bool(signed) or lo < 0
    cmp_x = _signed(xn, use_signed) if use_signed else xn
    lo_lit = str(lo) if lo >= 0 else f"-{abs(lo)}"
    hi_lit = str(hi)
    in_decls = [_decl("input", n, w) for n, w in ins]
    out_decls = [_decl("output", n, w, reg=(n == yn)) for n, w in outs]
    body = [
        "    always @(*) begin",
        f"        if ({cmp_x} < {_signed(lo_lit, use_signed) if use_signed else lo_lit})",
        f"            {yn} = {lo_lit};",
        f"        else if ({cmp_x} > {_signed(hi_lit, use_signed) if use_signed else hi_lit})",
        f"            {yn} = {hi_lit};",
        "        else",
        f"            {yn} = {xn};",
        "    end",
    ]
    return _module(top, in_decls, out_decls, body,
                   f"// program-SOLVED combinational clamp/saturate to "
                   f"[{lo_lit},{hi_lit}] ({'signed' if use_signed else 'unsigned'}); "
                   f"deterministic.")


# --------------------------------------------------------------------------- #
# SIGN-EXTEND / ZERO-EXTEND x from W to M.
# --------------------------------------------------------------------------- #
def _emit_extend(top, prompt, low, params, ins, outs, x, y) -> Optional[str]:
    if not (x and y):
        return None
    is_sign = bool(re.search(r"sign[-\s]?extend|sign[-\s]?extension", low))
    is_zero = bool(re.search(r"zero[-\s]?extend|zero[-\s]?extension", low))
    if is_sign == is_zero:
        return None  # neither or BOTH mentioned ambiguously -> SKIP
    xn, fw = x   # from-width = the input port width
    yn, mw = y   # to-width   = the output port width
    if mw <= fw or fw < 1:
        return None  # §4.05: widths must be stated and M > W
    in_decls = [_decl("input", n, w) for n, w in ins]
    out_decls = [_decl("output", n, w) for n, w in outs]
    pad = mw - fw
    if is_sign:
        rhs = f"{{{{{pad}{{{xn}[{fw-1}]}}}}, {xn}}}"
        kind = "sign-extend"
    else:
        rhs = f"{{{{{pad}{{1'b0}}}}, {xn}}}"
        kind = "zero-extend"
    body = [f"    assign {yn} = {rhs};"]
    return _module(top, in_decls, out_decls, body,
                   f"// program-SOLVED combinational {kind} {fw}->{mw}; "
                   f"deterministic.")


# --------------------------------------------------------------------------- #
# ABSOLUTE VALUE of a signed operand.
# --------------------------------------------------------------------------- #
def _emit_abs(top, prompt, low, ins, outs, x, y) -> Optional[str]:
    if not (x and y):
        return None
    signed = _stated_signed(low)
    if signed is not True:
        return None  # §4.05: abs is only defined on a SIGNED operand
    xn, xw = x
    yn, yw = y
    if yw < xw:
        return None
    in_decls = [_decl("input", n, w) for n, w in ins]
    out_decls = [_decl("output", n, w) for n, w in outs]
    body = [f"    assign {yn} = {xn}[{xw-1}] ? (~{xn} + 1'b1) : {xn};"]
    return _module(top, in_decls, out_decls, body,
                   f"// program-SOLVED combinational absolute value (signed); "
                   f"deterministic.")


# --------------------------------------------------------------------------- #
# NEGATE / two's-complement.
# --------------------------------------------------------------------------- #
def _emit_negate(top, prompt, low, ins, outs, x, y) -> Optional[str]:
    if not (x and y):
        return None
    xn, xw = x
    yn, yw = y
    if yw < xw:
        return None
    in_decls = [_decl("input", n, w) for n, w in ins]
    out_decls = [_decl("output", n, w) for n, w in outs]
    body = [f"    assign {yn} = (~{xn} + 1'b1);"]
    return _module(top, in_decls, out_decls, body,
                   f"// program-SOLVED combinational negate (two's complement); "
                   f"deterministic.")


# --------------------------------------------------------------------------- #
# THRESHOLD / comparator-to-flag.
#   * a dual-mode (signed/magnitude) gt/lt/eq comparator with enable; or
#   * a single (x </>/>=/<= T) ? p : q select with a STATED threshold.
# --------------------------------------------------------------------------- #
def _emit_threshold(top, prompt, low, params, ins, outs) -> Optional[str]:
    gt = _find(outs, ("o_greater", "greater", "gt", "o_gt", "a_gt_b", "o_a_gt_b"))
    lt = _find(outs, ("o_less", "less", "lt", "o_lt", "a_lt_b", "o_a_lt_b"))
    eq = _find(outs, ("o_equal", "equal", "eq", "o_eq", "a_eq_b", "o_a_eq_b"))
    a = _find(ins, ("i_a", "a", "in_a", "x", "i_x", "data", "i_data", "in0", "i_in0"))
    b = _find(ins, ("i_b", "b", "in_b", "y", "i_y", "ref", "i_ref", "in1", "i_in1"))
    en = _find(ins, ("i_enable", "enable", "en", "i_en"))
    mode = _find(ins, ("i_mode", "mode", "sel", "i_sel", "signed_mode"))

    # ---- gt/lt/eq comparator-to-flag (the dominant CVDP comparator shape) ----#
    if (gt or lt or eq) and a and b:
        # need at least two of the three flags to be a real comparator.
        if sum(bool(f) for f in (gt, lt, eq)) < 2:
            return None
        if a[1] != b[1] or a[1] < 1:
            return None
        signed = _stated_signed(low)
        has_dual = mode is not None and bool(
            re.search(r"(?i)(signed|magnitude|unsigned)\s+mode", low)) \
            and re.search(r"(?i)magnitude", low) and re.search(r"(?i)signed", low)
        if not has_dual and signed is None:
            return None  # §4.05: single-mode compare but signed-ness unstated
        in_decls = [_decl("input", n, w) for n, w in ins]
        out_decls = [_decl("output", n, w) for n, w in outs]
        an, bn = a[0], b[0]
        if has_dual:
            # mode high => signed compare; low => unsigned magnitude compare.
            # parse which polarity is signed (default: high=signed per CVDP norm).
            high_signed = not bool(re.search(
                r"(?i)(low|0)\D{0,20}signed\s+mode", low))
            sa, sb = f"$signed({an})", f"$signed({bn})"
            sig_cmp = "(%s {op} %s)"
            usig_cmp = "(%s {op} %s)" % (an, bn)
            mn = mode[0]
            sel = mn if high_signed else f"!{mn}"

            def _expr(op):
                return (f"({sel} ? ($signed({an}) {op} $signed({bn})) "
                        f": ({an} {op} {bn}))")
        else:
            su = bool(signed)
            ca, cb = _signed(an, su), _signed(bn, su)

            def _expr(op):
                return f"({ca} {op} {cb})"
        guard = (f"{en[0]} && " if en else "")
        body = []
        if gt:
            body.append(f"    assign {gt[0]} = {guard}{_expr('>')};")
        if lt:
            body.append(f"    assign {lt[0]} = {guard}{_expr('<')};")
        if eq:
            body.append(f"    assign {eq[0]} = {guard}({an} == {bn});")
        return _module(top, in_decls, out_decls, body,
                       "// program-SOLVED combinational comparator-to-flag "
                       + ("(dual signed/magnitude mode)" if has_dual
                          else ("signed" if signed else "unsigned"))
                       + (" with enable" if en else "") + "; deterministic.")

    # ---- single threshold select: out = (x <op> T) ? p : q -------------------#
    x = _find(ins, _X_NAMES)
    y = _find(outs, _Y_NAMES)
    flag = _find(outs, ("flag", "o_flag", "above", "o_above", "exceeded",
                        "o_exceeded", "trigger", "o_trigger"))
    out_t = y or flag
    if not (x and out_t):
        return None
    # need a STATED threshold tied to the operand with an explicit comparison.
    best = None
    for m in _THRESH_RE.finditer(prompt):
        lhs, op, rhs = m.group(1), m.group(2), m.group(3)
        if lhs.lower() != x[0].lower():
            continue
        tv = _parse_value(prompt, params, rhs)
        if tv is None:
            continue
        best = (op, tv)
        break
    if best is None:
        return None  # §4.05: no parseable threshold tied to the operand -> SKIP
    op, tv = best
    signed = _stated_signed(low)
    if (tv < 0) and signed is not True:
        return None
    xn = _signed(x[0], bool(signed)) if signed else x[0]
    # a 1-bit flag output: out = (x <op> T).
    if flag and out_t == flag and flag[1] == 1:
        in_decls = [_decl("input", n, w) for n, w in ins]
        out_decls = [_decl("output", n, w) for n, w in outs]
        body = [f"    assign {flag[0]} = ({xn} {op} {tv});"]
        return _module(top, in_decls, out_decls, body,
                       f"// program-SOLVED combinational threshold flag "
                       f"(x {op} {tv}); deterministic.")
    return None  # a value-select needs both stated results; SKIP if not pinned


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def solve(record: dict) -> Optional[str]:
    """Emit a deterministic combinational clamp/saturate/threshold/sign datapath
    (module named per the PROMPT) for a record whose interface + function are fully
    stated in input.prompt + input.context, else None (SKIP). Reads ONLY
    input.prompt + input.context — never the cocotb harness / `.env` / golden."""
    if not isinstance(record, dict):
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None

    # §4.05 up-front SKIPs (composite / special-algebra / edit-task) — prompt-only.
    if _COMPOSITE_RE.search(prompt) or _SPECIAL_ALGEBRA_RE.search(prompt) \
            or _EDIT_TASK_RE.search(prompt):
        return None

    # module name + interface from prompt+context ONLY (the bridge is the sanctioned
    # prompt/context reader; it never touches the harness or golden).
    top = _bridge.toplevel_name(record)
    if not top:
        return None
    iface = _bridge.extract_interface(record, top)
    if not iface:
        return None
    ins, outs = iface

    # a clocked / registered / synchronous design => not a pure combinational map.
    if _is_sequential(prompt, ins):
        return None

    params = _param_defaults(prompt)
    try:
        return _recognize_and_emit(top, prompt, ins, outs, params)
    except Exception:
        return None


def family_of(record: dict) -> Optional[str]:
    """Reporting helper: the family this solver emitted, or None."""
    rtl = solve(record)
    if not rtl:
        return None
    c = rtl.splitlines()[0]
    for key in ("clamp/saturate", "sign-extend", "zero-extend", "absolute value",
                "negate", "comparator-to-flag", "threshold flag"):
        if key in c:
            return key
    return "saturate-family"


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--id")
    ap.add_argument("--emit", action="store_true")
    a = ap.parse_args(argv)
    recs = [json.loads(l) for l in open(a.jsonl)]
    n = 0
    fam: Dict[str, int] = {}
    for r in recs:
        if a.id and r.get("id") != a.id:
            continue
        rtl = solve(r)
        if rtl:
            n += 1
            k = family_of(r)
            fam[k] = fam.get(k, 0) + 1
            if a.emit or a.id:
                print(f"=== {r.get('id')}  family={k} ===")
                print(rtl)
    print(f"emitted={n}/{len(recs)}  families={fam}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
