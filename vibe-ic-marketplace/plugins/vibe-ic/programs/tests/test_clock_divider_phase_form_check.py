"""Tests for clock_divider_phase_form_check.py — the odd / double-edge divider
PHASE-FORM gate (freq_divbyodd pass@6 = 0/6 deterministic-capture).

§4.05 doctrine: this is a RESTRICTING/BLOCKING gate, so the load-bearing half is the
NEGATIVE no-leak proof — the correct LEVEL-DECODE golden form, a plain even divider,
and a non-divider must all SKIP. The positive cases prove it catches the phase-wrong
self-toggle two-edge-OR form. Fixtures are generic (chip-AGNOSTIC), shaped from the
real golden vs the real failing blind attempts.
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import clock_divider_phase_form_check as g  # noqa: E402

# WRONG form: two intermediates OR-ed, each a SELF-TOGGLE, reset 0 (the trap).
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

# RIGHT form: same two-edge-OR structure but LEVEL-DECODE, reset HIGH (the golden).
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

# legitimate EVEN divider: a SINGLE toggled output, NO OR of two intermediates.
RTL_EVEN = """
module evendiv(input clk, input rst_n, output reg clk_div);
  reg [3:0] cnt;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin cnt<=0; clk_div<=0; end
    else if(cnt==3) begin cnt<=0; clk_div<=~clk_div; end
    else cnt<=cnt+1;
endmodule
"""

RTL_NON_DIVIDER = "module orblk(input a, input b, output y); assign y = a | b; endmodule"


def _risky(rtl: str) -> bool:
    return g.analyze(rtl)["phase_risky"]


# -------- POSITIVE: the trap fires --------
def test_self_toggle_two_edge_or_form_fires():
    res = g.analyze(RTL_TOGGLE_OR)
    assert res["phase_risky"] is True
    f = res["findings"][0]
    assert f["output"] == "clk_div"
    assert set(f["or_operands"]) == {"clk_div1", "clk_div2"}
    assert f["self_toggled"]  # at least one OR-operand is self-toggled


# -------- NEGATIVE no-leak (load-bearing): correct forms SKIP --------
def test_level_decode_golden_form_does_not_fire():
    assert _risky(RTL_LEVEL_OR) is False  # the golden realisation must never block


def test_even_divider_single_toggle_does_not_fire():
    assert _risky(RTL_EVEN) is False  # legitimate even-divide idiom


def test_non_divider_or_does_not_fire():
    assert _risky(RTL_NON_DIVIDER) is False


def test_self_toggle_without_or_output_does_not_fire():
    # an intermediate self-toggles but the OUTPUT is not an OR of two of them
    rtl = ("module m(input clk, output clk_div); reg clk_div1;"
           " always @(posedge clk) clk_div1 <= ~clk_div1;"
           " assign clk_div = clk_div1; endmodule")
    assert _risky(rtl) is False


# -------- Step-2.7 §4.05 reproduced FALSE-FIRES, now pinned SKIP --------
# A div-by-2 in the DEGENERATE OR form: ONE self-toggle operand + one constant.
# iverilog proved this is waveform-IDENTICAL to the level-decode golden, yet the
# pre-narrowing gate BLOCKed it. Requires >=2 self-toggle operands ⇒ now SKIPs.
RTL_EVEN_OR_SINGLE_TOGGLE = """
module d2(input clk, input rst_n, output clk_div);
  reg clk_div1, clk_div2;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin clk_div1<=1'b0; clk_div2<=1'b0; end
    else begin clk_div1<=~clk_div1; clk_div2<=1'b0; end
  assign clk_div = clk_div1 | clk_div2;
endmodule
"""

# A NON-clock-divider: two ping-pong status flags merely NAMED with a `div`
# substring, ORed. No `clk`/`clock` root ⇒ the tightened _DIVOUT_RE excludes it.
RTL_NON_CLOCK_DIV_SUBSTRING = """
module merge(input c, input rst_n, output any_active);
  reg bank_a_div, bank_b_en;
  always @(posedge c or negedge rst_n)
    if(!rst_n) begin bank_a_div<=1'b0; bank_b_en<=1'b0; end
    else begin bank_a_div<=~bank_a_div; bank_b_en<=~bank_b_en; end
  assign any_active = bank_a_div | bank_b_en;
endmodule
"""

# A clock-named two-edge-OR whose intermediates are reset HIGH (plausibly
# phase-correct) — defense-in-depth: the gate must err to false-SKIP.
RTL_DUAL_TOGGLE_RESET_HIGH = """
module dhi(input clk, input rst_n, output clk_div);
  reg clk_div1, clk_div2;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) clk_div1<=1'b1; else clk_div1 <= ~clk_div1;
  always @(negedge clk or negedge rst_n)
    if(!rst_n) clk_div2<=1'b1; else clk_div2 <= ~clk_div2;
  assign clk_div = clk_div1 | clk_div2;
endmodule
"""


def test_even_divider_OR_form_single_toggle_does_not_fire():
    # HIGH false-fire: degenerate OR with ONE self-toggle is phase-CORRECT
    assert _risky(RTL_EVEN_OR_SINGLE_TOGGLE) is False


def test_non_clock_div_substring_or_does_not_fire():
    # MED false-fire: a `div`-substring name without a clk/clock root is not a clock
    assert _risky(RTL_NON_CLOCK_DIV_SUBSTRING) is False


def test_dual_self_toggle_reset_high_does_not_fire():
    # defense-in-depth: reset-HIGH self-toggle is plausibly phase-correct → SKIP
    assert _risky(RTL_DUAL_TOGGLE_RESET_HIGH) is False


# -------- CLI --------
def test_cli_block_on_toggle(tmp_path, capsys):
    p = tmp_path / "d.v"; p.write_text(RTL_TOGGLE_OR)
    rc = g.main([str(p), "--strict"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "BLOCK" in out and "LEVEL-DECODE" in out


def test_cli_pass_on_level(tmp_path, capsys):
    p = tmp_path / "d.v"; p.write_text(RTL_LEVEL_OR)
    assert g.main([str(p)]) == 0
    assert "PASS" in capsys.readouterr().out


def test_cli_missing_file_is_arg_error(tmp_path):
    assert g.main([str(tmp_path / "nope.v")]) == 2


# -------- WIRED into the Shape-B emit guard (GATE-AS-SOLE-EMIT-PATH) --------
def test_shape_b_guard_blocks_toggle_form(tmp_path):
    import shape_b_sample_export as sb
    p = tmp_path / "freqdiv.v"; p.write_text(RTL_TOGGLE_OR)
    ok, problems = sb.guard_export(p)
    assert ok is False
    assert any("phase-form trap" in s for s in problems), problems


def test_shape_b_guard_passes_level_decode_form(tmp_path):
    import shape_b_sample_export as sb
    p = tmp_path / "freqdiv.v"; p.write_text(RTL_LEVEL_OR)
    ok, problems = sb.guard_export(p)
    # the divider phase-form check must NOT fire on the golden level-decode form
    assert not any("phase-form trap" in s for s in problems), problems


def test_shape_b_guard_no_divider_problem_for_even_divider(tmp_path):
    import shape_b_sample_export as sb
    p = tmp_path / "even.v"; p.write_text(RTL_EVEN)
    _ok, problems = sb.guard_export(p)
    assert not any("phase-form trap" in s for s in problems), problems
