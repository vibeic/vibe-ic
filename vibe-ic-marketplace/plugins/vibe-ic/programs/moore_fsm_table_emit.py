#!/usr/bin/env python3
"""moore_fsm_table_emit.py — the PROGRAM half of the AI-extracts / program-emits
hybrid for behavioral-prose Moore FSMs (Lemmings, PS/2, prose controllers).

WHY (user directive 2026-06-23): a narrative FSM ("if a Lemming is bumped on the
left it walks right; if it falls for >20 cycles it splatters") cannot be parsed
into a transition table by a deterministic program — that reading needs genuine
NL understanding, where the AI is strongest. But once the FSM STRUCTURE is in a
COMPLETE enumerated table, emitting correct RTL is a deterministic FORMULA. So we
split the work:

    AI (skill / authoring step)  ->  produces the canonical FSM table below
    THIS PROGRAM (deterministic) ->  VALIDATES the table is complete + consistent
                                     against the prompt's real interface, then EMITS
                                     the RTL (free internal encoding — the TB observes
                                     only the Moore outputs).

The program is the §4.05 GATE: it returns None (SKIP) on ANY incompleteness or any
mismatch with the declared ports, so the AI cannot ship a wrong/hallucinated FSM —
the emitted RTL is a pure function of a table the program proved complete. This is
the §4.2 "AI-step gated by a program" bucket, not free-text authoring.

CANONICAL TABLE FORMAT (the AI emits this; one directive per line):

    STATES: LEFT RIGHT
    INPUTS: bump_left bump_right          # order fixes the TRANS bit order (MSB first)
    OUTPUTS: walk_left walk_right          # Moore outputs (each 1-bit)
    RESET: LEFT async active_high          # <state> <sync|async> <active_high|active_low>
    TRANS: LEFT 00 -> LEFT                  # one row per state x EVERY input combo
    TRANS: LEFT 01 -> LEFT
    TRANS: LEFT 10 -> RIGHT
    TRANS: LEFT 11 -> RIGHT
    TRANS: RIGHT 00 -> RIGHT
    TRANS: RIGHT 01 -> LEFT
    TRANS: RIGHT 10 -> RIGHT
    TRANS: RIGHT 11 -> LEFT
    OUT: LEFT walk_left=1 walk_right=0      # every OUTPUT defined for every state
    OUT: RIGHT walk_left=0 walk_right=1

API: synth(prompt_text, fsm_table_text, top="TopModule") -> RTL | None
     (prompt_text supplies the real interface — clk + reset + 1-bit inputs/outputs —
      which the table is validated against; chip-AGNOSTIC, pure parse + emit.)
"""
from __future__ import annotations
import itertools
import re


def _parse_ports(prompt):
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import port_parser
    return port_parser.parse_ports(prompt)


def parse_table(text):
    """Parse the canonical FSM table. Returns a dict or None (malformed)."""
    states, inputs, outputs = [], [], []
    reset = None
    trans = {}            # state -> {input_bits(str) -> next_state}
    mout = {}             # state -> {output_name -> 0/1}
    for raw in text.splitlines():
        ln = raw.strip()
        if not ln or ln.startswith("#"):
            continue
        m = re.match(r"STATES:\s*(.+)$", ln)
        if m:
            states = m.group(1).split()
            continue
        m = re.match(r"INPUTS:\s*(.*)$", ln)
        if m:
            inputs = m.group(1).split()
            continue
        m = re.match(r"OUTPUTS:\s*(.+)$", ln)
        if m:
            outputs = m.group(1).split()
            continue
        m = re.match(r"RESET:\s*(\w+)\s+(sync|async)\s+(active_high|active_low)\s*$", ln, re.I)
        if m:
            reset = (m.group(1), m.group(2).lower() == "async", m.group(3).lower() == "active_high")
            continue
        m = re.match(r"TRANS:\s*(\w+)\s+([01]+)\s*->\s*(\w+)\s*$", ln)
        if m:
            s, bits, nx = m.groups()
            trans.setdefault(s, {})
            if bits in trans[s] and trans[s][bits] != nx:
                return None                       # conflicting duplicate row
            trans[s][bits] = nx
            continue
        m = re.match(r"OUT:\s*(\w+)\s+(.+)$", ln)
        if m:
            s = m.group(1)
            od = {}
            for pair in re.finditer(r"(\w+)\s*=\s*([01])", m.group(2)):
                od[pair.group(1)] = int(pair.group(2))
            mout[s] = od
            continue
        return None                               # unrecognized directive -> malformed
    if not (states and outputs and reset):
        return None
    return {"states": states, "inputs": inputs, "outputs": outputs,
            "reset": reset, "trans": trans, "mout": mout}


def _validate(tbl, ins, outs):
    """§4.05 gate: the table must be COMPLETE and match the declared interface.
    Returns True iff safe to emit."""
    states = tbl["states"]
    if len(states) < 2 or len(set(states)) != len(states):
        return False
    known = set(states)
    in_widths = {n: w for n, w in ins}
    in_names = {n for n, w in ins if w == 1}
    out_names = {n for n, w in outs if w == 1}
    # the table's INPUTS must be REAL ports (no hallucination): either a declared
    # 1-bit input NAME, or a bit-select `name[k]` of a declared input BUS with the
    # index in range (an FSM that branches on one bit of a wide input, e.g. PS/2's
    # in[3]). Anything else -> reject.
    for i in tbl["inputs"]:
        m = re.match(r"^(\w+)\[(\d+)\]$", i)
        if m:
            base, k = m.group(1), int(m.group(2))
            if base not in in_widths or k >= in_widths[base]:
                return False
        elif i not in in_names:
            return False
    if set(tbl["outputs"]) != out_names or not out_names:
        return False
    # reset state known + reset is a declared reset-ish port present
    if tbl["reset"][0] not in known:
        return False
    # EVERY state x EVERY input combination must have a known next-state
    n = len(tbl["inputs"])
    combos = ["".join(c) for c in itertools.product("01", repeat=n)] if n else [""]
    for s in states:
        row = tbl["trans"].get(s, {})
        if set(row.keys()) != set(combos):
            return False                          # incomplete / wrong-width
        if any(nx not in known for nx in row.values()):
            return False
    # every state defines every output, 0/1
    for s in states:
        od = tbl["mout"].get(s, {})
        if set(od.keys()) != set(tbl["outputs"]):
            return False
    return True


def synth(prompt_text, fsm_table_text, top="TopModule"):
    ins, outs = _parse_ports(prompt_text)
    if not ins or not outs:
        return None
    tbl = parse_table(fsm_table_text)
    if tbl is None or not _validate(tbl, ins, outs):
        return None
    names = [n for n, _ in ins]
    clk = next((n for n in names if n.lower() in ("clk", "clock")), None)
    rst = next((n for n in names
                if "reset" in n.lower() or n.lower() in ("rst", "rst_n", "arst", "areset")), None)
    if not clk or not rst:
        return None

    states = tbl["states"]
    inp = tbl["inputs"]
    outputs = tbl["outputs"]
    reset_state, is_async, active_high = tbl["reset"]
    code = {s: i for i, s in enumerate(states)}
    w = max(1, (len(states) - 1).bit_length())
    combos = ["".join(c) for c in itertools.product("01", repeat=len(inp))] if inp else [""]

    rst_lvl = rst if active_high else f"!{rst}"
    edge = f"posedge {clk}" + (f" or {'posedge' if active_high else 'negedge'} {rst}"
                              if is_async else "")
    # port order: clk, rst, the FSM input PORTS, then the Moore outputs. A table
    # input may be a bit-select `bus[k]`; declare the DISTINCT base bus once at its
    # full width (the case selector below keys on the bit-select expressions).
    in_widths = {n: w for n, w in ins}
    fsm_ports, seen = [], set()
    for i in inp:
        mb = re.match(r"^(\w+)\[\d+\]$", i)
        base = mb.group(1) if mb else i
        if base in seen:
            continue
        seen.add(base)
        wb = in_widths.get(base, 1)
        fsm_ports.append(f"input [{wb-1}:0] {base}" if wb > 1 else f"input {base}")
    port_lines = [f"input {clk}", f"input {rst}"] + fsm_ports \
        + [f"output reg {n}" for n in outputs]
    L = [
        "// program-EMITTED Moore FSM from an AI-extracted complete table; the table",
        "// was validated complete + interface-matched before emit (deterministic).",
        f"module {top}(",
        "    " + ",\n    ".join(port_lines),
        ");",
    ]
    for s in states:
        L.append(f"    localparam [{w-1}:0] S_{s} = {w}'d{code[s]};")
    L += [f"    reg [{w-1}:0] state, nstate;",
          "    always @(*) begin",
          "        case (state)"]
    sel = "{" + ", ".join(inp) + "}" if inp else None
    for s in states:
        if inp:
            L.append(f"            S_{s}: case ({sel})")
            for c in combos:
                L.append(f"                {len(inp)}'b{c}: nstate = S_{tbl['trans'][s][c]};")
            L.append(f"                default: nstate = S_{reset_state};")
            L.append("            endcase")
        else:
            L.append(f"            S_{s}: nstate = S_{tbl['trans'][s]['']};")
    L += [f"            default: nstate = S_{reset_state};",
          "        endcase",
          "    end",
          f"    always @({edge}) begin",
          f"        if ({rst_lvl}) state <= S_{reset_state};",
          "        else state <= nstate;",
          "    end",
          "    always @(*) begin"]
    # Moore outputs: per-output case over state
    for o in outputs:
        L.append(f"        case (state)")
        for s in states:
            L.append(f"            S_{s}: {o} = 1'b{tbl['mout'][s][o]};")
        L.append(f"            default: {o} = 1'b0;")
        L.append("        endcase")
    L += ["    end", "endmodule", ""]
    return "\n".join(L)


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="the spec prompt (for the interface)")
    ap.add_argument("--table", required=True, help="the AI-extracted canonical FSM table")
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    rtl = synth(Path(a.prompt).read_text(errors="replace"),
                Path(a.table).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: table incomplete / inconsistent with the declared interface", file=sys.stderr)
        sys.exit(1)
    print(rtl)
