"""v1.1.38 §4.2 absorption — deterministic combinational-waveform → RTL synth.

The circuitN family embeds a literal truth table; for a COMBINATIONAL circuit it
is a complete oracle-free spec, so the answer is deterministic (SOP over the 1-rows).
This was a per-round single-shot variance (a blind author re-derives the boolean
function by eye and flips it); the synth absorbs it as a PROGRAM so it is a
guaranteed first-pass PASS.

§4.05 no-leak: the synth FIRES only inside the proven-faithful envelope
(combinational, no-clock table, all-port columns, self-consistent) and SKIPs
everywhere else — it can never emit a wrong sample. These tests pin both halves:
the positive (fires + emits the correct SOP) AND the no-leak negatives
(SKIP on sequential / clock-column / contradiction / no-table / no-ports).
"""
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import waveform_truth_table_synth as W  # noqa: E402


_COMB_PROMPT = """
Implement a module named TopModule.

  input a,
  input b,
  output q

The module should implement a combinational circuit. Read the simulation
waveforms to determine what the circuit does, then implement it.

  time  a  b  q
  0ns   0  0  0
  5ns   0  1  1
  10ns  1  0  1
  15ns  1  1  0
"""


# ── POSITIVE: fires, emits a correct XOR SOP, all minterms covered ────────────
def test_combinational_synth_fires_and_is_correct():
    rtl = W.synth(_COMB_PROMPT, "TopModule")
    assert rtl is not None, "combinational waveform must synthesize"
    assert "module TopModule" in rtl and "assign q" in rtl
    # q = a^b: 1-rows are (a=0,b=1) and (a=1,b=0)
    assert "(~a & b)" in rtl and "(a & ~b)" in rtl


def test_unobserved_combo_is_dont_care_zero():
    # only a couple of rows; absent combos emit 0 (canonical reading)
    p = _COMB_PROMPT.replace("  10ns  1  0  1\n", "").replace("  15ns  1  1  0\n", "")
    rtl = W.synth(p, "TopModule")
    assert rtl is not None
    assert "(~a & b)" in rtl  # the one observed 1-row
    assert "a & ~b" not in rtl  # unobserved -> not a minterm


# ── §4.05 NO-LEAK NEGATIVES: must SKIP (return None), never emit a guess ───────
def test_skip_sequential_flipflop():
    seq = _COMB_PROMPT.replace(
        "combinational circuit", "sequential circuit with one flip-flop")
    assert W.synth(seq, "TopModule") is None


def test_skip_when_table_has_clock_column():
    clk = """
Implement a module named TopModule.
  input clk,
  input a,
  output q
The module should implement a combinational circuit.
  time  clk a  q
  0ns   0   0  0
  5ns   1   1  1
"""
    assert W.synth(clk, "TopModule") is None


def test_skip_on_contradiction():
    # same inputs (a=0,b=0) give q=0 then q=1 -> not a clean function -> SKIP
    bad = _COMB_PROMPT + "  20ns  0  0  1\n"
    assert W.synth(bad, "TopModule") is None


def test_skip_when_no_table():
    assert W.synth("Implement a combinational module TopModule with input a.", "TopModule") is None


def test_skip_when_no_ports():
    notports = "The module is combinational.\n  time  a  q\n  0ns  0  0\n  5ns  1  1\n"
    assert W.synth(notports, "TopModule") is None


def test_skip_when_word_combinational_absent():
    # a sequential-or-unspecified prompt with a table but no 'combinational' word
    p = _COMB_PROMPT.replace("combinational ", "")
    assert W.synth(p, "TopModule") is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
