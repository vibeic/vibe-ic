#!/usr/bin/env python3
"""A finding added to `si_mcf_sta_check` at WARNING severity must not move the
verdict its own re-adjudication rule would issue over a published record.

WHAT WAS MEASURED
-----------------
v1.14.24 moved `si_mcf_sta_check.build_report`'s closure — three new `summary`
keys — and did not re-review the `RECORD_ADJUDICATION` declaration pinned over
it, so `published_record_staleness_check` booked the gate `RULES_UNREVIEWED`
and both its published records went undecidable:

    [FAIL] 1 gate(s) changed their decision logic without their re-adjudication
           rules being re-reviewed.
      [RULES_UNREVIEWED] gate si_mcf_sta_check
          declared bab7cda2e01f, now 4e7ac17edadb

The digest is a fingerprint over SOURCE, so re-declaring it is one line and
carries no evidence about behaviour. What the re-review actually had to answer
is the question the same commit created and the digest can only point at: the
same change made `audit()` emit a NEW finding, `WINDOW_COVERAGE_PARTIAL`, and
`_zero_fold_supersession` rebuilds `Finding` objects out of the record's own
`findings` list and puts them through `error_categories`. A new finding
reaching that list is a new input to a verdict rule.

`test_si_mcf_escaped_spef_pin_names` already pins the severity at the EMITTER
(the audit emits it as WARNING, never ERROR). Nothing pinned the CONSUMER end —
that the warning, once it is sitting in a PUBLISHED record, cannot change what
this repo says about that record's verdict. That is the coupling here, and it
is the half that outlives the run: records are committed and re-adjudicated
later, against a gate that has moved on.

THE CONTROL IS BIDIRECTIONAL
----------------------------
Asserting only "the warning changes nothing" would pass just as well against a
rule that reads no findings at all, or against a test that built the wrong
record. So the same category is also injected at ERROR severity, where it MUST
change the answer — that is what proves these tests are measuring SEVERITY and
not measuring nothing.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))

import _record_adjudication as _ra         # noqa: E402
import si_mcf_sta_check as SI              # noqa: E402

#: The finding v1.14.24 added, verbatim in the shape `audit()` publishes it.
_COVERAGE_WARNING = {
    "severity": "WARNING",
    "category": "WINDOW_COVERAGE_PARTIAL",
    "message": ("switching windows resolved for 465 of 1558 coupling net(s) "
                "(29.8%); the remaining 1093 were folded at the worst-case "
                "Miller factor"),
}


def _rule():
    """The gate's OWN registered rule — not a copy of its logic."""
    rules = [r for r in SI.RECORD_ADJUDICATION.rules
             if r.rule_id == "si_mcf_sta_check.zero-fold-is-not-a-signoff"]
    assert len(rules) == 1, "the rule under test is not registered"
    return rules[0]


def _record(verdict="PASS", coupling_pairs=0, findings=()):
    return {
        "program": "si_mcf_sta_check",
        "verdict": verdict,
        "summary": {"coupling_pairs": coupling_pairs},
        "findings": [copy.deepcopy(f) for f in findings],
    }


def test_the_declaration_is_reviewed_against_the_logic_it_is_pinned_over():
    """The digest names the closure that ships, so the rest of this file is
    describing the gate that is actually installed."""
    assert SI.RECORD_ADJUDICATION.drift() is None


def test_the_coverage_warning_does_not_change_what_the_rule_would_issue():
    rule = _rule()
    without = rule.decide(_record())
    withw = rule.decide(_record(findings=[_COVERAGE_WARNING]))

    assert isinstance(without, _ra.Supersession)
    assert without.would_issue == "VACUOUS_PASS"
    assert isinstance(withw, _ra.Supersession)
    assert withw.would_issue == without.would_issue


def test_the_same_category_at_ERROR_severity_DOES_change_it():
    """The negative control. Without this the test above would pass against a
    rule that never opened `findings`."""
    escalated = dict(_COVERAGE_WARNING, severity="ERROR")
    out = _rule().decide(_record(findings=[escalated]))

    assert isinstance(out, _ra.Supersession)
    # WINDOW_COVERAGE_PARTIAL is not a could-not-run category, so at ERROR it
    # lands in `defect` and the precedence answers FAIL, not VACUOUS_PASS.
    assert out.would_issue == "FAIL"
    assert out.would_issue != "VACUOUS_PASS"


def test_error_categories_is_where_the_severity_is_read():
    """Names the line the two tests above depend on, so a reader who breaks it
    is told WHICH function decided, not just that a verdict moved."""
    warn = SI.Finding("WARNING", "WINDOW_COVERAGE_PARTIAL", "x")
    err = SI.Finding("ERROR", "WINDOW_COVERAGE_PARTIAL", "x")

    assert SI.error_categories([warn]) == ([], [])
    assert SI.error_categories([err]) == ([], ["WINDOW_COVERAGE_PARTIAL"])
    assert "WINDOW_COVERAGE_PARTIAL" not in SI.NOT_RUN_CATEGORIES


def test_a_record_that_re_derived_folds_is_still_not_reached_by_this_rule():
    """The published records this gate actually has carry thousands of pairs,
    so the re-adjudication that cleared the RULES_UNREVIEWED red decided them
    STILL CURRENT. Pinned here with the warning present, because that is the
    shape a record produced by today's gate will have."""
    rule = _rule()
    for pairs in (1558, 2066):
        rec = _record(coupling_pairs=pairs, findings=[_COVERAGE_WARNING])
        assert rule.decide(rec) is None, (
            f"a run that re-derived {pairs} coupling pair(s) is not a "
            f"zero-fold sign-off and this rule must decline to speak")
