"""The sweep must REACH its guard, not stop at the pre-contract early return.

THE MEASUREMENT THIS IS WRITTEN FROM (review of PR #858). The shipped corpus
sweep ran `blocker_classification_check --dir` over 5 committed reports and
exited 0 — but every one of them PREDATES the blocker contract, so
`check_report` returned at its `blockers is None` early return and none of the
guard's five rules executed. Exit 0 was correct on that state and proved
NOTHING about detection: a sweep whose guard is never entered is a green light
wired to nothing.

These tests build a sweep tree that CARRIES the contract, so the guard's
decision points are actually entered, and show it firing in BOTH directions —
a clean contract-carrying report passes, a seeded violation in the same sweep
turns the sweep red and is named — and that a pre-contract report in the tree
is still counted as pre-contract rather than silently dropped.

This module imports only `blocker_classification_check`, which this change
introduces; against the pre-change tree it fails at COLLECTION, which proves
the module exists, not the behaviour. Its job is the complementary one the PR's
own bidirectional control cannot do: prove the SWEEP path enters the guard body
and returns a verdict off it.
"""
from __future__ import annotations

import importlib
import json

_GUARD = importlib.import_module("blocker_classification_check")


def _contract_report(step_id, classification, basis):
    """A minimal but CONTRACT-CARRYING `flow_compliance_check --json` report:
    it has the `blockers` key, so the guard cannot take its pre-contract early
    return on it."""
    blocker = {
        "step_id": step_id, "step_name": f"step {step_id}", "stage": "s",
        "status": "FAIL", "classification": classification, "basis": basis,
        "measures": "m", "observed": "o", "derived_from": [],
        "sub_blockers": None,
    }
    counts = {"PLUGIN_DEFECT": 0, "DESIGN_FACT": 0,
              "MISSING_CAPABILITY": 0, "UNCLASSIFIED": 0}
    counts[classification] = counts.get(classification, 0) + 1
    return {
        "overall": "FAIL",
        "steps": [{"id": step_id, "name": f"step {step_id}", "status": "FAIL",
                   "reasons": ["program failed: g ."]}],
        "blockers": [blocker],
        "blocker_class_counts": counts,
        "blocker_list_error": "",
    }


def test_the_sweep_enters_the_guard_body_on_a_contract_carrying_report(tmp_path):
    """A `--dir` sweep over a report that HAS the `blockers` key must count it
    as checked-with-the-contract-present (`pre_contract == 0`) — i.e. the rule
    body ran. On the shipped corpus every report was pre-contract, so the guard
    never reached this state and the exit-0 measured nothing."""
    tree = tmp_path / "reports"
    tree.mkdir()
    (tree / "clean.json").write_text(json.dumps(
        _contract_report(7, "DESIGN_FACT", "gate-reached-verdict")))
    out = tmp_path / "sweep.json"
    rc = _GUARD.main(["--dir", str(tree), "--json", str(out)])
    result = json.loads(out.read_text())
    assert rc == 0
    assert result["reports_checked"] == 1
    assert result["pre_contract_reports"] == 0, (
        "the guard stopped at the pre-contract early return — it never reached "
        "its own rules, which is exactly the vacuous sweep this test exists for")
    assert result["verdict"] == "PASS"


def test_the_sweep_fires_the_guard_on_a_seeded_violation(tmp_path):
    """The other direction: a contract-carrying report with a class the evidence
    does not license (basis `no-rule-matched` on a non-UNCLASSIFIED class) must
    turn the SWEEP red and name the offending report by path. This is the
    guard's decision point being ENTERED and returning a violation — the thing
    the shipped vacuous sweep never demonstrated."""
    tree = tmp_path / "reports"
    tree.mkdir()
    (tree / "clean.json").write_text(json.dumps(
        _contract_report(7, "DESIGN_FACT", "gate-reached-verdict")))
    (tree / "bad.json").write_text(json.dumps(
        _contract_report(9, "DESIGN_FACT", "no-rule-matched")))
    out = tmp_path / "sweep.json"
    rc = _GUARD.main(["--dir", str(tree), "--json", str(out)])
    result = json.loads(out.read_text())
    assert rc == 1
    assert result["verdict"] == "FAIL"
    assert result["reports_checked"] == 2
    offending = {f["report"] for f in result["failures"]}
    assert any("bad.json" in r for r in offending), offending
    assert not any("clean.json" in r for r in offending), (
        "the clean contract report must NOT be flagged — the guard must "
        "discriminate, not fail the whole sweep")


def test_a_pre_contract_report_in_the_sweep_is_counted_not_skipped(tmp_path):
    """A report older than the contract (no `blockers` key) is reported as
    pre-contract and does not fail the sweep — the shipped, correct behaviour,
    kept honest so a corpus of only-old reports reads as 'nothing exercised'
    (checked>0, pre_contract==checked) rather than a false 'all clean'."""
    tree = tmp_path / "reports"
    tree.mkdir()
    (tree / "clean.json").write_text(json.dumps(
        _contract_report(7, "UNCLASSIFIED", "declared-artefact-absent")))
    (tree / "old.json").write_text(json.dumps(
        {"overall": "FAIL",
         "steps": [{"id": 1, "name": "s", "status": "FAIL"}]}))
    out = tmp_path / "sweep.json"
    rc = _GUARD.main(["--dir", str(tree), "--json", str(out)])
    result = json.loads(out.read_text())
    assert rc == 0
    assert result["reports_checked"] == 2
    assert result["pre_contract_reports"] == 1
