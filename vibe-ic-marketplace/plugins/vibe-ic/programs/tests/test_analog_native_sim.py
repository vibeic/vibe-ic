"""Behavioral controls for the Default native A06--A10 consumers."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import analog_native_sim as sim
from _hostpaths import require_repo


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    block = root / "phase3" / "analog" / "stage"
    block.mkdir(parents=True)
    (block / "stage.sp").write_text("* delivered circuit\n.subckt stage in out\nr1 in out 1k\n.ends stage\n")
    (block / "tb_stage.sp").write_text(
        '* delivered DUT stimulus\n.include "stage.sp"\nxdut in out stage\nv1 in 0 1\n'
        '.control\ntran 1n 1u\nmeas tran level avg v(out) from=100n to=1u\n.endc\n.end\n')
    (block / "spec.json").write_text(json.dumps({"specs": [{"name": "level", "min": 0.9, "max": 1.1, "unit": "V"}]}))
    return root


def _options(**updates):
    return {"container": "native-tool", "pdk": "project-process", "config": {}, **updates}


def _never(*args, **kwargs):
    raise AssertionError("a native producer must not have been launched")


def test_a06_validates_actual_delivered_dut(project):
    result = sim.run_step("A06", project, {"name": "stage"}, _options(), _never)
    assert result["status"] == "PASS"
    assert result["metrics"]["required_measurements"] == ["level"]


def test_a06_rejects_include_without_dut_instantiation(project):
    deck = project / "phase3/analog/stage/tb_stage.sp"
    deck.write_text(deck.read_text().replace("xdut in out stage", "* xd ut is omitted"))
    result = sim.run_step("A06", project, {"name": "stage"}, _options(), _never)
    assert result["status"] == "FAIL"
    assert "never instantiates" in result["detail"]


def test_a06_missing_measurement_is_unmeasured(project):
    options = _options(config={"blocks": {"stage": {"required_measurements": ["level", "resolution"]}}})
    result = sim.run_step("A06", project, {"name": "stage"}, options, _never)
    assert result["status"] == "NOT_MEASURED"
    assert "resolution" in result["detail"]


def test_a06_rejects_measurement_beyond_actual_record(project):
    deck = project / "phase3/analog/stage/tb_stage.sp"
    deck.write_text(deck.read_text().replace("to=1u", "to=2u"))
    result = sim.run_step("A06", project, {"name": "stage"}, _options(), _never)
    assert result["status"] == "FAIL"
    assert "beyond" in result["detail"]


def _op_deck(project, expression="v(out)"):
    deck = project / "phase3/analog/stage/tb_stage.sp"
    deck.write_text('* delivered OP stimulus\n.include "stage.sp"\n'
                    'xdut in out stage\nv1 in 0 1\n.control\nop\n'
                    f'let sensed = {expression}\necho "MEAS level=" $&sensed\n.endc\n.end\n')
    return deck


def test_a06_accepts_existing_native_op_echo_shape(project):
    _op_deck(project)
    result = sim.run_step("A06", project, {"name": "stage"}, _options(), _never)
    assert result["status"] == "PASS"
    assert result["metrics"]["required_measurements"] == ["level"]


def test_a06_does_not_call_literal_echo_a_dut_measure(project):
    _op_deck(project, expression="1.0")
    result = sim.run_step("A06", project, {"name": "stage"}, _options(), _never)
    assert result["status"] == "NOT_MEASURED"


def test_native_ac_probe_and_actual_endpoint_alias_are_measured_definitions():
    text = ('ac dec 20 1 1Meg\nlet transfer = -vdb(vout)\n'
            'let endpoint = transfer[length(transfer)-1]\necho "MEAS psrr=" $&endpoint\n')
    assert sim._measurement_names(text) == ["psrr"]


@pytest.mark.parametrize("transcript,expected", [("MEAS level=1.0\n", "PASS"),
                                                  ("MEAS level=\n", "NOT_MEASURED"),
                                                  ("MEAS level=nan\n", "NOT_MEASURED"),
                                                  ("Error: &sensed: no such variable\nMEAS level=0\n", "FAIL")])
def test_a07_native_op_echo_uses_spec_bounds_and_requires_actual_value(project, transcript, expected):
    _op_deck(project)
    result = sim.run_step("A07", project, {"name": "stage"}, _options(),
                          lambda *a, **k: {"returncode": 0, "stdout": transcript})
    assert result["status"] == expected


def _source_performance_spec(project):
    spec = project / "phase3/analog/stage/spec.json"
    spec.write_text(json.dumps({"specs": [
        {"name": "dropout", "max": 0.5, "unit": "V"},
        {"name": "iq", "max": 50, "unit": "uA"},
        {"name": "psrr", "min": 40, "unit": "dB"},
        {"name": "vout", "min": 1.1, "max": 1.3, "unit": "V"},
        {"name": "vin", "min": 1.6, "max": 2.0, "unit": "V"},
        {"name": "iout", "min": 0.1, "max": 1.0, "unit": "mA"},
    ]}))
    return spec


def test_a06_and_a07_refuse_missing_source_definitions_without_native_launch(project):
    deck = _op_deck(project)
    deck.write_text(deck.read_text().replace("MEAS level=", "MEAS vout="))
    _source_performance_spec(project)
    for step in ("A06", "A07"):
        result = sim.run_step(step, project, {"name": "stage"}, _options(), _never)
        assert result["status"] == "NOT_MEASURED"
        assert result["executions"] == []
        assert result["metrics"]["measurement_definition_coverage"]["missing"] == ["dropout", "iq", "psrr"]
        assert result["metrics"]["analysis_coverage"] == {
            "source_required": [".op", ".dc", ".ac"], "observed": [".op"], "missing": [".ac", ".dc"]}


def _performance_deck(project, *, analyses=True, definitions=True):
    deck = _op_deck(project)
    text = deck.read_text().replace("v1 in 0 1", "v1 in 0 1 ac 1").replace("MEAS level=", "MEAS vout=")
    extra = ""
    if analyses:
        extra += "dc v1 0 1 0.1\nac dec 10 1 1Meg\n"
    if definitions:
        extra += ('let draw = abs(i(v1))*1e6\necho "MEAS iq=" $&draw\n'
                  'meas dc dropout find v(in) when v(out)=0.9\n'
                  'meas ac psrr find vdb(out) at=1\n')
    deck.write_text(text.replace(".endc", extra + ".endc"))
    return deck


@pytest.mark.parametrize("analyses,definitions", [(False, True), (True, False)])
def test_a06_and_a07_require_both_source_analyses_and_measurement_definitions(project, analyses, definitions):
    _source_performance_spec(project)
    _performance_deck(project, analyses=analyses, definitions=definitions)
    for step in ("A06", "A07"):
        result = sim.run_step(step, project, {"name": "stage"}, _options(), _never)
        assert result["status"] == "NOT_MEASURED"
        assert bool(result["metrics"]["analysis_coverage"]["missing"]) is not analyses
        assert bool(result["metrics"]["measurement_definition_coverage"]["missing"]) is not definitions


def test_a07_long_transient_with_unmeasured_source_requirement_is_not_launched(project):
    deck = project / "phase3/analog/stage/tb_stage.sp"
    deck.write_text(deck.read_text().replace("tran 1n 1u", "tran 5n 28m"))
    (project / "phase3/analog/stage/spec.json").write_text(json.dumps({"specs": [{"name": "enob", "min": 14}]}))
    result = sim.run_step("A07", project, {"name": "stage"}, _options(), _never)
    assert result["status"] == "NOT_MEASURED"
    assert result["metrics"]["measurement_definition_coverage"]["missing"] == ["enob"]


def test_bad_dut_stays_fail_before_missing_source_coverage(project):
    _source_performance_spec(project)
    deck = _op_deck(project)
    deck.write_text(deck.read_text().replace("xdut in out stage", "* DUT omitted"))
    for step in ("A06", "A07"):
        result = sim.run_step(step, project, {"name": "stage"}, _options(), _never)
        assert result["status"] == "FAIL"
        assert "never instantiates" in result["detail"]


@pytest.mark.parametrize("vout,expected", [(1.2, "NOT_MEASURED"), (1.5, "FAIL")])
def test_a07_complete_deck_retains_measured_failure_despite_missing_runtime_output(project, vout, expected):
    _performance_deck(project)
    _source_performance_spec(project)
    result = sim.run_step("A07", project, {"name": "stage"}, _options(),
        lambda *a, **k: {"returncode": 0, "stdout": f"MEAS vout={vout}\n"})
    assert result["status"] == expected
    assert result["metrics"]["vout"] == vout
    assert result["metrics"]["source_measurement_coverage"]["missing"] == ["dropout", "iq", "psrr"]
    assert len(result["executions"]) == 1


def test_a07_all_source_metrics_measured_and_within_bounds_pass(project):
    _performance_deck(project)
    _source_performance_spec(project)
    a06 = sim.run_step("A06", project, {"name": "stage"}, _options(), _never)
    assert a06["status"] == "PASS"
    assert a06["metrics"]["analysis_coverage"]["missing"] == []
    assert a06["metrics"]["measurement_definition_coverage"]["missing"] == []
    result = sim.run_step("A07", project, {"name": "stage"}, _options(), lambda *a, **k: {
        "returncode": 0, "stdout": "MEAS vout=1.2\ndropout = 0.3\niq = 20\npsrr = 50\n"})
    assert result["status"] == "PASS"
    assert result["metrics"]["source_measurement_coverage"]["missing"] == []


def _retained_native_study(project, vout=1.2):
    import analog_bound_measurements as producer
    bdir = project / "phase3/analog/stage"
    _source_performance_spec(project)
    deck = _op_deck(project)
    deck.write_text(deck.read_text().replace("MEAS level=", "MEAS vout="))
    template = bdir / "study_tb.sp"
    template.write_text(deck.read_text().replace('.include "stage.sp"', f'.include "{bdir / "stage.sp"}"'))
    bindings = {"analysis": {"kind": "OP"}, "measurements": {
        "vout": {"analysis": "OP", "expression": "v(out)", "unit": "V"},
        "iq": {"analysis": "OP", "expression": "-i(v1)*1e6", "unit": "uA"}}}
    binding_path = bdir / "study-bindings.json"
    binding_path.write_text(json.dumps(bindings))
    destination = project / "study-results"
    def run(*args, **kwargs):
        log = destination / "native.log"
        log.write_text(f"MEAS vout={vout} iq=20\n")
        return {"returncode": 0, "log": str(log), "log_sha256": producer.sha(log)}
    record = producer.run_measurements(project, bdir / "stage.sp", template, bindings, destination, run)
    record["native_inputs"]["bindings"] = {"path": str(binding_path), "sha256": producer.sha(binding_path)}
    result_path = destination / "result.json"
    result_path.write_text(json.dumps(record))
    return {"testbench": str(template), "bindings": str(binding_path), "result": str(result_path)}


@pytest.mark.parametrize("source", ["sidecar", "config", "previous"])
def test_incomplete_a06_a07_adopt_exact_retained_native_studies_without_duplicate_execution(project, source):
    entry = _retained_native_study(project)
    config = {"blocks": {"stage": {"measurement_studies": [entry]}}}
    if source == "sidecar":
        (project / "phase3/analog/stage/measurement_studies.json").write_text(json.dumps([entry]))
        config = {}
    result = sim.run_step("A06", project, {"name": "stage"}, _options(config=config), _never)
    assert result["status"] == "NOT_MEASURED"
    assert result["metrics"]["vout"] == 1.2 and result["metrics"]["iq"] == 20
    assert result["metrics"]["source_measurement_coverage"]["missing"] == ["dropout", "psrr"]
    if source == "previous":
        entry.pop("result")
    nominal = sim.run_step("A07", project, {"name": "stage"},
        _options(config=config, previous_results={"A06": {"stage": result}}), _never)
    assert nominal["status"] == "NOT_MEASURED"
    assert nominal["metrics"]["native_measurement_studies"][0]["reused"] is True
    assert nominal["metrics"]["vout"] == 1.2 and nominal["metrics"]["iq"] == 20
    assert nominal["executions"] == []  # No canonical PRE claim from a different stimulus.


def test_partial_native_study_retains_real_failure_before_missing_performance(project):
    entry = _retained_native_study(project, vout=1.5)
    result = sim.run_step("A07", project, {"name": "stage"},
        _options(config={"blocks": {"stage": {"measurement_studies": [entry]}}}), _never)
    assert result["status"] == "FAIL"
    assert result["metrics"]["measured_spec_violations"] == ["vout"]
    assert result["metrics"]["source_measurement_coverage"]["missing"] == ["dropout", "psrr"]


def test_stale_or_changed_native_transcript_cannot_supply_retained_values(project):
    entry = _retained_native_study(project)
    record = json.loads(Path(entry["result"]).read_text())
    Path(record["executions"][0]["log"]).write_text("MEAS vout=0 iq=0\n")
    calls = []
    def run(program, argv, **kwargs):
        calls.append(program)
        return {"returncode": 2}
    result = sim.run_step("A07", project, {"name": "stage"},
        _options(config={"blocks": {"stage": {"measurement_studies": [entry]}}}), run)
    assert calls == ["analog_bound_measurements.py"]
    assert result["status"] == "NOT_MEASURED" and "vout" not in result["metrics"]


@pytest.mark.parametrize('actual_temperature,reuse', [(-40, True), (27, False), (None, False)])
def test_retained_native_study_requires_actual_requested_temperature(project, actual_temperature, reuse):
    entry = _retained_native_study(project)
    result_path, bindings_path = Path(entry['result']), Path(entry['bindings'])
    record, bindings = json.loads(result_path.read_text()), json.loads(bindings_path.read_text())
    bindings['analysis']['temperature_c'] = -40
    bindings_path.write_text(json.dumps(bindings))
    record['bindings'] = bindings
    record['native_inputs']['bindings']['sha256'] = hashlib.sha256(bindings_path.read_bytes()).hexdigest()
    execution = record['executions'][0]
    log = Path(execution['log'])
    if actual_temperature is not None:
        log.write_text(f'Doing analysis at TEMP = {actual_temperature:.6f} and TNOM = 27\n' + log.read_text())
    execution['log_sha256'] = hashlib.sha256(log.read_bytes()).hexdigest()
    result_path.write_text(json.dumps(record))
    calls = []
    def run(program, argv, **kwargs):
        calls.append(program)
        return {'returncode': 2}
    result = sim.run_step('A07', project, {'name': 'stage'},
        _options(config={'blocks': {'stage': {'measurement_studies': [entry]}}}), run)
    assert calls == ([] if reuse else ['analog_bound_measurements.py'])
    assert ('vout' in result['metrics']) == reuse


@pytest.mark.parametrize("rc,diagnostic,expected", [
    (1, "", "FAIL"), (0, ";;RESIDUAL_FAIL worst_ratio=2.5\n", "FAIL"),
    (0, "Error: native AC analysis failed\n", "FAIL"), (143, "", "NOT_MEASURED")])
def test_cached_pass_word_cannot_hide_actual_native_failure_or_interruption(project, rc, diagnostic, expected):
    entry = _retained_native_study(project)
    path = Path(entry["result"])
    record = json.loads(path.read_text())
    record["status"] = "PASS"
    execution = record["executions"][0]
    execution["returncode"] = rc
    log = Path(execution["log"])
    log.write_text(log.read_text() + diagnostic)
    execution["log_sha256"] = hashlib.sha256(log.read_bytes()).hexdigest()
    path.write_text(json.dumps(record))
    result = sim.run_step("A07", project, {"name": "stage"},
        _options(config={"blocks": {"stage": {"measurement_studies": [entry]}}}), _never)
    assert result["status"] == expected
    assert result["metrics"]["native_measurement_studies"][0]["status"] == expected
    assert "vout" not in result["metrics"] and "iq" not in result["metrics"]


def test_old_native_study_without_model_closure_cannot_be_reused(project):
    entry = _retained_native_study(project)
    path = Path(entry["result"])
    record = json.loads(path.read_text())
    record["native_inputs"] = {key: value for key, value in record["native_inputs"].items()
                               if not key.startswith("include:")}
    path.write_text(json.dumps(record))
    calls = []
    def run(program, argv, **kwargs):
        calls.append(program)
        return {"returncode": 2}
    result = sim.run_step("A07", project, {"name": "stage"},
        _options(config={"blocks": {"stage": {"measurement_studies": [entry]}}}), run)
    assert calls == ["analog_bound_measurements.py"]
    assert result["status"] == "NOT_MEASURED" and "vout" not in result["metrics"]


@pytest.mark.parametrize("transcript,returncode,expected", [
    ("level = 1.0 from=1e-7 to=1e-6\n", 0, "PASS"),
    ("level = 1.5\n", 0, "FAIL"),
    ("level = 1.0\nError: transient analysis failed\n", 0, "FAIL"),
    ("level = 1.0\ntran simulation(s) aborted\n", 0, "FAIL"),
    ("level = 1.0\n;;RESIDUAL_FAIL worst_ratio=2.5\n", 0, "FAIL"),
    ("simulation ended\n", 0, "NOT_MEASURED"),
    ("level = 1.0\n", 1, "FAIL"),
])
def test_a07_uses_native_result_and_propagates_failure(project, transcript, returncode, expected):
    calls = []
    def run(program, argv, **kwargs):
        calls.append((program, argv, kwargs))
        return {"returncode": returncode, "stdout": transcript, "stderr": ""}
    result = sim.run_step("A07", project, {"name": "stage"}, _options(), run)
    assert result["status"] == expected
    assert calls[0][0] == "@ngspice"
    assert calls[0][1] == ["-b", str(project / "phase3/analog/stage/tb_stage.sp")]
    assert len(result["executions"]) == 1


def test_a07_never_scores_a_metric_without_source_limit(project):
    (project / "phase3/analog/stage/spec.json").write_text('{"specs": []}')
    result = sim.run_step("A07", project, {"name": "stage"}, _options(),
                          lambda *a, **k: {"returncode": 0, "stdout": "level = 1.0\n"})
    assert result["status"] == "NOT_MEASURED"
    assert result["metrics"] == {"level": 1.0}


def test_a07_rejects_override_input_changed_during_execution(project):
    block = project / "phase3/analog/stage"
    netlist, deck, spec = (block / leaf for leaf in ("alternate.sp", "nominal.sp", "alternate_spec.json"))
    netlist.write_text((block / "stage.sp").read_text())
    deck.write_text((block / "tb_stage.sp").read_text().replace('"stage.sp"', '"alternate.sp"'))
    spec.write_text((block / "spec.json").read_text())
    expected = {role: {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for role, path in (("netlist", netlist), ("testbench", deck), ("spec", spec))}
    def run(program, argv, **kwargs):
        assert argv == ["-b", str(deck)]
        deck.write_text("* changed after native execution started\n")
        return {"returncode": 0, "stdout": "level = 1.0\n"}
    options = _options(config={"blocks": {"stage": {
        "netlist": str(netlist.relative_to(project)), "nominal_testbench": str(deck.relative_to(project)),
        "spec": str(spec.relative_to(project))}}})
    result = sim.run_step("A07", project, {"name": "stage"}, options, run)
    assert result["status"] == "NOT_MEASURED"
    assert "testbench" in result["detail"]
    assert result["native_inputs"] == expected
    assert result["native_inputs"]["testbench"]["sha256"] != hashlib.sha256(deck.read_bytes()).hexdigest()


def test_a07_input_drift_does_not_erase_measured_failure(project):
    deck = project / "phase3/analog/stage/tb_stage.sp"
    def run(*args, **kwargs):
        deck.write_text("* changed after native execution started\n")
        return {"returncode": 0, "stdout": "level = 1.5\n"}
    result = sim.run_step("A07", project, {"name": "stage"}, _options(), run)
    assert result["status"] == "FAIL"
    assert "outside declared spec limit" in result["detail"]


@pytest.mark.parametrize("rc", [130, 137, 143, -9, -15])
def test_a07_interruption_without_measured_failure_is_unmeasured(project, rc):
    result = sim.run_step("A07", project, {"name": "stage"}, _options(),
                          lambda *a, **k: {"returncode": rc, "stdout": "", "stderr": "interrupted"})
    assert result["status"] == "NOT_MEASURED"
    assert "interrupted" in result["detail"]


def test_a07_measured_failure_precedes_another_missing_or_malformed_limit(project):
    deck = project / "phase3/analog/stage/tb_stage.sp"
    deck.write_text(deck.read_text().replace(".endc", "meas tran other avg v(out)\n.endc"))
    options = _options(config={"blocks": {"stage": {"limits": {
        "level": {"min": 0.9, "max": 1.1}, "other": {"max": "unknown"}}}}})
    result = sim.run_step("A07", project, {"name": "stage"}, options,
                          lambda *a, **k: {"returncode": 0, "stdout": "level = 1.5\nother = 1.0\n"})
    assert result["status"] == "FAIL"
    assert "outside declared spec limit: level" in result["detail"]


def _process_starttime(pid):
    return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19])


def test_selected_local_ngspice_identity_comes_from_current_resolver(monkeypatch):
    selected = Path(sys.executable).resolve()
    monkeypatch.setattr(shutil, "which", lambda name: str(selected) if name == "ngspice" else None)
    assert sim._selected_ngspice_identity({"container": ""}) == {
        "scope": "host", "path": str(selected),
        "sha256": hashlib.sha256(selected.read_bytes()).hexdigest()}


def test_selected_container_ngspice_identity_uses_remote_digest_not_host_foss(
        monkeypatch):
    import analog_a8_hardmacro_emit as hardmacro
    selected = "/foss/tools/ngspice/bin/ngspice"
    monkeypatch.setattr(sim.sweep, "_resolve_ngspice", lambda container: selected)
    monkeypatch.setattr(hardmacro, "_remote_sha256", lambda container, path: ("a" * 64, ""))
    assert sim._selected_ngspice_identity({"container": "native-container"}) == {
        "scope": "container", "path": selected, "sha256": "a" * 64}


def test_running_native_work_is_retained_without_duplicate_launch(project, monkeypatch, tmp_path):
    deck = project / "phase3/analog/stage/tb_stage.sp"
    executable = Path(sys.executable).resolve()
    selected = {"scope": "host", "path": str(executable),
                "sha256": hashlib.sha256(executable.read_bytes()).hexdigest()}
    monkeypatch.setattr(sim, "_selected_ngspice_identity", lambda options: selected)
    log = tmp_path / "native.log"
    log.write_text("running\n")
    argv = [str(executable), "-c", "import time; time.sleep(30)", "-b", str(deck), "-o", str(log)]
    process = subprocess.Popen(argv)
    try:
        record = {"pid": process.pid, "starttime": _process_starttime(process.pid), "argv": argv,
                  "executable": str(executable.resolve()),
                  "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                  "deck": str(deck), "deck_sha256": hashlib.sha256(deck.read_bytes()).hexdigest(),
                  "log": str(log)}
        options = _options(container="", config={"active_runs": {"stage": [record]}})
        result = sim.run_step("A07", project, {"name": "stage"}, options, _never)
        assert result["status"] == "NOT_MEASURED"
        assert result["executions"] == [{**record, "transport_identity": "VERIFIED",
                                         "selected_tool": selected}]
        assert "existing native jobs" in result["detail"]
    finally:
        process.terminate()
        process.wait()


def test_unrelated_live_pid_cannot_suppress_native_launch(project):
    deck = project / "phase3/analog/stage/tb_stage.sp"
    record = {"pid": os.getpid(), "starttime": _process_starttime(os.getpid()),
              "argv": ["ngspice", "-b", str(deck), "-o", "existing.log"],
              "executable": sys.executable,
              "executable_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
              "deck": str(deck), "deck_sha256": hashlib.sha256(deck.read_bytes()).hexdigest(),
              "log": "existing.log"}
    calls = []
    result = sim.run_step("A07", project, {"name": "stage"},
                          _options(container="", config={"active_runs": {"stage": [record]}}),
                          lambda *a, **k: calls.append((a, k)) or {"returncode": 0, "stdout": "level = 1.0\n"})
    assert result["status"] == "PASS"
    assert calls and calls[0][0][0] == "@ngspice"


@pytest.mark.parametrize("mutation", ["starttime", "argv", "log", "selected_tool", "container"])
def test_active_run_requires_complete_live_transport_identity(project, monkeypatch, tmp_path, mutation):
    deck = project / "phase3/analog/stage/tb_stage.sp"
    executable = Path(sys.executable).resolve()
    selected = {"scope": "host", "path": str(executable),
                "sha256": hashlib.sha256(executable.read_bytes()).hexdigest()}
    monkeypatch.setattr(sim, "_selected_ngspice_identity", lambda options: selected)
    log = tmp_path / "native.log"
    log.write_text("running\n")
    argv = [str(executable), "-c", "import time; time.sleep(30)", "-b", str(deck), "-o", str(log)]
    process = subprocess.Popen(argv)
    try:
        record = {"pid": process.pid, "starttime": _process_starttime(process.pid), "argv": argv,
                  "executable": str(executable.resolve()),
                  "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                  "deck": str(deck), "deck_sha256": hashlib.sha256(deck.read_bytes()).hexdigest(),
                  "log": str(log)}
        options = _options(container="", config={"active_runs": {"stage": [record]}})
        assert sim._active_runs(options, "stage") == [
            {**record, "transport_identity": "VERIFIED", "selected_tool": selected}]
        changed = dict(record)
        if mutation == "starttime":
            changed["starttime"] += 1
        elif mutation == "argv":
            changed["argv"] = [*argv, "--not-live"]
        elif mutation == "log":
            changed["log"] = str(tmp_path / "other.log")
        elif mutation == "selected_tool":
            monkeypatch.setattr(sim, "_selected_ngspice_identity", lambda options: {
                **selected, "sha256": "0" * 64})
        else:
            changed["container"] = "claimed-container"
            changed["cid"] = "claimed-cid"
        changed_options = _options(container=("required-container" if mutation == "container" else ""),
                                   config={"active_runs": {"stage": [changed]}})
        assert sim._active_runs(changed_options, "stage") == []
    finally:
        process.terminate()
        process.wait()


def test_copied_python_named_ngspice_is_not_selected_native_tool(project, monkeypatch, tmp_path):
    deck = project / "phase3/analog/stage/tb_stage.sp"
    selected_executable = Path(sys.executable).resolve()
    selected = {"scope": "host", "path": str(selected_executable),
                "sha256": hashlib.sha256(selected_executable.read_bytes()).hexdigest()}
    monkeypatch.setattr(sim, "_selected_ngspice_identity", lambda options: selected)
    renamed = tmp_path / "ngspice"
    shutil.copy2(sys.executable, renamed)
    log = tmp_path / "renamed.log"
    log.write_text("not native ngspice\n")
    argv = [str(renamed), "-c", "import time; time.sleep(30)", "-b", str(deck), "-o", str(log)]
    process = subprocess.Popen(argv)
    try:
        record = {"pid": process.pid, "starttime": _process_starttime(process.pid), "argv": argv,
                  "executable": str(renamed.resolve()),
                  "executable_sha256": hashlib.sha256(renamed.read_bytes()).hexdigest(),
                  "deck": str(deck), "deck_sha256": hashlib.sha256(deck.read_bytes()).hexdigest(),
                  "log": str(log)}
        options = _options(container="", config={"active_runs": {"stage": [record]}})
        assert sim._active_runs(options, "stage") == []
    finally:
        process.terminate()
        process.wait()


def test_unobservable_selected_tool_protects_plausible_active_job_without_verifying_it(
        project, monkeypatch, tmp_path):
    deck = project / "phase3/analog/stage/tb_stage.sp"
    executable = Path(sys.executable).resolve()
    monkeypatch.setattr(sim, "_selected_ngspice_identity", lambda options: None)
    log = tmp_path / "unverified.log"
    log.write_text("running\n")
    argv = [str(executable), "-c", "import time; time.sleep(30)", "-b", str(deck), "-o", str(log)]
    process = subprocess.Popen(argv)
    try:
        record = {"pid": process.pid, "starttime": _process_starttime(process.pid), "argv": argv,
                  "executable": str(executable),
                  "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                  "deck": str(deck), "deck_sha256": hashlib.sha256(deck.read_bytes()).hexdigest(),
                  "log": str(log)}
        options = _options(container="", config={"active_runs": {"stage": [record]}})
        active = sim._active_runs(options, "stage")
        assert active == [{**record, "transport_identity": "UNVERIFIED",
                           "reason": "selected ngspice identity is not currently observable"}]
        result = sim.run_step("A07", project, {"name": "stage"}, options, _never)
        assert result["status"] == "NOT_MEASURED"
        assert result["executions"] == active
    finally:
        process.terminate()
        process.wait()


def test_a08_requires_nominal_pass_before_native_pvt(project):
    result = sim.run_step("A08", project, {"name": "stage"}, _options(), _never)
    assert result["status"] == "NOT_MEASURED"
    assert "nominal A07" in result["detail"]


@pytest.mark.parametrize("native_status,gate_rc,expected", [("PASS", 0, "PASS"), ("FAIL", 1, "FAIL"), ("NOT_MEASURED", 0, "NOT_MEASURED")])
def test_a08_runs_existing_native_sweep_and_consumer(project, native_status, gate_rc, expected):
    spec = project / "phase3/analog/stage/spec.json"
    spec.write_text(json.dumps({"specs": [{"name": "vout", "min": 0.9, "max": 1.1, "unit": "V"}]}))
    calls = []
    def run(program, argv, **kwargs):
        calls.append(program)
        if program == "analog_real_corner_sweep.py":
            output = Path(kwargs["outputs"][0])
            output.write_text(json.dumps({"full_pvt_sweep_executed": True, "design_traceable": True,
                                          "total_corners": 9, "corners_executed": 9,
                                          "spec_results": [{"name": "vout", "status": native_status, "value": 1.0}]}))
            return {"returncode": 0}
        Path(kwargs["outputs"][0]).write_text(json.dumps({"verdict": native_status}))
        return {"returncode": gate_rc}
    options = _options(previous_results={"A07": {"stage": {"status": "PASS"}}})
    result = sim.run_step("A08", project, {"name": "stage"}, options, run)
    assert result["status"] == expected
    assert calls == ["analog_real_corner_sweep.py", "analog_a4_corner_sweep_check.py"]


@pytest.mark.parametrize("current,status,expected", [(True, "FAIL", "FAIL"),
    (True, "PASS", "NOT_MEASURED"), (False, "FAIL", "NOT_MEASURED")])
def test_a08_nonzero_producer_preserves_only_current_explicit_spec_failure(project, current, status, expected):
    output = project / "phase3/analog/stage/corner_results.json"
    record = {"spec_results": [{"name": "level", "value": 1.5, "status": status}]}
    if not current:
        output.write_text(json.dumps(record))
    def run(program, argv, **kwargs):
        assert program == "analog_real_corner_sweep.py"
        if current:
            output.write_text(json.dumps(record))
        return {"returncode": 2, "log": "native-pvt.log"}
    result = sim.run_step("A08", project, {"name": "stage"},
        _options(previous_results={"A07": {"stage": {"status": "PASS"}}}), run)
    assert result["status"] == expected
    assert result["executions"][0]["returncode"] == 2
    if current:
        assert result["metrics"]["spec_results"] == record["spec_results"]


@pytest.mark.parametrize("complete,expected", [(False, "NOT_MEASURED"), (True, "PASS")])
def test_a08_requires_all_source_performance_metrics_but_not_input_conditions(project, complete, expected):
    spec = project / "phase3/analog/stage/spec.json"
    spec.write_text(json.dumps({"specs": [
        {"name": "dropout", "max": 0.5, "unit": "V"},
        {"name": "iq", "max": 50, "unit": "uA"},
        {"name": "psrr", "min": 40, "unit": "dB"},
        {"name": "vout", "min": 1.1, "max": 1.3, "unit": "V"},
        {"name": "vin", "min": 1.6, "max": 2.0, "unit": "V"},
        {"name": "iout", "min": 0.1, "max": 1.0, "unit": "mA"},
    ]}))
    rows = [{"name": "vout", "status": "PASS", "value": 1.2}]
    if complete:
        rows += [{"name": "dropout", "status": "PASS", "value": 0.3},
                 {"name": "iq", "status": "PASS", "value": 20},
                 {"name": "psrr", "status": "PASS", "value": 50}]
    def run(program, argv, **kwargs):
        output = Path(kwargs["outputs"][0])
        if program == "analog_real_corner_sweep.py":
            output.write_text(json.dumps({"full_pvt_sweep_executed": True, "design_traceable": True,
                                          "total_corners": 9, "corners_executed": 9,
                                          "spec_results": rows}))
        else:
            output.write_text('{"verdict": "PASS"}')
        return {"returncode": 0}
    options = _options(previous_results={"A07": {"stage": {"status": "PASS"}}})
    result = sim.run_step("A08", project, {"name": "stage"}, options, run)
    assert result["status"] == expected
    coverage = result["metrics"]["source_measurement_coverage"]
    assert coverage["required"] == ["dropout", "iq", "psrr", "vout"]
    assert coverage["missing"] == ([] if complete else ["dropout", "iq", "psrr"])
    assert result["metrics"]["corners_executed"] == 9


@pytest.mark.parametrize("verdict,rc,runs,expected", [("PASS", 0, 8, "PASS"), ("FAIL", 0, 8, "FAIL"), ("UNSCOREABLE", 2, 0, "NOT_MEASURED"), ("PASS", 0, 0, "NOT_MEASURED")])
def test_a09_preserves_native_mc_verdict_even_with_rc_zero(project, verdict, rc, runs, expected):
    (project / "phase3/analog/stage/spec.json").write_text(json.dumps({"specs": [{"name": "vout", "min": 0.9, "max": 1.1}]}))
    def run(program, argv, **kwargs):
        assert program == "analog_native_sim.py" and argv[0] == "mc"
        assert argv[argv.index("--pdk") + 1] == "project-process"
        Path(kwargs["outputs"][0]).write_text(json.dumps({"verdict": verdict, "mc_runs": runs, "mc_yield_pct": 100 if verdict == "PASS" else 0,
            "spec_yield": {"vout": {"runs_scored": runs, "yield_pct": 100 if verdict == "PASS" else 0}}}))
        return {"returncode": rc}
    result = sim.run_step("A09", project, {"name": "stage"},
                          _options(previous_results={"A07": {"stage": {"status": "PASS"}}}), run)
    assert result["status"] == expected


def test_a09_does_not_launch_mc_for_unresolved_nominal(project):
    result = sim.run_step("A09", project, {"name": "stage"}, _options(), _never)
    assert result["status"] == "NOT_MEASURED"
    assert "nominal A07" in result["detail"]


@pytest.mark.parametrize("complete,expected", [(False, "NOT_MEASURED"), (True, "PASS")])
def test_a09_requires_source_metric_coverage_and_all_actual_samples(project, complete, expected):
    _source_performance_spec(project)
    yields = {"vout": {"runs_scored": 3, "yield_pct": 100}}
    for name in ("dropout", "iq", "psrr"):
        yields[name] = {"runs_scored": 3 if complete else 0, "yield_pct": 100 if complete else None}
    def run(program, argv, **kwargs):
        Path(kwargs["outputs"][0]).write_text(json.dumps({"verdict": "PASS", "mc_runs": 3,
            "mc_yield_pct": 100, "spec_yield": yields}))
        return {"returncode": 0}
    result = sim.run_step("A09", project, {"name": "stage"},
        _options(previous_results={"A07": {"stage": {"status": "PASS"}}}), run)
    assert result["status"] == expected
    assert result["metrics"]["mc_runs"] == 3
    assert result["metrics"]["source_measurement_coverage"]["missing"] == ([] if complete else ["dropout", "iq", "psrr"])


def test_mc_cli_uses_existing_native_api_without_legacy_cli_pdk_restriction(project, monkeypatch):
    import analog_mc_yield_run as mc
    calls = []
    payload = {"rc": 0, "verdict": "FAIL", "mc_runs": 3, "mc_yield_pct": 20,
               "reason": "Mānoa 目標"}
    def native(*args):
        calls.append(args)
        return payload
    monkeypatch.setattr(mc, "run_block", native)
    report = project / "native-mc.json"
    rc = sim.main(["mc", str(project), "--block", "stage", "--container", "native-tool", "--pdk", "project-process", "--n", "3", "--json", str(report)])
    assert calls == [(project, "stage", "native-tool", "project-process", 3)]
    assert rc == 0 and report.read_bytes() == (json.dumps(payload, indent=2) + "\n").encode()


def test_mc_cli_interrupted_publication_keeps_current_reader_on_complete_report(project, monkeypatch):
    import _atomic_artefact as atomic
    import analog_mc_yield_run as mc
    report = project / "native-mc.json"
    previous = {"rc": 0, "verdict": "PASS", "mc_runs": 2}
    report.write_text(json.dumps(previous, indent=2) + "\n")
    monkeypatch.setattr(mc, "run_block", lambda *args: {
        "rc": 1, "verdict": "FAIL", "mc_runs": 3, "reason": "replacement"})
    real_open = open

    class InterruptedFile:
        def __init__(self, handle):
            self.handle = handle

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def write(self, data):
            self.handle.write(data[:max(1, len(data) // 2)])
            raise KeyboardInterrupt("publication interrupted")

    def interrupted_open(path, *args, **kwargs):
        handle = real_open(path, *args, **kwargs)
        return InterruptedFile(handle) if atomic.is_temp_artefact(path) else handle

    monkeypatch.setattr(atomic, "open", interrupted_open, raising=False)
    with pytest.raises(KeyboardInterrupt, match="publication interrupted"):
        sim.main(["mc", str(project), "--block", "stage", "--container", "native-tool",
                  "--pdk", "project-process", "--n", "3", "--json", str(report)])
    assert json.loads(report.read_text()) == previous
    assert not atomic.temp_name_for(report).exists()


def test_a10_only_explicit_inapplicability_gets_na(project):
    absent = sim.run_step("A10", project, {"name": "stage"}, _options(), _never)
    declared = sim.run_step("A10", project, {"name": "stage"}, _options(config={"features": {"analog_trim": False}}), _never)
    assert absent["status"] == "NOT_MEASURED"
    assert declared["status"] == "NOT_APPLICABLE"
    derived = sim.run_step("A10", project, {"name": "stage"}, _options(features={"analog_trim": False}), _never)
    assert derived["status"] == "NOT_APPLICABLE"


def test_a10_runs_source_calibration_on_the_delivered_dut(project):
    options = _options(config={"blocks": {"stage": {"calibration": {
        "applicable": True, "testbench": "phase3/analog/stage/tb_stage.sp",
        "limits": {"level": {"min": 0.9, "max": 1.1}}, "required_measurements": ["level"]}}}})
    result = sim.run_step("A10", project, {"name": "stage"}, options,
                          lambda *a, **k: {"returncode": 0, "stdout": "level = 1.0\n"})
    assert result["status"] == "PASS"


def test_real_shipped_native_measurement_deck_is_parsed_without_changing_it():
    path = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "calibration", "ngspice47_cal_meas_rows.sp")
    original = path.read_bytes()
    assert sim._MEASURE.findall(sim._deck_text(path)) == ["cal_avg", "cal_max", "cal_at"]
    assert sim._ANALYSIS.search(sim._deck_text(path)).group(1).casefold() == "tran"
    assert path.read_bytes() == original


def test_explicit_metric_attribution_keeps_every_native_context(project):
    spec = project / 'phase3/analog/stage/spec.json'
    spec.write_text(json.dumps({'specs': [{'name': 'vout', 'min': 1.1, 'max': 1.3, 'unit': 'V'},
                                         {'name': 'psrr', 'min': 40, 'unit': 'dB'}]}))
    bindings = {'measurements': {
        'vout_low': {'spec_key': 'vout', 'unit': 'V'},
        'vout_nominal': {'spec_key': 'vout', 'unit': 'V'},
        'psrr_1hz': {'unit': 'dB'}}}
    rows = sim.attributed_study_measurements(spec, bindings, {
        'vout_low': 1.05, 'vout_nominal': 1.2, 'psrr_1hz': 60})
    assert [row['label'] for row in rows] == ['vout_low', 'vout_nominal']
    assert [row['violation'] for row in rows] == [True, False]
    coverage = sim._source_measurement_coverage(spec, rows)
    assert coverage['missing'] == ['psrr']


@pytest.mark.parametrize('headroom,vout,point,expected,violations', [
    (0.4, 1.2, 1.6, 'PASS', []),
    (-0.1, 1.2, 1.6, 'NOT_MEASURED', []),
    (0.6, 1.2, 1.6, 'NOT_MEASURED', []),
    (0.4, 1.0, 1.6, 'NOT_MEASURED', ['regulated_vout']),
    (0.4, 1.2, 1.8, 'NOT_MEASURED', []),
])
def test_dropout_upper_bound_needs_same_point_regulation_and_cannot_prove_failure(
        project, headroom, vout, point, expected, violations):
    spec = project / 'phase3/analog/stage/spec.json'
    spec.write_text(json.dumps({'specs': [{'name': 'vout', 'min': 1.1, 'max': 1.3, 'unit': 'V'},
                                         {'name': 'dropout', 'max': 0.5, 'unit': 'V'}]}))
    bindings = {'measurements': {
        'headroom': {'spec_key': 'dropout', 'unit': 'V', 'analysis': 'DC', 'at': 1.6,
            'interpretation': 'upper_bound_when_regulated', 'regulation_measurement': 'regulated_vout'},
        'regulated_vout': {'spec_key': 'vout', 'unit': 'V', 'analysis': 'DC', 'at': point}}}
    rows = sim.attributed_study_measurements(spec, bindings, {'headroom': headroom, 'regulated_vout': vout})
    assert rows[0]['status'] == expected
    assert [row['label'] for row in rows if row['violation']] == violations


@pytest.mark.parametrize('step,metrics,analyses,expected', [
    ('A06', {}, ['.op', '.tran'], 'PASS'),
    ('A06', {}, ['.tran'], 'NOT_MEASURED'),
    ('A07', {}, ['.op', '.tran'], 'NOT_MEASURED'),
    ('A07', {'enob': 14.2}, ['.op', '.tran'], 'PASS'),
    ('A07', {'enob': 14.2}, ['.tran'], 'NOT_MEASURED'),
    ('A07', {'enob': 12.0}, ['.op', '.tran'], 'FAIL')])
def test_incremental_consumer_distinguishes_method_from_measured_enob_and_ignores_old_density_guard(
        project, monkeypatch, step, metrics, analyses, expected):
    import analog_incremental_capture as incremental
    spec = project / 'phase3/analog/stage/spec.json'
    spec.write_text(json.dumps({'specs': [{'name': 'enob', 'min': 14, 'unit': 'bit'}]}))
    entry = {'kind': 'incremental_capture', 'settings': 'settings.json', 'result': 'series/score.json'}
    (project / 'phase3/analog/stage/measurement_studies.json').write_text(json.dumps([entry]))
    calls = []
    def consume(*arguments):
        calls.append(arguments[-1])
        return {'status': 'PASS', 'measurements': metrics, 'definitions': ['enob'],
                'analyses': analyses, 'outputs': [], 'executions': [], 'native_inputs': {}}
    monkeypatch.setattr(incremental, 'consume_study', consume)
    result = sim.run_step(step, project, {'name': 'stage'}, _options(active_blocks=['stage']), _never)
    assert calls == [step]
    assert result['status'] == expected
    assert result['metrics'].get('enob') == metrics.get('enob')
    if not metrics:
        assert result['metrics']['source_measurement_coverage']['missing'] == ['enob']
