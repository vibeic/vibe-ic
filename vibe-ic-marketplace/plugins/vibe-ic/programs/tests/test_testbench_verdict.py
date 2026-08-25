#!/usr/bin/env python3
r"""Tests for testbench_verdict — turning a simulator transcript into PASS/FAIL.

What is pinned here is the JUDGEMENT, which has a wrong answer available in both
directions: reading a never-ran log as PASS ships a defect, reading a passing log
as FAIL invents one.

  * every reader in the READERS table recognises its own simulator's summary and
    reports (failures, compared) — a new simulator is a new row, so the table is
    asserted through `read_counts`, by name, not by counting rows;
  * ZERO FAILURES OVER ZERO CASES IS NOT A PASS — the module's headline rule;
  * a non-zero simulator exit and a silent transcript are never a pass, even when
    the transcript also carries a pass banner;
  * an anchored failure statement beats a co-occurring pass token;
  * an unrecognised transcript is NOT a pass (fail-safe direction).
"""
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import testbench_verdict as V  # noqa: E402


# --------------------------------------------------------------------------- #
# the reader table — each simulator's own vocabulary, by name
# --------------------------------------------------------------------------- #
_READER_CASES = [
    ("rtllm_counted",
     "Test completed with 0 failures\n", 0, None),
    ("rtllm_counted",
     "Test completed with 3 / 100 errors\n", 3, 100),
    ("cocotb_summary",
     "** TESTS=3 PASS=3 FAIL=0 **\n", 0, 3),
    ("cocotb_summary",
     "** TESTS=4 PASS=1 FAIL=3 **\n", 3, 4),
    ("verilogeval_hint",
     "Total mismatched samples is 0 out of 100 samples\n", 0, 100),
    ("verilogeval_count",
     "Mismatches: 7 in 100 samples\n", 7, 100),
    ("uvm_summary",
     "UVM_ERROR : 2\nUVM_FATAL : 1\n", 3, None),
    ("error_count",
     "# Number of errors: 5\n", 5, None),
]


@pytest.mark.parametrize("name,text,failures,compared", _READER_CASES)
def test_each_reader_recognises_its_own_summary(name, text, failures, compared):
    """A reader must extract the failure count AND its denominator (or state it
    has none). read_counts is the 'show your work' surface, so assert through it."""
    got = V.read_counts(text)
    assert (name, failures, compared) in got, got


def test_a_transcript_of_none_of_the_forms_yields_no_counts():
    assert V.read_counts("simulation finished at 1000 ns\n") == []


# --------------------------------------------------------------------------- #
# the verdict
# --------------------------------------------------------------------------- #
def test_counted_zero_failures_over_real_cases_is_a_pass():
    ok, why = V.testbench_verdict("Mismatches: 0 in 100 samples\n", 0)
    assert ok is True, why
    assert "100" in why


@pytest.mark.parametrize("text", [
    "** TESTS=0 PASS=0 FAIL=0 **\n",
    "Total mismatched samples is 0 out of 0 samples\n",
    "Mismatches: 0 in 0 samples\n",
])
def test_zero_failures_over_zero_cases_is_not_a_pass(text):
    """The module's headline rule: a counted reader that compared nothing proves
    nothing. Counting no failures is not the same as finding none."""
    ok, why = V.testbench_verdict(text, 0)
    assert ok is False
    assert "nothing was compared" in why


def test_any_reader_counting_a_failure_fails_the_run():
    # two summaries disagreeing is not a tie to break — the failure wins.
    text = "** TESTS=2 PASS=2 FAIL=0 **\nMismatches: 4 in 50 samples\n"
    ok, why = V.testbench_verdict(text, 0)
    assert ok is False
    assert "4 failure" in why


def test_nonzero_simulator_exit_is_never_a_pass():
    ok, why = V.testbench_verdict("=== Your Design Passed ===\n", 2)
    assert ok is False
    assert "exited 2" in why


def test_silent_transcript_is_not_a_pass():
    ok, why = V.testbench_verdict("   \n", 0)
    assert ok is False
    assert "silent" in why


def test_zero_count_contradicted_by_a_failure_statement_is_not_a_pass():
    text = ("Test completed with 0 failures\n"
            "Assertion failed at time 400\n")
    ok, why = V.testbench_verdict(text, 0)
    assert ok is False
    assert "contradicted" in why


def test_failure_statement_beats_a_co_occurring_pass_token():
    text = "Failed at 120 ns\nPassed\n"
    ok, _why = V.testbench_verdict(text, 0)
    assert ok is False


def test_pass_banner_without_any_counted_line_is_a_pass():
    ok, why = V.testbench_verdict("=== Your Design Passed ===\n", 0)
    assert ok is True, why


def test_unrecognised_transcript_is_not_a_pass():
    ok, why = V.testbench_verdict(
        "VCD info: dumpfile wave.vcd opened for output.\n"
        "simulation finished at 2000 ns\n", 0)
    assert ok is False
    assert "no recognisable" in why


def test_verdict_survives_an_absent_returncode():
    # a caller that cannot report an exit status must still get the transcript's
    # own verdict, not a crash and not a free pass.
    assert V.testbench_verdict("Mismatches: 0 in 8 samples\n")[0] is True
    assert V.testbench_verdict("Mismatches: 1 in 8 samples\n")[0] is False
