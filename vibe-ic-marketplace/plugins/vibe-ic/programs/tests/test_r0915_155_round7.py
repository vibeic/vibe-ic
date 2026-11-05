#!/usr/bin/env python3
"""R-0915-155 round 7 — the review of next/icformal1f (bfae4cd54), two
directions each, on the reviewer's own RTL, through the real programs
(`formal_harness_gen.generate` -> `formal_property_run.run` ->
`formal_proof_evidence_check.audit`), plus one pure test per defended layer so
each layer's mutation is visible on its own.

  HIGH  `$` in a register name: C6 keeps it OUTSIDE the class (named); the
        observer parser reads a pragma WHOLE or refuses it; `_obs_wire` is
        injective; every `connect -set` must equal the declared observer
  MED   (R-0915-157 supersedes C7) the DUT is read as the CHIP reads it, so a
        design whose logic differs under `ifdef FORMAL` is proved on the arm
        the chip builds: an async reset refutes "synchronous", a non-zero
        reset value keeps "all zero" open
  LOW   C1-C3 examine design-relevant flops only: a FORMAL-only helper
        `f_rst_q <= rst` feeding an assertion does not push a design outside
  (opt) a second clock domain's gate verdict is pinned == FAIL (main's, from
        the pre-existing reset-safety floor)

The engine arms need yosys + sby on PATH (the vibeic-eda image, as CI and
falsref run them); without them they are NOT_VERIFIED by name, and
VIBEIC_REQUIRE_EDA_VERIFICATION=1 turns that back into a failure.
chip-AGNOSTIC: every fixture is a generic circuit written here.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

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


SYNC_ZERO = [{"name": "rst", "polarity": "active_high", "sync": "synchronous",
              "port_description": "synchronous, active-high; " + ZERO}]


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
            "tools/ci/run_suite_in_eda_image.sh -- programs/tests/test_r0915_155_round7.py")
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


def _outside(res, rep, precondition: str):
    assert res["verdict"] != "ERROR", res.get("refusal")
    assert _closed(res) == set()
    assert not res.get("structural_refutations")
    l8 = {k: v for k, v in _open(res).items() if k.startswith(L8P)}
    assert l8
    for oid, row in l8.items():
        assert "R-0915-155" in _why(row) and precondition in _why(row), (oid, _why(row))
    assert rep["verdict"] != "PASS"


# ── HIGH: `$` in a register name ────────────────────────────────────────────
DOLLAR = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q);
  reg [7:0] a;
  reg [7:0] a$b;
  always @(posedge clk) if (rst) begin a <= 8'd0; a$b <= 8'hA5; q <= 8'd0; end
                        else begin a <= d; a$b <= d; q <= a ^ a$b; end
endmodule
"""


def test_high_a_dollar_register_is_outside_the_class_named_c6(tmp_path):
    gen, res, rep = _step5(_project(tmp_path, DOLLAR, _l8(SYNC_ZERO)))
    _outside(res, rep, "C6")
    assert "dut.a$b" not in Path(gen["harness_path"]).read_text()


def test_high_layer_b_an_observer_pragma_is_read_whole_or_refused():
    text = "    // @observe vibeic_obs_a__b = dut.a$b\n    // @observe vibeic_obs_q = dut.q\n"
    assert fpr.parse_observers(text) == [("vibeic_obs_q", "dut.q")]
    assert fpr.unreadable_observers(text) == ["// @observe vibeic_obs_a__b = dut.a$b"]


def test_high_layer_c_the_observer_wire_is_injective():
    assert fhg._obs_wire("a__b") == "vibeic_obs_a__b"
    for bad in ("a$b", r"\esc", "u.q", "pipe[0]"):
        with pytest.raises(ValueError):
            fhg._obs_wire(bad)


def test_high_layer_d_every_connect_equals_the_declared_observer():
    harness = "    // @observe vibeic_obs_x = dut.x\n"
    good = "connect -set vibeic_obs_x dut.x\n"
    assert fpr.observer_binding_mismatches(harness, good) == []
    assert fpr.observer_binding_mismatches(harness, "connect -set vibeic_obs_x dut.y\n")
    assert fpr.observer_binding_mismatches(harness, good + "connect -set vibeic_obs_z dut.z\n")
    assert fpr.observer_binding_mismatches(harness, "")


# ── MED: the synthesis build ────────────────────────────────────────────────
def test_med_sync_under_formal_async_in_synthesis_is_proved_on_the_chip_arm(tmp_path):
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q);
`ifdef FORMAL
  always @(posedge clk) if (rst) q <= 8'd0; else q <= d;
`else
  always @(posedge clk or posedge rst) if (rst) q <= 8'd0; else q <= d;
`endif
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, rtl, _l8(SYNC_ZERO)))
    # R-0915-157: the DUT is read as the chip reads it (no FORMAL), so the
    # proof sees the ASYNC arm the chip builds: "synchronous" is refuted
    assert L8P + "resets.0.sync" in {r["id"] for r in res.get("structural_refutations") or []}
    assert rep["verdict"] == "FAIL"


def test_med_a_different_reset_value_in_synthesis_is_proved_on_the_chip_arm(tmp_path):
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q);
`ifdef FORMAL
  always @(posedge clk) if (rst) q <= 8'd0; else q <= d;
`else
  always @(posedge clk) if (rst) q <= 8'hA5; else q <= d;
`endif
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, rtl, _l8(SYNC_ZERO)))
    # R-0915-157: the chip resets q to A5 — "all registers zero" is false
    assert L8P + "resets.0.port_description" not in _closed(res)
    assert rep["verdict"] != "PASS"


def test_med_one_design_in_every_build_stays_inside(tmp_path):
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q);
  always @(posedge clk) if (rst) q <= 8'd0; else q <= d;
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, rtl, _l8(SYNC_ZERO)))
    assert rep["verdict"] == "PASS", rep["findings"]
    ev = json.loads((tmp_path / "phase2/stage1/formal/formal_structural_evidence.json").read_text())
    # R-0915-157: ONE DUT read, the chip's
    assert [e["defines"] for e in ev["elaborations"]] == ["chip read (-DSIMULATION)"]
    assert ev["applicability"]["inside"] is True


# ── LOW: verification-only helpers are not the design ───────────────────────
def test_low_a_formal_only_reset_helper_does_not_push_the_design_outside(tmp_path):
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q);
  always @(posedge clk) if (rst) q <= 8'd0; else q <= d;
`ifdef FORMAL
  reg f_rst_q = 1'b0;
  always @(posedge clk) f_rst_q <= rst;
  always @(posedge clk) if (f_rst_q) assert (q == 8'd0);
`endif
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, rtl, _l8(SYNC_ZERO)))
    assert L8P + "resets.0.port_description" in _closed(res)
    assert rep["verdict"] == "PASS", rep["findings"]


# ── optional: the second clock domain's gate verdict is main's ──────────────
def test_opt_a_second_clock_domain_gate_verdict_is_fail_as_on_main(tmp_path):
    rtl = """module m(input clk, input clk_b, input rst, input [7:0] d, output reg [7:0] q, output reg [7:0] qb);
  always @(posedge clk) if (rst) q <= 0; else q <= d;
  always @(posedge clk_b) if (rst) qb <= 0; else qb <= d;
endmodule
"""
    l8 = _l8(SYNC_ZERO, clocks=[{"name": "clk", "edge": "posedge"},
                                {"name": "clk_b", "edge": "posedge"}])
    gen, res, rep = _step5(_project(tmp_path, rtl, l8))
    assert "p_l8_" not in Path(gen["harness_path"]).read_text()
    assert _closed(res) == set()
    # the pre-existing reset-safety floor asserts qb on clk: FAIL, as on main
    assert rep["verdict"] == "FAIL"
