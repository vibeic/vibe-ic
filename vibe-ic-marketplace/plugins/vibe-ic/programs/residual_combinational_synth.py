#!/usr/bin/env python3
"""residual_combinational_synth.py — deterministic spec->RTL for the RESIDUAL
"other" cluster of tiny combinational VerilogEval problems: the grab-bag left
after the named structured-artifact families (truth table / K-map / FSM table /
mux / shift / cellular-automaton / LFSR / waveform / one-hot FSM / ...) are
covered by the wave-1 registry.

These residual problems carry NO structured artifact at all — no table, no grid,
no transition diagram. The behaviour is stated either as a *constant output* or as
an *equality comparator*. Each shape is fully determined by the prompt text, so it
is deterministically solvable WITHOUT any AI judgement. Everything else in the
residual (named-gate prose, structural net-lists, arithmetic with overflow,
multi-bit replicated compare, hierarchical sub-module composition) requires
inference and is left to the AI floor — this module SKIPs (returns None) on all of
it. (A literal Boolean equation `z = (x^y) & x` is owned by the dedicated
`comb_gate_synth` family, NOT here — see the v1.1.76 dedup note in section (2).)

Two §4.05-guarded sub-shapes, dispatched internally by `synth`:

  (1) constant_output     — one output, prose "always drive/output 0/1/LOW/HIGH".
                            e.g. Prob001_zero, Prob002_m2014_q4i, Prob003_step_one.
  (2) [REMOVED v1.1.76]    — boolean_equation moved to comb_gate_synth (the gate/
                            boolean family) so exactly one solver claims Prob010.
  (3) equality_comparator — two same-width inputs + one 1-bit output, prose
                            "z should be 1 if A = B, otherwise z should be 0".
                            e.g. Prob020_mt2015_eq2.

§4.05 NO-LEAK: every sub-shape SKIPs on ANY ambiguity. A prompt that mentions a
clock/register/state/sequence/sub-module/arithmetic-add, or whose stated equation
references a token that is NOT a declared input, or whose interface does not match
the sub-shape's exact port signature, returns None. The module never guesses.

General / chip-agnostic. Pure regex + port_parser.parse_ports. No I/O except the
optional __main__ CLI.

API:  synth(prompt_text, top="TopModule") -> str | None
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from port_parser import parse_ports  # noqa: E402  shared bullet/header port reader


# --------------------------------------------------------------------------- #
# Shared §4.05 disqualifiers — if the prompt smells of anything beyond a tiny
# pure-combinational stateless circuit, NONE of the residual sub-shapes apply.
# (Sequential / structural / arithmetic prompts are owned by other families or
# are genuine AI floor; we must never mis-fire onto them.)
# --------------------------------------------------------------------------- #
_SEQ_OR_STRUCT_RE = re.compile(
    r"\b(clk|clock|posedge|negedge|always\s*@|reset|register|flip[- ]?flop|"
    r"latch|state\b|next[- ]?state|sequence|counter|shift|sub[- ]?module|"
    r"submodule|instantiate|memory|ram\b|rom\b|fsm)\b",
    re.I,
)


def _disqualified(text: str) -> bool:
    """True if the prompt references sequential / structural / hierarchical
    behaviour that none of the residual combinational sub-shapes may touch."""
    return bool(_SEQ_OR_STRUCT_RE.search(text))


def _emit(top: str, port_decls: List[str], body_lines: List[str]) -> str:
    ports = ",\n  ".join(port_decls)
    body = "\n".join("  " + b for b in body_lines)
    return (
        f"module {top} (\n  {ports}\n);\n\n"
        f"{body}\n\n"
        f"endmodule\n"
    )


def _decl(direction: str, name: str, width: int) -> str:
    rng = "" if width <= 1 else f"[{width - 1}:0] "
    return f"{direction} {rng}{name}"


# --------------------------------------------------------------------------- #
# (1) constant_output
# --------------------------------------------------------------------------- #
# Prose forms that fully determine a constant 0 or 1 on the single output:
#   "always drive 0 (or logic low)"   "always outputs a LOW"
#   "always drive 1 (or logic high)"  "always output a HIGH"
_CONST_LOW_RE = re.compile(
    r"always\s+(?:out\w*|drive[s]?)\b[^.\n]*\b(?:low|logic\s*low|0\b|a\s+0\b)",
    re.I,
)
_CONST_HIGH_RE = re.compile(
    r"always\s+(?:out\w*|drive[s]?)\b[^.\n]*\b(?:high|logic\s*high|1\b|a\s+1\b)",
    re.I,
)


def _synth_constant_output(text: str, top: str) -> Optional[str]:
    if _disqualified(text):
        return None
    ins, outs = parse_ports(text)
    # exactly one 1-bit output, NO inputs — a constant has no functional input.
    if ins or len(outs) != 1:
        return None
    oname, owidth = outs[0]
    if owidth != 1:
        return None
    low = bool(_CONST_LOW_RE.search(text))
    high = bool(_CONST_HIGH_RE.search(text))
    # exactly one of {low, high} — never both (ambiguous), never neither.
    if low == high:
        return None
    val = "1'b0" if low else "1'b1"
    return _emit(top,
                 [_decl("output", oname, 1)],
                 [f"assign {oname} = {val};"])


# --------------------------------------------------------------------------- #
# (2) boolean_equation  — REMOVED at v1.1.76 integration.
# A literal Boolean equation (`z = (x^y) & x`) is owned by the dedicated
# `comb_gate_synth` family (single gate / wire / boolean-equation). Keeping a
# second copy here made two solvers fire on Prob010 — redundant. residual now
# owns ONLY the two shapes comb_gate does not: constant output + equality
# comparator. (Disjointness is enforced by the registry mutual-exclusion test.)
# --------------------------------------------------------------------------- #
# (3) equality_comparator
# --------------------------------------------------------------------------- #
# "two N-bit inputs A and B ... z should be 1 if A = B, otherwise z should be 0"
_EQ_CMP_RE = re.compile(
    r"\b(\w+)\s*(?:=|==|equals?)\s*(\w+)\b[^.\n]*?\botherwise\b[^.\n]*?\b0\b",
    re.I,
)
_EQ_CMP_ALT_RE = re.compile(
    r"\b1\s+if\s+(\w+)\s*(?:=|==|equals?)\s*(\w+)\b", re.I)


def _synth_equality_comparator(text: str, top: str) -> Optional[str]:
    if _disqualified(text):
        return None
    ins, outs = parse_ports(text)
    # exactly two inputs of equal width + exactly one 1-bit output
    if len(ins) != 2 or len(outs) != 1:
        return None
    (a_name, a_w), (b_name, b_w) = ins
    o_name, o_w = outs[0]
    if a_w != b_w or o_w != 1:
        return None
    pair = None
    m = _EQ_CMP_RE.search(text) or _EQ_CMP_ALT_RE.search(text)
    if not m:
        return None
    lhs, rhs = m.group(1), m.group(2)
    names = {a_name, b_name}
    if {lhs, rhs} != names:
        return None  # the equality must be between THE two inputs
    # confirm the output really is "1 when equal" — the prose must say z is 1
    # if A==B (we matched it); guard against the negated "z is 1 if A != B" form.
    # "not ... equal" within a short window (handles "not equal", "not be equal",
    # "must not be equal", ...), plus the explicit inequality tokens.
    if re.search(r"\bnot\b\W+(?:\w+\W+){0,3}equal", text, re.I) or \
       re.search(r"(?:!=|\bdiffer\w*|\bunequal\b)", text, re.I):
        return None
    port_decls = [_decl("input", a_name, a_w), _decl("input", b_name, b_w),
                  _decl("output", o_name, 1)]
    return _emit(top, port_decls,
                 [f"assign {o_name} = ({a_name} == {b_name});"])


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
_SUBSHAPES = (
    _synth_constant_output,
    _synth_equality_comparator,
)


def synth(prompt_text: str, top: str = "TopModule") -> Optional[str]:
    """Return synthesizable RTL for the first residual sub-shape that fires,
    or None (SKIP) if the prompt is ambiguous / out of the deterministic subset.

    At most one sub-shape can fire because their interface signatures are
    mutually exclusive (constant=no-inputs; equation=needs a stated equation;
    comparator=exactly-2-equal-width-inputs+equality-prose). Dispatch order is
    therefore irrelevant to correctness; it is fixed for determinism."""
    if not prompt_text or not prompt_text.strip():
        return None
    for fn in _SUBSHAPES:
        try:
            rtl = fn(prompt_text, top)
        except Exception:
            rtl = None
        if rtl:
            return rtl
    return None


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("prompt", help="path to a spec / prompt text file")
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args(argv)
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("// SKIP — no residual-combinational sub-shape matched")
        return 1
    sys.stdout.write(rtl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
