"""Backup reentry uses the admitted route and native per-row outcomes."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import benchmark_dispatch as dispatch
import flow109
import task_nature_route as routing
from step_output_collector import flow109_step_folder
from _hostpaths import require_repo


def _case(tmp_path):
    source = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs")
    registry = flow109.load_registry()
    features = {key: False for key in registry["predicate_names"]
                if key not in registry["predicate_definitions"]}
    features.update(always=True, has_digital=True, soft_ip=True)
    plan = flow109.resolve_plan(features)
    project = tmp_path / "projects/unit"
    (project / "input").mkdir(parents=True)
    (project / "input/flow109-manifest.json").write_text(json.dumps({"features": features}))
    (project / "reports/flow109").mkdir(parents=True)
    (project / "reports/flow109/plan.json").write_text(json.dumps(plan))
    receipt = routing.route_decision_receipt(
        "Debug the supplied RTL and return corrected Verilog.", nature="debug",
        requested_evidence="behaviour", source_sha256="0" * 64)
    return source, project, plan, receipt


def _result(project, plan, step, status="PASS", *, completed=True):
    spec = next(row for row in plan["rows"] if row["id"] == step)
    folder = project / "steps" / flow109_step_folder(spec) / "20261104T000000Z"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "result.json").write_text(json.dumps({
        "step_id": step, "default_row_status": status, "completed": completed,
        "fixture_scope": "SOFTWARE_ONLY"}))


def _resume(source, project, plan, receipt, *, first_status="PASS"):
    # Exercise the actual nested caller without constructing an unrelated AI
    # review. Admission and collection are outside this scheduling control.
    tree = ast.parse((source / "benchmark_dispatch.py").read_text())
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "_run_and_collect")
    seen = []

    def run(argv):
        entry = argv[argv.index("--entry-step") + 1]
        exit_step = argv[argv.index("--exit-step") + 1]
        seen.append((entry, exit_step))
        if entry != exit_step:
            _result(project, plan, "D11", first_status)
            _result(project, plan, "D12", "NOT_MEASURED", completed=False)
            _result(project, plan, "D13", "NOT_MEASURED", completed=False)
            return dispatch._ProcessOutcome(1, stdout="phase1 checkpoint handoff refused", stderr="")
        _result(project, plan, entry, first_status if entry == "D11" else "PASS")
        return dispatch._ProcessOutcome(0, stdout="", stderr="")

    state = {"status": "ACTIVE", "activation": None, "effective_entry": "2",
             "exit_step": "4", "delivery_route": "ip", "route_receipt": receipt,
             "task": {"task_sha256": "fixture"}}
    namespace = {**vars(dispatch), "run_p": project.parent.parent,
                 "result_by_id": {}, "fmt": "rtllm", "bench": "rtllm",
                 "runner": source / "vibe_ic_one_shot_runner.py",
                 "runner_budget": SimpleNamespace(run=run),
                 "_route_reentry_state": lambda *_a, **_k: state,
                 "_forward_product_manifest": lambda *_a: None,
                 "_require_route_admission": lambda *_a, **_k: None,
                 "_runner_diagnostics": lambda *_a: None,
                 "_collect_runner_result": lambda *_a, **_k: {"ok": True},
                 "_required_scorer_top": lambda *_a: None,
                 "_entry": lambda *_a: {}}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source / "benchmark_dispatch.py"), "exec"), namespace)
    outcome = namespace["_run_and_collect"](("unit", project, True, "4", "4"))
    return seen, outcome


def test_backup_uses_only_admitted_validation_rows(tmp_path):
    source, project, plan, receipt = _case(tmp_path)
    seen, outcome = _resume(source, project, plan, receipt)
    assert seen == [("D11", "D11"), ("D13", "D13")]
    assert outcome.rc == 0 and outcome.error is None
    assert not (project / "steps" / flow109_step_folder(next(
        row for row in plan["rows"] if row["id"] == "D12"))).exists()


def test_backup_stops_on_native_failure_even_with_zero_process_rc(tmp_path):
    source, project, plan, receipt = _case(tmp_path)
    seen, _ = _resume(source, project, plan, receipt, first_status="FAIL")
    assert seen == [("D11", "D11")]
    assert not (project / "steps" / flow109_step_folder(next(
        row for row in plan["rows"] if row["id"] == "D13"))).exists()



def test_native_simulation_child_reaches_collection(tmp_path, monkeypatch):
    from test_runner_report_generation import _selected_d09_handoff
    project, argv, process, _ = _selected_d09_handoff(
        tmp_path, monkeypatch, row_id="D13")
    got = dispatch._collect_runner_result(process, argv, "neutral", "neutral", project)
    assert got["runner_diagnostics"]["status"] == "REPORTS_AVAILABLE", got
    assert "reason" not in got["runner_diagnostics"]


def test_native_simulation_child_still_rejects_wrong_window(tmp_path, monkeypatch):
    from test_runner_report_generation import _selected_d09_handoff
    project, argv, process, _ = _selected_d09_handoff(
        tmp_path, monkeypatch, damage="argv", row_id="D13")
    got = dispatch._collect_runner_result(process, argv, "neutral", "neutral", project)
    assert got["runner_diagnostics"]["status"] == "REPORT_BINDING_MISMATCH", got
    assert got["ok"] is False
