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
    extract.assert_called_once_with(tmp_path.resolve(), "UNNAMED_CHIP",
                                    ["--pdk", "sky130A", "--engine", "native"])
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
    measured = {"steps": [
        {"name": "rtl_gen", "status": "PASS", "extras": {}},
        {"name": "rtl_validate", "status": "PASS", "extras": {}},
    ]}
    def publish(*args, **kwargs):
        report.write_text(json.dumps(measured))
        return SimpleNamespace(returncode=0)
    selected = {"entry_step": "1", "verify_through": "2", "input_contract": "original",
                "delivery_target": "rtl"}
    with patch.object(frontend.subprocess, "run", side_effect=publish) as execute:
        session = frontend.OwnerSession(tmp_path, selected)
        authored = session.result(tmp_path / "steps/author", "rtl_gen")
        checked = session.result(tmp_path / "steps/lint", "rtl_validate")
    execute.assert_called_once()
    assert authored["metrics"]["rtl_gen"] == "PASS"
    assert checked["metrics"]["rtl_validate"] == "PASS"
    assert json.loads((tmp_path / "steps/author/phase2_one_shot.json").read_text()) == measured
    assert json.loads((tmp_path / "steps/lint/phase2_one_shot.json").read_text()) == measured


def test_owner_log_does_not_change_the_project_during_generation(tmp_path):
    report = tmp_path / "reports/orchestrator/phase2_one_shot.json"
    report.parent.mkdir(parents=True)
    directory = tmp_path / "steps/author"
    directory.mkdir(parents=True)
    selected = {"delivery_target": "ip_hardmacro"}
    run = frontend.subprocess.run

    def publish(command, **kwargs):
        run([sys.executable, "-c", "import sys; sys.stdout.buffer.write(b'catalog diagnostic\\xff\\n')"],
            stdout=kwargs["stdout"], check=True)
        assert not (directory / "owner.log").exists()
        report.write_text(json.dumps({"steps": [{"name": "rtl_gen", "status": "PASS"}]}))
        return SimpleNamespace(returncode=0)

    with patch.object(frontend.subprocess, "run", side_effect=publish):
        result = frontend.OwnerSession(tmp_path, selected).result(directory, "rtl_gen")
    assert (directory / "owner.log").read_bytes() == b"catalog diagnostic\xff\n"
    assert str(directory / "owner.log") in result["reports"]


def test_owner_lint_numbers_are_read_from_its_report(tmp_path):
    report = tmp_path / "reports/orchestrator/phase2_one_shot.json"
    report.parent.mkdir(parents=True)
    numbers = {"design__lint_error__count": 0, "design__lint_timing_construct__count": 0}
    report.write_text(json.dumps({"steps": [{"name": "rtl_validate", "status": "PASS",
        "extras": {"exit_code": 0, "metrics": numbers}}]}))
    selected = {"delivery_target": "rtl", "input_contract": "original"}
    session = frontend.OwnerSession(tmp_path, selected)
    session.executed = True
    result = session.result(tmp_path / "steps/lint", "rtl_validate")
    assert all(result["metrics"].get(key) == value for key, value in numbers.items())


@pytest.mark.parametrize("produced", [True, False])
@pytest.mark.parametrize("owner_status", ["WAIVED", "PASS_WITH_WAIVERS", "PASS"])
def test_author_fallback_is_decided_by_produced_rtl(tmp_path, produced, owner_status):
    import flow_engine
    report = tmp_path / "reports/orchestrator/phase2_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"steps": [{"name": "rtl_gen", "status": owner_status}]}))
    if produced:
        rtl = tmp_path / "phase2/stage1/rtl"
        rtl.mkdir(parents=True)
        (rtl / "unit.v").write_text("module unit; endmodule\n")
    session = frontend.OwnerSession(tmp_path, {"delivery_target": "ip_hardmacro"})
    result = flow_engine.ToolResult(**session.result(tmp_path / "steps/author", "rtl_gen"))
    assert flow_engine.evaluate(result, []) == ("PASS" if produced else "FAIL")


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


@pytest.mark.parametrize("selected,target", [("ic", "shippable_gds"), ("ip", "ip_hardmacro")])
def test_public_native_delivery_flag_overrides_document_wording(tmp_path, monkeypatch, selected, target):
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "requirements.md").write_text("Generate a digital IP block with a clock and data ports.")
    observed = []
    engine = SimpleNamespace(
        design_text=lambda project: (docs / "requirements.md").read_text(),
        run=lambda project, **kwargs: observed.append(kwargs["route"]) or {})
    monkeypatch.setitem(sys.modules, "flow_engine", engine)
    args = SimpleNamespace(project=tmp_path, entry_step=None, exit_step=None,
                           rtl_input="structured", delivery_target=None, route=selected, pdk="auto")
    assert frontend.run_public(args) == 0
    assert observed[0]["delivery_target"] == target


def test_native_owner_forwards_explicit_pdk_to_document_extraction(tmp_path):
    route = {"delivery_target": "shippable_gds", "pdk": "process_variant"}
    with patch.object(frontend.subprocess, "run") as execute:
        frontend.OwnerSession(tmp_path, route).result(tmp_path / "step", "phase1")
    command = execute.call_args.args[0]
    assert command[command.index("--pdk") + 1] == "process_variant"


def test_failed_owner_invocation_cannot_reuse_the_previous_report(tmp_path):
    report = tmp_path / "reports/orchestrator/phase2_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"steps": [{"name": "rtl_validate", "status": "PASS"}]}))
    selected = {"entry_step": "2", "verify_through": "2", "input_contract": "original",
                "delivery_target": "rtl"}
    with patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(returncode=2)):
        result = frontend.OwnerSession(tmp_path, selected).result(tmp_path / "steps/lint", "rtl_validate")
    assert not result["ran"]
    assert result["metrics"] == {}


def test_fresh_physical_project_invokes_the_document_owner(tmp_path):
    selected = {"entry_step": "definition", "verify_through": "release",
                "input_contract": "structured", "delivery_target": "ip_hardmacro"}
    report = tmp_path / "reports/orchestrator/phase1_one_shot.json"

    def publish(command, **kwargs):
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({"steps": [
            {"name": "phase1_ingest_render", "status": "PASS"}]}))
        assert Path(command[1]).name == "phase1_one_shot_runner.py"
        assert command[command.index("--route") + 1] == "ip"
        assert command[command.index("--mode") + 1] == "docs"
        assert "--pdk" not in command
        return SimpleNamespace(returncode=0)

    with patch.object(frontend.subprocess, "run", side_effect=publish) as execute:
        observed = frontend.OwnerSession(tmp_path, selected).result(tmp_path / "steps/definition", "phase1")
    execute.assert_called_once()
    assert observed["metrics"]["phase1_ingest_render"] == "PASS"


def test_fresh_physical_author_uses_only_the_table_author_window(tmp_path, monkeypatch):
    selected = {"entry_step": "definition", "verify_through": "release",
                "input_contract": "structured", "delivery_target": "ip_hardmacro"}
    report = tmp_path / "reports/orchestrator/phase2_one_shot.json"
    original_read = Path.read_text
    table_path = Path(frontend.__file__).parents[1] / "flow/steps.json"
    table = {"steps": [{"tool": {"function": "step_rtl_gen"},
                        "legacy_id": {"native": ["author-address"]}}]}

    def read(path, *args, **kwargs):
        return json.dumps(table) if path == table_path else original_read(path, *args, **kwargs)

    def publish(command, **kwargs):
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({"steps": [
            {"name": "rtl_gen", "status": "PASS_WITH_WAIVERS",
             "extras": {"fallback_skill": "spec-to-rtl"}}]}))
        assert Path(command[1]).name == "design_one_shot_runner.py"
        assert command[command.index("--entry-step") + 1] == "author-address"
        assert command[command.index("--exit-step") + 1] == "author-address"
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(Path, "read_text", read)
    with patch.object(frontend.subprocess, "run", side_effect=publish) as execute:
        observed = frontend.OwnerSession(tmp_path, selected).result(tmp_path / "steps/author", "rtl_gen")
    execute.assert_called_once()
    assert observed["metrics"]["rtl_gen"] == "PASS_WITH_WAIVERS"
    assert observed["native_steps"][0]["status"] == "FAIL"
    assert observed["native_steps"][0]["detail"] == "The owner produced no RTL."


def test_retained_physical_report_needs_an_explicit_rerun(tmp_path):
    selected = {"entry_step": "definition", "verify_through": "release",
                "input_contract": "structured", "delivery_target": "ip_hardmacro"}
    report = tmp_path / "reports/orchestrator/phase1_one_shot.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"steps": [{"name": "phase1_ingest_render", "status": "PASS"}]}))
    with patch.object(frontend.subprocess, "run", side_effect=AssertionError("retained owner reran")):
        retained = frontend.OwnerSession(tmp_path, selected).result(tmp_path / "steps/definition", "phase1")
    assert retained["metrics"]["phase1_ingest_render"] == "PASS"
    with patch.object(frontend.subprocess, "run", return_value=SimpleNamespace(returncode=2)) as execute:
        frontend.OwnerSession(tmp_path, selected, force=True).result(tmp_path / "steps/definition", "phase1")
    execute.assert_called_once()


@pytest.mark.parametrize("input_contract", ["original", "structured"])
def test_debug_closure_runs_only_owner_backed_dependencies(tmp_path, input_contract):
    route = {"entry_step": "4", "verify_through": "4", "delivery_target": "rtl",
             "input_contract": input_contract, "verify_closed_steps": ["D1", "0.5ic", "1", "2", "4"]}
    report = tmp_path / "reports/orchestrator/phase2_one_shot.json"
    def publish(command, **kwargs):
        assert command[command.index("--entry-step") + 1] == "1"
        assert command[command.index("--exit-step") + 1] == "2"
        assert Path(command[1]).name == "design_one_shot_runner.py"
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({"steps": [
            {"name": "rtl_gen", "status": "PASS", "extras": {"deterministic_generator": "existing_program"}},
            {"name": "rtl_validate", "status": "PASS"}]}))
        rtl = tmp_path / "phase2/stage1/rtl"
        rtl.mkdir(parents=True)
        (rtl / "unit.v").write_text("module unit; endmodule\n")
        return SimpleNamespace(returncode=0)
    with patch.object(frontend.subprocess, "run", side_effect=publish) as execute:
        session = frontend.OwnerSession(tmp_path, route, table=json.loads(
            (Path(frontend.__file__).parents[1] / "flow/steps.json").read_text()))
        requirements = session.result(tmp_path / "steps/requirements", "phase1")
        assert execute.call_count == 0
        authored = session.result(tmp_path / "steps/author", "rtl_gen")
        checked = session.result(tmp_path / "steps/lint", "rtl_validate")
    execute.assert_called_once()
    assert requirements["native_steps"][0]["source"].startswith("task_nature_route.")
    assert authored["metrics"]["rtl_gen"] == "PASS"
    assert checked["metrics"]["rtl_validate"] == "PASS"
    assert session.route == route
    assert not (tmp_path / "reports/orchestrator/phase1_one_shot.json").exists()


@pytest.mark.parametrize("input_contract", ["original", "structured"])
def test_debug_resume_keeps_ai_canonical_rtl_and_lints_only(tmp_path, input_contract):
    route = {"entry_step": "4", "verify_through": "4", "delivery_target": "rtl",
             "input_contract": input_contract, "verify_closed_steps": ["D1", "0.5ic", "1", "2", "4"]}
    rtl = tmp_path / "phase2/stage1/rtl/unit.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module unit(input a,output y); assign y=~a; endmodule\n")
    original = rtl.read_bytes()
    report = tmp_path / "reports/orchestrator/phase2_one_shot.json"
    report.parent.mkdir(parents=True)
    previous = {"steps": [{"name": "rtl_gen", "status": "WAIVED",
                           "extras": {"fallback_skill": "spec-to-rtl", "candidate_origin": "AI_BACKUP"}}]}
    report.write_text(json.dumps(previous))
    def publish(command, **kwargs):
        assert command[command.index("--entry-step") + 1] == "2"
        assert command[command.index("--exit-step") + 1] == "2"
        assert rtl.read_bytes() == original
        report.write_text(json.dumps({"steps": [
            {"name": "rtl_gen", "status": "NOT_APPLICABLE"},
            {"name": "rtl_validate", "status": "PASS"}]}))
        return SimpleNamespace(returncode=0)
    with patch.object(frontend.subprocess, "run", side_effect=publish) as execute:
        session = frontend.OwnerSession(tmp_path, route, force=True)
        result = session.result(tmp_path / "steps/author", "rtl_gen")
        session.result(tmp_path / "steps/lint", "rtl_validate")
    execute.assert_called_once()
    assert rtl.read_bytes() == original
    assert result["native_steps"][-1]["reused"] is True
    assert "C7" in result["detail"]
    assert json.loads((tmp_path / "steps/author/reused_authoring.json").read_text()) == previous


def test_bounded_native_lint_does_not_import_librelane(tmp_path, monkeypatch):
    import builtins
    original_import = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name == "librelane" or name.startswith("librelane."):
            raise AssertionError("Bounded native lint imported LibreLane")
        return original_import(name, *args, **kwargs)
    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "unit.v").write_text("module unit(input a,output y); assign y=a; endmodule\n")
    monkeypatch.setattr(builtins, "__import__", guarded)
    result = frontend.native_lint(tmp_path, "unit")
    assert result.name == "rtl_validate"


def test_public_native_resume_forwards_pdk_and_from_without_rerouting(tmp_path, monkeypatch):
    observed = []
    engine = SimpleNamespace(run=lambda project, **kwargs: observed.append(kwargs) or {})
    monkeypatch.setitem(sys.modules, "flow_engine", engine)
    args = SimpleNamespace(project=tmp_path, entry_step="1", exit_step="2", rtl_input="original",
                           delivery_target="rtl", route="ip", from_name="rtl_validation_and_lint", pdk="sky130A")
    assert frontend.run_public(args) == 0
    assert observed[0]["from_name"] == "rtl_validation_and_lint"
    assert observed[0]["pdk"] == "sky130A"
    assert observed[0]["route"]["verify_closed_steps"] == ["1", "2"]
