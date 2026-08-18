"""v1.1.76 — counter_popcount_synth deterministic SOLVER for the counter /
popcount / parity-reduction family (bucket-② spec -> bucket-① RTL).

Three STATED-structure shapes are fully determined by the prompt, so the emitter
turns them into RTL blind:
  * POPCOUNT (combinational sum of set bits) — Prob009_popcount3, Prob030_popcount255
  * PARITY / REDUCTION-XOR (^in even / ~^in odd) — Prob025_reduction
  * MODULO-N UP COUNTER (sync active-high reset + optional enable) —
    Prob038_count15, Prob040_count10, Prob035_count1to10,
    Prob037_review2015_count1k, Prob067_countslow

Positives are host-scored (iverilog -g2012 dut + ref + test; vvp; 0 mismatches)
when the dataset is present. §4.05 NO-LEAK: >=5 negative fixtures that MUST return
None (SKIP) — down-counter, saturating counter, BCD, 12-hour clock, ambiguous
reduction with no operator named, popcount with too-narrow output, parity with no
even/odd sense, async reset, missing reset value.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROG_DIR = Path(__file__).resolve().parents[1]
if str(PROG_DIR) not in sys.path:
    sys.path.insert(0, str(PROG_DIR))
import counter_popcount_synth as CP  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

DS = corpus_path("_extbench/verilog-eval/dataset_spec-to-rtl")
HAVE_DS = DS.is_dir()
IVERILOG = shutil.which("iverilog")
VVP = shutil.which("vvp")

_HDR = ("I would like you to implement a module named TopModule with the following\n"
        "interface. All input and output ports are one bit unless otherwise specified.\n\n")


# --------------------------------------------------------------------------- #
# host-score helper
# --------------------------------------------------------------------------- #
def _host_score(prob, rtl):
    """iverilog-compile dut(rtl)+ref+test, run vvp, assert 0 mismatches."""
    ref = DS / f"{prob}_ref.sv"
    test = DS / f"{prob}_test.sv"
    assert ref.is_file() and test.is_file(), f"dataset missing for {prob}"
    with tempfile.TemporaryDirectory() as d:
        dut = Path(d) / "dut.sv"
        dut.write_text(rtl)
        vvp_out = Path(d) / "sim.vvp"
        c = subprocess.run(
            [IVERILOG, "-g2012", "-o", str(vvp_out), str(dut), str(ref), str(test)],
            capture_output=True, text=True)
        assert c.returncode == 0, f"{prob} compile failed:\n{c.stderr}"
        r = subprocess.run([VVP, str(vvp_out)], capture_output=True, text=True)
        out = r.stdout + r.stderr
        m = re.search(r"Mismatches:\s*(\d+)", out, re.I)
        assert m is not None, f"{prob}: no Mismatches line in:\n{out}"
        assert int(m.group(1)) == 0, f"{prob}: {m.group(1)} mismatches\n{out}"


# --------------------------------------------------------------------------- #
# POSITIVE fixtures (also host-scored against the real dataset when present)
# --------------------------------------------------------------------------- #
POSITIVES = [
    "Prob009_popcount3",
    "Prob030_popcount255",
    "Prob025_reduction",
    "Prob038_count15",
    "Prob040_count10",
    "Prob035_count1to10",
    "Prob037_review2015_count1k",
    "Prob067_countslow",
]


def test_positives_fire_and_hostscore():
    """Every known family member FIREs and (if dataset+tools present) host-PASSes."""
    if not HAVE_DS:
        import pytest
        pytest.skip("verilog-eval dataset not present")
    for prob in POSITIVES:
        prompt = (DS / f"{prob}_prompt.txt").read_text()
        rtl = CP.synth(prompt)
        assert rtl is not None, f"{prob} should FIRE but SKIPped"
        assert "module TopModule" in rtl
        if IVERILOG and VVP:
            _host_score(prob, rtl)


# --------------------------------------------------------------------------- #
# Self-contained positives (no dataset needed) — pin the emitted structure
# --------------------------------------------------------------------------- #
def test_popcount_emits_reg_sum():
    p = _HDR + (" - input  in  (8 bits)\n - output out (4 bits)\n\n"
                "The module should implement a population count circuit that counts "
                "the number of '1's in the input vector.\n")
    rtl = CP.synth(p)
    assert rtl is not None
    assert "for (i = 0; i < 8" in rtl
    assert "out = out + in[i]" in rtl
    assert "input [7:0] in" in rtl and "output reg [3:0] out" in rtl


def test_popcount_single_bit_in():
    # 1-bit input -> popcount is just the bit itself; out width 1 holds 0..1.
    p = _HDR + (" - input  in\n - output out\n\n"
                "Population count: count the number of 1s in the input vector.\n")
    rtl = CP.synth(p)
    assert rtl is not None
    assert "out = in" in rtl


def test_parity_even_is_xor():
    p = _HDR + (" - input  in (8 bits)\n - output parity\n\n"
                "Compute an even parity bit: the XOR of all 8 data bits.\n")
    rtl = CP.synth(p)
    assert rtl is not None
    assert "assign parity = ^in;" in rtl


def test_parity_odd_is_xnor():
    p = _HDR + (" - input  in (8 bits)\n - output parity\n\n"
                "Compute an odd parity bit over the input bus.\n")
    rtl = CP.synth(p)
    assert rtl is not None
    assert "assign parity = ~^in;" in rtl


def test_counter_full_range_reset_zero():
    p = _HDR + (" - input  clk\n - input  reset\n - output q (4 bits)\n\n"
                "Implement a 4-bit binary counter that counts from 0 through 15, "
                "inclusive, with a period of 16. The reset input is active high "
                "synchronous, and should reset the counter to 0.\n")
    rtl = CP.synth(p)
    assert rtl is not None
    assert "posedge clk" in rtl
    assert "reset || q == 15" in rtl
    assert "q <= 0;" in rtl


def test_counter_decade_reset_one():
    p = _HDR + (" - input  clk\n - input  reset\n - output q (4 bits)\n\n"
                "Implement a decade counter that counts 1 through 10, inclusive. "
                "The reset input is active high synchronous, and should reset the "
                "counter to 1.\n")
    rtl = CP.synth(p)
    assert rtl is not None
    # reset value (1) differs from wrap-start (1 here too) -> START==RESET path.
    assert "q == 10" in rtl
    assert "q <= 1;" in rtl


def test_counter_with_enable():
    p = _HDR + (" - input  clk\n - input  reset\n - input  slowena\n"
                " - output q (4 bits)\n\n"
                "Implement a decade counter that counts from 0 through 9, inclusive, "
                "with a period of 10. The reset input is active high synchronous, and "
                "should reset the counter to 0. The slowena input if high indicates "
                "when the counter should increment.\n")
    rtl = CP.synth(p)
    assert rtl is not None
    assert "input slowena" in rtl
    assert "else if (slowena)" in rtl
    assert "q == 9" in rtl


# --------------------------------------------------------------------------- #
# §4.05 NO-LEAK negatives — MUST return None
# --------------------------------------------------------------------------- #
def test_neg_down_counter_timer():
    # down-counter / terminal-count timer (Prob080_timer shape) -> SKIP.
    p = _HDR + (" - input  clk\n - input  load\n - input  data (10 bits)\n"
                " - output tc\n\n"
                "Implement a timer that counts down for a given number of clock "
                "cycles, then asserts a terminal count signal when the count "
                "reaches 0. A down-counter decrements by 1 each cycle.\n")
    assert CP.synth(p) is None


def test_neg_saturating_counter():
    # two-bit saturating counter w/ async reset (Prob075 shape) -> SKIP.
    p = _HDR + (" - input  clk\n - input  areset\n - input  train_valid\n"
                " - input  train_taken\n - output state (2 bits)\n\n"
                "Implement a two-bit saturating counter. It increments up to a "
                "maximum of 3 and decrements down to a minimum of 0. areset is a "
                "positive edge triggered asynchronous reset to 2'b01.\n")
    assert CP.synth(p) is None


def test_neg_bcd_counter():
    # 4-digit BCD counter (Prob068 shape) -> SKIP.
    p = _HDR + (" - input  clk\n - input  reset\n - output ena (3 bits)\n"
                " - output q   (16 bits)\n\n"
                "Implement a 4-digit BCD counter. Include a synchronous active-high "
                "reset.\n")
    assert CP.synth(p) is None


def test_neg_twelve_hour_clock():
    # 12-hour clock with hours/minutes/seconds (Prob141 shape) -> SKIP.
    p = _HDR + (" - input  clk\n - input  reset\n - input  ena\n - output pm\n"
                " - output hh (8 bits)\n - output mm (8 bits)\n - output ss (8 bits)\n\n"
                "Create a set of counters for a 12-hour clock with am/pm indicator. "
                "hh, mm, ss are BCD digits for hours, minutes, seconds. Reset is "
                "active high synchronous and resets the clock to 12:00 AM.\n")
    assert CP.synth(p) is None


def test_neg_reduction_no_operator():
    # "reduction" with no even/odd and no operator named -> ambiguous -> SKIP.
    p = _HDR + (" - input  in (8 bits)\n - output out\n\n"
                "The module should compute a reduction of the input bus into a "
                "single bit.\n")
    assert CP.synth(p) is None


def test_neg_popcount_output_too_narrow():
    # 8-bit in needs 4-bit out (0..8); a stated 3-bit out can't hold 8 -> SKIP.
    p = _HDR + (" - input  in (8 bits)\n - output out (3 bits)\n\n"
                "Population count: count the number of 1s in the input vector.\n")
    assert CP.synth(p) is None


def test_neg_parity_no_sense():
    # parity but neither even nor odd nor XOR-of-all stated -> SKIP.
    p = _HDR + (" - input  in (8 bits)\n - output parity\n\n"
                "Compute a parity bit for the input byte for error detection.\n")
    assert CP.synth(p) is None


def test_neg_counter_async_reset():
    # counter but reset is asynchronous -> different RTL -> SKIP.
    p = _HDR + (" - input  clk\n - input  reset\n - output q (4 bits)\n\n"
                "Implement a counter that counts from 0 through 9. The reset is "
                "active high asynchronous and resets the counter to 0.\n")
    assert CP.synth(p) is None


def test_neg_counter_no_reset_value():
    # counter range stated but reset VALUE not stated -> don't guess -> SKIP.
    p = _HDR + (" - input  clk\n - input  reset\n - output q (4 bits)\n\n"
                "Implement a counter that counts from 0 through 9. The reset input "
                "is active high synchronous.\n")
    assert CP.synth(p) is None


def test_neg_counter_period_disagrees_range():
    # stated period (12) disagrees with stated range 0..9 (period 10) -> SKIP.
    p = _HDR + (" - input  clk\n - input  reset\n - output q (4 bits)\n\n"
                "Implement a counter that counts from 0 through 9, with a period of "
                "12. The reset input is active high synchronous, and should reset "
                "the counter to 0.\n")
    assert CP.synth(p) is None


def test_neg_unrelated_prompt():
    p = _HDR + (" - input  a\n - input  b\n - output out\n\n"
                "Implement an AND gate.\n")
    assert CP.synth(p) is None


# --------------------------------------------------------------------------- #
# corpus no-leak sweep — exactly the 8 intended fires, nothing else
# --------------------------------------------------------------------------- #
def test_corpus_no_leak_sweep():
    if not HAVE_DS:
        import pytest
        pytest.skip("verilog-eval dataset not present")
    fires = []
    for f in sorted(DS.glob("*_prompt.txt")):
        prob = f.name[:-len("_prompt.txt")]
        if CP.synth(f.read_text()) is not None:
            fires.append(prob)
    assert set(fires) == set(POSITIVES), f"unexpected fire set: {sorted(fires)}"
