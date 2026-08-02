"""Tests for clock_divider_ratio_oracle_check.py — the clock divider / generator
WAVEFORM-MEASUREMENT oracle (freq_divbyeven / freq_divbyfrac false-certificate
capture).

This is a RESTRICTING/BLOCKING gate, so the load-bearing half is the NEGATIVE
no-leak proof: a CORRECT even / odd / fractional divider and a free-running
generator must all PASS, and a non-divider (or an undriveable design) must SKIP.
The positive cases prove it catches the division-RATIO, DUTY, and RESET-VALUE
bugs that the structural gates cannot see. Every fixture is generic
(chip-AGNOSTIC) and authored from the spec prose — never from any golden.
"""
import shutil
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import clock_divider_ratio_oracle_check as g  # noqa: E402

HAVE_IV = shutil.which("iverilog") is not None and shutil.which("vvp") is not None
requires_iv = pytest.mark.skipif(not HAVE_IV, reason="iverilog/vvp unavailable")

# ── spec prose (chip-AGNOSTIC; mirrors the RTLLM divider/generator wording) ──
SPEC_EVEN = (
    "Frequency divider that divides the input clock frequency by even numbers. "
    "The NUM_DIV parameter specifies the division factor, which must be even. "
    "When reset (rst_n) is low, the counter and the divided clock signal "
    "(clk_div) are initialized to zero. Input ports clk, rst_n. Output clk_div.")
SPEC_ODD = (
    "A frequency divider that divides the input clock frequency by odd numbers. "
    "The module divides the input clock by an odd number NUM_DIV, default 5. "
    "Input ports clk, rst_n. Output clk_div.")
SPEC_FRAC = (
    "A frequency divider that divides the input clock frequency by fractional "
    "values, generating a 3.5x division using double-edge clocking. Input ports "
    "clk, rst_n. Output clk_div.")
SPEC_GEN = (
    "A clock generator module that produces a periodic clock signal, toggling its "
    "output every half of the PERIOD parameter. Parameter PERIOD = 10. Output clk.")
SPEC_ADDER = "A simple 8-bit adder that outputs the sum of a and b."

# ── correct RTL (authored from the spec prose) ──────────────────────────────
EVEN_OK = """
module freq_diveven #(parameter NUM_DIV = 4) (input clk, input rst_n, output reg clk_div);
  reg [3:0] cnt;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin cnt<=0; clk_div<=0; end
    else if(cnt < NUM_DIV/2 - 1) cnt<=cnt+1;
    else begin cnt<=0; clk_div<=~clk_div; end
endmodule
"""
ODD_OK = """
module freq_divbyodd #(parameter NUM_DIV = 5) (input clk, input rst_n, output clk_div);
  reg [3:0] cnt1, cnt2; reg clk_div1, clk_div2;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) cnt1<=0; else if(cnt1==NUM_DIV-1) cnt1<=0; else cnt1<=cnt1+1;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) clk_div1<=1'b1; else if(cnt1<(NUM_DIV/2)) clk_div1<=1'b1; else clk_div1<=1'b0;
  always @(negedge clk or negedge rst_n)
    if(!rst_n) cnt2<=0; else if(cnt2==NUM_DIV-1) cnt2<=0; else cnt2<=cnt2+1;
  always @(negedge clk or negedge rst_n)
    if(!rst_n) clk_div2<=1'b1; else if(cnt2<(NUM_DIV/2)) clk_div2<=1'b1; else clk_div2<=1'b0;
  assign clk_div = clk_div1 | clk_div2;
endmodule
"""
FRAC_OK = """
module freq_divbyfrac (input clk, input rst_n, output clk_div);
  parameter MUL2_DIV_CLK = 7;
  reg [3:0] cnt; reg clk_ps, clk_ng;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) cnt<=0; else cnt<=(cnt==MUL2_DIV_CLK-1)?0:cnt+1;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) clk_ps<=0; else clk_ps<=(cnt<2)||(cnt>=4 && cnt<6);
  always @(negedge clk or negedge rst_n)
    if(!rst_n) clk_ng<=0; else clk_ng<=clk_ps;
  assign clk_div = clk_ps | clk_ng;
endmodule
"""
GEN_OK = """
module clkgenerator #(parameter PERIOD = 10) (output reg clk);
  initial clk = 1'b0;
  always #(PERIOD/2) clk = ~clk;
endmodule
"""

# ── buggy RTL ───────────────────────────────────────────────────────────────
EVEN_RATIO_BUG = EVEN_OK.replace("cnt < NUM_DIV/2 - 1", "cnt < NUM_DIV/2")
EVEN_DUTY_BUG = """
module freq_diveven #(parameter NUM_DIV = 8) (input clk, input rst_n, output reg clk_div);
  reg [3:0] cnt;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin cnt<=0; clk_div<=0; end
    else begin cnt <= (cnt==NUM_DIV-1)?0:cnt+1; clk_div <= (cnt < NUM_DIV/4); end
endmodule
"""
EVEN_RESET_BUG = EVEN_OK.replace("cnt<=0; clk_div<=0;", "cnt<=0; clk_div<=1'b1;")
FRAC_INT_BUG = """
module freq_divbyfrac (input clk, input rst_n, output reg clk_div);
  reg [3:0] cnt;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin cnt<=0; clk_div<=0; end
    else if(cnt<1) cnt<=cnt+1; else begin cnt<=0; clk_div<=~clk_div; end
endmodule
"""
GEN_STUCK = """
module clkgenerator #(parameter PERIOD = 10) (output reg clk);
  initial clk = 1'b0;
endmodule
"""
# a divider with an extra undriveable input (enable) — must SKIP, never BLOCK
EVEN_WITH_ENABLE = """
module freq_diveven #(parameter NUM_DIV = 4) (input clk, input rst_n, input en, output reg clk_div);
  reg [3:0] cnt;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin cnt<=0; clk_div<=0; end
    else if(en) begin
      if(cnt < NUM_DIV/2 - 1) cnt<=cnt+1; else begin cnt<=0; clk_div<=~clk_div; end
    end
endmodule
"""
ADDER = "module adder(input [7:0] a, input [7:0] b, output [8:0] sum); assign sum=a+b; endmodule"


def _v(rtl, spec):
    return g.analyze(rtl, spec)["verdict"]


# ── POSITIVE: the oracle catches the waveform bug ───────────────────────────
@requires_iv
def test_even_ratio_off_by_one_blocks():
    r = g.analyze(EVEN_RATIO_BUG, SPEC_EVEN)
    assert r["verdict"] == "BLOCK" and r["failure"] == "ratio_mismatch"
    assert r["measured_ratio"] != r["expected_ratio"]


@requires_iv
def test_even_wrong_duty_blocks():
    r = g.analyze(EVEN_DUTY_BUG, SPEC_EVEN)
    assert r["verdict"] == "BLOCK" and r["failure"] == "duty_mismatch"


@requires_iv
def test_even_wrong_reset_value_blocks():
    r = g.analyze(EVEN_RESET_BUG, SPEC_EVEN)
    assert r["verdict"] == "BLOCK" and r["failure"] == "reset_value_mismatch"


@requires_iv
def test_frac_integer_substitute_blocks():
    r = g.analyze(FRAC_INT_BUG, SPEC_FRAC)
    assert r["verdict"] == "BLOCK" and r["failure"] == "ratio_mismatch"


@requires_iv
def test_generator_stuck_blocks():
    r = g.analyze(GEN_STUCK, SPEC_GEN)
    assert r["verdict"] == "BLOCK" and r["failure"] == "no_periodic_output"


# ── NEGATIVE no-leak (load-bearing): correct designs must PASS ──────────────
@requires_iv
def test_even_correct_passes():
    assert _v(EVEN_OK, SPEC_EVEN) == "PASS"


@requires_iv
def test_odd_correct_passes():
    # the ratio oracle passes a correct-PERIOD odd divider; the odd PHASE bug is
    # the separate clock_divider_phase_form_check's job (complementary coverage).
    assert _v(ODD_OK, SPEC_ODD) == "PASS"


@requires_iv
def test_frac_correct_passes():
    assert _v(FRAC_OK, SPEC_FRAC) == "PASS"


@requires_iv
def test_generator_correct_passes():
    assert _v(GEN_OK, SPEC_GEN) == "PASS"


# ── NEGATIVE no-leak: not-applicable designs SKIP (never BLOCK) ─────────────
def test_non_divider_skips():
    assert _v(ADDER, SPEC_ADDER) == "SKIP"


def test_divider_spec_but_adder_rtl_skips():
    # divider spec, but the RTL has no 1-bit clock output → SKIP, not a false block
    assert _v(ADDER, SPEC_EVEN) == "SKIP"


@requires_iv
def test_extra_undriveable_input_skips():
    r = g.analyze(EVEN_WITH_ENABLE, SPEC_EVEN)
    assert r["verdict"] == "SKIP" and "extra input" in r["reason"]


def test_empty_inputs_skip():
    assert g.analyze("", SPEC_EVEN)["verdict"] == "SKIP"
    assert g.analyze(EVEN_OK, "")["verdict"] == "SKIP"


# ── GENERALITY: a plain prose design doc, NO benchmark / harness anywhere ────
GENERIC_DOC = ("Internal design note: implement a clock divider that divides the "
               "input clock frequency by 4 with a 50% duty cycle. Ports: clk, "
               "rst_n, clk_div.")
GENERIC_OK = """
module my_divider (input clk, input rst_n, output reg clk_div);
  reg [2:0] cnt;
  always @(posedge clk or negedge rst_n)
    if(!rst_n) begin cnt<=0; clk_div<=0; end
    else if(cnt < 4/2 - 1) cnt<=cnt+1; else begin cnt<=0; clk_div<=~clk_div; end
endmodule
"""
GENERIC_BUG = GENERIC_OK.replace("cnt < 4/2 - 1", "cnt < 4/2")


@requires_iv
def test_generality_passes_correct_prose_divider():
    # module named `my_divider` — the rule keys on the spec relationship, not a name
    assert _v(GENERIC_OK, GENERIC_DOC) == "PASS"


@requires_iv
def test_generality_blocks_buggy_prose_divider():
    r = g.analyze(GENERIC_BUG, GENERIC_DOC)
    assert r["verdict"] == "BLOCK" and r["failure"] == "ratio_mismatch"


# ── parsing units (no sim required) ─────────────────────────────────────────
def test_int_literal_parsing():
    assert g._int_literal("10") == 10
    assert g._int_literal("4'd10") == 10
    assert g._int_literal("8'hA") == 10
    assert g._int_literal("4'b1010") == 10
    assert g._int_literal("2*5") is None


def test_spec_fraction_unique_only():
    assert g._spec_fraction("3.5x fractional divider") == 3.5
    # two distinct fractional factors → ambiguous → None
    assert g._spec_fraction("divide by 3.5 or 2.5 fractional") is None


# ── CLI ─────────────────────────────────────────────────────────────────────
@requires_iv
def test_cli_block(tmp_path, capsys):
    rtl = tmp_path / "d.v"; rtl.write_text(EVEN_RATIO_BUG)
    spec = tmp_path / "s.txt"; spec.write_text(SPEC_EVEN)
    assert g.main(["--rtl", str(rtl), "--spec", str(spec)]) == 1
    assert "BLOCK" in capsys.readouterr().out


@requires_iv
def test_cli_pass(tmp_path, capsys):
    rtl = tmp_path / "d.v"; rtl.write_text(EVEN_OK)
    spec = tmp_path / "s.txt"; spec.write_text(SPEC_EVEN)
    assert g.main(["--rtl", str(rtl), "--spec", str(spec)]) == 0


def test_cli_missing_file_is_arg_error(tmp_path):
    assert g.main(["--rtl", str(tmp_path / "nope.v"),
                   "--spec", str(tmp_path / "no.txt")]) == 2


# ── WIRED into the Shape-B emit guard (GATE-AS-SOLE-EMIT-PATH) ───────────────
@requires_iv
def test_shape_b_guard_blocks_ratio_bug(tmp_path):
    import shape_b_sample_export as sb
    p = tmp_path / "freq_diveven.v"; p.write_text(EVEN_RATIO_BUG)
    ok, problems = sb.guard_export(p, prompt_text=SPEC_EVEN)
    assert ok is False
    assert any("waveform oracle" in s for s in problems), problems


@requires_iv
def test_shape_b_guard_passes_correct_divider(tmp_path):
    import shape_b_sample_export as sb
    p = tmp_path / "freq_diveven.v"; p.write_text(EVEN_OK)
    _ok, problems = sb.guard_export(p, prompt_text=SPEC_EVEN)
    assert not any("waveform oracle" in s for s in problems), problems


def test_shape_b_guard_no_waveform_problem_without_prompt(tmp_path):
    # no prompt_text → the spec-derived oracle stays disarmed (fail-safe)
    import shape_b_sample_export as sb
    p = tmp_path / "freq_diveven.v"; p.write_text(EVEN_RATIO_BUG)
    _ok, problems = sb.guard_export(p)
    assert not any("waveform oracle" in s for s in problems), problems


# ── WIRED into the general Phase-2 runner (prove-by-run the gate stops the flow) ─
def _scaffold(tmp_path, rtl):
    (tmp_path / "phase1/input_prompt").mkdir(parents=True)
    (tmp_path / "phase2/stage1/rtl").mkdir(parents=True)
    (tmp_path / "phase1/input_prompt/prompt.txt").write_text(SPEC_EVEN)
    (tmp_path / "phase2/stage1/rtl/freq_diveven.v").write_text(rtl)
    return tmp_path


@requires_iv
def test_runner_determinism_gate_fails_on_ratio_bug(tmp_path):
    import design_one_shot_runner as R
    proj = _scaffold(tmp_path, EVEN_RATIO_BUG)
    res = R.step_determinism_gates(proj, top_name="freq_diveven")
    assert res.status == "FAIL"
    assert "waveform oracle" in (res.detail or "")


@requires_iv
def test_runner_determinism_gate_passes_correct_divider(tmp_path):
    import design_one_shot_runner as R
    proj = _scaffold(tmp_path, EVEN_OK)
    res = R.step_determinism_gates(proj, top_name="freq_diveven")
    assert res.status == "PASS"


# ── folded in at merge: the message must not call the RTL "the spec" ────────
#
# For the parameterised family the expected ratio IS the RTL's own declared
# default — deliberately, to avoid a `#()`-override elaboration failure on a
# body-declared parameter. The BEHAVIOUR is sound and documented; the wording
# was not. MEASURED, with the RTL changed to `NUM_DIV = 7` against a spec whose
# only stated ratio is "defaults to 5":
#
#     measured ratio 7.000 ~ spec 7.0
#
# calling 7.0 "spec" when the spec says 5. The verdict was right by the rule and
# the sentence was false — and the sentence is what a reader reaches for when
# asking why a design was let through, or why one was blocked.
def test_the_message_says_EXPECTED_and_names_where_the_number_came_from():
    import pathlib as _pl
    src = (_pl.Path(__file__).resolve().parents[1]
           / "clock_divider_ratio_oracle_check.py").read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "~ spec {contract.ratio}" not in body, \
        "the PASS line calls the RTL-derived ratio 'spec'"
    assert "!= spec " not in body, "the BLOCK line calls it 'spec'"
    assert "expected " in body
    # the provenance travels with the number, so "expected 7.0" is checkable
    assert "{contract.note}" in body
