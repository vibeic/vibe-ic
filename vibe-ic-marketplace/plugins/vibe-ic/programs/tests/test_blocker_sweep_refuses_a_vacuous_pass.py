"""A sweep that entered no rule is NOT_CHECKED, never PASS.

THE MEASUREMENT THIS IS WRITTEN FROM. `blocker_classification_check --dir
benchmark-data` on 221689eb:

    blocker_classification_check: 5 compliance report(s) checked, 5 predate the
    blocker contract (no `blockers` key — reported, not failed), 8293 JSON
    file(s) were not compliance reports
    blocker_classification_check: PASS
    EXIT=0

Every one of the five took `check_report`'s `blockers is None` early return, so
not one of the guard's five rules ran — and the program answered with the same
word it uses for a sweep that entered the guard and found nothing. That is the
state PR #858's review already measured and named ("a green light wired to
nothing"), left in the exit code where a CI lane would consume it.

These tests pin the three-way outcome by RETURN VALUE and EMITTED JSON:
exercised>0 and clean -> 0/PASS, a violation -> 1/FAIL wherever it sits, and
nothing exercised -> 2/NOT_CHECKED with the count that says so.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_GUARD = importlib.import_module("blocker_classification_check")


def _pre_contract_report(step_id: int) -> dict:
    """A report older than the `blockers` contract — the shipped corpus shape."""
    return {"overall": "FAIL",
            "steps": [{"id": step_id, "name": f"step {step_id}",
                       "status": "FAIL"}]}


def _contract_report(step_id: int, classification: str, basis: str) -> dict:
    counts = {"PLUGIN_DEFECT": 0, "DESIGN_FACT": 0,
              "MISSING_CAPABILITY": 0, "UNCLASSIFIED": 0}
    counts[classification] = counts.get(classification, 0) + 1
    return {
        "overall": "FAIL",
        "steps": [{"id": step_id, "name": f"step {step_id}", "status": "FAIL",
                   "reasons": ["program failed: g ."]}],
        "blockers": [{
            "step_id": step_id, "step_name": f"step {step_id}", "stage": "s",
            "status": "FAIL", "classification": classification,
            "basis": basis, "measures": "m", "observed": "o",
            "derived_from": [], "sub_blockers": None,
        }],
        "blocker_class_counts": counts,
        "blocker_list_error": "",
    }


def _sweep(tmp_path: Path, docs: dict):
    tree = tmp_path / "reports"
    tree.mkdir()
    for name, doc in docs.items():
        (tree / name).write_text(json.dumps(doc))
    out = tmp_path / "sweep.json"
    rc = _GUARD.main(["--dir", str(tree), "--json", str(out)])
    return rc, json.loads(out.read_text())


def test_a_corpus_of_only_pre_contract_reports_is_not_a_pass(tmp_path):
    """The shipped state, reproduced: reports exist, none carries the contract.

    rc 2 is this repo's vacuous-exit convention, which `_gate_dispatch.sh`
    records as NOT_CHECKED and refuses to fold into `passed`.
    """
    rc, res = _sweep(tmp_path, {"old1.json": _pre_contract_report(1),
                                "old2.json": _pre_contract_report(2)})
    assert rc == 2
    assert res["verdict"] == "NOT_CHECKED"
    assert res["reports_checked"] == 2
    assert res["pre_contract_reports"] == 2
    assert res["reports_exercising_the_contract"] == 0


def test_a_tree_with_no_compliance_report_at_all_is_not_a_pass(tmp_path):
    """The emptier half of the same hole: JSON everywhere, none of it ours."""
    rc, res = _sweep(tmp_path, {"unrelated.json": {"hello": "world"}})
    assert rc == 2
    assert res["verdict"] == "NOT_CHECKED"
    assert res["reports_checked"] == 0
    assert res["reports_exercising_the_contract"] == 0
    assert res["non_report_json_skipped"] == 1


def test_one_contract_carrying_report_makes_the_sweep_a_real_pass(tmp_path):
    """The other direction — the verdict must still be reachable.

    A guard that could only ever answer NOT_CHECKED would be no better than one
    that could only ever answer PASS.
    """
    rc, res = _sweep(tmp_path, {
        "old.json": _pre_contract_report(1),
        "new.json": _contract_report(7, "DESIGN_FACT", "gate-reached-verdict")})
    assert rc == 0
    assert res["verdict"] == "PASS"
    assert res["reports_checked"] == 2
    assert res["pre_contract_reports"] == 1
    assert res["reports_exercising_the_contract"] == 1


def test_a_violation_still_wins_over_the_vacuity_verdict(tmp_path):
    """A FAIL is a FAIL even in a corpus that is mostly pre-contract.

    The ordering matters: `exercised` is computed over the whole sweep, and a
    guard that reported NOT_CHECKED while holding a real violation would be the
    original defect with a new name.
    """
    rc, res = _sweep(tmp_path, {
        "old.json": _pre_contract_report(1),
        "bad.json": _contract_report(9, "DESIGN_FACT", "no-rule-matched")})
    assert rc == 1
    assert res["verdict"] == "FAIL"
    assert res["reports_exercising_the_contract"] == 1
    assert any("bad.json" in f["report"] for f in res["failures"])
