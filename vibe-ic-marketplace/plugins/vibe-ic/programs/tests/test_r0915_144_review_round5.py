#!/usr/bin/env python3
"""R-0915-144 round 5 — the round-4 review of next/icformal1d (4f135c77c).
The principle the review asked for: every decision about the design is read
from the NETLIST, never from RTL text. Two directions each, on the review's
own RTL + L8, through the real programs (`formal_harness_gen.generate` ->
`formal_property_run.run` -> `formal_proof_evidence_check.audit`). Defect
arms are RED on 4f135c77c; companion arms pin the other direction.

  H1  "declared top" means RESOLVED and FOUND by name: a first-module fallback
      (no top, a name that is not a module, a case mismatch) closes nothing
  H2  polarity is a structural fact over EVERY flop the reset forces: a
      register reset under the opposite sense (a missing `!`) is refuted
  H3  a reset that only GATES an enable is not a reset: a correct async
      design with `if (rst_n && load) cfg <= din;` passes
  M4  state comes from the netlist: a for-loop variable and an `ifdef FORMAL`
      helper that only feeds an assertion are not design state
  L   a latch enabled by the clock leaves the clock edge undischarged

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


def _step5(project: Path, top):
    missing = [t for t in ("yosys", "sby") if shutil.which(t) is None]
    if missing:
        skip_not_verified(
            f"{missing} not on PATH, so no harness can be proved here",
            "tools/ci/run_suite_in_eda_image.sh -- programs/tests/test_r0915_144_review_round5.py")
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


# ── H1: the declared top must be RESOLVED and FOUND ─────────────────────────
CORE = """module core(input clk, input rst_n, input [7:0] d, output reg [7:0] q);
  always @(posedge clk) if (!rst_n) q <= 8'h00; else q <= d;
endmodule
"""
TOPV = """module m(input clk, input rst_n, input scan_mode, input [7:0] d, output [7:0] q);
  core u_core(.clk(clk), .rst_n(rst_n | scan_mode), .d(d), .q(q));
endmodule
"""
H1_L8 = _l8([{"name": "rst_n", "polarity": "active_low", "sync": "synchronous"}])


def _nothing_closes(res, rep):
    assert _closed(res) == set()
    for oid, row in _open(res).items():
        if oid.startswith(L8P):
            assert "closes nothing" in _why(row), oid
    assert rep["verdict"] != "PASS"


def test_h1_no_top_and_two_modules_closes_nothing(tmp_path):
    # the first module of the first sorted file (a_core.v) is a leaf
    project = _project(tmp_path, {"a_core.v": CORE, "b_top.v": TOPV}, H1_L8)
    gen, res, rep = _step5(project, None)
    assert gen["top"] == "core"
    _nothing_closes(res, rep)


def test_h1_a_declared_top_that_is_not_a_module_closes_nothing(tmp_path):
    # the runner's default top name when no chip_top.v was emitted
    project = _project(tmp_path, {"a_core.v": CORE, "b_top.v": TOPV}, H1_L8)
    _, res, rep = _step5(project, "chip_top")
    _nothing_closes(res, rep)


def test_h1_a_case_mismatched_top_closes_nothing(tmp_path):
    project = _project(tmp_path, {"a_core.v": CORE, "b_top.v": TOPV}, H1_L8)
    _, res, rep = _step5(project, "M")
    _nothing_closes(res, rep)


def test_h1_a_found_declared_top_still_closes(tmp_path):
    project = _project(tmp_path, {"m.v": CORE.replace("module core", "module m")}, H1_L8)
    gen, res, rep = _step5(project, "m")
    assert gen["selection"] == "declared_top"
    assert L8P + "resets.0.polarity" in _closed(res)
    assert rep["verdict"] == "PASS", rep["findings"]


# ── H2: polarity over EVERY flop the reset forces ───────────────────────────
def test_h2_a_register_reset_in_the_opposite_sense_refutes_the_polarity(tmp_path):
    rtl = """module m(input clk, input rst_n, input [7:0] d, output reg [7:0] q, output reg [7:0] p);
  always @(posedge clk) if (!rst_n) q <= 8'h00; else q <= d;
  always @(posedge clk) if (rst_n) p <= 8'h00; else p <= d;
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, {"m.v": rtl},
                                  _l8([{"name": "rst_n", "polarity": "active_low"}])), "m")
    assert L8P + "resets.0.polarity" in _refuted(res)
    assert rep["verdict"] == "FAIL"


def test_h2_every_register_reset_in_the_declared_sense_passes(tmp_path):
    rtl = """module m(input clk, input rst_n, input [7:0] d, output reg [7:0] q, output reg [7:0] p);
  always @(posedge clk) if (!rst_n) q <= 8'h00; else q <= d;
  always @(posedge clk) if (!rst_n) p <= 8'h00; else p <= d;
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, {"m.v": rtl},
                                  _l8([{"name": "rst_n", "polarity": "active_low"}])), "m")
    assert L8P + "resets.0.polarity" in _closed(res)
    assert rep["verdict"] == "PASS", rep["findings"]


# ── H3: gating an enable is not a reset ─────────────────────────────────────
def test_h3_a_reset_qualified_load_does_not_refute_asynchronous(tmp_path):
    rtl = """module m(input clk, input rst_n, input load, input [7:0] din, d,
          output reg [7:0] q, output reg [7:0] cfg);
  always @(posedge clk or negedge rst_n) if (!rst_n) q <= 8'h00; else q <= d;
  always @(posedge clk) if (rst_n && load) cfg <= din;
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, {"m.v": rtl},
                                  _l8([{"name": "rst_n", "sync": "asynchronous"}])), "m")
    # not refuted (the round-4 false FAIL); R-0915-155: the reset reaching an
    # ENABLE is outside the class, so it is NOT_DISCHARGED — never FAIL
    assert L8P + "resets.0.sync" not in _refuted(res)
    assert L8P + "resets.0.sync" not in _closed(res)
    assert "R-0915-155" in _why(_open(res)[L8P + "resets.0.sync"])
    assert rep["verdict"] not in ("PASS", "FAIL")


def test_h3_a_forced_synchronous_reset_still_refutes_asynchronous(tmp_path):
    rtl = """module m(input clk, input rst_n, input [7:0] d, output reg [7:0] q, output reg [7:0] s);
  always @(posedge clk or negedge rst_n) if (!rst_n) q <= 8'h00; else q <= d;
  always @(posedge clk) if (!rst_n) s <= 8'h00; else s <= d;
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, {"m.v": rtl},
                                  _l8([{"name": "rst_n", "sync": "asynchronous"}])), "m")
    assert L8P + "resets.0.sync" in _refuted(res)
    assert rep["verdict"] == "FAIL"


# ── M4: state from the netlist ──────────────────────────────────────────────
PROSE = [{"name": "rst", "polarity": "active_high", "sync": "synchronous",
          "port_description": "synchronous, active-high; " + ZERO}]


def test_m4_a_for_loop_variable_is_not_state(tmp_path):
    rtl = """module m(input clk, input rst, input d, output reg [7:0] q);
  reg [3:0] i;
  always @(posedge clk)
    if (rst) q <= 8'd0;
    else begin q[0] <= d; for (i = 1; i <= 7; i = i + 1) q[i] <= q[i-1]; end
endmodule
"""
    gen, res, rep = _step5(_project(tmp_path, {"m.v": rtl}, _l8(PROSE)), "m")
    assert "dut.i" not in Path(gen["harness_path"]).read_text()
    assert L8P + "resets.0.port_description" in _closed(res)
    assert rep["verdict"] == "PASS", rep["findings"]


def test_m4_a_formal_only_helper_register_is_not_state(tmp_path):
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q);
  always @(posedge clk) if (rst) q <= 8'd0; else q <= d;
`ifdef FORMAL
  reg seen = 1'b0;
  always @(posedge clk) seen <= 1'b1;
  always @(posedge clk) if (seen) assert (q == q);
`endif
endmodule
"""
    gen, res, rep = _step5(_project(tmp_path, {"m.v": rtl}, _l8(PROSE)), "m")
    assert "dut.seen" not in Path(gen["harness_path"]).read_text()
    assert L8P + "resets.0.port_description" in _closed(res)
    assert rep["verdict"] == "PASS", rep["findings"]


def test_m4_real_unreset_state_still_keeps_all_state_zero_open(tmp_path):
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q, output reg [7:0] u);
  always @(posedge clk) if (rst) q <= 8'd0; else q <= d;
  always @(posedge clk) u <= d;
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, {"m.v": rtl}, _l8(PROSE)), "m")
    assert L8P + "resets.0.port_description" not in _closed(res)
    assert rep["verdict"] != "PASS"


# ── L: a latch the clock enables ────────────────────────────────────────────
def test_l_a_latch_enabled_by_the_clock_leaves_the_edge_undischarged(tmp_path):
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q, output [7:0] y);
  reg [7:0] l;
  always @(posedge clk) if (rst) q <= 8'd0; else q <= d;
  always @(*) if (clk) l = d;
  assign y = l;
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, {"m.v": rtl}, _l8([{"name": "rst"}])), "m")
    assert L8P + "clocks.0.edge" not in _closed(res)
    assert rep["verdict"] != "PASS"
