"""Exercise native SPICE output and original numerical limits without passports."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import analog_bound_measurements as bound
import analog_incremental_statistics as statistics
import analog_native_em as em
import analog_native_flow as native
import analog_native_sim as sim
from flow_native_adapters import Commands
from flow_native_analog import command_bridge

pytestmark = pytest.mark.skipif(shutil.which("ngspice") is None, reason="native ngspice unavailable")


@pytest.fixture
def project(tmp_path):
    block = tmp_path / "phase3/analog/stage"
    block.mkdir(parents=True)
    (block / "stage.sp").write_text("* resistor DUT\n.subckt stage a b\nr1 a b 1k\n.ends stage\n")
    (block / "spec.json").write_text(json.dumps({"specs": [{"name": "level", "min": 0.9, "max": 1.1, "unit": "V"}]}))
    return tmp_path


def executor(project, kind):
    directory = project / ("commands-" + kind)
    directory.mkdir()
    if kind == "native":
        return native.NativeCommands(project, directory, "")
    return command_bridge(Commands(directory), project)


@pytest.mark.parametrize("kind", ["native", "table"])
@pytest.mark.parametrize("voltage,expected", [(0.9, "PASS"), (1.1, "PASS"), (0.89, "FAIL"), (1.11, "FAIL")])
def test_native_nominal_voltage_uses_original_bounds(project, kind, voltage, expected):
    block = project / "phase3/analog/stage"
    (block / "tb_stage.sp").write_text(
        '* actual transient DUT\n.include "stage.sp"\nxdut in out stage\n'
        f'v1 in 0 {voltage}\n.control\ntran 1n 100n\n'
        'meas tran level avg v(out) from=10n to=100n\n.endc\n.end\n')
    result = sim.run_step("A07", project, {"name": "stage"}, {"config": {}}, executor(project, kind))
    assert result["status"] == expected, result
    assert result["metrics"]["level"] == pytest.approx(voltage)
    assert result["executions"][0]["returncode"] == 0
    assert all(set(view) == {"path"} for view in result["native_inputs"].values())
    assert "log_sha256" not in result["executions"][0]


@pytest.mark.parametrize("kind", ["native", "table"])
def test_completed_native_run_without_measurement_is_not_measured(project, kind):
    block = project / "phase3/analog/stage"
    (block / "tb_stage.sp").write_text(
        '* actual transient without requested output\n.include "stage.sp"\nxdut in out stage\nv1 in 0 1\n'
        '.control\ntran 1n 100n\nif 0\nmeas tran level avg v(out) from=10n to=100n\nend\n.endc\n.end\n')
    result = sim.run_step("A07", project, {"name": "stage"}, {"config": {}}, executor(project, kind))
    assert result["status"] == "NOT_MEASURED", result
    assert result["executions"][0]["returncode"] == 0
    assert "level" not in result["metrics"]


def test_native_bound_op_retains_model_paths_and_measured_value(project):
    block = project / "phase3/analog/stage"
    template = block / "tb_stage.sp"
    template.write_text('* actual OP stimulus\n.include "stage.sp"\nxdut in out stage\nv1 in 0 1.025\n.end\n')
    bindings = {"analysis": {"kind": "OP", "temperature_c": 27},
                "measurements": {"level": {"analysis": "OP", "expression": "v(out)"}}}
    result = bound.run_measurements(project, block / "stage.sp", template, bindings,
                                    project / "op", executor(project, "native"))
    assert result["status"] == "PASS", result
    assert result["measurements"]["level"] == pytest.approx(1.025)
    assert any(Path(row["path"]).name == "stage.sp" for role, row in result["native_inputs"].items() if role.startswith("include:"))
    assert all(set(row) <= {"path", "section"} for row in result["native_inputs"].values())


def test_missing_native_model_and_missing_executable_are_honest(project):
    block = project / "phase3/analog/stage"
    template = block / "tb_stage.sp"
    template.write_text('* unavailable model\n.include "missing-process-model.sp"\n.include "stage.sp"\n'
                        'xdut in out stage\nv1 in 0 1\n.end\n')
    bindings = {"analysis": {"kind": "OP"}, "measurements": {"level": {"analysis": "OP", "expression": "v(out)"}}}
    result = bound.run_measurements(project, block / "stage.sp", template, bindings,
                                    project / "op", executor(project, "native"))
    assert result["status"] == "NOT_MEASURED", result
    assert not result["executions"]
    missing = command_bridge(Commands(project / "commands-native"), project)("@no-such-native-eda-tool", [])
    assert missing["returncode"] == 127


def raw_capture(project):
    deck, raw = project / "native-op.sp", project / "op.raw"
    deck.write_text('* actual voltage-divider OP\nv1 in 0 1\nr1 in out 1k\nr2 out 0 1k\n.op\n.end\n')
    result = executor(project, "native")("@ngspice", ["-b", "-r", raw, deck], outputs=[raw])
    assert result["returncode"] == 0, result
    assert result["outputs"] == [str(raw)]
    return raw


def test_native_raw_plain_and_gzip_need_no_identity_record(project):
    raw = raw_capture(project)
    compressed = raw.with_suffix(".raw.gz")
    with gzip.open(compressed, "wb") as stream:
        stream.write(raw.read_bytes())
    assert em.NativeRaw(raw).row()["out"] == pytest.approx(0.5)
    assert em.read_op_capture(compressed)["out"] == pytest.approx(0.5)
    record = {"outputs": [str(compressed)], "native_raw": {
        "executed_path": str(raw), "stored_path": str(compressed), "encoding": "gzip"}}
    assert em.native_capture(record, transient=False) == compressed


def test_native_raw_truncated_payload_still_fails(project):
    raw = raw_capture(project)
    raw.write_bytes(raw.read_bytes()[:-8])
    with pytest.raises(ValueError, match="payload dimensions"):
        em.NativeRaw(raw)


def test_native_gzip_crc_still_fails(project):
    raw = raw_capture(project)
    compressed = raw.with_suffix(".raw.gz")
    data = bytearray(gzip.compress(raw.read_bytes()))
    data[-8] ^= 1
    compressed.write_bytes(data)
    with pytest.raises((gzip.BadGzipFile, ValueError)):
        em.NativeRaw(compressed)


def test_native_parameter_probe_uses_actual_log_and_temperature(project):
    deck = project / "probe.sp"
    deck.write_text('* native parameter probe\nv1 node 0 1.025\nr1 node 0 1k\n.control\ntran 1n 100n\n'
                    'meas tran field avg v(node) from=10n to=100n\n.endc\n.end\n')
    execution = executor(project, "native")("@ngspice", ["-b", deck])
    path = project / "probe-result.json"
    path.write_text(json.dumps({"execution": execution}))
    probe = {"receipt": str(path), "deck": {"path": str(deck)}}
    status, values, detail = statistics._native_probe(probe, [{"key": "field"}], "")
    assert status == "PASS", detail
    assert values["field"] == pytest.approx(1.025)
    status, values, detail = statistics._native_probe(probe, [{"key": "absent"}], "")
    assert status == "NOT_MEASURED" and not values, detail


@pytest.mark.parametrize("voltage,expected", [(1.0, "PASS"), (1.2, "FAIL")])
def test_native_declared_pvt_retains_all_nine_coordinates_and_limits(project, voltage, expected):
    import analog_declared_pvt as pvt
    block = project / "phase3/analog/stage"
    library = block / "models.lib"
    library.write_text("".join(f'.lib {section}\n.model process_diode D(Is=1e-14)\n.endl {section}\n' for section in ("tt", "ss", "ff")))
    net = block / "stage.sp"
    net.write_text('.lib "models.lib" tt\n' + net.read_text())
    (block / "spec.json").write_text(json.dumps({"specs": [{"name": "vout", "min": 0.9, "max": 1.1, "unit": "V"}]}))
    (block / "testbench_inputs.json").write_text(json.dumps({"block": "stage", "ports": ["a", "b"],
        "testbench": {"supply_exprs": [str(voltage)], "stimulus": ["v_force a 0 {supply}"],
            "control": ["op", "let observed = v(b)", 'echo "MEAS vout=" $&observed', "quit"]}}))
    result = pvt.run(project, "stage", {}, {"process_sections": ["tt", "ss", "ff"]},
                     project / "pvt", executor(project, "native"))
    assert result["status"] == expected, result
    assert len(result["executions"]) == 9
    assert all(corner["status"] == expected for corner in result["metrics"]["corners"])
    assert all(corner["measurements"]["vout"] == pytest.approx(voltage) for corner in result["metrics"]["corners"])
    assert {corner["temperature_c"] for corner in result["metrics"]["corners"]} == {-40, 27, 125}


def test_explicit_native_sweep_binary_returns_real_measurements(project, monkeypatch):
    import subprocess
    import analog_real_corner_sweep as sweep
    deck = project / "selected-native.sp"
    deck.write_text('* selected native binary\nv1 node 0 1.025\nr1 node 0 1k\n.control\ntran 1n 100n\n'
                    'meas tran level avg v(node) from=10n to=100n\n.endc\n.end\n')
    def local_transport(container, command, timeout=None):
        return subprocess.run(["bash", "-lc", command], capture_output=True, text=True, timeout=timeout)
    monkeypatch.setattr(sweep, "_docker", local_transport)
    binary = shutil.which("ngspice")
    ok, values, transcript, state = sweep._run_ngspice("", str(deck), cwd=str(project), ngspice_bin=binary)
    assert ok, transcript
    assert values["level"] == pytest.approx(1.025)
    assert state["native_binary"] == {"path": binary}
    assert not state["partial"]
    with pytest.raises(ValueError, match="not executable"):
        sweep._selected_ngspice_binary("", "/no-such-native-ngspice")


def test_native_selected_model_closure_retains_sections_and_missing_model_errors(project):
    import analog_mc_yield_run as mc
    library = project / "native-models.lib"
    library.write_text('.lib tt\n.model diode D(Is=1e-14)\n.endl tt\n'
                       '.lib ff\n.model diode D(Is=2e-14)\n.endl ff\n')
    text, files = mc._statistical_closure(project, library, "ff")
    assert "Is=2e-14" in text and "Is=1e-14" not in text
    assert files == [{"path": str(library), "section": "ff"}]
    with pytest.raises(ValueError, match="section absent"):
        mc._statistical_closure(project, library, "ss")
