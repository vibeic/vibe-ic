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
import json
import os
import sys
from pathlib import Path

import pytest

import _sweep_reach as sr
import _vacuous_exit as vx
import sweep_reach_survey as srv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(srv.__file__).resolve().parent


# --------------------------------------------------------------- fixtures
def _probe(body: str) -> str:
    return ("#!/usr/bin/env python3\nimport argparse, os, sys\n"
            "def main():\n"
            "    ap = argparse.ArgumentParser()\n"
            "    ap.add_argument('paths', nargs='+')\n"
            "    a = ap.parse_args()\n"
            + body +
            "\nsys.exit(main())\n")


#: DISCLOSES when handed directories, SILENT when handed files. The shape whose
#: verdict the aggregation rule — and nothing else — decides.
TWO_FACED = _probe(
    "    if all(os.path.isdir(p) for p in a.paths):\n"
    "        print('VACUOUS_PASS: probe examined nothing')\n"
    "        return 2\n"
    "    print('PASS - probe swept', len(a.paths), 'item(s)')\n"
    "    return 0\n")

ALWAYS_DISCLOSES = _probe(
    "    print('VACUOUS_PASS: probe examined nothing')\n    return 2\n")

ALWAYS_SILENT = _probe(
    "    print('PASS - probe swept', len(a.paths), 'item(s)')\n    return 0\n")

#: DISCLOSES on directories, and blows up on files. A NOT_DRIVABLE attempt must
#: NOT drag a program out of the numerator: the probe corpus failing to express
#: one argv shape is a fact about the corpus, not about the program.
DISCLOSES_OR_CRASHES = _probe(
    "    if all(os.path.isdir(p) for p in a.paths):\n"
    "        print('VACUOUS_PASS: probe examined nothing')\n"
    "        return 2\n"
    "    raise RuntimeError('this probe cannot take files')\n")


def _tree(root: Path, **programs: str) -> Path:
    d = root / "probe_programs"
    d.mkdir(exist_ok=True)
    for name, body in programs.items():
        (d / f"{name}.py").write_text(body)
    return d


def _verdicts(root: Path, **programs: str) -> dict:
    doc = srv.survey(_tree(root, **programs), timeout=45)
    doc.pop("_reach", None)
    return {r["program"]: r for r in doc["rows"]}


# =====================================================================
class TestConservativeAggregationHasABidirectionalControl:
    """Direction 1: the rule fires. Direction 2: it stays out of the way."""

    def test_a_program_silent_under_any_shape_is_counted_silent(self, tmp_path):
        """POSITIVE control — the branch a favourable-selection bug removes.

        ``classify_run`` alone cannot express this: each invocation is
        individually correct. Only ``survey()``'s aggregation decides it.
        """
        rows = _verdicts(tmp_path, probe_two_faced=TWO_FACED)
        row = rows["probe_two_faced.py"]
        seen = sorted({a["verdict"] for a in row["attempts"]})
        assert seen == ["DISCLOSES", "SILENT"], (
            "the fixture must actually produce BOTH verdicts, or this control "
            f"is a zero over an empty set; got {seen}")
        assert row["verdict"] == "SILENT", (
            "a program that can report clean having judged nothing under ANY "
            "drivable argv is SILENT; taking its most flattering invocation is "
            "measurement by selection")
        assert row["deciding_invocation"] == next(
            a["invocation"] for a in row["attempts"] if a["verdict"] == "SILENT")

    def test_a_program_that_discloses_under_every_shape_is_not_downgraded(self, tmp_path):
        """NEGATIVE control — same code path, nothing to report."""
        rows = _verdicts(tmp_path, probe_ok=ALWAYS_DISCLOSES)
        assert rows["probe_ok.py"]["verdict"] == "DISCLOSES"

    def test_the_two_are_distinguishable_in_the_published_ratio(self, tmp_path):
        """The property, asserted on the headline number rather than on a row."""
        doc = srv.survey(_tree(tmp_path, probe_two_faced=TWO_FACED,
                               probe_ok=ALWAYS_DISCLOSES), timeout=45)
        doc.pop("_reach", None)
        assert doc["ratio"] == "1/2", (
            "the two fixtures differ ONLY in whether one argv shape is silent; "
            f"if the ratio cannot tell them apart the rule is dead. {doc['ratio']}")


# =====================================================================
class TestReverseCaseMustStillPass:
    """Conservatism must not be widened into 'any bad attempt loses'."""

    def test_a_not_drivable_attempt_does_not_remove_a_disclosing_program(self, tmp_path):
        """The real ``formal_harness_gen.py`` shape.

        NOT_DRIVABLE says the generic probe corpus could not express that argv.
        Letting it outrank DISCLOSES would shrink the numerator for a fact
        about the CORPUS, and would make the survey under-report exactly the
        programs that already do the right thing.
        """
        rows = _verdicts(tmp_path, probe_mixed=DISCLOSES_OR_CRASHES)
        seen = sorted({a["verdict"] for a in rows["probe_mixed.py"]["attempts"]})
        assert seen == ["DISCLOSES", "NOT_DRIVABLE"], seen
        assert rows["probe_mixed.py"]["verdict"] == "DISCLOSES"

    def test_a_uniformly_silent_program_is_still_just_silent(self, tmp_path):
        rows = _verdicts(tmp_path, probe_quiet=ALWAYS_SILENT)
        assert rows["probe_quiet.py"]["verdict"] == "SILENT"
        assert {a["verdict"] for a in rows["probe_quiet.py"]["attempts"]} == {"SILENT"}


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
class TestTheCounterMeasurementIsRederivable:
    """The 'point it at an empty corpus' number must come from the instrument."""

    @pytest.mark.parametrize("mode", ["none", "dirs"])
    def test_empty_corpus_mode_runs_and_publishes_its_own_denominator(self, tmp_path, mode):
        doc = srv.survey(_tree(tmp_path, probe_two_faced=TWO_FACED,
                               probe_ok=ALWAYS_DISCLOSES),
                         timeout=45, empty_corpus=mode)
        doc.pop("_reach", None)
        assert doc["corpus"] == f"empty:{mode}"
        assert doc["discovered"] == 2
        assert doc["driven"] + doc["not_drivable"] == 2
        assert sr.reach_violations(doc) == []

    def test_the_populated_corpus_is_the_default_and_is_labelled(self, tmp_path):
        doc = srv.survey(_tree(tmp_path, probe_ok=ALWAYS_DISCLOSES), timeout=45)
        doc.pop("_reach", None)
        assert doc["corpus"] == "populated"

    def test_the_two_corpora_are_not_the_same_measurement(self, tmp_path):
        """V1 'I was given nothing' and V2 'I judged nothing' must not collapse.

        The two-faced probe reads three real modules and reports clean; handed
        nothing, it cannot even parse its argv. Same program, different claim.
        """
        tree = _tree(tmp_path, probe_two_faced=TWO_FACED)
        pop = srv.survey(tree, timeout=45)
        emp = srv.survey(tree, timeout=45, empty_corpus="none")
        assert pop["rows"][0]["verdict"] == "SILENT"
        assert emp["rows"][0]["verdict"] == "NOT_DRIVABLE"


# =====================================================================
class TestAnArgShapeWithNoTargetsIsNotThatShape:
    """``_invocations``: a labelled shape emptied of its targets is a LIE.

    This is the one rule in this change that lives in a function present, with
    the same signature, on both sides of it — so its control fails on the
    pre-change tree by DISAGREEING ABOUT A VALUE rather than by not finding a
    name. It is the reason the two empty-corpus denominators (29 and 18) are
    different numbers instead of the same number twice: without the drop, the
    ``dirs`` corpus also drives a target-less ``…/files`` invocation, which is
    the ``none`` corpus wearing the ``dirs`` label, and both measurements
    collapse into the one they were supposed to be contrasted against.
    """

    POSITIONAL = {"positionals": True, "options": []}
    OPTIONED = {"positionals": False, "options": ["--paths"]}

    def test_a_files_shape_with_no_files_is_dropped(self):
        got = sorted(srv._invocations(Path("p.py"), self.POSITIONAL,
                                      [], ["d0", "d1"]))
        assert got == ["positional/dirs"], (
            "a 'files' invocation built from an empty file list carries no "
            "target at all; driving it and recording its verdict under the "
            f"files label attributes the no-targets answer to this corpus. {got}")

    def test_the_same_holds_for_an_optioned_shape(self):
        got = sorted(srv._invocations(Path("p.py"), self.OPTIONED, [], ["d0"]))
        assert got == ["--paths/dirs"], got

    def test_every_surviving_invocation_actually_carries_a_target(self):
        """Stated as the property, not as a label list."""
        for shape in (self.POSITIONAL, self.OPTIONED):
            for label, cmd in srv._invocations(Path("p.py"), shape,
                                               ["f0"], ["d0"]).items():
                assert len(cmd) > 1, (label, cmd)
            for label, cmd in srv._invocations(Path("p.py"), shape,
                                               [], ["d0"]).items():
                assert len(cmd) > 1, (
                    f"{label} survived with no target after its list was "
                    f"emptied: {cmd}")

    def test_the_no_targets_corpus_is_still_driven_once(self):
        """REVERSE direction — the drop must not delete the ``none`` corpus.

        When BOTH lists are empty that is not an accident of one shape being
        emptied, it is the deliberate 'I was given nothing' corpus, and it has
        to reach the program or ``--empty-corpus none`` measures nothing.
        """
        for shape in (self.POSITIONAL, self.OPTIONED):
            got = srv._invocations(Path("p.py"), shape, [], [])
            assert len(got) == 2, got
            assert all(len(c) == 1 for c in got.values()), got


# =====================================================================
class TestTheCorpusLabelReachesTheReportAReaderSees:
    """The label has to be in the TEXT the operator reads, not only the JSON.

    A ratio quoted from a terminal is quoted from these lines. Asserting on
    ``doc['corpus']`` alone would leave the printed report free to omit it.
    """

    def _run(self, tmp_path, *extra):
        tree = _tree(tmp_path, probe_ok=ALWAYS_DISCLOSES)
        return _pr.run(
            [sys.executable, str(PROGRAMS / "sweep_reach_survey.py"),
             "--programs-dir", str(tree), "--timeout", "30", *extra],
            capture_output=True, text=True, cwd=str(PROGRAMS),
            env={**os.environ, "PYTHONPATH": str(PROGRAMS)})

    def test_the_populated_report_names_its_corpus(self, tmp_path):
        out = self._run(tmp_path).stdout
        assert "corpus: populated" in out, (
            "the printed report gives a ratio with no statement of which "
            f"corpus produced it:\n{out}")

    def test_the_empty_report_names_a_different_corpus(self, tmp_path):
        out = self._run(tmp_path, "--empty-corpus", "dirs").stdout
        assert "corpus: empty:dirs" in out, out
        assert "corpus: populated" not in out, out


# =====================================================================
class TestTheRuleIsLoadBearingOnTheRealCorpus:
    """This file's own corpus sweep — over ``programs/``, and it must FIRE.

    Everything above is a fixture. If no REAL program in this tree ever
    produces two different verdicts, the aggregation rule is never entered and
    every control above is a zero over an empty set.
    """

    def test_the_aggregation_decision_point_is_entered_on_real_programs(self):
        doc = srv.survey(PROGRAMS, timeout=45)
        doc.pop("_reach", None)

        own = sr.SweepReach(
            unit="sweep-shaped program in programs/",
            decision_points=("verdicts_agreed", "verdicts_disagreed"))
        decisive = []
        for row in doc["rows"]:
            seen = {a["verdict"] for a in row["attempts"]}
            if len(seen) > 1:
                own.reached(row["program"], point="verdicts_disagreed")
                if {"SILENT", "DISCLOSES"} <= seen:
                    decisive.append(row["program"])
            else:
                own.reached(row["program"], point="verdicts_agreed")

        # ---- this sweep's OWN reach, asserted BEFORE any finding is read.
        rep = own.report()
        assert sr.reach_violations({sr.REACH_KEY: rep}) == []
        assert rep["reached"] == doc["discovered"] > 0, rep
        assert rep["decision_points"]["verdicts_disagreed"] > 0, (
            "no program in programs/ produced two different per-invocation "
            "verdicts, so survey()'s aggregation was never entered and every "
            f"fixture control in this file is a zero over an empty set. {rep}")

        # ---- and only now, the finding.
        assert decisive, (
            "no real program is SILENT under one argv and DISCLOSES under "
            "another, so the SILENT-beats-DISCLOSES rule changed no real "
            "verdict on this run. The rule is then unmeasured on the corpus "
            "that produces the published ratio, and the ratio should not be "
            f"quoted as if the rule had been exercised. reach={rep}")

    def test_the_published_ratio_moves_when_the_rule_is_removed(self):
        """The mutation, run against the REAL corpus rather than described.

        ``survey()`` is re-aggregated here from its own recorded per-invocation
        attempts, so this needs no edit to the shipped file and cannot drift
        away from what the shipped file actually did.
        """
        doc = srv.survey(PROGRAMS, timeout=45)
        doc.pop("_reach", None)

        def ratio(favourable: bool) -> str:
            disc = driven = 0
            for row in doc["rows"]:
                seen = {a["verdict"] for a in row["attempts"]}
                if favourable:
                    final = ("DISCLOSES" if "DISCLOSES" in seen
                             else "SILENT" if "SILENT" in seen else "NOT_DRIVABLE")
                else:
                    final = ("SILENT" if "SILENT" in seen
                             else "DISCLOSES" if "DISCLOSES" in seen
                             else "NOT_DRIVABLE")
                if final != "NOT_DRIVABLE":
                    driven += 1
                    disc += (final == "DISCLOSES")
            return f"{disc}/{driven}"

        shipped, inflated = ratio(False), ratio(True)
        assert shipped == doc["ratio"], (
            "re-aggregating the shipped attempts must reproduce the shipped "
            f"ratio, or this control is measuring something else: "
            f"{shipped} vs {doc['ratio']}")
        assert shipped != inflated, (
            "taking each program's most flattering invocation produced the "
            f"SAME ratio ({shipped}); the rule is not load-bearing on this "
            "corpus and the controls above prove nothing about the number")
