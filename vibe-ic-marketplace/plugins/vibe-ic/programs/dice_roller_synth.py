#!/usr/bin/env python3
"""dice_roller_synth.py — DETERMINISTIC solver for the CVDP digital dice-roller.

An FSM (IDLE/ROLLING) that cycles an internal counter 1..DICE_MAX while a button
is HIGH and holds the last value when the button goes LOW; async reset initializes
the die. GENERAL: DICE_MAX is parsed from the prose ("6-sided" / "1 to 6" /
parameter default); the FSM structure and the 1..MAX wrap are the dice invariant.

§4.05 PARSE-OR-SKIP: emit ONLY for the plain single-die roller with a button-gated
ROLLING state; SKIP a modify/complete-partial task, a multi-die / weighted /
LFSR-random / seven-segment-decoded variant.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _toplevel(record: dict) -> Optional[str]:
    try:
        import record_prompt_context_bridge as _bridge
        t = _bridge.toplevel_name(record)
        if t:
            return t
    except Exception:
        pass
    # The harness `.env` TOPLEVEL is an OFF-LIMITS oracle; the module name comes
    # ONLY from input.prompt + input.context (via the bridge). None -> honest SKIP.
    return None


def _find_port(prompt: str, *names) -> Optional[str]:
    for n in names:
        if re.search(rf"`?{n}`?\b", prompt):
            return n
    return None


def _dice_max(prompt: str) -> Optional[int]:
    low = prompt.lower()
    # "6-sided" / "six-sided" / "values from 1 to 6" / "DICE_MAX ... default 6"
    m = re.search(r"\b(\d+)\s*-?\s*sided\b", low)
    if m:
        return int(m.group(1))
    m = re.search(r"DICE_MAX[^.\n]{0,40}?(?:default\s*(?:value)?\s*(?:is|of|=)?\s*)?(\d+)",
                  prompt)
    if m:
        return int(m.group(1))
    m = re.search(r"values?\s+from\s+1\s+to\s+(\d+)", low)
    if m:
        return int(m.group(1))
    return None


def solve(record: dict) -> Optional[str]:
    if not isinstance(record, dict):
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    low = prompt.lower()
    if not prompt.strip():
        return None
    if "dice" not in low and "die roller" not in low and "die-roller" not in low:
        return None
    if (record.get("input") or {}).get("context"):
        return None
    if re.search(r"\bmodify\b|complete the (?:given|partial)|\bretain\b|"
                 r"already written|partial (?:system)?verilog", low):
        return None
    # not the plain single-die button-gated roller -> SKIP
    if re.search(r"seven[-\s]?segment|7[-\s]?segment|lfsr|weighted|two\s+dice|"
                 r"multiple\s+dice|random\s+number\s+generator", low):
        return None
    if "rolling" not in low or "button" not in low:
        return None

    dmax = _dice_max(prompt)
    if dmax is None or dmax < 2 or dmax > 7:  # a 3-bit die value holds 1..7
        return None

    top = _toplevel(record) or "digital_dice_roller"
    clk = _find_port(prompt, "clk", "clock") or "clk"
    # Reset-port binding: the name and polarity come ONLY from the prompt prose
    # (the hidden cocotb TB is an OFF-LIMITS oracle). Prefer an explicit `reset_n`
    # spelling, then `reset`/`rst`; polarity is read from the prose ("active LOW").
    rst = _find_port(prompt, "reset_n", "reset", "rst") or "reset"
    button = _find_port(prompt, "button", "btn", "roll") or "button"
    dval = _find_port(prompt, "dice_value", "dice", "value", "result") or "dice_value"
    active_low = "active low" in low or "active-low" in low
    rst_edge = "negedge" if active_low else "posedge"
    rst_test = f"!{rst}" if active_low else rst

    return f"""// program-SOLVED digital dice roller: FSM IDLE/ROLLING, counts 1..DICE_MAX while
// button HIGH, holds last value when button LOW; async reset initializes the die.
module {top} #(
    parameter DICE_MAX = {dmax}
) (
    input {clk},
    input {rst},
    input {button},
    output reg [2:0] {dval}
);
    localparam IDLE = 1'b0, ROLLING = 1'b1;
    reg state;
    reg [2:0] counter;
    always @(posedge {clk} or {rst_edge} {rst}) begin
        if ({rst_test}) begin
            state <= IDLE;
            counter <= 3'd1;
            {dval} <= 3'd1;
        end else begin
            case (state)
                IDLE: begin
                    if ({button}) state <= ROLLING;
                end
                ROLLING: begin
                    if (counter == DICE_MAX[2:0]) counter <= 3'd1;
                    else counter <= counter + 3'd1;
                    {dval} <= counter;
                    if (!{button}) state <= IDLE;
                end
            endcase
        end
    end
endmodule
"""


def main(argv=None) -> int:
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--id")
    a = ap.parse_args(argv)
    n = 0
    for line in open(a.jsonl):
        r = json.loads(line)
        if a.id and r.get("id") != a.id:
            continue
        rtl = solve(r)
        if rtl:
            n += 1
            print(f"=== {r.get('id')} ===\n{rtl}")
    print(f"emitted={n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
