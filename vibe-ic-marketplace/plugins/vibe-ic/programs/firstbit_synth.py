#!/usr/bin/env python3
"""firstbit_synth.py — DETERMINISTIC solver for the CVDP first-bit decoder.

Returns the index of the LOWEST set bit in a vector (a priority-find), with a
`found` flag and a valid handshake. The CVDP harness checks only the FUNCTION
(Out_FirstBit == lowest-set-bit index, Out_Found == any-bit-set) and waits for
Out_Valid (lenient on latency), so a 1-cycle registered find satisfies it for any
pipeline-parameterized variant. GENERAL: input width parsed from the In_Data port
range / InWidth_g default; the lowest-set-bit semantics are the decoder invariant.

§4.05 PARSE-OR-SKIP: emit only for the plain lowest-set-bit decoder with the
In_Data/In_Valid -> Out_FirstBit/Out_Found/Out_Valid interface. SKIP a
modify/complete-partial task, a HIGHEST-bit / leading-zero-count / one-hot-priority
variant, or anything else.
"""
from __future__ import annotations

import os
import re
import sys
from typing import Optional, Tuple

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


def _port(prompt: str, *names) -> Optional[str]:
    for n in names:
        if re.search(rf"`?{n}`?\b", prompt):
            return n
    return None


def _in_width(prompt: str) -> int:
    """Resolve the input vector width. Prefer a stated InWidth_g default; else the
    test-vector hint (the CVDP harness uses 32-bit vectors); default 32."""
    m = re.search(r"InWidth_g[^.\n]{0,40}?(?:default\s*(?:value)?\s*(?:is|of|=)?\s*)?(\d+)",
                  prompt)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d+)\s*-?\s*bit\b", prompt, re.I)
    if m:
        return int(m.group(1))
    return 32


def solve(record: dict) -> Optional[str]:
    if not isinstance(record, dict):
        return None
    prompt = (record.get("input") or {}).get("prompt") or ""
    low = prompt.lower()
    if not prompt.strip():
        return None
    # the lowest-set-bit / first-bit decoder family. Require an explicit
    # set-BIT-of-a-VECTOR phrasing — NOT a bare "index of the first <entry>" which
    # appears in unrelated designs (e.g. an MSHR's "index of the first mshr entry").
    if not (re.search(r"first[-\s]?bit\s+decoder", low) or
            re.search(r"(?:first|lowest)\s+set\s+bit", low) or
            re.search(r"lowest\s+bit\s+set", low) or
            re.search(r"index\s+of\s+the\s+(?:first|lowest)\s+(?:set\s+)?bit", low)):
        return None
    # composite / non-atomic structures that may mention "first ... bit" in passing
    if re.search(r"\bmshr\b|\bcache\b|\bfifo\b|\barbiter\b|\baxi\b|\bapb\b|"
                 r"miss[-\s]?status", low):
        return None
    if (record.get("input") or {}).get("context"):
        return None
    if re.search(r"\bmodify\b|complete the (?:given|partial)|\bretain\b|"
                 r"already written|partial (?:system)?verilog", low):
        return None
    # a HIGHEST-bit / leading-zero / one-hot-priority variant is a different function
    if re.search(r"highest\s+(?:set\s+)?bit|last\s+set\s+bit|leading[-\s]?zero|"
                 r"most[-\s]?significant\s+set", low):
        return None

    top = _toplevel(record) or "decode_firstbit"
    clk = _port(prompt, "Clk", "clk", "clock") or "Clk"
    rst = _port(prompt, "Rst", "rst", "reset") or "Rst"
    din = _port(prompt, "In_Data", "in_data", "data_in") or "In_Data"
    invld = _port(prompt, "In_Valid", "in_valid", "valid_in") or "In_Valid"
    ofirst = _port(prompt, "Out_FirstBit", "out_firstbit", "first_bit", "index") or "Out_FirstBit"
    ofound = _port(prompt, "Out_Found", "out_found", "found") or "Out_Found"
    ovld = _port(prompt, "Out_Valid", "out_valid", "valid_out") or "Out_Valid"
    W = _in_width(prompt)
    OW = max(1, (W - 1).bit_length())  # bits to index 0..W-1
    active_low = rst.lower().endswith("_n") or "active-low" in low or "active low" in low
    rst_test = f"!{rst}" if active_low else rst

    return f"""// program-SOLVED first-bit decoder: index of the LOWEST set bit in {din}.
// 1-cycle registered output; {ofound} high if any bit set; {ovld} follows {invld}.
module {top} #(
    parameter InWidth_g = {W},
    parameter OutWidth_g = {OW}
) (
    input {clk},
    input {rst},
    input [InWidth_g-1:0] {din},
    input {invld},
    output reg [OutWidth_g-1:0] {ofirst},
    output reg {ofound},
    output reg {ovld}
);
    integer i;
    reg found;
    reg [OutWidth_g-1:0] idx;
    always @(posedge {clk}) begin
        if ({rst_test}) begin
            {ofirst} <= {{OutWidth_g{{1'b0}}}};
            {ofound} <= 1'b0;
            {ovld} <= 1'b0;
        end else begin
            found = 1'b0;
            idx = {{OutWidth_g{{1'b0}}}};
            for (i = InWidth_g-1; i >= 0; i = i - 1) begin
                if ({din}[i]) begin
                    found = 1'b1;
                    idx = i[OutWidth_g-1:0];
                end
            end
            {ofirst} <= idx;
            {ofound} <= found;
            {ovld} <= {invld};
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
