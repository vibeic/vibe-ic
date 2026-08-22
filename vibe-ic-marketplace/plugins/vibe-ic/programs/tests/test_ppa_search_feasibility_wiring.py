#!/usr/bin/env python3
"""F-12 — the search may reach the real feasibility gate, and a STUB REASON
may not be published as a fact.

THE MEASURED DEFECT
===================
`ppa_search_run.py:243` was `ledger.evaluate_feasibility(None)` with no flag
that could reach `_ppa/feasibility.py`, so every manifest a downloaded plugin
could produce marked every candidate UNDETERMINED and published an EMPTY Pareto
frontier. And the stub's reason -- a string literal in the source -- asserted
that `_ppa/feasibility.py` "has not landed". It landed at v1.11.26 and the
search landed at v1.11.29, three commits later. Sixty published manifests
carried that sentence about a module that was right there.

The second half is the one this file spends the most tests on. A stub that
names a condition must CHECK that condition at the moment it speaks, or it must
not name one -- because a hard-wired excuse that outlives its cause is how a
false sentence gets into a published record and stays there.

FOUR ARMS, AS THE CONTRACT REQUIRES
===================================
    positive   the shipped gate makes a clean candidate ELIGIBLE and it
               reaches the frontier
    negative   it makes a DRC-violating candidate INELIGIBLE and names the
               axis -- so "the gate refuses everything" cannot pass for "the
               gate discriminates"
    vacuous    a policy that could not be read is rc=2 with a marker; it is
               NEVER a silent fall-through to the stub, because that would
               publish a stub verdict under a manifest saying a policy applied
    mutation   see RESULT.md; each fix names the test that reddens when it is
               reverted

chip-AGNOSTIC: synthetic records and declared policy only.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import ppa_search_run as R                      # noqa: E402
from _ppa import feasibility as F               # noqa: E402
from _ppa import search as S                    # noqa: E402
from _ppa import search_feasibility as SF       # noqa: E402

SPACE = {
    "program": "crosslayer_search_space",
    "levers": [{"lever": "state_encoding", "admitted": True, "status": "FREE",
                "domain": "binary | gray"}],
}
STAGE = "post_route_extracted"
VIEW = {"stage": STAGE}


def _rec(metric, value, unit="count", status="MEASURED", **scope):
    sc = {"stage": STAGE}
    sc.update(scope)
    return {"schema": "vibeic.ppa.metric.v1", "metric": metric,
            "status": status, "value": value, "unit": unit, "scope": sc,
            "source": {"path": "reports/signoff.rpt",
                       "sha256": "sha256:" + "a" * 64}}


def _nine_clean(area):
    """A full nine-axis clean evidence set. Every axis really is measured."""
    return [
        _rec("area.design_report.um2", area, "um^2"),
        _rec("timing.setup.wns_ns", 0.50, "ns"),
        _rec("timing.hold.wns_ns", 0.10, "ns"),
        _rec("timing.drv.violations", 0),
        _rec("physical.drc.violations", 0),
        _rec("physical.lvs.verdict", "MATCH", ""),
        _rec("physical.antenna.violations", 0),
        _rec("power.ir.violations", 0),
        _rec("reliability.em.violations", 0),
        _rec("equivalence.verdict", "PROVEN", ""),
    ]


def _one_axis_dirty(area, metric="physical.drc.violations", value=7):
    """The SAME evidence set with ONE field changed. That is what makes the
    negative arm a discriminator rather than a second way of refusing."""
    out = _nine_clean(area)
    for r in out:
        if r["metric"] == metric:
            r["value"] = value
    return out


def _trial(enc, metrics):
    return {"knobs": {"state_encoding": enc}, "state": "COMPLETED",
            "completed_stage": STAGE, "metrics": metrics,
            "cost": {"cpu_seconds": 60.0, "wall_seconds": 30.0,
                     "peak_rss_mb": 512.0}}


@pytest.fixture
def run_dir(tmp_path):
    (tmp_path / "space.json").write_text(json.dumps(SPACE))
    (tmp_path / "trials.json").write_text(json.dumps([
        _trial("binary", _nine_clean(1000.0)),
        _trial("gray", _one_axis_dirty(900.0)),
    ]))
    # The policy DECLARES that this design needs no spare population, rather
    # than being silent about it. The neighbouring test below already describes
    # it that way -- "the one term this fixture's policy declares no requirement
    # for" -- and until now that sentence was aspirational: the document said
    # nothing at all, which is a different fact and one `audit_manifest` now
    # separates (ELIGIBLE_ON_AN_UNDECLARED_ECO_STANCE). `required: false` is a
    # decision, so the term still reads NOT_APPLICABLE and every verdict in this
    # file is unchanged; what changes is that the fixture now means what it says.
    (tmp_path / "policy.json").write_text(
        json.dumps({"required_views": [VIEW],
                    "eco_readiness": {"required": False}}))
    return tmp_path


def _build(d, *extra, out="manifest.json"):
    rc = R.main([str(d / "space.json"), "--trials", str(d / "trials.json"),
                 "--max-trials", "2", "--max-full-pnr-trials", "2",
                 "--json", str(d / out), *extra])
    man = json.loads((d / out).read_text()) if (d / out).exists() else {}
    return rc, man


# ---------------------------------------------------------------------------
# the stub reason -- the half that matters more
# ---------------------------------------------------------------------------
def test_the_stub_reason_does_not_claim_an_unlanded_module_that_is_present():
    """THE F-12 REGRESSION, stated directly.

    On this tree `_ppa/feasibility.py` is present, so no reason the stub emits
    may contain the words that assert it has not landed. Reverting
    `stub_feasibility` to a literal reddens exactly this test.
    """
    assert S.feasibility_module_has_landed(), (
        "_ppa/feasibility.py is not importable from this tree; the rest of "
        "this file measures the wrong world")
    reason = S.stub_feasibility(S.Candidate({})).reason
    assert S.unlanded_claims_contradicted_by_tree(reason) == []
    assert S.FEASIBILITY_MODULE_REL + " " + S.UNLANDED_CLAIM_PHRASE \
        not in reason


def test_the_stub_reason_still_names_the_condition_when_it_actually_holds(
        monkeypatch):
    """The fix is not "delete the sentence". A stub standing in for something
    genuinely absent must still say so -- otherwise the honest case loses the
    only diagnosis it had."""
    monkeypatch.setattr(S, "feasibility_module_has_landed", lambda: False)
    reason = S.stub_feasibility(S.Candidate({})).reason
    assert S.UNLANDED_CLAIM_PHRASE in reason
    assert S.FEASIBILITY_MODULE_REL in reason


def test_the_stub_verdict_is_undetermined_in_both_worlds(monkeypatch):
    """Whatever the reason says, a stub never manufactures eligibility."""
    for landed in (True, False):
        monkeypatch.setattr(S, "feasibility_module_has_landed",
                            lambda landed=landed: landed)
        v = S.stub_feasibility(S.Candidate({}))
        assert v.verdict == S.FEAS_UNDETERMINED
        assert set(v.terms.values()) == {"NOT_CHECKED"}
        assert sorted(v.terms) == sorted(S.FEASIBILITY_TERMS)


# ---------------------------------------------------------------------------
# the audit clause -- the half that applies to a manifest somebody published
# ---------------------------------------------------------------------------
def test_the_sixty_manifests_are_rc1_with_a_named_finding(run_dir, capsys):
    """The literal record that shipped: a stub note asserting the module has
    not landed, audited on a tree where it is right there."""
    rc, man = _build(run_dir)
    assert rc == R.RC_PASS
    false_note = ("feasibility lane not wired: _ppa/feasibility.py has not "
                  "landed, so no setup/hold/DRV/DRC/LVS/antenna/IR/EM/"
                  "equivalence evidence was read")
    man["toolchain"]["feasibility_note"] = false_note
    p = run_dir / "false.json"
    p.write_text(json.dumps(man))
    capsys.readouterr()
    rc = R.main(["--verify", str(p)])
    err = capsys.readouterr().err
    assert rc == R.RC_REFUSED
    assert S.AUDIT_STUB_REASON_FALSE in err
    assert "toolchain.feasibility_note" in err


def test_a_false_claim_in_a_candidate_reason_is_also_caught(run_dir, capsys):
    rc, man = _build(run_dir)
    assert rc == R.RC_PASS
    man["candidates"][0]["feasibility"]["reason"] = \
        "_ppa/feasibility.py has not landed, so nothing was read"
    p = run_dir / "false2.json"
    p.write_text(json.dumps(man))
    capsys.readouterr()
    assert R.main(["--verify", str(p)]) == R.RC_REFUSED
    assert "candidates[0].feasibility.reason" in capsys.readouterr().err


def test_a_claim_about_a_module_that_really_is_absent_is_not_a_finding(
        run_dir, capsys):
    """THE FALSE-POSITIVE ARM. The clause fires on a claim the tree
    CONTRADICTS, never on the mere shape of the sentence -- otherwise a
    manifest published honestly against a tree where the claim was true would
    redden here, and the clause would be punishing the wrong record."""
    rc, man = _build(run_dir)
    assert rc == R.RC_PASS
    man["toolchain"]["feasibility_note"] = \
        "_ppa/no_such_module_at_all.py has not landed, so nothing was read"
    p = run_dir / "absent.json"
    p.write_text(json.dumps(man))
    capsys.readouterr()
    assert R.main(["--verify", str(p)]) == R.RC_PASS


def test_the_manifest_this_program_builds_today_verifies_clean(run_dir):
    """Both lanes. Neither may publish a sentence its own audit refuses."""
    for extra, out in (((), "stub.json"),
                       (("--feasibility-policy",
                         str(run_dir / "policy.json")), "real.json")):
        rc, _ = _build(run_dir, *extra, out=out)
        assert rc == R.RC_PASS
        assert R.main(["--verify", str(run_dir / out)]) == R.RC_PASS


# ---------------------------------------------------------------------------
# positive -- the gate is reachable and it admits
# ---------------------------------------------------------------------------
def test_the_shipped_gate_makes_a_clean_candidate_eligible(run_dir):
    """THE F-12 UNBLOCK. Before the fix this frontier was empty on every input
    a downloaded plugin could construct."""
    rc, man = _build(run_dir, "--feasibility-policy",
                     str(run_dir / "policy.json"))
    assert rc == R.RC_PASS
    verdicts = {c["knobs"]["state_encoding"]: c["feasibility"]["verdict"]
                for c in man["candidates"]}
    assert verdicts["binary"] == S.FEAS_ELIGIBLE
    assert man["frontier_input"]["included_count"] == 1
    assert man["frontier_input"]["frontier_stage"] == STAGE


def test_every_term_is_published_and_none_is_silently_absent(run_dir):
    """`audit_manifest` refuses an ELIGIBLE candidate whose vector is partial.
    The translation must therefore fill every term, and this asserts it does
    rather than trusting that the two vocabularies line up.

    `eco_readiness` is the one term this fixture's policy declares no
    requirement for, so it reads NOT_APPLICABLE -- which is what
    `audit_manifest` accepts beside PASS, and is NOT the same as a missing
    row."""
    _, man = _build(run_dir, "--feasibility-policy",
                    str(run_dir / "policy.json"))
    clean = [c for c in man["candidates"]
             if c["knobs"]["state_encoding"] == "binary"][0]
    expect = {t: "PASS" for t in S.FEASIBILITY_TERMS}
    expect["eco_readiness"] = "NOT_APPLICABLE"
    assert clean["feasibility"]["terms"] == expect
    assert clean["feasibility"]["verdict"] == S.FEAS_ELIGIBLE


def test_the_manifest_records_the_policy_by_digest_not_only_by_path(run_dir):
    """Two runs citing `policy.json` may have adjudicated against two different
    documents; a reader comparing them needs the bytes, not the name."""
    _, man = _build(run_dir, "--feasibility-policy",
                    str(run_dir / "policy.json"))
    tc = man["toolchain"]
    assert tc["feasibility_source"] == SF.SOURCE_SHIPPED
    assert tc["feasibility_policy_digest"].startswith("sha256:")
    assert tc["feasibility_required_views"] == 1
    assert tc["feasibility_waivers_supplied"] is False


# ---------------------------------------------------------------------------
# negative -- and it refuses, for a NAMED reason, on the SAME fixture
# ---------------------------------------------------------------------------
def test_a_violating_candidate_is_ineligible_and_the_axis_is_named(run_dir):
    _, man = _build(run_dir, "--feasibility-policy",
                    str(run_dir / "policy.json"))
    dirty = [c for c in man["candidates"]
             if c["knobs"]["state_encoding"] == "gray"][0]
    assert dirty["feasibility"]["verdict"] == S.FEAS_INELIGIBLE
    assert dirty["feasibility"]["terms"]["drc"] == "FAIL"
    codes = {e["code"] for e in man["frontier_input"]["excluded"]}
    assert S.EXCL_NOT_ELIGIBLE in codes
    assert S.EXCL_UNDETERMINED not in codes, (
        "'we checked and it fails' and 'we never checked' must never share a "
        "code")


@pytest.mark.parametrize("metric,value", [
    ("timing.setup.wns_ns", -0.10),
    ("physical.lvs.verdict", "MISMATCH"),
    ("physical.antenna.violations", 3),
    ("equivalence.verdict", "NOT_EQUIVALENT"),
])
def test_one_dirty_axis_anywhere_costs_eligibility(run_dir, metric, value):
    """Nine axes, and any one of them refuses. A gate that only ever noticed
    DRC would pass this file's main negative arm and still be the ORFS
    `num_drc` mistake."""
    (run_dir / "trials.json").write_text(json.dumps(
        [_trial("binary", _one_axis_dirty(1000.0, metric, value))]))
    rc = R.main([str(run_dir / "space.json"), "--trials",
                 str(run_dir / "trials.json"), "--max-trials", "1",
                 "--max-full-pnr-trials", "1", "--feasibility-policy",
                 str(run_dir / "policy.json"),
                 "--json", str(run_dir / "m.json")])
    assert rc == R.RC_PASS
    man = json.loads((run_dir / "m.json").read_text())
    assert man["candidates"][0]["feasibility"]["verdict"] == S.FEAS_INELIGIBLE
    assert man["frontier_input"]["included_count"] == 0


# ---------------------------------------------------------------------------
# vacuous -- the arm that is not paperwork
# ---------------------------------------------------------------------------
def test_an_absent_policy_is_rc2_and_never_a_silent_stub(run_dir, capsys):
    rc = R.main([str(run_dir / "space.json"), "--trials",
                 str(run_dir / "trials.json"), "--max-trials", "2",
                 "--max-full-pnr-trials", "2",
                 "--feasibility-policy", str(run_dir / "nope.json"),
                 "--json", str(run_dir / "m.json")])
    err = capsys.readouterr().err
    assert rc == R.RC_UNDETERMINED
    assert R.MARK_CANNOT_CHECK in err
    assert not (run_dir / "m.json").exists() or \
        json.loads((run_dir / "m.json").read_text()).get("undetermined")


@pytest.mark.parametrize("body,label", [
    ("", "empty"),
    ("{ not json", "unparseable"),
    ("[1, 2, 3]", "not an object"),
])
def test_a_policy_that_is_not_a_policy_is_rc2(run_dir, capsys, body, label):
    p = run_dir / "bad.json"
    p.write_text(body)
    rc = R.main([str(run_dir / "space.json"), "--trials",
                 str(run_dir / "trials.json"), "--max-trials", "2",
                 "--max-full-pnr-trials", "2",
                 "--feasibility-policy", str(p)])
    assert rc == R.RC_UNDETERMINED, label
    assert R.MARK_CANNOT_CHECK in capsys.readouterr().err


def test_a_policy_declaring_no_view_adjudicates_nothing_and_says_so(run_dir):
    """An undeclared view set is not "whatever was measured is enough". The
    gate returns UNDETERMINED and the frontier stays empty -- a policy file
    that exists is not a policy that decided anything."""
    (run_dir / "empty_policy.json").write_text(json.dumps({}))
    rc, man = _build(run_dir, "--feasibility-policy",
                     str(run_dir / "empty_policy.json"), out="e.json")
    assert rc == R.RC_PASS
    assert all(c["feasibility"]["verdict"] == S.FEAS_UNDETERMINED
               for c in man["candidates"])
    assert man["frontier_input"]["included_count"] == 0


def test_verify_refuses_a_feasibility_policy_as_a_bad_invocation(run_dir):
    """`--verify` audits verdicts that already exist; re-adjudicating them
    under audit would let the auditor change the thing it is auditing."""
    assert R.main(["--verify", str(run_dir / "space.json"),
                   "--feasibility-policy", str(run_dir / "policy.json")]) \
        == R.RC_BAD_INVOCATION


# ---------------------------------------------------------------------------
# the default is unchanged, and the bridge cannot drift
# ---------------------------------------------------------------------------
def test_without_the_flag_the_stub_still_runs_and_the_frontier_is_empty(
        run_dir):
    rc, man = _build(run_dir, out="stub2.json")
    assert rc == R.RC_PASS
    assert man["toolchain"]["feasibility_source"] == "STUB"
    assert man["frontier_input"]["included_count"] == 0
    assert all(c["feasibility"]["verdict"] == S.FEAS_UNDETERMINED
               for c in man["candidates"])


def test_the_gate_axes_are_exactly_the_search_terms():
    """Two tuples in two files. Their drifting apart is silent: a published
    term no axis fills reads NOT_CHECKED forever, and an axis with no term
    vanishes from the vector with nothing saying so."""
    assert SF._axis_names_match_terms(), (
        [a.name for a in F.DEFAULT_AXES], list(S.FEASIBILITY_TERMS))


def test_no_translation_arm_can_manufacture_eligibility():
    """The unknown arm of both maps must fall to the refusing value. A default
    of ELIGIBLE / PASS anywhere here is the whole defect class in one line."""
    assert SF.VERDICT_MAP.get("SOMETHING_NEW", S.FEAS_UNDETERMINED) == \
        S.FEAS_UNDETERMINED
    assert S.FEAS_ELIGIBLE not in \
        {v for k, v in SF.VERDICT_MAP.items() if k != F.FEASIBLE}
    assert SF.TERM_MAP.get("SOMETHING_NEW", "NOT_CHECKED") == "NOT_CHECKED"
    assert "PASS" not in {v for k, v in SF.TERM_MAP.items()
                          if k != F.AXIS_SATISFIED}


def test_the_bridge_hands_the_gate_records_and_nothing_else(run_dir):
    """No waiver travels this bridge (see the module docstring): a waiver is a
    named owner accepting ONE violation on ONE run, and a point in a search
    space is not a run."""
    seen = {}

    def _spy(candidate, policy):
        seen.update(candidate)
        return F.FeasibilityResult("x", F.UNDETERMINED, (), ())

    real = F.promotion_verdict
    try:
        SF.F.promotion_verdict = _spy
        fn = SF.feasibility_fn(F.FeasibilityPolicy(required_views=(VIEW,)))
        fn(S.Candidate({"a": 1}, metrics=_nine_clean(1.0)))
    finally:
        SF.F.promotion_verdict = real
    assert set(seen) == {"candidate_id", "metrics"}
    assert "waivers" not in seen and "knobs" not in seen
