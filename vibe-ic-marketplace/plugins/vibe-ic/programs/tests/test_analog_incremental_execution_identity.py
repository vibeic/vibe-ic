"""One neutral native point; authority controls never replay an ADC population.

The PVT collector controls use the exact native point plus software manifests;
those manifests are unit fixtures, not nine-corner or ADC acceptance evidence.
"""
import copy
import json
import os
from pathlib import Path
import subprocess

import pytest

import analog_incremental_capture as capture
import analog_incremental_pvt as pvt
from test_analog_incremental_capture import _template


@pytest.fixture(scope="module")
def native_point(tmp_path_factory):
    root = tmp_path_factory.mktemp("neutral-native")
    project = root / "project"
    bdir = project / "phase3/analog/converter"
    bdir.mkdir(parents=True)
    source, spec, topology = _template(bdir)
    topology["constants"]["window_clocks"] = 4
    text = source.read_text()
    body = text[text.index(".subckt"):text.index(".ends conv") + len(".ends conv")]
    signals = """
v_reset reset_b vss pulse(1.8 0 1.5u 1n 1n 1u 4u)
b_reset reset_on vss v=1.8-v(reset_b)
v_transfer transfer_n vss pulse(0 1.8 .6u .1n .1n .3u 1u)
b_transfer transfer_p vss v=1.8-v(transfer_n)
v_sample sample_on vss pulse(1.8 0 .5u .1n .1n .5u 1u)
b_sample sample_off vss v=1.8-v(sample_on)
v_reference reference_state vss .3
r_drain1 drain1 vdd 10k
r_drain2 drain2 vdd 10k
"""
    body = body.replace(".ends conv", signals + ".ends conv")
    model = project / "neutral.lib"
    model.write_text(".model NTEST nmos level=1 vto=.4 kp=100u\n.model PTEST pmos level=1 vto=-.4 kp=50u\n")
    netlist = bdir / "converter.sp"
    netlist.write_text(f'.include "{model}"\n' + body)
    template = bdir / "tb_converter.sp"
    original_body = text[text.index(".subckt"):text.index(".ends conv") + len(".ends conv")]
    template.write_text(text.replace(original_body, '.include "converter.sp"') + "\n")
    source.unlink()
    for name, value in (("spec", spec), ("topology", topology)):
        (bdir / (name + ".json")).write_text(json.dumps(value))
    settings = {"series_length": 64, "tone_bin": 9, "dc_offset_v": .7, "amplitude_v": .2,
                "reset_node": "xdut.reset_b", "threads": 1, "compress_capture": False, "capture_clocks": 8}
    point_settings = capture.phase_settings(settings, 0)
    output = root / "point-000"
    output.mkdir()
    settings_path = output / "settings.json"
    settings_path.write_text(json.dumps(point_settings))
    image = os.environ["VIBEIC_EDA_IMAGE"]
    command = ["python3", "-B", str(Path(capture.__file__)), str(project), "--block", "converter",
               "--settings", str(settings_path), "--out", str(output), "--container", "", "--image", image]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=60)
    (root / "producer_stdout.log").write_text(completed.stdout)
    (root / "producer_stderr.log").write_text(completed.stderr)
    assert (output / "result.json").is_file(), completed.stderr
    record = json.loads((output / "result.json").read_text())
    (root / "CONTROL_NATIVE_START.json").write_text(json.dumps({"argv": command,
        "returncode": completed.returncode, "result": str(output / "result.json"),
        "scope": "one neutral 8us transient; no ADC or series population"}, indent=2))
    return record, model, output, settings


def _identity(record):
    # On base this is the existing normal reader, so controls observe its
    # false acceptance rather than failing because a new helper is absent.
    reader = getattr(capture, "validate_execution_identity", capture.validate_point)
    return reader(record)


def test_actual_native_point_has_current_prelaunch_identity(native_point):
    record, _model, _out, _settings = native_point
    assert record["status"] == "PASS", record.get("detail", record.get("decoded"))
    assert _identity(record)[0] is True, _identity(record)
    assert capture.validate_point(record)[0] is True, capture.validate_point(record)


def test_readset_was_written_before_native_started(native_point):
    record, _model, out, _settings = native_point
    before = out / "execution_inputs.json"
    assert before.is_file()
    held = json.loads(before.read_text())
    running = json.loads((out / "running.json").read_text())
    assert held["prepared_at"] <= running["started_at"]
    assert held["argv"] == record["executions"][0]["argv"]
    assert held["tool"]["path"] in held["argv"]
    assert held["runtime"]["image"] == record["image"]
    assert any(role.startswith("startup:") for role in held["native_inputs"])
    assert any(role.startswith("source:") for role in held["native_inputs"])


@pytest.mark.parametrize("role", ["model", "deck", "tool"])
@pytest.mark.parametrize("mutation", ["missing", "changed"])
def test_missing_or_changed_consumed_authority_refuses(native_point, role, mutation, monkeypatch):
    original, model, _out, _settings = native_point
    record = copy.deepcopy(original)
    views = record["native_inputs"]
    key = next(k for k, v in views.items() if k.startswith("include:") and v["path"] == str(model)) if role == "model" else {
        "deck": "deck", "tool": "native_binary"}[role]
    # Base has no binary view. Changing the actual selected tool resolver still
    # demonstrates its successful reader never checks executable authority.
    if role == "tool" and mutation == "changed":
        import analog_native_sim as sim
        selected = sim._selected_ngspice_identity({"container": ""})
        monkeypatch.setattr(sim, "_selected_ngspice_identity", lambda _options: {**selected, "sha256": "0" * 64})
    elif mutation == "missing":
        views.pop(key, None)
    else:
        views[key]["sha256"] = "0" * 64
    observed = _identity(record)[0]
    assert observed is False


@pytest.mark.parametrize("field", ["argv", "image", "startup", "source", "receipt"])
def test_wrong_execution_authority_refuses(native_point, field):
    original, _model, _out, _settings = native_point
    record = copy.deepcopy(original)
    if field == "argv":
        record["executions"][0]["argv"] = ["ngspice", "-b", "/wrong/deck.sp"]
    elif field == "image":
        record["image"] = "unrelated-image"
    else:
        views = record["native_inputs"]
        if field == "receipt":
            views.pop("execution_receipt", None)
        else:
            for key in list(views):
                if key.startswith(field + ":"):
                    views.pop(key)
    assert _identity(record)[0] is False


@pytest.mark.parametrize("role", ["model", "deck"])
@pytest.mark.parametrize("mutation", ["missing", "changed"])
def test_changed_or_missing_actual_input_bytes_refuse(native_point, role, mutation):
    record, model, _out, _settings = native_point
    path = model if role == "model" else Path(record["native_inputs"]["deck"]["path"])
    original = path.read_bytes()
    try:
        if mutation == "missing":
            path.unlink()
        else:
            path.write_bytes(original + b"\n* changed after execution\n")
        assert _identity(record)[0] is False
    finally:
        path.write_bytes(original)


def test_current_point_reused_without_native_launch(native_point, monkeypatch):
    record, _model, out, common = native_point
    # Reuse the existing point in its real series directory. Only point0 is
    # selected; incomplete series remains NOT_MEASURED and launches nothing.
    setting = out.parent / "common.json"
    setting.write_text(json.dumps(common))
    point = out / "result.json"
    before = point.read_bytes()
    calls = []
    code = capture.series_main([record["project"], "--block", "converter", "--settings", str(setting),
        "--out", str(out.parent), "--container", "", "--image", record["image"], "--cpus", "1",
        "--workers", "1", "--limit-points", "1"], launch=lambda _args: calls.append(_args))
    assert calls == []
    assert code == 2
    assert point.read_bytes() == before


def test_changed_startup_preserves_actual_native_exit_and_log(native_point, monkeypatch, tmp_path):
    """Software subprocess seam; no additional native analysis is launched."""
    import analog_native_flow as flow
    record, _model, _out, _common = native_point
    init = tmp_path / ".spiceinit"
    init.write_text("* original startup\n")
    monkeypatch.setattr(flow, "_local_ngspice_startup", lambda *_a: (
        {"SPICE_USERINIT_DIR": str(tmp_path)}, {"path": str(init), "sha256": capture.bound.sha(init)}))
    log_text = "native process seam returned zero\n"
    class NativeSeam:
        pid = os.getpid()
        def __init__(self, _command, *, stdout, **_kwargs):
            stdout.write(log_text)
            init.write_text("* startup changed during execution\n")
        def wait(self):
            return 0
    monkeypatch.setattr(capture.subprocess, "Popen", NativeSeam)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps(record["settings"]))
    output = tmp_path / "point"
    code = capture.main([record["project"], "--block", "converter", "--settings", str(settings),
                         "--out", str(output), "--container", "", "--image", record["image"]])
    result = json.loads((output / "result.json").read_text())
    assert result["executions"][0]["returncode"] == 0
    assert (output / "ngspice.log").read_text() == log_text
    assert code == 2
    assert result["status"] == "NOT_MEASURED"


def _collector(native_point, monkeypatch, tmp_path, points):
    record, _model, _out, common = native_point
    project = Path(record["project"])
    setting = tmp_path / "common.json"
    setting.write_text(json.dumps(common))
    rows = []
    # Unit collector seam: exact native point references, one context, no
    # manifest preparation or native corner/phase generation.
    for index, value in enumerate(points):
        path = tmp_path / f"retained-{index}.json"
        path.write_text(json.dumps(value))
        rows.append(pvt._view(path))
    score = tmp_path / "score.json"
    score.write_text(json.dumps({"points": rows}))
    context = {"project": str(project), "score": str(score), "process": "neutral_tt", "temperature_c": 27,
               "settings": pvt._view(setting), "native_inputs": {k: v for k, v in record["native_inputs"].items()
                    if k in ("netlist", "testbench", "spec", "topology")}}
    monkeypatch.setattr(pvt, "_validate_manifest", lambda _manifest: [context])
    monkeypatch.setattr(capture, "series_main", lambda *_a, **_kw: pytest.fail("collection cannot launch"))
    return pvt.collect({"image": record["image"], "native_inputs": {"spec": record["native_inputs"]["spec"]}})


def test_pvt_collection_refuses_legacy_point_without_tool_authority(native_point, monkeypatch, tmp_path):
    record = copy.deepcopy(native_point[0])
    record["native_inputs"].pop("execution_receipt", None)
    # Keep a plausible passing cached score. It cannot supply native authority.
    monkeypatch.setattr(capture, "replay_score", lambda _p: {"status": "PASS", "measurements": {"enob": 99}, "target_bits": 14})
    result = _collector(native_point, monkeypatch, tmp_path, [record])
    assert result["status"] == "NOT_MEASURED"
    assert result["metrics"]["contexts"][0]["status"] == "NOT_MEASURED"


@pytest.mark.parametrize("missing_first", [True, False])
def test_native_failure_survives_mixed_missing_point_identity(native_point, monkeypatch, tmp_path, missing_first):
    record = copy.deepcopy(native_point[0])
    missing = copy.deepcopy(record)
    missing["native_inputs"].pop("execution_receipt", None)
    missing["native_inputs"].pop("deck")
    # Software failure injection uses the retained log path/hash contract.
    # It is a precedence control, not a second native execution.
    log = tmp_path / "native-failure.log"
    log.write_text("fatal error: neutral precedence control\n")
    record["executions"][0].update(returncode=1, log=str(log), log_sha256=capture.bound.sha(log))
    points = [missing, record] if missing_first else [record, missing]
    result = _collector(native_point, monkeypatch, tmp_path, points)
    assert result["status"] == "FAIL"
    assert result["metrics"]["contexts"][0]["status"] == "FAIL"


def test_observed_native_failure_is_retained_without_new_readset_credit(native_point, monkeypatch, tmp_path):
    record = copy.deepcopy(native_point[0])
    record["native_inputs"].pop("execution_receipt", None)
    log = tmp_path / "retained-failure.log"
    log.write_text("fatal error: retained native error\n")
    record["executions"][0].update(returncode=1, log=str(log), log_sha256=capture.bound.sha(log))
    result = _collector(native_point, monkeypatch, tmp_path, [record])
    assert result["status"] == "FAIL"
