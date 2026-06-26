#!/usr/bin/env python3
"""compose_synth.py — a CVDP DECOMPOSE -> SOLVE-EACH -> COMPOSE engine.

WHY (owner directive 2026-06-23): a composite CVDP "code generation" design is a
TOP that instantiates atomic sub-blocks + glue. The cocotb scorer tests the WHOLE
top's function. So if we (1) PARSE the structure from the prompt prose / skeleton
HEADER / harness interface, (2) SOLVE each sub-block with the existing atomic
solvers (cvdp_atomic_bridge + the cvdp_*_synth family), and (3) EMIT the wired top
(sub-module defs + a top that instantiates + wires them), the harness passes — WITHOUT
ever reconstructing a custom algorithm. This is the COMPOSE counterpart to the atomic
bridge: the bridge solves ONE atomic module; this engine solves a STRUCTURED top whose
function is (atomic core) + (deterministic glue the prose fully specifies).

SCOPE (start with the SIMPLEST pattern that yields real, verified solves — per the
directive "get that correct + verified before adding patterns"):

  (a) THIN-WRAPPER — the top is a registered / fixed-latency wrapper around ONE atomic
      combinational core, where the prose fully and unambiguously specifies:
        * the atomic core's function (a reduction/arith the registry can emit:
          a sum/`+`-reduction of N flattened elements, today),
        * the wrapper plumbing: a FIXED total latency of K clock cycles (input
          register + combinational core + output register), a reset (async/sync, the
          polarity stated), and a valid pipeline (i_valid delayed K cycles -> o_valid).
      The emitted top is: input-latch reg -> the atomic core (combinational) ->
      output-latch reg, with a K-deep valid shift. Every emitted fact is grounded in
      the prose; nothing is guessed.

  Patterns (b) PIPELINE / (c) CONTROLLER+DATAPATH / (d) PARALLEL-COMPOSE are recognized
  as NON-(a) and SKIPped for now (the registry has no general iterative-datapath or
  per-stage-register-insertion template yet; emitting one would risk a wrong function).

§4.05 PARSE-or-SKIP / NO-CHEAT (binding):
  * NEVER read the golden/reference RTL. `output['context']` is the EMPTY answer slot
    in CVDP v1.1.0; `input['context']` may hold a buggy/partial skeleton — we parse ONLY
    its `module ... ( ... );` HEADER (ports/params), NEVER its body logic. The function
    is reconstructed ONLY from the prompt prose; the body is never copied.
  * SKIP (return None) unless the structure is UNAMBIGUOUSLY parseable AND every
    sub-block is atomic-solvable AND the wrapper plumbing (latency / reset / valid) is
    explicitly stated. Never guess a width, a latency, a reset polarity, or a wiring.
  * A novel algorithm / protocol / bus / memory / FIFO / cache / FSM-with-custom-datapath
    top is NOT decomposable -> SKIP.

API: solve(record: dict) -> Optional[str]   # emitted structural RTL (top == TOPLEVEL) | None
chip-AGNOSTIC (no design-name keys), pure-function, deterministic.

DISPATCH NOTE (for the maintainer to wire — do NOT self-edit the bridge):
  Registered in spec_artifact_registry._RECORD_SOLVER_NAMES (the unified dispatch)
  (it is parse-or-SKIP, so it only contributes on a clean composite and is otherwise a
  no-op). Try it AFTER the atomic family solvers so a pure-atomic record is solved atomically.
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import cvdp_atomic_bridge as _bridge  # reuse harness/.env access + composite SKIP cues


# --------------------------------------------------------------------------- #
# Harness / prompt access (delegated to the bridge where it already exists)
# --------------------------------------------------------------------------- #
def _prompt(record: dict) -> str:
    return (record.get("input") or {}).get("prompt") or ""


def _toplevel(record: dict) -> Optional[str]:
    return _bridge.toplevel_name(record)


def _skeleton_header(record: dict, top: str) -> Optional[str]:
    """The `module <top> #(...) ( ... );` HEADER text from input['context'] OR the
    prompt's embedded ```verilog module ...``` block. HEADER ONLY — never any body.
    Returns the parenthesised port-list text, or None."""
    # input['context'] skeleton (header only).
    ic = (record.get("input") or {}).get("context") or {}
    sources = [v for v in ic.values() if isinstance(v, str)]
    # the prompt may embed the partial module header in a fenced block.
    sources.append(_prompt(record))
    for text in sources:
        for m in re.finditer(
                r"module\s+(\w+)\s*(?:#\s*\(.*?\)\s*)?\((.*?)\)\s*;", text, re.S):
            if m.group(1) == top:
                return m.group(2)
    return None


# --------------------------------------------------------------------------- #
# Parameters (default values) — needed to size parametric ports unambiguously
# --------------------------------------------------------------------------- #
def _params(record: dict, top: str) -> Dict[str, int]:
    """Integer parameter defaults from the `module <top> #( parameter X = V, ... )`
    block (skeleton HEADER or the prompt's prose `**X** (default = V)`). Only plain
    integer defaults are captured — a parameter whose default is itself an expression
    of another parameter (e.g. NUM_STAGES = $clog2(IN_DATA_NS)) is computed lazily by
    the width evaluator, not stored here."""
    params: Dict[str, int] = {}
    ic = (record.get("input") or {}).get("context") or {}
    blob = "\n".join(v for v in ic.values() if isinstance(v, str)) + "\n" + _prompt(record)
    # `parameter [type] NAME = <int>` in the module #(...) block.
    for m in re.finditer(
            r"\bparameter\b\s+(?:int\b|logic\b[^=,)]*|integer\b|signed\b|unsigned\b|\[[^\]]*\]\s*)?\s*"
            r"(\w+)\s*=\s*([0-9]+)\b", blob):
        params.setdefault(m.group(1), int(m.group(2)))
    # prose form: **`NAME`** (default = 16) / `NAME` (default 16)
    for m in re.finditer(r"`?(\w+)`?\s*\(default\s*=?\s*([0-9]+)\)", blob):
        params.setdefault(m.group(1), int(m.group(2)))
    return params


# --------------------------------------------------------------------------- #
# Width-expression evaluator (parametric forms the bridge can't size)
# --------------------------------------------------------------------------- #
def _eval_width_expr(expr: str, params: Dict[str, int]) -> Optional[int]:
    """Evaluate a Verilog width expression like `IN_DATA_WIDTH*IN_DATA_NS-1 : 0`'s
    msb+1, or `(IN_DATA_WIDTH + $clog2(IN_DATA_NS))-1`. Supports + - * and $clog2 only,
    over known integer params. Returns the bit-count (msb-lsb+1) or None if it can't be
    resolved deterministically."""
    m = re.match(r"\s*\[\s*(.+?)\s*:\s*(.+?)\s*\]\s*$", expr)
    if not m:
        return None
    hi_s, lo_s = m.group(1), m.group(2)

    def _ev(s: str) -> Optional[int]:
        s = s.strip()
        # $clog2(<inner>)
        def _clog2(mm):
            inner = _ev(mm.group(1))
            if inner is None or inner < 1:
                return None
            return str(max(1, math.ceil(math.log2(inner)) if inner > 1 else 1))
        prev = None
        cur = s
        # iteratively resolve $clog2(...) with a balanced-by-regex simple inner (no nesting of clog2)
        while "$clog2" in cur and cur != prev:
            prev = cur
            cur = re.sub(r"\$clog2\s*\(\s*([^()]+?)\s*\)", lambda mm: _clog2(mm) or "<<ERR>>", cur)
            if "<<ERR>>" in cur:
                return None
        # substitute params (word-boundary), leave numbers
        def _sub(mm):
            tok = mm.group(0)
            if tok in params:
                return str(params[tok])
            return tok
        cur = re.sub(r"[A-Za-z_]\w*", _sub, cur)
        # any remaining identifier => unresolved
        if re.search(r"[A-Za-z_]", cur):
            return None
        # only digits, + - * ( ) and spaces now -> safe arithmetic eval
        if not re.fullmatch(r"[0-9+\-*()\s]+", cur):
            return None
        try:
            return int(eval(cur, {"__builtins__": {}}, {}))  # noqa: S307 sanitized above
        except Exception:
            return None

    hi = _ev(hi_s)
    lo = _ev(lo_s)
    if hi is None or lo is None:
        return None
    return abs(hi - lo) + 1


# --------------------------------------------------------------------------- #
# Port parse from the skeleton HEADER (directions + parametric widths)
# --------------------------------------------------------------------------- #
PortDecl = Tuple[str, str, Optional[str]]  # (direction, name, raw-range-or-None)


def _header_ports(header: str) -> List[PortDecl]:
    """Parse (direction, name, raw_range) tuples from a module header port list.
    Keeps the RAW `[ ... : ... ]` range string so the width evaluator can resolve
    parametric expressions later. Header text only."""
    out: List[PortDecl] = []
    # split on commas that separate declarations (ranges have no top-level commas here
    # because a Verilog range uses ':', not ','); a simple comma split is safe for the
    # ANSI port list dialect CVDP uses.
    for piece in re.split(r",(?![^\[]*\])", header):
        piece = piece.strip()
        m = re.match(
            r"(input|output|inout)\s+(?:wire\s+|reg\s+|logic\s+)?(?:signed\s+|unsigned\s+)?"
            r"(\[[^\]]*\])?\s*(\w+)\s*$", piece)
        if not m:
            continue
        direction, rng, name = m.group(1), m.group(2), m.group(3)
        out.append((direction, name, rng))
    return out


def _prose_ports(record: dict, top: str) -> List[PortDecl]:
    """Parse ports from the prompt's prose `## Input Ports:` / `## Output Ports:`
    bullet lists (the CVDP code-gen dialect when there is no fenced Verilog header).
    Each bullet is `- \\`name\\` [<range>]: <desc>`. Returns (direction, name, raw_range)
    with backticks stripped from the range so the parametric width evaluator can read it.
    PROSE ONLY — no body, no golden RTL."""
    prompt = _prompt(record)
    out: List[PortDecl] = []
    # locate Input/Output sections by a markdown header containing 'Input ports' /
    # 'Output ports' (any heading depth, case-insensitive).
    secs = []
    for m in re.finditer(r"(?im)^\s*#{0,6}\s*\**\s*(input|output)\s+ports?\b.*$", prompt):
        secs.append((m.start(), m.group(1).lower()))
    if not secs:
        return out
    secs.append((len(prompt), None))
    for i in range(len(secs) - 1):
        start, direction = secs[i]
        end = secs[i + 1][0]
        block = prompt[start:end]
        for bm in re.finditer(
                r"(?m)^\s*[-*]\s*`?(\w+)`?\s*(\[[^\]]*\])?\s*[:.-]", block):
            name = bm.group(1)
            rng = bm.group(2)
            if rng:
                # strip markdown ticks/bold but PRESERVE the '*' multiply operator.
                rng = rng.replace("`", "")
                rng = re.sub(r"\*\*", "", rng)  # bold markers only (a real op is single '*')
            out.append((direction, name, rng))
    return out


# --------------------------------------------------------------------------- #
# THIN-WRAPPER recognizer: a fixed-latency registered wrapper around an
# N-element SUM reduction of a flattened input vector.
# --------------------------------------------------------------------------- #
_SEQ_CTRL = {"clk", "clock", "rst", "reset", "rstn", "rst_n", "resetn", "reset_n",
             "areset", "aresetn", "srst"}


def _is_valid_in(n: str) -> bool:
    return bool(re.fullmatch(r"(?i)i_?valid|valid_i|in_?valid|valid_in|s_?valid", n))


def _is_valid_out(n: str) -> bool:
    return bool(re.fullmatch(r"(?i)o_?valid|valid_o|out_?valid|valid_out|m_?valid", n))


def _stated_latency(prompt: str) -> Optional[int]:
    """A FIXED total latency in clock cycles, only when the prose states it explicitly.
    Returns the integer, or None (=> SKIP, never guess)."""
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    pats = [
        r"(?xi)\b(?:total\s+)?latency\s+of\s+(two|three|four|five|one|\d+)\s+clock\s+cycles?",
        r"(?xi)\bintroduces?\s+a\s+(?:total\s+)?latency\s+of\s+(two|three|four|five|one|\d+)\s+clock",
        r"(?xi)\bfixed\s+latency\s+of\s+\*{0,2}(two|three|four|five|one|\d+)\s+clock",
        r"(?xi)\b(two|three|four|five|one|\d+)[-\s]clock[-\s]cycle\s+latency",
    ]
    found = set()
    for pat in pats:
        for m in re.finditer(pat, prompt):
            tok = m.group(1).lower()
            found.add(words.get(tok, int(tok) if tok.isdigit() else None))
    found.discard(None)
    if len(found) == 1:
        return found.pop()
    return None  # absent OR contradictory -> SKIP


def _reset_spec(prompt: str) -> Optional[Tuple[bool, bool]]:
    """(is_async, active_low) for the reset, only when stated unambiguously. None=>SKIP."""
    low = bool(re.search(r"(?xi)\bactive[-\s]?low\b.*\breset\b|\breset\b.*\bactive[-\s]?low\b|"
                         r"\bactive[-\s]?low\s+(?:asynchronous\s+)?reset\b|`?rst_?n`?|`?reset_?n`?|`?resetn`?",
                         prompt))
    high = bool(re.search(r"(?xi)\bactive[-\s]?high\b.*\breset\b|\breset\b.*\bactive[-\s]?high\b|"
                          r"\bactive[-\s]?high\s+(?:asynchronous\s+)?reset\b", prompt))
    is_async = bool(re.search(r"(?xi)\basynchronous\s+reset\b|\basync\s+reset\b|\basynchronous[,\s]", prompt))
    is_sync = bool(re.search(r"(?xi)\bsynchronous\s+reset\b|\bsync\s+reset\b", prompt))
    if low and high:
        return None  # contradictory
    if not low and not high:
        return None  # unstated polarity -> never guess
    active_low = low and not high
    if is_async and is_sync:
        return None
    # default to async only if the prose says async; if neither said, SKIP (no guess).
    if not is_async and not is_sync:
        return None
    return (is_async, active_low)


def _sum_reduction(prompt: str) -> bool:
    """The atomic core is a SUM (`+`) reduction of all input elements. Recognized only
    on explicit summation language; any other reduction/op -> not this template -> SKIP."""
    pos = re.search(r"(?xi)\b(cumulative\s+sum|sum(?:mation)?\s+of\s+(?:all\s+|the\s+|multiple\s+)?"
                    r"(?:input\s+)?(?:data\s+)?elements|sum\s+all|adds?\s+(?:up\s+)?all|"
                    r"summing\s+(?:input\s+)?(?:data\s+)?elements|total\s+sum)\b", prompt)
    if not pos:
        return False
    # exclude non-plain-sum semantics that would make `+` wrong
    if _bridge._SPECIAL_ALGEBRA_RE.search(prompt):
        return False
    # exclude products/MAC/weighted (a different core)
    if re.search(r"(?xi)\b(multipl|product|weighted|accumulat\w*\s*\*|convolution|"
                 r"dot\s+product|mac\b|filter)\b", prompt):
        return False
    return True


def _flattened_vector_input(ports: List[PortDecl], params: Dict[str, int],
                            prompt: str) -> Optional[Tuple[str, str, int, int, str]]:
    """Identify THE single flattened data-input port and resolve (name, raw_range,
    elem_width, num_elems, out_range) for the N-element sum. None => not this template."""
    # the data input is a wide bus whose width is W*N (elem_width * num_elems).
    # find the elem-width and num-elems param names from the prose, then the port whose
    # range is exactly [W*N-1:0].
    # prose pin-down of the two params:
    wname = None
    nname = None
    mw = re.search(r"(?xi)`?(\w+)`?[^.\n]*\b(?:bit[-\s]?width|width)\s+of\s+each\b", prompt)
    if mw:
        wname = mw.group(1)
    mn = re.search(r"(?xi)`?(\w+)`?[^.\n]*\bnumber\s+of\s+(?:input\s+)?(?:data\s+)?elements\b", prompt)
    if mn:
        nname = mn.group(1)
    if not (wname and nname and wname in params and nname in params):
        return None
    elem_w = params[wname]
    n_elem = params[nname]
    if elem_w < 1 or n_elem < 2:
        return None
    # the data input port: an `input` whose evaluated width == elem_w * n_elem.
    data_port = None
    for direction, name, rng in ports:
        if direction != "input" or rng is None:
            continue
        if name.lower() in _SEQ_CTRL or _is_valid_in(name):
            continue
        w = _eval_width_expr(rng, params)
        if w == elem_w * n_elem:
            data_port = (name, rng)
            break
    if not data_port:
        return None
    # the output sum width must be W + clog2(N) (no overflow). Confirm from the output port.
    out_port = None
    for direction, name, rng in ports:
        if direction != "output" or rng is None or _is_valid_out(name):
            continue
        w = _eval_width_expr(rng, params)
        if w is not None:
            out_port = (name, rng, w)
            break
    if not out_port:
        return None
    expect_out_w = elem_w + (max(1, math.ceil(math.log2(n_elem))) if n_elem > 1 else 1)
    if out_port[2] != expect_out_w:
        return None
    return (data_port[0], data_port[1], elem_w, n_elem, out_port[1], wname, nname)


# --------------------------------------------------------------------------- #
# Emit: the structural top (no separate sub-module file needed for the sum core —
# the "atomic block" is a generate-unrolled `+`-reduction, emitted inline as the
# combinational core between the input and output registers, which is exactly the
# THIN-WRAPPER decomposition: regs (glue) around the adder core).
# --------------------------------------------------------------------------- #
def _emit_thin_wrapper_sum(top: str, header_ports: List[PortDecl], params: Dict[str, int],
                           data_name: str, data_rng: str, elem_w: int, n_elem: int,
                           out_name: str, out_rng: str, latency: int,
                           reset: Tuple[bool, bool], prompt: str,
                           wname: Optional[str] = None,
                           nname: Optional[str] = None) -> Optional[str]:
    """Emit a registered wrapper around an N-element `+`-reduction with a `latency`-deep
    valid pipeline and the prose-stated reset.

    Structure (general for latency L >= 2, empirically pinned against the cocotb
    measurement convention — drive at edge A, sample at edge B, count edges to o_valid):
      * input latch:  dq <= data    (when valid)
      * valid pipe:   v[1] <= valid;  v[k] <= v[k-1]  for k = 2..L;  o_valid <= v[L]
      * output latch: o_data <= sum(dq)  (when v[L-1]) and then HELD
    This yields cocotb-measured latency == L with the correct sum. L < 2 cannot be
    realized by a register-in + combinational-core + register-out wrapper -> SKIP."""
    if latency < 2:
        return None
    is_async, active_low = reset
    # locate clk / reset / valid_in / valid_out port names from the parsed interface
    # (no name guessing — they MUST all be present, else this is not a THIN-WRAPPER).
    clk = vin = vout = rstp = None
    for direction, name, _rng in header_ports:
        ln = name.lower()
        if ln in ("clk", "clock"):
            clk = name
        elif ln in _SEQ_CTRL and ln not in ("clk", "clock"):
            rstp = name
        elif direction == "input" and _is_valid_in(name):
            vin = name
        elif direction == "output" and _is_valid_out(name):
            vout = name
    if not (clk and rstp and vin and vout):
        return None

    # GENERAL parameterization (§9 GENERAL-not-OVERFIT): the cocotb harness sweeps
    # IN_DATA_WIDTH / IN_DATA_NS via `-P<top>.NAME=...`, so the element width, element
    # count and the sum core MUST be expressed in the PARAMETER IDENTIFIERS, never the
    # baked default literals (16/4). When the names are known, emit a generate/for-loop
    # accumulator over `nname` elements of `wname` bits; otherwise fall back to literals.
    elem_w_expr = wname if (wname and wname in params) else str(elem_w)
    n_elem_expr = nname if (nname and nname in params) else str(n_elem)
    symbolic = (wname and wname in params and nname and nname in params)
    if symbolic:
        out_msb = f"({elem_w_expr} + $clog2({n_elem_expr})) - 1"
    else:
        out_msb = str(elem_w + (max(1, math.ceil(math.log2(n_elem))) if n_elem > 1 else 1) - 1)
    rst_edge = (f" or negedge {rstp}" if active_low else f" or posedge {rstp}") if is_async else ""
    rst_cond = f"!{rstp}" if active_low else f"{rstp}"
    # rebuild the ANSI port list verbatim from the parsed interface so widths/params match.
    port_lines = [f"    {direction} logic{(' ' + rng) if rng else ''} {name}"
                  for direction, name, rng in header_ports]
    ports_txt = ",\n".join(port_lines)
    param_block = ""
    if params:
        param_decls = ",\n".join(f"    parameter int {k} = {v}" for k, v in params.items())
        param_block = f"#(\n{param_decls}\n) "

    # element slices of the flattened vector: element i occupies bits [(i+1)*W-1 : i*W];
    # the sum is order-independent so the packing direction does not affect the result.
    # When parameterized, the slice count/width are unknown at emit time -> a for-loop
    # accumulator (`+: elem_w_expr` part-select with a variable base) is the GENERAL form.
    if symbolic:
        sum_core_decl = [
            f"    // combinational sum core (the atomic block being composed)",
            f"    reg [{out_msb}:0] sum_comb;",
            f"    integer _i;",
            f"    always @* begin",
            f"        sum_comb = '0;",
            f"        for (_i = 0; _i < {n_elem_expr}; _i = _i + 1)",
            f"            sum_comb = sum_comb + {data_name}_q[_i*{elem_w_expr} +: {elem_w_expr}];",
            f"    end",
        ]
    else:
        sum_terms = " + ".join(
            f"{data_name}_q[{i}*{elem_w} +: {elem_w}]" for i in range(n_elem))
        sum_core_decl = [
            f"    // combinational sum core (the atomic block being composed)",
            f"    wire [{out_msb}:0] sum_comb = {sum_terms};",
        ]
    # The THIN-WRAPPER physically realizes EXACTLY 2 cycles (input register -> combinational
    # sum core -> output register), and the cocotb harness counts edges from the edge that
    # samples i_valid to the edge after which o_valid reads 1. Under that readout convention a
    # 2-flop valid path (v1 <= i_valid; o_valid <= v1) is measured as latency 2 — verified
    # against the design's own cocotb harness across random IN_DATA_NS/IN_DATA_WIDTH sweeps.
    # The previous emit built an L-deep valid pipe AND registered o_valid from its last stage,
    # which measured L+1 (an off-by-one — the assert was `latency == 2`, got 3). A stated
    # latency other than 2 cannot be realized by this 1-in/comb/1-out wrapper, so SKIP it to
    # the gate tier rather than ship an unverified pipeline depth (§9 honesty).
    if latency != 2:
        return None

    lines = [
        f"// Auto-composed THIN-WRAPPER: a 2-cycle registered wrapper around an "
        f"{n_elem}-element '+'-reduction (the atomic core).",
        f"// Decomposition: input register (glue) -> combinational sum core (atomic) -> "
        f"output register (glue),",
        f"// with a 2-deep valid pipeline and the prose-stated reset. "
        f"Function grounded in the prompt; no body copied.",
        f"module {top} {param_block}(",
        ports_txt,
        f");",
        f"",
        f"    logic {data_rng} {data_name}_q;     // input latch (stage 1)",
        f"    logic v1;                            // valid stage 1",
        *sum_core_decl,
        f"",
        f"    always @(posedge {clk}{rst_edge}) begin",
        f"        if ({rst_cond}) begin",
        f"            {data_name}_q <= '0;",
        f"            v1 <= 1'b0;",
        f"            {out_name} <= '0;",
        f"            {vout} <= 1'b0;",
        f"        end else begin",
        f"            if ({vin}) {data_name}_q <= {data_name};",  # stage-1 input register
        f"            v1 <= {vin};",
        f"            {out_name} <= sum_comb;",                   # stage-2 output register
        f"            {vout} <= v1;",
        f"        end",
        f"    end",
        f"endmodule",
        f"",
    ]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# the compose entry point
# --------------------------------------------------------------------------- #
def solve(record: dict) -> Optional[str]:
    """Emit a wired structural top for a DECOMPOSABLE composite, or None (SKIP) on any
    ambiguity / non-atomic sub-block / novel logic. Never reads the golden RTL body."""
    if not isinstance(record, dict):
        return None
    top = _toplevel(record)
    if not top:
        return None
    prompt = _prompt(record)
    if not prompt.strip():
        return None

    # §4.05 up-front: a protocol / bus / memory / cache / FIFO / CPU / special-algebra
    # top is not a clean atomic-sub-block composite. Reuse the bridge's SKIP cues, but
    # allow the 'pipeline' token (the THIN-WRAPPER/PIPELINE families legitimately use it).
    comp = _bridge._COMPOSITE_RE.search(prompt)
    if comp and comp.group(0).strip().lower() not in ("pipeline",):
        return None
    if _bridge._SPECIAL_ALGEBRA_RE.search(prompt):
        return None

    # Ports: prefer a fenced/skeleton module HEADER (header-only); else the prose
    # `## Input Ports / ## Output Ports` bullet list. Either way it is interface-only.
    header = _skeleton_header(record, top)
    ports = _header_ports(header) if header else []
    if not ports:
        ports = _prose_ports(record, top)
    if not ports:
        return None
    params = _params(record, top)

    # --- PATTERN (a) THIN-WRAPPER: registered fixed-latency wrapper around a sum core ---
    if _sum_reduction(prompt):
        latency = _stated_latency(prompt)
        reset = _reset_spec(prompt)
        if latency is None or reset is None:
            return None  # plumbing not unambiguously stated -> SKIP
        fv = _flattened_vector_input(ports, params, prompt)
        if not fv:
            return None
        data_name, data_rng, elem_w, n_elem, out_rng, wname, nname = fv
        out_name = None
        for direction, name, rng in ports:
            if direction == "output" and not _is_valid_out(name) and rng == out_rng:
                out_name = name
                break
        if not out_name:
            return None
        return _emit_thin_wrapper_sum(
            top, ports, params, data_name, data_rng, elem_w, n_elem,
            out_name, out_rng, latency, reset, prompt, wname, nname)

    # No recognized decomposable pattern -> SKIP (patterns b/c/d not yet emitted).
    return None


def pattern_of(record: dict) -> Optional[str]:
    """Report which decomposable pattern solved this record ('thin_wrapper_sum'), or None."""
    rtl = solve(record)
    if not rtl:
        return None
    if "THIN-WRAPPER" in rtl and "'+'-reduction" in rtl:
        return "thin_wrapper_sum"
    return "composite"


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
    pats: Dict[str, int] = {}
    ids: List[str] = []
    for r in recs:
        if a.id and r.get("id") != a.id:
            continue
        rtl = solve(r)
        if rtl:
            n_emit += 1
            ids.append(r.get("id"))
            p = pattern_of(r) or "?"
            pats[p] = pats.get(p, 0) + 1
            if a.emit or a.id:
                print(f"=== {r.get('id')}  pattern={p} ===")
                print(rtl)
    print(f"emitted={n_emit}/{len(recs)}  patterns={pats}")
    print("ids=" + ",".join(ids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
