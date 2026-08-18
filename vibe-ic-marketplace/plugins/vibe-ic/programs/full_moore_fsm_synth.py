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

Extraction-completeness note (the "②->① is really push extraction up" doctrine):
the load-bearing work here is RECOGNISING the transition structure — three written
forms are accepted: bare arrow `A (0) --1--> B`, NAMED arrow `B (out=1) --in=0--> A`,
and tabular `A | A, B | 0`. The named arrow also expresses a TWO-input Moore where
each state gates on its OWN named input (`OFF (out=0) --j=1--> ON` /
`ON (out=1) --k=1--> OFF`, Prob110/111). Once the structure is complete the RTL is a
free formula. The output column being FREE internal encoding is what makes emission
deterministic (the TB observes only the Moore output, never the state register).

§4.05 NO-LEAK: returns None (SKIP — author untouched) unless EVERYTHING is
unambiguous: a clk + a reset port, ≥1 1-bit FSM input, exactly one 1-bit Moore
output, a complete table (both input values per state), consistent per-state output
annotations, all next-states known, and an EXPLICIT reset (async|sync + a named
reset state + active level). For the named-input form: every state's two arrows must
name the SAME governing input (a state gating on two different inputs SKIPs — we
never guess j-vs-k priority), the set of governing inputs must EQUAL the module's
1-bit inputs (no module input silently dropped), and bare/named arrows must not be
mixed. A prompt that omits the reset state / polarity (e.g. Prob136_m2014_q6) SKIPs
— we never guess reset behavior.

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
    """Return (states, trans, mout, gov) from a COMPLETE Moore table, or None.
    `gov[s]` is the input NAME that governs state s's transition (or None when the
    format gives a single implicit input). Accepts, SKIPping on any conflict/
    incompleteness:
      (a) arrow:        `A (0) --1--> B`        (state (output) --input--> next)
      (b) named arrow:  `B (out=1) --in=0--> A` (annotated output + named input;
                        a TWO-input Moore names a DIFFERENT input per state, e.g.
                        `OFF (out=0) --j=1--> ON` / `ON (out=1) --k=1--> OFF`)
      (c) tabular:      `A | A, B | 0`          (state | next@in=0, next@in=1 | output)
    The named-input arm tolerates the bare `(N)`/`--N-->` form too (the `out=`/
    `<name>=` prefixes are optional), so format (a) stays a subset of it.
    """
    trans, mout, states, gov = {}, {}, [], {}
    arrow = False
    # state (out[=]N) --[<name>=]N--> next  ; the out=/name= prefixes are OPTIONAL,
    # so the bare `A (0) --1--> B` form is still matched (in_name -> None).
    arrow_re = re.compile(
        r"^\s*(\w+)\s*\(\s*(?:out\s*=\s*)?([01])\s*\)\s*--\s*"
        r"(?:([A-Za-z_]\w*)\s*=\s*)?([01])\s*-->\s*(\w+)", re.M)
    for m in arrow_re.finditer(prompt):
        arrow = True
        s, o, in_name, i, nx = m.groups()
        if s not in states:
            states.append(s)
        _d = trans.setdefault(s, {})
        if i in _d and _d[i] != nx:
            return None
        _d[i] = nx
        # the governing input must be CONSISTENT within a state (both of a state's
        # arrows name the same input); two different inputs on one state -> SKIP
        # (we never guess transition priority between j and k).
        if s in gov and gov[s] != in_name:
            return None
        gov[s] = in_name
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
            gov[s] = None                       # tabular -> single implicit input
    if len(states) < 2:
        return None
    known = set(states)
    for s in states:
        if set(trans.get(s, {}).keys()) != {"0", "1"}:    # incomplete -> SKIP
            return None
        if any(nx not in known for nx in trans[s].values()):
            return None
    return states, trans, mout, gov


def _parse_reset(prompt, known):
    """Return (reset_state, is_async, active_high) or None — fully-specified only."""
    # collect EVERY reset-anchored "to/into state X" (X a known state); require a
    # UNIQUE target — an intervening clause ("reset takes priority over the
    # transition to state D and forces the machine to state A") names two and must
    # SKIP, never grab the first (Step-2.7 tabular review Finding 1).
    targets = []
    # Capture the reset clause up to the SENTENCE end (`.`), not the first newline:
    # the VE-v2 twin soft-wraps the clause ("...reset that resets\nthe FSM to state A"
    # / "...resets the FSM to\nstate A"), so the "to state X" target lives on the next
    # physical line. Spanning to the period keeps the whole clause together; the
    # UNIQUE-target guard below still SKIPs if two different states are named.
    for m in re.finditer(r"resets?\b([^.]*)", prompt, re.I):
        for t in re.finditer(r"\b(?:into|to)\s+state\s+(\w+)", m.group(1), re.I):
            if t.group(1) in known:
                targets.append(t.group(1))
    # also the declarative phrasing "The reset state is <S>" (Prob107_fsm1s) — a
    # named reset target that is not anchored by a "resets to/into" verb clause.
    for m in re.finditer(r"\breset\s+state\s+is\s+(\w+)", prompt, re.I):
        if m.group(1) in known:
            targets.append(m.group(1))
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
    # §4.05 belt-and-suspenders: a Moore arrow/tabular table only encodes 1-bit
    # input VALUES (in=0/1), so a single-bit governing input is the only thing it
    # can describe. If any non-clk/non-reset port is multi-bit we would silently
    # DROP it from the emitted ports (RTL that ignores a real input) — SKIP instead.
    if any(w != 1 for n, w in ins if n not in (clk, rst)):
        return None
    fsm_ins = [n for n, w in ins if w == 1 and n not in (clk, rst)]
    if not fsm_ins:
        return None

    parsed = _parse_fsm_table(prompt_text)
    if parsed is None:
        return None
    states, trans, mout, gov = parsed
    known = set(states)

    # Governing-input mode. Either EVERY state has a named governing input
    # ("named" — a 1- or 2-input arrow FSM where each state gates on its own
    # named input), or NONE do ("single" — the tabular / bare-arrow single
    # implicit input). A MIX is ambiguous -> SKIP.
    gov_vals = [gov[s] for s in states]
    if all(g is None for g in gov_vals):
        if len(fsm_ins) != 1:                   # single implicit input only
            return None
        per_state_input = {s: fsm_ins[0] for s in states}
    elif all(g is not None for g in gov_vals):
        # every governing input must BE a real fsm input, and every fsm input must
        # govern some state — no module input may be silently ignored (that would
        # emit RTL that drops a real input = a §4.05 leak).
        if set(gov_vals) != set(fsm_ins):
            return None
        per_state_input = {s: gov[s] for s in states}
    else:
        return None                             # mixed named/bare -> SKIP

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
    port_lines = [f"input {clk}", f"input {rst}"] + [f"input {n}" for n in fsm_ins] \
        + [f"output reg {out_name}"]
    lines = [
        f"// program-SOLVED full Moore FSM (free internal encoding); deterministic, no AI.",
        f"module {top}(",
        "    " + ",\n    ".join(port_lines),
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
        fin_s = per_state_input[s]              # input that governs THIS state
        lines.append(f"            S_{s}: nstate = {fin_s} ? S_{trans[s]['1']} : S_{trans[s]['0']};")
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
