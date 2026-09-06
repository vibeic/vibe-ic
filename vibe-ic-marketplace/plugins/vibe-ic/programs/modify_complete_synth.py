#!/usr/bin/env python3
"""modify_complete_synth.py — deterministic SOLVER for two CVDP
"complete / enhance a FULLY-and-UNAMBIGUOUSLY-specified atomic function"
records whose function is pinned by a STANDARD deterministic algorithm and whose
emitted RTL is iverilog-PROVEN against the cocotb harness's own reference model
(NOT the golden answer — the golden is stripped/empty in CVDP v1.1.0).

The two operations (each keyed on stated OPERATION semantics, never a design
name or record id; the SAME prose under any TOPLEVEL solves identically):

  (C) CONVOLUTIONAL ENCODER — a fixed constraint-length K=3 rate-1/2
      convolutional encoder with the TWO stated generator polynomials
      g1 = 111 (x^2+x+1) and g2 = 101 (x^2+1) over a 2-bit shift register of the
      previous input bits. Synchronous, async-free, reset-clears. The encoding is
      the textbook deterministic function of the stated taps; verified
      cycle-accurate vs an independent Python reference (incl. reset-mid-stream).

  (M) MOVING AVERAGE (+enable) — an 8-sample, 12-bit running moving average using
      a circular memory + running sum (latest added, oldest subtracted, divide by
      8 via >>3), ENHANCED with a 1-bit `enable` that gates the state update
      (write / read / address-increment / sum-update all conditioned on enable);
      synchronous reset clears state. The window, width, divisor and enable
      semantics are stated exactly; verified vs the harness
      `calculate_moving_average` reference under the harness reset/enable warmup
      sequence and 1-enabled-cycle output latency, multi-seed.

§4.05 PARSE-OR-SKIP / NO-LEAK / NO-CHEAT (binding):
  * NEVER read the golden/reference RTL. The PORT INTERFACE is recovered ONLY
    from the PROVIDED `input['context']` skeleton's module HEADER (header-only —
    the bridge / cvdp_context_interface_recover doctrine: a port header is the
    spec interface, never the functional answer) and/or the stated prose; the
    FUNCTION is derived from the prompt prose + the STANDARD algorithm it names,
    never from any reference body.
  * NEVER guess a width / direction / polynomial / window / divisor / reset
    style. Each emitter re-checks every governing fact it depends on against the
    actual recovered interface and the prose; ANY mismatch / ambiguity -> None.
  * Recognition is EXACT-operation-gated: a record that is a LINT review, an
    AREA-optimization, a different polynomial, a different window/width, or a
    differently-shaped interface returns None. A near-miss MUST SKIP.

API (mirrors the sibling solvers):
    solve(record) -> Optional[str]   # emitted RTL (module == harness TOPLEVEL) | None
chip-AGNOSTIC, pure-function, deterministic.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

Port = Tuple[str, int]  # (name, width)

# A record whose deliverable is a LINT review / an AREA-optimization / a
# functional-equivalence rewrite is NOT a from-spec atomic emit — SKIP it up
# front (these ship a complex existing module the scorer pins functionally, which
# we must not reconstruct-and-guess). Keyed on the stated TASK shape.
_NON_GEN_TASK_RE = re.compile(
    r"""(?xi)
      \blint\s+code\s+review\b | \blint[-\s]clean\b | \blint\s+review\b |
      \barea\s+optimization\b | \barea[-\s]optimi[sz] |
      \breduction\s+in\s+(?:cells|wires)\b | \bfunctional\s+equivalence\b
    """,
)


# --------------------------------------------------------------------------- #
# interface recovery — HEADER ONLY (never a body). Reuse the shipped recover
# helper / bridge; fall back to a local header parse of the context skeleton.
# --------------------------------------------------------------------------- #
def _toplevel(record: dict) -> Optional[str]:
    try:
        import record_prompt_context_bridge as _bridge
        return _bridge.toplevel_name(record)
    except Exception:
        return None


def _context_header_ports(record: dict, top: str
                          ) -> Optional[Tuple[List[Port], List[Port], Dict[str, int]]]:
    """Recover (ins, outs, params) from the PROVIDED input.context skeleton's
    `module <top> #(...) ( ... );` HEADER only. None if the target header is
    absent / unparseable. The body is NEVER read."""
    ctx = (record.get("input") or {}).get("context") or {}
    if not isinstance(ctx, dict):
        return None
    src = None
    for k, v in ctx.items():
        if isinstance(v, str) and (k.endswith(".v") or k.endswith(".sv")) \
           and re.search(rf"\bmodule\s+{re.escape(top)}\b", v):
            src = v
            break
    if src is None:
        return None
    # strip comments
    s = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    s = re.sub(r"//[^\n]*", " ", s)
    mm = re.search(rf"\bmodule\s+{re.escape(top)}\b", s)
    if not mm:
        return None
    rest = s[mm.end():]
    # optional #( ... ) parameter block -> read integer defaults
    params: Dict[str, int] = {}
    pm = re.match(r"\s*#\s*\(", rest)
    after_params = rest
    if pm:
        depth = 0
        for i, c in enumerate(rest):
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    pblock = rest[pm.end():i]
                    for pmm in re.finditer(r"\b([A-Za-z_]\w*)\s*=\s*(\d+)", pblock):
                        params.setdefault(pmm.group(1), int(pmm.group(2)))
                    after_params = rest[i + 1:]
                    break
    # the port-list ( ... )
    op = after_params.find("(")
    if op < 0:
        return None
    depth = 0
    cp = -1
    for i in range(op, len(after_params)):
        c = after_params[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                cp = i
                break
    if cp < 0:
        return None
    portlist = after_params[op + 1:cp]
    ins: List[Port] = []
    outs: List[Port] = []
    for piece in _split_top_commas(portlist):
        piece = piece.strip()
        dm = re.match(r"\b(input|output|inout)\b", piece)
        if not dm:
            continue
        direction = dm.group(1)
        # width: a [hi:lo] range (literal or param-expr), else scalar 1-bit
        w = _range_width(piece, params)
        nm = re.search(r"(\w+)\s*$", piece)
        if not nm or w is None:
            continue
        name = nm.group(1)
        if name in ("wire", "reg", "logic", "signed", "unsigned"):
            continue
        (ins if direction == "input" else outs).append((name, w))
    if not ins or not outs:
        return None
    return ins, outs, params


def _split_top_commas(s: str) -> List[str]:
    out, depth, cur = [], 0, []
    for c in s:
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
    if "".join(cur).strip():
        out.append("".join(cur))
    return out


def _range_width(piece: str, params: Dict[str, int]) -> Optional[int]:
    """Width from a single port declaration's `[hi:lo]` (literal or
    param-expr over the recovered param defaults). Scalar -> 1. Unresolvable -> None."""
    m = re.search(r"\[\s*([^:\]]+?)\s*:\s*([^:\]]+?)\s*\]", piece)
    if not m:
        # scalar port (typed, no bracket) -> 1 bit
        return 1
    hi, lo = m.group(1).strip(), m.group(2).strip()
    hv = _eval_expr(hi, params)
    lv = _eval_expr(lo, params)
    if hv is None or lv is None:
        return None
    return abs(hv - lv) + 1


def _eval_expr(expr: str, params: Dict[str, int]) -> Optional[int]:
    """Evaluate a width-bound expression over integer param defaults. Supports
    + - * / and integer literals and recovered parameter names. None on any
    unknown identifier (no guessing)."""
    e = expr.strip()
    # substitute known params
    toks = re.findall(r"[A-Za-z_]\w*", e)
    for t in toks:
        if t not in params:
            return None
    safe = re.sub(r"([A-Za-z_]\w*)", lambda mm: str(params[mm.group(1)]), e)
    if not re.fullmatch(r"[\d\s+\-*/()]+", safe):
        return None
    try:
        v = eval(safe, {"__builtins__": {}}, {})  # noqa: S307 — arithmetic only, sanitized
        return int(v)
    except Exception:
        return None


# =========================================================================== #
# (C) CONVOLUTIONAL ENCODER (K=3, g1=111, g2=101)
# =========================================================================== #
def _is_conv_encoder(prompt: str) -> Optional[Tuple[str, str]]:
    """Return (g1_taps, g2_taps) bit strings if the prompt UNAMBIGUOUSLY states a
    K=3 rate-1/2 convolutional encoder with two stated generator polynomials, else
    None. The polynomials MUST be stated (either as 111/101 or x^2+x+1 / x^2+1)."""
    t = prompt.lower()
    if "convolutional" not in t or "encoder" not in t:
        return None
    # constraint length K=3 must be stated.
    if not re.search(r"\b(?:k\s*=\s*3|constraint\s+length\s*(?:of\s*)?(?:k\s*=\s*)?3)\b", t):
        return None
    # two generator polynomials, stated as bit triples and/or x-polynomials.
    g1 = _gen_taps(t, idx=1)
    g2 = _gen_taps(t, idx=2)
    if g1 is None or g2 is None:
        return None
    # rate-1/2 shape: a single serial data input, two encoded outputs.
    return g1, g2


def _gen_taps(t: str, idx: int) -> Optional[str]:
    """Resolve generator polynomial #idx to a 3-bit tap string '<x2><x1><x0>'.
    Accept an explicit 3-bit code (`g1=111`, `g2 = 101`) OR an x-polynomial
    (`x^2 + x + 1`, `x^2 + 1`). None if not unambiguously stated."""
    # explicit bit triple: gN=111 / gN = 101 / g_N 110
    m = re.search(rf"\bg_?{idx}\b[^.\n]{{0,20}}?([01]{{3}})\b", t)
    if m:
        return m.group(1)
    # x-polynomial near gN
    m = re.search(rf"\bg_?{idx}\b[^.\n]{{0,40}}?\(([^)]*x[^)]*)\)", t)
    if m:
        return _poly_to_taps(m.group(1))
    # ordered "two generator polynomials: g_1(x) = ... and g_2(x) = ..."
    m = re.search(rf"g_?{idx}\s*\(\s*x\s*\)\s*=\s*([^.\n]+?)(?:\s+and\b|\.|$)", t)
    if m:
        return _poly_to_taps(m.group(1))
    return None


def _poly_to_taps(poly: str) -> Optional[str]:
    """`x^2 + x + 1` -> '111', `x^2 + 1` -> '101', `x^2 + x` -> '110'. Degree must
    be 2 (K=3). None if any unexpected term."""
    p = poly.lower().replace(" ", "")
    taps = [0, 0, 0]  # [x2, x1, x0]
    # tokenize additive terms
    terms = re.split(r"\+", p)
    for term in terms:
        term = term.strip().strip("*")
        if term == "":
            continue
        if term in ("1",):
            taps[2] = 1
        elif term in ("x", "x^1", "x**1"):
            taps[1] = 1
        elif term in ("x^2", "x**2", "x2"):
            taps[0] = 1
        else:
            return None
    if taps[0] != 1:           # degree must be 2 for K=3
        return None
    return f"{taps[0]}{taps[1]}{taps[2]}"


def _emit_conv_encoder(record: dict, top: str, ins: List[Port], outs: List[Port],
                       g1: str, g2: str) -> Optional[str]:
    # interface: clk, rst, one 1-bit data input; two 1-bit encoded outputs.
    clk = [n for n, w in ins if n.lower() in ("clk", "clock") and w == 1]
    rst = [n for n, w in ins if n.lower() in ("rst", "reset", "rst_n", "resetn",
                                              "rstn") and w == 1]
    data = [(n, w) for n, w in ins if n.lower() not in
            ("clk", "clock", "rst", "reset", "rst_n", "resetn", "rstn")]
    if len(clk) != 1 or len(rst) != 1 or len(data) != 1 or data[0][1] != 1:
        return None
    if len(outs) != 2 or any(w != 1 for _, w in outs):
        return None
    clk_n, rst_n_port = clk[0], rst[0]
    din = data[0][0]
    o1, o2 = outs[0][0], outs[1][0]
    # active-high reset assumed when name lacks _n; active-low when _n suffix.
    rst_active_low = rst_n_port.lower().endswith("_n") or rst_n_port.lower().endswith("n") \
        and rst_n_port.lower() in ("rstn", "resetn", "rst_n")
    rst_cond = f"!{rst_n_port}" if rst_active_low else rst_n_port
    # taps: index 0 = x^2 (sr[1], two cycles ago), index1 = x^1 (sr[0], one cycle
    # ago), index2 = x^0 (current data_in).
    def _expr(taps: str) -> str:
        terms = []
        if taps[2] == "1":
            terms.append(din)
        if taps[1] == "1":
            terms.append("sr[0]")
        if taps[0] == "1":
            terms.append("sr[1]")
        return " ^ ".join(terms) if terms else "1'b0"
    return "\n".join([
        f"// program-SOLVED K=3 convolutional encoder g1={g1} g2={g2}; sequential, deterministic.",
        f"module {top} (",
        f"    input  wire {clk_n},",
        f"    input  wire {rst_n_port},",
        f"    input  wire {din},",
        f"    output reg  {o1},",
        f"    output reg  {o2}",
        f");",
        f"    reg [1:0] sr;   // sr[1]=x^2 (2 cycles ago), sr[0]=x^1 (1 cycle ago)",
        f"    always @(posedge {clk_n}) begin",
        f"        if ({rst_cond}) begin",
        f"            sr <= 2'b00;",
        f"            {o1} <= 1'b0;",
        f"            {o2} <= 1'b0;",
        f"        end else begin",
        f"            {o1} <= {_expr(g1)};",
        f"            {o2} <= {_expr(g2)};",
        f"            sr <= {{sr[0], {din}}};",
        f"        end",
        f"    end",
        f"endmodule",
        "",
    ])


# =========================================================================== #
# (M) MOVING AVERAGE (+enable)
# =========================================================================== #
def _is_moving_average_enable(prompt: str) -> Optional[Tuple[int, int]]:
    """Return (width, window) if the prompt UNAMBIGUOUSLY states a power-of-2
    window moving average ENHANCED with an enable that gates the state update,
    with both width and window stated; else None."""
    t = prompt.lower()
    if "moving average" not in t:
        return None
    # the enhancement must add an enable that gates the update.
    if not (re.search(r"\benable\b", t) and re.search(r"\b(?:gates?|only\s+when|"
            r"controls?\s+when|only\s+execute|when\s+(?:the\s+)?enable)\b", t)):
        return None
    # window: "N-sample moving average" (N must be stated; divide-by-N).
    wm = re.search(r"\b(\d+)[-\s]sample\s+moving\s+average\b", t)
    if not wm:
        return None
    window = int(wm.group(1))
    if window < 2 or (window & (window - 1)) != 0:   # power-of-2 only (>>log2)
        return None
    # width: "M-bit input data".
    bm = re.search(r"\b(\d+)[-\s]bit\b", t)
    if not bm:
        return None
    width = int(bm.group(1))
    if width < 2:
        return None
    return width, window


def _enable_port_name(prompt: str, existing: set) -> Optional[str]:
    """The NEW enable input port name the prompt states to ADD. CVDP states it as
    `enable` (the prose names the signal). None if not unambiguously a single
    1-bit enable add; never invents a name not in the prose."""
    t = prompt
    # an explicit "`enable`" / "Enable:" signal mention; CVDP uses 'enable'.
    if re.search(r"(?i)\benable\b", t):
        # prefer a backticked / bolded signal token if present.
        m = re.search(r"`(enable\w*)`", t) or re.search(r"\*\*\s*(enable\w*)\s*\*\*", t, re.I)
        name = m.group(1) if m else "enable"
        return name if name not in existing else None
    return None


def _emit_moving_average(record: dict, top: str, ins: List[Port], outs: List[Port],
                         width: int, window: int, prompt: str) -> Optional[str]:
    # interface: existing header (clk, reset, data_in[width], data_out[width]) PLUS
    # the NEW 1-bit `enable` input the prompt states to add. The enable is NOT yet
    # in the recovered (pre-modification) header — it is the stated enhancement.
    clk = [n for n, w in ins if n.lower() in ("clk", "clock") and w == 1]
    rst = [n for n, w in ins if n.lower() in ("reset", "rst", "rst_n", "resetn",
                                              "rstn") and w == 1]
    en = [n for n, w in ins if n.lower() in ("enable", "en", "en_i", "i_enable") and w == 1]
    din = [(n, w) for n, w in ins if w == width and n.lower() not in
           ("clk", "clock", "reset", "rst", "enable", "en")]
    if len(clk) != 1 or len(rst) != 1 or len(din) != 1:
        return None
    if len(outs) != 1 or outs[0][1] != width:
        return None
    # require EXACTLY the pre-modification interface (clk+reset+data_in -> data_out)
    # so we never mis-fire on an already-different shape; then ADD the stated enable.
    if len(ins) != 3:
        return None
    if len(en) == 1:
        en_n = en[0]
    else:
        en_n = _enable_port_name(prompt, {n for n, _ in ins})
        if not en_n:
            return None
    import math
    log2w = int(round(math.log2(window)))
    if (1 << log2w) != window:
        return None
    aw = max(1, math.ceil(math.log2(window)))
    sumw = width + log2w                 # sum of `window` values of `width` bits
    clk_n, rst_n = clk[0], rst[0]
    in_name = din[0][0]
    out_name = outs[0][0]
    rst_active_low = rst_n.lower() in ("rst_n", "resetn", "rstn")
    rst_cond = f"!{rst_n}" if rst_active_low else rst_n
    return "\n".join([
        f"// program-SOLVED {window}-sample {width}-bit moving average (+enable);"
        f" sequential, deterministic.",
        f"module {top} (",
        f"    input  wire        {clk_n},",
        f"    input  wire        {rst_n},",
        f"    input  wire        {en_n},",
        f"    input  wire [{width-1}:0] {in_name},",
        f"    output wire [{width-1}:0] {out_name}",
        f");",
        f"    reg [{width-1}:0] memory [0:{window-1}];",
        f"    reg [{sumw-1}:0] sum;",
        f"    reg [{aw-1}:0] write_address;",
        f"    integer k;",
        f"    always @(posedge {clk_n}) begin",
        f"        if ({rst_cond}) begin",
        f"            sum <= {sumw}'d0;",
        f"            write_address <= {aw}'d0;",
        f"            for (k = 0; k < {window}; k = k + 1)",
        f"                memory[k] <= {width}'d0;",
        f"        end else if ({en_n}) begin",
        f"            sum <= sum + {in_name} - memory[write_address];",
        f"            memory[write_address] <= {in_name};",
        f"            write_address <= write_address + {aw}'d1;",
        f"        end",
        f"    end",
        f"    assign {out_name} = sum[{sumw-1}:{log2w}];",
        f"endmodule",
        "",
    ])


# =========================================================================== #
# GENERAL LAYER — the SUPPLIED CONTRACT (issue #2035, families F1 and F5)
#
# This layer is NOT a third hard-coded design. It is a declarative description
# extracted from the design INPUT alone (prompt prose + the provided context
# module HEADER), plus an emitter driven by that description and an EXECUTABLE
# SEQUENTIAL REFERENCE so the contract can be RUN against a candidate rather
# than only compared as text.
#
# Two defect classes are addressed, both of which are the same mistake:
#
#   F1  A design's OWN supplied clocked stage list or literal table is flattened
#       or replaced by "what those words usually mean". The contract records the
#       supplied stages/table and marks them OVERRIDING, and `solve()` consults
#       the contract BEFORE any conventional-meaning solver.
#
#   F5  A word-boundary transfer's byte masks, response mode or prealigned store
#       lane are taken from convention instead of from the input's own statement.
#       The contract extracts a per-beat transaction model and the FSM is emitted
#       FROM that model.
#
# DISPOSITION: ADVISORY, and deliberately so (flow-change-acceptance §5 — an
# unstated default is how gates end up unable to stop anything, so this says it
# rather than leaving it to be inferred). A refusal here does NOT stop the flow:
# `solve()` returns None, which is the routing contract this program already had,
# and `task_nature_route` hands the record to the declared `ai_backup` for that
# nature. Nothing downstream treats None as "nothing needed doing", because the
# refusal also NAMES its unresolved decisions (see `notes`), which is the §6
# degrade-loudly obligation: a decline that discloses nothing reads downstream as
# a success. There is no BLOCKING claim anywhere in this layer to prove by run.
#
# THE DISCIPLINE THAT MAKES THIS PROGRAM-FIRST RATHER THAN OVER-FITTED:
# where the input does not STRUCTURALLY specify something, the fact is appended
# to `SuppliedContract.unresolved` BY NAME and emission is refused. A program
# that silently picks the conventional meaning when the input is silent is the
# defect one level up. Nothing here keys on a design id, a prompt hash, a
# benchmark name or a copied answer.
# =========================================================================== #

_VERILOG_LITERAL_RE = re.compile(
    r"""(?xi)^\s*
      (?:(?P<w>\d+)\s*'\s*(?P<base>[bodh]))?   # optional  8'h
      \s*(?P<digits>[0-9a-fx_]+)
    \s*$""")

_BASES = {"b": 2, "o": 8, "d": 10, "h": 16}


def _parse_literal(tok: str) -> Optional[int]:
    """Parse ONE supplied literal exactly as the input wrote it: a Verilog sized
    literal (`8'hFF`, `3'b101`), a `0x`/`0b` literal, or a plain decimal. Returns
    None for anything else — including a literal carrying x/z, which is not a
    value a table row can assert. No guessing, no default."""
    t = tok.strip().strip("|").strip()
    if not t:
        return None
    low = t.lower().replace("_", "")
    if low.startswith("0x"):
        try:
            return int(low[2:], 16)
        except ValueError:
            return None
    if low.startswith("0b"):
        try:
            return int(low[2:], 2)
        except ValueError:
            return None
    m = _VERILOG_LITERAL_RE.match(t)
    if not m:
        return None
    digits = m.group("digits").lower().replace("_", "")
    if "x" in digits and not m.group("base"):
        return None
    base = _BASES.get((m.group("base") or "d").lower())
    if base is None:
        return None
    if base != 16 and "x" in digits:
        return None
    try:
        return int(digits, base)
    except ValueError:
        return None


class Stage:
    """ONE supplied pipeline stage: a named result, the expression the input
    itself gave for it, and the clock the input says it is registered on."""

    __slots__ = ("index", "name", "expr", "clock", "width")

    def __init__(self, index: int, name: str, expr: str, clock: str, width: int):
        self.index, self.name, self.expr, self.clock = index, name, expr, clock
        # The width the stage register HOLDS. It is never guessed: it is either
        # the width of the interface port of that name, or a width the input
        # states in the stage line itself. An unstated intermediate width is
        # routed to AI by name — silently reusing the input width is how a
        # supplied accumulator gets flattened.
        self.width = width

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return (f"Stage({self.index}, {self.name!r}, {self.expr!r}, "
                f"clk={self.clock!r}, w={self.width})")


class LiteralTable:
    """A literal input->output map the INPUT itself supplies.

    `overrides_conventional` is the load-bearing field: it records that these
    rows are the design's own statement and therefore outrank any conventional
    reading of the same words. `complete` records whether the supplied rows
    cover the whole input domain; when they do not, the input must also state
    what an unlisted input produces, or the gap is routed to AI by name."""

    __slots__ = ("in_port", "out_port", "in_width", "out_width", "rows",
                 "default", "overrides_conventional")

    def __init__(self, in_port: str, out_port: str, in_width: int,
                 out_width: int, rows: List[Tuple[int, int]],
                 default: Optional[int]):
        self.in_port, self.out_port = in_port, out_port
        self.in_width, self.out_width = in_width, out_width
        self.rows, self.default = rows, default
        self.overrides_conventional = True

    @property
    def complete(self) -> bool:
        return len({k for k, _ in self.rows}) == (1 << self.in_width)

    def lookup(self, value: int) -> Optional[int]:
        for k, v in self.rows:
            if k == value:
                return v
        return self.default


class BeatModel:
    """The per-beat transaction model for a word-boundary transfer (family F5),
    every field of which comes from the input's OWN statement.

      data_width        bits carried per beat
      mask_port         the byte-mask / strobe port the input names, or None
      mask_active_high  True when a mask bit ASSERTED selects the byte
      masked_write      what happens to a byte whose mask bit is deasserted:
                        'preserve' or 'zero' — stated, never assumed
      alignment         'word' when the input requires word-aligned addresses
      response_mode     'raw' when the input says the response is forwarded
                        unmodified, 'decoded' when it says it is decoded
      prealigned_store  True when the input says the initiator pre-aligns the
                        store lane, False when it says the target aligns it"""

    __slots__ = ("data_width", "mask_port", "mask_active_high", "masked_write",
                 "alignment", "response_mode", "prealigned_store", "addr_port",
                 "data_in_port", "data_out_port",
                 # sequencing — what turns a per-beat model into an FSM. All
                 # three come from the input's own statement; a partially stated
                 # handshake is a refusal, not a half-built state machine.
                 "valid_port", "ready_port", "burst_beats")

    def __init__(self, data_width: int):
        self.data_width = data_width
        self.mask_port = None
        self.mask_active_high = None
        self.masked_write = None
        self.alignment = None
        self.response_mode = None
        self.prealigned_store = None
        self.addr_port = None
        self.data_in_port = None
        self.data_out_port = None
        self.valid_port = None
        self.ready_port = None
        self.burst_beats = None

    @property
    def is_sequenced(self) -> bool:
        """True when the input states a handshake, which is what makes the
        transfer a multi-beat SEQUENCE rather than one beat per cycle."""
        return self.valid_port is not None and self.ready_port is not None

    @property
    def beat_bytes(self) -> int:
        return self.data_width // 8


class SuppliedContract:
    """The typed contract: what the INPUT structurally specifies, plus the NAMES
    of what it does not.

    `unresolved` is not a diagnostic afterthought — it is the mechanism by which
    this program refuses to guess. Any entry in it means emission is refused and
    the named decision is routed to AI."""

    __slots__ = ("clock", "reset", "reset_active_low", "stages", "tables",
                 "beat", "unresolved")

    def __init__(self):
        self.clock: Optional[str] = None
        self.reset: Optional[str] = None
        self.reset_active_low: Optional[bool] = None
        self.stages: List[Stage] = []
        self.tables: List[LiteralTable] = []
        self.beat: Optional[BeatModel] = None
        self.unresolved: List[str] = []

    # -- what the input supplied ------------------------------------------- #
    def supplies_own_behaviour(self) -> bool:
        """True when the input states its OWN stages or its OWN literal table.
        When this is True a conventional-meaning reading of the same words is
        NOT permitted to overwrite it — that is defect family F1."""
        return bool(self.stages or self.tables)

    def is_empty(self) -> bool:
        return not (self.stages or self.tables or self.beat)

    # -- the EXECUTABLE SEQUENTIAL REFERENCE -------------------------------- #
    def initial_state(self) -> Dict[str, int]:
        st: Dict[str, int] = {s.name: 0 for s in self.stages}
        for t in self.tables:
            st.setdefault(t.out_port, 0)
        return st

    def reference_step(self, state: Dict[str, int],
                       inputs: Dict[str, int]) -> Tuple[Dict[str, int], Dict[str, int]]:
        """Advance the supplied contract by ONE clock, returning (next_state,
        outputs). This is the contract's executable form: it can be RUN against a
        candidate implementation instead of only compared as text.

        This mirrors the emitted RTL exactly: a supplied literal table is
        COMBINATIONAL, so its output is visible in the same cycle, while supplied
        stages are REGISTERED, so they evaluate against the previous cycle's
        state and all advance together."""
        if inputs.get("__reset__"):
            st = self.initial_state()
            return st, dict(st)
        env: Dict[str, int] = dict(state)
        env.update(inputs)
        nxt = dict(state)
        for t in self.tables:
            src = inputs.get(t.in_port, state.get(t.in_port, 0))
            val = t.lookup(src & ((1 << t.in_width) - 1))
            if val is None:
                raise KeyError(f"table row unsupplied for {t.in_port}={src}")
            val &= (1 << t.out_width) - 1
            env[t.out_port] = val      # combinational: visible THIS cycle
            nxt[t.out_port] = val
        for s in self.stages:
            # mask to the stage's OWN width — the register in the emitted RTL is
            # exactly this wide, so the reference wraps where the hardware wraps
            nxt[s.name] = _eval_int_expr(s.expr, env) & ((1 << s.width) - 1)
        outs = dict(nxt)
        for t in self.tables:
            outs[t.out_port] = env[t.out_port]
        return nxt, outs

    def run(self, sequence: List[Dict[str, int]]) -> List[Dict[str, int]]:
        """Run the executable reference over a cycle-by-cycle input sequence."""
        state = self.initial_state()
        trace = []
        for inputs in sequence:
            state, outputs = self.reference_step(state, inputs)
            trace.append(outputs)
        return trace


_EXPR_SAFE_RE = re.compile(r"^[\w\s+\-*/%&|^~()<>!=?:\[\].']+$")


def _eval_int_expr(expr: str, env: Dict[str, int]) -> int:
    """Evaluate ONE supplied stage expression over the current environment.
    Verilog operators that mean the same thing in Python are used directly; the
    identifier set is closed over `env`, so an unknown name raises rather than
    defaulting to zero."""
    e = expr.strip().rstrip(";")
    if not _EXPR_SAFE_RE.match(e):
        raise ValueError(f"unsupported stage expression: {expr!r}")
    e = re.sub(r"(?<![<>=!])=(?!=)", "==", e)
    e = e.replace("&&", " and ").replace("||", " or ")
    for name in set(re.findall(r"[A-Za-z_]\w*", e)):
        if name not in env:
            raise KeyError(f"unknown identifier in supplied expression: {name}")
    return int(eval(e, {"__builtins__": {}}, dict(env)))  # noqa: S307 - closed env


# --------------------------------------------------------------------------- #
# EXTRACTION — from the design INPUT only (prompt prose + context HEADER).
# Never a reference body, never a golden answer, never a harness model.
# --------------------------------------------------------------------------- #
_STAGE_RE = re.compile(
    r"""(?xim)^\s*
      (?:[-*]\s*)?
      stage\s*(?P<idx>\d+)\s*[:.)\-]\s*
      (?P<name>[A-Za-z_]\w*)\s*
      (?:\[\s*(?P<hi>\d+)\s*:\s*(?P<lo>\d+)\s*\]\s*)?   # optional stated width
      (?:<=|=)\s*
      (?P<expr>[^\n;]+)
    """)

# A clause that states the stages are REGISTERED. The clock is then resolved
# STRUCTURALLY — the clause's identifiers are intersected with the recovered
# interface's real port names — rather than by counting words after a keyword,
# which picks up "on"/"the"/"edge" and silently loses the clock.
_REGISTERED_RE = re.compile(
    r"(?i)[^.\n]*\b(?:registered|clocked)\b[^.\n]*")


def _extract_stages(prompt: str, port_names: set,
                    port_widths: Optional[Dict[str, int]] = None
                    ) -> Tuple[List[Stage], Optional[str], List[str]]:
    """Recover the pipeline stages the INPUT itself enumerates, in the order it
    gives them. Returns (stages, clock, unresolved)."""
    raw = list(_STAGE_RE.finditer(prompt))
    if not raw:
        return [], None, []
    unresolved: List[str] = []
    clock = None
    # Search the prose for the registering clause with the stage-definition lines
    # REMOVED (their operand names are not clock candidates) and with wrapped
    # lines rejoined, so a clause broken across a line is still one clause.
    prose = "\n".join("" if _STAGE_RE.match(ln) else ln
                      for ln in prompt.splitlines())
    prose = re.sub(r"\n(?!\s*\n)", " ", prose)
    for cm in _REGISTERED_RE.finditer(prose):
        cands = [tok for tok in re.findall(r"[A-Za-z_]\w*", cm.group(0))
                 if tok in port_names]
        # exactly one real port named in the clause -> that is the clock the
        # input stated. Two or more is an ambiguity we must not break by picking.
        if len(set(cands)) == 1:
            clock = cands[0]
            break
        if len(set(cands)) > 1:
            unresolved.append(
                "stage_clock: the clause stating the stages are registered names "
                + str(len(set(cands))) + " interface ports, so which one clocks "
                "them is not determined by the input")
            break
    if clock is None:
        # The input enumerated stages but never said what clocks them. That is a
        # sequencing decision this program must NOT make for it.
        unresolved.append("stage_clock: the input enumerates pipeline stages but "
                          "does not state the clock they are registered on")
    stages: List[Stage] = []
    seen = set()
    for m in raw:
        idx = int(m.group("idx"))
        if idx in seen:
            unresolved.append(f"stage_order: stage {idx} is stated more than once")
            continue
        seen.add(idx)
        name = m.group("name").strip()
        widths = port_widths or {}
        if m.group("hi") is not None:
            width = abs(int(m.group("hi")) - int(m.group("lo"))) + 1
        elif name in widths:
            width = widths[name]
        else:
            unresolved.append(
                f"stage_width: stage {idx} result `{name}` is not an interface "
                f"port and the input does not state how many bits it holds")
            continue
        stages.append(Stage(idx, name, m.group("expr").strip(),
                            clock or "", width))
    stages.sort(key=lambda s: s.index)
    if stages and [s.index for s in stages] != list(range(stages[0].index,
                                                          stages[0].index + len(stages))):
        unresolved.append("stage_order: the stated stage indices are not contiguous")
    return stages, clock, unresolved


_TABLE_ROW_RE = re.compile(r"^\s*\|(?P<cells>.+)\|\s*$")


def _extract_literal_tables(prompt: str, ins: List[Port], outs: List[Port]
                            ) -> Tuple[List[LiteralTable], List[str]]:
    """Recover literal input->output maps the INPUT itself supplies, as a
    two-column table whose header names real ports of the recovered interface.

    A supplied table is the design's OWN statement of the mapping and is marked
    `overrides_conventional`. Where the rows do not cover the input domain and
    the input states no default, the gap is named, never filled."""
    in_w = {n: w for n, w in ins}
    out_w = {n: w for n, w in outs}
    tables: List[LiteralTable] = []
    unresolved: List[str] = []
    lines = prompt.splitlines()
    i = 0
    while i < len(lines):
        m = _TABLE_ROW_RE.match(lines[i])
        if not m:
            i += 1
            continue
        header = [c.strip().strip("`*") for c in m.group("cells").split("|")]
        if len(header) != 2 or header[0] not in in_w or header[1] not in out_w:
            i += 1
            continue
        in_port, out_port = header[0], header[1]
        j = i + 1
        # an optional markdown separator row
        if j < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[j]):
            j += 1
        rows: List[Tuple[int, int]] = []
        malformed = False
        while j < len(lines):
            rm = _TABLE_ROW_RE.match(lines[j])
            if not rm:
                break
            cells = [c.strip() for c in rm.group("cells").split("|")]
            if len(cells) != 2:
                malformed = True
                break
            a, b = _parse_literal(cells[0]), _parse_literal(cells[1])
            if a is None or b is None:
                malformed = True
                break
            rows.append((a, b))
            j += 1
        if malformed:
            unresolved.append(f"literal_table[{in_port}->{out_port}]: a supplied "
                              f"row is not a parseable literal pair")
            i = j + 1
            continue
        if not rows:
            i = j + 1
            continue
        keys = [k for k, _ in rows]
        if len(set(keys)) != len(keys):
            unresolved.append(f"literal_table[{in_port}->{out_port}]: the supplied "
                              f"rows state conflicting outputs for the same input")
            i = j
            continue
        dm = re.search(rf"(?i)\b(?:any\s+other|all\s+other|unlisted|otherwise|"
                       rf"default)\b[^.\n]{{0,60}}?{re.escape(out_port)}\s*"
                       rf"(?:is|=|shall\s+be|outputs?)\s*([^\s.,;]+)", prompt)
        default = _parse_literal(dm.group(1)) if dm else None
        tbl = LiteralTable(in_port, out_port, in_w[in_port], out_w[out_port],
                           rows, default)
        if not tbl.complete and default is None:
            unresolved.append(
                f"literal_table[{in_port}->{out_port}]: the supplied rows cover "
                f"{len(set(keys))} of {1 << in_w[in_port]} input values and the "
                f"input states no value for the rest")
        tables.append(tbl)
        i = j
    return tables, unresolved


def _extract_beat_model(prompt: str, ins: List[Port], outs: List[Port]
                        ) -> Tuple[Optional[BeatModel], List[str]]:
    """Recover the per-beat transaction model (family F5) from the input's OWN
    statement of beat width, byte-mask semantics, alignment and response mode.

    Every field this emitter depends on must be STATED. A byte-mask port whose
    write semantics the input never settles is the exact case that must go to
    AI by name rather than be filled in with the conventional answer."""
    t = prompt.lower()
    if not re.search(r"\b(?:per[-\s]beat|each\s+beat|beat|burst\s+transfer|"
                     r"word[-\s]boundary)\b", t):
        return None, []
    unresolved: List[str] = []
    in_w = {n: w for n, w in ins}
    out_w = {n: w for n, w in outs}

    # the beat width, stated in either order ("32-bit data bus" / "the data bus
    # is 32-bit"). Two DIFFERENT stated widths is an ambiguity, not a vote.
    widths = {int(m.group(1) or m.group(2)) for m in re.finditer(
        r"(?i)\b(\d+)[-\s]bits?\s+(?:wide\s+)?(?:data\s+)?(?:bus|beat|word|lane)\b"
        r"|\b(?:data\s+)?(?:bus|beat|word|lane)\s+(?:width\s+)?is\s+(\d+)[-\s]?bits?\b",
        prompt)}
    if not widths:
        return None, ["beat_width: the input describes beats but never states "
                      "the number of bits carried per beat"]
    if len(widths) > 1:
        return None, ["beat_width: the input states " + str(len(widths))
                      + " different beat widths " + str(sorted(widths))]
    bm = BeatModel(widths.pop())
    if bm.data_width % 8 or bm.data_width < 8:
        return None, [f"beat_width: the stated beat width {bm.data_width} is not "
                      f"a whole number of bytes, so a byte mask has no meaning"]

    # the byte mask / strobe port, if the input names one that is really a port
    mp = re.search(r"(?i)[`'\"]?(\w+)[`'\"]?\s*(?:is|as|,)?\s*(?:the\s+)?"
                   r"(?:byte\s+(?:mask|enable|strobe)|write\s+strobe)", prompt)
    if mp is None:
        mp = re.search(r"(?i)(?:byte\s+(?:mask|enable|strobe)|write\s+strobe)\s*"
                       r"(?:port\s*)?[`'\"]?(\w+)[`'\"]?", prompt)
    if mp is not None and mp.group(1) in in_w:
        bm.mask_port = mp.group(1)
        if in_w[bm.mask_port] != bm.beat_bytes:
            unresolved.append(
                f"byte_mask_width: port `{bm.mask_port}` is {in_w[bm.mask_port]} "
                f"bits but the stated {bm.data_width}-bit beat has "
                f"{bm.beat_bytes} bytes")
        if re.search(r"(?i)\bmask\s+bit[^.\n]{0,40}?\b(?:0|low|deasserted|cleared)\b"
                     r"[^.\n]{0,30}?\bselects?\b", prompt):
            bm.mask_active_high = False
        elif re.search(r"(?i)\b(?:a\s+)?(?:set|asserted|high|1)\b[^.\n]{0,40}?"
                       r"\bmask\s+bit[^.\n]{0,40}?\bselects?\b|"
                       r"\bmask\s+bit[^.\n]{0,40}?\b(?:set|asserted|high)\b"
                       r"[^.\n]{0,30}?\bselects?\b", prompt):
            bm.mask_active_high = True
        else:
            unresolved.append(
                f"byte_mask_polarity: the input names byte mask `{bm.mask_port}` "
                f"but never states which mask level selects a byte")
        if re.search(r"(?i)\b(?:unselected|masked[-\s]off|deselected)\s+bytes?"
                     r"[^.\n]{0,40}?\b(?:preserved?|retain|unchanged|untouched)\b", prompt):
            bm.masked_write = "preserve"
        elif re.search(r"(?i)\b(?:unselected|masked[-\s]off|deselected)\s+bytes?"
                       r"[^.\n]{0,40}?\b(?:zero(?:ed)?|cleared)\b", prompt):
            bm.masked_write = "zero"
        else:
            unresolved.append(
                f"byte_mask_write_semantics: the input names byte mask "
                f"`{bm.mask_port}` but never states what happens to a byte whose "
                f"mask bit is not selected")

    if re.search(r"(?i)\bword[-\s]aligned\b|\baligned\s+to\s+(?:a\s+)?word\b", prompt):
        bm.alignment = "word"
    elif re.search(r"(?i)\bunaligned\s+(?:transfers?|addresses?)\s+are\s+"
                   r"(?:permitted|allowed|supported)\b", prompt):
        bm.alignment = "none"

    if re.search(r"(?i)\bresponse\b[^.\n]{0,60}?\b(?:raw|unmodified|verbatim|"
                 r"forwarded\s+as[-\s]is)\b|\braw\s+response\s+mode\b", prompt):
        bm.response_mode = "raw"
    elif re.search(r"(?i)\bresponse\b[^.\n]{0,60}?\bdecoded\b|"
                   r"\bdecodes?\s+the\s+response\b", prompt):
        bm.response_mode = "decoded"
    elif re.search(r"(?i)\bresponse\b", prompt):
        unresolved.append("response_mode: the input mentions a response but never "
                          "states whether it is forwarded raw or decoded")

    if re.search(r"(?i)\b(?:store\s+)?(?:lane|data)\s+is\s+pre[-\s]?aligned\b|"
                 r"\binitiator\s+pre[-\s]?aligns\b", prompt):
        bm.prealigned_store = True
    elif re.search(r"(?i)\btarget\s+(?:must\s+)?aligns?\s+the\s+(?:store\s+)?lane\b|"
                   r"\blane\s+is\s+aligned\s+by\s+the\s+target\b", prompt):
        bm.prealigned_store = False
    elif re.search(r"(?i)\bstore\s+lane\b", prompt):
        unresolved.append("prealigned_store: the input mentions a store lane but "
                          "never states which side aligns it")

    # -- sequencing: the handshake and the burst length -------------------- #
    # Resolved STRUCTURALLY: a name is only taken when the prose mentions it in a
    # handshake clause AND it is a real 1-bit port of the recovered interface.
    all_w = dict(in_w)
    all_w.update(out_w)
    hs = re.search(r"(?i)[^.]*\b(?:handshake|valid|ready|accepted?|accept)\b[^.]*", prompt)
    if hs:
        toks = [t for t in re.findall(r"[A-Za-z_]\w*", hs.group(0)) if t in all_w]
        v = [t for t in toks if re.search(r"(?i)valid", t)]
        r = [t for t in toks if re.search(r"(?i)ready", t)]
        if len(set(v)) == 1 and all_w[v[0]] == 1:
            bm.valid_port = v[0]
        if len(set(r)) == 1 and all_w[r[0]] == 1:
            bm.ready_port = r[0]
        if (bm.valid_port is None) != (bm.ready_port is None):
            unresolved.append(
                "handshake_incomplete: the input describes a handshake but only "
                + ("the valid" if bm.valid_port else "the ready")
                + " side resolves to a 1-bit interface port, so when a beat is "
                  "ACCEPTED is not determined")
    lm = re.search(r"(?i)\b(?:bursts?\s+of\s+)?(\d+)[-\s]beat\s+burst|"
                   r"\bburst\s+(?:length|of)\s+(?:is\s+)?(\d+)\b|"
                   r"\bbursts?\s+of\s+(\d+)\s+beats?\b", prompt)
    if lm:
        bm.burst_beats = int(next(g for g in lm.groups() if g))
        if bm.burst_beats < 1:
            unresolved.append("burst_length: the stated burst length is not positive")
    elif re.search(r"(?i)\bburst\b", prompt):
        unresolved.append("burst_length: the input describes a burst but never "
                          "states how many beats it carries")
    if bm.burst_beats is not None and not bm.is_sequenced and not unresolved:
        unresolved.append("burst_sequencing: a burst length is stated but the "
                          "input names no handshake, so when each beat is "
                          "accepted is not determined")

    for nm, w in ins:
        if w == bm.data_width and bm.data_in_port is None:
            bm.data_in_port = nm
    for nm, w in outs:
        if w == bm.data_width and bm.data_out_port is None:
            bm.data_out_port = nm
    return bm, unresolved


def extract_contract(record: dict, ins: List[Port], outs: List[Port]
                     ) -> SuppliedContract:
    """Build the typed contract from the design INPUT alone."""
    c = SuppliedContract()
    prompt = (record.get("input") or {}).get("prompt") or ""
    names = {n for n, _ in ins} | {n for n, _ in outs}
    for n, w in ins:
        if w == 1 and n.lower() in ("clk", "clock", "i_clk", "clk_i"):
            c.clock = c.clock or n
        if w == 1 and n.lower() in ("rst", "reset", "rst_n", "resetn", "rstn",
                                    "reset_n", "i_rst", "rst_i"):
            c.reset = c.reset or n
    if c.reset is not None:
        c.reset_active_low = c.reset.lower() in ("rst_n", "resetn", "rstn", "reset_n")
    widths = {n: w for n, w in ins}
    widths.update({n: w for n, w in outs})
    stages, clk, u1 = _extract_stages(prompt, names, widths)
    c.stages = stages
    if clk:
        c.clock = clk
    tables, u2 = _extract_literal_tables(prompt, ins, outs)
    c.tables = tables
    beat, u3 = _extract_beat_model(prompt, ins, outs)
    c.beat = beat
    c.unresolved = u1 + u2 + u3
    if (c.stages or c.beat) and c.clock is None:
        c.unresolved.append("clock: the recovered interface exposes no clock port "
                            "and the input names none")
    return c


# --------------------------------------------------------------------------- #
# EMISSION — driven ONLY by the contract. No topology is chosen here that the
# contract did not carry, and nothing is emitted while `unresolved` is non-empty.
# --------------------------------------------------------------------------- #
def _decl(width: int) -> str:
    return "" if width <= 1 else f"[{width-1}:0] "


def emit_from_contract(top: str, ins: List[Port], outs: List[Port],
                       c: SuppliedContract) -> Optional[str]:
    """Emit RTL from the supplied contract, or None when the contract does not
    structurally determine it. None here means 'route to AI', and the reasons are
    already named in `c.unresolved`."""
    if c.unresolved or c.is_empty():
        return None
    if c.clock is None or c.reset is None:
        return None
    rst = f"!{c.reset}" if c.reset_active_low else c.reset
    out_w = {n: w for n, w in outs}
    body: List[str] = []
    decls = ([f"input  wire {_decl(w)}{n}" for n, w in ins]
             + [f"output {'reg ' if _is_driven_sequentially(n, c) else 'wire'} "
                f"{_decl(w)}{n}" for n, w in outs])
    body.append(f"module {top} (")
    for k, d in enumerate(decls):
        body.append("    " + d + ("," if k < len(decls) - 1 else ""))
    body.append(");")

    # -- literal tables: the SUPPLIED rows, verbatim, overriding convention --- #
    for t in c.tables:
        body.append(f"    // supplied literal map {t.in_port} -> {t.out_port} "
                    f"({len(t.rows)} stated rows); the input's own statement "
                    f"overrides any conventional reading")
        reg = t.out_port in out_w
        if not reg:
            body.append(f"    reg {_decl(t.out_width)}{t.out_port};")
        body.append(f"    always @(*) begin")
        body.append(f"        case ({t.in_port})")
        for k, v in t.rows:
            body.append(f"            {t.in_width}'d{k}: {t.out_port} = "
                        f"{t.out_width}'d{v};")
        if t.default is not None:
            body.append(f"            default: {t.out_port} = "
                        f"{t.out_width}'d{t.default};")
        body.append(f"        endcase")
        body.append(f"    end")

    # -- stages: registered in the SUPPLIED order on the SUPPLIED clock ------- #
    if c.stages:
        for s in c.stages:
            if s.name not in out_w:
                body.append(f"    reg {_decl(s.width)}{s.name};")
        body.append(f"    always @(posedge {c.clock}) begin")
        body.append(f"        if ({rst}) begin")
        for s in c.stages:
            body.append(f"            {s.name} <= 0;")
        body.append(f"        end else begin")
        for s in c.stages:
            body.append(f"            // stage {s.index}, as supplied")
            body.append(f"            {s.name} <= {s.expr};")
        body.append(f"        end")
        body.append(f"    end")

    if c.beat is not None:
        seg = _emit_beat_fsm(c, ins, outs, rst)
        if seg is None:
            return None
        body.extend(seg)
    body.append("endmodule")
    body.append("")
    return "\n".join(body)


def _is_driven_sequentially(name: str, c: SuppliedContract) -> bool:
    if any(s.name == name for s in c.stages):
        return True
    if any(t.out_port == name for t in c.tables):
        return True
    if c.beat is not None and name in (c.beat.data_out_port,):
        return True
    return False


def _emit_beat_fsm(c: SuppliedContract, ins: List[Port], outs: List[Port],
                   rst: str) -> Optional[List[str]]:
    """Emit the per-beat transfer FSM FROM the contract's beat model. Every
    branch below is taken from a STATED field; there is no conventional default
    anywhere in this function, because an unstated field already put a name into
    `unresolved` and stopped emission before we got here."""
    b = c.beat
    if b.data_in_port is None or b.data_out_port is None:
        return None
    if b.mask_port is not None and (b.mask_active_high is None
                                    or b.masked_write is None):
        return None
    lines: List[str] = []
    lines.append(f"    // per-beat transaction model recovered from the input: "
                 f"{b.data_width}-bit beat ({b.beat_bytes} bytes)"
                 + (f", byte mask `{b.mask_port}` active-"
                    f"{'high' if b.mask_active_high else 'low'}, unselected bytes "
                    f"{'preserved' if b.masked_write == 'preserve' else 'zeroed'}"
                    if b.mask_port else "")
                 + (f", {b.alignment}-aligned" if b.alignment else "")
                 + (f", {b.response_mode} response" if b.response_mode else "")
                 + (f", store lane pre-aligned by the "
                    f"{'initiator' if b.prealigned_store else 'target'}"
                    if b.prealigned_store is not None else ""))
    def lane_writes(indent: str) -> List[str]:
        """The masked write, one statement per byte lane, exactly as stated."""
        out = []
        for i in range(b.beat_bytes):
            hi, lo = 8 * i + 7, 8 * i
            if b.mask_port is None:
                sel = "1'b1"
            else:
                sel = (f"{b.mask_port}[{i}]" if b.mask_active_high
                       else f"~{b.mask_port}[{i}]")
            keep = (f"{b.data_out_port}[{hi}:{lo}]" if b.masked_write == "preserve"
                    else "8'h00")
            out.append(f"{indent}{b.data_out_port}[{hi}:{lo}] <= {sel} ? "
                       f"{b.data_in_port}[{hi}:{lo}] : {keep};")
        return out

    if not b.is_sequenced:
        # UNSEQUENCED: the input states one beat per cycle and names no
        # handshake, so there is no sequence to step through and a state machine
        # would be a state machine the input never asked for.
        lines.append(f"    // unsequenced: one beat per cycle, no handshake stated")
        lines.append(f"    always @(posedge {c.clock}) begin")
        lines.append(f"        if ({rst}) begin")
        lines.append(f"            {b.data_out_port} <= 0;")
        lines.append(f"        end else begin")
        lines.extend(lane_writes("            "))
        lines.append(f"        end")
        lines.append(f"    end")
        return lines

    # SEQUENCED: the input states a handshake, so beats are ACCEPTED rather than
    # taken every cycle, and the transfer is a sequence with a response phase.
    # Every state below exists because the input named the fact that creates it.
    n = b.burst_beats
    cw = max(1, (n - 1).bit_length()) if n else 1
    has_resp = b.response_mode is not None
    accept = f"{b.valid_port} && {b.ready_port}"
    lines.append(f"    // SEQUENCED per-beat FSM: handshake `{b.valid_port}`/"
                 f"`{b.ready_port}`"
                 + (f", {n}-beat burst" if n else "")
                 + (f", {b.response_mode} response phase" if has_resp else ""))
    lines.append(f"    localparam S_IDLE = 2'd0, S_BEAT = 2'd1"
                 + (", S_RESP = 2'd2;" if has_resp else ";"))
    lines.append(f"    reg [1:0] state;")
    lines.append(f"    reg [{cw-1}:0] beat_index;")
    lines.append(f"    always @(posedge {c.clock}) begin")
    lines.append(f"        if ({rst}) begin")
    lines.append(f"            state <= S_IDLE;")
    lines.append(f"            beat_index <= {cw}'d0;")
    lines.append(f"            {b.data_out_port} <= 0;")
    lines.append(f"        end else begin")
    lines.append(f"            case (state)")
    lines.append(f"            S_IDLE: if ({accept}) begin")
    lines.extend(lane_writes("                "))
    if n and n > 1:
        lines.append(f"                beat_index <= {cw}'d1;")
        lines.append(f"                state <= S_BEAT;")
    else:
        lines.append(f"                state <= "
                     + ("S_RESP;" if has_resp else "S_IDLE;"))
    lines.append(f"            end")
    lines.append(f"            S_BEAT: if ({accept}) begin")
    lines.extend(lane_writes("                "))
    if n and n > 1:
        lines.append(f"                if (beat_index == {cw}'d{n-1}) begin")
        lines.append(f"                    beat_index <= {cw}'d0;")
        lines.append(f"                    state <= "
                     + ("S_RESP;" if has_resp else "S_IDLE;"))
        lines.append(f"                end else begin")
        lines.append(f"                    beat_index <= beat_index + {cw}'d1;")
        lines.append(f"                end")
    else:
        lines.append(f"                state <= "
                     + ("S_RESP;" if has_resp else "S_IDLE;"))
    lines.append(f"            end")
    if has_resp:
        # the response phase exists because the input STATED a response mode;
        # `raw` forwards the beat unmodified, `decoded` is the other stated form.
        lines.append(f"            S_RESP: begin")
        lines.append(f"                // {b.response_mode} response, as stated")
        lines.append(f"                state <= S_IDLE;")
        lines.append(f"            end")
    lines.append(f"            default: state <= S_IDLE;")
    lines.append(f"            endcase")
    lines.append(f"        end")
    lines.append(f"    end")
    return lines


# =========================================================================== #
# public API
# =========================================================================== #
def solve(record: dict, notes: Optional[List[str]] = None) -> Optional[str]:
    """CVDP-record entry. Recover the interface from the context HEADER (never a
    body) + the harness TOPLEVEL, and emit RTL.

    PRECEDENCE (issue #2035, family F1). The SUPPLIED CONTRACT is consulted
    FIRST. When the design INPUT states its own clocked stages or its own literal
    table, that statement governs and the conventional-meaning solvers below are
    NOT permitted to overwrite it — replacing a supplied table with "what those
    words usually mean" is the defect, not the fallback. When the input supplies
    its own behaviour but does not structurally settle it, this returns None and
    the unresolved decisions are named in `notes`, to be routed to AI. It never
    silently substitutes the conventional reading.

    `notes`, when a list is passed, receives the named unresolved decisions.
    None on any ambiguity / non-matching shape.

    ADVISORY, not blocking: None routes the record to this nature's declared AI
    backup; it never halts the flow. Pass `notes` to see why a record declined —
    an unresolved decision is always named, never silently defaulted."""
    if not isinstance(record, dict):
        return None
    top = _toplevel(record)
    if not top:
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None
    if _NON_GEN_TASK_RE.search(prompt):
        return None

    rec_iface = _context_header_ports(record, top)
    ins = outs = None
    params: Dict[str, int] = {}
    if rec_iface is not None:
        ins, outs, params = rec_iface

    # ---- the SUPPLIED CONTRACT comes FIRST (issue #2035, families F1/F5) ---- #
    # A design that states its own stages or its own literal table has already
    # said what it means; a conventional reading of the same words must not
    # override it. Where the input supplies behaviour but leaves a structural
    # decision open, we refuse and NAME it rather than guessing.
    if ins and outs:
        contract = extract_contract(record, ins, outs)
        if notes is not None:
            notes.extend(contract.unresolved)
        if contract.supplies_own_behaviour() or contract.beat is not None:
            rtl = emit_from_contract(top, ins, outs, contract)
            if rtl is not None:
                return rtl
            if contract.supplies_own_behaviour():
                # The input DID state its own behaviour, so falling through to a
                # conventional-meaning solver here would reintroduce exactly the
                # defect this precedence exists to stop. Route to AI instead.
                return None

    # (C) convolutional encoder — interface may come from the harness (no context
    # skeleton in this record), so fall back to the bridge interface for it.
    conv = _is_conv_encoder(prompt)
    if conv is not None:
        if ins is None or outs is None:
            try:
                import record_prompt_context_bridge as _bridge
                bi = _bridge.extract_interface(record, top)
                if bi:
                    ins, outs = bi
            except Exception:
                pass
        if ins and outs:
            return _emit_conv_encoder(record, top, ins, outs, conv[0], conv[1])
        return None

    # (M) requires the context skeleton header (a "modify/enhance" record always
    # ships the prior RTL as input.context — header is the interface). The FUNCTION
    # is fully stated in the prompt + the input.context DOCUMENTATION; the only
    # interface change (the new `enable` input) is stated in the prompt prose.
    if ins is None or outs is None:
        return None

    ma = _is_moving_average_enable(prompt)
    if ma is not None:
        return _emit_moving_average(record, top, ins, outs, ma[0], ma[1], prompt)

    return None


def explain(record: dict) -> Dict[str, object]:
    """Why did `solve()` decline this record? — the §6 degrade-loudly channel.

    `solve(record, notes)` discloses only when the caller already knows to pass
    `notes`, and its default is silent. This is the pure, first-class way to ask
    instead: any caller, including the AI backup that receives the record, can
    obtain the contract this program recovered and the decisions the input left
    open, WITHOUT the emit path having to carry mutable state (this module
    declares itself pure and deterministic, so a module-level record is not
    available to it).

    Returns a dict that always answers three questions: whether the input
    supplied its own behaviour, what was recovered, and what is unresolved. It
    never guesses, and `reason` distinguishes "the input settles this" from
    "nothing here for this program to do"."""
    out: Dict[str, object] = {"emitted": False, "supplies_own_behaviour": False,
                              "stages": 0, "tables": 0, "beat": False,
                              "unresolved": [], "reason": ""}
    if not isinstance(record, dict):
        out["reason"] = "record is not a dict"
        return out
    top = _toplevel(record)
    if not top:
        out["reason"] = "no harness TOPLEVEL could be recovered"
        return out
    iface = _context_header_ports(record, top)
    if iface is None:
        out["reason"] = ("no parseable module header for `%s` in input.context, "
                         "so no interface could be recovered" % top)
        return out
    ins, outs, _ = iface
    c = extract_contract(record, ins, outs)
    out["supplies_own_behaviour"] = c.supplies_own_behaviour()
    out["stages"], out["tables"] = len(c.stages), len(c.tables)
    out["beat"] = c.beat is not None
    out["unresolved"] = list(c.unresolved)
    notes: List[str] = []
    out["emitted"] = solve(record, notes) is not None
    if out["emitted"]:
        out["reason"] = "the input structurally determines this design"
    elif c.unresolved:
        out["reason"] = ("the input supplies behaviour but leaves %d decision(s) "
                         "open; they are named in `unresolved`" % len(c.unresolved))
    elif c.is_empty():
        out["reason"] = ("the input supplies no stages, no literal table and no "
                         "per-beat model, so this layer claims nothing")
    else:
        out["reason"] = "the recovered contract does not determine an emission"
    return out


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
    for r in recs:
        if a.id and r.get("id") != a.id:
            continue
        rtl = solve(r)
        if rtl:
            n += 1
            if a.emit or a.id:
                print(f"=== {r.get('id')} ===")
                print(rtl)
    print(f"emitted={n}/{len(recs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
