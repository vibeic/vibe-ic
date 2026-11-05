import json
from copy import deepcopy
from pathlib import Path
import sys
import subprocess
from decimal import Decimal

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import flow_engine as engine


@pytest.fixture(params=["installed", "regenerated"])
def physical_step_table(request, tmp_path):
    if request.param == "installed":
        return engine.read_json(engine.TABLE)
    output = tmp_path / "steps.json"
    subprocess.run([sys.executable, str(engine.HERE / "flow_steps_generate.py"),
                    "--output", str(output)], check=True)
    return engine.read_json(output)


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


@pytest.mark.parametrize("errors,status", [(0, "PASS"), (1, "FAIL")])
def test_manufacturability_runs_its_own_screen_before_aggregation(
        tmp_path, monkeypatch, errors, status, physical_step_table):

    routed = tmp_path / "captured.def"
    routed.write_text("""VERSION 5.8 ;
DESIGN unit ;
VIAS 1 ;
- cut + VIARULE vr + CUTSIZE 200 200 + ROWCOL 1 1 ;
END VIAS
NETS 1 ;
- signal ( inst A ) + ROUTED met1 ( 0 0 ) cut ( 1 0 ) ;
END NETS
""")
    initialize = engine.NativeChain.__init__
    def configured(chain, *args, **kwargs):
        initialize(chain, *args, **kwargs)
        chain.state = {"def": str(routed)}
    monkeypatch.setattr(engine.NativeChain, "__init__", configured)
    names = {"design_for_manufacturability", "final_electrical_analysis", "signoff_aggregation"}
    rows = [deepcopy(row) for row in physical_step_table["steps"] if row["name"] in names]
    measurement = command_row("final_electrical_analysis", errors)
    for row in rows:
        row["when"] = "always"
        if row["name"] == measurement["name"]:
            row["tool"], row["checks"] = measurement["tool"], measurement["checks"]
        elif row["name"] == "design_for_manufacturability":
            row["tool"]["routed_def"] = str(routed)
    report = execute(tmp_path, rows)
    actual = {row["name"]: row for row in report["steps"]}
    screen = actual["design_for_manufacturability"]
    assert screen["status"] == "PASS"
    assert screen["native_metrics"]["signal_via_uses"] == 1
    assert screen["native_metrics"]["single_cut_fraction"] == 1
    assert actual["final_electrical_analysis"]["status"] == status
    assert actual["signoff_aggregation"]["status"] == status
    assert actual["signoff_aggregation"]["native_metrics"]["non_passing_steps"] == errors


@pytest.mark.parametrize("bounded", [False, True])
def test_from_preserves_results_outside_explicit_window(tmp_path, bounded):
    rows = [command_row(name) for name in ("first", "middle", "last")]
    execute(tmp_path, rows)
    prior = (tmp_path / "steps/first/result.json").read_bytes()
    later = tmp_path / "steps/last/result.json"
    saved = later.read_bytes()
    state = later.with_name("state_out.json")
    state.write_text("original native state\n")
    rows[-1] = command_row("last", value=1)
    execute(tmp_path, rows, from_name="middle", to_name="middle" if bounded else None)
    assert (tmp_path / "steps/first/result.json").read_bytes() == prior
    if bounded:
        assert later.read_bytes() == saved
        assert state.read_text() == "original native state\n"
    else:
        assert json.loads(later.read_text())["status"] == "FAIL"
        assert not state.exists()
    assert json.loads((tmp_path / "steps/middle/result.json").read_text())["status"] == "PASS"


def test_bounded_replay_recomputes_later_aggregates_without_rerunning_tools(tmp_path):
    aggregate = {"name": "summary", "title": "summary", "when": "always", "legacy_id": {},
                 "tool": {"kind": "aggregate"}, "checks": [
                     {"metric": "non_passing_steps", "operator": "==", "limit": 0}]}
    rows = [command_row("first"), command_row("middle", value=1), command_row("physical"),
            aggregate, {**aggregate, "name": "final_summary", "title": "final_summary"}]
    execute(tmp_path, rows)
    physical = tmp_path / "steps/physical/result.json"
    saved = physical.read_bytes()
    rows[1] = command_row("middle")
    report = execute(tmp_path, rows, from_name="middle", to_name="middle")
    assert physical.read_bytes() == saved
    assert report["selected"] == report["run"] == report["pass"] == 1
    for name in ("summary", "final_summary"):
        result = json.loads((tmp_path / "steps" / name / "result.json").read_text())
        assert result["status"] == "PASS"
        assert result["native_metrics"]["non_passing_steps"] == 0


def test_added_table_entry_runs_without_runner_change(tmp_path):
    report = execute(tmp_path, [command_row("existing"), command_row("new_step")])
    assert report["pass"] == 2
    assert (tmp_path / "steps/new_step/tool.log").is_file()


def test_progress_uses_full_table_order_after_filtering_and_insertion(tmp_path, capsys):
    rows = [command_row(name) for name in ("first", "inapplicable", "selected")]
    rows[1]["when"] = "False"
    execute(tmp_path, rows, from_name="selected", to_name="selected")
    assert capsys.readouterr().out == "第 3 步 selected: PASS\n"

    rows.insert(0, command_row("inserted"))
    execute(tmp_path, rows, from_name="selected", to_name="selected")
    assert capsys.readouterr().out == "第 4 步 selected: PASS\n"


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


@pytest.mark.parametrize("input_contract", ["original", "structured"])
def test_debug_entry_runs_the_router_declared_prerequisite_closure(tmp_path, input_contract):
    rows = [command_row(name) for name in ("requirements", "author", "lint", "unselected", "simulation", "floorplan")]
    for row, native in zip(rows, ("D1", "1", "2", "3", "4", "15")):
        row["legacy_id"] = {"registry": "", "native": [native]}
    route = {"task_nature": "debug", "entry_step": "4", "verify_through": "4",
             "delivery_target": "rtl", "input_contract": input_contract,
             "verify_closed_steps": ["D1", "0.5ic", "1", "2", "4"]}
    report = engine.run(tmp_path, table={"steps": rows}, route=route)
    assert [row["name"] for row in report["steps"]] == ["requirements", "author", "lint", "simulation"]
    assert report["route"] == route


def test_missing_limit_never_becomes_pass(tmp_path):
    row = command_row("unlimited")
    row["checks"][0]["limit"] = None
    assert execute(tmp_path, [row])["steps"][0]["status"] == "NOT_MEASURED"


def test_successful_tool_without_remaining_checks_passes(tmp_path):
    row = command_row("native_exit")
    row["checks"] = []
    assert execute(tmp_path, [row])["steps"][0]["status"] == "PASS"


def test_ic_stream_out_does_not_require_a_macro_lef():
    pytest.importorskip("librelane")
    from librelane.flows.chip import Chip
    from librelane.flows.classic import Classic
    from librelane.steps import Step
    from flow_steps_generate import generate

    root = engine.TABLE.parent.parent
    table, _, _ = generate(
        json.loads((root / "flow/flow109.json").read_text()),
        json.loads((root / "flow/native_limits.json").read_text()))
    features = {"ic": True, "analog_physical": False,
                "digital_physical": True, "assembly_only": False}
    available = {"gds", "def", "odb", "mag_gds", "klayout_gds"}
    removed = {step.id for step in Classic.Steps} - {step.id for step in Chip.Steps}
    for candidate in (table, engine.read_json(engine.TABLE)):
        row = next(item for item in candidate["steps"] if item["name"] == "stream_out")
        selected = engine.choose_tool(row["tool"], features)
        missing = {name: [item.id for item in Step.factory.get(name).inputs
                          if not item.optional and item.id not in available]
                   for name in selected["steps"]}
        assert {name: views for name, views in missing.items() if views} == {}

        classic = engine.choose_tool(row["tool"], {**features, "ic": False})
        assert [name for name in classic["steps"] if name in removed] == [
            "Magic.WriteLEF", "Odb.CheckDesignAntennaProperties"]


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


@pytest.mark.parametrize("errors", [0, 1])
def test_later_producer_report_is_read_before_its_aggregate(tmp_path, errors):
    reader = command_row("reader")
    reader.update(tool={"kind": "native_report", "from": "producer"}, checks=[])
    aggregate = command_row("summary")
    aggregate.update(tool={"kind": "aggregate"}, checks=[
        {"metric": "non_passing_steps", "operator": "==", "limit": 0}])
    result = execute(tmp_path, [reader, aggregate, command_row("producer", value=errors)])
    rows = {row["name"]: row for row in result["steps"]}
    assert rows["reader"]["status"] == rows["producer"]["status"] == ("FAIL" if errors else "PASS")
    assert rows["summary"]["native_metrics"]["non_passing_steps"] == errors


@pytest.mark.parametrize("declared,status", [(False, "PASS"), (True, "FAIL")])
def test_intermediate_number_blocks_only_on_a_declared_bound(tmp_path, declared, status):
    row = command_row("intermediate", value=7)
    row["checks"] = []
    row["observations"] = [{"metric": "intermediate_bound", "native_metrics": ["errors"],
                             "operator": "<=", "limit": None,
                             "declared_limit_from": {"metric": "intermediate_bound"}}]
    if declared:
        docs = tmp_path / "phase1/generated_docs"
        docs.mkdir(parents=True)
        (docs / "L19.json").write_text(json.dumps({"fields": {"intermediate_bound": 5}}))
    result = execute(tmp_path, [row])["steps"][0]
    assert result["status"] == status
    assert result["observations"][0]["values"] == {"errors": 7}


def test_declared_observation_cannot_drop_a_missing_native_number(tmp_path):
    native = engine.ToolResult(True, 0, {"setup": 1})
    row = {"observations": [{"metric": "timing", "native_metrics": ["setup", "hold"],
                            "operator": "within_declared_bounds",
                            "limit": {"setup": {"min": 0}, "hold": {"min": 0}}}]}
    _, checks = engine.report_observations(row, tmp_path, native, {}, {"always": True}, tmp_path)
    measured = engine.measure(checks, native.metrics, {}, {"always": True}, tmp_path)
    assert [item["status"] for item in measured] == ["PASS", "NOT_MEASURED"]
    assert engine.evaluate(native, measured) == "NOT_MEASURED"


@pytest.mark.parametrize("category", ["line", "toggle", "branch"])
def test_zero_native_coverage_points_have_no_percentage_floor(category):
    metric = f"coverage_{category}_pct"
    numbers = {f"coverage_{category}_points": 0}
    native = engine.ToolResult(True, 0, numbers)
    checks = [{"metric": metric, "operator": ">=", "limit": 70}]
    measured = engine.measure(checks, numbers, {}, {"always": True})
    assert measured[0]["status"] == "NOT_APPLICABLE"
    assert measured[0]["points"] == 0 and measured[0]["value"] is None
    assert measured[0]["limit"] == 70 and measured[0]["reason"]
    assert engine.evaluate(native, measured) == "PASS"


@pytest.mark.parametrize("points", [None, False, 1])
def test_missing_or_nonempty_coverage_population_keeps_missing_percentage_unmeasured(points):
    numbers = {"coverage_branch_points": points} if points is not None else {}
    measured = engine.measure([{"metric": "coverage_branch_pct", "operator": ">=", "limit": 70}],
                              numbers, {}, {"always": True})
    assert measured[0]["status"] == "NOT_MEASURED"


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


def test_new_invocation_runs_existing_and_added_entries(tmp_path):
    row = command_row("existing")
    counter = tmp_path / "calls"
    row["tool"]["command"][2] = (
        "import pathlib; p=pathlib.Path('calls'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1'); "
        + row["tool"]["command"][2])
    execute(tmp_path, [row])
    result = execute(tmp_path, [row, command_row("added")])
    assert counter.read_text() == "2"
    assert result["pass"] == 2


@pytest.mark.parametrize("input_contract", ["original", "structured"])
def test_bounded_lint_resume_reads_owner_numbers_without_librelane(tmp_path, monkeypatch, input_contract):
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
    route = {"entry_step": "lint", "verify_through": "lint",
             "delivery_target": "rtl", "input_contract": input_contract}
    assert engine.run(tmp_path, table={"steps": [row]}, route=route)["pass"] == 1
    assert engine.run(tmp_path, table={"steps": [row]}, route=route)["pass"] == 1
    assert calls == ["rtl_validate", "rtl_validate"]


@pytest.mark.parametrize("explicit_from", [False, True])
def test_author_refresh_preserves_failure_and_uses_current_ai_output(tmp_path, monkeypatch, explicit_from):
    import flow_engine_frontend
    calls = []
    rtl = tmp_path / "phase2/stage1/rtl/unit.v"

    def author(self, directory, kind):
        calls.append(kind)
        produced = rtl.is_file()
        return {"ran": True, "exit_code": 0 if produced else 1,
                "native_steps": [{"name": "rtl_output", "ran": True,
                    "status": "PASS" if produced else "FAIL", "exit_code": 0 if produced else 1,
                    "source": {"author": {"kind": "AI", "model": "recorded-model"}}}]}

    monkeypatch.setattr(flow_engine_frontend.OwnerSession, "result", author)
    row = command_row("author")
    row.update(tool={"kind": "adapter", "function": "step_rtl_gen"}, checks=[])
    assert execute(tmp_path, [row])["fail"] == 1
    old = (tmp_path / "steps/author/result.json").read_bytes()
    (tmp_path / "steps/author/native-author.log").write_text("original author failure\n")
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module unit(input a,output y); assign y=a; endmodule\n")
    report = execute(tmp_path, [row], **({"from_name": "author"} if explicit_from else {}))
    assert report["pass"] == 1
    assert calls == ["rtl_gen", "rtl_gen"]
    current = report["steps"][0]["native_steps"][0]
    assert current["source"]["author"]["kind"] == "AI"
    history = list((tmp_path / "steps/author/author_history").glob("*/result.json"))
    assert len(history) == 1 and history[0].read_bytes() == old
    assert (history[0].parent / "native-author.log").read_text() == "original author failure\n"


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
    execute(tmp_path, rows, from_name="first")
    assert not (tmp_path / "steps/middle/state_out.json").exists()
    execute(tmp_path, rows, from_name="last")
    assert restored == ["first"]


def test_resume_accounts_preparation_before_a_non_native_interval(tmp_path, monkeypatch):
    import subprocess
    import time
    rows = [command_row(name) for name in ("previous", "resumed", "later")]
    execute(tmp_path, rows)
    (tmp_path / "steps/previous/state_out.json").write_text("{}")
    observed = []
    def initialize(chain):
        started = time.perf_counter()
        subprocess.run([sys.executable, "-c", "pass"], check=True)
        elapsed = time.perf_counter() - started
        observed.append(elapsed)
        chain.observe_preparation({"name": "test-sizing-tool", "ran": True,
            "exit_code": 0, "status": "PASS", "tool_seconds": elapsed,
            "reports": str(tmp_path / "sizing")})
    monkeypatch.setattr(engine.NativeChain, "initialize", initialize)
    monkeypatch.setattr(engine.NativeChain, "restore", lambda chain, directory: None)
    report = execute(tmp_path, rows, from_name="resumed")
    first, later = report["steps"]
    assert len(observed) == 1
    assert first["native_steps"][0]["name"] == "test-sizing-tool"
    assert first["tool_seconds"] >= observed[0] > 0
    assert first["wall_seconds"] >= first["tool_seconds"]
    assert first["program_seconds"] + first["tool_seconds"] == pytest.approx(first["wall_seconds"])
    assert not later["native_steps"]


@pytest.mark.parametrize("declared,status", [(False, "PASS"), (True, "FAIL")])
def test_coverage_observes_numbers_and_enforces_declared_targets(tmp_path, declared, status):
    table = engine.read_json(engine.TABLE)
    row = next(row for row in table["steps"] if row["name"] == "functional_simulation_and_coverage")
    numbers = {"assertion_failures": 0, "coverage_line_pct": 75,
               "coverage_toggle_pct": 65, "coverage_branch_pct": 80}
    if declared:
        docs = tmp_path / "phase1/generated_docs"
        docs.mkdir(parents=True)
        (docs / "L7.json").write_text(json.dumps({
            "coverage_targets": {"coverage_line_pct": {"min": 90}}}))
    features = engine.design_features(tmp_path, {"delivery_target": "rtl"}, table)
    native = engine.ToolResult(True, 0, numbers)
    observations, declared_checks = engine.report_observations(
        row, tmp_path, native, {}, features, tmp_path)
    measurements = engine.measure([*row["checks"], *declared_checks], numbers,
                                  {}, features, tmp_path)
    assert engine.evaluate(native, measurements) == status
    coverage = next(item for item in observations if item["metric"] == "coverage_targets")
    assert coverage["values"] == {key: value for key, value in numbers.items() if key.startswith("coverage_")}
    assert [(item["metric"], item["limit"]) for item in row["checks"]
            if item["metric"].startswith("coverage_")] == [
                ("coverage_line_pct", 70), ("coverage_toggle_pct", 60), ("coverage_branch_pct", 70)]


@pytest.mark.parametrize("filters", [None, [], [""]])
def test_empty_corner_filter_keeps_native_numbers_and_original_limit(filters):
    check = {"metric": "slew__corner:*", "operator": "<=", "limit": 0,
             "corner_config": "CORNERS"}
    metrics = {"slew__corner:nom_ss": 0, "slew__corner:max_ss": 1}
    observed = engine.measure([check], metrics, {"CORNERS": filters}, {"always": True})
    assert [(item["metric"], item["status"]) for item in observed] == [
        ("slew__corner:nom_ss", "PASS"), ("slew__corner:max_ss", "FAIL")]
    assert engine.evaluate(engine.ToolResult(True, 0), observed) == "FAIL"
    selected = engine.measure([check], metrics, {"CORNERS": ["nom_*"]}, {"always": True})
    assert [item["metric"] for item in selected] == ["slew__corner:nom_ss"]


def test_report_reuse_cannot_hide_failed_resume_preparation(tmp_path, monkeypatch):
    import subprocess
    import time
    previous, reused = command_row("previous"), command_row("reused")
    reused.update(tool={"kind": "native_report", "from": "previous"}, checks=[])
    execute(tmp_path, [previous, reused])
    (tmp_path / "steps/previous/state_out.json").write_text("{}")
    def initialize(chain):
        started = time.perf_counter()
        process = subprocess.run([sys.executable, "-c", "raise SystemExit(3)"])
        chain.observe_preparation({"name": "test-sizing-tool", "ran": True,
            "exit_code": process.returncode, "status": "FAIL",
            "tool_seconds": time.perf_counter() - started,
            "reports": str(tmp_path / "sizing")})
        raise ValueError("preparation failed")
    monkeypatch.setattr(engine.NativeChain, "initialize", initialize)
    result = execute(tmp_path, [previous, reused], from_name="reused")["steps"][0]
    assert result["status"] == "FAIL"
    assert result["tool_exit_code"] == 3
    assert result["tool_seconds"] > 0


@pytest.mark.parametrize("value,status", [(1, "PASS"), (0, "NOT_MEASURED"), (None, "NOT_MEASURED")])
def test_native_seal_skip_is_missing_measurement_and_verifier_failure_still_fails(value, status):
    row = next(row for row in engine.read_json(engine.TABLE)["steps"]
               if row["name"] == "seal_ring_and_die_identification")
    measured = engine.measure(row["checks"], {"design__seal_ring__verified": value}, {},
                              {"always": True, "ic": True, "owner_die": True})
    assert len(measured) == 1
    assert measured[0]["value"] == value
    assert measured[0]["limit"] == 1
    assert measured[0]["status"] == status
    assert engine.evaluate(engine.ToolResult(True, 0), measured) == status
    failed = engine.ToolResult(True, 1, native_steps=[{
        "name": "KLayout.SealRing", "ran": True, "status": "FAIL", "exit_code": 1}])
    assert engine.evaluate(failed, measured) == "FAIL"


@pytest.mark.parametrize("target,nature,entry,exit_step,count", [
    ("rtl", "debug", "4", "4", 4),
    ("ip_hardmacro", "spec_generation", "D1", "37.5ip", 44),
    ("shippable_gds", "spec_generation", "D1", "37.5ic", 51),
])
def test_real_structured_routes_keep_bounded_closure_and_full_physical_windows(
        tmp_path, target, nature, entry, exit_step, count, physical_step_table):
    import task_nature_route as router
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({"clock_domains": [
        {"domain_kind": "primary", "source_pin": "clk", "period_ns": 20}]}))
    route = router.route_decision_receipt(
        "Debug a synchronous counter." if nature == "debug" else
        "Build a synchronous counter from the design documents.",
        nature=nature, delivery_target=target)
    route = {**route, "input_contract": "structured"}
    assert (route["entry_step"], route["verify_through"]) == (entry, exit_step)
    table = physical_step_table
    features = engine.design_features(tmp_path, route, table)
    selected = engine.select_steps(table, route, features, None, None)
    assert len(selected) == count
    names = {row["name"] for row in selected}
    if target == "rtl":
        assert names == {"requirements_and_delivery_route", "rtl_authoring",
                         "rtl_validation_and_lint", "functional_simulation_and_coverage"}
    else:
        assert {"formal_verification", "functional_simulation_and_coverage",
                "implemented_netlist_cdc_and_rdc", "final_geometry_rc_and_pex",
                "final_electrical_analysis", "final_sdf_gate_level_replay"} <= names
        if target == "shippable_gds":
            assert {"candidate_signal_integrity", "post_layout_spice_correlation",
                    "candidate_reliability_and_esd", "final_perc_esd_and_latch_up"} <= names
        assert selected[0]["name"] == "requirements_and_delivery_route"
        assert selected[-1]["name"] == ("ip_release_views_and_documentation"
                                          if target == "ip_hardmacro" else "tapeout_precheck")
        for name, native_step, values in (
            ("candidate_signal_integrity", "VibeIC.SignalIntegrity",
             {"si_setup_slack_ns": 0, "si_hold_slack_ns": 0}),
            ("candidate_electromigration", "VibeIC.EMCorners",
             {"em_violations": 0, "em_worst_utilization_pct": 100}),
        ):
            row = next(row for row in selected if row["name"] == name)
            assert engine.choose_tool(row["tool"], features)["steps"] == [native_step]
            measured = engine.measure(row["checks"], values, {}, features)
            assert {item["metric"] for item in measured} == set(values)
            assert engine.evaluate(engine.ToolResult(True, 0), measured) == "PASS"
            for metric in values:
                bad = {**values, metric: -0.01 if metric.startswith("si_") else values[metric] + 1}
                assert engine.evaluate(engine.ToolResult(True, 0),
                                       engine.measure(row["checks"], bad, {}, features)) == "FAIL"


@pytest.mark.parametrize("watts,status,statement", [
    (0.004, "PASS", "< 5 mW"), (0.005, "FAIL", "< 5 mW"),
    (0.0416, "FAIL", "< 5 mW"), (None, "NOT_MEASURED", "< 5 mW"),
    (0.0416, "PASS", "5 mW"),
    (0.0416, "PASS", "< 5 mW at gf180mcuD, 24 ns")])
def test_power_report_compares_declared_tt_limit_instead_of_inheriting_pass(tmp_path, monkeypatch, watts, status, statement):
    initialize = engine.NativeChain.__init__
    def configured(chain, *args, **kwargs):
        initialize(chain, *args, **kwargs)
        chain.config = {"STA_CORNERS": ["nom_tt_025C_1v80"]}
    monkeypatch.setattr(engine.NativeChain, "__init__", configured)
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "quality.md").write_text(f"| total power(TT) | {statement} | sign-off |\n")
    table = engine.read_json(engine.TABLE)
    row = next(row for row in table["steps"] if row["name"] == "candidate_power_analysis")
    features = engine.design_features(tmp_path, {"delivery_target": "ip_hardmacro"}, table)
    row = {**row, "when": "always", "tool": {
        **engine.choose_tool(row["tool"], features), "from": "producer"}}
    producer = command_row("producer")
    metrics = {"power__total__corner:nom_ff": 0.999}
    if watts is not None:
        metrics["power__total__corner:nom_tt"] = watts
    producer["checks"] = []
    producer["tool"]["command"][2] = (
        "import json,pathlib,sys; pathlib.Path(sys.argv[1]).write_text("
        + repr(json.dumps(metrics)) + ")")
    result = execute(tmp_path, [producer, row])["steps"][-1]
    assert result["status"] == status
    if statement != "< 5 mW":
        assert result["metrics"] == []
        observation = result["observations"][-1]
        assert observation["status"] == "NOT_APPLICABLE"
        assert observation["applicable"] is False
        return
    assert len(result["metrics"]) == 1
    check = result["metrics"][0]
    assert check["operator"] == "within_declared_bounds"
    assert check["limit"] == {"max": 0.005, "max_exclusive": True}
    assert check["unit"] == "W"
    assert check["source"]["line"] == 1
    assert "pad" in check["scope"].lower()


@pytest.mark.parametrize("milliwatts,watts", [("5", Decimal("0.005")),
                                           ("41.6", 0.0416), ("41.6", Decimal("0.0416"))])
def test_strict_power_ceiling_rejects_decimal_and_float_equality(tmp_path, milliwatts, watts):
    from flow_config import declared_power_checks
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "quality.md").write_text(
        f"Total power (including core power and pads) < {milliwatts} mW at TT.\n")
    checks = declared_power_checks(tmp_path, metrics={"power__total__corner:nom_tt": watts})
    assert len(checks) == 1 and checks[0].get("applicable") is not False
    measured = engine.measure(checks, {"power__total__corner:nom_tt": watts}, {}, {"always": True})
    assert measured[0]["status"] == "FAIL"
    assert engine.evaluate(engine.ToolResult(True, 0), measured) == "FAIL"


def test_view_snapshot_cannot_replace_the_ip_document_program(tmp_path, monkeypatch):
    import flow_native_adapters

    name = 'ip_release_views_and_documentation'
    directory = tmp_path / 'steps' / name
    monkeypatch.setattr(engine.NativeChain, 'snapshot', lambda *args:
                        engine.ToolResult(True, 0, {'design__instance__count': 1}))
    snapshot = {'name': name, 'title': 'IP release views and documentation',
                'when': 'always', 'legacy_id': {}, 'checks': [],
                'tool': {'kind': 'snapshot', 'destination': 'exported', 'formats': {}}}
    assert execute(tmp_path, [snapshot])['steps'][0]['status'] == 'PASS'
    calls = []

    def produce(project, step, tool, route, **kwargs):
        calls.append(tool['adapter'])
        (step / 'IP_DATASHEET.md').write_text('Current native interface.')
        return {'ran': True, 'exit_code': 0, 'metrics': {'release_documents': 6},
                'reports': [str(step / 'IP_DATASHEET.md')]}

    monkeypatch.setattr(flow_native_adapters, 'execute', produce)
    row = {'name': name, 'title': 'IP release views and documentation',
           'when': 'always', 'legacy_id': {}, 'checks': [],
           'tool': {'kind': 'adapter', 'adapter': 'ip_release_docs'}}
    report = execute(tmp_path, [row])
    assert calls == ['ip_release_docs']
    assert (directory / 'IP_DATASHEET.md').is_file()
    assert report['steps'][0]['native_metrics']['release_documents'] == 6
