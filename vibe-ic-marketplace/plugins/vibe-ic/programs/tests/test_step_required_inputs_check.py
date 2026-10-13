#!/usr/bin/env python3
"""Bidirectional control for `required_inputs` + step_required_inputs_check.

FORWARD (must FAIL against the byte-identical pre-change flow, PASS after)
    A step whose declared input is ABSENT is reported BLOCKED, naming the
    producing step that owes it, BEFORE the step runs. Against a flow with no
    `required_inputs` the same call can only answer UNDECLARED — it cannot say
    the step was starved, which is the whole gap this change closes.

REVERSE (must STILL pass — before AND after)
    A step whose declared inputs are ALL present is NOT reported blocked, even
    when the step's OWN outputs are missing. This is the case the change must
    not break: "produced nothing" and "had nothing to read" are different
    findings, and manufacturing a false BLOCKED for the first would move the
    blame in the opposite wrong direction.

The "pre-change" flow is reconstructed by stripping every `required_inputs`
key from the shipped one, which is what this change added and nothing else
(verified at authoring time: the two parse structurally identical once that
key is removed). Reconstructing rather than vendoring a 4000-line fixture
keeps the control valid as the flow keeps evolving.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

PROGRAMS = Path(__file__).resolve().parent.parent
FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
CHECK = PROGRAMS / "step_required_inputs_check.py"


def _run(project: Path, flow: Path, step: str | None = None):
    cmd = [sys.executable, str(CHECK), str(project), "--flow-def", str(flow),
           "--quiet"]
    if step:
        cmd += ["--step", step]
    out = project / "ri.json"
    cmd += ["--json", str(out)]
    rc = subprocess.run(cmd, capture_output=True, text=True).returncode
    return rc, json.loads(out.read_text())


@pytest.fixture(scope="module")
def pre_change_flow(tmp_path_factory):
    """The flow as it was before this change: no `required_inputs` anywhere."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    for s in doc.get("steps", []):
        s.pop("required_inputs", None)
    p = tmp_path_factory.mktemp("flow") / "pre_change.yaml"
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


@pytest.fixture
def project(tmp_path):
    """Minimal run root: step 11 produced NOTHING, step 1 produced its RTL."""
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "top.v").write_text(
        "module top(); endmodule\n")
    # Step 2 also consumes the integration declaration; its present-input
    # reverse control must supply both inputs from the current shipped flow.
    integration = tmp_path / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    integration.parent.mkdir(parents=True)
    integration.write_text(json.dumps({"fields": {"top_module": "top"}}))
    # step 11's declared scan_netlist.v is deliberately NOT created.
    (tmp_path / "phase2" / "stage2" / "dft").mkdir(parents=True)
    return tmp_path


def test_forward_control_blocked_step_is_named_before_it_runs(
        project, pre_change_flow):
    rc_before, rep_before = _run(project, pre_change_flow, "12")
    assert rep_before["steps"][0]["verdict"] == "UNDECLARED", (
        "pre-change flow declares no required_inputs, so the check cannot "
        "say the step is starved")
    assert rc_before == 0, "and therefore cannot fail on it"

    rc_after, rep_after = _run(project, FLOW, "12")
    row = rep_after["steps"][0]
    assert row["verdict"] == "BLOCKED"
    assert rc_after == 1
    absent = [i for i in row["inputs"] if i["present"] is False]
    assert absent, "a BLOCKED step must name the artefact that is absent"
    assert absent[0]["path"] == "phase2/stage2/dft/scan_netlist.v"
    assert str(absent[0]["from"]) == "11", (
        "the absence must be charged to the step that OWES the artefact, not "
        "to the step that was about to read it")


def test_reverse_case_present_inputs_are_never_blocked(project,
                                                       pre_change_flow):
    """Step 2 reads step 1's RTL, which exists. Step 2's own outputs do not.

    Must NOT be BLOCKED — before or after.
    """
    for flow in (pre_change_flow, FLOW):
        rc, rep = _run(project, flow, "2")
        assert rep["steps"][0]["verdict"] != "BLOCKED"
        assert rc == 0


def test_reverse_case_no_step_is_blocked_while_all_inputs_present(project):
    """Whole-project sweep: BLOCKED implies at least one absent input."""
    _rc, rep = _run(project, FLOW)
    for row in rep["steps"]:
        if row["verdict"] != "BLOCKED":
            continue
        assert any(i["present"] is False for i in row["inputs"]), (
            f"step {row['id']} reported BLOCKED with every declared input "
            f"present — a manufactured absence")


def test_declaration_is_self_consistent():
    """Every `from: <step>` input names a path that step really declares.

    This is the guard against the defect the exercise exists to avoid: a data
    edge pointing at an artefact its own named producer does not declare. The
    check refuses to compute any verdict from such a flow (exit 2), so this
    test failing means the SHIPPED flow is broken, not the test.
    """
    sys.path.insert(0, str(PROGRAMS))
    import step_required_inputs_check as m
    steps, err = m.load_flow(FLOW)
    assert err is None and steps
    assert m.declaration_defects(steps) == []


def test_undeclared_steps_are_listed_not_counted_as_ready(project):
    """A step with no required_inputs is UNDECLARED, never READY.

    A check that reported the 7 undeclared steps green would be the falsely
    clean result this change exists to remove.
    """
    _rc, rep = _run(project, FLOW)
    assert rep["undeclared"], "the flow still has undeclared steps; say so"
    ready = {r["id"] for r in rep["steps"] if r["verdict"] == "READY"}
    assert not (set(rep["undeclared"]) & ready)


def test_backward_compatibility_no_steps_tree_and_no_ledger(project):
    """A run with neither steps/ nor a write ledger is judged, and SAYS SO."""
    assert not (project / "steps").exists()
    assert not (project / "reports" / "write_ledger.json").exists()
    rc, rep = _run(project, FLOW)
    assert rep["ok"] is True
    assert "no reports/write_ledger.json" in rep["degraded"]["attribution"]
    assert "PRESENCE-ONLY" in rep["degraded"]["attribution"]
    assert "not required and not read" in rep["degraded"]["steps_tree"]
    # and the degradation must not be expressed as a pass
    assert rc in (0, 1)


def _issue3054_flow():
    from _hostpaths import require_repo
    return yaml.safe_load(require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "flow",
        "phase1_phase2_phase3.yaml").read_text())


def _issue3054_step1(project):
    """Neutral initialized inputs, derived from the actual D1 declaration."""
    doc = _issue3054_flow()
    for spec in next(row for row in doc["steps"] if row["id"] == "D1")["required_outputs"]:
        rel = spec.split(" OR ")[0].replace("*", "NEUTRAL")
        path = project / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n" if path.suffix == ".json" else "neutral input\n")
    return doc


@pytest.mark.parametrize("complete", [True, False], ids=["present", "missing"])
def test_issue3054_scoped_step1_cli_and_rtl_preflight(tmp_path, complete):
    import step_preflight as preflight
    _issue3054_step1(tmp_path)
    missing = "phase1/generated_docs/L1_DATASHEET.json"
    if not complete:
        (tmp_path / missing).unlink()
    rc, report = _run(tmp_path, FLOW, "1")
    assert rc == (0 if complete else 1), report
    row = report["steps"][0]
    assert row["verdict"] == ("READY" if complete else "BLOCKED")
    assert row["inputs"] and all(item["present"] is not None for item in row["inputs"])

    called = []
    def native_boundary():
        called.append("dispatched")
        return "SOURCE_FIXTURE_ONLY"
    def refusal(detail, extras):
        return {"detail": detail, "extras": extras}
    result = preflight.gate(tmp_path, "design_one_shot_runner", "rtl_gen",
                            refusal, native_boundary)
    assert len(called) == (1 if complete else 0), result
    decision = json.loads(preflight.ledger_path(tmp_path).read_text())["decisions"][0]
    assert decision["verdict"] == ("READY" if complete else "REFUSED")
    assert decision["allow"] is complete and decision["inputs"]
    if not complete:
        assert missing in result["detail"]


@pytest.mark.parametrize("mutation", ["sta_owner", "spef_alternative",
                                      "unknown_owner", "undeclared_output"])
def test_issue3054_reversed_declarations_still_refuse_scoped_step1(tmp_path, mutation):
    doc = _issue3054_step1(tmp_path)
    rows = {str(row["id"]): row for row in doc["steps"]}
    if mutation == "sta_owner":
        rows["23"]["required_outputs"].remove("reports/phase3/sta_postpnr_signoff.json")
    elif mutation == "spef_alternative":
        rows["30"]["required_inputs"][1]["path"] = "phase3/stage3/extracted/*.spef"
    elif mutation == "unknown_owner":
        rows["30"]["required_inputs"][0]["from"] = "UNKNOWN_PRODUCER"
    else:
        rows["30"]["required_inputs"][0]["path"] = "reports/phase3/undeclared.json"
    flow = tmp_path / "reversed.yaml"
    flow.write_text(yaml.safe_dump(doc, sort_keys=False))
    rc, report = _run(tmp_path, flow, "1")
    assert rc == 2, report
    assert report["ok"] is False and "SELF-INCONSISTENT" in report["error"]
    assert len(report["declaration_defects"]) == 1, report
    assert "steps" not in report
    import step_preflight as preflight
    decision = preflight.decide(tmp_path, "design_one_shot_runner", "rtl_gen", flow)
    # This historical default is advisory UNAVAILABLE: dispatch was allowed,
    # and this reversal must not claim that the malformed flow stopped it.
    assert decision.verdict == "UNAVAILABLE" and decision.inputs == []
    assert decision.allow is True
