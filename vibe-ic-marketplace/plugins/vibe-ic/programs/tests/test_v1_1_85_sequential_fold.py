"""v1.1.85 — RTLLM-prose SEQUENTIAL fold into the three canonical solvers.

The same sequential families the VE-phrasing solvers already own, now also read in
the RTLLM structured-prose dialect ("Module name:/Input ports:" + a behaviour
paragraph), folded as a parse-or-SKIP fallback AFTER the native VE shapes:

  counter_advanced_synth : Johnson (JC_counter), modulo-N (counter_12),
                           up/down (up_down_counter), ring (ring_counter — emit
                           correct RTL; iverilog Category-D floor on the TB's
                           VCS-only array-init), and the frequency dividers
                           (freq_div /2,/10,/100; freq_divbyodd NUM_DIV=5;
                           freq_divbyfrac MUL2_DIV_CLK=7). freq_divbyeven's divide
                           value is UNSTATED in prose -> §4.05 SKIP.
  shift_register_synth   : right_shifter (PARSE 8-bit, d->MSB). barrel_shifter does
                           NOT state LEFT vs RIGHT in its prose -> §4.05 SKIP (a
                           guessed direction is a coin-flip cheat).
  lfsr_synth             : Fibonacci external-XOR LEFT-shift LFSR (feedback parsed
                           exactly from prose). Galois-right path unchanged.

This test pins the §4.05 NO-CHEAT boundary with NEAR-MISS negatives — the three the
task mandates plus siblings — and host-scores the canonical positives when the
RTLLM dataset + iverilog/vvp are present. Pure prose in; no chip name, magic
constant, or dataset port-name gate anywhere in the fold.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))

import counter_advanced_synth as CA  # noqa: E402
import lfsr_synth as LF              # noqa: E402
import shift_register_synth as SR    # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

RTLLM = corpus_path("_extbench/RTLLM")


def _have_iverilog():
    from shutil import which
    return which("iverilog") and which("vvp")


def _host_pass(rtl, tb_path):
    """Compile dut RTL + the RTLLM testbench with iverilog; True iff the TB prints
    'Your Design Passed'. None means tool/compile error (e.g. the ring_counter
    Category-D floor) — distinguished from a functional FAIL."""
    with tempfile.TemporaryDirectory() as d:
        dut = os.path.join(d, "dut.v")
        open(dut, "w").write(rtl)
        outb = os.path.join(d, "o")
        c = subprocess.run(["iverilog", "-g2012", "-o", outb, dut, str(tb_path)],
                           capture_output=True, text=True)
        if c.returncode != 0:
            return None  # compile error (tool floor)
        r = subprocess.run(["vvp", outb], capture_output=True, text=True)
        log = r.stdout + r.stderr
        return "Your Design Passed" in log


def _prose(rel):
    return (RTLLM / rel / "design_description.txt").read_text(errors="replace")


def _tb(rel):
    return RTLLM / rel / "testbench.v"


# --------------------------------------------------------------------------- #
# (a) near-miss: a "shift LEFT" barrel emits << (or SKIPs) but NEVER >>.       #
# --------------------------------------------------------------------------- #
def test_barrel_left_never_emits_right():
    # The dataset barrel_shifter states NO direction -> must SKIP.
    if RTLLM.exists():
        assert SR.synth(_prose("Memory/Shifter/barrel_shifter"),
                        "barrel_shifter") is None
    # A near-miss variant that DOES state "shift left" must, if it emits at all,
    # use a LEFT shift (<< / low-end zero-fill), and must NEVER emit a right shift.
    left_prose = (
        "Module name:\n    barrel_shifter\n"
        "Function:\n    An 8-bit barrel shifter that performs a logical shift left.\n"
        "Input ports:\n    in [7:0]: 8-bit input to be shifted.\n"
        "    ctrl [2:0]: 3-bit control signal; each bit shifts left by 1, 2, or 4.\n"
        "Output ports:\n    out [7:0]: 8-bit shifted output.\n"
        "    The input is shifted left based on ctrl.\n")
    rtl = SR.synth(left_prose, "barrel_shifter")
    if rtl is not None:
        # left shift: vacated low bits filled with 0 ({.., N'b0}); never a
        # right-shift slice [7:amt] feeding the high end.
        assert "'b0}" in rtl or "<<" in rtl
        assert "[7:1]" not in rtl and "[7:2]" not in rtl and "[7:4]" not in rtl


def test_barrel_right_variant_never_emits_left():
    # symmetric guard: a stated "shift right" near-miss must not emit a left shift.
    right_prose = (
        "Module name:\n    barrel_shifter\n"
        "Function:\n    An 8-bit barrel shifter that performs a logical shift right.\n"
        "Input ports:\n    in [7:0]: 8-bit input to be shifted.\n"
        "    ctrl [2:0]: 3-bit control; each bit shifts right by 1, 2, or 4.\n"
        "Output ports:\n    out [7:0]: 8-bit shifted output.\n"
        "    The input is shifted right based on ctrl.\n")
    rtl = SR.synth(right_prose, "barrel_shifter")
    if rtl is not None:
        # right shift: high bits filled with 0, low end dropped — a {in[6:0], 0}
        # left-concat must NOT appear.
        assert "{in[6:0]" not in rtl and "{st0[6:0]" not in rtl


# --------------------------------------------------------------------------- #
# (b) freq-frac stating N=5 emits N=5, not the dataset's 7.                    #
# --------------------------------------------------------------------------- #
def test_freq_frac_parses_stated_cycle_count_not_hardcoded():
    base = (
        "Module name:\n    freq_divbyfrac\n"
        "Input ports:\n    clk: Input clock signal.\n"
        "    rst_n: Active low reset signal.\n"
        "Output ports:\n    clk_div: Fractionally divided clock output.\n"
        "A fractional frequency divider using the double-edge clocking technique. "
        "The counter cycles through {N} clock cycles (MUL2_DIV_CLK = {N}).\n")
    r5 = CA.synth(base.replace("{N}", "5"), "freq_divbyfrac")
    r7 = CA.synth(base.replace("{N}", "7"), "freq_divbyfrac")
    assert r5 is not None and r7 is not None
    assert "MUL2_DIV_CLK = 5" in r5 and "MUL2_DIV_CLK = 7" not in r5
    assert "MUL2_DIV_CLK = 7" in r7 and "MUL2_DIV_CLK = 5" not in r7


def test_freq_odd_parses_stated_default_not_hardcoded():
    base = (
        "Module name:\n    freq_divbyodd\n"
        "Input ports:\n    clk: Input clock signal.\n"
        "    rst_n: Active low reset signal.\n"
        "Output ports:\n    clk_div: Divided clock output.\n"
        "A frequency divider that divides by an odd number. The parameter NUM_DIV, "
        "which defaults to {N}, sets the divisor.\n")
    r3 = CA.synth(base.replace("{N}", "3"), "freq_divbyodd")
    r9 = CA.synth(base.replace("{N}", "9"), "freq_divbyodd")
    assert r3 is not None and "NUM_DIV = 3" in r3
    assert r9 is not None and "NUM_DIV = 9" in r9 and "NUM_DIV = 3" not in r9


# --------------------------------------------------------------------------- #
# (c) unstated divide / taps -> SKIP.                                         #
# --------------------------------------------------------------------------- #
def test_freq_even_unstated_divide_skips():
    # the dataset freq_divbyeven names NUM_DIV but states no concrete value -> SKIP
    # (emitting the golden's default 6 would be reading the reference = a cheat).
    if RTLLM.exists():
        assert CA.synth(_prose("Miscellaneous/Frequency divider/freq_divbyeven"),
                        "freq_divbyeven") is None
    # an even divider with no stated NUM_DIV and no concrete divisor -> SKIP.
    prose = (
        "Module name:\n    freq_divbyeven\n"
        "Input ports:\n    clk: Input clock signal.\n"
        "    rst_n: Active low reset signal.\n"
        "Output ports:\n    clk_div: Divided clock output.\n"
        "A frequency divider that divides the input clock by an even number using a "
        "counter cnt and toggling clk_div. NUM_DIV must be even.\n")
    assert CA.synth(prose, "freq_divbyeven") is None


def test_lfsr_unstated_taps_skips():
    # an LFSR whose feedback taps are NOT named -> SKIP (never guess the polynomial).
    prose = (
        "Module name:\n    LFSR\n"
        "Input ports:\n    clk: Clock signal.\n    rst: Active high reset.\n"
        "Output ports:\n    out [3:0]: 4-bit LFSR state.\n"
        "A 4-bit LFSR that shifts left and inserts a feedback bit at the LSB. "
        "The feedback is derived from carefully chosen tap positions. On reset the "
        "register is initialized to zero.\n")
    assert LF.synth(prose, "LFSR") is None


def test_lfsr_right_shift_galois_not_taken_by_left_dialect():
    # a Galois-RIGHT lfsr must NOT be emitted by the left-shift dialect; and a
    # left-shift prose with no width consistency must SKIP.
    prose = (
        "Module name:\n    LFSR\n"
        "Input ports:\n    clk: Clock signal.\n    rst: Active high reset.\n"
        "Output ports:\n    out [3:0]: 4-bit state.\n"
        "A 4-bit LFSR. The feedback XORs out[3] and out[2]; the result is inverted "
        "and shifted into the LSB after a LEFT shift. Reset initializes to zero.\n"
        # contradict the width: claim 5-bit elsewhere
        "Note: this is actually a 5-bit register.\n")
    # conflicting widths (4-bit vs 5-bit) -> ambiguous -> SKIP
    assert LF.synth(prose, "LFSR") is None


# --------------------------------------------------------------------------- #
# Positive host-scores (canonical RTLLM designs) — gated on dataset + tools.   #
# --------------------------------------------------------------------------- #
_POS = [
    (CA, "Control/Counter/JC_counter", "JC_counter", True),
    (CA, "Control/Counter/counter_12", "counter_12", True),
    (CA, "Control/Counter/up_down_counter", "up_down_counter", True),
    (CA, "Miscellaneous/Frequency divider/freq_div", "freq_div", True),
    (CA, "Miscellaneous/Frequency divider/freq_divbyodd", "freq_divbyodd", True),
    (CA, "Miscellaneous/Frequency divider/freq_divbyfrac", "freq_divbyfrac", True),
    (SR, "Memory/Shifter/right_shifter", "right_shifter", True),
    (LF, "Memory/Shifter/LFSR", "LFSR", True),
]


@pytest.mark.parametrize("mod,rel,top,must_pass", _POS,
                         ids=[p[2] for p in _POS])
def test_rtllm_positive_host_pass(mod, rel, top, must_pass):
    if not RTLLM.exists() or not _have_iverilog():
        pytest.skip("RTLLM dataset or iverilog/vvp not present")
    rtl = mod.synth(_prose(rel), top)
    assert rtl is not None, f"{top} should emit (fully stated in prose)"
    assert _host_pass(rtl, _tb(rel)) is True, f"{top} host-score must PASS"


def test_rtllm_ring_counter_emits_correct_rtl_category_d_floor():
    # ring_counter: emit CORRECT one-hot rotate RTL, but the dataset TB uses a
    # VCS-only array-aggregate init that iverilog cannot elaborate (the golden
    # ALSO fails under iverilog) -> a host CErr (None), NOT a functional FAIL.
    if not RTLLM.exists():
        pytest.skip("RTLLM dataset not present")
    rtl = CA.synth(_prose("Control/Counter/ring_counter"), "ring_counter")
    assert rtl is not None, "ring_counter should emit correct RTL (not SKIP)"
    # the emitted RTL is a correct one-hot left-rotate with LSB-set reset.
    assert "{out[6:0], out[7]}" in rtl
    assert "1'b1" in rtl
    if _have_iverilog():
        # compile against the TB -> Category-D floor (CErr), surfaced as None.
        assert _host_pass(rtl, _tb("Control/Counter/ring_counter")) is None


def test_rtllm_barrel_shifter_honest_skip():
    # the dataset barrel_shifter's prose never states LEFT vs RIGHT -> SKIP.
    if not RTLLM.exists():
        pytest.skip("RTLLM dataset not present")
    assert SR.synth(_prose("Memory/Shifter/barrel_shifter"),
                    "barrel_shifter") is None


def test_native_ve_fire_set_unchanged_smoke():
    # the fold must not change the VE behaviour: a bullet-form VE Galois LFSR still
    # emits the Galois-right next state, and a non-shift prompt still SKIPs.
    galois = (
        " - input clk\n - input reset\n - output q (5 bits)\n\n"
        "Build a 5-bit Galois LFSR that shifts right with taps at bit positions 5 "
        "and 3. The reset is synchronous active-high and sets the output to 5'h1.\n")
    rtl = LF.synth(galois, "TopModule")
    assert rtl is not None and "Galois shift-right" in rtl
    # a plain combinational prompt is not in any of these families -> SKIP.
    assert SR.synth("compute a + b", "TopModule") is None
    assert CA.synth("compute a + b", "TopModule") is None
    assert LF.synth("compute a + b", "TopModule") is None
