#!/usr/bin/env python3
"""AUDIT: does the design-for-ECO axis actually BITE, and where does it not?

WHY A SECOND FILE BESIDE `test_ppa_eco_readiness_axis.py`
========================================================
That file proves the axis is correct GIVEN a declaration. This one asks the
question a reader of a published search actually has: on the run shape the
campaign really used, does a candidate that deleted the design's spares come
back non-promotable?

The answer is measured here and it is TWO answers:

  * With the requirement declared, the axis bites everywhere -- through
    `promotion_verdict`, through `set_exit_code`, through the CLI's rc, and
    through the SEARCH BRIDGE, which is the path a PPA campaign actually takes
    and which nothing else in this tree covered.

  * With the contract SILENT -- no `eco_readiness`, no `delivery_path` -- the
    same records come back FEASIBLE, rc=0, and ELIGIBLE in the search manifest,
    with the ECO term published as NOT_APPLICABLE.

THE SILENT-CONTRACT ROW IS THE FINDING, NOT AN OVERSIGHT IN THIS FILE
=====================================================================
It is the landed design working as written: the requirement is DECLARED, never
assumed, and an absent declaration with no route resolved means "nobody asked".
What the audit adds is the measurement of what that costs in the lane the axis
was written for. Every trial contract in the shipped cross-layer campaign
(`ppa-crosslayer/records/trials/*/contract.json`) carries neither key, and
`ppa_search_run.py` has no `--project`, so a search cannot resolve the route on
its own the way `ppa_feasibility_check.py --project` can. On that shape the
axis is declared and inert.

`test_finding_*` pins that behaviour so it cannot change by accident. If the
route gap is closed, those tests must be updated DELIBERATELY -- which is the
point of pinning it rather than leaving it as a sentence in a report.
"""
import json
import pathlib
import subprocess
import sys
import types

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from _ppa import feasibility as F               # noqa: E402
from _ppa import search as S                    # noqa: E402
from _ppa import search_feasibility as SF       # noqa: E402
from test_ppa_eco_readiness_axis import (       # noqa: E402
    CHECK, DECL, VIEW, axis_of, cand, clean_nine, policy, run_cli, spares)

#: A candidate identical to a preserving one on every other axis, whose whole
#: spare population is gone. This is the published PnR-only winner's shape:
#: `--spare-density 0`, ten declared cells, none in the routed database.
def deleted_spares():
    return clean_nine() + spares(
        count=0, by_kind={k: 0 for k in DECL["min_spare_cells_by_kind"]},
        positions=0, tied=None)


def kept_spares():
    return clean_nine() + spares()


def silent_policy():
    """The contract shape the shipped campaign actually used: required views
    and nothing else -- no `eco_readiness`, no `delivery_path`."""
    return F.policy_from_document({"required_views": [dict(VIEW)]})


def chip_policy():
    """No declaration, but the route resolved to the tape-out-bound one."""
    return F.policy_from_document(
        {"required_views": [dict(VIEW)],
         "delivery_path": {"path": "CHIP",
                           "reason": "the flow routed this design to tapeout"}})


def _bridge(pol, metrics, cid="c"):
    return SF.feasibility_fn(pol)(
        types.SimpleNamespace(identity=cid, metrics=metrics))


# ---------------------------------------------------------------------------
# IT BITES -- with the requirement declared, on every path a promoter can take
# ---------------------------------------------------------------------------
def test_bite_a_deleted_population_is_not_promotable():
    r = F.promotion_verdict(cand("deleted", deleted_spares()), policy())
    assert r.verdict == F.INFEASIBLE, r.codes
    assert not r.eligible_for_promotion
    assert F.set_exit_code([r]) == F.RC_FAIL
    assert axis_of(r).status == F.AXIS_VIOLATED
    # not a general sulk: every other axis is still SATISFIED
    assert all(a.status == F.AXIS_SATISFIED
               for a in r.axes if a.name != F.ECO_AXIS)


def test_bite_one_deleted_spare_is_enough_there_is_no_tolerance():
    """Nine of ten. An axis with a tolerance is a threshold somebody argues
    about; the floor is the declaration's and 9 < 10."""
    nine = clean_nine() + spares(count=9)
    r = F.promotion_verdict(cand("nine-of-ten", nine), policy())
    assert r.verdict == F.INFEASIBLE, r.codes
    assert axis_of(r).status == F.AXIS_VIOLATED


def test_bite_a_better_number_on_every_other_axis_does_not_buy_it():
    """The trade the campaign actually made, as an assertion. This candidate
    is better than a preserving one everywhere a search can see, and it is
    still refused, because the gate reads no objective at all."""
    better = [dict(m) for m in deleted_spares()]
    for m in better:
        if m["metric"] == "timing.setup.wns_ns":
            m["value"] = 5.0                     # two orders of magnitude
    better.append({"schema": F.METRIC_SCHEMA, "metric": "area.design_report.um2",
                   "status": "MEASURED", "value": 6136.0, "unit": "um^2",
                   "scope": dict(VIEW),
                   "source": {"path": "a.rpt", "sha256": "sha256:" + "0" * 64,
                              "tool": "t", "parser": "p"}})
    r = F.promotion_verdict(cand("area-winner", better), policy())
    assert r.verdict == F.INFEASIBLE, r.codes
    assert not r.eligible_for_promotion


def test_bite_the_cli_returns_rc1_and_names_the_axis(tmp_path):
    r, doc = run_cli(tmp_path, {"required_views": [VIEW], "eco_readiness": DECL,
                                "candidates": [cand("deleted", deleted_spares())]})
    assert r.returncode == F.RC_FAIL, r.stdout + r.stderr
    axes = {a["axis"]: a["status"] for a in doc["candidates"][0]["axes"]}
    assert axes[F.ECO_AXIS] == "VIOLATED"


def test_bite_reaches_the_search_bridge_which_is_the_campaign_s_own_path():
    """The arm nothing else covered. A PPA campaign never calls the CLI: it
    calls `_ppa/search_feasibility.feasibility_fn`, whose verdict is what the
    published manifest carries and what the frontier admits."""
    v = _bridge(policy(), deleted_spares(), "deleted")
    assert v.verdict == S.FEAS_INELIGIBLE
    assert v.terms[F.ECO_AXIS] == "FAIL"
    assert SF.TERM_MAP[F.AXIS_VIOLATED] == "FAIL"


def test_bite_an_ineligible_candidate_cannot_reach_the_frontier():
    """`eligible_for_promotion` is the ONE predicate a promoter may read, and
    it is false here. A frontier built from eligible candidates therefore
    cannot contain this one."""
    r = F.promotion_verdict(cand("deleted", deleted_spares()), policy())
    assert [x for x in (r,) if x.eligible_for_promotion] == []


# ---------------------------------------------------------------------------
# THE THREE-WAY VERDICT, MEASURED ROW BY ROW
# ---------------------------------------------------------------------------
def test_three_way_preserved_is_rc0():
    r = F.promotion_verdict(cand("keeps", kept_spares()), policy())
    assert r.verdict == F.FEASIBLE, r.codes
    assert F.set_exit_code([r]) == F.RC_PASS
    assert axis_of(r).status == F.AXIS_SATISFIED


def test_three_way_deleted_is_rc1():
    r = F.promotion_verdict(cand("deleted", deleted_spares()), policy())
    assert F.set_exit_code([r]) == F.RC_FAIL


def test_three_way_declared_but_never_measured_is_rc2_not_rc0_and_not_rc1():
    """The row that keeps the axis honest in both directions: a requirement
    with no evidence is UNKNOWN, not "0 spares, therefore fails" and not a
    pass. Convicting a run nobody looked at is as wrong as acquitting one."""
    r = F.promotion_verdict(cand("silent-records", clean_nine()), policy())
    assert r.verdict == F.UNDETERMINED, r.codes
    assert F.set_exit_code([r]) == F.RC_UNDETERMINED
    assert F.set_exit_code([r]) not in (F.RC_PASS, F.RC_FAIL)


def test_three_way_no_declaration_on_the_chip_path_is_rc2():
    """A tape-out-bound design that declared no requirement is [CANNOT CHECK].
    This is the arm that makes "none declared -> rc=2" true, and it is true
    only once the route is known."""
    r = F.promotion_verdict(cand("silent-chip", clean_nine()), chip_policy())
    assert r.verdict == F.UNDETERMINED, r.codes
    assert F.set_exit_code([r]) == F.RC_UNDETERMINED
    assert axis_of(r).applicability["state"] == F.ECO_NOT_DECLARED_ON_CHIP_PATH


# ---------------------------------------------------------------------------
# THE FINDING -- the shape the shipped campaign used, and what it costs
# ---------------------------------------------------------------------------
def test_finding_a_silent_contract_makes_the_deletion_promotable():
    """MEASURED, and the reason this file exists.

    No `eco_readiness`, no `delivery_path` -- the contract shape every trial in
    `ppa-crosslayer/records/trials/*/contract.json` carries. The candidate that
    deleted all ten spares is FEASIBLE, rc=0 and promotable, and the axis row
    says NOT_APPLICABLE.

    This is the landed rule working as written (the requirement is declared,
    never assumed) and it is also the gap: on this shape the axis is declared
    and inert. Pinned, so closing the gap is a deliberate act.
    """
    r = F.promotion_verdict(cand("deleted", deleted_spares()), silent_policy())
    assert r.verdict == F.FEASIBLE, r.codes
    assert r.eligible_for_promotion
    assert F.set_exit_code([r]) == F.RC_PASS
    a = axis_of(r)
    assert a.status == F.AXIS_NOT_APPLICABLE
    assert a.applicability["state"] == F.ECO_NOT_DECLARED


def test_finding_the_search_manifest_publishes_it_as_eligible():
    """Same shape through the bridge a campaign really uses. `NOT_APPLICABLE`
    is at least printed rather than absent, so the manifest does not claim the
    axis passed -- but the candidate is ELIGIBLE and can win."""
    v = _bridge(silent_policy(), deleted_spares(), "deleted")
    assert v.verdict == S.FEAS_ELIGIBLE
    assert v.terms[F.ECO_AXIS] == "NOT_APPLICABLE"
    assert v.terms[F.ECO_AXIS] != "PASS"


def test_finding_one_line_in_the_contract_is_the_whole_difference():
    """The candidate's records are byte-identical in both arms. What flips the
    verdict is the CONTRACT, which is exactly where the landed design put the
    decision -- and exactly why a campaign that does not write that line gets
    no gate."""
    records = deleted_spares()
    silent = F.promotion_verdict(cand("d", records), silent_policy())
    declared = F.promotion_verdict(cand("d", records), policy())
    assert silent.verdict == F.FEASIBLE
    assert declared.verdict == F.INFEASIBLE
    assert silent.eligible_for_promotion and not declared.eligible_for_promotion


def test_finding_the_route_alone_also_flips_it_without_any_declaration():
    """The other half of the fix that is available today: no declaration at
    all, but a resolved CHIP route, already turns rc=0 into rc=2. So a campaign
    does not have to author a spare requirement to stop publishing a silent
    pass -- it has to state which route the design is on."""
    silent = F.promotion_verdict(cand("s", clean_nine()), silent_policy())
    routed = F.promotion_verdict(cand("s", clean_nine()), chip_policy())
    assert F.set_exit_code([silent]) == F.RC_PASS
    assert F.set_exit_code([routed]) == F.RC_UNDETERMINED


def test_finding_the_search_runner_cannot_resolve_the_route_itself():
    """`ppa_feasibility_check.py` takes `--project` and lets the flow's own
    router decide. `ppa_search_run.py` does not, so a campaign's only lever is
    the policy document. Measured against the CLIs' own help text rather than
    asserted, so it stops being true the moment the flag is added."""
    feas_help = subprocess.run(
        [sys.executable, str(CHECK), "--help"],
        capture_output=True, text=True).stdout
    search_help = subprocess.run(
        [sys.executable, str(_PROGRAMS / "ppa_search_run.py"), "--help"],
        capture_output=True, text=True).stdout
    assert "--project" in feas_help
    assert "--project" not in search_help, (
        "the search runner has grown a --project flag: the route gap this "
        "file measures may be closed, and the test_finding_* rows above "
        "should be re-measured rather than trusted")


def test_finding_the_shipped_campaign_contracts_declare_neither_key():
    """The denominator, read from the shipped records rather than remembered.

    Skipped, not silently passed, when the campaign tree is not present -- an
    empty scan is NOT OBSERVED and must not read as "every contract is fine".
    """
    import pytest
    trials = (_PROGRAMS.parents[3] / "ppa-crosslayer" / "records" / "trials")
    if not trials.is_dir():
        pytest.skip(f"the cross-layer campaign records are not in this tree "
                    f"({trials}); this row was NOT OBSERVED, not satisfied")
    seen = declares = routes = 0
    for contract in sorted(trials.glob("*/contract.json")):
        try:
            doc = json.loads(contract.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        seen += 1
        declares += int("eco_readiness" in doc)
        routes += int("delivery_path" in doc)
    assert seen > 0, "no contract.json parsed; the denominator is empty"
    assert (declares, routes) == (0, 0), (
        f"{declares} of {seen} campaign contracts declare eco_readiness and "
        f"{routes} state a delivery path; the finding in this file's header "
        f"was measured when both were zero and must be re-measured")


# ---------------------------------------------------------------------------
# THE NEGATIVE CONTROL -- the refusal is measured to come from the rule
# ---------------------------------------------------------------------------
#: THE arm that refuses. `KIND_LIMIT_MIN` is where a declared floor becomes a
#: verdict, and this line is the whole of "fewer than the design requires is a
#: violation". Everything else in the axis routes evidence towards it.
_REJECTION = "        ok = value >= lim[\"min\"]"
_ACCEPTANCE = "        ok = True"

#: A declaration asking for ONE thing, so the control isolates ONE rule. With
#: the kind mix and the tie-off in it, removing the count floor leaves the axis
#: refusing for a different reason and the control would measure nothing.
DECL_COUNT_ONLY = {"required": True, "min_spare_cells": 10}


def _module_with(arm, replacement):
    """Execute the shipped module source with one arm replaced.

    Not a monkeypatch: the rule is changed in the SOURCE, so what is measured
    is that rule's contribution and not a stub's. Registered in `sys.modules`
    because `dataclasses` resolves annotations through it, and removed again so
    nothing else can import the loosened gate by accident.
    """
    path = pathlib.Path(F.__file__)
    src = path.read_text(encoding="utf-8")
    assert src.count(arm) == 1, (
        f"the control is pinned to this arm's exact text and found "
        f"{src.count(arm)} of it; a control that changes nothing proves "
        f"nothing:\n{arm}")
    name = "_feasibility_with_the_floor_comparison_removed"
    mod = types.ModuleType(name)
    mod.__file__ = str(path)
    sys.modules[name] = mod
    try:
        exec(compile(src.replace(arm, replacement), str(path), "exec"),
             mod.__dict__)
    finally:
        sys.modules.pop(name, None)
    return mod


def _count_only(n):
    """Clean on every other axis; the spare COUNT is the only ECO evidence."""
    return clean_nine() + [spares(count=n)[0]]


def _count_only_policy(mod=F):
    return mod.policy_from_document(
        {"required_views": [dict(VIEW)],
         "eco_readiness": dict(DECL_COUNT_ONLY)})


def test_negative_control_the_shipped_floor_comparison_is_what_refuses():
    """Break the rejection; the SAME candidate becomes promotable.

    Without this control every assertion above could be passing because of
    something else in the pipeline. With it, the refusal is measured to come
    from the rule, and removing the rule is measured to remove the refusal.

    The control also fails if the arm is DELETED rather than neutered: then
    `_module_with` finds nothing to replace and its own assertion fires.
    """
    zero = _count_only(0)
    shipped = F.promotion_verdict(cand("deleted", zero), _count_only_policy())
    assert shipped.verdict == F.INFEASIBLE, shipped.codes
    assert not shipped.eligible_for_promotion
    assert axis_of(shipped).status == F.AXIS_VIOLATED

    loosened = _module_with(_REJECTION, _ACCEPTANCE)
    without = loosened.promotion_verdict(
        {"candidate_id": "deleted", "metrics": zero},
        _count_only_policy(loosened))
    assert without.verdict == loosened.FEASIBLE, (
        "with the floor comparison removed the candidate is STILL refused, so "
        "the refusal measured above is not coming from that rule and this "
        "control is not testing what it says it is")
    assert without.eligible_for_promotion
    assert shipped.verdict != without.verdict


def test_negative_control_the_positive_arm_is_unchanged_by_the_break():
    """A control that flips BOTH arms would prove only that the module broke.
    A preserving candidate is FEASIBLE before and after, so what the break
    moved is exactly the refusal."""
    ten = _count_only(10)
    assert F.promotion_verdict(cand("keeps", ten),
                               _count_only_policy()).verdict == F.FEASIBLE
    loosened = _module_with(_REJECTION, _ACCEPTANCE)
    assert loosened.promotion_verdict(
        {"candidate_id": "keeps", "metrics": ten},
        _count_only_policy(loosened)).verdict == loosened.FEASIBLE
