#!/usr/bin/env python3
"""ff_truth_table_synth.py — deterministic SOLVER for a flip-flop truth table.

A prompt that gives a clocked flip-flop's COMPLETE truth table whose output column
is one of {Qold, ~Qold, 0, 1} (the next-state as a function of the current output
Qold and the control inputs) fully determines the FF, blind — e.g. the JK-FF
  J | K | Q
  0 | 0 | Qold
  0 | 1 | 0
  1 | 0 | 1
  1 | 1 | ~Qold
Generalizes to D / T / SR flip-flops written in the same Qold notation. Emits a
posedge-clk register whose next value is the looked-up expression.

§4.05 SKIP (None) unless: a single clk input + the control inputs are 1-bit + a
single 1-bit output + a COMPLETE table (every control combination once) + every
output cell is one of the four allowed tokens.

API: synth(prompt_text, top="TopModule") -> RTL | None
"""
from __future__ import annotations
import itertools
import re

_CELL = {"qold": "Q", "~qold": "~Q", "!qold": "~Q", "0": "1'b0", "1": "1'b1"}


def _parse_ports(prompt):
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import port_parser   # bullet form OR Verilog module header (the v2/human twins)
    return port_parser.parse_ports(prompt)


def synth(prompt_text: str, top: str = "TopModule"):
    if not re.search(r"flip.?flop", prompt_text, re.I):
        return None
    ins, outs = _parse_ports(prompt_text)
    if len(outs) != 1 or outs[0][1] != 1:
        return None
    out_name = outs[0][0]
    clk = next((n for n, _ in ins if n.lower() in ("clk", "clock")), None)
    if not clk:
        return None
    ctrl = [n for n, w in ins if w == 1 and n != clk]
    if not ctrl or any(w != 1 for n, w in ins if n != clk):
        return None
    # header row: <ctrl...> | <out>  ; then 2^len(ctrl) rows of {0/1 ctrl} | <cell>
    table = {}
    for ln in prompt_text.splitlines():
        cells = [c.strip() for c in ln.split("|")]
        if len(cells) != len(ctrl) + 1:
            continue
        try:
            key = tuple(int(cells[i]) for i in range(len(ctrl)))
        except ValueError:
            continue
        if any(b not in (0, 1) for b in key):
            continue
        val = cells[-1].lower().replace(" ", "")
        if val not in _CELL:
            return None                      # an output token we don't understand -> SKIP
        cv = _CELL[val]
        if key in table and table[key] != cv:  # conflicting duplicate row -> SKIP
            return None
        table[key] = cv
    if len(table) != 2 ** len(ctrl):         # incomplete -> SKIP
        return None
    lines = [
        "// program-SOLVED flip-flop truth table (Qold feedback); deterministic, no AI.",
        f"module {top}(",
        "    " + ",\n    ".join([f"input {clk}"] + [f"input {n}" for n in ctrl]
                                + [f"output reg {out_name}"]),
        ");",
        f"    always @(posedge {clk}) begin",
        f"        case ({{{', '.join(ctrl)}}})",
    ]
    for combo in itertools.product([0, 1], repeat=len(ctrl)):
        bits = "".join(str(b) for b in combo)
        nxt = table[combo].replace("Q", out_name)
        lines.append(f"            {len(ctrl)}'b{bits}: {out_name} <= {nxt};")
    lines += ["        endcase", "    end", "endmodule", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    import sys
    from pathlib import Path
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: not a complete flip-flop truth table", file=sys.stderr)
        sys.exit(1)
    print(rtl)
