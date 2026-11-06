from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

import analog_native_flow
import flow_native_analog as analog
from flow_native_adapters import Commands


def project_at(tmp_path, specs=None):
    project = tmp_path / "project"
    docs = project / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L5_ADI_SPEC.json").write_text(json.dumps({"analog_blocks": [
        {"name": "unit", "type": "ldo", "spec": {"specs": specs or [{"name": "Vout", "min": 1.1, "max": 1.3}]}}
    ]}))
    return project


class CapturedCommands(Commands):
    def __init__(self, directory, report=None):
        super().__init__(directory)
        self.calls = []
        self.report = report

    def run(self, argv, cwd=None, *, input_text=None):
        self.calls.append((list(argv), cwd, input_text))
        log = self.directory / f"command_{len(self.records) + 1}.log"
        log.write_text("native tool output\n")
        self.records.append({"command": list(argv), "exit_code": 0, "log": str(log)})
        if self.report is not None and "--json" in argv:
            Path(argv[argv.index("--json") + 1]).write_text(json.dumps(self.report))
        elif self.report is not None and "-c" in argv:
            Path(argv[-1]).write_text(json.dumps(self.report))
        return subprocess.CompletedProcess(argv, 0, "native tool output", "")


@pytest.mark.parametrize("step", analog.ANALOG_STEPS[:-1])
def test_each_analog_connection_calls_existing_native_dispatch(tmp_path, monkeypatch, step):
    project = project_at(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    calls = []

    def dispatch(selected, current_project, block, options, run):
        calls.append((selected, current_project, block, options))
        execution = run("@ngspice", ["-b", "unit.sp"], cwd=project)
        return {"status": "PASS", "detail": "native number", "executions": [execution],
                "metrics": {"output_voltage": 1.2}, "outputs": []}

    monkeypatch.setattr(analog_native_flow, "_dispatch", dispatch)
    commands = CapturedCommands(output)
    result = analog.execute(project, output, {"step": next(name for name, native in analog.NATIVE_STEPS.items() if native == step)}, commands)
    assert result["ran"] is True
    assert result["metrics"]["output_voltage"] == 1.2
    assert result["native_steps"][0]["status"] == "PASS"
    assert commands.calls[0][0] == ["ngspice", "-b", "unit.sp"]
    selected, current_project, block, options = calls[0]
    assert (selected, current_project, block["name"]) == (step, project, "unit")
    assert (options["transport"], options["container"], options["image"]) == ("HOST", "", "")
    assert not (project / "phase3/analog/analog_block_list.json").exists()


def test_bridge_runs_python_producer_and_preserves_outputs_and_stdin(tmp_path):
    commands = CapturedCommands(tmp_path)
    missing = tmp_path / "missing.json"
    result = analog.command_bridge(commands, tmp_path)(
        "analog_native_sim.py", ["run"], outputs=[missing], input_text="native input")
    assert commands.calls[0][0][1] == str(analog.HERE / "analog_native_sim.py")
    assert commands.calls[0][2] == "native input"
    assert result["returncode"] == 0
    assert result["stdout"] == "native tool output"
    assert result["missing_outputs"] == [str(missing)]


def test_missing_executable_does_not_claim_a_tool_ran(tmp_path, monkeypatch):
    commands = Commands(tmp_path)
    monkeypatch.setattr(commands, "run", lambda *args, **kwargs: None)
    result = analog.command_bridge(commands, tmp_path)("@ngspice", ["-b", "unit.sp"])
    assert result["returncode"] == 127
    assert result["log"] is None
    assert "ngspice" in result["stderr"]
    assert commands.result()["ran"] is False


def test_native_state_branch_preserves_exit_code_and_tool_results(tmp_path, monkeypatch):
    project = project_at(tmp_path)
    output = tmp_path / 'output'
    output.mkdir()
    native = {'name': 'Magic.RCX', 'ran': True, 'exit_code': 17, 'status': 'FAIL'}
    monkeypatch.setattr(analog, '_branch', lambda *args: {
        'status': 'FAIL', 'detail': 'native extraction failed', 'native_ran': True,
        'exit_code': 17, 'native_steps': [native], 'tool_seconds': 2.5,
        'metrics': {'native_errors': 3}})
    result = analog.execute(project, output, {'step': 'candidate_parasitic_extraction'}, Commands(output))
    assert result['exit_code'] == 17
    assert native in result['native_steps']
    assert result['metrics']['native_errors'] == 3
    assert result['tool_seconds'] == 2.5


def test_a03_preserves_exact_native_unsupported_reason(tmp_path):
    project = project_at(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    result = analog.execute(project, output, {"step": next(name for name, native in analog.NATIVE_STEPS.items() if native == "A03")}, Commands(output))
    assert result["ran"] is False
    assert result["native_steps"][0]["status"] == "NOT_MEASURED"
    assert result["detail"] == "A03_TESTABILITY_IMPLEMENTATION_ABSENT: applicability is undeclared"


def test_a06_without_a_native_command_does_not_become_pass(tmp_path, monkeypatch):
    project = project_at(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    monkeypatch.setattr(analog_native_flow, "_dispatch", lambda *args: {
        "status": "PASS", "detail": "testbench already covers measurements", "metrics": {}})
    result = analog.execute(project, output, {"step": next(name for name, native in analog.NATIVE_STEPS.items() if native == "A06")}, Commands(output))
    assert result["ran"] is False
    assert result["native_steps"][0]["status"] == "NOT_MEASURED"


def test_plain_previous_native_output_is_available_to_dependent_steps(tmp_path, monkeypatch):
    project = project_at(tmp_path)
    previous = project / "steps/nominal/analog_results.json"
    previous.parent.mkdir(parents=True)
    previous.write_text(json.dumps({"blocks": [{"step": "A07", "block": "unit", "status": "PASS",
                                                "metrics": {"output_voltage": 1.2}}]}))
    output = tmp_path / "output"
    output.mkdir()
    seen = []

    def dispatch(step, project, block, options, run):
        seen.append(options["previous_results"]["A07"]["unit"])
        return {"status": "NOT_MEASURED", "detail": "source corner deck absent"}

    monkeypatch.setattr(analog_native_flow, "_dispatch", dispatch)
    analog.execute(project, output, {"step": "analog_pre_layout_pvt_and_operating_range"}, Commands(output))
    assert seen[0]["metrics"]["output_voltage"] == 1.2


@pytest.mark.parametrize("value,expected", [(14.01, "PASS"), (13.99, "FAIL"), (None, "NOT_MEASURED")])
def test_a19_preserves_original_resolution_limit(tmp_path, value, expected):
    project = project_at(tmp_path, [{"name": "ENOB", "min": 14, "unit": "bit"}])
    report = project / "phase3/analog/unit/corner_results.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"spec_results": [{"name": "enob", "status": "PASS"}],
        "corners": [{"name": "nominal", "simulator_run": True, "enob": value}]}))
    output = tmp_path / "output"
    output.mkdir()
    result = analog.execute(project, output, {"step": next(name for name, native in analog.NATIVE_STEPS.items() if native == "A19")}, Commands(output))
    check = result["metrics"]["spec_results"][0]
    assert check["limit"] == {"min": 14}
    assert check["value"] == value
    assert check["status"] == expected
    assert result["native_steps"][0]["status"] == expected
    assert result["ran"] is (value is not None)


def test_declared_spec_checks_keep_all_corners_unknown_specs_and_missing_numbers(tmp_path):
    project = project_at(tmp_path, [{"name": "Vout", "min": 1.1, "max": 1.3},
                                    {"name": "custom settling time", "max": 2.0}])
    report = project / "phase3/analog/unit/corner_results.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"corners": [
        {"name": "typical", "simulator_run": True, "vout_v": 1.2},
        {"name": "slow", "simulator_run": True, "vout_v": 1.4},
        {"name": "derived", "simulator_run": False, "vout_v": 1.2}]}))
    rows = analog.declared_spec_checks(project)
    assert len(rows) == 6
    assert [row["status"] for row in rows[:3]] == ["PASS", "FAIL", "NOT_MEASURED"]
    assert all(row["status"] == "NOT_MEASURED" for row in rows[3:])
    assert rows[2]["value"] is None
    assert rows[0]["source"] == str(project / "phase1/generated_docs/L5_ADI_SPEC.json")


@pytest.mark.parametrize("name", sorted(analog.BRANCHES))
def test_each_analog_die_branch_reports_missing_native_products(tmp_path, name):
    project = project_at(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    result = analog.execute(project, output, {"step": name}, Commands(output))
    assert result["native_steps"][0]["status"] == "NOT_MEASURED"
    assert result["ran"] is False
    assert result["detail"]
    assert "hand-written" not in result["detail"]
    assert "unsupported native analog step" not in result["detail"]


def test_declared_spec_checks_use_this_steps_native_number_before_corner_fallback(tmp_path):
    project = project_at(tmp_path, [{"name": "Vout", "min": 0.49, "max": 0.51}])
    metrics = {"unit": {"vout": 0.5, "native_executed": True,
                         "native_report": str(tmp_path / "nominal.json")}}
    rows = analog.declared_spec_checks(project, metrics=metrics)
    assert rows[0]["value"] == 0.5
    assert rows[0]["limit"] == {"min": 0.49, "max": 0.51}
    assert rows[0]["status"] == "PASS"
    assert rows[0]["report"] == str(tmp_path / "nominal.json")
    metrics["unit"]["native_executed"] = False
    assert analog.declared_spec_checks(project, metrics=metrics)[0]["status"] == "NOT_MEASURED"


@pytest.mark.parametrize("unit,bound,expected,value", [
    ("mV", 100, "FAIL", 500), ("V", 1, "PASS", 0.5), ("unknown", 100, "NOT_MEASURED", None)])
def test_declared_spec_checks_convert_native_voltage_to_source_units(tmp_path, unit, bound, expected, value):
    project = project_at(tmp_path, [{"name": "Vout", "max": bound, "unit": unit}])
    rows = analog.declared_spec_checks(project, metrics={"unit": {"vout": 0.5, "native_executed": True}})
    assert rows[0]["status"] == expected
    assert rows[0]["value"] == value
    assert rows[0]["native_value"] == 0.5
    assert rows[0]["limit"] == {"max": bound}


def test_declared_spec_checks_convert_native_current_to_source_units(tmp_path):
    project = project_at(tmp_path, [{"name": "Iq", "max": 3, "unit": "uA"}])
    rows = analog.declared_spec_checks(project, metrics={"unit": {"iq": 5e-6, "native_executed": True}})
    assert rows[0]["status"] == "FAIL"
    assert rows[0]["value"] == pytest.approx(5.0)


def test_malformed_source_bound_does_not_disappear_beside_a_numeric_bound(tmp_path):
    project = project_at(tmp_path, [{"name": "Vout", "min": "unstated", "max": 1}])
    rows = analog.declared_spec_checks(project, metrics={"unit": {"vout": 0.5, "native_executed": True}})
    assert rows[0]["status"] == "NOT_MEASURED"
    assert rows[0]["limit"] == {"min": "unstated", "max": 1}
    assert "malformed" in rows[0]["reason"]


def test_pvt_checks_use_raw_corner_numbers_instead_of_sweep_counters(tmp_path):
    project = project_at(tmp_path)
    report = project / "phase3/analog/unit/corner_results.json"
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({"pvt_grid": [{"name": "nominal", "vout_v": 1.2, "simulator_run": True}]}))
    rows = analog.declared_spec_checks(project, metrics={"unit": {
        "native_step": "A08", "native_executed": True, "total_corners": 1}})
    assert rows[0]["status"] == "PASS"
    assert rows[0]["value"] == 1.2


@pytest.mark.parametrize("execution", [
    {"simulation": {"native_execution": True}},
    {"native_measurement_study": {"analysis": "TRAN"}}])
def test_post_layout_checks_read_actual_producer_measurements(tmp_path, execution):
    project = project_at(tmp_path)
    metrics = {"unit": {"native_step": "A14", "native_executed": True,
        "corners": [{"style": "nominal", "measurements": {"vout": 1.2}, **execution}]}}
    rows = analog.declared_spec_checks(project, metrics=metrics)
    assert rows[0]["status"] == "PASS"
    assert rows[0]["value"] == 1.2


def test_d31_reports_the_actual_missing_native_input(tmp_path):
    project = project_at(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    result = analog.execute(project, output, {"step": "die_floorplan_and_macros"}, Commands(output))
    assert result["native_steps"][0]["status"] == "NOT_MEASURED"
    assert "State" in result["detail"]
    assert "D31.json" not in result["detail"]




def test_native_pv_uses_host_tools_without_an_execution_attestation(tmp_path, monkeypatch):
    import analog_native_physical as physical
    import analog_pdk_availability as availability

    seen = []

    def resolve(*args, **kwargs):
        seen.append(kwargs)
        return {"available": False, "reason": "native PDK DRC deck absent"}

    monkeypatch.setattr(availability, "resolve_pdk", resolve)
    result = physical._pv(tmp_path, "unit", "", "", "", {})
    assert result["detail"] == "native PDK DRC deck absent"
    assert seen[0]["container"] is None


def test_native_extraction_reaches_technology_check_with_actual_inputs(tmp_path, monkeypatch):
    import analog_a7_post_layout_emit as extraction
    import analog_native_physical as physical

    block = tmp_path / "phase3/analog/unit"
    block.mkdir(parents=True)
    (block / "unit.sp").write_text(".subckt unit a b\nR1 a b 1k\n.ends unit\n")
    (block / "unit.gds").write_bytes(b"native geometry")

    def missing_technology(path):
        raise ValueError("native extraction technology is absent")

    monkeypatch.setattr(extraction, "layout_tech", missing_technology)
    result = physical._extract(tmp_path, "unit", "", "", "", {})
    assert result["status"] == "NOT_MEASURED"
    assert result["detail"] == "native extraction technology is absent"
