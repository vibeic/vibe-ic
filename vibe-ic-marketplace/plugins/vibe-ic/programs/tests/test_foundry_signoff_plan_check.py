#!/usr/bin/env python3
"""Tests for foundry_signoff_plan_check.py"""
from __future__ import annotations
import subprocess, sys, json
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "foundry_signoff_plan_check.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_skip_no_plan(tmp_path):
    r = _run([str(tmp_path)])
    assert r.returncode == 0

def test_with_plan(tmp_path):
    plan = {"foundry_signoff_plan": {"closures": [
        {"waiver_id": 14, "tool": "Innovus", "proof_artefact": "step14.rpt"}
    ]}}
    (tmp_path / "foundry_signoff_plan.json").write_text(json.dumps(plan))
    r = _run([str(tmp_path)])
    assert r.returncode == 0


# --- main() ignored its arguments, so no test could drive it

def test_main_takes_argv_at_all():
    """`gate_cli_mutation_probe` reported this gate SILENT, and the cause was
    that no test COULD drive it: `def main():` read `sys.argv` unconditionally.

    Second instance of this exact shape today (`dispatcher_awake_gate_check` was
    the first), out of the 48 gates here that declare `main()` with no argv.
    """
    import inspect
    import foundry_signoff_plan_check as F
    assert "argv" in inspect.signature(F.main).parameters


def test_main_refuses_on_a_missing_project(tmp_path):
    """rc 2 — the question could not be asked, which is not a pass."""
    import foundry_signoff_plan_check as F
    assert F.main([str(tmp_path / "nope")]) == 2


def test_a_project_with_waivers_and_no_plan_exits_non_zero(tmp_path):
    """The real failure path, from the program's own contract: waivers present
    and no `foundry_signoff_plan.yaml` is the defect this gate exists for.

    My first version asserted `rc in (0, 1)` on an empty project, which is a
    weak assertion in the exact way this whole sweep is about — it passes
    whether the gate works or not. Measured: an empty project is rc 0 by design
    ("skip — no waivers"), so it could never have failed.
    """
    import json
    import foundry_signoff_plan_check as F
    (tmp_path / "waivers.json").write_text(json.dumps(
        {"waived_steps": [{"id": 20, "reason": "x"}]}))
    rc = F.main([str(tmp_path)])
    assert rc == 1, f"waivers with no signoff plan exited {rc}"


def test_a_project_with_no_waivers_is_a_documented_skip(tmp_path):
    """…and the other direction, pinned as a SKIP rather than invented as a
    pass: "no waivers in project — no signoff plan required"."""
    import foundry_signoff_plan_check as F
    assert F.main([str(tmp_path)]) == 0


# ----------------------------------------------------------------------
# The FAIL verdict was unreachable for every runner-produced project
# ----------------------------------------------------------------------
# A waivers.json carries its entries under ONE OF TWO documented keys.
# `waivers_materialize` writes `waived_steps`; `phase3_one_shot_runner`
# writes `waivers`. This gate read `waived_steps` only and early-returned
# `[PASS] ... (skip — no waivers)` the moment it came back empty — so on a
# runner-produced project NO closure-plan verdict could ever be emitted,
# whatever the plan file said. Measured on the tracked corpus when this was
# written: 6 of 9 waiver files use the key the gate could not see.
#
# Every assertion below is on the RETURN CODE and the EMITTED JSON. None of
# them reads the source.

_RUNNER_DIALECT = {
    "_schema_version": "1",
    "waivers": [
        {
            "step": "drc",
            "phase": "3",
            "verdict_tier": "ENV_UNAVAILABLE",
            "rationale": "deck unavailable in this environment",
            "evidence": ["reports/orchestrator/run.json"],
            "ticket": "TAPEOUT-ENV-DRC",
            "review_required": True,
            "_autogen": True,
        }
    ],
}


def _complete_closure(waiver_id):
    return {
        "waiver_id": waiver_id,
        "tool": "open-source physical-verification deck",
        "input": "gds/top.gds",
        "proof_artefact": "reports/pv/summary.rpt",
        "acceptance_criterion": "zero unwaived violations on the signoff deck",
    }


def _plan(closures, **top):
    body = {
        "foundry": "example-foundry",
        "contact": "signoff@example.com",
        "expected_review_date": "2027-01-01",
        "closures": closures,
    }
    body.update(top)
    return {"foundry_signoff_plan": body}


def _emit(tmp_path, out):
    """Run the gate, return (rc, parsed JSON). Drives the real CLI writer."""
    import json as _json
    import foundry_signoff_plan_check as F
    rc = F.main([str(tmp_path), "--json", str(out)])
    return rc, _json.loads(out.read_text())


def test_runner_dialect_waiver_without_a_plan_can_reach_FAIL(tmp_path):
    """DIRECTION 1 — the missing verdict. A project carrying a waiver under
    the `waivers` key and NO foundry_signoff_plan must FAIL and must NAME the
    waiver it has no plan for.

    Against the unfixed program this returns 0 with
    `summary.skip == True` and `summary.reason` claiming "no waivers in
    project", which is a false statement about a project holding a waiver.
    """
    import json as _json
    (tmp_path / "waivers.json").write_text(_json.dumps(_RUNNER_DIALECT))
    rc, doc = _emit(tmp_path, tmp_path / "out.json")

    assert rc == 1, f"runner-dialect waiver with no signoff plan exited {rc}"
    assert doc["summary"]["pass"] is False
    assert doc["summary"].get("skip") is not True
    assert doc["summary"]["waiver_root_count"] == 1
    assert doc["summary"]["waiver_root_ids"] == ["drc"]
    cats = [f["category"] for f in doc["findings"]]
    assert "PLAN_MISSING" in cats, cats


def test_runner_dialect_waiver_with_a_complete_plan_still_reaches_PASS(tmp_path):
    """DIRECTION 2 — the OTHER verdict, on the SAME newly-reachable path.
    Verifying only direction 1 would be satisfied by a gate that can now
    ONLY fail. The identical project, plus a closure entry naming the waiver
    by the identifier the runner actually wrote (`step: "drc"`), passes.
    """
    import json as _json
    (tmp_path / "waivers.json").write_text(_json.dumps(_RUNNER_DIALECT))
    (tmp_path / "foundry_signoff_plan.json").write_text(
        _json.dumps(_plan([_complete_closure("drc")])))
    rc, doc = _emit(tmp_path, tmp_path / "out.json")

    assert rc == 0, f"a completely planned waiver exited {rc}: {doc['findings']}"
    assert doc["summary"]["pass"] is True
    assert doc["summary"]["waiver_root_count"] == 1
    assert doc["findings"] == []


def test_runner_dialect_waiver_with_an_incomplete_closure_FAILs(tmp_path):
    """The plan EXISTS and names the waiver, but the closure has no proof
    artefact — the substance check must still bite on this dialect, not just
    the existence check."""
    import json as _json
    closure = _complete_closure("drc")
    del closure["proof_artefact"]
    (tmp_path / "waivers.json").write_text(_json.dumps(_RUNNER_DIALECT))
    (tmp_path / "foundry_signoff_plan.json").write_text(
        _json.dumps(_plan([closure])))
    rc, doc = _emit(tmp_path, tmp_path / "out.json")

    assert rc == 1
    assert "CLOSURE_FIELD_MISSING" in [f["category"] for f in doc["findings"]]


def test_a_plan_that_names_a_DIFFERENT_waiver_does_not_close_this_one(tmp_path):
    """Coverage is matched, not assumed: a plan naming some other step leaves
    this waiver unplanned. Guards the pass direction against becoming
    always-pass once the entries are finally visible."""
    import json as _json
    (tmp_path / "waivers.json").write_text(_json.dumps(_RUNNER_DIALECT))
    (tmp_path / "foundry_signoff_plan.json").write_text(
        _json.dumps(_plan([_complete_closure("metal_fill")])))
    rc, doc = _emit(tmp_path, tmp_path / "out.json")

    assert rc == 1
    assert "WAIVER_NOT_PLANNED" in [f["category"] for f in doc["findings"]]


def test_role_names_are_not_resolved_to_canonical_step_ids(tmp_path):
    """`_waiver_entries.STEP_NAME_TO_ID` maps drc/lvs/erc all to 31. Resolving
    would let ONE closure entry discharge THREE separately-waived steps —
    coverage the plan never wrote. Two waivers, a closure for one of them:
    the other is still unplanned."""
    import json as _json
    doc_in = {"waivers": [dict(_RUNNER_DIALECT["waivers"][0]),
                          dict(_RUNNER_DIALECT["waivers"][0], step="lvs")]}
    (tmp_path / "waivers.json").write_text(_json.dumps(doc_in))
    (tmp_path / "foundry_signoff_plan.json").write_text(
        _json.dumps(_plan([_complete_closure("drc")])))
    rc, doc = _emit(tmp_path, tmp_path / "out.json")

    assert rc == 1
    unplanned = [f for f in doc["findings"]
                 if f["category"] == "WAIVER_NOT_PLANNED"]
    assert len(unplanned) == 1, doc["findings"]
    assert "'lvs'" in unplanned[0]["message"]


def test_legacy_waived_steps_dialect_still_reaches_both_verdicts(tmp_path):
    """No regression for the key that already worked — both directions."""
    import json as _json
    ledger = {"waived_steps": [{"id": 31, "reason": "x" * 30,
                                "approver": "A Named Engineer"}]}
    (tmp_path / "waivers.json").write_text(_json.dumps(ledger))
    rc, doc = _emit(tmp_path, tmp_path / "fail.json")
    assert rc == 1
    assert "PLAN_MISSING" in [f["category"] for f in doc["findings"]]

    # `waiver_id: "31"` in YAML vs `id: 31` in JSON is a scalar-type
    # difference, not a missing plan.
    (tmp_path / "foundry_signoff_plan.json").write_text(
        _json.dumps(_plan([_complete_closure("31")])))
    rc, doc = _emit(tmp_path, tmp_path / "pass.json")
    assert rc == 0, doc["findings"]
    assert doc["summary"]["pass"] is True


def test_an_unreadable_waiver_ledger_cannot_report_itself_as_a_pass(tmp_path):
    """The WAIVERS_PARSE finding was constructed and then discarded by the
    early return, which hard-codes `findings: []` and `pass: True`. It was
    dead: no input could put it in front of a reader. Unfixed, this returns 0
    with the skip-PASS line."""
    (tmp_path / "waivers.json").write_text("{ this is not json")
    rc, doc = _emit(tmp_path, tmp_path / "out.json")

    assert rc == 1
    assert doc["summary"]["pass"] is False
    assert doc["summary"]["waiver_ledger_readable"] is False
    assert "WAIVERS_PARSE" in [f["category"] for f in doc["findings"]]
    # …and it must NOT invent a plan complaint for waivers it never read.
    assert "PLAN_MISSING" not in [f["category"] for f in doc["findings"]]


def test_a_key_holding_a_non_list_is_not_an_empty_ledger(tmp_path):
    """`"waivers": {...}` reads as zero entries in any fail-soft reader. That
    is unreadable, not empty."""
    import json as _json
    (tmp_path / "waivers.json").write_text(
        _json.dumps({"waivers": {"step": "drc"}}))
    rc, doc = _emit(tmp_path, tmp_path / "out.json")

    assert rc == 1
    assert "WAIVERS_SCHEMA" in [f["category"] for f in doc["findings"]]


def test_an_empty_ledger_is_still_a_skip_and_says_how_many_it_examined(tmp_path):
    """The OTHER direction for the skip branch: a genuinely empty ledger
    still passes, and now publishes the count so "0 problems found" is
    distinguishable from "0 entries examined"."""
    import json as _json
    (tmp_path / "waivers.json").write_text(
        _json.dumps({"waived_steps": [], "waivers": []}))
    rc, doc = _emit(tmp_path, tmp_path / "out.json")

    assert rc == 0
    assert doc["summary"]["skip"] is True
    assert doc["summary"]["waiver_entry_count"] == 0
    assert set(doc["summary"]["waiver_keys_read"]) == {"waived_steps", "waivers"}


def test_a_cascade_child_still_inherits_its_parents_closure(tmp_path):
    """Pre-existing contract, re-pinned against the new identity matching:
    only the ROOT waiver needs its own closure entry."""
    import json as _json
    ledger = {"waived_steps": [
        {"id": 31, "cascades_to": [32], "reason": "x" * 30},
        {"id": 32, "cascade_source": 31, "reason": "x" * 30},
    ]}
    (tmp_path / "waivers.json").write_text(_json.dumps(ledger))
    (tmp_path / "foundry_signoff_plan.json").write_text(
        _json.dumps(_plan([_complete_closure(31)])))
    rc, doc = _emit(tmp_path, tmp_path / "out.json")

    assert rc == 0, doc["findings"]
    assert doc["summary"]["waiver_root_count"] == 1
