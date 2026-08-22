#!/usr/bin/env python3
"""Four of the six mutations the spec names. Each one must be RED.

A mutation case is a candidate that a careless gate calls promotable. Every test
here asserts the refusal, so if the rule that produces the refusal is removed
the test named in it goes red and says which rule went.

    M1  WNS improved but LVS fails            -> INFEASIBLE
    M4  DRC count 0 but DRC never ran         -> UNDETERMINED  (never FEASIBLE)
    M5  a waiver with no owner                -> the violation stands
    M6  an incomplete view set                -> UNDETERMINED

The two remaining mutations are about COMPARABILITY rather than eligibility and
live with the frontier, in `test_ppa_pareto_mutations.py`:

    M2  power better but a different activity basis
    M3  area better but a different stage

M4's shape is the reason rc=2 exists at all. "DRC reported zero violations" and
"DRC never ran" both produce the number 0 to anything that reads a count, and a
gate that cannot tell them apart reports clean for a run that never happened.
"""
import json
import pathlib
import subprocess
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _ppa import feasibility as F  # noqa: E402
from test_ppa_feasibility import (DIGEST, VIEW, VIEW_FF, candidate,  # noqa: E402
                                  clean_metrics, metric, policy, run)

CHECK = _PROGRAMS / "ppa_feasibility_check.py"


# --- M1 ---------------------------------------------------------------------
def test_M1_wns_improved_but_lvs_fails():
    """An improvement on one axis is not a licence on another.

    The candidate's setup slack is better than the reference by two orders of
    magnitude. Its layout does not match its netlist. It is not promotable, and
    no arrangement of the first fact changes the second.
    """
    baseline = clean_metrics()
    ms = clean_metrics()
    ms[0]["value"] = baseline[0]["value"] * 20      # WNS much improved
    ms[4]["value"] = "MISMATCH"                     # LVS fails
    r = F.promotion_verdict(candidate("m1", ms), policy())
    assert r.verdict == F.INFEASIBLE, r.codes
    assert not r.eligible_for_promotion
    lvs = [a for a in r.axes if a.name == "lvs"][0]
    assert lvs.status == F.AXIS_VIOLATED
    setup = [a for a in r.axes if a.name == "setup"][0]
    assert setup.status == F.AXIS_SATISFIED     # and the good axis is still good


def test_M1_via_the_cli_is_rc1_and_names_the_axis(tmp_path):
    ms = clean_metrics()
    ms[0]["value"] = 5.0
    ms[4]["value"] = "MISMATCH"
    r, doc = run(tmp_path, {"required_views": [VIEW],
                            "candidates": [candidate("m1", ms)]})
    assert r.returncode == F.RC_FAIL
    axes = {a["axis"]: a["status"] for a in doc["candidates"][0]["axes"]}
    assert axes["lvs"] == "VIOLATED"
    assert axes["setup"] == "SATISFIED"


# --- M4 ---------------------------------------------------------------------
def test_M4_a_zero_that_was_never_measured_is_not_a_clean_run():
    """`status: NOT_MEASURED` with `value: 0` is the exact shipped defect.

    The record LOOKS like evidence to anything that reads `value` without
    reading `status`. Per the interface freeze a NOT_MEASURED record carries a
    reason and not a value, so this record is malformed as well as unusable,
    and both facts are reported.
    """
    ms = clean_metrics()
    drc = [m for m in ms if m["metric"] == "physical.drc.violations"][0]
    drc["status"] = "NOT_MEASURED"
    drc["value"] = 0
    drc["reason"] = "the design-rule check did not run"
    r = F.promotion_verdict(candidate("m4", ms), policy())
    assert r.verdict == F.UNDETERMINED
    assert r.verdict != F.FEASIBLE
    assert any("FEAS_NOT_MEASURED_CARRIES_VALUE" in c for c in r.codes), r.codes


def test_M4_a_zero_with_no_artefact_behind_it_is_not_a_clean_run():
    """The other shape: MEASURED, value 0, and nothing to point at.

    A number with no source path and no artefact hash cannot be traced to a run
    that produced it, so crediting it is crediting an assertion.
    """
    ms = clean_metrics()
    drc = [m for m in ms if m["metric"] == "physical.drc.violations"][0]
    drc.pop("source")
    r = F.promotion_verdict(candidate("m4b", ms), policy())
    assert r.verdict == F.UNDETERMINED
    assert any("FEAS_NO_PROVENANCE" in c for c in r.codes), r.codes


def test_M4_an_absent_drc_record_is_undetermined_not_absent_violations():
    ms = [m for m in clean_metrics()
          if m["metric"] != "physical.drc.violations"]
    r = F.promotion_verdict(candidate("m4c", ms), policy())
    assert r.verdict == F.UNDETERMINED
    assert any("FEAS_METRIC_ABSENT" in c for c in r.codes)


def test_M4_via_the_cli_is_rc2_with_a_marker_not_rc0(tmp_path):
    ms = clean_metrics()
    drc = [m for m in ms if m["metric"] == "physical.drc.violations"][0]
    drc["status"] = "NOT_MEASURED"
    drc["value"] = 0
    r, doc = run(tmp_path, {"required_views": [VIEW],
                            "candidates": [candidate("m4", ms)]})
    assert r.returncode == F.RC_UNDETERMINED, r.stdout + r.stderr
    assert "[CANNOT CHECK]" in r.stderr
    assert doc["candidates"][0]["verdict"] == "UNDETERMINED"


# --- M5 ---------------------------------------------------------------------
def _violating(axis_metric="physical.drc.violations", value=3):
    ms = clean_metrics()
    [m for m in ms if m["metric"] == axis_metric][0]["value"] = value
    return ms


def test_M5_a_waiver_with_no_owner_does_not_apply_and_the_violation_stands():
    """A waiver is a NAMED person accepting a known risk.

    With nobody named there is no acceptance -- only a violation with a note
    attached. The note does not change the silicon.
    """
    w = [{"waiver_id": "W-1", "axis": "drc",
          "justification": "acceptable density marker", "owner": ""}]
    r = F.promotion_verdict(candidate("m5", _violating(), waivers=w), policy())
    assert r.verdict == F.INFEASIBLE
    drc = [a for a in r.axes if a.name == "drc"][0]
    assert drc.status == F.AXIS_VIOLATED
    assert drc.status != F.AXIS_WAIVED
    assert any("FEAS_WAIVER_NO_OWNER" in c for c in r.codes), r.codes
    assert r.waivers[0]["applied"] is False


def test_M5_the_positive_control_a_complete_waiver_does_apply():
    """Without this the test above proves only that waivers never work."""
    w = [{"waiver_id": "W-1", "axis": "drc", "owner": "block owner",
          "justification": "acceptable density marker",
          "evidence": ["phase3/stage3/drc.rpt"]}]
    r = F.promotion_verdict(candidate("m5ok", _violating(), waivers=w), policy())
    assert r.verdict == F.FEASIBLE
    drc = [a for a in r.axes if a.name == "drc"][0]
    assert drc.status == F.AXIS_WAIVED
    assert drc.waiver_ids == ("W-1",)
    assert r.waivers[0]["applied"] is True


def test_M5_a_waiver_may_not_rescue_an_axis_nobody_measured():
    """The dangerous cousin: waiving an UNKNOWN turns it into a pass.

    A waiver states that a known violation is acceptable. Applied to an axis
    that was never measured it manufactures knowledge, which is the single move
    this whole contract exists to make impossible.
    """
    ms = [m for m in clean_metrics()
          if m["metric"] != "physical.drc.violations"]
    w = [{"waiver_id": "W-2", "axis": "drc", "owner": "block owner",
          "justification": "we expect this to be clean"}]
    r = F.promotion_verdict(candidate("m5u", ms, waivers=w), policy())
    assert r.verdict == F.UNDETERMINED
    drc = [a for a in r.axes if a.name == "drc"][0]
    assert drc.status == F.AXIS_UNDETERMINED
    assert any("FEAS_WAIVER_ON_UNMEASURED" in c for c in r.codes), r.codes


def test_M5_a_waiver_without_a_justification_does_not_apply_either():
    w = [{"waiver_id": "W-3", "axis": "drc", "owner": "block owner"}]
    r = F.promotion_verdict(candidate("m5j", _violating(), waivers=w), policy())
    assert r.verdict == F.INFEASIBLE
    assert any("FEAS_WAIVER_NO_JUSTIFICATION" in c for c in r.codes)


def test_M5_no_waivers_mode_re_adjudicates_the_same_evidence(tmp_path):
    """The audit view: what would this candidate be without its waivers?"""
    w = [{"waiver_id": "W-1", "axis": "drc", "owner": "block owner",
          "justification": "acceptable density marker"}]
    doc = {"required_views": [VIEW],
           "candidates": [candidate("m5", _violating(), waivers=w)]}
    ok, _ = run(tmp_path, doc)
    assert ok.returncode == F.RC_PASS
    strict, payload = run(tmp_path, doc, "--no-waivers")
    assert strict.returncode == F.RC_FAIL
    assert payload["candidates"][0]["verdict"] == "INFEASIBLE"


# --- M6 ---------------------------------------------------------------------
def test_M6_an_incomplete_view_set_is_undetermined_not_feasible():
    """Two views required, one measured. A one-corner run is not signoff."""
    pol = policy(views=(VIEW, VIEW_FF))
    r = F.promotion_verdict(candidate("m6", clean_metrics()), pol)
    assert r.verdict == F.UNDETERMINED
    assert any("FEAS_INCOMPLETE_VIEW_SET" in c for c in r.codes), r.codes


def test_M6_the_positive_control_both_views_measured_is_feasible():
    pol = policy(views=(VIEW, VIEW_FF))
    ms = clean_metrics(VIEW) + clean_metrics(VIEW_FF)
    r = F.promotion_verdict(candidate("m6ok", ms), pol)
    assert r.verdict == F.FEASIBLE, r.codes


def test_M6_a_violation_in_one_view_survives_incomplete_coverage():
    """Partial coverage does not turn a measured violation into an unknown.

    More views could only ever find more violations, so the one already found
    is a fact and the candidate is INFEASIBLE, not UNDETERMINED.
    """
    pol = policy(views=(VIEW, VIEW_FF))
    ms = clean_metrics(VIEW)
    [m for m in ms if m["metric"] == "physical.drc.violations"][0]["value"] = 4
    r = F.promotion_verdict(candidate("m6v", ms), pol)
    assert r.verdict == F.INFEASIBLE


def test_M6_no_declared_view_set_is_undetermined_not_permission():
    """An undeclared view set is not `any view is fine`.

    With nothing declared, nothing here can distinguish a full multi-corner
    signoff from a single nominal run, so it declines to claim either.
    """
    r = F.promotion_verdict(candidate("m6n", clean_metrics()), policy(views=()))
    assert r.verdict == F.UNDETERMINED
    assert any("FEAS_VIEWS_NOT_DECLARED" in c for c in r.codes), r.codes


def test_M6_via_the_cli_is_rc2(tmp_path):
    r, doc = run(tmp_path, {"required_views": [VIEW, VIEW_FF],
                            "candidates": [candidate("m6", clean_metrics())]})
    assert r.returncode == F.RC_UNDETERMINED
    assert "[CANNOT CHECK]" in r.stderr


# --- the shape of the whole set --------------------------------------------
def test_all_four_mutations_at_once_never_produce_rc0(tmp_path):
    """The compound case, because a real run has more than one thing wrong."""
    m1 = clean_metrics(); m1[4]["value"] = "MISMATCH"
    m4 = clean_metrics()
    [m for m in m4 if m["metric"] == "physical.drc.violations"][0].update(
        {"status": "NOT_MEASURED", "value": 0})
    m5 = _violating()
    doc = {"required_views": [VIEW],
           "candidates": [candidate("m1", m1), candidate("m4", m4),
                          candidate("m5", m5, waivers=[
                              {"waiver_id": "W", "axis": "drc",
                               "justification": "x", "owner": ""}])]}
    r, payload = run(tmp_path, doc)
    assert r.returncode != F.RC_PASS
    verdicts = {c["candidate_id"]: c["verdict"] for c in payload["candidates"]}
    assert verdicts == {"m1": "INFEASIBLE", "m4": "UNDETERMINED",
                        "m5": "INFEASIBLE"}
    assert r.returncode == F.RC_UNDETERMINED     # 2 outranks 1, deliberately
