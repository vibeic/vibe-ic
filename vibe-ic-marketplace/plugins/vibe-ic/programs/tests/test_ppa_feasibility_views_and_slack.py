#!/usr/bin/env python3
"""Per-axis required views (F-11) and the setup/hold slack proofs (F-15).

Both changes make the gate able to reach a verdict it structurally could not
reach before, and BOTH are only defensible if they refuse exactly what they
refused before. Most of what is here is that second half.
"""
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _ppa import feasibility as F  # noqa: E402

DIGEST = "sha256:" + "0" * 64
SS = {"stage": "post_route_extracted", "process": "ss"}
FF = {"stage": "post_route_extracted", "process": "ff"}
GDS = {"stage": "signed_off_gds"}


def rec(metric, value, unit="", scope=None, status="MEASURED", reason=None):
    r = {"schema": F.METRIC_SCHEMA, "metric": metric, "status": status,
         "unit": unit, "scope": dict(scope or SS),
         "source": {"path": "reports/x.json", "sha256": DIGEST, "tool": "t"}}
    if status == "MEASURED":
        r["value"] = value
    if reason:
        r["reason"] = reason
    return r


def axis_of(result, name):
    return next(a for a in result.axes if a.name == name)


def adjudicate(records, doc):
    return F.promotion_verdict({"candidate_id": "c", "metrics": records},
                               F.policy_from_document(doc))


# ==========================================================================
# F-11 -- per-axis required views
# ==========================================================================
def test_a_corner_independent_axis_no_longer_needs_the_timing_corners():
    """THE DEFECT. One global `required_views` was applied to all nine axes, so
    a contract that declared the corners it signs timing off at ALSO demanded
    those corners of DRC -- which has no process corner. Either DRC was
    permanently uncovered, or its producer had to emit one measurement N times
    under fabricated scopes."""
    records = [rec("physical.drc.violations", 0, "count", GDS)]
    poisoned = adjudicate(records, {"required_views": [SS, FF]})
    assert axis_of(poisoned, "drc").status == F.AXIS_UNDETERMINED
    assert F.C_INCOMPLETE_VIEW_SET in axis_of(poisoned, "drc").codes

    fixed = adjudicate(records, {"required_views": [SS, FF],
                                 "required_views_by_axis": {"drc": [GDS]}})
    assert axis_of(fixed, "drc").status == F.AXIS_SATISFIED


def test_an_unmeasured_required_view_still_sinks_the_axis():
    """The invariant this change was NOT allowed to weaken. A corner nobody ran
    is a corner nobody ran."""
    records = [rec("timing.setup.wns_ns", 0.4, "ns", SS)]
    r = adjudicate(records, {"required_views_by_axis": {
        "setup": [SS, FF]}})
    assert axis_of(r, "setup").status == F.AXIS_UNDETERMINED
    assert F.C_INCOMPLETE_VIEW_SET in axis_of(r, "setup").codes


def test_an_axis_named_with_an_empty_view_list_is_not_thereby_exempt():
    """There is no spelling of this field that means 'whatever was measured is
    enough'. That would be the knob the gate is not allowed to have."""
    records = [rec("physical.drc.violations", 0, "count", GDS)]
    r = adjudicate(records, {"required_views": [GDS],
                             "required_views_by_axis": {"drc": []}})
    assert axis_of(r, "drc").status == F.AXIS_UNDETERMINED
    assert F.C_VIEWS_NOT_DECLARED in axis_of(r, "drc").codes


def test_an_axis_the_map_does_not_name_falls_back_to_the_global_list():
    """A contract written before this field existed must adjudicate the same."""
    records = [rec("physical.drc.violations", 0, "count", GDS)]
    with_map = adjudicate(records, {"required_views": [GDS],
                                    "required_views_by_axis": {"lvs": [SS]}})
    without = adjudicate(records, {"required_views": [GDS]})
    assert axis_of(with_map, "drc").status == axis_of(without, "drc").status
    assert axis_of(with_map, "drc").status == F.AXIS_SATISFIED
    assert F.views_for("drc", F.policy_from_document(
        {"required_views": [GDS], "required_views_by_axis": {"lvs": [SS]}})) \
        == (GDS,)


def test_a_key_naming_no_known_axis_is_dropped_and_not_honoured():
    """`{"drc ": [...]}` must not become a policy whose effect nobody can find."""
    p = F.policy_from_document({"required_views": [GDS],
                                "required_views_by_axis": {"drc ": [SS],
                                                           "nonsense": [SS]}})
    assert dict(p.required_views_by_axis) == {}
    assert F.views_for("drc", p) == (GDS,)


def test_a_measured_violation_still_stands_when_coverage_is_partial():
    """More views cannot unmake a fact about the design."""
    r = adjudicate([rec("physical.drc.violations", 12, "count", GDS)],
                   {"required_views_by_axis": {"drc": [GDS, SS]}})
    assert axis_of(r, "drc").status == F.AXIS_VIOLATED


# --- the record must SAY which views were measured -------------------------
def test_the_coverage_names_every_declared_view_even_when_satisfied():
    """A reader checking whether the view set was the right one should not have
    to make the axis fail first."""
    r = adjudicate([rec("physical.drc.violations", 0, "count", GDS)],
                   {"required_views_by_axis": {"drc": [GDS]}})
    cov = axis_of(r, "drc").coverage
    assert [c["state"] for c in cov] == [F.COV_MEASURED]
    assert cov[0]["view"] == GDS
    assert cov[0]["metric"] == "physical.drc.violations"


def test_the_coverage_separates_a_view_nobody_ran_from_one_that_could_not_be_read():
    """The two causes of UNDETERMINED that used to be one sentence.

    'The ff corner was never analysed' and 'the ff corner was analysed and the
    report carried no wns line' need different fixes, and before this the
    verdict named neither view."""
    records = [
        rec("timing.setup.wns_ns", 0.4, "ns", SS),
        rec("timing.setup.wns_ns", None, "ns", FF, status="NOT_MEASURED",
            reason="the artefact carries no wns line for this view"),
    ]
    NEVER = {"stage": "post_route_extracted", "process": "tt"}
    r = adjudicate(records, {"required_views_by_axis": {
        "setup": [SS, FF, NEVER]}})
    cov = {c["view"]["process"]: c for c in axis_of(r, "setup").coverage
           if c.get("view") and c["metric"] == "timing.setup.wns_ns"}
    assert cov["ss"]["state"] == F.COV_MEASURED
    assert cov["ff"]["state"] == F.COV_NOT_MEASURED
    assert "no wns line" in cov["ff"]["reason"]
    assert cov["ff"]["sources"] == ["reports/x.json"]
    assert cov["tt"]["state"] == F.COV_NO_RECORD


def test_a_waived_axis_keeps_the_coverage_it_was_waived_against():
    """A waiver is somebody signing for a violation, and the reader is entitled
    to the same per-view evidence they signed against."""
    cand = {"candidate_id": "c",
            "metrics": [rec("physical.drc.violations", 3, "count", GDS)],
            "waivers": [{"waiver_id": "w1", "axis": "drc", "owner": "someone",
                         "justification": "known and accepted"}]}
    r = F.promotion_verdict(cand, F.policy_from_document(
        {"required_views_by_axis": {"drc": [GDS]}}))
    a = axis_of(r, "drc")
    assert a.status == F.AXIS_WAIVED
    assert len(a.coverage) == 1 and a.coverage[0]["state"] == F.COV_MEASURED


# ==========================================================================
# F-15 -- the setup/hold slack proofs
# ==========================================================================
@pytest.mark.parametrize("slack", [-5.0, -0.001, 0.0, 0.001, 5.0, 1e-12])
@pytest.mark.parametrize("check", ["setup", "hold"])
def test_worst_slack_and_wns_are_the_same_predicate(check, slack):
    """MEASURED, not asserted in a comment.

    OpenSTA's wns is `min(0, worst_slack)`, so `wns >= 0` and
    `worst_slack >= 0` decide identically. That is why the worst-slack group is
    not a relaxation: it admits no candidate the wns proof would refuse. This
    sweeps both signs and the boundary and requires the two verdicts to agree.
    """
    wns = min(0.0, slack)
    doc = {"required_views_by_axis": {check: [SS]}}
    by_wns = adjudicate([rec(f"timing.{check}.wns_ns", wns, "ns", SS)], doc)
    by_ws = adjudicate([rec(f"timing.{check}.worst_slack_ns", slack, "ns", SS)],
                       doc)
    assert axis_of(by_wns, check).status == axis_of(by_ws, check).status
    assert axis_of(by_ws, check).status == (
        F.AXIS_SATISFIED if slack >= 0 else F.AXIS_VIOLATED)


@pytest.mark.parametrize("check", ["setup", "hold"])
def test_a_negative_worst_slack_still_violates(check):
    """The thing a widening would have broken."""
    r = adjudicate([rec(f"timing.{check}.worst_slack_ns", -0.31, "ns", SS)],
                   {"required_views_by_axis": {check: [SS]}})
    assert axis_of(r, check).status == F.AXIS_VIOLATED
    assert r.verdict == F.INFEASIBLE


@pytest.mark.parametrize("check", ["setup", "hold"])
def test_a_no_paths_view_is_not_rescued_by_the_worst_slack_group(check):
    """OpenSTA's worst_slack starts at infinity and takes the min over analysed
    paths, so an empty path set leaves it at INF. `_ppa/timing.py` emits that as
    NOT_MEASURED with the no-paths reason, and this axis refuses it like any
    other NOT_MEASURED record -- the sentinel is handled where it is read."""
    r = adjudicate([rec(f"timing.{check}.worst_slack_ns", None, "ns", SS,
                        status="NOT_MEASURED",
                        reason="no_paths_analysed_in_view")],
                   {"required_views_by_axis": {check: [SS]}})
    assert axis_of(r, check).status == F.AXIS_UNDETERMINED
    assert r.verdict == F.UNDETERMINED


@pytest.mark.parametrize("check", ["setup", "hold"])
def test_a_violation_in_one_group_is_not_outvoted_by_another(check):
    """Two artefacts that disagree is not permission to believe the flattering
    one -- the axis says so and the new group must not change it."""
    r = adjudicate([rec(f"timing.{check}.wns_ns", 0.0, "ns", SS),
                    rec(f"timing.{check}.worst_slack_ns", -1.2, "ns", SS)],
                   {"required_views_by_axis": {check: [SS]}})
    assert axis_of(r, check).status == F.AXIS_VIOLATED


def test_the_hold_axis_is_provable_from_a_report_that_prints_only_worst_slack():
    """The end-to-end defect. Across all six STA artefacts of a real sign-off
    run `timing.hold.wns_ns` was NOT_MEASURED on every view, because the two
    multi-corner sign-off emitters never called `report_wns` at all. The hold
    axis was unprovable for every design on every run."""
    records = [
        rec("timing.hold.wns_ns", None, "ns", FF, status="NOT_MEASURED",
            reason="the artefact carries no wns line for this view"),
        rec("timing.hold.worst_slack_ns", 0.54, "ns", FF),
    ]
    r = adjudicate(records, {"required_views_by_axis": {"hold": [FF]}})
    assert axis_of(r, "hold").status == F.AXIS_SATISFIED


# --- the emitter half ------------------------------------------------------
def test_both_multi_corner_signoff_stanzas_ask_the_tool_for_the_wns():
    """`_ppa/timing.py` will not derive the wns from the worst slack, and it is
    right not to. The fix therefore belongs in the emitter: it has to ask."""
    import phase3_one_shot_runner as R
    src = pathlib.Path(R.__file__).read_text()
    assert src.count("_report_wns_tcl(rpt_c, flag)") == 2, (
        "a multi-corner sign-off stanza stopped asking for the wns")
    for flag in ("-max", "-min"):
        tcl = R._report_wns_tcl("/r/out.rpt", flag)
        assert f"report_wns {flag} >> /r/out.rpt" in tcl
        # Guarded: a build that rejects the flag must not abort a sign-off
        # script that has already written its setup half.
        assert tcl.startswith("if {[catch {")
        # ...and the failure is WRITTEN, so an absent wns line stays visible as
        # a refusal rather than becoming a silent skip.
        assert "SIGNOFF_WNS_UNAVAILABLE" in tcl
        assert R._SIGNOFF_WNS_MARKER in tcl
