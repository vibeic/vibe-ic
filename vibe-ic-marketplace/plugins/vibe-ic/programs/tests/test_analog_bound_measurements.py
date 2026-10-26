"""Explicit native measurement controls; no EDA process is launched here."""
import json
from pathlib import Path

import pytest

import analog_bound_measurements as measurements


@pytest.mark.parametrize("prefix,expected", [("", "PASS"), ("not ", "NOT_MEASURED"),
                                             ("* denied ", "NOT_MEASURED")])
def test_native_measurement_records_are_formal_not_prose(tmp_path, prefix, expected):
    net = tmp_path / "unit.sp"
    net.write_text(".subckt unit a b\nr1 a b 1k\n.ends unit\n")
    template = tmp_path / "tb.sp"
    template.write_text(f'.include "{net}"\nxdut in out unit\nv1 in 0 1\n.end\n')
    binding = {"analysis": {"kind": "OP", "temperature_c": 25},
               "measurements": {"vout": {"analysis": "OP", "expression": "v(out)"}}}
    result = measurements.run_measurements(tmp_path, net, template, binding, tmp_path / "result",
        lambda *args, **kwargs: {"returncode": 0, "stdout":
            prefix + "Doing analysis at TEMP = 25 and TNOM = 25\n" + prefix + "MEAS vout=0.975\n"})
    assert result["status"] == expected
    if expected == "PASS":
        assert result["measurements"]["vout"] == 0.975
    else:
        assert not result["measurements"]


def test_bound_cli_interruption_preserves_previous_complete_report(tmp_path, monkeypatch):
    from contextlib import contextmanager
    import _atomic_artefact as atomic
    import analog_native_flow
    output = tmp_path / "out"
    output.mkdir()
    destination = output / "result.json"
    previous = '{"status": "previous complete result"}\n'
    destination.write_text(previous)
    bindings = tmp_path / "bindings.json"
    bindings.write_text("{}")
    monkeypatch.setattr(analog_native_flow, "NativeCommands", lambda *args: object())
    monkeypatch.setattr(measurements, "run_measurements", lambda *args: {
        "status": "PASS", "measurements": {"vout": 0.975}, "native_inputs": {}})
    original = atomic.writing

    @contextmanager
    def interrupted(path, *args, **kwargs):
        with original(path, *args, **kwargs) as stream:
            class PartialWriter:
                encoding = stream.encoding
                def write(self, text):
                    stream.write(text[:len(text) // 2])
                    stream.flush()
                    raise KeyboardInterrupt("native report publication interrupted")
            yield PartialWriter()
    monkeypatch.setattr(atomic, "writing", interrupted)
    with pytest.raises(KeyboardInterrupt):
        measurements.main([str(tmp_path), "--netlist", str(tmp_path / "unit.sp"),
                           "--testbench", str(tmp_path / "tb.sp"), "--bindings", str(bindings),
                           "--out", str(output), "--container", "", "--image", "unit-only"])
    assert destination.read_text() == previous
    assert json.loads(destination.read_text())["status"] == "previous complete result"


def test_native_op_uses_delivered_dut_and_retains_measured_value(tmp_path):
    net = tmp_path / "unit.sp"
    net.write_text(".subckt unit a b\nr1 a b 1k\n.ends unit\n")
    template = tmp_path / "tb.sp"
    template.write_text(f'.include "{net}"\nxdut in out unit\nv1 in 0 1\n.control\ntran 1n 28m\n.endc\n.end\n')
    bindings = {"analysis": {"kind": "OP"}, "measurements": {
        "vout": {"analysis": "OP", "expression": "v(out)"}}}
    calls = []
    def run(program, argv, **kwargs):
        calls.append((program, argv))
        return {"returncode": 0, "stdout": "MEAS vout=0.975\n"}
    result = measurements.run_measurements(tmp_path, net, template, bindings, tmp_path / "result", run)
    assert result["status"] == "PASS" and result["measurements"]["vout"] == 0.975
    assert len(calls) == 1
    assert "tran 1n 28m" not in Path(calls[0][1][-1]).read_text()
    assert "xdut in out unit" in Path(calls[0][1][-1]).read_text()
    assert ".save v(out)" in Path(calls[0][1][-1]).read_text()
    assert result["native_inputs"]["netlist"]["sha256"] == measurements.sha(net)


@pytest.mark.parametrize("binding", [{"analysis": {"kind": "TRAN"}},
    {"analysis": {"kind": "AC", "points": 10, "start_hz": 1}},
    {"analysis": {"kind": "DC", "source": "v1", "start": 1, "stop": 2, "step": -0.1}}])
def test_undeclared_or_invalid_analysis_refuses_without_native_launch(binding):
    with pytest.raises(ValueError):
        measurements.emit_deck(".end\n", binding)


def test_native_endpoint_binding_reads_actual_last_sample_without_extrapolation():
    binding = {"analysis": {"kind": "AC", "points": 20, "start_hz": 1, "stop_hz": 1e6},
               "measurements": {"psrr": {"analysis": "AC", "expression": "-vdb(out)", "frequency_hz": "last"}}}
    deck = measurements.emit_deck(".save v(other)\n.end\n", binding)
    assert "bound_psrr[length(bound_psrr)-1]" in deck
    assert "AT=1000000" not in deck
    assert ".save v(out)" in deck and ".save v(other)" in deck


def test_transient_analysis_preserves_physical_stimulus_and_native_time_average():
    template = ("* original poweron\nv_supply vdd 0 pwl(0 0 100n 1.2)\n"
                ".options trtol=1\n.control\ntran 1n 28m\n.endc\n.end\n")
    bindings = {"analysis": {"kind": "TRAN", "step_s": 5e-9, "stop_s": 9.1e-6},
        "measurements": {"idd": {"analysis": "TRAN", "expression": "-i(v_supply)",
            "statistic": "AVG", "from_s": 7e-6, "to_s": 9e-6}},
        "execution": {"threads": 1, "wait_policy": "PASSIVE",
            "numerical_options": {"reltol": 1e-6, "vntol": 1e-8, "abstol": 1e-15}}}
    deck = measurements.emit_deck(template, bindings)
    assert "v_supply vdd 0 pwl(0 0 100n 1.2)" in deck and ".options trtol=1" in deck
    assert f"tran {5e-9:.17g} {9.1e-6:.17g} 0" in deck and "28m" not in deck
    assert "meas TRAN idd AVG bound_idd" in deck and ".save i(v_supply)" in deck
    assert "set num_threads=1" in deck and "vntol=" in deck


@pytest.mark.parametrize("analysis", [{"step_s": 0}, {"stop_s": -1},
    {"step_s": float("nan")}, {"stop_s": float("inf")}, {"start_s": -1},
    {"start_s": 10e-6}, {"start_s": 8e-6}])
def test_invalid_transient_analysis_cannot_launch_native(analysis):
    binding = {"analysis": {"kind": "TRAN", "step_s": 5e-9, "stop_s": 9.1e-6, **analysis},
        "measurements": {"idd": {"analysis": "TRAN", "expression": "-i(v_supply)",
            "statistic": "AVG", "from_s": 7e-6, "to_s": 9e-6}}}
    with pytest.raises(ValueError):
        measurements.emit_deck(".end\n", binding)


def test_literal_transient_statistic_still_cannot_fake_a_dut_measurement(tmp_path):
    net = tmp_path / "unit.sp"
    net.write_text(".subckt unit a b\nr1 a b 1k\n.ends unit\n")
    template = tmp_path / "tb.sp"
    template.write_text(f'.include "{net}"\nxdut in out unit\nv1 in 0 1\n.end\n')
    bindings = {"analysis": {"kind": "TRAN", "step_s": 1e-9, "stop_s": 1e-6},
        "measurements": {"pretend": {"analysis": "TRAN", "expression": "1.2",
            "statistic": "AVG", "from_s": 0, "to_s": 1e-6}}}
    calls = []
    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return {"returncode": 0, "stdout": "MEAS pretend=1.2\n"}
    result = measurements.run_measurements(tmp_path, net, template, bindings,
        tmp_path / "result", run)
    assert result["status"] == "NOT_MEASURED"
    assert "pretend" in result["detail"] and calls == []


def test_execution_choice_survives_replaced_controls_and_reaches_native_process(tmp_path):
    net = tmp_path / "unit.sp"
    net.write_text(".subckt unit a b\nr1 a b 1k\n.ends unit\n")
    template = tmp_path / "tb.sp"
    template.write_text(f'.include "{net}"\nxdut in out unit\nv1 in 0 1\n.options reltol=1e-5\n'
                        '.control\nset num_threads=8\nop\n.endc\n.end\n')
    bindings = {"analysis": {"kind": "OP"}, "measurements": {
        "vout": {"analysis": "OP", "expression": "v(out)"}},
        "execution": {"threads": 1, "wait_policy": "PASSIVE"}}
    def run(program, argv, **kwargs):
        assert program == "@env"
        assert argv[:4] == ["OMP_NUM_THREADS=1", "OMP_WAIT_POLICY=PASSIVE", "GOMP_SPINCOUNT=0", "ngspice"]
        deck = Path(argv[-1]).read_text()
        assert ".control\nset num_threads=1\nop\n" in deck
        assert "set num_threads=8" not in deck
        assert ".options reltol=1e-5" in deck
        return {"returncode": 0, "stdout": "MEAS vout=0.975\n"}
    result = measurements.run_measurements(tmp_path, net, template, bindings, tmp_path / "result", run)
    assert result["status"] == "PASS"
    assert result["bindings"]["execution"] == bindings["execution"]


@pytest.mark.parametrize("execution", [{"threads": 0}, {"threads": True},
    {"threads": 1.5}, {"wait_policy": "PASSIVE;other"}, {"method": "gear;other"},
    {"ngspice_bin": "relative/ngspice"}, {"numerical_options": []},
    {"numerical_options": {"reltol": 0}}, {"numerical_options": {"unknown": 1e-6}}, []])
def test_invalid_execution_settings_refuse_before_native_launch(execution):
    with pytest.raises(ValueError):
        measurements.emit_deck(".end\n", {"analysis": {"kind": "OP"}, "measurements": {
            "vout": {"analysis": "OP", "expression": "v(out)"}}, "execution": execution})


@pytest.mark.parametrize("environment", [{}, {"threads": 1, "wait_policy": "PASSIVE"}])
@pytest.mark.parametrize("change_binary", [False, True])
def test_selected_native_binary_is_executed_and_frozen(tmp_path, environment, change_binary):
    binary = tmp_path / "selected ngspice"
    binary.write_bytes(b"selected native bytes")
    digest = measurements.sha(binary)
    net = tmp_path / "unit.sp"
    net.write_text(".subckt unit a b\nr1 a b 1k\n.ends unit\n")
    template = tmp_path / "tb.sp"
    template.write_text(f'.include "{net}"\nxdut in out unit\nv1 in 0 1\n'
                        '.options method=trap reltol=1e-5\n.end\n')
    bindings = {"analysis": {"kind": "OP"}, "measurements": {
        "vout": {"analysis": "OP", "expression": "v(out)"}},
        "execution": {**environment, "ngspice_bin": str(binary), "method": "gear"}}
    def run(program, argv, **kwargs):
        assert program == ("@env" if environment else "@" + str(binary))
        if environment:
            assert argv[-3] == str(binary)
        deck = Path(argv[-1]).read_text()
        assert "method=trap" not in deck and "method=gear" in deck
        assert "reltol=1e-5" in deck
        if change_binary:
            binary.write_bytes(b"changed native bytes")
        return {"returncode": 0, "stdout": "MEAS vout=0.975\n"}
    result = measurements.run_measurements(tmp_path, net, template, bindings, tmp_path / "result", run)
    assert result["native_inputs"]["native_binary"]["sha256"] == digest
    assert result["status"] == ("NOT_MEASURED" if change_binary else "PASS")
    assert bool(result["measurements"]) is (not change_binary)


@pytest.mark.parametrize("native_temperature,expected", [("-40", "PASS"), ("27", "NOT_MEASURED"),
                                                         (None, "NOT_MEASURED")])
def test_temperature_point_is_a_native_condition_not_a_case_label(tmp_path, native_temperature, expected):
    net = tmp_path / "unit.sp"
    net.write_text(".subckt unit a b\nr1 a b 1k\n.ends unit\n")
    template = tmp_path / "tb.sp"
    template.write_text(f'.temp 27\n.include "{net}"\nxdut in out unit\nv1 in 0 1\n.end\n')
    bindings = {"analysis": {"kind": "OP", "temperature_c": -40}, "measurements": {
        "vout": {"analysis": "OP", "expression": "v(out)"}}}
    def run(program, argv, **kwargs):
        deck = Path(argv[-1]).read_text()
        assert deck.startswith("* Explicit native measurement\n.temp -40\n")
        assert ".temp 27" not in deck
        assert f'.include "{net}"' in deck
        temperature = (f"Doing analysis at TEMP = {native_temperature} and TNOM = 27\n"
                       if native_temperature is not None else "")
        return {"returncode": 0, "stdout": temperature + "MEAS vout=0.975\n"}
    result = measurements.run_measurements(tmp_path, net, template, bindings, tmp_path / "result", run)
    assert result["status"] == expected
    assert result["temperature"]["matched"] is (expected == "PASS")
    assert bool(result["measurements"]) is (expected == "PASS")


def test_first_include_card_is_never_lost_as_the_native_title():
    bindings = {"analysis": {"kind": "OP"}, "measurements": {
        "vout": {"analysis": "OP", "expression": "v(out)"}}}
    deck = measurements.emit_deck('.include "unit.sp"\n.end\n', bindings)
    assert deck.splitlines()[:2] == ["* Explicit native measurement", '.include "unit.sp"']


@pytest.mark.parametrize("temperature", [-273.15, True, float("nan"), "-40"])
def test_invalid_temperature_refuses_before_native_launch(temperature):
    with pytest.raises(ValueError):
        measurements.emit_deck(".end\n", {
            "analysis": {"kind": "OP", "temperature_c": temperature},
            "measurements": {"vout": {"analysis": "OP", "expression": "v(out)"}}})


def test_native_capture_uses_wrdata_filename_token_and_retains_bound_vectors(tmp_path):
    binding = {"analysis": {"kind": "OP"}, "measurements": {
        "vout": {"analysis": "OP", "expression": "v(out)"}}, "capture": {"output": "v(out)"}}
    path = tmp_path / "curve.dat"
    deck = measurements.emit_deck(".end\n", binding, path)
    assert f"wrdata {path} bound_output\n" in deck
    assert f'wrdata "{path}"' not in deck


def test_literal_op_binding_cannot_be_credited_as_another_dut_measurement(tmp_path):
    net = tmp_path / "unit.sp"
    net.write_text(".subckt unit a b\nr1 a b 1k\n.ends unit\n")
    template = tmp_path / "tb.sp"
    template.write_text(f'.include "{net}"\nxdut in out unit\nv1 in 0 1\n.end\n')
    bindings = {"analysis": {"kind": "OP"}, "measurements": {
        "vout": {"analysis": "OP", "expression": "v(out)"},
        "pretend": {"analysis": "OP", "expression": "1.2"}}}
    result = measurements.run_measurements(tmp_path, net, template, bindings, tmp_path / "result",
                                          lambda *a, **k: pytest.fail("literal result must not launch native tool"))
    assert result["status"] == "NOT_MEASURED"
    assert "pretend" in result["detail"]


def test_relative_quoted_dut_and_model_paths_keep_template_context(tmp_path):
    source = tmp_path / "source with space"
    source.mkdir()
    net = source / "unit circuit.sp"
    net.write_text(".subckt unit a b\nr1 a b 1k\n.ends unit\n")
    model = source / "models with space.lib"
    model.write_text(".lib typical\n.model resistor r\n.endl typical\n")
    template = source / "tb.sp"
    template.write_text('.include "unit circuit.sp"\n.lib "models with space.lib" typical\n'
                        'xdut in out unit\nv1 in 0 1\n.end\n')
    bindings = {"analysis": {"kind": "OP"}, "measurements": {"vout": {"analysis": "OP", "expression": "v(out)"}}}
    calls = []
    def run(program, argv, **kwargs):
        calls.append(argv)
        deck = Path(argv[-1]).read_text()
        assert f'.include "{net}"' in deck
        assert f'.lib "{model}" typical' in deck
        return {"returncode": 0, "stdout": "MEAS vout=1.0\n"}
    result = measurements.run_measurements(tmp_path, net, template, bindings, tmp_path / "elsewhere", run)
    assert result["status"] == "PASS" and len(calls) == 1
    assert '.include "unit circuit.sp"' in template.read_text()


def test_inflight_dut_change_cannot_receive_bound_native_acceptance(tmp_path):
    net = tmp_path / "unit.sp"
    net.write_text(".subckt unit a b\nr1 a b 1k\n.ends unit\n")
    template = tmp_path / "tb.sp"
    template.write_text('.include "unit.sp"\nxdut in out unit\nv1 in 0 1\n.end\n')
    bindings = {"analysis": {"kind": "OP"}, "measurements": {"vout": {"analysis": "OP", "expression": "v(out)"}}}
    def run(*args, **kwargs):
        net.write_text(net.read_text().replace("1k", "2k"))
        return {"returncode": 0, "stdout": "MEAS vout=1.0\n"}
    result = measurements.run_measurements(tmp_path, net, template, bindings, tmp_path / "result", run)
    assert result["status"] == "NOT_MEASURED"
    assert "netlist" in result["changed_inputs"]


def _model_project(tmp_path):
    net = tmp_path / "unit.sp"
    net.write_text('.lib "corner models.lib" tt\n.subckt unit a b\nr1 a b 1k\n.ends unit\n')
    library = tmp_path / "corner models.lib"
    library.write_text('.lib tt\n.include "active models.inc"\n.endl tt\n'
                       '.lib ss\n.include inactive.inc\n.endl ss\n')
    active = tmp_path / "active models.inc"
    active.write_text('.include leaf.mod\n')
    leaf = tmp_path / "leaf.mod"
    leaf.write_text('.model model_alpha r\n')
    inactive = tmp_path / "inactive.inc"
    inactive.write_text('.model inactive r\n')
    template = tmp_path / "tb.sp"
    template.write_text('.include unit.sp\nxdut in out unit\nv1 in 0 1\n.end\n')
    bindings = {"analysis": {"kind": "OP"}, "measurements": {"vout": {"analysis": "OP", "expression": "v(out)"}}}
    return net, template, bindings, library, active, leaf, inactive


def test_selected_model_transitive_inputs_are_bound_before_native_and_stale_after_change(tmp_path):
    net, template, bindings, library, active, leaf, inactive = _model_project(tmp_path)
    result = measurements.run_measurements(tmp_path, net, template, bindings, tmp_path / "result",
        lambda *a, **k: {"returncode": 0, "stdout": "MEAS vout=1.0\n"})
    assert result["status"] == "PASS"
    views = result["native_inputs"]
    for path in (net, library, active, leaf):
        assert views["include:" + str(path)] == {"path": str(path), "sha256": measurements.sha(path)}
    assert "include:" + str(inactive) not in views
    assert measurements.validate_consumed_inputs(tmp_path, views)[0] is True
    leaf.write_text('.model model_alpha r rsh=2\n')
    assert measurements.validate_consumed_inputs(tmp_path, views)[0] is False


def test_legacy_model_record_without_executed_closure_is_not_upgraded_in_place(tmp_path):
    net, template, bindings, *_ = _model_project(tmp_path)
    result = measurements.run_measurements(tmp_path, net, template, bindings, tmp_path / "result",
        lambda *a, **k: {"returncode": 0, "stdout": "MEAS vout=1.0\n"})
    views = {key: value for key, value in result["native_inputs"].items() if not key.startswith("include:")}
    assert measurements.validate_consumed_inputs(tmp_path, views)[0] is False
    assert not any(key.startswith("include:") for key in views)


def test_inflight_transitive_model_change_refuses_native_acceptance(tmp_path):
    net, template, bindings, _library, _active, leaf, _inactive = _model_project(tmp_path)
    def run(*args, **kwargs):
        leaf.write_text('.model model_alpha r rsh=3\n')
        return {"returncode": 0, "stdout": "MEAS vout=1.0\n"}
    result = measurements.run_measurements(tmp_path, net, template, bindings, tmp_path / "result", run)
    assert result["status"] == "NOT_MEASURED"
    assert "include:" + str(leaf) in result["changed_inputs"]


def test_known_native_failure_stays_fail_when_model_also_changes(tmp_path):
    net, template, bindings, _library, _active, leaf, _inactive = _model_project(tmp_path)
    def run(*args, **kwargs):
        leaf.write_text('.model model_alpha r rsh=4\n')
        return {"returncode": 1, "stdout": "MEAS vout=1.0\nError: native analysis failed\n"}
    result = measurements.run_measurements(tmp_path, net, template, bindings, tmp_path / "result", run)
    assert result["status"] == "FAIL"
    assert "include:" + str(leaf) in result["changed_inputs"]
    assert "changed during execution" in result["detail"]
    assert result["measurements"] == {}
    assert result["executions"][0]["returncode"] == 1
