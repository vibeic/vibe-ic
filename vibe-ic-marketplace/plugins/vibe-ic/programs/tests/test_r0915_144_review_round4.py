#!/usr/bin/env python3
"""R-0915-144 round 4 — the round-3 review of next/icformal1c (43b904f26),
two directions each, on the review's OWN RTL + L8, through the real programs
(`formal_harness_gen.generate` -> `formal_property_run.run` ->
`formal_proof_evidence_check.audit`). Defect arms are RED on 43b904f26 and
GREEN on the fix; companion arms pin the other direction.

  H   off the declared top the program closes NOTHING — the three bypasses of
      the removed wire allowance (a second instance, a `#(...)` reset-value
      override, the wrapper's own flops) and the state-name collision all go
      to the expert; the declared-top case (spm's) still closes program-only
  M   "asynchronous" is not passed when the reset reaches a flop's D pin
      (round 5: NOT_DISCHARGED, not refuted); a purely async design passes
  L   `$display` ($print) is not state; `thr <= cnt` in a condition is not a
      register assignment

The engine arms need yosys + sby on PATH (the vibeic-eda image, as CI and
falsref run them); without them they are NOT_VERIFIED by name, and
VIBEIC_REQUIRE_EDA_VERIFICATION=1 turns that back into a failure.

chip-AGNOSTIC: every fixture is a generic textbook circuit written here.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import formal_harness_gen as fhg  # noqa: E402
import formal_property_run as fpr  # noqa: E402
import formal_proof_evidence_check as gate  # noqa: E402
from _tool_probes import skip_not_verified  # noqa: E402

L8P = "L8.clock_and_reset_waveform."
ZERO = "all registers are zero one cycle after assertion"


def _l8(resets, clocks=None) -> dict:
    return {"clock_and_reset_waveform": {
        "clocks": clocks if clocks is not None else [{"name": "clk", "edge": "posedge"}],
        "resets": resets}}


def _project(tmp: Path, rtl: str, l8: dict) -> Path:
    docs = tmp / "phase1/generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L3_PROTOCOL.json").write_text(json.dumps({"no_opcodes_in_input": True}))
    (docs / "L6_FSM.json").write_text(json.dumps({"no_fsm_in_input": True}))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps(l8, ensure_ascii=False))
    rd = tmp / "phase2/stage1/rtl"
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "m.v").write_text(rtl)
    return tmp


def _step5(project: Path, top: str = "m"):
    missing = [t for t in ("yosys", "sby") if shutil.which(t) is None]
    if missing:
        skip_not_verified(
            f"{missing} not on PATH, so no harness can be proved here",
            "tools/ci/run_suite_in_eda_image.sh -- programs/tests/test_r0915_144_review_round4.py")
    gen = fhg.generate(project=project, top=top)
    assert gen["verdict"] == "EMITTED", gen
    res = fpr.run(project, harness=Path(gen["harness_path"]),
                  rtl=[Path(p) for p in gen["rtl_files"]],
                  top=gen["harness_module"], container=None, timeout=300)
    return gen, res, gate.audit(project)


def _open(res) -> dict:
    return {o["id"]: o for o in res.get("unresolved_obligations") or []}


def _why(row: dict) -> str:
    return f"{row.get('description', '')} {row.get('program_refused', '')}"


def _closed(res) -> set:
    return set(res.get("program_discharged_obligations") or [])


def _refuted(res) -> set:
    return {r["id"] for r in res.get("structural_refutations") or []}


# ── H: off the declared top, nothing closes ─────────────────────────────────
CORE = """module core(input clk, input rst_n, input [7:0] d, output reg [7:0] q);
  always @(posedge clk) if (!rst_n) q <= 8'h00; else q <= d;
endmodule
"""
# The override case needs a core the generator can prove on (a literal-reset
# output `v`) while its OTHER register resets to a parameter the wrapper
# overrides: at the top "all registers zero" is false (q resets to A5).
CORE_INIT = """module core #(parameter [7:0] INIT = 8'h00)
  (input clk, input rst_n, input [7:0] d, output reg [7:0] q, output reg v);
  always @(posedge clk) if (!rst_n) begin q <= INIT; v <= 1'b0; end
                        else begin q <= d; v <= 1'b1; end
endmodule
"""


def _nothing_closes(tmp_path, rtl, l8):
    gen, res, rep = _step5(_project(tmp_path, rtl, l8))
    assert gen["selection"] != "declared_top"
    assert _closed(res) == set()
    assert res["expert_fallback_invocation_status"] != "INVOKED_BY_PROGRAM"
    for oid, row in _open(res).items():
        if oid.startswith(L8P):
            assert "closes nothing" in _why(row), oid
    assert rep["verdict"] != "PASS"


def test_h_a_second_instance_with_a_gated_reset_closes_nothing(tmp_path):
    rtl = ("module m(input clk, input rst_n, input scan_mode, input [7:0] d0, d1,"
           " output [7:0] q0, q1);\n"
           "  core u0(.clk(clk), .rst_n(rst_n), .d(d0), .q(q0));\n"
           "  core u1(.clk(clk), .rst_n(rst_n | scan_mode), .d(d1), .q(q1));\n"
           "endmodule\n" + CORE)
    _nothing_closes(tmp_path, rtl, _l8([{"name": "rst_n", "polarity": "active_low"}]))


def test_h_a_parameter_override_of_the_reset_value_closes_nothing(tmp_path):
    rtl = ("module m(input clk, input rst_n, input [7:0] d, output [7:0] q, output v);\n"
           "  core #(.INIT(8'hA5)) u_core(.clk(clk), .rst_n(rst_n), .d(d), .q(q), .v(v));\n"
           "endmodule\n" + CORE_INIT)
    _nothing_closes(tmp_path, rtl, _l8([{
        "name": "rst_n", "polarity": "active_low",
        "port_description": "synchronous, active-low; " + ZERO}]))


def test_h_the_wrappers_own_flops_close_nothing(tmp_path):
    rtl = ("module m(input clk, input rst_n, input [7:0] d, output [7:0] q);\n"
           "  reg [7:0] stage;\n"
           "  always @(posedge clk) if (rst_n) stage <= 8'h00; else stage <= d;\n"
           "  core u_core(.clk(clk), .rst_n(rst_n), .d(stage), .q(q));\n"
           "endmodule\n" + CORE)
    _nothing_closes(tmp_path, rtl, _l8([{"name": "rst_n", "polarity": "active_low"}]))


def test_h_a_top_bus_named_like_a_core_register_closes_nothing(tmp_path):
    rtl = """module m(input clk, input rst, input [3:0] d, e, output [7:0] q);
  wire [3:0] lo; reg [3:0] hi;
  always @(posedge clk) hi <= e;
  core4 u_core(.clk(clk), .rst(rst), .d(d), .q(lo));
  assign q = {hi, lo};
endmodule
module core4(input clk, input rst, input [3:0] d, output reg [3:0] q);
  always @(posedge clk) if (rst) q <= 4'd0; else q <= d;
endmodule
"""
    _nothing_closes(tmp_path, rtl, _l8([{
        "name": "rst", "polarity": "active_high",
        "port_description": "synchronous, active-high; " + ZERO}]))


def test_h_the_declared_top_still_closes_program_only(tmp_path):
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q);
  reg [7:0] r;
  always @(posedge clk) if (rst) begin r <= 8'd0; q <= 8'd0; end
                        else begin r <= d; q <= r; end
endmodule
"""
    gen, res, rep = _step5(_project(tmp_path, rtl, _l8([{
        "name": "rst", "polarity": "active_high", "sync": "synchronous",
        "port_description": "synchronous, active-high; " + ZERO}])))
    assert gen["selection"] == "declared_top"
    assert L8P + "resets.0.port_description" in _closed(res)
    assert res["expert_fallback_invocation_status"] == "INVOKED_BY_PROGRAM"
    assert rep["verdict"] == "PASS", rep["findings"]


# ── M: "asynchronous" vs a reset through D / EN ─────────────────────────────
def test_m_a_flop_reset_through_its_data_pin_is_not_discharged(tmp_path):
    rtl = """module m(input clk, input rst_n, input [7:0] seed, d, output reg [7:0] a, b);
  always @(posedge clk or negedge rst_n) if (!rst_n) a <= 8'h00; else a <= d;
  always @(posedge clk) if (!rst_n) b <= seed; else b <= d;
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, rtl, _l8([
        {"name": "rst_n", "sync": "asynchronous"}])))
    # round 5 (review round 4, H3): a reset that reaches a D pin is NOT
    # classified — it may be a reset to a non-constant value or plain data
    # use — so the claim is neither closed nor refuted
    assert L8P + "resets.0.sync" not in _closed(res)
    assert L8P + "resets.0.sync" not in _refuted(res)
    assert rep["verdict"] != "PASS"


def test_m_a_purely_asynchronous_reset_still_passes(tmp_path):
    rtl = """module m(input clk, input rst_n, input [7:0] d, output reg [7:0] a);
  always @(posedge clk or negedge rst_n) if (!rst_n) a <= 8'h00; else a <= d;
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, rtl, _l8([
        {"name": "rst_n", "sync": "asynchronous"}])))
    assert L8P + "resets.0.sync" in _closed(res)
    assert rep["verdict"] == "PASS", rep["findings"]


# ── L: debug cells and comparison operands ──────────────────────────────────
def test_l_a_display_is_not_state(tmp_path):
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q);
  always @(posedge clk) begin
    if (rst) q <= 8'd0; else q <= d;
    if (q == 8'hff) $display("full");
  end
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, rtl, _l8([{
        "name": "rst", "polarity": "active_high",
        "port_description": "synchronous, active-high; " + ZERO}])))
    assert L8P + "resets.0.port_description" in _closed(res)
    assert rep["verdict"] == "PASS", rep["findings"]


def test_l_a_comparison_operand_is_not_a_register(tmp_path):
    rtl = """module m(input clk, input rst, input en, input [7:0] thr,
          output reg [7:0] cnt, output reg hit);
  always @(posedge clk) begin
    if (rst) begin cnt <= 8'd0; hit <= 1'b0; end
    else begin
      cnt <= cnt + 8'd1;
      if (en && thr <= cnt) hit <= 1'b1;
    end
  end
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, rtl, _l8([{
        "name": "rst", "polarity": "active_high",
        "port_description": "synchronous, active-high; " + ZERO}])))
    assert L8P + "resets.0.port_description" in _closed(res)
    assert rep["verdict"] == "PASS", rep["findings"]
