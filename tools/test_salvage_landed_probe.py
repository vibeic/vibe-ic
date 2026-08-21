#!/usr/bin/env python3
"""Tests for salvage_landed_probe.

Every test here is paired: the positive case AND the case that the guard exists
to prevent.  A single-direction assertion would be a rubber stamp -- this tool's
whole reason to exist is that four previous instruments were confidently wrong
in ONE direction, so a test that only checks the happy direction reproduces the
original defect.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import salvage_landed_probe as P  # noqa: E402


# ------------------------------------------------------------------ helpers

def summary(**outcomes):
    """A minimal `-rA` short-summary transcript."""
    lines = ["=" * 20 + " short test summary info " + "=" * 20]
    for name, outcome in outcomes.items():
        lines.append("%s tests/test_x.py::%s" % (outcome, name))
    return "\n".join(lines) + "\n"


def with_failure_block(text, name, reason):
    return (text + "\n" + "=" * 30 + " FAILURES " + "=" * 30 + "\n"
            + "_" * 20 + " " + name + " " + "_" * 20 + "\n"
            + "E   " + reason + "\n")


# --------------------------------------------------- reason recovery (P1/P2)

def test_failure_reason_is_recovered_from_the_failures_block():
    """The summary line carries no reason on this pytest; the block does.

    Paired with the next test: if reasons were read from the summary instead,
    this returns empty and the private-API quarantine silently never fires.
    """
    text = with_failure_block(summary(test_a="FAILED"), "test_a",
                              "AttributeError: module 'm' has no attribute '_helper'")
    assert "_helper" in P.parse_outcomes(text)["test_a"][1]


def test_summary_only_transcript_yields_no_reason():
    assert P.parse_outcomes(summary(test_a="FAILED"))["test_a"][1] == ""


# -------------------------------------------------- discrimination (P3..P6)

def test_a_node_that_already_passes_on_base_is_not_evidence():
    base = P.parse_outcomes(summary(test_a="PASSED"))
    tip = P.parse_outcomes(summary(test_a="PASSED"))
    assert P.discriminating_set(base, tip, "OK") == []


def test_a_node_that_fails_on_base_and_passes_on_tip_is_evidence():
    base = P.parse_outcomes(summary(test_a="FAILED"))
    tip = P.parse_outcomes(summary(test_a="PASSED"))
    assert P.discriminating_set(base, tip, "OK") == ["test_a"]


def test_a_node_the_branch_added_counts_when_the_base_run_was_healthy():
    base = P.parse_outcomes(summary(test_other="PASSED"))
    tip = P.parse_outcomes(summary(test_new="PASSED"))
    assert P.discriminating_set(base, tip, "OK") == ["test_new"]


def test_a_node_that_fails_on_the_tip_too_is_not_evidence():
    """A test that passes NOWHERE proves nothing and must not be scored.

    Found by mutation control: removing the tip-PASS guard left the whole suite
    green, because every other case here happens to pass on tip.  Without this,
    a branch whose own test is broken would have its failures scored against
    main and reported as UNLANDED.
    """
    base = P.parse_outcomes(summary(test_a="FAILED"))
    tip = P.parse_outcomes(summary(test_a="FAILED"))
    assert P.discriminating_set(base, tip, "OK") == []


def test_an_unrunnable_base_discriminates_nothing():
    """The guard that stops a failed import becoming a confident verdict.

    With a collect error EVERY node reads as absent, so without this the whole
    file would score as discriminating and the probe would emit a full-file
    UNLANDED off a broken import.
    """
    base = {}
    tip = P.parse_outcomes(summary(test_a="PASSED", test_b="PASSED"))
    assert P.discriminating_set(base, tip, "COLLECT_ERROR") == []


# ------------------------------------------------------- verdicts (P7..P10)

def test_all_evidence_passing_on_main_is_landed():
    main = P.parse_outcomes(summary(test_a="PASSED", test_b="PASSED"))
    assert P.classify(["test_a", "test_b"], main, "OK")["verdict"] == P.VERDICT_LANDED


def test_no_evidence_passing_on_main_is_unlanded():
    main = P.parse_outcomes(summary(test_a="FAILED", test_b="FAILED"))
    assert P.classify(["test_a", "test_b"], main, "OK")["verdict"] == P.VERDICT_UNLANDED


def test_mixed_evidence_is_partial_not_rounded_to_either_end():
    main = P.parse_outcomes(summary(test_a="PASSED", test_b="FAILED"))
    r = P.classify(["test_a", "test_b"], main, "OK")
    assert r["verdict"] == P.VERDICT_PARTIAL
    assert r["score"] == "1/2"


def test_empty_evidence_never_produces_a_confident_verdict():
    r = P.classify([], P.parse_outcomes(summary()), "OK")
    assert r["verdict"] == P.VERDICT_NO_DISCRIMINATION
    assert r["verdict"] not in P.CONCLUSIVE


# ------------------------------------------------- private-API drift (P11/12)

def test_private_attribute_failure_is_quarantined_not_scored_as_absence():
    """main re-implemented the behaviour under different private names.

    Scoring this as absence is the false-UNLANDED that made a real fix look
    like outstanding work.
    """
    text = with_failure_block(
        summary(test_a="FAILED"), "test_a",
        "AttributeError: module 'report' has no attribute '_pv_verdict'")
    main = P.parse_outcomes(text)
    r = P.classify(["test_a"], main, "OK")
    assert r["failed"] == []
    assert r["drift"] == ["test_a"]
    assert r["verdict"] == P.VERDICT_API_DRIFT


def test_an_ordinary_assertion_failure_is_still_scored_as_absence():
    """The other direction: quarantining everything would make UNLANDED
    unreachable and the tool would never report real absence."""
    text = with_failure_block(summary(test_a="FAILED"), "test_a",
                              "AssertionError: assert False is True")
    r = P.classify(["test_a"], P.parse_outcomes(text), "OK")
    assert r["failed"] == ["test_a"]
    assert r["verdict"] == P.VERDICT_UNLANDED


@pytest.mark.parametrize("reason,drifts", [
    ("AttributeError: module 'm' has no attribute '_helper'", True),
    ("AttributeError: module 'm' has no attribute 'public_helper'", False),
    ("AssertionError: assert 1 == 2", False),
    ("", False),
])
def test_only_private_names_count_as_drift(reason, drifts):
    """A PUBLIC attribute going missing is a real behavioural change."""
    assert P.is_api_drift(reason) is drifts


# ------------------------------------------------- unmeasurable main (P13/14)

def test_a_module_main_cannot_import_is_reported_as_unmeasured_not_unlanded():
    text = ("ERROR collecting tests/test_x.py\n"
            "E   ModuleNotFoundError: No module named 'some_new_program'\n")
    r = P.classify(["test_a"], {}, P.harness_status(text), "OK", text)
    assert r["verdict"] == P.VERDICT_MISSING_MODULE
    assert r["verdict"] not in P.CONCLUSIVE
    assert r["missing_modules"] == ["some_new_program"]


def test_collect_error_is_detected_from_the_transcript():
    assert P.harness_status("ERROR collecting tests/test_x.py\n") == "COLLECT_ERROR"
    assert P.harness_status(summary(test_a="PASSED")) == "OK"


# ------------------------------------------------------ end-to-end (P15..17)

def test_end_to_end_landed():
    r = P.probe_from_texts(summary(test_a="FAILED"), summary(test_a="PASSED"),
                           summary(test_a="PASSED"))
    assert r["verdict"] == P.VERDICT_LANDED
    assert r["discriminating"] == ["test_a"]


def test_end_to_end_unlanded():
    r = P.probe_from_texts(summary(test_a="FAILED"), summary(test_a="PASSED"),
                           with_failure_block(summary(test_a="FAILED"), "test_a",
                                              "AssertionError: nope"))
    assert r["verdict"] == P.VERDICT_UNLANDED


def test_every_unlanded_verdict_carries_the_not_a_work_item_warning():
    """#315 recorded salvage items that would have REGRESSED main if re-applied.
    A bare 'UNLANDED' reads as an instruction, so the caveat travels with it."""
    note = P.verdict_note(P.VERDICT_UNLANDED)
    assert "declined" in note
    assert "NOT necessarily work to do" in note


def test_conclusive_set_excludes_every_inconclusive_verdict():
    for v in (P.VERDICT_NO_DISCRIMINATION, P.VERDICT_MISSING_MODULE,
              P.VERDICT_API_DRIFT, P.VERDICT_BASE_UNRUNNABLE):
        assert v not in P.CONCLUSIVE
