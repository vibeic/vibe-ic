#!/usr/bin/env python3
"""R-0915-155 — the program closes ONLY the class it can prove soundly.

Five review rounds each found a design class the program answered wrongly.
The ruling: one APPLICABILITY GATE, evaluated on the proof's own netlist(s)
before any closure. Inside the class the program answers (PASS or REFUTED);
outside it every L8 obligation is NOT_DISCHARGED — the flow's designed expert
fallback — with the failing precondition named. Never PASS, never REFUTED,
never ERROR outside the class.

Through the real programs (`formal_harness_gen.generate` ->
`formal_property_run.run` -> `formal_proof_evidence_check.audit`):

  OUTSIDE (the round-5 review's five RTLs) -> NOT_DISCHARGED, not PASS/FAIL/ERROR
    a flop reset through a synchronizer (a missing `!` one stage down)
    a register written only by reset (folded by opt_dff, kept by the proof)
    an array element as state (`pipe[0]`)
    a reset-qualified constant clear (`if (rst_n && clear) cnt <= 0`)
    a second clock domain
  INSIDE
    the spm-shaped serial multiplier -> PASS, program-only
    a simple correct design          -> PASS
    a simple wrong-polarity design   -> REFUTED

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


def _project(tmp: Path, files: dict, l8: dict) -> Path:
    docs = tmp / "phase1/generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L3_PROTOCOL.json").write_text(json.dumps({"no_opcodes_in_input": True}))
    (docs / "L6_FSM.json").write_text(json.dumps({"no_fsm_in_input": True}))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps(l8, ensure_ascii=False))
    rd = tmp / "phase2/stage1/rtl"
    rd.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (rd / name).write_text(text)
    return tmp


def _step5(project: Path, top: str = "m"):
    missing = [t for t in ("yosys", "sby") if shutil.which(t) is None]
    if missing:
        skip_not_verified(
            f"{missing} not on PATH, so no harness can be proved here",
            "tools/ci/run_suite_in_eda_image.sh -- programs/tests/test_r0915_155_applicability_gate.py")
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


def _not_discharged(res, rep, precondition: str, harness: Path,
                    base_floor_fails: bool = False):
    """Outside the class: every L8 obligation open with the precondition
    named; nothing closed, nothing refuted, no L8 property emitted; the proof
    ran (no ERROR); the gate is neither PASS nor FAIL.

    `base_floor_fails`: the pre-existing reset-safety FLOOR (not an L8
    property, and not this ruling's subject) fails on this design at main
    too — measured on the second-clock fixture — so the gate verdict there is
    main's, and only the L8 half is asserted."""
    assert res["verdict"] != "ERROR", res.get("refusal")
    assert _closed(res) == set()
    assert _refuted(res) == set()
    assert "p_l8_" not in harness.read_text()
    l8 = {k: v for k, v in _open(res).items() if k.startswith(L8P)}
    assert l8, "no L8 obligation is open"
    for oid, row in l8.items():
        assert "R-0915-155" in _why(row) and precondition in _why(row), (oid, _why(row))
    if not base_floor_fails:
        assert res["all_proved"] is True
        assert rep["verdict"] not in ("PASS", "FAIL"), rep["verdict"]
    else:
        assert rep["verdict"] != "PASS"


# ── OUTSIDE the class ───────────────────────────────────────────────────────
def test_a_flop_reset_through_a_synchronizer_is_not_discharged(tmp_path):
    rtl = """module m(input clk, input rst_n, input [7:0] d, output reg [7:0] q, output reg [7:0] b);
  reg s1, s2;
  always @(posedge clk or negedge rst_n) if (!rst_n) begin s1<=1'b0; s2<=1'b0; end else begin s1<=1'b1; s2<=s1; end
  always @(posedge clk or negedge rst_n) if (!rst_n) q <= 8'h00; else q <= d;
  always @(posedge clk or posedge s2) if (s2) b <= 8'h00; else b <= d;
endmodule
"""
    gen, res, rep = _step5(_project(tmp_path, {"m.v": rtl}, _l8([
        {"name": "rst_n", "polarity": "active_low", "sync": "asynchronous"}])))
    _not_discharged(res, rep, "C2", Path(gen["harness_path"]))


def test_a_register_written_only_by_reset_is_not_discharged(tmp_path):
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q);
  reg [7:0] key;
  always @(posedge clk) if (rst) key <= 8'hA5;
  always @(posedge clk) if (rst) q <= 8'd0; else q <= d ^ key;
endmodule
"""
    gen, res, rep = _step5(_project(tmp_path, {"m.v": rtl}, _l8([
        {"name": "rst", "polarity": "active_high", "sync": "synchronous",
         "port_description": "synchronous, active-high; " + ZERO}])))
    _not_discharged(res, rep, "R-0915-155", Path(gen["harness_path"]))


def test_an_array_element_as_state_is_not_discharged(tmp_path):
    files = {
        "a_sat.v": "module a_sat(input clk, input rst, input [7:0] x, output reg [7:0] y);"
                   " always @(posedge clk) if (rst) y <= 0; else y <= x; endmodule\n",
        "m.v": """module m(input clk, input rst, input [7:0] d, output reg [7:0] q);
  reg [7:0] pipe [0:1]; wire [7:0] s;
  a_sat u(.clk(clk),.rst(rst),.x(pipe[1]),.y(s));
  always @(posedge clk) if (rst) begin pipe[0]<=0; pipe[1]<=0; q<=0; end
                        else begin pipe[0]<=d; pipe[1]<=pipe[0]; q<=s; end
endmodule
"""}
    gen, res, rep = _step5(_project(tmp_path, files, _l8([
        {"name": "rst", "polarity": "active_high", "sync": "synchronous",
         "port_description": "synchronous, active-high; " + ZERO}])))
    _not_discharged(res, rep, "R-0915-155", Path(gen["harness_path"]))


def test_a_reset_qualified_constant_clear_is_not_discharged(tmp_path):
    rtl = """module m(input clk, input rst_n, input clear, input [7:0] d, output reg [7:0] q, output reg [7:0] cnt);
  always @(posedge clk or negedge rst_n) if (!rst_n) q <= 8'h00; else q <= d;
  always @(posedge clk) if (rst_n && clear) cnt <= 8'h00; else cnt <= cnt + 8'd1;
endmodule
"""
    gen, res, rep = _step5(_project(tmp_path, {"m.v": rtl}, _l8([
        {"name": "rst_n", "sync": "asynchronous"}])))
    _not_discharged(res, rep, "R-0915-155", Path(gen["harness_path"]))


def test_a_second_clock_domain_is_not_discharged(tmp_path):
    rtl = """module m(input clk, input clk_b, input rst, input [7:0] d, output reg [7:0] q, output reg [7:0] qb);
  always @(posedge clk) if (rst) q <= 0; else q <= d;
  always @(posedge clk_b) if (rst) qb <= 0; else qb <= d;
endmodule
"""
    gen, res, rep = _step5(_project(tmp_path, {"m.v": rtl}, _l8(
        [{"name": "rst", "polarity": "active_high", "sync": "synchronous",
          "port_description": "synchronous, active-high; " + ZERO}],
        clocks=[{"name": "clk", "edge": "posedge"}, {"name": "clk_b", "edge": "posedge"}])))
    _not_discharged(res, rep, "C1", Path(gen["harness_path"]),
                    base_floor_fails=True)


# ── INSIDE the class ────────────────────────────────────────────────────────
SERIAL = """module m #(parameter size = 8) (input wire clk, input wire rst,
    input wire [size-1:0] x, input wire y, output wire p);
    reg [size-1:0] s; reg [size-1:0] c; reg yr; reg pr;
    wire [size-1:0] mm = x & {size{yr}};
    wire [size-1:0] so = mm ^ s ^ c;
    wire [size-1:0] co = (mm & s) | (mm & c) | (s & c);
    always @(posedge clk) begin
        if (rst) begin s <= {size{1'b0}}; c <= {size{1'b0}}; yr <= 1'b0; pr <= 1'b0; end
        else begin yr <= y; s <= {1'b0, so[size-1:1]}; c <= co; pr <= so[0]; end
    end
    assign p = pr;
endmodule
"""
SPM_L8 = _l8([{"name": "rst", "polarity": "active_high", "sync": "synchronous",
               "port_description": "同步 reset(**active-high**);"
                                   "assertion 後一個 cycle 內所有內部狀態歸零"}])


def test_the_spm_shaped_design_is_inside_the_class_and_passes(tmp_path):
    _, res, rep = _step5(_project(tmp_path, {"m.v": SERIAL}, SPM_L8))
    assert res["expert_fallback_invocation_status"] == "INVOKED_BY_PROGRAM"
    # R-0924-2 (landed on main before this port): the reset NAME is
    # discharged by BINDING at the gate, not by the structural check, so
    # it is the one row the proof record leaves open and the gate closes.
    assert list(_open(res)) == [L8P + "resets.0.name"]
    assert res["property_denominator"] == 6
    assert res["authored_property_count"] == 5
    assert rep["verdict"] == "PASS", rep["findings"]
    assert rep["discharged_by_binding"] == [L8P + "resets.0.name"]
    ev = json.loads((tmp_path / "phase2/stage1/formal/formal_structural_evidence.json").read_text())
    assert ev["applicability"] == {"class": "R-0915-155", "inside": True,
                                   "failed_preconditions": []}


SIMPLE = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q, output reg [7:0] r);
  always @(posedge clk) if (rst) begin q <= 8'd0; r <= 8'd0; end else begin q <= d; r <= q; end
endmodule
"""
SIMPLE_L8 = _l8([{"name": "rst", "polarity": "active_high", "sync": "synchronous",
                  "port_description": "synchronous, active-high; " + ZERO}])


def test_a_simple_correct_design_passes(tmp_path):
    _, res, rep = _step5(_project(tmp_path, {"m.v": SIMPLE}, SIMPLE_L8))
    # R-0924-2 (landed on main before this port): the reset NAME is
    # discharged by BINDING at the gate, not by the structural check, so
    # it is the one row the proof record leaves open and the gate closes.
    assert list(_open(res)) == [L8P + "resets.0.name"]
    assert rep["verdict"] == "PASS", rep["findings"]
    assert rep["discharged_by_binding"] == [L8P + "resets.0.name"]


def test_a_simple_wrong_polarity_design_is_refuted(tmp_path):
    rtl = SIMPLE.replace("if (rst) begin", "if (!rst) begin")
    _, res, rep = _step5(_project(tmp_path, {"m.v": rtl}, SIMPLE_L8))
    assert L8P + "resets.0.polarity" in _refuted(res)
    assert rep["verdict"] == "FAIL"
