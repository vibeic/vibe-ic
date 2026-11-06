"""The rule that decides the published ratio must itself have a control.

WHAT THIS FILE ADDS TO ``test_sweep_reach_contract.py``
=======================================================
``_sweep_reach`` ships with a ratio produced by ``sweep_reach_survey.py``. Two
decisions inside that instrument move the ratio, and neither had a control:

1. ``survey()`` aggregates several argv shapes per program and takes the LEAST
   flattering one — ``SILENT`` beats ``DISCLOSES``. This is the rule whose
   ABSENCE the survey's own module docstring calls "measurement by selection".
   The only test naming it (``test_one_silent_witness_decides_a_program``)
   asserts on ``classify_run`` — the per-invocation classifier — and never on
   the aggregation. MEASURED: swapping the two branches so the most flattering
   invocation wins leaves the whole contract suite green at 32/32 and moves the
   published ratio from 8/35 to 14/35 on this tree.

2. ``SweepReach.absorb_child_rc`` counts a child that returned rc 1 as REACHED:
   a child that FAILED entered the guard, it just did not like what it found.
   No test passed it an ``RC_FAIL``. MEASURED: changing the branch to
   ``rc != RC_PASS`` leaves the suite green at 32/32, and then a sweep whose 756
   children each ran the guard and each found a violation publishes
   ``reached the decision point on 0 of 756`` with the fabricated reason
   "child gate returned rc 2 (examined nothing)" — the exact inversion the
   module exists to prevent, in the API the change calls "the bridge the
   756-pair sweep lacked".

APPLIED TO ITSELF — AND THIS IS THE POINT
=========================================
A control for a rule that the corpus never triggers is a zero over an empty
set. ``TestTheRuleIsLoadBearingOnTheRealCorpus`` therefore sweeps the REAL
``programs/`` tree, accounts for its own reach with ``SweepReach``, and asserts
that the aggregation's deciding branch was ENTERED on real programs before it
reads any finding. On this tree it is entered on 6 of 35 driven programs — the
same 6 that separate 8/35 from 14/35.

HOW THIS FILE FAILS AGAINST THE TREE BEFORE THE CHANGE
======================================================
MEASURED on the rebased base (``94b6c495``, this stack's first commit on top of
``e0a5257b``): 9 fail, 14 pass, 0 collection errors. Classified honestly,
because a failure count is not evidence:

  4  TAUTOLOGICAL — ``TypeError: survey() got an unexpected keyword argument
     'empty_corpus'`` x3 and ``KeyError: 'corpus'`` x1. These say the name is
     new. They prove the switch was added, not that anything behaves better.

  3  SUBSTANTIVE — ``TestAnArgShapeWithNoTargetsIsNotThatShape`` asserts on the
     return value of ``_invocations``, which exists with the SAME signature on
     both sides. The pre-change tree disagrees about a VALUE:
     ``['positional/dirs', 'positional/files']`` where only the first shape
     still carries a target.

  2  OBSERVED OUTPUT, of a field this change introduces —
     ``TestTheCorpusLabelReachesTheReportAReaderSees`` compares against the
     report text the pre-change program really prints. That is an observed
     value, but the thing missing from it is this change's own line, so it is
     counted apart from the 3 above rather than with them.

  14 PASS on both sides ON PURPOSE. The aggregation rule and
     ``absorb_child_rc`` are already CORRECT in the shipped code; this file
     exists because nothing held them there. Their control is the mutation run
     in ``TestTheRuleIsLoadBearingOnTheRealCorpus``, not a red-to-green flip.

Fixtures are invented grammar (probe_*.py) with no PDK identity of any kind.
"""
import sys
from pathlib import Path


import _sweep_reach as sr
import _vacuous_exit as vx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))



# --------------------------------------------------------------- fixtures


#: DISCLOSES when handed directories, SILENT when handed files. The shape whose
#: verdict the aggregation rule — and nothing else — decides.



#: DISCLOSES on directories, and blows up on files. A NOT_DRIVABLE attempt must
#: NOT drag a program out of the numerator: the probe corpus failing to express
#: one argv shape is a fact about the corpus, not about the program.






# =====================================================================


# =====================================================================


# =====================================================================
class TestAFailingChildReachedTheGuard:
    """``absorb_child_rc``: rc 1 is a reading of the guard, not an absence of one."""

    def test_rc_fail_children_are_reached_not_vacuous(self):
        """POSITIVE control for the branch no test exercised."""
        reach = sr.SweepReach(unit="ordered audit pair")
        for i in range(5):
            reach.absorb_child_rc(f"pair-{i}", vx.RC_FAIL)
        assert reach.n_reached == 5
        assert reach.is_vacuous is False
        assert reach.report()["coverage"] == "5/5"
        assert "0 of 5" not in reach.line()

    def test_rc_vacuous_children_are_still_not_reached(self):
        """NEGATIVE control — the direction the shipped test already covers,
        restated here so the pair cannot drift apart."""
        reach = sr.SweepReach(unit="ordered audit pair")
        reach.absorb_child_rc("p", vx.RC_VACUOUS)
        assert reach.is_vacuous is True

    def test_a_mixed_child_population_is_partial_not_vacuous(self):
        """REVERSE case: some ran, some did not — a legitimate partial sweep."""
        reach = sr.SweepReach(unit="ordered audit pair")
        reach.absorb_child_rc("a", vx.RC_FAIL)
        reach.absorb_child_rc("b", vx.RC_VACUOUS)
        reach.absorb_child_rc("c", vx.RC_PASS)
        rep = reach.report()
        assert (rep["reached"], rep["targets"]) == (2, 3)
        assert rep["is_vacuous"] is False
        assert reach.exit_code(passed=False) == vx.RC_FAIL
        assert sr.reach_violations({sr.REACH_KEY: rep}) == []

    def test_the_reason_recorded_for_a_failing_child_is_never_examined_nothing(self):
        """The mutation's visible symptom, pinned.

        Counting rc 1 as a non-reach does not only move a number: it writes
        "examined nothing" against a child that examined the design and found a
        violation, and ``as_denominator`` then publishes that sentence.
        """
        reach = sr.SweepReach(unit="ordered audit pair")
        reach.absorb_child_rc("p", vx.RC_FAIL)
        assert reach.reasons() == {}
        assert reach.as_denominator().not_applicable_reason == ""


# =====================================================================
class TestTheEmptyCorpusRuleIsCheckedOnTheConsumerSide(object):
    """``report()`` cannot emit an unexplained empty corpus; a report read from
    DISK can carry one, so ``reach_violations`` must catch it too."""

    def test_an_unexplained_empty_corpus_report_is_a_violation(self):
        assert sr.reach_violations({sr.REACH_KEY: {
            "unit": "pair", "targets": 0, "reached": 0, "not_reached": 0,
            "is_vacuous": True, "not_reached_reasons": {},
            "decision_points": {}}})

    def test_an_explained_empty_corpus_report_is_not(self):
        assert sr.reach_violations({sr.REACH_KEY: {
            "unit": "pair", "targets": 0, "reached": 0, "not_reached": 0,
            "is_vacuous": True, "not_reached_reasons": {},
            "decision_points": {},
            "empty_corpus_reason": "the project filter matched no design"}}) == []


# =====================================================================


# =====================================================================


# =====================================================================


# =====================================================================
