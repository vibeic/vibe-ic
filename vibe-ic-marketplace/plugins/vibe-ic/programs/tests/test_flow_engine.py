import json
from pathlib import Path
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flow_engine as engine


def command_row(name, value=0, code=0, inputs=()):
    script = ("import json,pathlib,sys; "
              f"pathlib.Path(sys.argv[1]).write_text(json.dumps({{'errors': {value}}})); "
              f"sys.exit({code})")
    return {"name": name, "title": name, "when": "always", "legacy_id": {},
            "tool": {"kind": "command", "command": [sys.executable, "-c", script,
                                                       "{step}/metrics.json"], "inputs": list(inputs)},
            "checks": [{"metric": "errors", "operator": "<=", "limit": 0,
                        "source": {"file": "test tool limit", "line": 1}}]}


def execute(project, rows, **kwargs):
    route = {"entry_step": rows[0]["name"], "verify_through": rows[-1]["name"],
             "delivery_target": "rtl", "input_contract": "original"}
    return engine.run(project, table={"steps": rows}, route=route, **kwargs)


@pytest.mark.parametrize("code,value,inputs,status", [
    (3, 0, (), "FAIL"), (0, 2, (), "FAIL"),
    (0, 0, ("absent.v",), "NOT_MEASURED"), (0, 0, (), "PASS"),
])
def test_tool_result_against_original_limit(tmp_path, code, value, inputs, status):
    report = execute(tmp_path, [command_row("measure", value, code, inputs)])
    actual = json.loads((tmp_path / "steps/measure/result.json").read_text())
    assert actual["status"] == status
    assert report["steps"][0]["status"] == status
    assert actual["metrics"][0]["limit"] == 0


def test_failed_step_does_not_block_independent_tool(tmp_path):
    report = execute(tmp_path, [command_row("bad", 2), command_row("good")])
    assert [row["status"] for row in report["steps"]] == ["FAIL", "PASS"]


def test_from_preserves_earlier_folder_and_clears_later_results(tmp_path):
    rows = [command_row(name) for name in ("first", "middle", "last")]
    execute(tmp_path, rows)
    prior = (tmp_path / "steps/first/result.json").read_bytes()
    execute(tmp_path, rows, from_name="middle", to_name="middle")
    assert (tmp_path / "steps/first/result.json").read_bytes() == prior
    assert not (tmp_path / "steps/last/result.json").exists()
    assert json.loads((tmp_path / "steps/middle/result.json").read_text())["status"] == "PASS"


def test_added_table_entry_runs_without_runner_change(tmp_path):
    report = execute(tmp_path, [command_row("existing"), command_row("new_step")])
    assert report["pass"] == 2
    assert (tmp_path / "steps/new_step/tool.log").is_file()


def test_router_window_remains_bounded(tmp_path):
    import task_nature_route as router
    decision = router.route_decision_receipt(
        "Generate a combinational RTL inverter and lint it.",
        nature="spec_generation", delivery_target="rtl", requested_evidence="lint_validated")
    rows = [command_row(name) for name in ("requirements", "author", "lint", "floorplan")]
    for row, native in zip(rows, ("D1", "1", "2", "15")):
        row["legacy_id"] = {"registry": "", "native": [native]}
    report = engine.run(tmp_path, table={"steps": rows}, route=decision)
    assert [row["name"] for row in report["steps"]] == ["author", "lint"]
    assert report["route"] == decision
    with pytest.raises(ValueError, match="outside"):
        engine.run(tmp_path, table={"steps": rows}, route=decision, to_name="floorplan")


def test_missing_limit_never_becomes_pass(tmp_path):
    row = command_row("unlimited")
    row["checks"][0]["limit"] = None
    assert execute(tmp_path, [row])["steps"][0]["status"] == "NOT_MEASURED"


def test_successful_tool_without_remaining_checks_passes(tmp_path):
    row = command_row("native_exit")
    row["checks"] = []
    assert execute(tmp_path, [row])["steps"][0]["status"] == "PASS"


def test_aggregate_counts_earlier_selected_failures(tmp_path):
    row = command_row("summary")
    row["tool"] = {"kind": "aggregate"}
    row["checks"] = [{"metric": "non_passing_steps", "operator": "==", "limit": 0}]
    report = execute(tmp_path, [command_row("bad", value=1), row])
    assert report["steps"][-1]["status"] == "FAIL"
    assert report["steps"][-1]["native_metrics"]["non_passing_steps"] == 1


@pytest.mark.parametrize("code,inputs,status", [(0, (), "PASS"), (1, (), "FAIL"),
                                                   (0, ("absent.v",), "NOT_MEASURED")])
def test_report_only_row_reuses_its_producer_verdict(tmp_path, code, inputs, status):
    producer = command_row("producer", code=code, inputs=inputs)
    reader = command_row("reader")
    reader.update(tool={"kind": "native_report", "from": "producer"}, checks=[])
    result = execute(tmp_path, [producer, reader])
    assert [row["status"] for row in result["steps"]] == [status, status]


def test_native_decimal_and_infinite_path_group_values(tmp_path):
    checks = [{"metric": "slack", "operator": ">=", "limit": Decimal("0")}]
    measured = engine.measure(checks, {"slack": Decimal("1.2")}, {}, {"always": True})
    assert measured[0]["status"] == "PASS"
    infinite = engine.measure(checks, {"slack": float("inf")}, {}, {"always": True})
    assert infinite[0]["status"] == "NOT_MEASURED"
    path = tmp_path / "result.json"
    engine.write_json(path, {"metrics": measured, "absent_path_group": float("inf")})
    assert json.loads(path.read_text())["absent_path_group"] == "Infinity"


def test_known_failure_survives_an_independent_missing_tool():
    outcome = engine.ToolResult(True, 0, native_steps=[{"ran": True}, {"ran": False}])
    assert engine.evaluate(outcome, [{"status": "FAIL"}]) == "FAIL"


def test_native_missing_report_is_not_a_chip_failure():
    outcome = engine.ToolResult(True, 1, native_steps=[
        {"ran": True, "exit_code": 1, "status": "NOT_MEASURED"}])
    assert engine.evaluate(outcome, [{"status": "NOT_MEASURED"}]) == "NOT_MEASURED"


def test_existing_native_results_survive_an_added_table_entry(tmp_path):
    row = command_row("existing")
    counter = tmp_path / "calls"
    row["tool"]["command"][2] = (
        "import pathlib; p=pathlib.Path('calls'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1'); "
        + row["tool"]["command"][2])
    execute(tmp_path, [row])
    result = execute(tmp_path, [row, command_row("added")])
    assert counter.read_text() == "1"
    assert result["pass"] == 2


def test_bounded_lint_resume_reads_owner_numbers_without_librelane(tmp_path, monkeypatch):
    import flow_engine_frontend
    calls = []

    def lint(self, directory, kind):
        calls.append(kind)
        return {"ran": True, "exit_code": 0, "metrics": {"errors": 0},
                "native_steps": [{"name": "verilator", "ran": True,
                                  "exit_code": 0, "status": "PASS"}]}

    def unavailable(self):
        raise ModuleNotFoundError("No module named 'librelane'")

    monkeypatch.setattr(flow_engine_frontend.OwnerSession, "result", lint)
    monkeypatch.setattr(engine.NativeChain, "initialize", unavailable)
    row = command_row("lint")
    row["tool"] = {"kind": "librelane", "steps": ["Verilator.Lint", "Checker.LintErrors"]}
    assert execute(tmp_path, [row])["pass"] == 1
    assert execute(tmp_path, [row])["pass"] == 1
    assert calls == ["rtl_validate", "rtl_validate"]


def test_adapter_accepts_explicit_rtl_and_top_without_document_defaults(tmp_path):
    from flow_native_adapters import inputs
    rtl = tmp_path / "provided.v"
    rtl.write_text("module provided; endmodule\n")
    assert inputs(tmp_path, {"rtl": ["provided.v"], "top": "provided"}) == ([rtl], "provided")


def test_document_owner_runs_before_feature_selection(tmp_path, monkeypatch):
    import flow_engine_frontend
    calls = []

    def extract(self, directory, kind):
        calls.append(kind)
        docs = tmp_path / "phase1/generated_docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "L1.json").write_text(json.dumps({"features": {"requires_ir": True}}))
        return {"ran": True, "exit_code": 0, "metrics": {"errors": 0}}

    monkeypatch.setattr(flow_engine_frontend.OwnerSession, "result", extract)
    first, second = command_row("documents"), command_row("after_extraction")
    first["tool"] = {"kind": "adapter", "program": "phase1_one_shot_runner.py", "function": "doc_extract"}
    second["when"] = "requires_ir"
    report = execute(tmp_path, [first, second])
    assert calls == ["phase1"]
    assert [row["name"] for row in report["steps"]] == ["documents", "after_extraction"]
    assert report["pass"] == 2


def test_unselected_profile_does_not_require_its_reports(tmp_path):
    row = command_row("conditional")
    row["tool"] = {"kind": "profiles", "profiles": [
        {"when": "always", "tool": row["tool"]},
        {"when": "otherwise", "tool": command_row("unused")["tool"]}]}
    row["checks"].append({"metric": "unused_report", "operator": "<=", "limit": 0, "when": "otherwise"})
    assert execute(tmp_path, [row])["steps"][0]["status"] == "PASS"


def test_list_valued_document_features_do_not_abort_the_chain(tmp_path):
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(json.dumps({"features": ["register interface"], "fields": []}))
    assert execute(tmp_path, [command_row("measure")])["pass"] == 1


def test_from_does_not_restore_an_invalidated_later_state(tmp_path, monkeypatch):
    restored = []
    monkeypatch.setattr(engine.NativeChain, "initialize", lambda self: None)
    monkeypatch.setattr(engine.NativeChain, "restore", lambda self, path: restored.append(path.name))
    rows = [command_row(name) for name in ("first", "middle", "last")]
    rows[0]["tool"]["command"][2] = (
        "import pathlib,sys; pathlib.Path(sys.argv[1]).with_name('state_out.json').write_text('{}'); "
        + rows[0]["tool"]["command"][2])
    execute(tmp_path, rows)
    (tmp_path / "steps/middle/state_out.json").write_text("{}")
    execute(tmp_path, rows, from_name="first", to_name="first")
    execute(tmp_path, rows, from_name="last")
    assert restored == ["first"]
