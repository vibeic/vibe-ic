"""v1.4.20 regression — professional_tb_gen's generated _reset() must drive every
DATA input to a known 0 BEFORE asserting reset, so no X propagates into the
datapath / streaming scoreboard during power-up.

Defect (found via a studio clean-run on the spm serial-parallel multiplier): the
generated _reset() asserted reset without first initialising the DUT inputs, so
`x`/`y` powered up at X. The X propagated through the datapath, and the
bounded-latency + bit-order calibrator in the streaming scoreboard locked a WRONG
(order, latency) — producing 203/208 FALSE mismatches on functionally-correct
RTL. Initialising every data input to 0 first takes the SAME RTL to 208/208 with
no RTL change. chip-AGNOSTIC: the input list is derived from the project's own
interface (L9/L1), never a per-chip literal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import professional_tb_gen as T  # noqa: E402


def _mk_spm(tmp: Path) -> Path:
    gd = tmp / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"fields": {
        "top_module": "spm",
        "top_ports": [
            {"name": "clk", "dir": "input", "width": 1},
            {"name": "rst", "dir": "input", "width": 1},
            {"name": "x", "dir": "input"},
            {"name": "y", "dir": "input", "width": 1},
            {"name": "p", "dir": "output", "width": 1}],
        "clocks": [{"name": "clk", "edge": "posedge", "period_ns": 10}],
        "reset_domains": [{"name": "rst", "polarity": "active_high",
                           "sync": "sync"}],
    }}))
    (gd / "L2_FRS.json").write_text(json.dumps({"frs_sections": [
        {"title": "Function",
         "content": "serial-parallel multiplier p = (x * y) mod 2^N"}]}))
    rtl = tmp / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "spm.v").write_text(
        "module spm #(parameter size = 32)("
        "input clk, input rst, input [size-1:0] x, input y, output p);\n"
        "endmodule\n")
    return tmp


def test_reset_zeroes_data_inputs_before_asserting_reset(tmp_path):
    proj = _mk_spm(tmp_path)
    res = T.generate(proj)
    tb = (Path(res["out_dir"]) / "tb_spm.py").read_text()

    # data inputs enumerated; clk/rst never reset-driven
    line = next(l for l in tb.splitlines() if l.startswith("DUT_INPUTS ="))
    assert "'x'" in line and "'y'" in line
    assert "'clk'" not in line and "'rst'" not in line

    # ordering: inputs zeroed BEFORE reset is asserted (the load-bearing fix)
    body = tb.split("async def _reset(dut):", 1)[1]
    zero_at = body.index("for _sig in DUT_INPUTS")
    assert_at = body.index("getattr(dut, RST).value = 1")
    assert zero_at < assert_at
    assert ".value = 0" in body[zero_at:assert_at]
