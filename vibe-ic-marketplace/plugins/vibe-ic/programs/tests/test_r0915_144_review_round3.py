#!/usr/bin/env python3
"""R-0915-144 round 3 — the round-2 review of next/icformal1b (dd183291e), as
two-direction tests on the review's OWN RTL + L8, through the real programs
(`formal_harness_gen.generate` -> `formal_property_run.run` ->
`formal_proof_evidence_check.audit`). Each defect test is RED on dd183291e
and GREEN on the fix; the companion arms pin the other direction.

  H1  a temporal L8 answer proven on a DESCENDED module never closes the TOP's
      declaration (round 4: the plain-wire allowance was removed — the
      program closes nothing off the declared top)
  M2  one reset, two declared polarities: the program answers neither
  M3  an assumption anywhere the model reads (the RTL's `ifdef FORMAL`, a
      `` `ASSUME `` macro) refuses program closure
  M4  a blocking temporary in a clocked block is not state; blocking state
      that really survives in the netlist keeps "all state zero" open

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
            "tools/ci/run_suite_in_eda_image.sh -- programs/tests/test_r0915_144_review_round3.py")
    gen = fhg.generate(project=project, top=top)
    assert gen["verdict"] == "EMITTED", gen
    res = fpr.run(project, harness=Path(gen["harness_path"]),
                  rtl=[Path(p) for p in gen["rtl_files"]],
                  top=gen["harness_module"], container=None, timeout=300)
    return gen, res, gate.audit(project)


def _open(res) -> dict:
    return {o["id"]: o for o in res.get("unresolved_obligations") or []}


def _why(row: dict) -> str:
    """The row's REASONS only — never its `source` path, which carries the
    pytest tmp dir and so the test's own name."""
    return f"{row.get('description', '')} {row.get('program_refused', '')}"


def _closed(res) -> set:
    return set(res.get("program_discharged_obligations") or [])


# ── H1 ──────────────────────────────────────────────────────────────────────
CORE = """module core(input clk, input rst_n, input [7:0] d, output reg [7:0] q);
  always @(posedge clk) if (!rst_n) q <= 8'h00; else q <= d;
endmodule
"""
H1_L8 = _l8([{"name": "rst_n", "polarity": "active_low", "sync": "synchronous",
              "port_description": "synchronous, active-low; " + ZERO}])


def _chip(conn: str) -> str:
    return ("module m(input clk, input rst_n, input scan_mode, input [7:0] d, "
            "output [7:0] q);\n"
            f"  core u_core(.clk(clk), .rst_n({conn}), .d(d), .q(q));\n"
            "endmodule\n" + CORE)


def _h1_red(tmp_path, conn):
    gen, res, rep = _step5(_project(tmp_path, _chip(conn), H1_L8))
    assert gen["selection"] != "declared_top"
    for oid in ("resets.0.polarity", "resets.0.port_description"):
        assert L8P + oid not in _closed(res), oid
        assert "closes nothing" in _why(_open(res)[L8P + oid]), oid
    assert rep["verdict"] != "PASS"


def test_h1_a_gated_reset_in_the_wrapper_keeps_the_top_declaration_open(tmp_path):
    _h1_red(tmp_path, "rst_n | scan_mode")


def test_h1_an_inverted_reset_in_the_wrapper_keeps_the_top_declaration_open(tmp_path):
    _h1_red(tmp_path, "~rst_n")


def test_h1_even_a_straight_wired_wrapper_closes_nothing(tmp_path):
    # Round-3 review: the "plain wire through every wrapper" allowance was
    # itself bypassable, so it was REMOVED. Off the declared top the program
    # closes nothing; the obligations go to the expert with the reason.
    gen, res, rep = _step5(_project(tmp_path, _chip("rst_n"), H1_L8))
    assert gen["selection"] == "descended_wrapper"
    assert _closed(res) == set()
    assert rep["verdict"] != "PASS"


# ── M2 ──────────────────────────────────────────────────────────────────────
def test_m2_contradictory_polarities_close_neither(tmp_path):
    rtl = """module m(input clk, rst, input [7:0] d, output reg [7:0] q);
  always @(posedge clk) if (!rst) q <= 8'd0; else q <= d;
endmodule
"""
    l8 = _l8([{"name": "rst", "polarity": "active_low",
               "port_description": "active-high; " + ZERO}])
    _, res, rep = _step5(_project(tmp_path, rtl, l8))
    for oid in ("resets.0.polarity", "resets.0.port_description"):
        assert L8P + oid not in _closed(res), oid
        assert "contradictory" in _why(_open(res)[L8P + oid]), oid
    assert rep["verdict"] != "PASS"


# ── M3 ──────────────────────────────────────────────────────────────────────
def test_m3_an_rtl_formal_assumption_refuses_program_closure(tmp_path):
    # `u` is never reset, so "all registers zero" is FALSE; the RTL's own
    # `ifdef FORMAL assume(!rst)` would make the zero properties vacuous.
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q, output reg [7:0] u);
  always @(posedge clk) if (rst) q <= 0; else q <= d;
  always @(posedge clk) u <= d;
`ifdef FORMAL
  always @(*) assume(!rst);
`endif
endmodule
"""
    l8 = _l8([{"name": "rst", "polarity": "active_high",
               "port_description": "synchronous, active-high; " + ZERO}])
    _, res, rep = _step5(_project(tmp_path, rtl, l8))
    prose = L8P + "resets.0.port_description"
    assert prose not in _closed(res)
    assert "assumption" in _why(_open(res)[prose])
    assert rep["verdict"] != "PASS"


def test_m3_an_uppercase_assume_macro_is_an_assumption():
    assert fpr.foreign_assumptions("  `ASSUME(rst)\n")
    assert fpr.foreign_assumptions("  Assume property (@(posedge clk) rst);\n")
    assert not fpr.foreign_assumptions("  // assume nothing here\n  wire assumed_ok;\n")


# ── M4 ──────────────────────────────────────────────────────────────────────
def test_m4_a_blocking_temporary_is_not_state(tmp_path):
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] acc);
  reg [8:0] sum;
  always @(posedge clk) begin
    sum = acc + d;
    if (rst) acc <= 8'd0; else acc <= sum[7:0];
  end
endmodule
"""
    l8 = _l8([{"name": "rst", "polarity": "active_high",
               "port_description": "synchronous, active-high; " + ZERO}])
    gen, res, rep = _step5(_project(tmp_path, rtl, l8))
    assert "vibeic_obs_sum" not in Path(gen["harness_path"]).read_text()
    assert res["all_proved"] is True
    assert rep["verdict"] == "PASS", rep["findings"]


def test_m4_blocking_state_the_netlist_keeps_leaves_all_state_open(tmp_path):
    # the other direction: `cnt` is read before it is written, so it IS state,
    # and it is never reset — "all registers zero" is false and must not close.
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] acc);
  reg [7:0] cnt;
  always @(posedge clk) begin
    cnt = cnt + 8'd1;
    if (rst) acc <= 8'd0; else acc <= cnt;
  end
endmodule
"""
    l8 = _l8([{"name": "rst", "polarity": "active_high",
               "port_description": "synchronous, active-high; " + ZERO}])
    _, res, rep = _step5(_project(tmp_path, rtl, l8))
    assert L8P + "resets.0.port_description" not in _closed(res)
    assert rep["verdict"] != "PASS"
