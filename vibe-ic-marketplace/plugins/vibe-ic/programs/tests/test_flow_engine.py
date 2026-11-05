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
    execute(tmp_path, rows, from_name="first", to_name="first")
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
    ("ip_hardmacro", "spec_generation", "D1", "37.5ip", 39),
    ("shippable_gds", "spec_generation", "D1", "37.5ic", 41),
])
def test_real_structured_routes_keep_bounded_closure_and_full_physical_windows(
        tmp_path, target, nature, entry, exit_step, count):
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
    table = engine.read_json(engine.TABLE)
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
        assert selected[0]["name"] == "requirements_and_delivery_route"
        assert selected[-1]["name"] == ("ip_release_views_and_documentation"
                                          if target == "ip_hardmacro" else "compliance_and_final_adoption")


@pytest.mark.parametrize("watts,status", [(0.004, "PASS"), (0.005, "FAIL"),
                                          (0.0416, "FAIL"), (None, "NOT_MEASURED")])
def test_power_report_compares_declared_tt_limit_instead_of_inheriting_pass(tmp_path, watts, status):
    docs = tmp_path / "input/docs"
    docs.mkdir(parents=True)
    (docs / "quality.md").write_text("| total power(TT) | < 5 mW | sign-off |\n")
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
    checks = declared_power_checks(tmp_path)
    assert len(checks) == 1
    measured = engine.measure(checks, {"power__total__corner:nom_tt": watts}, {}, {"always": True})
    assert measured[0]["status"] == "FAIL"
    assert engine.evaluate(engine.ToolResult(True, 0), measured) == "FAIL"
