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

from _ppa import feasibility as F               # noqa: E402

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




# ---------------------------------------------------------------------------
# the stub reason -- the half that matters more
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# the audit clause -- the half that applies to a manifest somebody published
# ---------------------------------------------------------------------------
def test_the_sixty_manifests_are_rc1_with_a_named_finding(run_dir, capsys):
    """The literal record that shipped: a stub note asserting the module has
    not landed, audited on a tree where it is right there."""
    false_note = ("feasibility lane not wired: _ppa/feasibility.py has not "
                  "landed, so no setup/hold/DRV/DRC/LVS/antenna/IR/EM/"
                  "equivalence evidence was read")
    p = run_dir / "false.json"
    capsys.readouterr()
    err = capsys.readouterr().err
    assert "toolchain.feasibility_note" in err


def test_a_false_claim_in_a_candidate_reason_is_also_caught(run_dir, capsys):
    p = run_dir / "false2.json"
    capsys.readouterr()
    assert "candidates[0].feasibility.reason" in capsys.readouterr().err






# ---------------------------------------------------------------------------
# positive -- the gate is reachable and it admits
# ---------------------------------------------------------------------------






# ---------------------------------------------------------------------------
# negative -- and it refuses, for a NAMED reason, on the SAME fixture
# ---------------------------------------------------------------------------


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
    man = json.loads((run_dir / "m.json").read_text())
    assert man["frontier_input"]["included_count"] == 0


# ---------------------------------------------------------------------------
# vacuous -- the arm that is not paperwork
# ---------------------------------------------------------------------------
def test_an_absent_policy_is_rc2_and_never_a_silent_stub(run_dir, capsys):
    err = capsys.readouterr().err
    assert not (run_dir / "m.json").exists() or \
        json.loads((run_dir / "m.json").read_text()).get("undetermined")








# ---------------------------------------------------------------------------
# the default is unchanged, and the bridge cannot drift
# ---------------------------------------------------------------------------






def test_the_bridge_hands_the_gate_records_and_nothing_else(run_dir):
    """No waiver travels this bridge (see the module docstring): a waiver is a
    named owner accepting ONE violation on ONE run, and a point in a search
    space is not a run."""
    seen = {}

    def _spy(candidate, policy):
        seen.update(candidate)
        return F.FeasibilityResult("x", F.UNDETERMINED, (), ())

    real = F.promotion_verdict
    assert set(seen) == {"candidate_id", "metrics"}
    assert "waivers" not in seen and "knobs" not in seen
