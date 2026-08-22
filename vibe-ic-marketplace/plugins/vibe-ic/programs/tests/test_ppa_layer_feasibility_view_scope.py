#!/usr/bin/env python3
"""E2E finding F-11: `required_views` is global, so one view poisons every axis.

THE SHAPE
=========
`FeasibilityPolicy.required_views` is a single tuple, and `_evaluate_proof`
applies it to EVERY proof of EVERY axis:

    for view in policy.required_views:
        hits = [r for r in usable if _covers(r["scope"], view)]
        if not hits:
            uncovered.append(view)          -> FEAS_INCOMPLETE_VIEW_SET

There are nine axes: setup, hold, drv, drc, lvs, antenna, ir, em, equivalence.
Six of them are not per-corner facts at all. A DRC run has no `check=setup`
and no `process=ss`; there is one layout and one deck. So the moment a contract
declares the views a real sign-off declares -- the STA corners -- DRC, LVS,
antenna, IR, EM and equivalence all report views they can never carry.

And the two timing axes poison each other: `required_views` contains the hold
view, which a setup record can never cover, and vice versa.

MEASURED ON `e36d81c0a` (v1.11.33), by this file
================================================
A candidate that is CLEAN on all nine axes and MEASURED across both declared
STA corners:

    required_views = ()                          UNDETERMINED   0/9 satisfied
    required_views = one stage-only view         FEASIBLE       9/9 satisfied
    required_views = the two STA corner views    UNDETERMINED   0/9 satisfied

The hard promotion gate can return FEASIBLE only when `required_views` holds a
single view so weak that every axis satisfies it. Declare the real thing and
the gate cannot pass anything -- which is a gate that cannot be satisfied, the
mirror image of a gate that cannot fail, and just as useless.

WHY NO PER-MODULE TEST SAW IT
=============================
`test_ppa_feasibility.py` and `test_ppa_feasibility_mutations.py` exercise ONE
axis at a time with `required_views` matched to that axis. Every one passes.
The defect is a property of the CROSS PRODUCT of axes and views, and a suite
that never puts a timing view and a DRC record in the same policy cannot see
it. That is F-11's shape and it is why it took an end-to-end run.

WHAT A FIX LOOKS LIKE (not asserted here -- it is the feasibility lane's call)
=============================================================================
Views are per-axis, or per-proof, or a view carries which axes it constrains.
Any of those makes the arms below green. This file does not pick one; it fails
while a clean, fully-measured candidate cannot be adjudicated.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

_TESTS = pathlib.Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
sys.path.insert(0, str(_PROGRAMS))

from _ppa import feasibility as F   # noqa: E402

_PIN = pytest.mark.xfail(
    strict=True,
    reason="F-11: `required_views` is one global tuple applied to all nine "
           "axes, so a per-corner view set makes every non-corner axis report "
           "FEAS_INCOMPLETE_VIEW_SET. `_ppa/feasibility.py` belongs to the "
           "feasibility-axes lane (PPA_INTERFACES §6); handed to the lander in "
           "RESULT.md. Strict: goes red the moment the fix lands.")

SRC = {"path": "artefact.rpt", "sha256": "sha256:" + "ab" * 32,
       "tool": "opensta", "parser": "probe.py",
       "parser_sha256": "sha256:" + "cd" * 32}
STAGE = "post_route_extracted"

# The two views a real multi-corner sign-off declares.
SETUP_VIEW = {"check": "setup", "process": "ss"}
HOLD_VIEW = {"check": "hold", "process": "ff"}


def _rec(metric, value, unit, **scope):
    return {"schema": "vibeic.ppa.metric.v1", "metric": metric,
            "status": "MEASURED", "value": value, "unit": unit,
            "scope": dict(scope, stage=STAGE), "source": dict(SRC)}


def _a_clean_fully_measured_candidate():
    """Clean on every axis. The timing records carry the two declared corners;
    the physical ones carry the stage, because a layout has no corner."""
    return {"candidate_id": "clean", "metrics": [
        _rec("timing.setup.wns_ns", 0.10, "ns", check="setup",
             process="ss", clock="clk"),
        _rec("timing.hold.wns_ns", 0.05, "ns", check="hold",
             process="ff", clock="clk"),
        _rec("timing.drv.violations", 0, "count"),
        _rec("physical.drc.violations", 0, "count"),
        _rec("physical.lvs.violations", 0, "count"),
        _rec("physical.antenna.violations", 0, "count"),
        _rec("power.ir.violations", 0, "count"),
        _rec("reliability.em.violations", 0, "count"),
        _rec("equivalence.verdict", "PROVEN", "verdict"),
    ]}


def test_the_axis_table_is_the_one_this_file_reasons_about():
    """The denominator. If an axis is added or removed the reasoning above is
    stale, and this says so instead of quietly testing a smaller cross
    product.

    `eco_readiness` is the tenth and is the one axis whose APPLICABILITY the
    design declares; this file's fixtures declare no ECO requirement, so it is
    NOT_APPLICABLE throughout and the view-scope reasoning above -- which is
    about corner coverage -- does not reach it."""
    names = [a.name for a in F.DEFAULT_AXES]
    assert names == ["setup", "hold", "drv", "drc", "lvs", "antenna",
                     "ir", "em", "equivalence", "eco_readiness"], names


def test_a_single_weak_view_is_the_only_way_the_gate_passes_today():
    """The control, and the reason the finding is not "the candidate is bad".

    With one stage-only view -- which every axis satisfies -- this exact
    candidate is FEASIBLE on 9 of 9 axes. So nothing is wrong with the
    records; what changes the verdict is only which views were declared.

    This PASSES today and must keep passing after the fix.
    """
    res = F.promotion_verdict(
        _a_clean_fully_measured_candidate(),
        F.FeasibilityPolicy(required_views=({"stage": STAGE},)))
    satisfied = [a.name for a in res.axes if a.status == F.AXIS_SATISFIED]
    assert res.verdict == F.FEASIBLE, (res.verdict, res.codes)
    assert len(satisfied) == 9, satisfied


@_PIN
def test_declaring_the_real_corner_views_still_adjudicates(tmp_path=None):
    """F-11. The same clean candidate, with the views a sign-off declares."""
    res = F.promotion_verdict(
        _a_clean_fully_measured_candidate(),
        F.FeasibilityPolicy(required_views=(SETUP_VIEW, HOLD_VIEW)))
    poisoned = [(a.name, tuple(a.codes)) for a in res.axes
                if a.status == F.AXIS_UNDETERMINED]
    assert res.verdict == F.FEASIBLE, (
        f"F-11: a candidate clean on all nine axes and measured across both "
        f"declared corners adjudicates {res.verdict}. "
        f"{len(poisoned)} of {len(res.axes)} axes are UNDETERMINED: "
        f"{poisoned}")


@_PIN
def test_a_non_corner_axis_is_not_asked_for_a_corner():
    """The mechanism, isolated: DRC alone, with an STA view declared.

    A layout has one deck and no process corner. Requiring `process=ss` of the
    DRC axis asks for a fact that cannot exist, and the axis is UNDETERMINED
    for a reason that says nothing about the design.
    """
    res = F.promotion_verdict(
        {"candidate_id": "drc-only",
         "metrics": [_rec("physical.drc.violations", 0, "count")]},
        F.FeasibilityPolicy(axes=(F.DEFAULT_AXES[3],),   # drc
                            required_views=(SETUP_VIEW,)))
    drc = res.axes[0]
    assert F.C_INCOMPLETE_VIEW_SET not in drc.codes, (
        f"F-11: the DRC axis reports {F.C_INCOMPLETE_VIEW_SET} because an STA "
        f"corner view was declared globally. codes={tuple(drc.codes)}")


@_PIN
def test_the_two_timing_axes_do_not_poison_each_other():
    """Even inside timing, one global tuple is wrong: a setup record can never
    cover the hold view, so declaring both makes both axes incomplete."""
    res = F.promotion_verdict(
        {"candidate_id": "timing-only", "metrics": [
            _rec("timing.setup.wns_ns", 0.10, "ns", check="setup",
                 process="ss", clock="clk"),
            _rec("timing.hold.wns_ns", 0.05, "ns", check="hold",
                 process="ff", clock="clk")]},
        F.FeasibilityPolicy(axes=F.DEFAULT_AXES[:2],
                            required_views=(SETUP_VIEW, HOLD_VIEW)))
    bad = [(a.name, tuple(a.codes)) for a in res.axes
           if F.C_INCOMPLETE_VIEW_SET in a.codes]
    assert not bad, (
        f"F-11: setup and hold are each measured at their own declared corner, "
        f"yet {len(bad)} axis/axes report an incomplete view set because the "
        f"other axis's view is in the same global tuple: {bad}")


def test_an_undeclared_view_set_is_undetermined_not_satisfied():
    """The neighbouring rule that IS right, asserted so a fix for F-11 cannot
    quietly take it out.

    Empty `required_views` must stay UNDETERMINED. "Not declared" is not
    "anything measured is enough" -- that would credit a one-corner run as
    sign-off, which is the defect `required_views` was added to prevent.
    """
    res = F.promotion_verdict(_a_clean_fully_measured_candidate(),
                              F.FeasibilityPolicy(required_views=()))
    assert res.verdict == F.UNDETERMINED
    assert any(F.C_VIEWS_NOT_DECLARED in a.codes for a in res.axes), (
        "an undeclared view set no longer reports FEAS_VIEWS_NOT_DECLARED")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
