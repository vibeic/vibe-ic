#!/usr/bin/env python3
"""R-0915-144 round 2 — every upheld finding of the pre-landing review of
next/icformal1 (63de71090), as a two-direction test on the review's OWN
concrete RTL + L8, through the real programs:
`formal_harness_gen.generate` -> `formal_property_run.run` ->
`formal_proof_evidence_check.audit`.

Each test is RED on 63de71090 (the wrong verdict the review traced) and GREEN
on the fix. The rule behind all of them: Step 5 may PASS only on what a program
actually SAW; anything it cannot see is NOT_DISCHARGED (the obligation stays
open, named), and nothing that is not the rule's subject is a refutation.

  H1  a second reset's "all state zero" is guarded by ITS OWN reset
  H2  a latch / a memory is state: "ALL internal state" is not discharged
  H3  a program receipt answers ONE run: stale or forged pairs close nothing
  (a) a foreign `assume` makes program closures refused, not vacuously green
  M4  a reset reaching an async control THROUGH LOGIC refutes "synchronous";
      a clock reaching a flop through logic leaves "posedge" undischarged
  H5  an OUTPUT reset / a clock that clocks nothing is not REFUTED
  H6  `always_comb` targets are not state
  M7  a body-localparam width is refused, not a harness that cannot elaborate
  M8  an expert fragment's `@observe` is bound; an unbound observer is refused
  L9  the authored count never exceeds its denominator

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
from not_verified_tier import skip_not_verified  # noqa: E402

ZERO = "all internal state is zeroed one cycle after assertion"
L8P = "L8.clock_and_reset_waveform."

SERIAL = """`default_nettype none
module m #(parameter size = 8) (
    input  wire            clk,
    input  wire            rst,
    input  wire [size-1:0] x,
    input  wire            y,
    output wire            p
);
    reg  [size-1:0] s;
    reg  [size-1:0] c;
    reg             yr;
    reg             pr;
    wire [size-1:0] mm = x & {size{yr}};
    wire [size-1:0] so = mm ^ s ^ c;
    wire [size-1:0] co = (mm & s) | (mm & c) | (s & c);
    always @(posedge clk) begin
        if (rst) begin
            s  <= {size{1'b0}};
            c  <= {size{1'b0}};
            yr <= 1'b0;
            pr <= 1'b0;
        end else begin
            yr <= y;
            s  <= {1'b0, so[size-1:1]};
            c  <= co;
            pr <= so[0];
        end
    end
    assign p = pr;
    // EXTRA
endmodule
`default_nettype wire
"""


def _l8(clocks=None, resets=None) -> dict:
    return {"clock_and_reset_waveform": {
        "clocks": clocks if clocks is not None else [{"name": "clk", "edge": "posedge"}],
        "resets": resets if resets is not None else [
            {"name": "rst", "polarity": "active_high", "sync": "synchronous",
             "port_description": "synchronous, active-high; " + ZERO}]}}


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


def _engine():
    missing = [t for t in ("yosys", "sby") if shutil.which(t) is None]
    if missing:
        skip_not_verified(
            f"{missing} not on PATH, so no harness can be proved here",
            "tools/ci/run_suite_in_eda_image.sh -- programs/tests/test_r0915_144_review_round2.py")


def _step5(project: Path, top: str = "m"):
    _engine()
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


def _refuted(res) -> set:
    return {r["id"] for r in res.get("structural_refutations") or []}


# ── H1 ──────────────────────────────────────────────────────────────────────
H1_RTL = """module m(input clk, rst, clr, input [7:0] d, output reg [7:0] q, output reg [7:0] s);
  always @(posedge clk) if (rst) q <= 8'd0; else q <= d;
  always @(posedge clk) if (clr) s <= 8'd0; else s <= d & {8{~rst}};
endmodule
"""


def test_h1_a_second_resets_all_state_zero_is_checked_under_that_reset(tmp_path):
    l8 = _l8(resets=[
        {"name": "rst", "polarity": "active_high", "port_description": ZERO},
        {"name": "clr", "polarity": "active_high", "port_description": ZERO}])
    gen, res, rep = _step5(_project(tmp_path, H1_RTL, l8))
    # asserting clr leaves q = d: the declaration is false and must not PASS.
    # R-0915-155: `rst` also reaches s's D (`d & {8{~rst}}`), so the design
    # is outside the class the program proves — nothing closes, named.
    assert L8P + "resets.1.port_description" not in _closed(res)
    assert "R-0915-155" in _why(_open(res)[L8P + "resets.1.port_description"])
    assert rep["verdict"] != "PASS"


# ── H2 ──────────────────────────────────────────────────────────────────────
def test_h2_a_latch_is_state_all_state_zero_is_not_discharged(tmp_path):
    rtl = SERIAL.replace(
        "output wire            p\n",
        "output wire            p,\n    output wire [size-1:0] h\n").replace(
        "    // EXTRA\n",
        "    reg [size-1:0] hold;\n    always @(*) if (y) hold = x;\n    assign h = hold;\n")
    _, res, rep = _step5(_project(tmp_path, rtl, _l8()))
    prose = L8P + "resets.0.port_description"
    assert prose not in _closed(res)
    assert "dlatch" in _why(_open(res)[prose])
    assert rep["verdict"] != "PASS"


def test_h2_a_memory_is_state_all_state_zero_is_not_discharged(tmp_path):
    rtl = """module m(input clk, rst, input [1:0] wa, input [7:0] d, output reg [7:0] q);
  reg [7:0] mem[0:3];
  always @(posedge clk) begin if (rst) q <= 8'd0; else q <= mem[wa]; mem[wa[1:0]] <= d; end
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, rtl, _l8()))
    assert L8P + "resets.0.port_description" not in _closed(res)
    assert rep["verdict"] != "PASS"


# ── H3 ──────────────────────────────────────────────────────────────────────
def test_h3_a_previous_runs_receipt_closes_nothing_in_this_run(tmp_path):
    project = _project(tmp_path, SERIAL, _l8())
    _, res_a, _ = _step5(project)
    assert L8P + "clocks.0.edge" in _closed(res_a)            # run A: honest PASS
    # run B, same project: L8 re-extracted in forms NO rule reads (the review's
    # shape), so the contract routes nothing to the program and only a stale
    # pair on disk could close these ids.
    (project / "phase1/generated_docs/L8_TIMING_WAVEFORM.json").write_text(json.dumps(
        _l8(clocks=[{"name": "clk", "edge": "falling edge"}],
            resets=[{"name": "rst (active-high)", "polarity": "active_high",
                     "sync": "asynchronous"}]), ensure_ascii=False))
    _, res_b, rep_b = _step5(project)
    for oid in ("clocks.0.edge", "resets.0.name", "resets.0.sync"):
        assert L8P + oid in _open(res_b), oid
        assert L8P + oid not in _closed(res_b), oid
    assert res_b["expert_fallback_invocation_status"] != "INVOKED_BY_PROGRAM"
    assert rep_b["verdict"] != "PASS"


def test_h3_a_pair_that_does_not_match_this_runs_rtl_is_refused(tmp_path):
    project = _project(tmp_path, SERIAL, _l8())
    _step5(project)
    fdir = project / "phase2/stage1/formal"
    closed, _, _ = fpr._verified_program_closures(fdir)
    assert closed                                              # bound pair reads back
    rtl = project / "phase2/stage1/rtl/m.v"
    rtl.write_text(rtl.read_text() + "\n// edited after the measurement\n")
    assert fpr._verified_program_closures(fdir) == ({}, {}, {})


def test_h3_a_forged_pair_cannot_close_an_obligation_outside_the_program_rows(tmp_path):
    project = _project(tmp_path, SERIAL, _l8())
    _step5(project)
    fdir = project / "phase2/stage1/formal"
    receipt = json.loads((fdir / fpr.PROGRAM_RECEIPT).read_text())
    receipt["dispositions"].append({"id": "L6.fsm_state.IDLE",
                                    "status": fpr.DISCHARGED_BY_PROGRAM, "claims": []})
    (fdir / fpr.PROGRAM_RECEIPT).write_text(json.dumps(receipt))
    closed, _, _ = fpr._verified_program_closures(fdir)
    assert "L6.fsm_state.IDLE" not in closed


# ── (a) ─────────────────────────────────────────────────────────────────────
def test_a_foreign_assume_refuses_program_closure(tmp_path):
    project = _project(tmp_path, SERIAL, _l8())
    fdir = project / "phase2/stage1/formal"
    fdir.mkdir(parents=True)
    (fdir / fhg.EXPERT_PROPERTIES_SVH).write_text(
        "    a_no_reset: assume property (@(posedge clk) !rst);\n")
    _, res, rep = _step5(project)
    # the temporal "all state zero" claim could be vacuous under the assume:
    # it is not closed, and the reason names the assumption. (Polarity is a
    # structural netlist fact since round 5, which no assumption touches.)
    prose = L8P + "resets.0.port_description"
    assert prose not in _closed(res)
    assert "assumption" in _why(_open(res)[prose])
    assert rep["verdict"] != "PASS"


# ── M4 ──────────────────────────────────────────────────────────────────────
M4_RTL = """module m(input clk, rst, sw_clr, input [7:0] d, output reg [7:0] a, output reg [7:0] b);
  wire aclr = rst | sw_clr;
  always @(posedge clk) if (rst) a <= 8'd0; else a <= d;
  always @(posedge clk or posedge aclr) if (aclr) b <= 8'd0; else b <= d;
endmodule
"""


def test_m4_a_reset_ored_into_an_async_clear_is_never_passed(tmp_path):
    l8 = _l8(resets=[{"name": "rst", "sync": "synchronous"}])
    _, res, rep = _step5(_project(tmp_path, M4_RTL, l8))
    # R-0915-155: b's ARST is `rst | sw_clr`, not a pure chain from the reset
    # — outside the class: never closed (the old false PASS), never refuted
    assert L8P + "resets.0.sync" not in _closed(res)
    assert "R-0915-155" in _why(_open(res)[L8P + "resets.0.sync"])
    assert rep["verdict"] != "PASS"


def test_m4_a_gated_clock_leaves_the_edge_undischarged(tmp_path):
    rtl = """module m(input clk, rst, en, input [7:0] d, output reg [7:0] a, output reg [7:0] c);
  wire gclk = clk & en;
  always @(posedge clk) if (rst) a <= 8'd0; else a <= d;
  always @(negedge gclk) c <= d;
endmodule
"""
    l8 = _l8(resets=[{"name": "rst"}])
    _, res, rep = _step5(_project(tmp_path, rtl, l8))
    assert L8P + "clocks.0.edge" not in _closed(res)
    assert L8P + "clocks.0.edge" in _open(res)
    assert rep["verdict"] != "PASS"


# ── H5 ──────────────────────────────────────────────────────────────────────
RST_SYNC = """module m(input wire i_clk, input wire i_rst_n, output reg o_rst_n);
  reg meta;
  always @(posedge i_clk or negedge i_rst_n)
    if (!i_rst_n) begin meta <= 1'b0; o_rst_n <= 1'b0; end
    else begin meta <= 1'b1; o_rst_n <= meta; end
endmodule
"""


def test_h5_an_output_reset_is_not_a_refutation(tmp_path):
    l8 = _l8(clocks=[{"name": "i_clk", "edge": "posedge"}],
             resets=[{"name": "i_rst_n", "polarity": "active_low"},
                     {"name": "o_rst_n", "polarity": "active_low"}])
    _, res, rep = _step5(_project(tmp_path, RST_SYNC, l8))
    assert not _refuted(res)
    assert rep["verdict"] != "FAIL"
    row = _open(res)[L8P + "resets.1.name"]
    assert "not a 1-bit input" in _why(row)


def test_h5_a_declared_clock_that_clocks_no_flop_is_not_a_refutation(tmp_path):
    rtl = """module m(input clk, rst, sclk, output reg q);
  reg s1;
  always @(posedge clk) if (rst) begin s1 <= 1'b0; q <= 1'b0; end
                        else begin s1 <= sclk; q <= s1; end
endmodule
"""
    l8 = _l8(clocks=[{"name": "clk", "edge": "posedge"},
                     {"name": "sclk", "edge": "posedge"}],
             resets=[{"name": "rst"}])
    _, res, rep = _step5(_project(tmp_path, rtl, l8))
    assert L8P + "clocks.1.edge" not in _refuted(res)
    assert L8P + "clocks.1.edge" in _open(res)
    assert rep["verdict"] != "FAIL"


# ── H6 ──────────────────────────────────────────────────────────────────────
def test_h6_always_comb_targets_are_not_state(tmp_path):
    rtl = """module m(input logic clk, input logic rst, output logic [3:0] q);
  logic [3:0] q_n;
  always_ff @(posedge clk) begin if (rst) q <= '0; else q <= q_n; end
  always_comb begin q_n = q + 4'd1; end
endmodule
"""
    l8 = _l8(resets=[{"name": "rst", "polarity": "active_high",
                      "sync": "synchronous",
                      "port_description": "Synchronous active-high reset; " + ZERO}])
    gen, res, rep = _step5(_project(tmp_path, rtl, l8))
    assert "q_n" not in Path(gen["harness_path"]).read_text()
    assert res["all_proved"] is True
    assert rep["verdict"] == "PASS", rep["findings"]


# ── M7 ──────────────────────────────────────────────────────────────────────
def test_m7_a_body_localparam_width_is_refused_not_a_broken_harness(tmp_path):
    rtl = """module m #(parameter DIV=10)(input wire clk, input wire rst, output reg tick);
  localparam CW = $clog2(DIV);
  reg [CW-1:0] cnt;
  always @(posedge clk)
    if (rst) begin cnt <= 0; tick <= 1'b0; end
    else if (cnt == DIV-1) begin cnt <= 0; tick <= 1'b1; end
    else begin cnt <= cnt + 1'b1; tick <= 1'b0; end
endmodule
"""
    l8 = _l8(clocks=[], resets=[{"name": "rst", "polarity": "active_high"}])
    gen, res, rep = _step5(_project(tmp_path, rtl, l8))
    # round 5: nothing is copied as text — no `CW` in the harness, the proof
    # elaborates and the floor proves. The polarity is answered from the
    # netlist: `cnt` is ALSO zeroed on `cnt == DIV-1`, so yosys folds
    # `rst | (cnt == DIV-1)` into the sync reset, and a reset seen through a
    # gate has no polarity fact — NOT_DISCHARGED, named, never FAIL.
    assert "CW" not in Path(gen["harness_path"]).read_text()
    assert res["all_proved"] is True
    assert rep["verdict"] != "FAIL"
    assert "R-0915-155" in _why(_open(res)[L8P + "resets.0.polarity"])


# ── M8 ──────────────────────────────────────────────────────────────────────
FRAGMENT = (
    "    // @observe obs_yr2 = dut.yr\n"
    "    (* keep *) wire obs_yr2;\n"
    "    property p_expert_yr;\n"
    "        @(posedge clk) (f_past_valid && rst_active_q) |-> (obs_yr2 == 1'b0);\n"
    "    endproperty\n"
    "    a_expert_yr: assert property (p_expert_yr);\n")


def test_m8_an_expert_fragment_observer_is_bound(tmp_path):
    project = _project(tmp_path, SERIAL, _l8(resets=[]))
    fdir = project / "phase2/stage1/formal"
    fdir.mkdir(parents=True)
    (fdir / fhg.EXPERT_PROPERTIES_SVH).write_text(FRAGMENT)
    _, res, _ = _step5(project)
    sby = (project / res["sby"]).read_text()
    assert "connect -nomap -set obs_yr2 dut.yr" in sby
    assert res["all_proved"] is True                 # a correct design proves


def test_m8_an_observer_a_reused_task_file_does_not_bind_is_refused(tmp_path):
    project = _project(tmp_path, SERIAL, _l8())
    _, res, _ = _step5(project)
    sby = project / res["sby"]
    sby.write_text("\n".join(l for l in sby.read_text().splitlines()
                             if not l.startswith(("connect -nomap -set", "select -assert-any"))))
    res2 = fpr.run(project, harness=None, container=None, timeout=300)
    assert res2["verdict"] == "ERROR"
    assert any("vibeic_obs_" in r for r in res2["hierarchical_references"])


# ── L9 ──────────────────────────────────────────────────────────────────────
def test_l9_authored_never_exceeds_the_denominator_and_spm_still_passes(tmp_path):
    _, res, rep = _step5(_project(tmp_path, SERIAL, _l8(resets=[
        {"name": "rst", "polarity": "active_high", "sync": "synchronous",
         "port_description": "同步 reset(**active-high**);"
                             "assertion 後一個 cycle 內所有內部狀態歸零"}])))
    assert rep["verdict"] == "PASS", rep["findings"]
    assert res["expert_fallback_invocation_status"] == "INVOKED_BY_PROGRAM"
    # R-0924-2 (landed on main before this port): the reset NAME is
    # discharged by BINDING at the gate, not by the structural check, so
    # it is the one row the proof record leaves open and the gate closes.
    assert res["property_denominator"] == 6
    assert res["authored_property_count"] == 5
    assert list(_open(res)) == [L8P + "resets.0.name"]
    assert rep["discharged_by_binding"] == [L8P + "resets.0.name"]
    # 1 reset-safety floor + 4 state-zero properties; polarity is structural
    assert res["assert_statement_count"] == 5
