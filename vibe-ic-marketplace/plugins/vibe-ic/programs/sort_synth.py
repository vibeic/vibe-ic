#!/usr/bin/env python3
"""sort_synth.py — DETERMINISTIC solver for the CVDP bubble-sort engine family.

A clean, fully-specified bubble-sort engine: a flattened N*WIDTH input bus, an
FSM (IDLE/SORTING/DONE), a fixed comparison schedule with NO early termination
(latency = N*(N-1)+2 cycles from start), and a 1-cycle `done` pulse. Parameters N
and WIDTH are PARSED from the prompt; the comparison schedule and latency are the
bubble-sort invariant, so the emit is GENERAL across any (N, WIDTH) instance.

GENERAL (§9): N/WIDTH read from the stated defaults; the sort direction (ascending
/ descending) read from prose; the module name from input.prompt/context (via the
bridge), never the OFF-LIMITS harness. No size, no element, no test vector hardcoded.

§4.05 PARSE-OR-SKIP: emit ONLY when ALL of these hold, else SKIP (return None):
  * the prompt names the bubble-sort algorithm with NO early termination (the
    fixed N*(N-1) schedule the bubble-sort invariant pins);
  * a flattened `[N*WIDTH-1:0]` in_data + out_data bus, a start pulse, a done pulse;
  * N and WIDTH parameter defaults are stated;
  * it is NOT a modify/complete-the-partial-code task (input.context present, or
    "modify"/"complete the given"/"retain" prose) — those are gate-backed AI authoring.
A different sort algorithm (insertion/merge/selection), an early-terminating bubble
sort (data-dependent latency), or a streaming sorter is NOT this shape -> SKIP.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Dict, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


def _toplevel(record: dict) -> Optional[str]:
    # module name — from input.prompt + input.context ONLY (via the bridge). The
    # harness `.env` TOPLEVEL is OFF-LIMITS oracle, so there is NO harness
    # fallback: when the name is stated in neither the prompt nor the context,
    # return None (never a peek at the hidden testbench).
    try:
        import record_prompt_context_bridge as _bridge
        return _bridge.toplevel_name(record)
    except Exception:
        return None


def _param_default(prompt: str, name: str) -> Optional[int]:
    # `N`  (Default is 8, ...) / `WIDTH`(Default is 8) / `N` (default = 8)
    for pat in (
        rf"`?{name}`?\s*\(\s*[Dd]efault\s+is\s+(\d+)",
        rf"`?{name}`?\s*\(\s*[Dd]efault\s*=\s*(\d+)",
        rf"`?{name}`?[^.\n]{{0,40}}?[Dd]efault(?:\s+value)?(?:\s+is|\s*=|\s+of)?\s*(\d+)",
    ):
        m = re.search(pat, prompt)
        if m:
            return int(m.group(1))
    return None


def _find_port(prompt: str, *names) -> Optional[str]:
    for n in names:
        if re.search(rf"`?{n}`?", prompt):
            return n
    return None


def solve(record: dict) -> Optional[str]:
    if not isinstance(record, dict):
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    if not prompt.strip():
        return None
    low = prompt.lower()

    if "bubble sort" not in low and "bubble-sort" not in low:
        return None
    # modify / complete-the-partial / context-bearing -> SKIP (gate-backed AI authoring)
    if (record.get("input") or {}).get("context"):
        return None
    if re.search(r"\bmodify\b|complete the (?:given|partial)|\bretain\b|"
                 r"already written|partial (?:system)?verilog|do not modify", low):
        return None
    # early-termination (data-dependent latency) is a different contract -> SKIP.
    # but "NO early termination" is the FIXED-schedule contract we DO emit, so the
    # negated form must not trip the skip.
    if re.search(r"(?<!no )(?<!without )early\s+termination|terminate\s+early|"
                 r"stop\s+when\s+(?:sorted|no\s+swap)", low):
        return None

    N = _param_default(prompt, "N")
    WIDTH = _param_default(prompt, "WIDTH")
    if N is None or WIDTH is None or N < 1 or WIDTH < 1:
        return None

    # the fixed N*(N-1) schedule must be the stated contract (latency N*(N-1)+2, or
    # "(N)*(N-1) passes", or "no early termination").
    if not (re.search(r"\(?N\)?\s*\*\s*\(?N\s*-\s*1\)?", prompt) or
            "no early termination" in low):
        return None

    top = _toplevel(record) or "sorting_engine"
    clk = _find_port(prompt, "clk", "clock") or "clk"
    rst = _find_port(prompt, "rst", "reset") or "rst"
    start = _find_port(prompt, "start") or "start"
    din = _find_port(prompt, "in_data", "data_in") or "in_data"
    dout = _find_port(prompt, "out_data", "data_out") or "out_data"
    done = _find_port(prompt, "done") or "done"
    descending = bool(re.search(r"descending|largest.*at\s+index\s*0|"
                                r"smallest.*at\s+index\s*(?:N|n)", low)) and \
        not re.search(r"ascending|smallest.*at\s+index\s*0", low)
    cmp_op = "<" if descending else ">"  # swap when out of order for the wanted direction
    active_low = rst.lower().endswith("_n") or "active-low" in low or "active low" in low
    rst_edge = "negedge" if active_low else "posedge"
    rst_test = f"!{rst}" if active_low else rst

    return f"""// program-SOLVED bubble-sort engine (N*WIDTH flattened bus, FSM IDLE/SORTING/DONE,
// fixed N*(N-1) comparison cycles, no early termination); parameters PARSED, deterministic.
module {top} #(
    parameter N = {N},
    parameter WIDTH = {WIDTH}
) (
    input {clk},
    input {rst},
    input {start},
    input [N*WIDTH-1:0] {din},
    output reg {done},
    output reg [N*WIDTH-1:0] {dout}
);
    localparam IDLE = 2'd0, SORTING = 2'd1, DONE = 2'd2;
    reg [1:0] state;
    reg [N*WIDTH-1:0] arr;
    integer step;
    integer pos;
    always @(posedge {clk} or {rst_edge} {rst}) begin
        if ({rst_test}) begin
            state <= IDLE;
            {done} <= 1'b0;
            step <= 0;
            pos <= 0;
        end else begin
            case (state)
                IDLE: begin
                    {done} <= 1'b0;
                    if ({start}) begin
                        arr <= {din};
                        state <= SORTING;
                        step <= 0;
                        pos <= 0;
                    end
                end
                SORTING: begin
                    if (arr[(pos*WIDTH) +: WIDTH] {cmp_op} arr[((pos+1)*WIDTH) +: WIDTH]) begin
                        arr[(pos*WIDTH) +: WIDTH] <= arr[((pos+1)*WIDTH) +: WIDTH];
                        arr[((pos+1)*WIDTH) +: WIDTH] <= arr[(pos*WIDTH) +: WIDTH];
                    end
                    step <= step + 1;
                    if (pos == N-2) pos <= 0;
                    else pos <= pos + 1;
                    if (step == N*(N-1) - 1) state <= DONE;
                end
                DONE: begin
                    {dout} <= arr;
                    {done} <= 1'b1;
                    state <= IDLE;
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
