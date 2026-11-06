"""Native analog entry, retained state and failure propagation controls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

import analog_native_flow as native


def project(tmp_path):
    (tmp_path / "input").mkdir()
    block = tmp_path / "phase3/analog/cell_alpha"
    block.mkdir(parents=True)
    (block.parent / "analog_block_list.json").write_text(json.dumps({
        "blocks": [{"name": "cell_alpha", "type": "amplifier"}]}))
    (block / "cell_alpha.sp").write_text("* actual DUT\n.subckt cell_alpha p n\nr1 p n 1k\n.ends\n")
    (block / "tb_cell_alpha.sp").write_text(
        "* actual testbench\n.include cell_alpha.sp\nv1 in 0 1\n"
        "xdut in 0 cell_alpha\n.control\ntran 1n 10n\n"
        "meas tran peak max v(in) from=2n to=8n\n.endc\n.end\n")
    (block / "spec.json").write_text('{"specs": [{"name":"peak","min":0.9,"max":1.1}]}')
    return tmp_path


def args(entry="A06", exit_="A06"):
    return SimpleNamespace(entry_step=entry, exit_step=exit_, blocks="", container="", pdk="")


def test_native_analog_cli_runs_delivered_consumer_without_qualification_files(tmp_path):
    root = project(tmp_path)
    command = [sys.executable, str(native.HERE / "analog_one_shot_runner.py"), str(root),
               "--entry-step", "A06", "--exit-step", "A06", "--container", ""]
    completed = subprocess.run(command, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads((root / "reports/analog_native/status.json").read_text())
    assert [(row["step"], row["block"], row["status"]) for row in report["steps"]] == [
        ("A06", "cell_alpha", "PASS")]
    assert not list(root.rglob("*qualification*"))


def test_new_default_native_entry_refuses_an_unimplemented_mode_before_execution(tmp_path):
    root = project(tmp_path)
    completed = subprocess.run([
        sys.executable, str(native.HERE / "analog_one_shot_runner.py"), str(root),
        "--entry-step", "A06", "--exit-step", "A06",
        "--execution-mode", "ultra"], capture_output=True, text=True)
    assert completed.returncode == 2
    assert "invalid choice" in completed.stderr and "default" in completed.stderr
    assert not (root / "reports/analog_native").exists()


def test_a18_preserves_native_component_fail_and_reason(tmp_path):
    from test_analog_macro_top import declaration, dispatch
    declaration(tmp_path)
    result, _, _ = dispatch(tmp_path, status="FAIL")
    assert result["status"] == "FAIL"
    assert result["detail"] == "native test result"
    assert result["native_evidence"]["component_status"] == "FAIL"


def test_a18_accepts_native_component_pass_with_required_outputs(tmp_path):
    from test_analog_macro_top import declaration, dispatch
    declaration(tmp_path)
    result, _, _ = dispatch(tmp_path)
    assert result["status"] == "NOT_MEASURED", result
    assert result["native_evidence"]["component_status"] == "PASS"
    assert result["measurements"]["status"] == "NOT_MEASURED"


def test_a18_non_object_receipt_is_not_measured(tmp_path):
    from test_analog_macro_top import declaration, put
    declaration(tmp_path)
    def run(*args, **kwargs):
        put(tmp_path, "reports/phase3/analog_macro_top_run.json", "[]")
        return {"returncode": 0, "missing_outputs": [], "outputs": {}}
    result = native._views("A18", tmp_path, {"name": "neutral"},
                           {"features": {}, "config": {}}, run)
    assert result["status"] == "NOT_MEASURED"


def test_a18_external_magic_script_does_not_replace_missing_declaration(tmp_path):
    root = project(tmp_path)
    script = root / "input/legacy.tcl"
    script.write_text("puts legacy")
    result = native._views("A18", root, {"name": "cell_alpha"},
        {"features": {}, "config": {"analog_top": {"implementation_script": str(script)}}},
        lambda *a, **k: pytest.fail("undeclared top reached native tool"))
    assert result["status"] == "NOT_MEASURED"
    assert result["reason"] == "A18_DECLARATION_ABSENT"


@pytest.mark.parametrize("state,expected", [("FAIL", "FAIL"), ("NOT_MEASURED", "NOT_MEASURED")])
def test_native_nonpass_reaches_run_verdict(tmp_path, monkeypatch, state, expected):
    root = project(tmp_path)
    monkeypatch.setattr(native, "_dispatch", lambda *arguments:
                        {"status": state, "detail": "actual native result", "outputs": []})
    result = native.run_window(root, args())
    assert result["verdict"] == expected
    assert result["steps"][0]["status"] == state


def test_bounded_native_pass_does_not_erase_or_inherit_an_unrelated_failure(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.setattr(native, "_dispatch", lambda step, *arguments: {
        "status": "FAIL" if step == "A06" else "PASS", "outputs": []})
    native.run_window(root, args("A06", "A06"))
    result = native.run_window(root, args("A11", "A11"))
    assert result["window_verdict"] == "PASS"
    assert result["verdict"] == "FAIL"


def test_block_subset_keeps_other_block_state_without_inheriting_its_failure(tmp_path, monkeypatch):
    root = project(tmp_path)
    (root / "phase3/analog/analog_block_list.json").write_text(json.dumps({
        "blocks": [{"name": "cell_alpha"}, {"name": "cell_beta"}]}))
    beta = root / "phase3/analog/cell_beta"
    beta.mkdir()
    (beta / "cell_beta.sp").write_text("* retained beta input\n")
    monkeypatch.setattr(native, "_dispatch", lambda step, _p, block, *_args: {
        "status": "FAIL" if block["name"] == "cell_beta" else "PASS", "outputs": []})
    native.run_window(root, args())
    selected = args()
    selected.blocks = "cell_alpha"
    result = native.run_window(root, selected)
    assert result["window_verdict"] == "PASS"
    assert result["verdict"] == "FAIL"
    assert {row["block"]: row["status"] for row in result["steps"]} == {
        "cell_alpha": "PASS", "cell_beta": "FAIL"}


def test_post_mc_execution_sample_override_reaches_native_dispatch_without_config_edit(tmp_path, monkeypatch):
    root = project(tmp_path)
    seen = []
    def dispatch(step, _project, _block, options, _run):
        seen.append(options["post_mc_samples"])
        return {"status": "NOT_MEASURED", "outputs": []}
    monkeypatch.setattr(native, "_dispatch", dispatch)
    request = args("A15", "A15")
    request.post_mc_samples = 2
    native.run_window(root, request)
    assert seen == [2]
    assert not (root / "input/analog_flow.json").exists()


def test_successful_exit_without_promised_native_output_is_not_pass(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.setattr(native, "_dispatch", lambda *arguments: {
        "status": "PASS", "outputs": [], "executions": [{"returncode": 0,
        "missing_outputs": [str(root / "missing.gds")]}]})
    result = native.run_window(root, args())
    assert result["verdict"] == "NOT_MEASURED"
    assert "missing.gds" in result["steps"][0]["detail"]


def test_normal_a07_window_consumes_declared_inputs_and_retains_actual_deck(tmp_path, monkeypatch):
    root = project(tmp_path)
    bdir = root / "phase3/analog/cell_alpha"
    (bdir / "spec.json").write_text(json.dumps({"specs": [{"name": "vout", "min": 0.9, "max": 1.1}]}))
    (bdir / "testbench_inputs.json").write_text(json.dumps({"block": "cell_alpha", "ports": ["p", "n"],
        "testbench": {"supply_exprs": ["1"], "stimulus": ["v1 p 0 {supply}"],
        "control": ["op", "let sensed = v(p)", 'echo "MEAS vout=" $&sensed']}}))
    calls = []
    def run(self, program, argv, **kwargs):
        calls.append((program, argv))
        log = Path(argv[argv.index("-o") + 1])
        log.write_text("MEAS vout=1.0\n")
        capture = log.parent / "capture.log"
        capture.write_text("ngspice batch mode\n")
        return {"returncode": 0, "log": str(capture), "outputs": [str(log)]}
    monkeypatch.setattr(native.NativeCommands, "__call__", run)
    report = native.run_window(root, args("A07", "A07"))
    assert report["verdict"] == "PASS"
    assert len(calls) == 1 and calls[0][0] == "@ngspice"
    row = report["steps"][0]
    assert row["metrics"]["vout"] == 1.0
    assert row["native_inputs"]["testbench"]["path"] != str(bdir / "tb_cell_alpha.sp")


def _declared_include_project(tmp_path):
    import shutil
    if not shutil.which("ngspice"):
        pytest.skip("native ngspice is required for the declared include control")
    root = project(tmp_path)
    bdir = root / "phase3/analog/cell_alpha"
    dependency = bdir / "load_detail.sp"
    dependency.write_text("rload n 0 1k\n")
    (bdir / "load.sp").write_text('.include "' + str(dependency) + '"\n')
    (bdir / "spec.json").write_text(json.dumps({"specs": [{"name": "vout", "min": 0.4, "max": 0.6}]}))
    (bdir / "testbench_inputs.json").write_text(json.dumps({"block": "cell_alpha", "ports": ["p", "n"],
        "testbench": {"supply_exprs": ["1"], "stimulus": ["v1 p 0 {supply}"],
        "cards": [".include load.sp"],
        "control": ["op", "let sensed = v(n)", 'echo "MEAS vout=" $&sensed', "quit"]}}))
    return root, dependency


def test_real_declared_include_change_updates_actual_measurement(tmp_path, monkeypatch):
    root, dependency = _declared_include_project(tmp_path)
    report = native.run_window(root, args("A07", "A07"))
    assert report["window_verdict"] == "PASS", report
    state = next(row for row in report["steps"] if row["step"] == "A07")
    assert state["metrics"]["vout"] == pytest.approx(0.5)
    dependency.write_text("rload n 0 2k\n")
    rerun = native.run_window(root, args("A07", "A07"))
    current = next(row for row in rerun["steps"] if row["step"] == "A07")
    assert current["status"] == "FAIL"
    assert current["metrics"]["vout"] == pytest.approx(2 / 3, abs=1e-6)


def test_declared_include_change_after_execution_retains_native_measurement(tmp_path, monkeypatch):
    root, dependency = _declared_include_project(tmp_path)
    execute = native.NativeCommands.__call__
    def changed_after_native(self, program, argv, **kwargs):
        execution = execute(self, program, argv, **kwargs)
        dependency.write_text("rload n 0 2k\n")
        return execution
    monkeypatch.setattr(native.NativeCommands, "__call__", changed_after_native)
    report = native.run_window(root, args("A07", "A07"))
    row = report["steps"][0]
    assert row["status"] == "PASS", row
    assert row["metrics"]["vout"] == pytest.approx(0.5)
    assert dependency.read_text() == "rload n 0 2k\n"


def test_independent_block_advances_while_another_native_step_is_waiting(tmp_path, monkeypatch):
    root = project(tmp_path)
    declared = root / "phase3/analog/analog_block_list.json"
    declared.write_text(json.dumps({"blocks": [{"name": "cell_alpha"}, {"name": "cell_beta"}]}))
    (root / "input/analog_flow.json").write_text('{"workers":2}')
    beta_advanced = threading.Event()
    observed = []
    def dispatch(step, _project, block, options, _run):
        if block["name"] == "cell_alpha" and step == "A06":
            observed.append(beta_advanced.wait(5))
        if block["name"] == "cell_beta" and step == "A07":
            assert options["previous_results"]["A06"]["cell_beta"]["status"] == "PASS"
            beta_advanced.set()
        return {"status": "PASS", "outputs": []}
    monkeypatch.setattr(native, "_dispatch", dispatch)
    result = native.run_window(root, args("A06", "A07"))
    assert observed == [True]
    assert result["verdict"] == "PASS"


def test_actual_subprocess_error_and_output_are_retained(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "HERE", tmp_path)
    (tmp_path / "native_tool.py").write_text("print('native failure detail')\nraise SystemExit(7)\n")
    execution = native.NativeCommands(tmp_path, tmp_path, "")("native_tool.py", [])
    assert execution["returncode"] == 7
    assert Path(execution["log"]).read_text() == "native failure detail\n"


def test_a17_selects_explicit_native_binary_without_changing_gds_producer(tmp_path):
    root = project(tmp_path)
    directory = root / "phase3/analog/cell_alpha"
    (directory / "layout.mag").write_text("magic\n")
    selected = root / "native-tools/ngspice"
    selected.parent.mkdir()
    selected.write_text("native binary identity")
    declaration = directory / "characterization_inputs.json"
    declaration.write_text(json.dumps({"ngspice_bin": str(selected)}))
    calls = []
    def run(program, argv):
        calls.append((program, argv))
        return {"returncode": 0 if len(calls) == 1 else 1}
    result = native._views("A17", root, {"name": "cell_alpha"}, {"container": "native"}, run)
    assert result["status"] == "FAIL"
    assert "--ngspice-bin" not in calls[0][1]
    assert calls[1][1][-2:] == ["--ngspice-bin", str(selected)]


def test_container_subprocess_loads_native_tool_environment_without_shell_interpolation(tmp_path, monkeypatch):
    seen = []
    def run(command, **kwargs):
        seen.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="native result\n", stderr="")
    monkeypatch.setattr(native.subprocess, "run", run)
    execution = native.NativeCommands(tmp_path, tmp_path, "native-box", "repo@sha256:fixed")(
        "@ngspice", ["-b", str(tmp_path / "deck with space.sp")])
    assert seen[0][0][-7:] == ["bash", "-lc", 'exec "$@"', "analog-native", "ngspice", "-b",
                             str(tmp_path / "deck with space.sp")]
    assert execution["returncode"] == 0


def test_a19_cannot_sign_off_empty_delivery_even_with_green_step_words(tmp_path):
    root = project(tmp_path)
    previous = {step: {"cell_alpha": {"status": "PASS"}} for step in native.STEPS[:-1]}
    result = native._views("A19", root, {"name": "cell_alpha"},
                           {"previous_results": previous}, None)
    assert result["status"] == "FAIL"
    receipt = json.loads((root / "phase3/analog/cell_alpha/signoff.json").read_text())
    assert receipt["deliverables"] == []


@pytest.mark.parametrize("rc", [130, 137, 143, -15])
def test_a17_interrupted_producer_without_terminal_measurement_is_unmeasured(tmp_path, rc):
    root = project(tmp_path)
    (root / "phase3/analog/cell_alpha/layout.mag").write_text("magic\n")
    result = native._views("A17", root, {"name": "cell_alpha"},
                           {"container": ""}, lambda *a, **kw: {"returncode": rc})
    assert result["status"] == "NOT_MEASURED"
    assert result["executions"][0]["returncode"] == rc


def test_attested_canonical_frontdoor_keeps_actual_a07_producer_local(tmp_path, monkeypatch):
    root = project(tmp_path)
    monkeypatch.setenv("VIBEIC_ANALOG_CONTAINER", "old-named-container")
    completed = subprocess.run([
        sys.executable, str(native.HERE / "analog_one_shot_runner.py"), str(root),
        "--entry-step", "A07", "--exit-step", "A07", "--container", ""],
        capture_output=True, text=True)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads((root / "reports/analog_native/status.json").read_text())
    assert report["transport"] == "HOST"
    assert report["container"] == ""
    execution = report["steps"][0]["executions"][0]
    assert execution["returncode"] == 0
    assert execution["argv"][0] != "docker"
    assert report["steps"][0]["tool_environment"]["transport"] == "HOST"


def test_canonical_invalid_block_input_returns_unmeasured_without_traceback(tmp_path):
    root = project(tmp_path)
    (root / "phase3/analog/analog_block_list.json").write_text('{"blocks":[]}')
    completed = subprocess.run([
        sys.executable, str(native.HERE / "analog_one_shot_runner.py"), str(root),
        "--entry-step", "A06", "--exit-step", "A06", "--container", ""],
        capture_output=True, text=True)
    assert completed.returncode == 2
    assert "Traceback" not in completed.stderr
    assert "block list" in completed.stderr
    assert not list(root.rglob("*.log"))


def test_canonical_analog_window_keeps_independent_consumers_running_after_native_refusal(tmp_path):
    root = project(tmp_path)
    completed = subprocess.run([
        sys.executable, str(native.HERE / "analog_one_shot_runner.py"), str(root),
        "--entry-step", "A05", "--exit-step", "A06", "--container", ""],
        capture_output=True, text=True)
    assert completed.returncode == 1, completed.stdout + completed.stderr
    report = json.loads((root / "reports/analog_native/status.json").read_text())
    rows = {row["step"]: row for row in report["steps"]}
    assert rows["A05"]["status"] == "FAIL"
    assert rows["A06"]["status"] == "PASS"
    assert not list(root.rglob("*qualification*"))
