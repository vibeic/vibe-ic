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
SPEC_CLOCKED = (
    SPEC + " Inside an always block, sensitive to the positive edge of clk, "
    "implement pulse detection and output generation. Set data_out to 1 in "
    "the end cycle of the pulse."
)

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
def test_worked_example_moore_is_detected_and_repaired(tmp_path):
    """The step used to report a bare FAIL here and ship nothing. It now hands
    the oracle's verdict to `gate_directed_rtl_repair`, which is accepted only
    on that same oracle's explicit PASS — so the step reports PASS *and* the
    RTL on disk has actually changed and now reproduces the spec's example.
    Detection is still proven: the repair note names the defect."""
    proj = _make_project(tmp_path, RTL_MOORE, spec=SPEC)
    res = r.step_determinism_gates(proj)
    assert res.status == "PASS", res.detail
    assert "gate-directed repair" in res.detail
    assert "output-cycle-alignment" in res.detail
    # the repaired bytes are on disk and satisfy the oracle that raised it
    import worked_example_sequence_oracle_check as _w
    rtl = next(_pl.rtl_dir(proj).rglob("*.v")).read_text()
    assert rtl != RTL_MOORE
    assert _w.analyze(rtl, SPEC)["verdict"] == "PASS"


@pytest.mark.skipif(not _HAS_IVERILOG, reason="worked-example oracle needs iverilog")
def test_worked_example_phase_ambiguity_is_reported_as_skip(tmp_path):
    proj = _make_project(tmp_path, RTL_MOORE, spec=SPEC_CLOCKED)
    res = r.step_determinism_gates(proj)
    assert res.status == "PASS", res.detail
    assert "worked-example oracle SKIP (applicable, non-blocking)" in res.detail
    assert "phase-ambiguous" in res.detail
    assert res.extras["worked_example_oracle"]["phase_verdicts"] == {
        "pre-edge": "BLOCK",
        "post-edge": "PASS",
    }
    assert next(_pl.rtl_dir(proj).rglob("*.v")).read_text() == RTL_MOORE


RTL_ALWAYS_ZERO = """
module top(input clk, input rst_n, input data_in, output data_out);
  assign data_out = 1'b0;
endmodule
"""


@pytest.mark.skipif(not _HAS_IVERILOG, reason="worked-example oracle needs iverilog")
def test_worked_example_all_phase_mismatch_stops_phase2(tmp_path):
    proj = _make_project(tmp_path, RTL_ALWAYS_ZERO, spec=SPEC_CLOCKED)
    res = r.step_determinism_gates(proj)
    assert res.status == "FAIL", res.detail
    assert "in every supported sampling phase" in res.detail
    assert next(_pl.rtl_dir(proj).rglob("*.v")).read_text() == RTL_ALWAYS_ZERO


# RTL whose output lags by THREE cycles: the repair transform applies and the
# result compiles, but one cycle less is still wrong — so no repair is accepted
# and the step must still FAIL. This is the negative control that keeps the
# repair path from being a way to turn every FAIL into a PASS.
RTL_TOO_LATE = """
module top(input clk, input rst_n, input data_in, output reg data_out);
  reg d1, d2;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin d1<=1'b0; d2<=1'b0; data_out<=1'b0; end
    else begin d1 <= data_in; d2 <= d1; data_out <= d2; end
endmodule
"""


@pytest.mark.skipif(not _HAS_IVERILOG, reason="worked-example oracle needs iverilog")
def test_unrepairable_worked_example_defect_still_fails(tmp_path):
    proj = _make_project(tmp_path, RTL_TOO_LATE, spec=SPEC)
    res = r.step_determinism_gates(proj)
    assert res.status == "FAIL", res.detail
    assert "worked-example" in res.detail
    # and the RTL must be left exactly as authored
    assert next(_pl.rtl_dir(proj).rglob("*.v")).read_text() == RTL_TOO_LATE


@pytest.mark.skipif(not _HAS_IVERILOG, reason="worked-example oracle needs iverilog")
def test_worked_example_without_spec_does_not_fire(tmp_path):
    # No spec prose present → the oracle has nothing to replay → must not FAIL.
    proj = _make_project(tmp_path, RTL_MOORE)  # Moore RTL but NO spec
    res = r.step_determinism_gates(proj)
    assert res.status == "PASS", res.detail


# --- §4.05 cross-module fan-out fix (PR #77 gatekeeper review HIGH) ---------

# A CORRECT top that reproduces the disclosed trace (Mealy falling-edge form).
RTL_PULSE_OK = """
module pulse_detect(input clk, input rst_n, input data_in, output data_out);
  reg prev;
  always @(posedge clk or negedge rst_n) if(!rst_n) prev<=0; else prev<=data_in;
  assign data_out = prev & ~data_in;
endmodule
"""

# A SEPARATE, internally-correct reusable cell that SHARES the generic 1-bit
# data_in/data_out port names (a registered inverter) — the false-fail vector.
# A `pulse_detect`-named top whose output lags by THREE cycles: the repair
# transform applies and compiles, but one cycle less is still wrong, so no
# repair is accepted and the step must still FAIL.
RTL_TOO_LATE_PD = """
module pulse_detect(input clk, input rst_n, input data_in, output reg data_out);
  reg d1, d2;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin d1<=1'b0; d2<=1'b0; data_out<=1'b0; end
    else begin d1 <= data_in; d2 <= d1; data_out <= d2; end
endmodule
"""

RTL_SIBLING_INV = """
module inv_reg(input clk, input rst_n, input data_in, output reg data_out);
  always @(posedge clk or negedge rst_n) if(!rst_n) data_out<=0; else data_out<=~data_in;
endmodule
"""


def _make_multimodule(tmp_path, top_rtl, sibling_rtl, *, spec=SPEC):
    proj = tmp_path / "proj"
    rtl_dir = _pl.rtl_dir(proj)
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "pulse_detect.v").write_text(top_rtl)
    (rtl_dir / "inv_reg.v").write_text(sibling_rtl)
    pdir = _pl.input_prompt_dir(proj)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "phase1_prompt.md").write_text(spec)
    return proj


@pytest.mark.skipif(not _HAS_IVERILOG, reason="worked-example oracle needs iverilog")
def test_correct_top_with_sibling_sharing_port_names_passes(tmp_path):
    # The repro from the gatekeeper review: a correct DUT + a correct sibling that
    # shares data_in/data_out must NOT false-FAIL — the oracle runs on the TOP only.
    proj = _make_multimodule(tmp_path, RTL_PULSE_OK, RTL_SIBLING_INV)
    res = r.step_determinism_gates(proj, "pulse_detect")
    assert res.status == "PASS", res.detail


@pytest.mark.skipif(not _HAS_IVERILOG, reason="worked-example oracle needs iverilog")
def test_buggy_top_still_caught_despite_sibling(tmp_path):
    # The fix must NOT over-suppress: a Moore-lag TOP is still CAUGHT even with a
    # sibling present (oracle scoped to the top, but the top itself is the bug).
    # It is now caught AND repaired, so the proof of detection is the repair note
    # naming the defect; the sibling must be left untouched.
    proj = _make_multimodule(tmp_path, RTL_MOORE, RTL_SIBLING_INV)
    res = r.step_determinism_gates(proj, "pulse_detect")
    assert res.status == "PASS", res.detail
    assert "gate-directed repair" in res.detail
    assert "output-cycle-alignment" in res.detail
    joined = "\n".join(p.read_text() for p in _pl.rtl_dir(proj).rglob("*.v"))
    assert RTL_SIBLING_INV.strip() in joined      # sibling untouched
    assert RTL_MOORE.strip() not in joined        # top actually rewritten


@pytest.mark.skipif(not _HAS_IVERILOG, reason="worked-example oracle needs iverilog")
def test_unrepairable_buggy_top_still_fails_despite_sibling(tmp_path):
    # The FAIL path must survive the repair wiring: a top whose defect no
    # transform can fix still reports FAIL, with the sibling untouched.
    proj = _make_multimodule(tmp_path, RTL_TOO_LATE_PD, RTL_SIBLING_INV)
    res = r.step_determinism_gates(proj, "pulse_detect")
    assert res.status == "FAIL", res.detail
    assert "worked-example" in res.detail and "pulse_detect" in res.detail


@pytest.mark.skipif(not _HAS_IVERILOG, reason="worked-example oracle needs iverilog")
def test_unresolvable_top_skips_oracle(tmp_path):
    # >1 module, no top_name, no L9 → the top is unidentifiable → oracle SKIPs
    # (no guess) rather than risk a false block.
    proj = _make_multimodule(tmp_path, RTL_MOORE, RTL_SIBLING_INV)
    res = r.step_determinism_gates(proj)  # no top_name
    assert res.status == "PASS", res.detail
