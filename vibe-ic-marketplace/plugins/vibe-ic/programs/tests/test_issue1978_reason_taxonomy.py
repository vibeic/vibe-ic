#!/usr/bin/env python3
"""Issue #1978: non-verdict reasons are typed and affect the P0 tier."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _flow_reason_taxonomy as T  # noqa: E402
from _hostpaths import require_repo  # noqa: E402




import _structural_absence as _sa  # R-0915-119













#: R-0915-85 — the expectations here are the STEP's word (this is the P0
#: umbrella's step verdict), so the three non-skip-eligible gate reason classes
#: now land on `NOT_MEASURED`. The three skip-eligible ones still land on PASS,
#: which is the discrimination #1978 exists for and it is unchanged.




def test_caller_error_zero_denominator_and_missing_upstream_are_not_skips():
    cases = [
        ("path not found", {}, T.EXECUTION_ERROR, "INCOMPLETE"),
        ("docs loaded NONE; 0/13 examined", {}, T.ZERO_DENOMINATOR,
         "INCOMPLETE"),
        ("no deliverable at RESULT.md — producer has not run", {},
         T.BLOCKED_BY_UPSTREAM, "BLOCKED"),
    ]
    for message, evidence, expected_class, expected_verdict in cases:
        reason_class = T.infer_nonverdict_reason(
            verdict="SKIP", message=message, evidence=evidence)
        assert reason_class == expected_class
        assert T.record_verdict(reason_class) == expected_verdict


def test_bare_not_applicable_is_not_a_design_declaration():
    assert T.infer_nonverdict_reason(
        verdict="SKIP", message="NOT_APPLICABLE") == T.EXECUTION_ERROR














# ── a counted zero is not an execution error (C1) ──────────────────────────
#
# THE MESSAGES BELOW ARE MEASURED, NOT WRITTEN. Each is the exact prose the
# named gate emits, captured on tree ca330272d through
# `flow_compliance_check._check_program_exit_zero`. A recogniser tuned against
# invented sentences is tuned against nothing.
_ZERO_DENOMINATOR_MESSAGES = {
    "em_peak_current_authority_check, no EM segments":
        "em_peak_current_authority_check: read 0 peak-current figure(s) and 0 "
        "declared supply authority(ies); 0 of 0 segment(s) screened against "
        "Jmax.\n  no comparison was possible: the report declares neither a "
        "peak segment current nor a supply authority.\nINCOMPLETE: "
        "electromigration was NOT screened",
    "si_mcf_sta_check, a SPEF it parsed to zero coupling pairs":
        "VACUOUS_PASS: the SPEF named by the report parses to 2 net record(s), "
        "0 two-node (coupling) *CAP entries and therefore 0 inter-net coupling "
        "pairs, so the MCF fold has nothing to re-derive. Read this as NOT "
        "CHECKED.",
}

_EXECUTION_ERROR_MESSAGES = {
    "sdc_validator_check, a positional that does not exist":
        "[SKIP] sdc_validator_check: NOT CHECKED — the positional "
        "does_not_exist does not exist, so 0 of 2 declared search root(s) "
        "(phase2/stage1/fpga, phase2/stage2/constraints) could be resolved and "
        "0 .sdc file(s) were read. The positional is the PROJECT ROOT",
    "provenance_check, argparse rejecting its own command line":
        "usage: provenance_check.py [-h] [--output OUTPUT] [--tool TOOL]\n"
        "provenance_check.py: error: argument --output: expected one argument",
    "a program that crashed":
        "Traceback (most recent call last):\n  File \"g.py\", line 3, in <m>\n"
        "ZeroDivisionError: division by zero",
}


@pytest.mark.parametrize("label", sorted(_ZERO_DENOMINATOR_MESSAGES))
def test_a_counted_zero_over_a_read_input_is_a_zero_denominator(label):
    """`EXECUTION_ERROR` says the program errored. These two did not: one read
    an EM report and found no segments, the other opened a SPEF, parsed two net
    records, and found no coupling. Booking them as errors sends a reviewer to
    debug a crash that did not happen."""
    assert T.infer_nonverdict_reason(
        message=_ZERO_DENOMINATOR_MESSAGES[label]) == T.ZERO_DENOMINATOR


@pytest.mark.parametrize("label", sorted(_EXECUTION_ERROR_MESSAGES))
def test_a_real_execution_fault_stays_an_execution_error(label):
    """THE OTHER DIRECTION, and the reason the patterns above are narrow.

    The sdc message truthfully reports `0 .sdc file(s) were read` and `0 of 2
    ... could be resolved`: zeroes that are the CONSEQUENCE of a bad argument,
    not a denominator anybody measured. A widening that swallows this sentence
    has widened too far, and this parametrisation is what says so."""
    assert T.infer_nonverdict_reason(
        message=_EXECUTION_ERROR_MESSAGES[label]) == T.EXECUTION_ERROR


def test_the_reclassification_greens_nothing():
    """THE ANTI-BACKDOOR PIN. Fixing the recogniser must not be a route back to
    the skip tier — the whole reason C1's five migrated assertions could not be
    'fixed' this way. Both classes are outside SKIP_ELIGIBLE, so both render
    INCOMPLETE; only the published row's wording changes."""
    for cls in (T.ZERO_DENOMINATOR, T.EXECUTION_ERROR):
        assert cls not in T.SKIP_ELIGIBLE
        assert T.record_verdict(cls) == "INCOMPLETE"
        assert T.p0_tier_for_reason_classes([cls]) == "INCOMPLETE"


def test_zero_of_zero_and_zero_of_n_are_not_the_same_question():
    """The discriminator, isolated. `0 of 0` is an empty population; `0 of N`
    is a population of N that failed to resolve, which is a fault."""
    assert T.infer_nonverdict_reason(
        message="0 of 0 segment(s) screened") == T.ZERO_DENOMINATOR
    assert T.infer_nonverdict_reason(
        message="the positional does not exist, so 0 of 2 declared search "
                "root(s) could be resolved") == T.EXECUTION_ERROR


# ── why a producer must declare, and prose cannot decide for it ────────────
#
# THE TWO SENTENCES BELOW ARE MEASURED, and they are the reason this file
# cannot grow a counted-zero recogniser for either of them. Both state a zero
# of the SAME noun. One is a zero denominator; the other is a design saying
# the question does not apply to it. No lexical rule separates them, because
# what separates them is what CAUSED the zero — and only the gate knows that.
_SI_ZERO = (
    "the SPEF named by the report parses to 2 net record(s), 0 two-node "
    "(coupling) *CAP entries and therefore 0 inter-net coupling pairs, so the "
    "MCF fold has nothing to re-derive")
_SI_ZERO_BARE = (
    "0 two-node (coupling) *CAP entries and therefore 0 inter-net coupling "
    "pairs")
_FSTC_NA = (
    "VACUOUS_PASS: no command protocol - the design's L3 declares no opcodes "
    "(L3.json); per-opcode state-transition coverage is N/A for this "
    "non-protocol IC (0 coverage entries, nothing to assert)")


def test_two_gates_state_the_same_shaped_zero_and_mean_opposite_classes():
    """MEASURED, and the measurement is the point.

    `si_mcf_sta_check` opened its input, parsed it, and found the population
    empty -> ZERO_DENOMINATOR, which is NOT skip-eligible and must not become a
    benign skip. `functional_state_transition_coverage_check` was told by the
    design that the question does not apply -> DESIGN_DECLARED_NA, which IS
    skip-eligible and must not be turned into an incomplete.

    Written out, both sentences contain `0 <words> entries`. A counted-zero
    pattern wide enough for the first is wide enough for the second, and it
    would fire FIRST -- `_ZERO_RE` is tried before `_DECLARED_NA_RE` -- turning
    every non-protocol IC's honest N/A into an unexamined question. This test
    exists so the next author who reaches for that pattern measures it against
    this pair before landing it."""
    import re
    counted_zero = re.compile(
        r"\b0\s+[^\n]{0,40}?\b(?:entr(?:y|ies)|pairs?|records?)\b", re.I)
    assert counted_zero.search(_SI_ZERO), _SI_ZERO
    assert counted_zero.search(_SI_ZERO_BARE), _SI_ZERO_BARE
    assert counted_zero.search(_FSTC_NA), (
        "if this stops matching, the two sentences have become lexically "
        "separable and a recogniser may be worth revisiting")


def test_the_declared_class_decides_both_and_the_prose_decides_neither():
    """THE REMEDY, and it is the one `_flow_reason_taxonomy`'s own docstring
    already asks for: "Producers should publish an explicit `reason_class`
    whenever possible."

    Given the declaration, both sentences classify correctly and the ambiguity
    above is irrelevant. Without it, the fail-closed default books BOTH as
    EXECUTION_ERROR -- "the gate blew up" -- which is wrong about both."""
    # The full si sentence is recognised today, but only because it ENDS with
    # "nothing to re-derive" (v1.16.64). State the same fact WITHOUT that
    # clause -- which `_vacuity`'s sibling branches do -- and the fail-closed
    # default books it "the gate blew up".
    assert T.infer_nonverdict_reason(message=_SI_ZERO) == T.ZERO_DENOMINATOR
    assert T.infer_nonverdict_reason(
        message=_SI_ZERO_BARE) == T.EXECUTION_ERROR
    assert T.infer_nonverdict_reason(
        message=_SI_ZERO_BARE,
        explicit=T.ZERO_DENOMINATOR) == T.ZERO_DENOMINATOR
    assert T.infer_nonverdict_reason(
        message=_FSTC_NA, explicit=T.DESIGN_DECLARED_NA) == T.DESIGN_DECLARED_NA
    # ...and the two land on OPPOSITE sides of the skip bar, which is why
    # getting it wrong is not a cosmetic error.
    assert T.ZERO_DENOMINATOR not in T.SKIP_ELIGIBLE
    assert T.DESIGN_DECLARED_NA in T.SKIP_ELIGIBLE
    assert T.p0_tier_for_reason_classes([T.ZERO_DENOMINATOR]) == "INCOMPLETE"
    assert T.p0_tier_for_reason_classes([T.DESIGN_DECLARED_NA]) == "PASS"
