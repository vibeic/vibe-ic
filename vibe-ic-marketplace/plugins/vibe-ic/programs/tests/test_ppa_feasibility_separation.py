#!/usr/bin/env python3
"""Spec 8.2: search may grade, promotion may not. Two code paths, no shared knob.

The failure this file exists to prevent is subtle and it is the reason the whole
lane exists. An optimiser needs a graded penalty or it has no gradient to walk.
A published promotion needs a hard refusal. If ONE code path serves both, the
penalty is by construction finite -- and a finite badness can always be
outweighed by a large enough win somewhere else. That is how a candidate with a
DRC violation wins.

So the tests below come in two halves:

  * the BEHAVIOURAL half builds the exact situation the spec names -- a
    candidate that a graded search would pick as the winner -- and shows it
    refused promotion anyway;
  * the STRUCTURAL half shows that the refusal is not a policy someone
    remembered to apply, but a property of the code, AND that the check which
    measures that property actually fires when the property is broken.
"""
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _ppa import feasibility as F  # noqa: E402
from _ppa import pareto as P  # noqa: E402
from test_ppa_feasibility import (VIEW, candidate, clean_metrics,  # noqa: E402
                                  metric, policy)


def _naive_search_score(cand_row, penalty):
    """The tempting single number: an objective gain minus a graded penalty.

    Written out here, in the test, precisely because it must never appear in
    the module under test. It is the thing a search is allowed to do and a
    report is not.
    """
    area, power, wns = cand_row
    return (-0.02 * area) + (-50.0 * power) + (10.0 * wns) - penalty


def test_a_graded_penalty_winner_is_still_refused_promotion():
    """The named fixture. The search's best candidate is ineligible.

    `hot` is better on every objective by a wide margin and carries one dirty
    LVS. Under any finite penalty a search will rank it first -- and it does,
    below, by construction. The promotion path returns INFEASIBLE regardless,
    because it never reads the score, the weights, or the penalty.
    """
    pol = policy()
    ms_ok = clean_metrics()
    ok = candidate("ok", ms_ok)

    ms_hot = clean_metrics()
    ms_hot[4]["value"] = "MISMATCH"          # LVS dirty -- the one violation
    hot = candidate("hot", ms_hot)

    r_ok = F.promotion_verdict(ok, pol)
    r_hot = F.promotion_verdict(hot, pol)

    w = F.PenaltyWeights(weights={"lvs": 1.0})
    pen_ok = F.search_penalty(r_ok, w)["penalty"]
    pen_hot = F.search_penalty(r_hot, w)["penalty"]
    assert pen_ok == 0.0 and pen_hot == 1.0, (pen_ok, pen_hot)

    # the objective triple: `hot` is far better on all three
    score_ok = _naive_search_score((100.0, 0.010, 0.05), pen_ok)
    score_hot = _naive_search_score((60.0, 0.006, 0.30), pen_hot)
    assert score_hot > score_ok, (score_hot, score_ok)   # the search picks `hot`

    # and the gate does not care in the slightest
    assert r_hot.verdict == F.INFEASIBLE
    assert not r_hot.eligible_for_promotion
    assert r_ok.eligible_for_promotion


def test_the_graded_penalty_winner_never_reaches_the_frontier():
    """The same fixture carried through to the public artefact."""
    pol = policy()
    S = dict(VIEW)
    ms_ok = clean_metrics() + [metric("area.total_um2", 100.0, "um2", S),
                               metric("power.total_w", 0.010, "W", S)]
    ms_hot = clean_metrics() + [metric("area.total_um2", 60.0, "um2", S),
                                metric("power.total_w", 0.006, "W", S)]
    ms_hot[0]["value"] = 0.30
    ms_hot[4]["value"] = "MISMATCH"
    cands = [candidate("ok", ms_ok), candidate("hot", ms_hot)]
    results = F.adjudicate_set(cands, pol)

    objectives = (P.Objective("area", "area.total_um2", P.SENSE_MIN, S),
                  P.Objective("power", "power.total_w", P.SENSE_MIN, S),
                  P.Objective("timing", "timing.setup.wns_ns", P.SENSE_MAX, S))
    doc = P.build_frontier(cands, results, objectives)

    assert doc["frontier"] == ["ok"]
    assert "hot" not in doc["frontier"]
    assert [r["candidate_id"] for r in doc["excluded_infeasible"]] == ["hot"]


def test_the_penalty_document_says_out_loud_that_it_is_not_a_verdict():
    r = F.promotion_verdict(candidate(), policy())
    out = F.search_penalty(r, F.PenaltyWeights())
    assert out["basis"] == "SEARCH_ONLY"
    assert out["promotable"] is None


# --- the structural half ----------------------------------------------------
def test_the_gate_call_closure_mentions_nothing_from_the_search_path():
    rep = F.separation_report()
    assert rep["search_names_reachable_from_gate"] == []
    assert "search_penalty" not in rep["gate_closure"]
    assert rep["separated"] is True


def test_the_two_configurations_share_no_field_so_no_threshold_is_shared():
    rep = F.separation_report()
    assert rep["shared_config_fields"] == []
    assert set(rep["gate_config_fields"]) & set(rep["search_config_fields"]) == set()


def test_the_separation_detector_actually_fires_when_the_separation_breaks():
    """The negative control for the check itself.

    A separation report that has only ever been run against a clean file proves
    nothing about its ability to notice a dirty one. Here the leak is put back:
    `promotion_verdict` is made to mention `search_penalty`, and the report must
    go false and name the edge.
    """
    leaked = F._module_source().replace(
        '    cid = str(candidate.get("candidate_id") or "")',
        '    cid = str(candidate.get("candidate_id") or ""); _ = search_penalty')
    assert "search_penalty" in leaked.split("def promotion_verdict")[1][:600]
    rep = F.separation_report(leaked)
    assert rep["separated"] is False
    assert "promotion_verdict->search_penalty" in \
        rep["search_names_reachable_from_gate"]


def test_the_shared_field_detector_actually_fires_on_a_shared_field():
    """The negative control for the other half of the same claim."""
    import dataclasses

    @dataclasses.dataclass(frozen=True)
    class _A:
        threshold: float = 0.0
        only_a: int = 0

    @dataclasses.dataclass(frozen=True)
    class _B:
        threshold: float = 0.0
        only_b: int = 0

    assert F.shared_field_names(_A, _B) == ["threshold"]
    assert F.shared_field_names(F.FeasibilityPolicy, F.PenaltyWeights) == []


def test_the_gate_has_no_numeric_margin_of_its_own():
    """There is no knob a caller could turn far enough to buy a promotion.

    `FeasibilityPolicy` carries an axis table, the views feasibility must hold
    across (globally and per axis), contract-declared limits and a waiver
    switch. None of those is a tolerance on a violation count or a slack; the
    only numbers in the gate are zero and the limits the CONTRACT declared.

    The set is enumerated EXACTLY rather than filtered, so a field added later
    has to be argued for here in a diff a reviewer sees, rather than sliding in
    under a name the substring list below happens not to catch.
    `required_views_by_axis` is the views ONE axis must hold across; it cannot
    express "any view will do" (an axis named with an empty list is
    UNDETERMINED, exactly as an undeclared global list is) so it is a view
    declaration and not a knob.

    `eco_requirement` is the DESIGN's design-for-ECO declaration, carried
    verbatim. It is argued for here because this test is where a new field has
    to be argued for. It is not a tolerance, and the direction it can move a
    verdict is the one that matters: the ONLY thing it can do on its own is
    make a candidate INFEASIBLE that would otherwise have been FEASIBLE, by
    stating a floor the candidate does not meet. Absent, it produces
    NOT_APPLICABLE -- which is the behaviour of every contract written before
    it existed, so adding it changed no standing verdict. The numbers it
    carries are the design's, never this module's;
    `test_no_spare_count_or_density_is_hard_coded_in_the_gate` measures that
    the gate contains none of its own.
    """
    fields = {f.name for f in __import__("dataclasses").fields(
        F.FeasibilityPolicy)}
    assert fields == {"axes", "required_views", "required_views_by_axis",
                      "limits", "allow_waivers", "eco_requirement"}
    assert not any(n in fields for n in
                   ("tolerance", "margin", "penalty", "weight", "weights",
                    "score", "threshold"))
