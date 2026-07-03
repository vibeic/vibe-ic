#!/usr/bin/env python3
"""test_cvdp_step27_remediation.py — pins the Step-2.7 adversarial-review HIGH
remediations (the §4.05 false-reject / false-COMPLETE class the independent
reviewer reproduced) under the CVDP prompt+context-ONLY compliance rule.

(2b) A port whose width is a PARAMETER EXPRESSION — in EITHER bracket order or a
     markdown table width-cell — must NOT take a coincidental same-line prose
     `N bits` literal; the port is placed with an UNKNOWN width and the gate does
     NOT enforce a literal (so the true-width candidate is never false-rejected).
(ctx) A width the PROMPT leaves unstated but the PROVIDED input.context module
     HEADER declares is resolved from that header (interface = spec, §3.9), never
     from the golden output or the hidden cocotb harness.

§4.05 CVDP COMPLIANCE: the interface is recovered from the PROMPT's declared
Input/Output ports (+ input.context header). The cocotb `dut.<sig>` test, the
`.env` TOPLEVEL, and the golden `output` are OFF-LIMITS oracle — never read.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import cvdp_solve_pipeline as SP   # noqa: E402
import cvdp_complete_extract as CE  # noqa: E402


def _rec(top, prompt, cocotb_test="", *, ctx=None):
    """Record with input.prompt + input.context. A DECOY cocotb test + .env are
    present in the harness but are OFF-LIMITS oracle — never read by extract()/
    solve()."""
    files = {
        "src/.env": f"TOPLEVEL_LANG=verilog\nTOPLEVEL={top}\nMODULE=test_{top}\n",
        f"src/test_{top}.py": cocotb_test,
    }
    return {"id": f"t_{top}", "input": {"prompt": prompt, "context": ctx or {}},
            "output": {"response": "", "context": {}}, "harness": {"files": files}}


# --------------------------------------------------------------------------- #
# (2b) param-expression width must not be overridden by coincidental prose
# --------------------------------------------------------------------------- #
RANGE_BEFORE_PROMPT = """Design the module named `dp`. Registered datapath.

### Inputs:
- wdata_i [DATA_WIDTH-1:0]: data to be written. The beat counter updates the 20-bit counter with the lower bits of wdata_i.

### Outputs:
- done_o: high when complete.
"""


def test_range_before_name_param_width_not_prose_overridden():
    # `wdata_i [DATA_WIDTH-1:0]` must bind to its param width, NOT the coincidental
    # "20-bit counter" prose. DATA_WIDTH has no stated default here -> width is
    # UNKNOWN (None), never 20.
    rec = _rec("dp", RANGE_BEFORE_PROMPT)
    spec = CE.extract(rec)
    by = {p["name"]: p for p in spec["interface"]}
    assert "wdata_i" in by, "the port is placed"
    assert by["wdata_i"]["width"] != 20, "must NOT take the coincidental prose literal 20"
    assert by["wdata_i"]["width"] is None, "param-expression width with no default is UNKNOWN"
    # the gate does not enforce a literal width for it
    gp = {p["name"]: p for p in SP.build_gate(spec)["ports"]}
    assert gp["wdata_i"]["width"] is None
    assert by["wdata_i"]["source"] == "param_expression_width", "the port is sourced from the param expression"


def test_range_before_name_param_width_resolves_from_context():
    # same port, but DATA_WIDTH=32 is declared in the provided input.context RTL ->
    # the width RESOLVES to 32 (COMPLETE-grade), still never the prose 20.
    ctx = {"rtl/dp.sv": "module dp #(parameter DATA_WIDTH = 32)(input [DATA_WIDTH-1:0] wdata_i, output done_o); endmodule\n"}
    rec = _rec("dp", RANGE_BEFORE_PROMPT, ctx=ctx)
    by = {p["name"]: p for p in CE.extract(rec)["interface"]}
    assert by["wdata_i"]["width"] == 32, "resolves from the context param default, not prose 20"
    assert by["wdata_i"]["source"] == "param_expression_width", "the port is sourced from the param expression"


TABLE_PARAM_PROMPT = """Design the module named `mapper`.

### Inputs:
- bits [N*IN_WIDTH-1:0]: Packed input bits. Each group of 4 bits is a symbol.

### Outputs:
- valid: output valid.
"""


def test_table_cell_param_width_not_prose_overridden():
    # `bits [N*IN_WIDTH-1:0]` is a param-override width; the "group of 4 bits" prose
    # must NOT win. N/IN_WIDTH unresolved here -> width UNKNOWN, never 4.
    rec = _rec("mapper", TABLE_PARAM_PROMPT)
    by = {p["name"]: p for p in CE.extract(rec)["interface"]}
    assert "bits" in by
    assert by["bits"]["width"] != 4, "must NOT take the coincidental prose literal 4"
    assert by["bits"]["width"] is None


def test_param_expr_port_gate_accepts_resolved_literal_candidate():
    # the §4.05 payoff: with the width unenforced, a CORRECT candidate that writes
    # a resolved literal width is NOT rejected.
    rec = _rec("dp", RANGE_BEFORE_PROMPT)
    cand = "module dp (input [31:0] wdata_i, output done_o);\nendmodule\n"
    res = SP.gate_check(rec, cand)
    assert not any(v["kind"] == "port_width" for v in res["violations"]), res["violations"]


# --------------------------------------------------------------------------- #
# (prompt) a prompt-declared interface makes the record gate-able (no harness)
# --------------------------------------------------------------------------- #
FIFO_PROMPT = """Design a module named `af`, an asynchronous FIFO.

### Inputs:
- w_clk: 1-bit write clock.
- w_data [7:0]: input data.

### Outputs:
- r_data [7:0]: output data.
"""


def test_prompt_declared_interface_is_gateable():
    # the interface is recovered from the PROMPT (never a cocotb harness), so the
    # data ports are placed and the record is gate-able (Tier2/Tier3), not Tier4.
    rec = _rec("af", FIFO_PROMPT)
    res = SP.solve(rec)
    names = {p["name"] for p in res["gate"]["ports"]}
    assert {"w_data", "r_data"} <= names, names
    assert res["tier"] in (SP.TIER_AI_EMIT, SP.TIER_AI_GATED)  # gate-able, not Tier4


# --------------------------------------------------------------------------- #
# (T3->T2) input.context module header resolves a `width_not_stated` gap
# --------------------------------------------------------------------------- #
WIDTHLESS_PROMPT = """Design the module named `acc`. An accumulator.

### Inputs:
- clk: clock.
- din: input sample to accumulate.

### Outputs:
- acc_o: the running total.
"""


def test_context_header_width_closes_width_not_stated_gap():
    # the prose never states din/acc_o widths -> without the context they are a
    # `width_not_stated` gap (Tier3). The provided input.context module header
    # DECLARES them -> the widths resolve (authoritative §3.9 interface fact), the
    # ports carry the declared width tagged `context_header`, and the record
    # becomes COMPLETE -> Tier2.
    ctx = {"rtl/acc.sv": (
        "module acc (input clk, input [11:0] din, output [31:0] acc_o);\n"
        "  // body must NOT be read\n"
        "  always @(posedge clk) acc_o <= acc_o + din;\n"
        "endmodule\n")}
    rec = _rec("acc", WIDTHLESS_PROMPT, ctx=ctx)
    spec = CE.extract(rec)
    by = {p["name"]: p for p in spec["interface"]}
    assert by["din"]["width"] == 12 and by["din"]["source"] == "context_header"
    assert by["acc_o"]["width"] == 32 and by["acc_o"]["source"] == "context_header"
    assert spec["completeness"] == "COMPLETE"
    assert SP.solve(rec)["tier"] == SP.TIER_AI_EMIT  # Tier2


def test_context_header_absent_port_stays_a_gap():
    # §4.05: a port the context header does NOT declare keeps its honest gap — the
    # context fill never fabricates a width for a port it doesn't carry.
    ctx = {"rtl/acc.sv": "module acc (input clk, input [11:0] din);\nendmodule\n"}
    rec = _rec("acc", WIDTHLESS_PROMPT, ctx=ctx)
    spec = CE.extract(rec)
    by = {p["name"]: p for p in spec["interface"]}
    assert by["din"]["width"] == 12          # context declares din
    assert by.get("acc_o", {}).get("width") is None
    assert spec["completeness"] != "COMPLETE"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
