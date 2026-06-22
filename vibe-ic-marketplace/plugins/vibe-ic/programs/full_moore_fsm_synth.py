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
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import port_parser   # bullet form OR Verilog module header (the v2/human twins)
    return port_parser.parse_ports(prompt)


def _parse_fsm_table(prompt):
    """Return (states, trans, mout) from a COMPLETE Moore table, or None. Accepts
    two formats, SKIPs on any conflict/incompleteness:
      (a) arrow:   `A (0) --1--> B`   (state (output) --input--> next)
      (b) tabular: `A | A, B | 0`     (state | next@in=0, next@in=1 | output)
    """
    trans, mout, states = {}, {}, []
    arrow = False
    for m in re.finditer(r"^\s*(\w+)\s*\(\s*([01])\s*\)\s*--\s*([01])\s*-->\s*(\w+)", prompt, re.M):
        arrow = True
        s, o, i, nx = m.groups()
        if s not in states:
            states.append(s)
        _d = trans.setdefault(s, {})
        if i in _d and _d[i] != nx:
            return None
        _d[i] = nx
        if s in mout and mout[s] != int(o):
            return None
        mout[s] = int(o)
    if not arrow:
        for m in re.finditer(r"^\s*(\w+)\s*\|\s*(\w+)\s*,\s*(\w+)\s*\|\s*([01])\s*$", prompt, re.M):
            s, n0, n1, o = m.groups()
            if s.lower() == "state":            # header row
                continue
            if s in trans:                      # duplicate row -> SKIP
                return None
            states.append(s)
            trans[s] = {"0": n0, "1": n1}
            mout[s] = int(o)
    if len(states) < 2:
        return None
    known = set(states)
    for s in states:
        if set(trans.get(s, {}).keys()) != {"0", "1"}:    # incomplete -> SKIP
            return None
        if any(nx not in known for nx in trans[s].values()):
            return None
    return states, trans, mout


def _parse_reset(prompt, known):
    """Return (reset_state, is_async, active_high) or None — fully-specified only."""
    # collect EVERY reset-anchored "to/into state X" (X a known state); require a
    # UNIQUE target — an intervening clause ("reset takes priority over the
    # transition to state D and forces the machine to state A") names two and must
    # SKIP, never grab the first (Step-2.7 tabular review Finding 1).
    targets = []
    for m in re.finditer(r"resets?\b([^.\n]*)", prompt, re.I):
        for t in re.finditer(r"\b(?:into|to)\s+state\s+(\w+)", m.group(1), re.I):
            if t.group(1) in known:
                targets.append(t.group(1))
    if len(set(targets)) != 1:
        return None
    reset_state = targets[0]
    # "asynchronous" CONTAINS "synchronous" — match on a word boundary.
    is_async = bool(re.search(r"\basynchronous", prompt, re.I))
    is_sync = bool(re.search(r"\bsynchronous", prompt, re.I))
    if is_async == is_sync:
        return None
    active_low = bool(re.search(r"active[-\s]?low|reset\s+(?:is\s+)?(?:active\s+)?low", prompt, re.I))
    active_high = bool(re.search(r"active[-\s]?high|reset\s+if\s+high|reset\s+(?:is\s+)?high", prompt, re.I))
    # an async reset described as "positive/negative edge triggered" fixes the level
    if not active_high and not active_low and is_async:
        if re.search(r"positive[-\s]edge[-\s]?triggered\s+asynchronous", prompt, re.I):
            active_high = True
        elif re.search(r"negative[-\s]edge[-\s]?triggered\s+asynchronous", prompt, re.I):
            active_low = True
    if active_low == active_high:               # need an unambiguous level
        return None
    return reset_state, is_async, active_high


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

    parsed = _parse_fsm_table(prompt_text)
    if parsed is None:
        return None
    states, trans, mout = parsed
    known = set(states)

    rparsed = _parse_reset(prompt_text, known)
    if rparsed is None:
        return None
    reset_state, is_async, active_high = rparsed

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
