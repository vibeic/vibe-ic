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

WHICH COMMITS ON THIS BRANCH CHANGE SHIPPED BEHAVIOUR
=====================================================
Three, and a reviewer should scrutinise exactly these:

    4ca6b6eaf  ppa_search_run.py gains --project
    9f693090c  _ppa/search.py: audit_manifest refuses eligibility on an
               undeclared ECO stance
    72f1543b4  ppa_search_run.py: the build warning names its consequence

Everything else adds tests or files backlog items.

CORRECTION TO 9f693090c's OWN MESSAGE, which cannot be edited once pushed: it
says "THIS IS THE ONE COMMIT ON THIS BRANCH THAT CHANGES CALLER-VISIBLE
BEHAVIOUR" and "it is last". Both were true when written and neither is now --
4ca6b6eaf preceded it and 72f1543b4 followed it. It IS still self-contained and
revertable on its own; it is not the only one, and it is not last.
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
    CHECK, DECL, VIEW, axis_of, cand, clean_nine, policy, rec, run_cli, spares)

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


def test_all_three_ppa_clis_can_resolve_the_route(tmp_path):
    """The gap this file was written to measure, closed.

    `ppa_feasibility_check.py` and `ppa_pnr_search_space.py` already took
    `--project` and let the flow's own router decide. `ppa_search_run.py` did
    not, so a campaign's only lever was whatever the policy document happened
    to say -- and the shipped campaign's said nothing. Measured against each
    CLI's own help text rather than asserted, so it goes red if any of them
    loses the flag again.
    """
    progs = ("ppa_feasibility_check.py", "ppa_pnr_search_space.py",
             "ppa_search_run.py")
    # THE DENOMINATOR, AGAINST THE POPULATION AND NOT AGAINST ITSELF.
    # This row used to read `len(progs) == 3`, which compares a literal to its
    # own size: it passes for free, on every tree, forever, and "all three
    # CLIs" was never checked against how many there are. The population is
    # DISCOVERED instead -- every `ppa_*` CLI whose source reaches the flow's
    # own delivery-path router, which is what "can resolve the route" means --
    # and the comparison is set equality in both directions, so a fourth CLI
    # joining the lane and a name dropped from this row are each red.
    routed = {q.name for q in _PROGRAMS.glob("ppa_*.py")
              if "delivery_path" in q.read_text(encoding="utf-8")}
    assert routed == set(progs), (
        f"on the route and not named here: {sorted(routed - set(progs))}; "
        f"named here and no longer on the route: {sorted(set(progs) - routed)}")
    for prog in progs:
        out = subprocess.run([sys.executable, str(_PROGRAMS / prog), "--help"],
                             capture_output=True, text=True,
                             cwd=str(tmp_path))
        # The EXIT CODE is deliberately not asserted here.
        # `ppa_feasibility_check.py --help` exits 3 rather than 0; that is a
        # separate, already-recorded defect
        # (`test_bad_invocation_help_is_0_on_the_feasibility_cli_too` is
        # xfail), and folding it into this row would make this test go green
        # or red for a reason that has nothing to do with the route.
        assert "--project" in out.stdout, (
            f"{prog} cannot be told which design tree its inputs came from, "
            f"so it cannot resolve a delivery path and an absent "
            f"design-for-ECO declaration stays a non-finding")


def test_finding_the_shipped_campaign_contracts_declare_neither_key():
    """The denominator, read from the shipped records rather than remembered.

    Skipped, not silently passed, when the campaign tree is not present -- an
    empty scan is NOT OBSERVED and must not read as "every contract is fine".
    """
    import pytest
    trials = _campaign_trials()
    if not trials.is_dir():
        pytest.skip(f"the cross-layer campaign records are not in this tree "
                    f"({trials}); this row was NOT OBSERVED, not satisfied")
    # BOTH documents, because they are not the same document and only one of
    # them is the feasibility policy. `contract.json` is `vibeic.ppa.contract`
    # -- identities, evidence manifest, declared facts. `candidates.json` is
    # what `policy_from_document` actually reads: it carries `required_views`,
    # `required_views_by_axis`, `limits` and `allow_waivers`. Checking only the
    # first would be measuring the finding on the wrong artefact.
    seen = declares = routes = 0
    for name in ("contract.json", "candidates.json"):
        for doc_path in sorted(trials.glob(f"*/{name}")):
            try:
                doc = json.loads(doc_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(doc, dict):
                continue
            seen += 1
            declares += int("eco_readiness" in doc)
            routes += int("delivery_path" in doc)
    assert seen > 0, "no campaign document parsed; the denominator is empty"
    assert (declares, routes) == (0, 0), (
        f"{declares} of {seen} campaign documents declare eco_readiness and "
        f"{routes} state a delivery path; the finding in this file's header "
        f"was measured when both were zero and must be re-measured")

    # And the sharper form: the policy documents ENUMERATE the axes they
    # require views for, and the ECO axis is not among them. These were written
    # when the table had nine entries; `eco_readiness` is the tenth.
    named = set()
    policies = 0
    for cand_path in sorted(trials.glob("*/candidates.json")):
        try:
            doc = json.loads(cand_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(doc, dict) and isinstance(
                doc.get("required_views_by_axis"), dict):
            policies += 1
            named |= set(doc["required_views_by_axis"])
    if policies:
        assert F.ECO_AXIS not in named, (
            f"{F.ECO_AXIS} is now named in the campaign's per-axis view "
            f"declarations ({sorted(named)}); the finding that the tenth axis "
            f"is absent from all {policies} of them must be re-measured")
        assert len(named) == 9, sorted(named)


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


# ---------------------------------------------------------------------------
# THE ROUTE, SUPPLIED -- the gap above, closed, and measured end to end
# ---------------------------------------------------------------------------
# `--project` changes nothing about what an absent declaration MEANS. It
# supplies the route, which is the thing the landed gate was already asking
# for and which this lane alone could not give it.
import dataclasses                              # noqa: E402
from _ppa import delivery_path as DP            # noqa: E402
from test_ppa_eco_delivery_path import chip_tree, ip_tree, unrouted_tree  # noqa: E402
import _submission_template as _ST            # noqa: E402
ST_NO_TEMPLATE_REL = _ST.NO_TEMPLATE_REL


def _with_route(pol, project):
    """What `ppa_search_run.py --project` does to a policy, via the same call."""
    return dataclasses.replace(pol, delivery_path=DP.resolve(str(project)))


def test_route_a_chip_tree_turns_the_silent_pass_into_cannot_check(tmp_path):
    """The whole point of the flag. Same silent policy, same records; the only
    new fact is which route the flow put this design on."""
    project = chip_tree(tmp_path / "chip")
    silent = silent_policy()
    routed = _with_route(silent, project)

    before = F.promotion_verdict(cand("deleted", deleted_spares()), silent)
    after = F.promotion_verdict(cand("deleted", deleted_spares()), routed)

    assert before.verdict == F.FEASIBLE
    assert F.set_exit_code([before]) == F.RC_PASS
    assert after.verdict == F.UNDETERMINED, after.codes
    assert F.set_exit_code([after]) == F.RC_UNDETERMINED
    assert axis_of(after).applicability["state"] == \
        F.ECO_NOT_DECLARED_ON_CHIP_PATH


def test_route_the_search_bridge_stops_publishing_it_as_eligible(tmp_path):
    """Through the bridge a campaign really uses, which is where it counts."""
    routed = _with_route(silent_policy(), chip_tree(tmp_path / "chip"))
    v = _bridge(routed, deleted_spares(), "deleted")
    assert v.verdict == S.FEAS_UNDETERMINED
    assert v.verdict != S.FEAS_ELIGIBLE
    assert v.terms[F.ECO_AXIS] == "NOT_CHECKED"


def test_route_a_proven_ip_delivery_is_still_not_applicable(tmp_path):
    """The flag must not become "refuse everything". A hardmacro delivery owes
    no spare population of its own, and the route says so."""
    routed = _with_route(silent_policy(), ip_tree(tmp_path / "ip"))
    r = F.promotion_verdict(cand("macro", deleted_spares()), routed)
    assert r.verdict == F.FEASIBLE, r.codes
    assert axis_of(r).status == F.AXIS_NOT_APPLICABLE
    assert axis_of(r).applicability["state"] == F.ECO_NOT_APPLICABLE_ON_IP_PATH


def test_route_an_unestablished_route_is_refused_not_read_as_ip(tmp_path):
    """A tree with no router artefact has NOT been shown to be an IP delivery.
    Guessing that it is would be the one way this flag could make things worse
    than the silence it replaces."""
    routed = _with_route(silent_policy(), unrouted_tree(tmp_path / "nowhere"))
    r = F.promotion_verdict(cand("unknown", deleted_spares()), routed)
    assert r.verdict == F.UNDETERMINED, r.codes
    assert axis_of(r).applicability["state"] == F.ECO_PATH_UNDETERMINED


def test_route_a_declaration_still_wins_over_the_route(tmp_path):
    """The route decides only what an ABSENT declaration means. A design that
    stated a requirement is held to it on any path -- including the IP one, so
    the flag cannot be used to declare a requirement away."""
    declared = F.policy_from_document(
        {"required_views": [dict(VIEW)], "eco_readiness": dict(DECL)})
    on_ip = _with_route(declared, ip_tree(tmp_path / "ip"))
    r = F.promotion_verdict(cand("deleted", deleted_spares()), on_ip)
    assert r.verdict == F.INFEASIBLE, r.codes
    assert axis_of(r).status == F.AXIS_VIOLATED


# ---------------------------------------------------------------------------
# THE MANIFEST SAYS WHAT IT WAS IN A POSITION TO DECIDE
# ---------------------------------------------------------------------------
def _toolchain(pol, tmp_path):
    return SF.toolchain_record(tmp_path / "policy.json", {}, pol)


def test_manifest_publishes_the_eco_stance_when_nothing_was_declared(tmp_path):
    """A per-candidate term reading NOT_APPLICABLE was the only thing that said
    so, and a reader of a published manifest looks at the toolchain block ONCE
    to find out what the run could decide. The note names the consequence in
    words rather than leaving it to be inferred from a status."""
    tc = _toolchain(silent_policy(), tmp_path)
    assert tc["feasibility_eco_state"] == F.ECO_NOT_DECLARED
    assert tc["feasibility_eco_declared"] is False
    assert tc["feasibility_delivery_path"] == "NOT_SUPPLIED"
    assert "NO ECO-readiness finding" in tc["feasibility_eco_note"]
    assert "eligible" in tc["feasibility_eco_note"]
    # and the headline note carries it too, so a reader quoting one line quotes
    # the caveat with it
    assert "NO ECO-readiness finding" in tc["feasibility_note"]


def test_manifest_stance_changes_with_the_route_and_the_declaration(tmp_path):
    """Three policies, three stances, three notes. A field that read the same
    in all three would be decoration."""
    silent = _toolchain(silent_policy(), tmp_path)
    routed = _toolchain(_with_route(silent_policy(), chip_tree(tmp_path / "c")),
                        tmp_path)
    declared = _toolchain(F.policy_from_document(
        {"required_views": [dict(VIEW)], "eco_readiness": dict(DECL)}), tmp_path)

    states = [silent["feasibility_eco_state"], routed["feasibility_eco_state"],
              declared["feasibility_eco_state"]]
    assert states == [F.ECO_NOT_DECLARED, F.ECO_NOT_DECLARED_ON_CHIP_PATH,
                      F.ECO_REQUIRED], states
    assert len({t["feasibility_eco_note"] for t in
                (silent, routed, declared)}) >= 2
    assert declared["feasibility_eco_declared"] is True
    assert routed["feasibility_delivery_path"] == "CHIP"


def test_manifest_stance_is_derived_and_cannot_disagree_with_the_verdicts(tmp_path):
    """Derived from the SAME policy the candidates are adjudicated against, so
    a manifest cannot state a stance the verdicts contradict."""
    pol = _with_route(silent_policy(), chip_tree(tmp_path / "c"))
    tc = _toolchain(pol, tmp_path)
    r = F.promotion_verdict(cand("deleted", deleted_spares()), pol)
    assert tc["feasibility_eco_state"] == \
        axis_of(r).applicability["state"] == F.ECO_NOT_DECLARED_ON_CHIP_PATH


# ---------------------------------------------------------------------------
# NEGATIVE CONTROL for the new wiring
# ---------------------------------------------------------------------------
# --- the CLI, RUN, because every route test above calls the library ---------
import ppa_search_run as R                      # noqa: E402
from test_ppa_search_feasibility_wiring import (  # noqa: E402
    SPACE as WIRING_SPACE, VIEW as WIRING_VIEW, _nine_clean, _trial)


def _campaign(tmp_path, eco=None):
    """A minimal but REAL search run: a space, one trial whose records are
    clean on every axis but ECO, and the shipped campaign's policy shape."""
    d = tmp_path / "campaign"
    d.mkdir()
    records = _nine_clean(1000.0) + [
        dict(m, scope=dict(WIRING_VIEW)) for m in spares(
            count=0, by_kind={k: 0 for k in DECL["min_spare_cells_by_kind"]},
            positions=0, tied=None)]
    (d / "space.json").write_text(json.dumps(WIRING_SPACE), encoding="utf-8")
    (d / "trials.json").write_text(
        json.dumps([_trial("binary", records)]), encoding="utf-8")
    doc = {"required_views": [WIRING_VIEW]}
    if eco is not None:
        doc["eco_readiness"] = eco
    (d / "policy.json").write_text(json.dumps(doc), encoding="utf-8")
    return d


def _ran(man):
    """The candidate that actually RAN.

    The space proposes two points and only one trial is supplied, so the other
    is UNDETERMINED because it was never executed -- which is correct and has
    nothing to do with ECO readiness. Selecting by knob rather than by verdict
    keeps this from quietly becoming "whichever one agrees with me".
    """
    hits = [c for c in man["candidates"]
            if c["knobs"]["state_encoding"] == "binary"]
    assert len(hits) == 1, [c["knobs"] for c in man["candidates"]]
    return hits[0]


def _run_campaign(d, *extra, out="manifest.json"):
    rc = R.main([str(d / "space.json"), "--trials", str(d / "trials.json"),
                 "--max-trials", "1", "--max-full-pnr-trials", "1",
                 "--feasibility-policy", str(d / "policy.json"),
                 "--json", str(d / out), *extra])
    man = json.loads((d / out).read_text()) if (d / out).exists() else {}
    return rc, man


def test_cli_a_silent_campaign_says_out_loud_that_it_made_no_eco_finding(
        tmp_path, capsys):
    """The published manifest and the human output both disclose it. Before
    this, the only thing that said so was a per-candidate term."""
    d = _campaign(tmp_path)
    _rc, man = _run_campaign(d)
    tc = man["toolchain"]
    assert tc["feasibility_eco_state"] == F.ECO_NOT_DECLARED
    assert tc["feasibility_delivery_path"] == "NOT_SUPPLIED"
    out = capsys.readouterr()
    text = out.out + out.err
    assert "[CANNOT CHECK]" in text
    assert "--project" in text
    # The warning must name the CONSEQUENCE, not only the condition. Without
    # this the line reads as informational and a caller does not learn that
    # `--verify` is about to refuse what they just built.
    assert "ELIGIBLE_ON_AN_UNDECLARED_ECO_STANCE" in text, text
    assert "--verify" in text, text


def test_cli_project_stamps_the_route_into_the_published_manifest(tmp_path):
    """`--project` end to end: the route reaches the manifest, so a reader can
    see WHAT this run was in a position to decide, by name."""
    d = _campaign(tmp_path)
    _rc, man = _run_campaign(d, "--project", str(chip_tree(tmp_path / "chip")))
    tc = man["toolchain"]
    assert tc["feasibility_delivery_path"] == "CHIP"
    assert tc["feasibility_eco_state"] == F.ECO_NOT_DECLARED_ON_CHIP_PATH


def test_cli_negative_control_the_flag_changes_the_published_verdict(tmp_path):
    """THE control for this fix, run rather than grepped.

    Two invocations of the real CLI over byte-identical inputs; the only
    difference is `--project`. If the flag parsed and changed nothing -- the
    worst outcome available, a run that looks guarded and is not -- both
    manifests would carry the same candidate verdict and this fails.
    """
    d = _campaign(tmp_path)
    _rc_a, without = _run_campaign(d, out="a.json")
    _rc_b, with_route = _run_campaign(
        d, "--project", str(chip_tree(tmp_path / "chip")), out="b.json")

    va = _ran(without)["feasibility"]["verdict"]
    vb = _ran(with_route)["feasibility"]["verdict"]
    assert va == S.FEAS_ELIGIBLE, va
    assert vb == S.FEAS_UNDETERMINED, vb
    assert va != vb


def test_cli_a_declared_requirement_needs_no_project_at_all(tmp_path):
    """The flag is a second route to the gate, not the only one. A campaign
    that declares its requirement is adjudicated without `--project`, and the
    spare-deleting candidate is INELIGIBLE."""
    d = _campaign(tmp_path, eco=dict(DECL))
    _rc, man = _run_campaign(d)
    assert man["toolchain"]["feasibility_eco_state"] == F.ECO_REQUIRED
    ran = _ran(man)
    assert ran["feasibility"]["verdict"] == S.FEAS_INELIGIBLE
    assert ran["feasibility"]["terms"][F.ECO_AXIS] == "FAIL"


def test_negative_control_the_route_is_what_flips_it_not_the_records(tmp_path):
    """Both arms use byte-identical records and byte-identical policy documents.
    The ONLY difference is whether a route was resolved. If this ever passes
    with the two arms agreeing, the route is not what is doing the work."""
    records = deleted_spares()
    without = F.promotion_verdict(cand("d", records), silent_policy())
    with_route = F.promotion_verdict(
        cand("d", records), _with_route(silent_policy(), chip_tree(tmp_path / "c")))
    assert without.verdict != with_route.verdict
    assert (without.eligible_for_promotion, with_route.eligible_for_promotion) \
        == (True, False)


# ---------------------------------------------------------------------------
# THE ARITHMETIC IS ON THE VERDICT -- checkable without re-running the flow
# ---------------------------------------------------------------------------
# A refusal a reader has to reproduce in order to understand is a refusal that
# gets argued with. The row must carry the numbers it refused on: what the
# design was required to have, what its insertion plan recorded, and how many
# of those reached the shipped artefacts.
def _stripped_row(surviving=9, floor_decl=None):
    """Declared floor 10 with preservation required; `surviving` shipped."""
    decl = dict(floor_decl or DECL, require_preservation=True)
    ms = clean_nine() + spares(count=10) + [rec(F.ECO_M_SURVIVING, surviving)]
    pol = F.policy_from_document({"required_views": [dict(VIEW)],
                                  "eco_readiness": decl})
    r = F.promotion_verdict(cand("stripped", ms), pol)
    return r, axis_of(r)


def _by_metric(row_dict):
    return {e["metric"]: e for e in row_dict["evidence"] if "metric" in e}


def test_acceptance_the_row_states_the_floor_the_plan_and_the_survivors():
    """Three numbers, all on the published row: what was REQUIRED, what the
    insertion plan RECORDED, and what SURVIVED to the shipped artefacts."""
    r, axis = _stripped_row(surviving=9)
    assert r.verdict == F.INFEASIBLE
    assert axis.status == F.AXIS_VIOLATED

    ev = _by_metric(axis.as_dict())
    inserted = ev[F.ECO_M_COUNT]
    survived = ev[F.ECO_M_SURVIVING]

    assert inserted["value"] == 10                    # the plan recorded ten
    assert survived["value"] == 9                     # nine reached the ship
    assert survived["limit"]["min"] == 10             # ten were required
    assert inserted["limit"]["min"] == 10


def test_acceptance_a_reader_can_do_the_subtraction_from_the_json_alone():
    """The whole clause, as one assertion: SERIALISE the verdict, throw the
    objects away, and recover how many spares went missing from the document a
    reader is actually handed."""
    r, _axis = _stripped_row(surviving=9)
    doc = json.loads(json.dumps(r.as_dict()))
    row = [a for a in doc["axes"] if a["axis"] == F.ECO_AXIS][0]
    ev = _by_metric(row)

    required = ev[F.ECO_M_SURVIVING]["limit"]["min"]
    survived = ev[F.ECO_M_SURVIVING]["value"]
    assert required - survived == 1, (required, survived)
    assert row["status"] == "VIOLATED"


def test_acceptance_the_row_states_them_when_it_PASSES_too(tmp_path):
    """A reader checking whether the floor was the right floor should not have
    to make the axis fail first. The satisfied row carries the same numbers."""
    r, axis = _stripped_row(surviving=10)
    assert r.verdict == F.FEASIBLE, r.codes
    assert axis.status == F.AXIS_SATISFIED
    ev = _by_metric(axis.as_dict())
    assert ev[F.ECO_M_SURVIVING]["value"] == 10
    assert ev[F.ECO_M_SURVIVING]["limit"]["min"] == 10


def test_acceptance_the_floor_on_the_row_is_the_designs_and_not_the_gates():
    """Change the declaration, and the number published as the floor changes
    with it. A floor that stayed at 10 would be a design decision living in
    chip-agnostic source -- which is the thing this axis is built not to do."""
    _r7, axis7 = _stripped_row(surviving=9, floor_decl=dict(
        DECL, min_spare_cells=7))
    ev = _by_metric(axis7.as_dict())
    assert ev[F.ECO_M_SURVIVING]["limit"]["min"] == 7
    # and nine against a floor of seven is not a violation at all
    assert axis7.status == F.AXIS_SATISFIED


# ---------------------------------------------------------------------------
# THE CAMPAIGN THAT MOTIVATED THE AXIS, ADJUDICATED BY IT
# ---------------------------------------------------------------------------
# Everything above runs on fixtures. This runs the SHIPPED producer over the
# SHIPPED `spare_cells.json` of four real trials and hands the records to the
# SHIPPED gate. It is the only row here where no number was authored by a test.
#
#   trial  area um2   power W    spares   the axis says
#   z23      6106     0.000541     10     FEASIBLE      <- admitted
#   p08      6291     0.000562     10     FEASIBLE
#   p04      6136     0.000559      0     INFEASIBLE    <- the published winner
#   z21      6011     0.000545      0     INFEASIBLE    <- the Pareto winner
#
# The two arms the axis refuses are the two the campaign published as winners,
# and it refuses them from their own artefacts. The arm it admits is smaller
# AND cooler than the PnR-only winner it replaces, which is the answer to "this
# gate is expensive".
PRODUCER = _PROGRAMS / "ppa_eco_spare_records.py"

#: The DESIGN's requirement, and it lives here because it is a statement about
#: a design -- the shipped default run of this design carried ten spares at
#: density 0.02, so ten is what it says it needs. Nothing in the gate may hold
#: this number.
CAMPAIGN_DECL = {"required": True, "min_spare_cells": 10}

#: (trial, spares its own spare_cells.json records, does the axis admit it)
CAMPAIGN_ARMS = (("z23", 10, True), ("p08", 10, True),
                 ("p04", 0, False), ("z21", 0, False))


#: A file in the repo root that is not this lane's, so finding it means the
#: anchor below resolved to a REPO and not merely to some directory that
#: happens to lack `ppa-crosslayer`.
_ROOT_WITNESS = "vibe-ic-marketplace"


def _repo_root():
    """The repo root, or a FAILURE -- never a silent skip.

    Every row that reads shipped records locates them from `_PROGRAMS.parents[3]`,
    and every one of them SKIPS when it finds nothing. That is right when the
    records are genuinely absent and WRONG when the arithmetic has gone stale:
    move the plugin one directory and all of them skip, reporting NOT OBSERVED
    about a tree they never looked at. "The records are not here" and "I am
    looking in the wrong place" would share a verdict, which is the one thing
    this lane refuses everywhere else.

    So the anchor is CHECKED. A root that does not carry `_ROOT_WITNESS` is a
    broken calculation and fails loudly; a root that carries it and lacks the
    records is a real absence and the caller may skip.
    """
    root = _PROGRAMS.parents[3]
    assert (root / _ROOT_WITNESS).is_dir(), (
        f"the repo-root anchor `_PROGRAMS.parents[3]` resolved to {root}, which "
        f"carries no `{_ROOT_WITNESS}` -- the path arithmetic is stale, and "
        f"every record-reading row in this file would otherwise SKIP and report "
        f"NOT OBSERVED about a tree it never looked at")
    return root


def _campaign_trials():
    return _repo_root() / "ppa-crosslayer" / "records" / "trials"


def _eco_only_policy():
    """The ECO axis alone. The bundles below carry ECO records and nothing
    else, so against the full table NINE axes have no evidence at all
    (setup, hold, drv, drc, lvs, antenna, ir, em, equivalence) and the verdict
    they drag to UNDETERMINED would say nothing about design-for-ECO.

    NINE, measured -- ten axes in the table, one of them the subject. An earlier
    revision of this docstring said "eight", which was wrong when written and is
    the reason `test_eco_only_policy_leaves_exactly_nine_axes_unevidenced`
    exists: a number in a comment that nothing checks is a number that drifts.
    """
    pol = F.policy_from_document(
        {"required_views_by_axis": {F.ECO_AXIS: [{"stage": "post_route"}]},
         "eco_readiness": dict(CAMPAIGN_DECL)})
    return dataclasses.replace(
        pol, axes=tuple(a for a in pol.axes if a.name == F.ECO_AXIS))


def test_the_prose_ten_is_the_declaration_and_the_kind_mix_sums_to_it():
    """The other number this file's prose leans on.

    Five comments say "all ten spare cells". That ten is not a literal anybody
    typed twice -- it is `DECL["min_spare_cells"]`, and the per-kind floors sum
    to it. Asserted because the sibling row exists for a docstring number that
    was wrong and nothing checked; the difference here is that the prose traces
    to one fixture, and this makes that traceability a test rather than a habit.
    """
    assert DECL["min_spare_cells"] == 10, DECL
    assert sum(DECL["min_spare_cells_by_kind"].values()) == 10, DECL
    # and the fixture the prose describes really does start from that number
    kept = [m for m in kept_spares() if m["metric"] == F.ECO_M_COUNT]
    assert kept and kept[0]["value"] == DECL["min_spare_cells"], kept


def test_eco_only_policy_leaves_exactly_nine_axes_unevidenced():
    """Pins the number the sibling docstring states.

    The ECO-only bundles carry one axis's records; the table has ten. If a
    future axis is added or removed, this reddens and the prose next to it gets
    re-read -- which is the only way a count in a comment stays true.
    """
    recs = clean_nine()[:0] + spares()          # ECO records and nothing else
    pol = F.policy_from_document(
        {"required_views_by_axis": {F.ECO_AXIS: [dict(VIEW)]},
         "eco_readiness": dict(DECL)})
    r = F.promotion_verdict(cand("eco-only", recs), pol)
    unevidenced = [a.name for a in r.axes if a.status == F.AXIS_UNDETERMINED]
    assert len(F.DEFAULT_AXES) == 10, [a.name for a in F.DEFAULT_AXES]
    assert len(unevidenced) == 9, unevidenced
    assert F.ECO_AXIS not in unevidenced, unevidenced


def test_real_the_axis_admits_the_eco_preserving_arm_and_refuses_the_winners(
        tmp_path):
    """End to end on shipped artefacts: real producer, real gate, no fixtures.

    Skipped -- not silently passed -- when the campaign tree is absent. An
    empty scan is NOT OBSERVED, and a green from an empty denominator is the
    thing this whole lane exists to refuse.
    """
    import pytest
    trials = _campaign_trials()
    if not trials.is_dir():
        pytest.skip(f"the cross-layer campaign records are not in this tree "
                    f"({trials}); this row was NOT OBSERVED")

    pol = _eco_only_policy()
    seen = {}
    for trial, spares_recorded, admitted in CAMPAIGN_ARMS:
        plan = trials / trial / "spare_cells.json"
        if not plan.is_file():
            pytest.skip(f"{plan} is not in this tree; NOT OBSERVED")
        out = tmp_path / f"{trial}.json"
        p = subprocess.run(
            [sys.executable, str(PRODUCER), "--spare-plan", str(plan),
             "--stage", "post_route", "--json", str(out)],
            capture_output=True, text=True, cwd=str(tmp_path))
        assert p.returncode == 0, (trial, p.stdout, p.stderr)

        records = json.loads(out.read_text(encoding="utf-8"))["records"]
        r = F.promotion_verdict({"candidate_id": trial, "metrics": records},
                                pol)
        count = next((e["value"] for e in r.axes[0].as_dict()["evidence"]
                      if e.get("metric") == F.ECO_M_COUNT), None)

        assert count == spares_recorded, (trial, count, spares_recorded)
        assert r.eligible_for_promotion is admitted, (
            f"{trial} records {count} spare(s) and the axis "
            f"{'admits' if r.eligible_for_promotion else 'refuses'} it; "
            f"expected the opposite")
        seen[trial] = (r.verdict, F.set_exit_code([r]))

    # stated as verdicts too, so a reader of a failure sees which way each went
    assert seen["z23"] == (F.FEASIBLE, F.RC_PASS)
    assert seen["p08"] == (F.FEASIBLE, F.RC_PASS)
    assert seen["p04"] == (F.INFEASIBLE, F.RC_FAIL)
    assert seen["z21"] == (F.INFEASIBLE, F.RC_FAIL)


def test_real_the_two_refused_arms_are_the_ones_the_campaign_published(
        tmp_path):
    """The cost of the axis, named. It refuses the published PnR-only winner
    (p04) and the published Pareto winner (z21) -- and the arm it admits is
    SMALLER and COOLER than p04, so the win survives the gate. Read from each
    arm's own artefact, not from the report's prose."""
    import pytest
    trials = _campaign_trials()
    if not trials.is_dir():
        pytest.skip("the cross-layer campaign records are not in this tree; "
                    "NOT OBSERVED")
    counts = {}
    for trial, _n, _adm in CAMPAIGN_ARMS:
        plan = trials / trial / "spare_cells.json"
        if not plan.is_file():
            pytest.skip(f"{plan} is not in this tree; NOT OBSERVED")
        counts[trial] = json.loads(plan.read_text(encoding="utf-8"))["count"]
    assert counts == {"z23": 10, "p08": 10, "p04": 0, "z21": 0}, counts


# ---------------------------------------------------------------------------
# WHAT THE AXIS ACTUALLY COSTS, BY THE SHIPPED COMPARATOR
# ---------------------------------------------------------------------------
# "This gate is expensive" is the objection the axis will meet, and the honest
# answer is not a sentence, it is a domination relation. Computed by
# `_ppa/pareto.dominates` over the two published objectives rather than by
# eyeballing a table:
#
#     z23 (admitted)  DOMINATES  p04 (refused, the published PnR-only winner)
#     z23 (admitted)  vs         z21 (refused)  -> INCOMPARABLE
#
# z21 is 95 um2 smaller and 0.000004 W hotter, so it does not dominate z23; it
# is a trade, and the campaign's own report publishes trades as trades. So NO
# arm this axis refuses dominates the arm it admits. The gate costs zero
# Pareto-dominating candidates, and that is the claim -- not "z21 was the price".
from _ppa import pareto as PA                   # noqa: E402

#: area µm² and post-route power W, from the campaign's published head-to-head.
CAMPAIGN_TRIPLES = {"z23": (6106, 0.000541), "p08": (6291, 0.000562),
                    "p04": (6136, 0.000559), "z21": (6011, 0.000545)}
ADMITTED_ARMS = ("z23", "p08")
REFUSED_ARMS = ("p04", "z21")


def _objectives():
    return (PA.Objective("area", "area.design_report.um2", PA.SENSE_MIN),
            PA.Objective("power", "power.total_w", PA.SENSE_MIN))


def _point(trial):
    area, power = CAMPAIGN_TRIPLES[trial]
    return {"values": {"area": {"value": area}, "power": {"value": power}}}


def test_cost_no_refused_arm_dominates_the_arm_the_axis_admits():
    """THE cost claim, as a domination relation and not a sentence.

    If any refused arm dominated an admitted one, the axis would be throwing
    away a strictly better design and "expensive" would be the right word.
    None does.
    """
    objs = _objectives()
    best_admitted = "z23"
    offenders = [r for r in REFUSED_ARMS
                 if PA.dominates(_point(r), _point(best_admitted), objs)]
    assert offenders == [], (
        f"{offenders} are refused by the ECO axis and dominate {best_admitted} "
        f"on both published objectives; the axis is discarding a strictly "
        f"better design")


def test_cost_the_admitted_arm_dominates_the_published_winner():
    """The positive half. z23 is not merely allowed through -- it is strictly
    better than the arm the campaign published, on BOTH objectives at once."""
    objs = _objectives()
    assert PA.dominates(_point("z23"), _point("p04"), objs), (
        "z23 no longer dominates p04; the 'the axis does not cost us the win' "
        "claim rests on this and must be re-measured")


def test_cost_the_other_refused_arm_is_a_trade_and_not_a_loss():
    """z21 is smaller and hotter. Neither dominates, so refusing it costs a
    TRADE, not a win -- and the campaign's own report publishes trades as
    trades. Asserted in both directions so a one-sided change is caught."""
    objs = _objectives()
    assert not PA.dominates(_point("z21"), _point("z23"), objs)
    assert not PA.dominates(_point("z23"), _point("z21"), objs)


# ---------------------------------------------------------------------------
# THE MANIFEST THIS LANE PUBLISHES STILL VALIDATES
# ---------------------------------------------------------------------------
# The ECO stance added four keys to the toolchain block of a document that has a
# SHIPPED schema. `search_manifest.v1` is permissive there today
# (`toolchain: {"type": "object"}`, top-level additionalProperties true), so the
# keys are legal -- but that is a fact about the schema, and a schema that is
# later tightened would break this lane silently. Validated against a REAL
# produced manifest rather than read off the schema file.
def test_the_published_manifest_still_validates_with_the_eco_stance(tmp_path):
    from _ppa import schema_validation as SV
    schema = json.loads(
        (_PROGRAMS.parent / "schemas" / "ppa"
         / "search_manifest.v1.schema.json").read_text(encoding="utf-8"))
    _rc, man = _run_campaign(_campaign(tmp_path))
    added = sorted(k for k in man["toolchain"]
                   if "eco" in k or "delivery" in k)
    assert added == ["feasibility_delivery_path", "feasibility_eco_declared",
                     "feasibility_eco_note", "feasibility_eco_state"], added
    assert SV.engine_or_skip(schema).errors(man) == []


# ---------------------------------------------------------------------------
# WHAT THE DELETE-THE-SPARES KNOB ACTUALLY COST THE CAMPAIGN
# ---------------------------------------------------------------------------
# The open question the axis raises is whether `spare_cell_density` should stay
# in the search space at all. The argument for keeping it -- that the budget
# wasted on points which can never promote is small -- is an EMPIRICAL claim,
# and it was made here without a measurement. Measured, over the shipped
# campaign's own run records:
#
#     77 trials state the knob:  42 at 0.02, 30 at 0.00, 5 at 0.05
#     10.16 CPU-hours total, 3.44 of them at density 0.00
#     -> 33.9% of the campaign's compute ran the arm that deletes the spares
#
# A THIRD, not "a few percent". That is the number the keep-it argument has to
# survive, and it is why `ppa_pnr_search_space.py --eco-declaration` refusing
# density 0 at SPACE-GENERATION time is the load-bearing part: with the guard in
# the loop the cost is zero because the points are never generated, and 33.9% is
# the cost of the guard being AVAILABLE rather than WIRED.
#
# These trials were not themselves unpromotable -- they ran before the axis
# existed, against contracts that declared no requirement. The conditional is
# the finding: re-run this campaign with the requirement declared and the space
# guard bypassed, and a third of the budget buys candidates the gate must
# refuse.
def test_knob_the_zero_spare_arm_took_a_third_of_the_campaign_budget():
    """The empirical half of the knob recommendation, measured not asserted.

    Skipped, never silently passed, when the campaign tree is absent.
    """
    import pytest
    trials = _campaign_trials()
    if not trials.is_dir():
        pytest.skip("the cross-layer campaign records are not in this tree; "
                    "NOT OBSERVED")

    total_cpu = zero_cpu = 0.0
    seen = zero_n = 0
    for run in sorted(trials.glob("*/run.json")):
        doc = json.loads(run.read_text(encoding="utf-8"))
        density = (doc.get("pnr_knobs") or {}).get("spare_cell_density")
        cpu = (doc.get("cost") or {}).get("cpu_seconds")
        if density is None:
            continue
        seen += 1
        cpu = cpu if isinstance(cpu, (int, float)) else 0.0
        total_cpu += cpu
        try:
            deletes_spares = float(density) == 0.0
        except (TypeError, ValueError):
            continue
        if deletes_spares:
            zero_n += 1
            zero_cpu += cpu

    assert seen > 0 and total_cpu > 0, (
        "no trial states both the knob and a CPU cost; the denominator is "
        "empty and this row measured nothing")

    share = zero_cpu / total_cpu
    # Pinned as a BAND, not a point: the claim is "a third of the budget", and
    # a test that demanded 33.9% exactly would break on one re-run without the
    # finding having changed.
    assert 0.25 <= share <= 0.45, (
        f"{zero_n} of {seen} trials ran at spare density 0.00 and took "
        f"{share:.1%} of {total_cpu/3600:.2f} CPU-hours; the knob recommendation "
        f"in this lane was argued from 'a third', and that number moved")
    assert zero_n >= 2, zero_n


def test_knob_the_space_guard_is_what_makes_that_cost_zero(tmp_path):
    """And the reason the answer is still "keep the lever, bounded below".

    With a declaration supplied, the space program REFUSES the zero value
    before a single place-and-route trial is spent -- so the 33.9% above is the
    cost of the guard being available rather than wired, not the cost of the
    lever existing. Run, not asserted: the negative control is the same
    invocation without the declaration.
    """
    decl = tmp_path / "eco.json"
    decl.write_text(json.dumps({"eco_readiness": dict(DECL)}), encoding="utf-8")
    space = _PROGRAMS / "ppa_pnr_search_space.py"
    args = [sys.executable, str(space), "--json", str(tmp_path / "space.json"),
            "--values", "spare_cell_density=0.00,0.02"]

    without = subprocess.run(args, capture_output=True, text=True,
                             cwd=str(tmp_path))
    withd = subprocess.run(args + ["--eco-declaration", str(decl)],
                           capture_output=True, text=True, cwd=str(tmp_path))

    assert without.returncode == 0, without.stderr      # the control
    # THE RC IS THE GATE. The message is corroboration on wording this file does
    # not own, kept because the landed `test_M_ECO_7` asserts the same phrase --
    # diverging would leave two tests disagreeing about what the refusal looks
    # like. Split out with its own message so a REWORD reads as a reword and
    # not as the guard having stopped refusing. (Audited after a sibling row was
    # found parsing an output shape that had already moved: this program is not
    # touched by current main, so the phrase has not drifted yet.)
    assert withd.returncode == 1, withd.stdout + withd.stderr
    assert "metal-only ECO" in withd.stderr, (
        "the space guard still refuses (rc=1) but no longer explains itself in "
        "these words; if the wording moved, update this row and the landed "
        f"test_M_ECO_7 together:\n{withd.stderr}")


# ---------------------------------------------------------------------------
# THE GRADED SIGNAL: DOES THE OPTIMISER GET A GRADIENT AWAY FROM THE DELETION?
# ---------------------------------------------------------------------------
# The knob recommendation in this lane leans on a claim about `search_penalty`:
# that an optimiser is steered out of the spare-deleting region rather than
# sampling it blind. That is a claim about code and it was made without being
# measured. Measured:
#
#     declared, spares kept      eco SATISFIED       penalty 0.0
#     declared, spares deleted   eco VIOLATED        penalty 1.0   <- gradient
#     silent contract, deleted   eco NOT_APPLICABLE  penalty 0.0   <- no gradient
#
# The third row sharpens the finding this whole file is about. On a silent
# contract the hard gate does not refuse the candidate AND the graded penalty
# gives the search nothing to walk down. Both signals go quiet together, which
# is worse than either alone: the search is not merely allowed to publish the
# deletion, it has no reason to look elsewhere.
def _penalty_for(candidate, pol):
    result = F.promotion_verdict(candidate, pol)
    return result, F.search_penalty(result, F.PenaltyWeights())


def _deleted_with_tie_off_stated():
    """A deleted population whose tie-off record EXISTS and says NOT_TIED_OFF.

    `spares(tied=None)` omits the record, which makes the axis UNDETERMINED for
    a second reason; this fixture keeps the refusal attributable to the count.
    """
    return clean_nine() + spares(
        count=0, by_kind={k: 0 for k in DECL["min_spare_cells_by_kind"]},
        positions=0, tied="NOT_TIED_OFF")


def test_penalty_a_deleted_population_carries_a_penalty_term():
    """The graded half. A search that only saw the hard verdict would have no
    gradient to walk back along; the axis contributes a term like any other."""
    _r, pen = _penalty_for(cand("gone", _deleted_with_tie_off_stated()),
                           policy())
    assert pen["terms"].get(F.ECO_AXIS) == 1.0, pen["terms"]
    assert pen["penalty"] >= 1.0


def test_penalty_a_preserved_population_carries_none():
    """A term on every candidate would be a constant, not a signal."""
    _r, pen = _penalty_for(cand("kept", clean_nine() + spares()), policy())
    assert F.ECO_AXIS not in pen["terms"], pen["terms"]
    assert pen["penalty"] == 0.0


def test_penalty_on_a_silent_contract_BOTH_signals_go_quiet():
    """The finding, in its sharpest form.

    With no requirement declared and no route resolved, the candidate that
    deleted the design's whole spare population is promotable AND carries no
    penalty. The gate does not refuse it and the search has no reason to move
    away from it. Two independent mechanisms, one silence.
    """
    records = _deleted_with_tie_off_stated()
    result, pen = _penalty_for(cand("gone", records), silent_policy())
    assert result.eligible_for_promotion            # the gate is quiet
    assert F.ECO_AXIS not in pen["terms"]           # the gradient is quiet too
    assert pen["penalty"] == 0.0

    # and both wake up together once the requirement is declared
    declared_result, declared_pen = _penalty_for(cand("gone", records),
                                                 policy())
    assert not declared_result.eligible_for_promotion
    assert declared_pen["terms"][F.ECO_AXIS] == 1.0


def test_penalty_is_never_mistakable_for_an_eligibility_decision():
    """The separation this module is built on, checked on THIS axis: the
    penalty document says `promotable: None` and `basis: SEARCH_ONLY`, so a
    caller serialising it into a report cannot pass it off as a verdict."""
    _r, pen = _penalty_for(cand("gone", _deleted_with_tie_off_stated()),
                           policy())
    assert pen["promotable"] is None
    assert pen["basis"] == "SEARCH_ONLY"


# ---------------------------------------------------------------------------
# THE ROUTER ON TREES NOBODY BUILT FOR IT
# ---------------------------------------------------------------------------
# Every route test above hands `DP.resolve` a tree this suite constructed. That
# is faithful -- the fixtures spell the marker files from the modules that own
# them -- but it cannot show what the predicate does on a directory nobody made
# for it. No tree in this repo carries `input/submission_template/`, so the CHIP
# and IP arms are not reachable from real in-tree data at all; what IS reachable,
# and is the arm that matters, is the SAFE direction:
#
#     a real project directory with no router artefact must resolve to
#     NOT_DETERMINED and the axis stance to PATH_UNDETERMINED -- never IP.
#
# Reading an unestablished route as an IP delivery would silently exempt a
# design from ECO readiness, which is the one way this flag could make things
# worse than the silence it replaces.
def _real_project_dirs():
    """Real, non-fixture directories in this repo that look like run trees."""
    root = _repo_root()
    out = []
    for phase3 in sorted(root.glob("docs/research/**/phase3"))[:12]:
        d = phase3.parent
        if d.is_dir():
            out.append(d)
    return out


def test_router_on_real_trees_never_guesses_an_ip_delivery():
    """The safe direction, on directories this suite did not construct.

    Skipped, not silently passed, when no such tree is in the checkout -- an
    empty scan is NOT OBSERVED.
    """
    import pytest
    dirs = _real_project_dirs()
    if not dirs:
        pytest.skip("no real run-tree directories in this checkout; NOT "
                    "OBSERVED rather than satisfied")

    seen = 0
    for d in dirs:
        route = DP.resolve(str(d))
        seen += 1
        assert route["path"] != DP.PATH_IP, (
            f"{d} carries no `{ST_NO_TEMPLATE_REL}` and the router still called "
            f"it an IP delivery; an unestablished route read as IP silently "
            f"exempts a design from ECO readiness")
        # and whatever it did say, the axis must not turn it into a pass
        pol = F.policy_from_document(
            {"required_views": [dict(VIEW)], "delivery_path": route})
        stance = F.eco_applicability(pol.eco_requirement,
                                     pol.delivery_path)[0]
        assert stance != F.ECO_NOT_APPLICABLE_ON_IP_PATH, (d, route["path"])
    assert seen > 0


def test_router_on_real_trees_reports_undetermined_not_a_verdict():
    """Positively: with no router artefact the answer is "the route was not
    established", and the axis says PATH_UNDETERMINED -- which blocks."""
    import pytest
    dirs = _real_project_dirs()
    if not dirs:
        pytest.skip("no real run-tree directories in this checkout; NOT "
                    "OBSERVED")
    route = DP.resolve(str(dirs[0]))
    assert route["path"] == DP.PATH_NOT_DETERMINED, route
    pol = F.policy_from_document(
        {"required_views": [dict(VIEW)], "delivery_path": route})
    r = F.promotion_verdict(cand("real-tree", clean_nine()), pol)
    assert axis_of(r).applicability["state"] == F.ECO_PATH_UNDETERMINED
    assert r.verdict == F.UNDETERMINED
    assert F.set_exit_code([r]) == F.RC_UNDETERMINED


# ---------------------------------------------------------------------------
# ELIGIBILITY MAY NOT REST ON ECO SILENCE (the publication boundary)
# ---------------------------------------------------------------------------
# The finding above is that a silent contract publishes the spare-deleting
# candidate as ELIGIBLE. Two ways of stopping that were built and measured and
# BOTH are wrong:
#
#   an UNDETERMINED verdict on an undeclared population -- 18 failures, incl.
#       the feasibility module's core positive fixture. No candidate on any
#       ECO-silent contract could ever be FEASIBLE, so "both arms feasible"
#       could never hold and no head-to-head could be defended.
#   a refusal at policy load -- invents a category the module does not have.
#       `test_a_policy_declaring_no_view_adjudicates_nothing_and_says_so` pins
#       that an UNDER-DECLARED policy RUNS and returns UNDETERMINED; it is
#       never refused at load.
#
# The third place is the one where eligibility stops being an adjudication and
# becomes a PUBLISHED CLAIM. `audit_manifest` already refuses
# ELIGIBLE_ON_A_PARTIAL_VECTOR, under a rule its own test states as "a term the
# contract PROVES does not apply is not a missing check". PROVES is the word
# that decides this: NOT_REQUIRED and the IP path are proofs, NOT_DECLARED is
# an absence wearing a proof's label. The audit could not tell them apart until
# the toolchain block carried the stance; it can now, from the document alone.
#
# The candidate verdict is UNTOUCHED. What is refused is the claim.
def test_publication_a_silent_run_may_not_publish_eligible_candidates(tmp_path):
    """The run still completes and still adjudicates; its manifest does not
    audit clean, because it is claiming eligibility on an axis nobody was
    asked about."""
    d = _campaign(tmp_path)
    _rc, man = _run_campaign(d)
    assert man["toolchain"]["feasibility_eco_state"] == F.ECO_NOT_DECLARED
    assert _ran(man)["feasibility"]["verdict"] == S.FEAS_ELIGIBLE  # unchanged
    codes = [f["code"] for f in S.audit_manifest(man)]
    assert "ELIGIBLE_ON_AN_UNDECLARED_ECO_STANCE" in codes, codes


def test_publication_the_run_that_prints_the_caveat_now_fails_its_own_audit():
    """`ppa_search_run` already PRINTED "[CANNOT CHECK] ... published ELIGIBLE
    by it" on this shape and then audited clean. A report may not publish a
    sentence its own audit refuses; this is the two agreeing."""
    import subprocess as _sp
    src = (_PROGRAMS / "ppa_search_run.py").read_text(encoding="utf-8")
    assert "published ELIGIBLE by it" in src or "is published ELIGIBLE" in src
    assert "ELIGIBLE_ON_AN_UNDECLARED_ECO_STANCE" in \
        (_PROGRAMS / "_ppa" / "search.py").read_text(encoding="utf-8")


def test_publication_a_declared_stance_audits_clean(tmp_path):
    """Both proofs license eligibility, and the clause must not refuse them --
    otherwise it is not "eligibility may not rest on silence", it is "no design
    may ever be eligible"."""
    proofs = ({"required": False}, dict(DECL))
    # THE POPULATION, NOT THE LITERAL'S OWN SIZE. This row used to read
    # `len(proofs) == 2`, which can never fail -- and two copies of the SAME
    # declaration would have satisfied it while proving half as much. What
    # "both licensing shapes" names is the pair of states a PRESENT
    # `eco_readiness` block resolves to that PROVE something, as against the
    # silence (NOT_DECLARED) and the refusal (UNREADABLE) that do not. The
    # states are collected from the runs and compared as a set in both
    # directions, so a shape that stops licensing, and two shapes that
    # collapse onto one state, are each red.
    licensing = {F.ECO_NOT_REQUIRED, F.ECO_REQUIRED}
    seen = {}
    for i, eco in enumerate(proofs):
        sub = tmp_path / f"case{i}"
        sub.mkdir()
        d = _campaign(sub, eco=eco)
        _rc, man = _run_campaign(d)
        seen[man["toolchain"]["feasibility_eco_state"]] = eco
        codes = [f["code"] for f in S.audit_manifest(man)]
        assert "ELIGIBLE_ON_AN_UNDECLARED_ECO_STANCE" not in codes, (eco, codes)
    assert set(seen) == licensing, (
        f"a licensing state no shape here reaches: "
        f"{sorted(licensing - set(seen))}; a state reached that does not "
        f"license: {sorted(set(seen) - licensing)}")


def test_publication_a_resolved_route_also_licenses_the_audit(tmp_path):
    """The other half: no declaration at all, but --project resolves the route.
    The stance is then NOT_DECLARED_ON_CHIP_PATH, candidates are UNDETERMINED
    rather than ELIGIBLE, and the clause has nothing to refuse."""
    d = _campaign(tmp_path)
    _rc, man = _run_campaign(d, "--project", str(chip_tree(tmp_path / "chip")))
    assert man["toolchain"]["feasibility_eco_state"] != F.ECO_NOT_DECLARED
    codes = [f["code"] for f in S.audit_manifest(man)]
    assert "ELIGIBLE_ON_AN_UNDECLARED_ECO_STANCE" not in codes, codes


def test_publication_negative_control_the_clause_is_what_refuses(tmp_path):
    """Remove the clause from the SOURCE; the same manifest audits clean.

    Without this the assertions above could be passing because of
    ELIGIBLE_ON_A_PARTIAL_VECTOR or any other clause.
    """
    d = _campaign(tmp_path)
    _rc, man = _run_campaign(d)
    assert "ELIGIBLE_ON_AN_UNDECLARED_ECO_STANCE" in \
        [f["code"] for f in S.audit_manifest(man)]

    path = pathlib.Path(S.__file__)
    src = path.read_text(encoding="utf-8")
    arm = '    if tc.get("feasibility_eco_state") == "NOT_DECLARED":'
    assert src.count(arm) == 1, "the control is pinned to this arm's exact text"
    # `_ppa/search.py` uses relative imports, so it cannot be exec'd as a
    # standalone module: it is loaded INSIDE the `_ppa` package, under a
    # distinct name, so `from . import ...` resolves the way it does normally.
    name = "_ppa._search_without_the_eco_stance_clause"
    mod = types.ModuleType(name)
    mod.__file__ = str(path)
    mod.__package__ = "_ppa"
    sys.modules[name] = mod
    try:
        exec(compile(src.replace(arm, '    if False:'), str(path), "exec"),
             mod.__dict__)
    finally:
        sys.modules.pop(name, None)
    codes = [f["code"] for f in mod.audit_manifest(man)]
    assert "ELIGIBLE_ON_AN_UNDECLARED_ECO_STANCE" not in codes
    assert codes == [], (
        "with the clause removed the manifest STILL does not audit clean, so "
        f"the refusal measured above is not coming from it: {codes}")


# ---------------------------------------------------------------------------
# THE FINDING, THROUGH THE SHIPPED CLI, ON THE SHIPPED CAMPAIGN
# ---------------------------------------------------------------------------
# Everything else here builds its own inputs. This runs `ppa_feasibility_check`
# -- unmodified, as a subprocess -- over two candidate sets committed in this
# repo, and compares what it says about the arm that KEPT all ten spare cells
# against the arm that DELETED all ten:
#
#     trial  spares in its own plan   eco_readiness   candidate verdict
#     z23              10             NOT_APPLICABLE  UNDETERMINED
#     p04               0             NOT_APPLICABLE  UNDETERMINED
#
# Identical. Nothing a reader of that output could use to tell them apart.
#
# (Both are UNDETERMINED overall for an unrelated reason -- `em` and
# `equivalence` are unmeasured in these sets, which is the finding of
# `ppa-gate-audit/RESULT.md`, not of this file. The row below asserts the ECO
# axis specifically, so it cannot pass or fail on that account.)
def test_shipped_cli_cannot_tell_the_kept_arm_from_the_deleted_arm():
    """The whole audit in one assertion, with nothing authored by a test.

    Skipped, never silently passed, when the campaign tree is absent.
    """
    import pytest
    trials = _campaign_trials()
    if not trials.is_dir():
        pytest.skip("the cross-layer campaign records are not in this tree; "
                    "NOT OBSERVED")

    seen = {}
    for trial in ("z23", "p04"):
        cands = trials / trial / "candidates.json"
        plan = trials / trial / "spare_cells.json"
        if not (cands.is_file() and plan.is_file()):
            pytest.skip(f"{trial} is not fully present in this tree")
        p = subprocess.run(
            [sys.executable, str(CHECK), "--candidates", str(cands)],
            capture_output=True, text=True)
        assert p.returncode in (F.RC_PASS, F.RC_FAIL, F.RC_UNDETERMINED), p.stderr
        # The axis row, parsed from the CLI's own stdout. ANCHORED ON THE TRIAL
        # ID, not on the first occurrence of the marker: the verdict line's
        # shape is not this test's to rely on, and it has already moved once --
        # it gained a `<candidates path>: ` prefix and a block of per-axis
        # MISSING detail lines. Taking the first match would silently start
        # reading a different candidate's row the day a run carries two.
        rows = [ln for ln in p.stdout.splitlines()
                if "[eco_readiness " in ln and f"{trial}:" in ln]
        assert len(rows) == 1, (
            f"expected exactly one eco_readiness verdict row naming {trial}, "
            f"got {len(rows)}; the CLI's output shape moved and this row is "
            f"no longer reading what it thinks:\n{p.stdout}")
        status = rows[0].split("[eco_readiness ", 1)[1].split("]", 1)[0].strip()
        spares = json.loads(plan.read_text(encoding="utf-8"))["count"]
        seen[trial] = (spares, status)

    assert seen["z23"][0] == 10, seen        # kept every declared spare
    assert seen["p04"][0] == 0, seen         # deleted every one
    assert seen["z23"][1] == seen["p04"][1] == "NOT_APPLICABLE", (
        f"the shipped CLI now distinguishes these two arms: {seen}. That is "
        f"the gap this file measures being CLOSED -- re-measure the report "
        f"rather than trusting it.")


# ---------------------------------------------------------------------------
# THE GATE'S OWN DECLARATION STILL DESCRIBES A NINE-AXIS WORLD
# ---------------------------------------------------------------------------
# `tools/ci/repo_hygiene_gates.sh` wires "PPA promotion feasibility" at the 21
# real candidate sets, and its exemption text explains the rc=2 as a CONTENT
# verdict:
#
#   "seven of nine feasibility axes are SATISFIED on every one and two
#    (em, equivalence) carry no measurement at all"
#
# Seven plus two is nine. The axis table has TEN. The tenth -- eco_readiness --
# is NOT_APPLICABLE on all 21 and is counted in neither half, so the gate's
# stated reasoning is complete about a table that no longer exists.
#
# This is the same shape as everything else in this file, one level up: a
# declaration that reads as total while a whole axis passes underneath it
# uncounted. It is a DISCLOSURE, not a gate -- the rows below fail if the
# numbers drift so somebody re-measures, and say which way.
def _hygiene_script():
    return _repo_root() / "tools" / "ci" / "repo_hygiene_gates.sh"


def test_the_hygiene_declaration_and_the_axis_table_disagree_on_the_count():
    """The axis table grew a tenth entry; the gate's exemption text did not."""
    import pytest, re
    script = _hygiene_script()
    if not script.is_file():
        pytest.skip(f"{script} is not in this checkout; NOT OBSERVED")
    text = script.read_text(encoding="utf-8")
    if "PPA promotion feasibility" not in text:
        pytest.skip("the promotion-feasibility gate is not wired here")

    assert len(F.DEFAULT_AXES) == 10, [a.name for a in F.DEFAULT_AXES]
    assert F.ECO_AXIS == F.DEFAULT_AXES[-1].name

    # The declaration's own arithmetic, read out of it rather than retyped.
    m = re.search(r"(\w+) of (\w+) feasibility axes are SATISFIED", text)
    assert m, ("the promotion-feasibility exemption no longer states its axis "
               "arithmetic; re-measure rather than trusting this row")
    words = {"seven": 7, "eight": 8, "nine": 9, "ten": 10}
    satisfied, of = words.get(m.group(1)), words.get(m.group(2))
    assert (satisfied, of) == (7, 9), (
        f"the declaration now reads '{m.group(1)} of {m.group(2)}'; it was "
        f"'seven of nine' when this was measured, so the gap may be closed")
    assert of < len(F.DEFAULT_AXES), (
        f"the declaration counts {of} axes and the table has "
        f"{len(F.DEFAULT_AXES)}")


def test_the_axis_the_declaration_omits_is_not_applicable_on_every_candidate():
    """And it is omitted while being uniformly inert, which is why nothing
    noticed: on all 21 real candidate sets the tenth axis reads
    NOT_APPLICABLE, so it never appears in a failure anybody reads."""
    import pytest
    trials = _campaign_trials()
    if not trials.is_dir():
        pytest.skip("the cross-layer campaign records are not in this tree; "
                    "NOT OBSERVED")
    sets = sorted(trials.glob("*/candidates.json"))
    if not sets:
        pytest.skip("no candidate sets in this tree; NOT OBSERVED")

    seen = []
    for cands in sets:
        p = subprocess.run(
            [sys.executable, str(CHECK), "--candidates", str(cands)],
            capture_output=True, text=True)
        rows = [ln for ln in p.stdout.splitlines() if "[eco_readiness " in ln]
        assert rows, (cands, p.stdout)
        for line in rows:
            seen.append(line.split("[eco_readiness ", 1)[1]
                        .split("]", 1)[0].strip())
    assert len(seen) >= len(sets), (len(seen), len(sets))
    assert set(seen) == {"NOT_APPLICABLE"}, (
        f"the tenth axis now reports {sorted(set(seen))} on the campaign; it "
        f"was uniformly NOT_APPLICABLE when this was measured")


def test_the_repo_root_anchor_fails_loudly_when_it_goes_stale(monkeypatch,
                                                              tmp_path):
    """The guard, SHOWN TO FIRE. A check that has only ever run against a
    correct tree has not been shown to detect anything.

    Point the anchor at a directory that is not a repo root and assert
    `_repo_root()` RAISES rather than returning a path the record-reading rows
    would then quietly skip on.
    """
    import pytest
    # sanity: it does not fire on the real tree
    assert _repo_root().is_dir()

    fake = tmp_path / "not" / "a" / "repo" / "root" / "deep" / "enough"
    fake.mkdir(parents=True)
    monkeypatch.setattr(sys.modules[__name__], "_PROGRAMS", fake)
    with pytest.raises(AssertionError) as exc:
        _repo_root()
    assert _ROOT_WITNESS in str(exc.value)
    assert "stale" in str(exc.value)

    # and the distinction it protects: a root that DOES carry the witness but
    # has no records is a real absence, and must NOT raise -- otherwise the
    # guard has replaced one conflation with another.
    real_shape = tmp_path / "empty_repo"
    (real_shape / _ROOT_WITNESS).mkdir(parents=True)
    deep = real_shape / "a" / "b" / "c" / "d"
    deep.mkdir(parents=True)
    monkeypatch.setattr(sys.modules[__name__], "_PROGRAMS", deep)
    assert _repo_root() == real_shape
    assert not (_repo_root() / "ppa-crosslayer").exists()
