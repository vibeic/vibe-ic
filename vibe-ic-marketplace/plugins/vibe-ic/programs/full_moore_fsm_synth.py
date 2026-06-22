#!/usr/bin/env python3
"""full_moore_fsm_synth.py — deterministic SOLVER for a full Moore FSM.

WHY (§4.2 absorption, "bucket-② -> bucket-①"): a VerilogEval prompt that gives a
COMPLETE Moore state-transition table (`A (0) --1--> B` = state A outputs 0, on
input 1 goes to B) + a fully-specified RESET (sync|async, named reset state,
active level) determines the whole machine, blind — the INTERNAL state encoding is
FREE because the testbench observes only the OUTPUT, not the state register. So we
pick a sequential encoding and EMIT the state register + next-state logic +
Moore-output lookup, making the problem program-GENERATED (zero authoring variance)
instead of AI-authored (Prob109_fsm1, Prob138_2012_q2fsm).

§4.05 NO-LEAK: returns None (SKIP — author untouched) unless EVERYTHING is
unambiguous: a clk + a reset port, exactly one 1-bit FSM input, exactly one 1-bit
Moore output, a complete table (both input values per state), consistent per-state
output annotations, all next-states known, and an EXPLICIT reset (async|sync +
`reset into state <S>` + active level). A prompt that omits the reset state /
polarity (e.g. Prob136_m2014_q6) SKIPs — we never guess reset behavior.

API: synth(prompt_text, top="TopModule") -> RTL string | None
"""
from __future__ import annotations
import re


def _parse_ports(prompt):
    ins, outs = [], []
    for m in re.finditer(
        r"^\s*-\s*(input|output)\s+(\w+)(\s*\(\s*(\d+)\s*bits?\s*\))?", prompt, re.M
    ):
        d, name, _, w = m.groups()
        (ins if d == "input" else outs).append((name, int(w) if w else 1))
    return ins, outs


def synth(prompt_text: str, top: str = "TopModule"):
    ins, outs = _parse_ports(prompt_text)
    if not ins or len(outs) != 1 or outs[0][1] != 1:
        return None
    out_name = outs[0][0]
    names = [n for n, _ in ins]
    clk = next((n for n in names if n.lower() in ("clk", "clock")), None)
    rst = next((n for n in names
                if "reset" in n.lower() or n.lower() in ("rst", "rst_n", "arst", "areset")), None)
    if not clk or not rst:
        return None
    fsm_ins = [n for n, w in ins if w == 1 and n not in (clk, rst)]
    if len(fsm_ins) != 1:                       # single-input transition format
        return None
    fin = fsm_ins[0]

    # Moore transition table: <state> (<out>) --<in>--> <next>
    trans, mout, states = {}, {}, []
    for m in re.finditer(r"^\s*(\w+)\s*\(\s*([01])\s*\)\s*--\s*([01])\s*-->\s*(\w+)",
                         prompt_text, re.M):
        s, o, i, nx = m.groups()
        if s not in states:
            states.append(s)
        _d = trans.setdefault(s, {})
        if i in _d and _d[i] != nx:             # conflicting duplicate (state,input) -> SKIP
            return None
        _d[i] = nx
        if s in mout and mout[s] != int(o):     # inconsistent output annotation -> SKIP
            return None
        mout[s] = int(o)
    if len(states) < 2:
        return None
    known = set(states)
    for s in states:
        if set(trans.get(s, {}).keys()) != {"0", "1"}:   # incomplete -> SKIP
            return None
        if any(nx not in known for nx in trans[s].values()):
            return None

    # reset MUST be fully specified
    mrs = re.search(r"reset[s]?\s+(?:in?to|to)\s+state\s+(\w+)", prompt_text, re.I)
    if not mrs:
        return None
    reset_state = mrs.group(1)
    if reset_state not in known:
        return None
    # NOTE: "asynchronous" CONTAINS "synchronous" — match on a word boundary so the
    # async case is not also read as sync (would SKIP a valid async-reset FSM).
    is_async = bool(re.search(r"\basynchronous", prompt_text, re.I))
    is_sync = bool(re.search(r"\bsynchronous", prompt_text, re.I))
    if is_async == is_sync:                     # need exactly one stated
        return None
    active_low = bool(re.search(r"active[-\s]?low", prompt_text, re.I)) or \
        bool(re.search(r"reset\s+(?:is\s+)?(?:active\s+)?low", prompt_text, re.I))
    active_high = bool(re.search(r"active[-\s]?high|reset\s+if\s+high|if\s+reset\s+if\s+high"
                                 r"|reset\s+(?:is\s+)?high", prompt_text, re.I))
    if active_low == active_high:               # need an unambiguous level
        return None

    # sequential encoding (FREE — TB observes only the output)
    code = {s: i for i, s in enumerate(states)}
    w = max(1, (len(states) - 1).bit_length())
    rst_lvl = rst if active_high else f"!{rst}"
    edge = f"posedge {clk}" + (f" or {'posedge' if active_high else 'negedge'} {rst}"
                               if is_async else "")
    lines = [
        f"// program-SOLVED full Moore FSM (free internal encoding); deterministic, no AI.",
        f"module {top}(",
        f"    input {clk},\n    input {rst},\n    input {fin},\n    output reg {out_name}",
        ");",
        f"    localparam SW = {w};",
    ]
    for s in states:
        lines.append(f"    localparam [{w-1}:0] S_{s} = {w}'d{code[s]};")
    lines += [f"    reg [{w-1}:0] state, nstate;",
              "    // next-state",
              "    always @(*) begin",
              f"        case (state)"]
    for s in states:
        lines.append(f"            S_{s}: nstate = {fin} ? S_{trans[s]['1']} : S_{trans[s]['0']};")
    lines += [f"            default: nstate = S_{reset_state};",
              "        endcase",
              "    end",
              "    // state register",
              f"    always @({edge}) begin",
              f"        if ({rst_lvl}) state <= S_{reset_state};",
              "        else state <= nstate;",
              "    end",
              "    // Moore output",
              "    always @(*) begin",
              f"        case (state)"]
    for s in states:
        lines.append(f"            S_{s}: {out_name} = 1'b{mout[s]};")
    lines += [f"            default: {out_name} = 1'b0;",
              "        endcase",
              "    end",
              "endmodule", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse, sys
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    from pathlib import Path
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: not a fully-specified Moore FSM", file=sys.stderr)
        sys.exit(1)
    print(rtl)
