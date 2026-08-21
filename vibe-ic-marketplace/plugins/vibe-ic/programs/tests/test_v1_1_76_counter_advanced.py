"""v1.1.76 — counter_advanced_synth deterministic SOLVER for the SUBTLE counter /
timer / clock family (bucket-② spec -> bucket-① RTL).

counter_popcount_synth owns the SIMPLE modulo-N up counter; this module owns the
subtle siblings it SKIPs, each with non-trivial rollover / clamp / reset-priority
semantics, emitted blind ONLY when every governing parameter is STATED:

  * MULTI-DIGIT BCD UP COUNTER (ripple carry + per-upper-digit enable out) —
    Prob068_countbcd
  * SATURATING UP/DOWN COUNTER (clamp both ends, no wrap, async reset) —
    Prob075_counter_2bc
  * DOWN-COUNTER TIMER (sync load + terminal count, stop at 0) — Prob080_timer
  * 12-HOUR BCD CLOCK (hh/mm/ss BCD + pm toggle + ena + sync reset>ena) —
    Prob141_count_clock
  * SHIFT-OR-(decrement/rollback-load) DUAL REGISTER — Prob063_review2015_shiftcount,
    Prob118_history_shift

Positives are host-scored (iverilog -g2012 dut + ref + test; vvp; 0 mismatches)
when the dataset + tools are present. §4.05 NO-LEAK: >=5 negative fixtures that
MUST return None (SKIP), plus a corpus sweep proving the fire set is EXACTLY the
six intended problems and nothing else in the 156-prompt benchmark.
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
import counter_advanced_synth as CA  # noqa: E402
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
# POSITIVE fixtures (host-scored against the real dataset when present)
# --------------------------------------------------------------------------- #
POSITIVES = [
    "Prob068_countbcd",
    "Prob075_counter_2bc",
    "Prob080_timer",
    "Prob141_count_clock",
    "Prob063_review2015_shiftcount",
    "Prob118_history_shift",
]


def test_positives_fire_and_hostscore():
    """Every known family member FIREs and (if dataset+tools present) host-PASSes
    to 0 mismatches — the §4.05 condition for a legitimate FIRE."""
    if not HAVE_DS:
        import pytest
        pytest.skip("verilog-eval dataset not present")
    for prob in POSITIVES:
        prompt = (DS / f"{prob}_prompt.txt").read_text()
        rtl = CA.synth(prompt)
        assert rtl is not None, f"{prob} should FIRE but SKIPped"
        assert "module TopModule" in rtl
        if IVERILOG and VVP:
            _host_score(prob, rtl)


# --------------------------------------------------------------------------- #
# Self-contained positives (no dataset needed) — pin the emitted structure
# --------------------------------------------------------------------------- #
def test_bcd_counter_emits_ripple_and_enable():
    p = _HDR + (" - input  clk\n - input  reset\n - output ena (3 bits)\n"
                " - output q   (16 bits)\n\n"
                "Implement a 4-digit BCD counter. Each decimal digit is encoded "
                "using 4 bits. For digits [3:1], also output an enable signal "
                "indicating when each upper digit should be incremented. Include a "
                "synchronous active-high reset.\n")
    rtl = CA.synth(p)
    assert rtl is not None
    assert "output [2:0] ena" in rtl or "output [2:0]ena" in rtl
    assert "assign ena = enable[3:1];" in rtl
    assert "q[i*4 +: 4] == 9" in rtl
    assert "if (reset)" in rtl


def test_saturating_emits_clamp_and_async_reset():
    p = _HDR + (" - input  clk\n - input  areset\n - input  train_valid\n"
                " - input  train_taken\n - output state (2 bits)\n\n"
                "Implement a two-bit saturating counter. The counter increments "
                "(up to a maximum of 3) when train_valid = 1 and train_taken = 1. "
                "It decrements (down to a minimum of 0) when train_valid = 1 and "
                "train_taken = 0. areset is a positive edge triggered asynchronous "
                "reset that resets the counter to 2'b01.\n")
    rtl = CA.synth(p)
    assert rtl is not None
    assert "posedge clk, posedge areset" in rtl   # async reset
    assert "state <= 1;" in rtl                    # weak value
    assert "state < 3 && train_taken" in rtl       # clamp at max
    assert "state > 0 && !train_taken" in rtl      # clamp at min


def test_timer_emits_load_decrement_tc():
    p = _HDR + (" - input  clk\n - input  load\n - input  data (10 bits)\n"
                " - output tc\n\n"
                "Implement a timer that counts down. If load = 1, load the internal "
                "counter with the 10-bit data. If load = 0, the counter decrements "
                "by 1. tc (terminal count) indicates the counter has reached 0. Once "
                "the counter reaches 0 it stays 0 until loaded again.\n")
    rtl = CA.synth(p)
    assert rtl is not None
    assert "if (load)" in rtl
    assert "count_value <= data;" in rtl
    assert "count_value <= count_value - 1;" in rtl
    assert "assign tc = (count_value == 0);" in rtl


def test_clock_emits_pm_toggle_and_sync_reset():
    p = (DS / "Prob141_count_clock_prompt.txt").read_text() if HAVE_DS else (
        _HDR + (" - input  clk\n - input  reset\n - input  ena\n - output pm\n"
                " - output hh (8 bits)\n - output mm (8 bits)\n - output ss (8 bits)\n\n"
                "Create a set of counters for a 12-hour clock with am/pm indicator. "
                "A pulse on ena increments once per second. hh, mm, ss are two BCD "
                "digits each for hours (01-12), minutes (00-59), seconds (00-59). "
                "Reset is the active high synchronous signal that resets the clock "
                "to 12:00 AM. Reset has higher priority than enable and can occur "
                "even when not enabled.\n"))
    rtl = CA.synth(p)
    assert rtl is not None
    assert "if (reset) begin" in rtl
    assert "hh <= 8'h12;" in rtl and "pm <= 1'b0;" in rtl
    assert "else if (ena) begin" in rtl
    assert "pm <= ~pm;" in rtl


def test_shiftcount_emits_shift_then_decrement():
    p = _HDR + (" - input  clk\n - input  shift_ena\n - input  count_ena\n"
                " - input  data\n - output q (4 bits)\n\n"
                "Implement a four-bit shift register that also acts as a down "
                "counter. Data is shifted in most-significant-bit first when "
                "shift_ena is 1. The number in the register is decremented when "
                "count_ena is 1. Since the system never uses both together, it "
                "does not matter which case gets higher priority.\n")
    rtl = CA.synth(p)
    assert rtl is not None
    assert "if (shift_ena)" in rtl
    assert "{q[2:0], data}" in rtl
    assert "else if (count_ena)" in rtl
    assert "q <= q - 1'b1;" in rtl


def test_history_shift_emits_rollback_precedence():
    p = (DS / "Prob118_history_shift_prompt.txt").read_text() if HAVE_DS else (
        _HDR + (" - input  clk\n - input  areset\n - input  predict_valid\n"
                " - input  predict_taken\n - input  train_mispredicted\n"
                " - input  train_taken\n - input  train_history   (32 bits)\n"
                " - output predict_history (32 bits)\n\n"
                "Implement a 32-bit global history shift register. When "
                "predict_valid = 1, shift in predict_taken from the LSB side. When "
                "train_mispredicted = 1, load the register with the history before "
                "the mispredicted branch (train_history) concatenated with "
                "train_taken. If both occur, the misprediction takes precedence. "
                "areset is a positive edge triggered asynchronous reset that resets "
                "the history to zero.\n"))
    rtl = CA.synth(p)
    assert rtl is not None
    assert "posedge clk, posedge areset" in rtl
    assert "predict_history <= 0;" in rtl
    # misprediction has precedence -> the mispredict load branch is tested BEFORE
    # the predict_valid shift branch inside the always block (look only at the
    # body, past the port-declaration list, so port-order isn't conflated).
    body = rtl[rtl.index("always @"):]
    i_mis = body.index("if (train_mispredicted)")
    i_pv = body.index("else if (predict_valid)")
    assert i_mis < i_pv
    assert "{train_history[30:0], train_taken}" in rtl
    assert "{predict_history[30:0], predict_taken}" in rtl


# --------------------------------------------------------------------------- #
# §4.05 NO-LEAK negatives — MUST return None (>=5)
# --------------------------------------------------------------------------- #
def test_neg_simple_modulo_counter():
    # a plain modulo-N up counter is the OTHER module's (counter_popcount) job;
    # this advanced solver must NOT also claim it.
    p = _HDR + (" - input  clk\n - input  reset\n - output q (4 bits)\n\n"
                "Implement a 4-bit binary counter that counts from 0 through 15 "
                "inclusive, with a period of 16. The reset input is active high "
                "synchronous, and should reset the counter to 0.\n")
    assert CA.synth(p) is None


def test_neg_bcd_digit_count_unstated():
    # BCD counter but the digit count is NOT stated (bus width alone is a guess)
    # -> SKIP.
    p = _HDR + (" - input  clk\n - input  reset\n - output q (16 bits)\n\n"
                "Implement a BCD counter. Include a synchronous active-high "
                "reset.\n")
    assert CA.synth(p) is None


def test_neg_bcd_async_reset():
    # BCD counter but reset is asynchronous -> different RTL than the sync emit
    # -> SKIP (no guessing the reset style).
    p = _HDR + (" - input  clk\n - input  reset\n - output ena (3 bits)\n"
                " - output q (16 bits)\n\n"
                "Implement a 4-digit BCD counter. For digits [3:1] output an "
                "enable indicating when each upper digit should be incremented. "
                "Include an asynchronous active-high reset.\n")
    assert CA.synth(p) is None


def test_neg_saturating_no_reset_value():
    # saturating counter but the reset VALUE is not stated -> don't guess -> SKIP.
    p = _HDR + (" - input  clk\n - input  areset\n - input  train_valid\n"
                " - input  train_taken\n - output state (2 bits)\n\n"
                "Implement a two-bit saturating counter that increments up to a "
                "maximum of 3 and decrements down to a minimum of 0. areset is an "
                "asynchronous reset.\n")
    assert CA.synth(p) is None


def test_neg_saturating_no_clamp_bounds():
    # "saturating" word but neither max nor min clamp stated -> SKIP.
    p = _HDR + (" - input  clk\n - input  areset\n - input  train_valid\n"
                " - input  train_taken\n - output state (2 bits)\n\n"
                "Implement a saturating counter. areset resets the counter to "
                "2'b01.\n")
    assert CA.synth(p) is None


def test_neg_timer_no_terminal_count():
    # a down-counter with no terminal-count / reach-zero semantics stated -> SKIP.
    p = _HDR + (" - input  clk\n - input  load\n - input  data (10 bits)\n"
                " - output tc\n\n"
                "Implement a down-counter that decrements by 1 each cycle. If "
                "load = 1, load the counter with data.\n")
    assert CA.synth(p) is None


def test_neg_timer_with_unexplained_reset():
    # a timer with an EXTRA reset input we don't model -> SKIP (no guessing).
    p = _HDR + (" - input  clk\n - input  reset\n - input  load\n"
                " - input  data (10 bits)\n - output tc\n\n"
                "Implement a timer that counts down and asserts tc (terminal "
                "count) when the count reaches 0. If load = 1, load data; else "
                "decrement.\n")
    assert CA.synth(p) is None


def test_neg_clock_no_pm():
    # 12-hour clock prose but no pm output in the interface -> SKIP.
    p = _HDR + (" - input  clk\n - input  reset\n - input  ena\n"
                " - output hh (8 bits)\n - output mm (8 bits)\n - output ss (8 bits)\n\n"
                "Create a 12-hour clock. hh, mm, ss are BCD digits for hours, "
                "minutes, seconds. Reset is active high synchronous and resets to "
                "12:00 AM.\n")
    assert CA.synth(p) is None


def test_neg_shiftcount_no_direction():
    # shift-or-count but the shift DIRECTION (MSB/LSB-first) is not stated -> SKIP.
    p = _HDR + (" - input  clk\n - input  shift_ena\n - input  count_ena\n"
                " - input  data\n - output q (4 bits)\n\n"
                "Implement a four-bit shift register that also acts as a down "
                "counter. Data is shifted in when shift_ena is 1. The number is "
                "decremented when count_ena is 1.\n")
    assert CA.synth(p) is None


def test_neg_unrelated_prompt():
    p = _HDR + (" - input  a\n - input  b\n - output out\n\n"
                "Implement an AND gate.\n")
    assert CA.synth(p) is None


# --------------------------------------------------------------------------- #
# corpus no-leak sweep — exactly the 6 intended fires, nothing else, and EVERY
# fire host-scores to 0 mismatches (the §4.05 absolute).
# --------------------------------------------------------------------------- #
def test_corpus_no_leak_sweep():
    if not HAVE_DS:
        import pytest
        pytest.skip("verilog-eval dataset not present")
    fires = []
    for f in sorted(DS.glob("*_prompt.txt")):
        prob = f.name[:-len("_prompt.txt")]
        rtl = CA.synth(f.read_text())
        if rtl is not None:
            fires.append(prob)
            if IVERILOG and VVP:
                _host_score(prob, rtl)   # every fire MUST be 0-mismatch
    assert set(fires) == set(POSITIVES), f"unexpected fire set: {sorted(fires)}"


def test_does_not_collide_with_existing_solvers():
    """The six advanced fires must NOT also be claimed by the registry's existing
    generators (counter_popcount / shift_register / …) — no double-fire."""
    if not HAVE_DS:
        import pytest
        pytest.skip("verilog-eval dataset not present")
    import spec_artifact_registry as reg
    for prob in POSITIVES:
        txt = (DS / f"{prob}_prompt.txt").read_text()
        # post-integration counter_advanced IS in the registry — assert no OTHER
        # (foreign) generator also claims these targets (mutual exclusion vs siblings).
        foreign = [a.key for a in reg.REGISTRY if a.key != "counter_advanced"
                   and a.generate and a.generate(txt, "TopModule")]
        assert foreign == [], f"{prob} also claimed by {foreign}"
