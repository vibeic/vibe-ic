#!/usr/bin/env python3
"""The two comparability mutations the spec names. Each one must be RED.

    M2  power better, but measured against a different activity basis
    M3  area better, but taken at a different stage

They are the same defect wearing two coats: a number that is better than another
number, describing something that is not the same thing. Vectorless power and
vector-driven power are different metrics; synthesis area and post-route area
are different metrics. A frontier that compares them announces a winner that
does not exist, and the announcement is indistinguishable from a real one.

The refusal has to be an EXCLUSION, not a shrug. Saying "we cannot compare them,
so neither dominates, so both stay" is how the mismatched candidate gets
published -- nobody could show it was worse.
"""
import json
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _ppa import feasibility as F  # noqa: E402
from _ppa import pareto as P  # noqa: E402
from test_ppa_feasibility import VIEW  # noqa: E402
from test_ppa_pareto import (AREA_SCOPE, CONTRACT, OBJECTIVES,  # noqa: E402
                             POWER_SCOPE, build, cand, run)


# --- M2 ---------------------------------------------------------------------
def test_M2_power_better_but_a_different_activity_basis_is_not_better():
    """0.001 W vectorless does not beat 0.010 W from a real switching trace.

    The candidate is better on paper on every objective. Its power number was
    produced by a different question being asked of the design, so it is not on
    the frontier and it is not dominated either -- it is UNDETERMINED, named,
    with the reason attached.
    """
    other_basis = {**VIEW, **POWER_SCOPE, "activity_basis": "vectorless"}
    cands = [cand("HONEST", 100.0, 0.010, 0.05),
             cand("BASIS", 60.0, 0.001, 0.40, power_scope=other_basis)]
    _, doc = build(cands)

    assert doc["frontier"] == ["HONEST"]
    assert "BASIS" not in doc["frontier"]
    undet = {u["candidate_id"]: u["codes"] for u in doc["undetermined"]}
    assert "BASIS" in undet
    assert "PARETO_SCOPE_MISMATCH" in undet["BASIS"]
    # and it was NOT recorded as merely dominated -- that would be a claim
    assert [d["candidate_id"] for d in doc["dominated"]] == []


def test_M2_the_positive_control_the_same_basis_does_compare():
    """Without this, the test above proves only that nothing ever compares."""
    cands = [cand("HONEST", 100.0, 0.010, 0.05),
             cand("SAME", 60.0, 0.001, 0.40)]
    _, doc = build(cands)
    assert doc["frontier"] == ["SAME"]
    assert [d["candidate_id"] for d in doc["dominated"]] == ["HONEST"]


def test_M2_the_cli_refuses_to_publish_the_mismatched_candidate(tmp_path):
    other_basis = {**VIEW, **POWER_SCOPE, "activity_basis": "vectorless"}
    cands = [cand("HONEST", 100.0, 0.010, 0.05),
             cand("BASIS", 60.0, 0.001, 0.40, power_scope=other_basis)]
    r, doc = run(tmp_path, cands, frontier={"frontier": ["BASIS"]})
    assert r.returncode != F.RC_PASS, r.stdout + r.stderr
    codes = {f["code"] for f in doc["findings"]}
    assert "PARETO_UNDETERMINED_JUDGED_BETTER" in codes


def test_M2_a_mismatched_basis_alone_makes_the_run_undetermined(tmp_path):
    """Even with nobody publishing anything wrong, the run claims no winner."""
    other_basis = {**VIEW, **POWER_SCOPE, "activity_basis": "vectorless"}
    r, doc = run(tmp_path, [cand("HONEST", 100.0, 0.010, 0.05),
                            cand("BASIS", 60.0, 0.001, 0.40,
                                 power_scope=other_basis)])
    assert r.returncode == F.RC_UNDETERMINED
    assert "[CANNOT CHECK]" in r.stderr


# --- M3 ---------------------------------------------------------------------
def test_M3_area_better_but_a_different_stage_is_not_better():
    """A synthesis area estimate does not beat a post-route area.

    They differ by everything place-and-route adds, which is exactly the part
    the comparison is supposed to be about.
    """
    synth = {**VIEW, "stage": "post_synth"}
    cands = [cand("ROUTED", 100.0, 0.010, 0.05),
             cand("SYNTH", 55.0, 0.009, 0.20, area_scope=synth)]
    _, doc = build(cands)

    assert doc["frontier"] == ["ROUTED"]
    undet = {u["candidate_id"]: u["codes"] for u in doc["undetermined"]}
    assert "PARETO_SCOPE_MISMATCH" in undet["SYNTH"]


def test_M3_the_positive_control_the_same_stage_does_compare():
    cands = [cand("ROUTED", 100.0, 0.010, 0.05),
             cand("SMALLER", 55.0, 0.009, 0.20)]
    _, doc = build(cands)
    assert doc["frontier"] == ["SMALLER"]


def test_M3_the_scope_check_is_a_subset_match_not_an_equality():
    """A contract asks for the stage; it does not have to restate everything.

    A record carrying extra scope keys the objective did not name still counts,
    or every contract would have to enumerate the whole corner to compare one
    number.
    """
    rich = {**VIEW, **AREA_SCOPE, "rc_corner": "max", "mode": "functional"}
    cands = [cand("A", 100.0, 0.010, 0.05, area_scope=rich),
             cand("B", 140.0, 0.014, 0.30)]
    _, doc = build(cands)
    assert doc["undetermined"] == []
    assert sorted(doc["frontier"]) == ["A", "B"]


def test_M3_two_records_that_both_match_but_differ_elsewhere_is_undetermined():
    """Two different measurements, both admissible, is not one number."""
    from test_ppa_feasibility import metric
    c = cand("TWO", 100.0, 0.010, 0.05)
    c["metrics"].append(metric("area.total_um2", 60.0, "um2",
                               {**VIEW, **AREA_SCOPE, "rc_corner": "min"}))
    _, doc = build([c, cand("B", 140.0, 0.014, 0.30)])
    undet = {u["candidate_id"]: u["codes"] for u in doc["undetermined"]}
    assert "PARETO_SCOPE_DIVERGENT" in undet["TWO"]


# --- the shared property both mutations are instances of --------------------
def test_an_incomparable_candidate_is_excluded_rather_than_left_undominated():
    """The load-bearing inversion, stated once.

    Under the naive rule an incomparable candidate stays on the frontier
    because nothing can be shown to beat it. Here it is not admitted at all.
    """
    other = {**VIEW, **POWER_SCOPE, "activity_basis": "vectorless"}
    cands = [cand("X", 60.0, 0.001, 0.40, power_scope=other)]
    _, doc = build(cands)
    assert doc["frontier"] == []
    assert [u["candidate_id"] for u in doc["undetermined"]] == ["X"]


def test_all_six_mutation_shapes_together_never_produce_rc0(tmp_path):
    """One run carrying every named mutation. It must not report a winner."""
    other = {**VIEW, **POWER_SCOPE, "activity_basis": "vectorless"}
    synth = {**VIEW, "stage": "post_synth"}
    m1 = cand("M1", 60.0, 0.005, 9.0, lvs="MISMATCH")           # WNS up, LVS bad
    m2 = cand("M2", 60.0, 0.001, 0.40, power_scope=other)       # basis differs
    m3 = cand("M3", 55.0, 0.009, 0.20, area_scope=synth)        # stage differs
    m4 = cand("M4", 90.0, 0.009, 0.20)                          # DRC never ran
    for m in m4["metrics"]:
        if m["metric"] == "physical.drc.violations":
            m["status"] = "NOT_MEASURED"
            m["value"] = 0
    m5 = cand("M5", 80.0, 0.008, 0.10)                          # unowned waiver
    for m in m5["metrics"]:
        if m["metric"] == "physical.drc.violations":
            m["value"] = 3
    m5["waivers"] = [{"waiver_id": "W", "axis": "drc",
                      "justification": "looks fine", "owner": ""}]
    ok = cand("OK", 100.0, 0.010, 0.05)

    r, doc = run(tmp_path, [m1, m2, m3, m4, m5, ok])
    assert r.returncode != F.RC_PASS, r.stdout + r.stderr
    assert doc["frontier"] == ["OK"]
    excluded = {e["candidate_id"] for e in doc["excluded_infeasible"]}
    undetermined = {u["candidate_id"] for u in doc["undetermined"]}
    assert {"M1", "M5"} <= excluded          # measured violations
    assert "M4" in excluded                  # not adjudicated by the hard gate
    assert {"M2", "M3"} <= undetermined      # not comparable
    assert P.assert_no_collapsed_scalar(doc) == []


def test_M6_an_incomplete_view_set_keeps_a_candidate_off_the_frontier(tmp_path):
    """The sixth mutation, carried through to the public artefact."""
    contract = json.loads(json.dumps(CONTRACT))
    contract["required_views"] = [VIEW, {**VIEW, "process": "ff"}]
    r, doc = run(tmp_path, [cand("A", 100.0, 0.010, 0.05)], contract=contract)
    assert r.returncode == F.RC_UNDETERMINED
    assert doc["frontier"] == []
    assert doc["excluded_infeasible"][0]["candidate_id"] == "A"
