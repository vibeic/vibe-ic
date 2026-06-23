"""Tests for step_determinism_gates — the divider phase-form + spec worked-example
oracle gates PROMOTED from the benchmark emit path (shape_b_sample_export.guard_export
checks C/D) into the production phase-2 chain (design_one_shot_runner).

§4.05 doctrine: both promoted gates are RESTRICTING/BLOCKING, so the load-bearing
half is the NEGATIVE no-leak proof — the correct level-decode divider golden and a
Mealy (same-cycle) worked-example design must PASS, never false-FAIL. The positive
cases prove the production step still catches the exact anti-patterns the benchmark
path blocks emit on. Fixtures are the SAME generic ones the underlying gate tests use.
"""
import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as r  # noqa: E402
import _path_layout as _pl  # noqa: E402

_HAS_IVERILOG = shutil.which("iverilog") is not None

# WRONG divider form: two intermediates OR-ed, each a SELF-TOGGLE, reset 0 (the trap).
RTL_TOGGLE_OR = """
module freqdiv(input clk, input rst_n, output clk_div);
  reg [2:0] cnt1, cnt2; reg clk_div1, clk_div2;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin cnt1<=0; clk_div1<=1'b0; end
    else begin
      if(cnt1==4) cnt1<=0; else cnt1<=cnt1+1;
      if(cnt1==2 || cnt1==4) clk_div1 <= ~clk_div1;
    end
  always @(negedge clk or negedge rst_n)
    if(!rst_n) begin cnt2<=0; clk_div2<=1'b0; end
    else begin
      if(cnt2==4) cnt2<=0; else cnt2<=cnt2+1;
      if(cnt2==2 || cnt2==4) clk_div2 <= ~clk_div2;
    end
  assign clk_div = clk_div1 | clk_div2;
endmodule
"""

# RIGHT divider form: same OR structure but LEVEL-DECODE, reset HIGH (the golden).
RTL_LEVEL_OR = """
module freqdiv(input clk, input rst_n, output clk_div);
  reg [2:0] cnt1, cnt2; reg clk_div1, clk_div2;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin cnt1<=0; clk_div1<=1'b1; end
    else begin
      if(cnt1<4) cnt1<=cnt1+1; else cnt1<=0;
      if(cnt1 < 5/2) clk_div1<=1'b1; else clk_div1<=1'b0;
    end
  always @(negedge clk or negedge rst_n)
    if(!rst_n) begin cnt2<=0; clk_div2<=1'b1; end
    else begin
      if(cnt2<4) cnt2<=cnt2+1; else cnt2<=0;
      if(cnt2 < 5/2) clk_div2<=1'b1; else clk_div2<=1'b0;
    end
  assign clk_div = clk_div1 | clk_div2;
endmodule
"""

SPEC = ("Implement a pulse detector. data_in is a 1-bit input. data_out is 1 the "
        "cycle the pulse completes. For example, if data_in is 01010, the data_out "
        "is 00101.")

# Moore (registered, one-cycle-late) output — the worked example forbids this.
RTL_MOORE = """
module pulse_detect(input clk, input rst_n, input data_in, output reg data_out);
  localparam IDLE=2'd0, GOT1=2'd1;
  reg [1:0] state;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin state<=IDLE; data_out<=1'b0; end
    else case(state)
      IDLE: begin state <= data_in ? GOT1 : IDLE; data_out<=1'b0; end
      GOT1: begin state <= data_in ? GOT1 : IDLE; data_out <= ~data_in; end
      default: begin state<=IDLE; data_out<=1'b0; end
    endcase
endmodule
"""


def _make_project(tmp_path: Path, rtl: str | None, *, spec: str = "") -> Path:
    proj = tmp_path / "proj"
    if rtl is not None:
        rtl_dir = _pl.rtl_dir(proj)
        rtl_dir.mkdir(parents=True, exist_ok=True)
        (rtl_dir / "top.v").write_text(rtl)
    if spec:
        pdir = _pl.input_prompt_dir(proj)
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "phase1_prompt.md").write_text(spec)
    return proj


def test_no_rtl_dir_skips(tmp_path):
    res = r.step_determinism_gates(tmp_path / "empty")
    assert res.status == "SKIP"


def test_self_toggle_or_divider_fails(tmp_path):
    proj = _make_project(tmp_path, RTL_TOGGLE_OR)
    res = r.step_determinism_gates(proj)
    assert res.status == "FAIL", res.detail
    assert "phase-form" in res.detail


def test_level_decode_golden_passes(tmp_path):
    # §4.05 no-leak: the CORRECT level-decode divider must NOT false-FAIL.
    proj = _make_project(tmp_path, RTL_LEVEL_OR)
    res = r.step_determinism_gates(proj)
    assert res.status == "PASS", res.detail


def test_non_divider_clean_passes(tmp_path):
    proj = _make_project(tmp_path, "module m(input a, output b); assign b=a; endmodule")
    res = r.step_determinism_gates(proj)
    assert res.status == "PASS", res.detail


@pytest.mark.skipif(not _HAS_IVERILOG, reason="worked-example oracle needs iverilog")
def test_worked_example_moore_fails(tmp_path):
    proj = _make_project(tmp_path, RTL_MOORE, spec=SPEC)
    res = r.step_determinism_gates(proj)
    assert res.status == "FAIL", res.detail
    assert "worked-example" in res.detail


@pytest.mark.skipif(not _HAS_IVERILOG, reason="worked-example oracle needs iverilog")
def test_worked_example_without_spec_does_not_fire(tmp_path):
    # No spec prose present → the oracle has nothing to replay → must not FAIL.
    proj = _make_project(tmp_path, RTL_MOORE)  # Moore RTL but NO spec
    res = r.step_determinism_gates(proj)
    assert res.status == "PASS", res.detail
