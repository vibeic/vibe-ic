import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import flow_engine_frontend as frontend
import pytest


def test_native_phase1_calls_document_owner_without_submission_admission(tmp_path):
    import phase1_one_shot_runner as owner
    argv = ["phase1_one_shot_runner.py", str(tmp_path), "--route", "ip",
            "--pdk", "sky130A", "--engine", "native"]
    with patch.object(sys, "argv", argv), \
            patch.object(owner, "_run_docs_mode", return_value=0) as extract, \
            patch.object(owner, "_run_step_0_5ic", side_effect=AssertionError("admission reached")):
        assert owner.main_recorded() == 0
    extract.assert_called_once_with(tmp_path.resolve(), "UNNAMED_CHIP", ["--pdk", "sky130A"])
    report = json.loads((tmp_path / "reports/orchestrator/phase1_one_shot.json").read_text())
    assert report["expert_review"] == "PENDING"


def test_native_benchmark_argv_preserves_router_window_without_old_manifest(tmp_path, monkeypatch):
    import benchmark_dispatch as dispatcher
    import flow109
    monkeypatch.setenv("VIBEIC_FLOW_ENGINE", "native")
    with patch.object(flow109, "resolve_task_manifest", side_effect=AssertionError("old manifest reached")):
        command = dispatcher._solver_argv(Path("vibe_ic_one_shot_runner.py"), tmp_path,
                                          "1", "2", "ip", "original", "rtl")
    for flag, value in (("--entry-step", "1"), ("--exit-step", "2"),
                        ("--rtl-input", "original"), ("--engine", "native")):
        assert command[command.index(flag) + 1] == value
    assert not (tmp_path / "input/flow109-manifest.json").exists()


def test_public_native_entry_forwards_the_selected_bounded_window(tmp_path, monkeypatch):
    observed = []
    engine = SimpleNamespace(run=lambda project, **kwargs:
                             observed.append((project, kwargs)) or {"fail": 0, "not_measured": 0})
    args = SimpleNamespace(project=tmp_path, entry_step="1", exit_step="2",
                           rtl_input="original", delivery_target="rtl", route="ip")
    monkeypatch.setitem(sys.modules, "flow_engine", engine)
    assert frontend.run_public(args) == 0
    assert observed == [(tmp_path.resolve(), {"route": {
        "entry_step": "1", "verify_through": "2", "input_contract": "original",
        "delivery_target": "rtl", "verify_closed_steps": ["1", "2"]}})]


def test_native_rtl_owner_reaches_generator_without_parse_track(tmp_path, monkeypatch):
    import design_one_shot_runner as owner

    class GeneratorReached(Exception):
        pass

    def forbidden(*args, **kwargs):
        raise AssertionError("legacy admission reached")

    def generate(*args, **kwargs):
        raise GeneratorReached

    monkeypatch.setattr(sys, "argv", ["design_one_shot_runner.py", str(tmp_path),
        "--entry-step", "1", "--exit-step", "2", "--engine", "native",
        "--skip-phase3", "--skip-hardware", "--skip-analog"])
    monkeypatch.setattr(owner._pl, "select_rtl_input", lambda *args: None)
    monkeypatch.setattr(owner, "_bootstrap_execution_policy", lambda *args, **kwargs: None)
    monkeypatch.setattr(owner, "_activate_runtime_program_tree", forbidden)
    monkeypatch.setattr(owner._spf, "entry_admission", forbidden)
    monkeypatch.setattr(owner._spf, "gate", forbidden)
    monkeypatch.setattr(owner._runner_lock, "acquire_or_reenter",
                        lambda *args: SimpleNamespace(release=lambda: None))
    monkeypatch.setattr(owner, "step_reused_ip_consume", lambda *args: None)
    monkeypatch.setattr(owner, "step_rig_topology_skeleton",
                        lambda *args: owner.StepResult("topology", "PASS", 0, ""))
    monkeypatch.setattr(owner, "detect_ic_class", lambda *args: ("generic", {}))
    monkeypatch.setattr(owner, "step_rtl_gen", generate)
    with pytest.raises(GeneratorReached):
        owner.main()


def test_native_lint_without_rtl_does_not_resolve_an_image(tmp_path):
    import librelane_contract
    with patch.object(librelane_contract, "resolve_image", side_effect=AssertionError("image lookup reached")):
        row = frontend.native_lint(tmp_path)
    assert row.status == "NOT_MEASURED"
    assert row.extras["metrics"] == {}
    assert row.extras["native_steps"] == []


def test_owner_session_runs_one_window_for_all_result_readers(tmp_path, monkeypatch):
    report = tmp_path / "reports/orchestrator/phase2_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"steps": [
        {"name": "rtl_gen", "status": "PASS", "extras": {}},
        {"name": "rtl_validate", "status": "PASS", "extras": {}},
    ]}))
    selected = {"entry_step": "1", "verify_through": "2", "input_contract": "original",
                "delivery_target": "rtl"}
    with patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as execute:
        session = frontend.OwnerSession(tmp_path, selected)
        authored = session.result(tmp_path / "steps/author", "rtl_gen")
        checked = session.result(tmp_path / "steps/lint", "rtl_validate")
    execute.assert_called_once()
    assert authored["metrics"]["rtl_gen"] == "PASS"
    assert checked["metrics"]["rtl_validate"] == "PASS"


def test_public_entry_retains_the_existing_router_closure(tmp_path, monkeypatch):
    route = {"entry_step": "1", "verify_through": "2", "answer_step": "1",
             "delivery_target": "rtl", "input_contract": "original",
             "verify_closed_steps": ["1", "2"], "task_nature": "completion"}
    decision = tmp_path / "route.json"
    decision.write_text(json.dumps({"payload": route}))
    pointer = tmp_path / "reports/orchestrator/receipts/route_decision.current.json"
    pointer.parent.mkdir(parents=True)
    pointer.write_text(json.dumps({"receipt_path": str(decision)}))
    args = SimpleNamespace(project=tmp_path, entry_step="1", exit_step="2",
                           rtl_input="original", delivery_target="rtl", route="ip")
    engine = SimpleNamespace(run=lambda *args, **kwargs: {"route": kwargs["route"]})
    monkeypatch.setitem(sys.modules, "flow_engine", engine)
    with patch.object(engine, "run", wraps=engine.run) as execute:
        assert frontend.run_public(args) == 0
    assert execute.call_args.kwargs["route"] == route
