#!/usr/bin/env python3
"""comb_state_table_synth.py — deterministic SOLVER for a COMBINATIONAL state
transition + output table (the Moore-FSM "combinational portion").

A prompt that gives a complete Moore transition table + a GIVEN state encoding and
asks ONLY for the combinational next_state + output logic (ports: a `state` input
bus, a 1-bit FSM input, a `next_state` output bus, a 1-bit `out`; NO clock) is
fully determined, blind — e.g. Prob100_fsm3comb with `A=2'b00, B=2'b01, C=2'b10,
D=2'b11`. Here the encoding IS observable (next_state is an output), so it must be
the DECLARED one, not free. Emits a combinational case over {state, in}.

§4.05 SKIP (None) unless: no clk; exactly one state-bus input + one 1-bit input;
exactly one next_state-bus output (same width) + one 1-bit output; a complete
table; and an explicit code for EVERY state (all within the bus width).

API: synth(prompt_text, top="TopModule") -> RTL | None
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
import full_moore_fsm_synth as _fm   # noqa: E402  reuse _parse_ports/_parse_fsm_table


def synth(prompt_text: str, top: str = "TopModule"):
    ins, outs = _fm._parse_ports(prompt_text)
    if any(n.lower() in ("clk", "clock") for n, _ in ins):
        return None                                   # combinational only
    in_bus = [(n, w) for n, w in ins if w > 1]
    in_sc = [(n, w) for n, w in ins if w == 1]
    out_bus = [(n, w) for n, w in outs if w > 1]
    out_sc = [(n, w) for n, w in outs if w == 1]
    if len(in_bus) != 1 or len(in_sc) != 1 or len(out_bus) != 1 or len(out_sc) != 1:
        return None
    state_in, sw = in_bus[0]
    fin = in_sc[0][0]
    next_out, nw = out_bus[0]
    out_name = out_sc[0][0]
    if sw != nw:
        return None
    parsed = _fm._parse_fsm_table(prompt_text)
    if parsed is None:
        return None
    states, trans, mout, _gov = parsed          # gov (per-state input) unused here
    # GIVEN encoding: "A=2'b00, B=2'b01, ..." (every state, within the bus width)
    code = {}
    for m in re.finditer(r"\b(\w+)\s*=\s*\d*'?[bB]([01]+)\b", prompt_text):
        nm, bits = m.group(1), m.group(2)
        if nm in states:
            v = int(bits, 2)
            if nm in code and code[nm] != v:        # conflicting re-encoding -> SKIP
                return None
            code[nm] = v
    if set(code) != set(states) or any(v >= (1 << sw) for v in code.values()):
        return None
    if len(set(code.values())) != len(code):        # duplicate codes -> SKIP
        return None
    by_code = {code[s]: s for s in states}
    lines = [
        "// program-SOLVED combinational state-transition + output logic; deterministic.",
        f"module {top}(",
        f"    input {fin},\n    input [{sw-1}:0] {state_in},\n"
        f"    output reg [{sw-1}:0] {next_out},\n    output reg {out_name}",
        ");",
        "    always @(*) begin",
        f"        {next_out} = {sw}'d0; {out_name} = 1'b0;",
        f"        case ({state_in})",
    ]
    for sc in sorted(by_code):
        s = by_code[sc]
        n0, n1 = code[trans[s]["0"]], code[trans[s]["1"]]
        lines.append(f"            {sw}'d{sc}: begin "
                     f"{next_out} = {fin} ? {sw}'d{n1} : {sw}'d{n0}; "
                     f"{out_name} = 1'b{mout[s]}; end")
    lines += [f"            default: begin {next_out} = {sw}'d0; {out_name} = 1'b0; end",
              "        endcase", "    end", "endmodule", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: not a complete combinational state table", file=sys.stderr)
        sys.exit(1)
    print(rtl)
