"""Actual public native windows retain PROGRAM origin at collection."""
import copy
import json
from pathlib import Path

import pytest

import benchmark_dispatch as bd
import benchmark_io_adapter as bio
import flow_phase_attribution as fpa


def _program_reentry(tmp_path_factory, exit_step):
    root = tmp_path_factory.mktemp("program_window_" + exit_step)
    project = root / "project"
    prompt = project / "input/phase1_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Module name: straight_link\nInput a drives output y combinationally.\n")
    rtl = project / "phase2/stage1/rtl/straight_link.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module straight_link(input a,output y); assign y=a; endmodule\n")
    argv = bd._solver_argv(Path(bd.__file__).with_name("vibe_ic_one_shot_runner.py"),
                          project, "2", exit_step, "ip", "original", "rtl")
    measured = bd._RunnerBudget(1, 1, 1).run(argv)
    assert not measured.error, measured.stderr
    native = json.loads((project / "reports/flow_engine.json").read_text())
    validation = next(row for row in native["steps"] if row["name"] == "rtl_validation_and_lint")
    assert validation["status"] == "PASS", native
    got = bio.collect("rtllm", "neutral", project, supplied_rtl=True)
    assert got["ok"], got
    task = bd._make_ai_review_task("neutral", project, got, {}, measured.rc,
        root / "review-run", "PROGRAM", runner_invocation=measured.invocation)
    result = {"candidate_origin": "PROGRAM", "rc": measured.rc,
              "exit": exit_step, "phases": fpa.attribute(project)}
    return root, project, task, result, measured


@pytest.fixture(scope="module")
def program_step2(tmp_path_factory):
    return _program_reentry(tmp_path_factory, "2")


@pytest.fixture(scope="module")
def program_step4(tmp_path_factory):
    return _program_reentry(tmp_path_factory, "4")


@pytest.mark.parametrize("candidate", ["program_step2", "program_step4"])
def test_program_reentry_collects_its_declared_native_window(request, candidate):
    root, project, task, result, measured = request.getfixturevalue(candidate)
    report = project / "reports/flow_engine.json"
    before = report.read_bytes()
    got = bio.collect("rtllm", "neutral", project, supplied_rtl=True)
    assert got["ok"], got
    assert got["completion"] == (project / "phase2/stage1/rtl/straight_link.v").read_text()
    assert task["candidate_origin"] == result["candidate_origin"] == "PROGRAM"
    assert report.read_bytes() == before


@pytest.mark.parametrize("status", ["NOT_MEASURED", "BLOCKED", None, "FAIL"])
@pytest.mark.parametrize("candidate,site", [("program_step2", "rtl_validate"),
    ("program_step4", "rtl_validate"), ("program_step4", "sim")])
def test_existing_typed_validation_fact_never_promotes_nonmeasurement(request, candidate, site, status):
    root, project, task, result, measured = request.getfixturevalue(candidate)
    report, why = fpa.step_report(project)
    report = copy.deepcopy(report)
    name = {"rtl_validate": "rtl_validation_and_lint", "sim": "functional_simulation_and_coverage"}[site]
    if status is None:
        report["steps"] = [row for row in report["steps"] if row["name"] != name]
        report["native_steps_recorded"] -= 1
    else:
        next(row for row in report["steps"] if row["name"] == name)["status"] = status
    ledger = bd._required_gate_ledger({"exit": result["exit"], "phases": {
        "phase3_verifying": fpa.phase3_verifying(report, why)}})
    assert ledger["eligibility"] == ("INELIGIBLE" if status == "FAIL" else "NOT_MEASURED")
    if status == "FAIL":
        assert name in ledger["failed_required"]


@pytest.mark.parametrize("origin", ["AI_BACKUP", "AI_REPAIR"])
def test_existing_ai_origin_selection_is_unchanged(origin):
    assert bd._review_collection_supplied_rtl({}, {"candidate_origin": origin}) is True
