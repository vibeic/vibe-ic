#!/usr/bin/env python3
"""arithmetic_synth.py — deterministic SOLVER for the integer-ARITHMETIC family
(spec -> RTL).

A prompt in this family states a small integer-arithmetic datapath whose function
is fixed by the spec with NO hidden information: a half adder, a full adder, an
N-bit (ripple-carry) adder whose output carries the overflow/carry bit, a signed
two's-complement adder that also computes a SIGNED-overflow flag, or an
add/subtract datapath selected by a STATED control bit (optionally with a
zero-result flag). When the operation, width, signedness and control polarity are
ALL unambiguously stated, this solver reads the declared interface (via the SHARED
port_parser) plus the function-fixing prose/embedded-module and EMITS correct
synthesizable RTL; on ANY ambiguity it returns None (SKIP). A wrong adder is far
worse than an honest skip.

This is NOT the truth-table / K-map / waveform path (those encode the function as
ROWS and are owned by oracle_table_synth / kmap_*_synth / waveform_truth_table_synth),
NOR the FSM path (a serial/Mealy/Moore "2's complementer" state machine is owned by
the FSM solvers — those are sequential bit-serial machines, not a combinational
adder). This solver fires ONLY on prompts that state a direct, parallel integer
operation over its declared operands.

FORMS recognized (keyed on stated STRUCTURE, never on chip names):

  (A) HALF ADDER — "implement a half adder": exactly two 1-bit data inputs (a,b),
      a 1-bit sum output and a 1-bit carry-out output. sum=a^b, cout=a&b
      (emitted as {cout,sum}=a+b, the canonical width-2 form).

  (B) FULL ADDER — "implement a full adder": three 1-bit data inputs
      (a,b,carry-in), a 1-bit sum and a 1-bit carry-out. {cout,sum}=a+b+cin.

  (C) N-bit UNSIGNED adder WITH OVERFLOW/CARRY bit — two N-bit operands and a
      SINGLE (N+1)-bit sum output that the prompt says "includes the overflow bit"
      / "include the carry out". out = a + b  (zero-extended, the MSB is the carry).

  (D) SIGNED two's-complement adder WITH SIGNED-OVERFLOW flag — two N-bit operands,
      an N-bit sum and a 1-bit overflow output, the prompt stating BOTH "two's
      complement" AND a "(signed) overflow". s=a+b; overflow when the operands share
      a sign but the sum's sign differs:  !(a[N-1]^b[N-1]) && (a[N-1]!=s[N-1]).

  (E) ADD/SUBTRACT by a STATED control bit (optional zero flag) — a control input
      whose two polarities are EXPLICITLY mapped to add vs subtract (a Verilog
      `case(ctrl) 0: out=a+b; 1: out=a-b;` embedded in a "fix-this-buggy-module"
      prompt, or prose stating the same), two N-bit operands, an N-bit result. If a
      "*_is_zero" / zero-flag output is declared it is driven by (out == 0).

§4.05 NO-LEAK — return None unless EVERY relevant condition holds:
  * a truth/timing/waveform table or a K-map present => SKIP (table-owning path);
  * an FSM / state-machine / serial-by-bit cue (state, posedge ... case(state),
    "one bit per clock cycle", "serial", Mealy/Moore) => SKIP (FSM path);
  * a multiply / divide / modulo / shift-as-the-operation cue => SKIP (out of scope);
  * an adder whose overflow is requested but whose SIGNEDNESS is NOT stated => SKIP
    (signed vs unsigned overflow logic differ — never guess);
  * an add/subtract datapath whose control POLARITY is not explicitly mapped
    (which value adds, which subtracts) => SKIP (never guess the polarity);
  * a carry-in / borrow whose convention is not stated => SKIP;
  * port arity / widths that don't match the stated operation => SKIP;
  * Prob132-style "adder-subtractor" HEADER text that the body contradicts (the
    body is pure conditional latch logic, no +/-) => SKIP (recognizers demand the
    actual +/- structure, so the lying header never fires this path).

API: synth(prompt_text, top="TopModule") -> str | None ; plus a __main__ CLI.
chip-AGNOSTIC, pure regex over the declared interface + function-fixing prose.
Deterministic. Every fire is host-verified (iverilog vs the dataset ref+test).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import port_parser as _pp  # noqa: E402  reuse the SHARED interface reader

Port = Tuple[str, int]


# --------------------------------------------------------------------------- #
# global blocking guards — if ANY trip, the whole prompt SKIPs                 #
# --------------------------------------------------------------------------- #

# A table / K-map / waveform encodes the function as ROWS -> a DIFFERENT path.
_TABLE_OR_WAVEFORM = re.compile(
    r"""(?xi)
      \bkarnaugh\b | \bk-?map\b | \btruth\s+table\b |
      \bwaveform\b | \bsimulation\s+waveform\b |
      \bstate\s+table\b
    """,
)

# An FSM / serial-bit-stream cue means this is a state machine, not a parallel
# adder.  The "2's complementer" benchmarks (Prob088/Prob089) are Mealy/Moore FSMs
# — they MUST land on the FSM path, never here.
_FSM_OR_SERIAL = re.compile(
    r"""(?xi)
      \bfinite[-\s]state\b | \bstate\s+machine\b | \bmealy\b | \bmoore\b |
      \bone-?hot\b | \bnext[-\s]state\b |
      \bposedge\b | \bnegedge\b | \balways\s*@\s*\(\s*posedge\b |
      \bone\s+per\s+clock\s+cycle\b | \bper\s+clock\s+cycle\b |
      \bserial\b | \bbit[-\s]stream\b |
      \bcase\s*\(\s*state\b | \breg\s*(\[[^\]]*\]\s*)?state\b
    """,
)

# Operations explicitly OUT OF SCOPE for this solver (no honest deterministic
# host-verified close here without more analysis -> SKIP, documented AI-floor).
_OUT_OF_SCOPE_OP = re.compile(
    r"""(?xi)
      \bmultiplier\b | \bmultiply\b | \bmultiplication\b |
      \bdivider\b | \bdivide\b | \bdivision\b | \bmodulo\b | \bmodulus\b |
      \bbcd\b | \bbinary[-\s]coded[-\s]decimal\b |
      \bbarrel\s+shifter\b | \baccumulat
    """,
)

# clock / sequential ports => not a combinational/parallel arithmetic block here.
_SEQUENTIAL_PORTS = {"clk", "clock", "rst", "reset", "rstn", "rst_n",
                     "areset", "aresetn", "clk_en", "clken"}


def _has_blocking_guard(text: str) -> bool:
    return bool(
        _TABLE_OR_WAVEFORM.search(text)
        or _FSM_OR_SERIAL.search(text)
        or _OUT_OF_SCOPE_OP.search(text)
    )


def _is_sequential(ins: List[Port]) -> bool:
    return any(n.lower() in _SEQUENTIAL_PORTS for n, _ in ins)


# --------------------------------------------------------------------------- #
# tiny port helpers + module-header emitter                                   #
# --------------------------------------------------------------------------- #
def _by_name(ports: List[Port], *names: str) -> Optional[Port]:
    low = {n.lower(): (n, w) for n, w in ports}
    for nm in names:
        if nm.lower() in low:
            return low[nm.lower()]
    return None


def _decl(name: str, w: int, direction: str, reg: bool = False) -> str:
    kind = f"{direction} reg" if reg else direction
    if w == 1:
        return f"    {kind} {name}"
    return f"    {kind} [{w-1}:0] {name}"


def _module_header(top: str, in_decls: List[str], out_decls: List[str]) -> List[str]:
    return [f"module {top} (", ",\n".join(in_decls + out_decls), ");"]


def _emit(comment: str, top: str, in_decls, out_decls, body: List[str]) -> str:
    return "\n".join(
        [comment]
        + _module_header(top, in_decls, out_decls)
        + body
        + ["endmodule", ""]
    )


# --------------------------------------------------------------------------- #
# FORM A — half adder                                                         #
# --------------------------------------------------------------------------- #
_HALF_ADDER = re.compile(r"(?i)\bhalf[-\s]?adder\b")
# carry-out output: any of these declared names is the carry-out.
_COUT_NAMES = ("cout", "carry_out", "carryout", "co", "c_out", "carry")
_SUM_NAMES = ("sum", "s")
_CIN_NAMES = ("cin", "carry_in", "carryin", "ci", "c_in")


def _half_adder(text: str, ins, outs, top: str) -> Optional[str]:
    if not _HALF_ADDER.search(text):
        return None
    # exactly two 1-bit data inputs and (sum, cout) 1-bit outputs; no carry-in.
    if len(ins) != 2 or len(outs) != 2:
        return None
    if any(w != 1 for _, w in ins) or any(w != 1 for _, w in outs):
        return None
    s = _by_name(outs, *_SUM_NAMES)
    co = _by_name(outs, *_COUT_NAMES)
    if not s or not co or s[0] == co[0]:
        return None
    # the two data inputs must not be a carry-in (half adder has no carry-in).
    if _by_name(ins, *_CIN_NAMES):
        return None
    in_decls = [_decl(n, w, "input") for n, w in ins]
    out_decls = [_decl(n, w, "output") for n, w in outs]
    body = [f"    assign {{{co[0]}, {s[0]}}} = {ins[0][0]} + {ins[1][0]};"]
    return _emit("// program-SOLVED half adder; deterministic.",
                 top, in_decls, out_decls, body)


# --------------------------------------------------------------------------- #
# FORM B — full adder                                                         #
# --------------------------------------------------------------------------- #
_FULL_ADDER = re.compile(r"(?i)\bfull[-\s]?adder\b")


def _full_adder(text: str, ins, outs, top: str) -> Optional[str]:
    # a *4-bit adder built from full adders* (Prob016) is NOT this scalar form;
    # that is FORM C — require a carry-in input to distinguish a true 1-bit FA.
    if not _FULL_ADDER.search(text):
        return None
    if len(ins) != 3 or len(outs) != 2:
        return None
    if any(w != 1 for _, w in ins) or any(w != 1 for _, w in outs):
        return None
    cin = _by_name(ins, *_CIN_NAMES)
    if not cin:
        return None
    # the other two inputs are the addends.
    addends = [n for n, _ in ins if n != cin[0]]
    if len(addends) != 2:
        return None
    s = _by_name(outs, *_SUM_NAMES)
    co = _by_name(outs, *_COUT_NAMES)
    if not s or not co or s[0] == co[0]:
        return None
    in_decls = [_decl(n, w, "input") for n, w in ins]
    out_decls = [_decl(n, w, "output") for n, w in outs]
    body = [f"    assign {{{co[0]}, {s[0]}}} = "
            f"{addends[0]} + {addends[1]} + {cin[0]};"]
    return _emit("// program-SOLVED full adder; deterministic.",
                 top, in_decls, out_decls, body)


# --------------------------------------------------------------------------- #
# FORM C — N-bit UNSIGNED adder whose (N+1)-bit output INCLUDES the carry bit  #
# --------------------------------------------------------------------------- #
# the prompt must say the sum output carries the overflow/carry bit explicitly.
_OVERFLOW_BIT_IN_SUM = re.compile(
    r"""(?xi)
      sum\s+should\s+include\s+the\s+overflow\s+bit |
      include\s+the\s+(?:overflow|carry(?:[-\s]out)?)\s+bit |
      output\s+(?:should\s+)?includes?\s+the\s+(?:overflow|carry) |
      \(?n\+1\)?[-\s]?bit\s+(?:sum|result)\s+(?:to\s+)?include
    """,
)
# the prompt must say "add" (and must NOT request a separate signed overflow flag,
# which is FORM D).
_ADD_VERB = re.compile(r"(?i)\badder\b|\badd\b|\badd\s+these\s+numbers\b")


def _nbit_unsigned_adder_with_carry(text: str, ins, outs, top: str) -> Optional[str]:
    if not _OVERFLOW_BIT_IN_SUM.search(text):
        return None
    if not _ADD_VERB.search(text):
        return None
    # exactly two N-bit operands and ONE (N+1)-bit output.
    if len(ins) != 2 or len(outs) != 1:
        return None
    (a, aw), (b, bw) = ins[0], ins[1]
    if aw < 1 or aw != bw:
        return None
    out_name, out_w = outs[0]
    if out_w != aw + 1:
        return None  # the single output must be exactly one wider (carry in MSB)
    # signed-overflow FLAG style (separate 1-bit overflow + N-bit sum) is FORM D.
    in_decls = [_decl(n, w, "input") for n, w in ins]
    out_decls = [_decl(out_name, out_w, "output")]
    body = [f"    assign {out_name} = {a} + {b};"]
    return _emit("// program-SOLVED N-bit unsigned adder (carry in MSB); "
                 "deterministic.", top, in_decls, out_decls, body)


# --------------------------------------------------------------------------- #
# FORM D — SIGNED two's-complement adder + SIGNED-overflow flag               #
# --------------------------------------------------------------------------- #
_TWOS_COMPLEMENT = re.compile(
    r"(?xi)\btwo'?s?[-\s]complement\b | \b2'?s?[-\s]complement\b")
_SIGNED_OVERFLOW = re.compile(
    r"(?xi)\(?\s*signed\s*\)?\s*overflow | signed\s+overflow | overflow\s+has\s+occurred")
_OVERFLOW_NAMES = ("overflow", "ovf", "of", "overflow_flag")


def _signed_adder_with_overflow(text: str, ins, outs, top: str) -> Optional[str]:
    # require BOTH the two's-complement statement AND a signed-overflow request.
    if not (_TWOS_COMPLEMENT.search(text) and _SIGNED_OVERFLOW.search(text)):
        return None
    if len(ins) != 2 or len(outs) != 2:
        return None
    (a, aw), (b, bw) = ins[0], ins[1]
    if aw < 2 or aw != bw:
        return None
    # one N-bit sum output + one 1-bit overflow output.
    ovf = _by_name(outs, *_OVERFLOW_NAMES)
    if not ovf or ovf[1] != 1:
        return None
    sum_out = [(n, w) for n, w in outs if n != ovf[0]]
    if len(sum_out) != 1:
        return None
    s, sw = sum_out[0]
    if sw != aw:
        return None  # the sum is the SAME width (carry is captured by the flag)
    msb = aw - 1
    in_decls = [_decl(n, w, "input") for n, w in ins]
    out_decls = [_decl(s, sw, "output"), _decl(ovf[0], 1, "output")]
    body = [
        f"    assign {s} = {a} + {b};",
        # signed overflow: operands share a sign but the result's sign differs.
        f"    assign {ovf[0]} = (~({a}[{msb}] ^ {b}[{msb}])) "
        f"& ({a}[{msb}] ^ {s}[{msb}]);",
    ]
    return _emit("// program-SOLVED signed two's-complement adder + signed-overflow "
                 "flag; deterministic.", top, in_decls, out_decls, body)


# --------------------------------------------------------------------------- #
# FORM E — add/subtract by a STATED control bit (optional zero flag)          #
# --------------------------------------------------------------------------- #
# An embedded Verilog `case(ctrl) 0: out = a+b; 1: out = a-b;` (or the reverse
# polarity) pins BOTH the control signal AND the polarity explicitly. We parse
# the case arms structurally; we never guess which polarity adds.
_CASE_HEADER = re.compile(r"(?i)case\s*\(\s*(\w+)\s*\)")
# an arm:  `<value> : <lhs> = <a> <op> <b> ;`  with op in {+,-}.
_CASE_ARM = re.compile(
    r"(?im)^\s*(?P<val>[01])\s*:\s*(?P<lhs>\w+)\s*=\s*"
    r"(?P<x>\w+)\s*(?P<op>[+\-])\s*(?P<y>\w+)\s*;")
_ZERO_FLAG_NAMES_RE = re.compile(r"(?i)(?:is_zero|result_is_zero|zero|_zero|z_flag)$")


def _add_sub_control(text: str, ins, outs, top: str) -> Optional[str]:
    mh = _CASE_HEADER.search(text)
    if not mh:
        return None
    ctrl = mh.group(1)
    if not _by_name(ins, ctrl):
        return None  # the case selector must be a declared input
    # collect the +/- arms; require EXACTLY the two polarities {0,1}, each mapped.
    arms = {}
    for m in _CASE_ARM.finditer(text):
        val, lhs, x, op, y = (m.group("val"), m.group("lhs"),
                              m.group("x"), m.group("op"), m.group("y"))
        if val in arms:
            return None  # duplicate polarity -> ambiguous
        arms[val] = (lhs, x, op, y)
    if set(arms.keys()) != {"0", "1"}:
        return None
    # both arms must drive the SAME output LHS and operate on the SAME two operands.
    lhss = {a[0] for a in arms.values()}
    if len(lhss) != 1:
        return None
    out_lhs = next(iter(lhss))
    operand_pairs = {tuple(sorted((a[1], a[3]))) for a in arms.values()}
    if len(operand_pairs) != 1:
        return None
    xa, yb = next(iter(operand_pairs))
    # exactly one arm must be '+' and the other '-' (a genuine add/sub).
    ops = {a[2] for a in arms.values()}
    if ops != {"+", "-"}:
        return None
    # the out_lhs must be a declared (reg) output of the operand width.
    out_port = _by_name(outs, out_lhs)
    px = _by_name(ins, xa)
    py = _by_name(ins, yb)
    if not out_port or not px or not py:
        return None
    if px[1] != py[1] or out_port[1] != px[1]:
        return None
    w = px[1]
    # optional zero flag: a declared 1-bit output whose name reads "*_is_zero" etc.
    zero_out = None
    for n, ow in outs:
        if n == out_port[0]:
            continue
        if ow == 1 and _ZERO_FLAG_NAMES_RE.search(n):
            zero_out = n
            break
    # any OTHER undeclared-purpose output makes the spec ambiguous -> SKIP.
    extra = [n for n, _ in outs if n not in (out_port[0],)
             and n != (zero_out or "")]
    if extra:
        return None

    # reconstruct the per-polarity expression. arms[val] = (lhs, x, op, y).
    def _arm_expr(val: str) -> str:
        _lhs, x, op, y = arms[val]
        return f"{x} {op} {y}"

    in_decls = [_decl(n, ww, "input") for n, ww in ins]
    out_decls = [_decl(out_port[0], w, "output", reg=True)]
    if zero_out:
        out_decls.append(_decl(zero_out, 1, "output", reg=True))
    body = ["    always @(*) begin",
            f"        case ({ctrl})",
            f"            0: {out_port[0]} = {_arm_expr('0')};",
            f"            1: {out_port[0]} = {_arm_expr('1')};",
            "        endcase"]
    if zero_out:
        body.append(f"        {zero_out} = ({out_port[0]} == 0);")
    body.append("    end")
    return _emit("// program-SOLVED add/subtract by stated control bit"
                 + ("" if not zero_out else " + zero flag") + "; deterministic.",
                 top, in_decls, out_decls, body)


# --------------------------------------------------------------------------- #
# the solver                                                                  #
# --------------------------------------------------------------------------- #
def synth(prompt_text: str, top: str = "TopModule") -> Optional[str]:
    if not prompt_text or not prompt_text.strip():
        return None
    if _has_blocking_guard(prompt_text):
        return None

    ins, outs = _pp.parse_ports(prompt_text)
    if not ins or not outs:
        return None

    # FORM E (control add/sub) carries its own control input; the other forms are
    # purely combinational data paths and must NOT have a clock/reset port.
    # Try the control form first (it has the strongest structural signature: a
    # parsed case with +/- arms), then the clock-free combinational forms.
    rtl = _add_sub_control(prompt_text, ins, outs, top)
    if rtl is not None:
        return rtl

    if _is_sequential(ins):
        return None

    for builder in (_half_adder, _full_adder,
                    _nbit_unsigned_adder_with_carry, _signed_adder_with_overflow):
        rtl = builder(prompt_text, ins, outs, top)
        if rtl is not None:
            return rtl
    return None


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="path to the spec prompt .txt")
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: not an unambiguously-specified integer-arithmetic datapath",
              file=sys.stderr)
        sys.exit(1)
    print(rtl)
