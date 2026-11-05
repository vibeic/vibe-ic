#!/usr/bin/env python3
"""R-0915-157 — the program-closed proof proves THE CHIP'S DESIGN.

The DUT is read for the proof EXACTLY as the synthesis that produces the chip
reads it (`_chip_synth_read`: the same file selection, the chip's
`-DSIMULATION` decision, `read_verilog -sv`, no `-formal`); only the harness is
read with `-formal` and the proof defines. Design flops start from ARBITRARY
state (silicon has no initializers). With one DUT read there is nothing to
compare, so the round-7 build signature (C7) is gone.

On the round-7 review's own RTL, through the real programs
(`formal_harness_gen.generate` -> `formal_property_run.run` ->
`formal_proof_evidence_check.audit`). Each defect arm is RED on 59f0be4ad:

  `ifdef SIMULATION` swap           -> the proof sees the chip's arm: never PASS
  `ifdef FORMAL` data-path swap     -> the proof reads the synthesis arm: never PASS
  `reg b = 0; b <= b & d` unreset   -> no initializer in the proof: never PASS
  FORMAL-only alias / next-state    -> no longer pushes a correct design outside: PASS
  reader
  `@connect` inductive run          -> not refused; the main results.json untouched

The engine arms need yosys + sby on PATH (the vibeic-eda image, as CI and
falsref run them); without them they are NOT_VERIFIED by name, and
VIBEIC_REQUIRE_EDA_VERIFICATION=1 turns that back into a failure.
chip-AGNOSTIC: generic fixtures written here.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import formal_harness_gen as fhg  # noqa: E402
import formal_property_run as fpr  # noqa: E402
import formal_proof_evidence_check as gate  # noqa: E402
from _tool_probes import skip_not_verified  # noqa: E402

L8P = "L8.clock_and_reset_waveform."
SYNC_ZERO = [{"name": "rst", "polarity": "active_high", "sync": "synchronous",
              "port_description": "synchronous, active-high; all registers "
                                  "are zero one cycle after assertion"}]


def _l8(resets=SYNC_ZERO, clocks=None) -> dict:
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


def _engine():
    missing = [t for t in ("yosys", "sby") if shutil.which(t) is None]
    if missing:
        skip_not_verified(
            f"{missing} not on PATH, so no harness can be proved here",
            # the helper also serves test_r0915_157_proof_is_about_the_built_chip
            "tools/ci/run_suite_in_eda_image.sh -- programs/tests/test_r0915_157_proof_reads_the_chip.py"
            " programs/tests/test_r0915_157_proof_is_about_the_built_chip.py")


def _step5(project: Path, top: str = "m"):
    _engine()
    gen = fhg.generate(project=project, top=top)
    assert gen["verdict"] == "EMITTED", gen
    res = fpr.run(project, harness=Path(gen["harness_path"]),
                  rtl=[Path(p) for p in gen["rtl_files"]],
                  top=gen["harness_module"], container=None, timeout=300)
    return gen, res, gate.audit(project)


def _closed(res) -> set:
    return set(res.get("program_discharged_obligations") or [])


# ── the proof sees the CHIP's arm ───────────────────────────────────────────
def test_an_ifdef_simulation_swap_is_proved_as_the_chip_builds_it(tmp_path):
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q);
  reg [7:0] s;
  always @(posedge clk) if (rst) q <= 8'd0; else q <= d ^ s;
`ifdef SIMULATION
  always @(posedge clk or posedge rst) if (rst) s <= 8'hA5; else s <= d;
`else
  always @(posedge clk) if (rst) s <= 8'd0; else s <= d;
`endif
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, rtl, _l8()))
    # the chip (-DSIMULATION) resets s ASYNCHRONOUSLY to A5: "synchronous" and
    # "all zero" are false for it, so nothing that claims them may close
    assert L8P + "resets.0.sync" not in _closed(res)
    assert L8P + "resets.0.port_description" not in _closed(res)
    assert rep["verdict"] != "PASS"


def test_an_ifdef_formal_datapath_swap_is_proved_on_the_synthesis_arm(tmp_path):
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q);
  reg [7:0] b;
  always @(posedge clk) if (rst) q <= 8'd0; else q <= d ^ b;
`ifdef FORMAL
  always @(posedge clk) b <= d & {8{(d == 8'd5) && (d == 8'd6)}};
`else
  always @(posedge clk) b <= d;
`endif
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, rtl, _l8()))
    sby = (tmp_path / res["sby"]).read_text()
    dut_reads = [l for l in sby.splitlines() if l.startswith("read_verilog") and "m.v" in l]
    assert dut_reads and all("-formal" not in l for l in dut_reads), dut_reads
    # the synthesis arm b <= d is not zero after reset
    assert L8P + "resets.0.port_description" not in _closed(res)
    assert rep["verdict"] != "PASS"


def test_an_initializer_is_not_silicon(tmp_path):
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q);
  reg [7:0] b = 8'd0;
  always @(posedge clk) if (rst) q <= 8'd0; else q <= d ^ b;
  always @(posedge clk) b <= b & d;
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, rtl, _l8()))
    assert "setattr -unset init" in (tmp_path / res["sby"]).read_text()
    assert L8P + "resets.0.port_description" not in _closed(res)
    assert rep["verdict"] != "PASS"


# ── FORMAL-only readers no longer push a correct design outside ─────────────
def test_a_formal_only_alias_does_not_push_a_correct_design_outside(tmp_path):
    rtl = """module m(input clk, input rst, input [7:0] d, output reg [7:0] q);
  reg [7:0] a;
  always @(posedge clk) if (rst) begin a <= 8'd0; q <= 8'd0; end else begin a <= d; q <= a; end
`ifdef FORMAL
  wire [7:0] f_a = a;
  always @(*) assert (f_a == a);
`endif
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, rtl, _l8()))
    assert L8P + "resets.0.port_description" in _closed(res)
    assert rep["verdict"] == "PASS", rep["findings"]


def test_a_formal_only_next_state_reader_does_not_push_a_correct_design_outside(tmp_path):
    rtl = """module m(input clk, input rst, input en, input [7:0] d, output reg [7:0] q);
  wire [7:0] q_nxt = en ? d : q;
  always @(posedge clk) if (rst) q <= 8'd0; else q <= q_nxt;
`ifdef FORMAL
  reg f_past_valid = 1'b0;
  always @(posedge clk) f_past_valid <= 1'b1;
  always @(posedge clk) if (f_past_valid && !$past(rst)) assert (q == $past(q_nxt));
`endif
endmodule
"""
    _, res, rep = _step5(_project(tmp_path, rtl, _l8()))
    assert L8P + "resets.0.port_description" in _closed(res)
    assert rep["verdict"] == "PASS", rep["findings"]


# ── the @connect inductive path ─────────────────────────────────────────────
def test_an_inductive_connect_run_is_not_refused_and_leaves_results_json_alone(tmp_path):
    _engine()
    import test_formal_property_run as t   # the repo's own @connect fixture
    rtl = tmp_path / "spm.v"
    rtl.write_text("""module spm #(parameter size = 32) (input clk, input rst,
    input [size-1:0] x, input y, output p);
  reg [size-1:0] s; reg [size-1:0] c; reg pr;
  always @(posedge clk) if (rst) begin s <= 0; c <= 0; pr <= 0; end
                        else begin s <= s ^ (x & {size{y}}); c <= c; pr <= s[0]; end
  assign p = pr;
endmodule
""")
    h = tmp_path / "formal_spm_inductive.sv"
    h.write_text(t._INV_HARNESS)
    fdir = tmp_path / "phase2/stage1/formal"
    fdir.mkdir(parents=True)
    sentinel = '{"verdict": "PASS", "note": "a standard Step-5 result"}\n'
    (fdir / "results.json").write_text(sentinel)
    res = fpr.run(tmp_path, invariant_harness=h, rtl=[rtl], top="formal_top",
                  container=None, timeout=300)
    assert res.get("verdict") != "ERROR", res.get("refusal")
    assert not res.get("refusal")
    assert (fdir / "results.json").read_text() == sentinel


def test_the_declared_set_includes_the_harness_connect_pragmas():
    harness = "// @connect peek_s = dut.s\n"
    assert fpr.observer_binding_mismatches(harness, "connect -set peek_s dut.s\n") == []
    assert fpr.observer_binding_mismatches(harness, "connect -set peek_s dut.c\n")
