#!/usr/bin/env python3
"""test_cvdp_step27_remediation.py — pins the Step-2.7 adversarial-review HIGH
remediations (the §4.05 false-reject / false-COMPLETE class the independent
reviewer reproduced) AND the tb.py cocotb-fallback that recovers the authoritative
harness interface.

(2b) A port whose width is a PARAMETER EXPRESSION — in EITHER bracket order or a
     markdown table width-cell — must NOT take a coincidental same-line prose
     `N bits` literal; the port is placed with an UNKNOWN width and the gate does
     NOT enforce a literal (so the true-width candidate is never false-rejected).
(tb) When the cocotb test lives in `tb.py` (not `test_*.py`), its `dut.<sig>.value`
     interface is still recovered — that is the contract the scorer binds.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import cvdp_solve_pipeline as SP   # noqa: E402
import cvdp_complete_extract as CE  # noqa: E402
import cvdp_atomic_bridge as B     # noqa: E402


def _rec(top, prompt, cocotb_test, *, test_name=None, ctx=None):
    """Record whose cocotb test file name is configurable (test_<top>.py by
    default, or `tb.py` to exercise the fallback)."""
    tf = test_name or f"test_{top}.py"
    files = {
        "src/.env": f"TOPLEVEL_LANG=verilog\nTOPLEVEL={top}\nMODULE=test_{top}\n",
        f"src/{tf}": cocotb_test,
        "src/test_runner.py": "runner stuff, ignore\n",
    }
    return {"id": f"t_{top}", "input": {"prompt": prompt, "context": ctx or {}},
            "output": {"response": "", "context": {}}, "harness": {"files": files}}


# --------------------------------------------------------------------------- #
# (2b) param-expression width must not be overridden by coincidental prose
# --------------------------------------------------------------------------- #
RANGE_BEFORE_PROMPT = """Design `dp`. Registered datapath.

- **`[DATA_WIDTH-1:0] wdata_i`**: data to be written.
- **Beat Counter**: updates the 20-bit counter with the lower bits of `wdata_i`.
- **`done_o`**: high when complete.
"""
RANGE_BEFORE_TB = """import cocotb
@cocotb.test()
async def test_dp(dut):
    dut.wdata_i.value = 1
    dut.done_o.value
"""


def test_range_before_name_param_width_not_prose_overridden():
    # `[DATA_WIDTH-1:0] wdata_i` (range BEFORE the name) must bind to its param
    # width, NOT the coincidental "20-bit counter" prose. DATA_WIDTH has no stated
    # default here -> width is UNKNOWN (None), never 20.
    rec = _rec("dp", RANGE_BEFORE_PROMPT, RANGE_BEFORE_TB)
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
    rec = _rec("dp", RANGE_BEFORE_PROMPT, RANGE_BEFORE_TB, ctx=ctx)
    by = {p["name"]: p for p in CE.extract(rec)["interface"]}
    assert by["wdata_i"]["width"] == 32, "resolves from the context param default, not prose 20"
    assert by["wdata_i"]["source"] == "param_expression_width", "the port is sourced from the param expression"


TABLE_PARAM_PROMPT = """Design `mapper`.

| Port | Width | Description |
|------|-------|-------------|
| `bits` | `N*IN_WIDTH` | Packed input bits. Each group of 4 bits is a symbol. |
| `valid` | 1 | output valid |
"""
TABLE_PARAM_TB = """import cocotb
@cocotb.test()
async def test_mapper(dut):
    dut.bits.value = 0
    dut.valid.value
"""


def test_table_cell_param_width_not_prose_overridden():
    # `| bits | N*IN_WIDTH |` is a param-override width; the "group of 4 bits" prose
    # must NOT win. N/IN_WIDTH unresolved here -> width UNKNOWN, never 4.
    rec = _rec("mapper", TABLE_PARAM_PROMPT, TABLE_PARAM_TB)
    by = {p["name"]: p for p in CE.extract(rec)["interface"]}
    assert "bits" in by
    assert by["bits"]["width"] != 4, "must NOT take the coincidental prose literal 4"
    assert by["bits"]["width"] is None


def test_param_expr_port_gate_accepts_resolved_literal_candidate():
    # the §4.05 payoff: with the width unenforced, a CORRECT candidate that writes
    # the harness-resolved literal width is NOT rejected.
    rec = _rec("dp", RANGE_BEFORE_PROMPT, RANGE_BEFORE_TB)
    cand = "module dp (input [31:0] wdata_i, output done_o);\nendmodule\n"
    res = SP.gate_check(rec, cand)
    assert not any(v["kind"] == "port_width" for v in res["violations"]), res["violations"]


# --------------------------------------------------------------------------- #
# (tb) cocotb-in-tb.py fallback recovers the authoritative interface
# --------------------------------------------------------------------------- #
FIFO_PROMPT = """Design a module named `af`, an asynchronous FIFO.
- `w_clk`: write clock
- `w_data` (8 bits): input data
- `r_data` (8 bits): output data
"""
FIFO_TB = """import cocotb
from cocotb.triggers import Timer
@cocotb.test()
async def run(dut):
    dut.w_clk.value = 0
    dut.w_data.value = 5
    await Timer(1, unit='ns')
    _ = dut.r_data.value
"""


def test_cocotb_in_tb_py_is_recovered():
    # the cocotb test lives in `tb.py`, NOT `test_*.py`. Its dut.<sig> interface
    # must still be recovered (the fallback) so the record is gate-able, not Tier4.
    rec = _rec("af", FIFO_PROMPT, FIFO_TB, test_name="tb.py")
    # the bridge's cocotb-text helper now returns the tb.py body
    txt = B._cocotb_test_text(B._harness_files(rec))
    assert "dut.w_clk" in txt and "dut.r_data" in txt
    res = SP.solve(rec)
    names = {p["name"] for p in res["gate"]["ports"]}
    # the data ports the tb.py harness binds are recovered -> the record is
    # gate-able (Tier3), not an un-gateable Tier4 (which is what the missing
    # fallback produced).
    assert {"w_data", "r_data"} <= names, names
    assert res["tier"] in (SP.TIER_AI_EMIT, SP.TIER_AI_GATED)  # gate-able, not Tier4


def test_test_py_still_preferred_over_tb_py():
    # a record WITH a proper test_*.py is unchanged (fallback only fires when none).
    rec = _rec("af", FIFO_PROMPT, FIFO_TB)  # default test_af.py
    txt = B._cocotb_test_text(B._harness_files(rec))
    assert "dut.w_clk" in txt


# --------------------------------------------------------------------------- #
# (T3->T2) input.context module header resolves a `width_not_stated` gap
# --------------------------------------------------------------------------- #
WIDTHLESS_PROMPT = """Design `acc`. An accumulator.
- `clk`: clock
- `din`: input sample to accumulate
- `acc_o`: the running total
"""
WIDTHLESS_TB = """import cocotb
@cocotb.test()
async def run(dut):
    dut.clk.value = 0
    dut.din.value = 7
    _ = dut.acc_o.value
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
    rec = _rec("acc", WIDTHLESS_PROMPT, WIDTHLESS_TB, ctx=ctx)
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
    rec = _rec("acc", WIDTHLESS_PROMPT, WIDTHLESS_TB, ctx=ctx)
    spec = CE.extract(rec)
    by = {p["name"]: p for p in spec["interface"]}
    assert by["din"]["width"] == 12          # context declares din
    assert by.get("acc_o", {}).get("width") is None
    assert spec["completeness"] != "COMPLETE"


def test_runner_only_harness_is_not_picked_as_test():
    # a harness with ONLY test_runner.py (no real test, no dut.) stays empty — the
    # fallback must not pick the runner (it has no dut.<sig> interface).
    rec = {"id": "t", "input": {"prompt": "x", "context": {}},
           "output": {"response": "", "context": {}},
           "harness": {"files": {"src/test_runner.py": "import cocotb_test  # no dut here\n"}}}
    assert B._cocotb_test_text(B._harness_files(rec)) == ""


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
