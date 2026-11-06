"""Self-authored native-format inputs qualify parser behavior, not ngspice."""
import copy
import hashlib
import json

import pytest

import _mixed_signal_native as consumer
import _mixed_signal_receiver_noise as noise
from mixed_signal_m3_run import Refusal


def _source_case(project):
    source = project / "input/models/receiver.sp"
    source.parent.mkdir(parents=True)
    source.write_text("* SOURCE_ONLY neutral model\n.subckt detector drive sense\nRload drive sense 1000\n.ends detector\n")
    dependency = source.with_name("dependency.sp")
    dependency.write_text(".model source_control_diode D(IS=1e-14)\n")
    spec = {"schema": noise.SCHEMA, "id": "noise_case", "top": "neutral_top",
            "scope": "declared_model_component", "analysis": "ngspice_noise",
            "model": source.relative_to(project).as_posix(),
            "subckt": "detector",
            "ports": ["drive", "sense"],
            "dependencies": [dependency.relative_to(project).as_posix()],
            "temperature_c": 25, "dc_drive_v": 0.5,
            "frequency_start_hz": 100, "frequency_stop_hz": 1000, "points_per_decade": 20,
            "criteria": [{"metric": noise.METRIC, "units": noise.UNITS, "max": 4e-8}]}
    data = {"schema": consumer.INPUT_SCHEMA, "top": spec["top"], "scope": spec["scope"],
            "digital": {"netlist": "input/neutral.v"},
            "analog": {"netlist": spec["model"], "drive_low_v": 0, "drive_high_v": 1},
            "si": {"receiver_noise": spec}}
    contract = project / consumer.CONTRACT
    contract.parent.mkdir(parents=True)
    contract.write_text(json.dumps(data))
    return data, spec


def _observations(work, spec, token="source_run", log_name="noise.log"):
    work.mkdir(parents=True, exist_ok=True)
    # Independent white voltage-density observation: RMS = sqrt(900)*1e-9 = 3e-8 V.
    rows = [(100 * 10 ** (i / 20), 1e-9) for i in range(21)]
    (work / "spectrum.txt").write_text("frequency onoise_spectrum\n" +
        "\n".join(f"{frequency:.17g} {density:.17g}" for frequency, density in rows) + "\n")
    (work / "integrated.txt").write_text("onoise_total onoise_total\n3e-8 3e-8\n")
    (work / log_name).write_text(
        f'M3NOISE_RUN {token} {spec["id"]}\n'
        'onoise_total = 3e-8\n' + f'M3NOISE_DONE {token} {spec["id"]}\n')


def test_public_models_hashes_and_paths_reach_existing_native_input_consumer(tmp_path):
    data, spec = _source_case(tmp_path)
    assert noise.declaration(tmp_path, data) == spec
    assert noise.input_paths(tmp_path, data) == {spec["model"], *spec["dependencies"]}
    assert consumer.input_paths(tmp_path, data["top"]) == {
        consumer.CONTRACT, "input/neutral.v", spec["model"], *spec["dependencies"]}
    deck = noise.deck(tmp_path, spec, "source_run")
    assert f'Xreceiver drive sense {spec["subckt"]}' in deck
    assert "noise v(sense) Vdrive dec 20 100 1000" in deck
    assert f'M3NOISE_RUN source_run noise_case' in deck
    assert deck.index("dependency.sp") < deck.index("receiver.sp")
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize("change,rule", [('hidden_control', 'UNSUPPORTED_NOISE_MODEL'), ('wrong_top', 'WRONG_DESIGN'), ('unbounded_grid', 'UNBOUNDED_NOISE_ANALYSIS'), ('fractional_grid', 'UNBOUNDED_NOISE_ANALYSIS'), ('missing_limit', 'UNBOUNDED_NOISE_CRITERIA'), ('negative_limit', 'UNBOUNDED_NOISE_CRITERIA')])
def test_noise_declaration_refuses_stale_hidden_or_unbounded_inputs(tmp_path, change, rule):
    data, spec = _source_case(tmp_path)
    if change == "hidden_control":
        path = tmp_path / spec["model"]
        path.write_text(path.read_text() + ".control\nop\n.endc\n")
    elif change == "wrong_top":
        spec["top"] = "other_top"
    elif change == "unbounded_grid":
        spec["points_per_decade"] = True
    elif change == "fractional_grid":
        spec["frequency_stop_hz"] = 999
    elif change == "missing_limit":
        del spec["criteria"][0]["max"]
    elif change == "negative_limit":
        spec["criteria"][0]["max"] = -1
    else:
        spec["dependencies"].append(spec["model"])
    with pytest.raises(Refusal) as refused:
        noise.declaration(tmp_path, data)
    assert refused.value.rule == rule
    assert not (tmp_path / "reports").exists()


def test_noise_derivation_reports_value_and_stricter_criteria_retain_failure(tmp_path):
    _, spec = _source_case(tmp_path)
    work = tmp_path / "observations"
    _observations(work, spec)
    got = noise.derive(tmp_path, spec, work, "source_run")
    assert (got["sample_count"], got["frequency_band_hz"], got["scope"]) == (
        21, [100, 1000], "declared_model_component")
    assert got["metrics"][noise.METRIC] == {"measured": 3e-8, "units": "V_RMS"}
    assert got["verdict"] == "PASS"
    tighter = copy.deepcopy(spec)
    tighter["criteria"][0]["max"] = 2e-8
    failed = noise.derive(tmp_path, tighter, work, "source_run")
    assert failed["verdict"] == "FAIL"
    assert failed["criteria"][0]["measured"] == got["criteria"][0]["measured"]


@pytest.mark.parametrize("change,rule", [
    ("run_token", "MISSING_NOISE_OBSERVATION"), ("incomplete_grid", "MISSING_NOISE_OBSERVATION"),
    ("frequency_grid", "FAILED_MEASUREMENT"), ("negative_density", "FAILED_MEASUREMENT"),
    ("log_scalar", "CONTRADICTS_NATIVE_OUTPUT"), ("spectrum_scalar", "CONTRADICTS_NATIVE_OUTPUT"),
])
def test_noise_derivation_rejects_incomplete_or_contradictory_observation_formats(tmp_path, change, rule):
    _, spec = _source_case(tmp_path)
    work = tmp_path / "observations"
    _observations(work, spec)
    if change == "run_token":
        (work / "noise.log").write_text((work / "noise.log").read_text().replace("source_run", "older_run"))
    elif change == "log_scalar":
        (work / "noise.log").write_text((work / "noise.log").read_text().replace("3e-8", "4e-8"))
    else:
        path = work / "spectrum.txt"
        lines = path.read_text().splitlines()
        if change == "incomplete_grid":
            lines.pop()
        elif change == "frequency_grid":
            lines[1] = "101 1e-9"
        elif change == "negative_density":
            lines[1] = "100 -1e-9"
        else:
            lines = [lines[0], *(line.split()[0] + " 2e-9" for line in lines[1:])]
        path.write_text("\n".join(lines) + "\n")
    with pytest.raises(Refusal) as refused:
        noise.derive(tmp_path, spec, work, "source_run")
    assert refused.value.rule == rule


def test_noise_verifier_requires_exact_execution_and_current_instrument(tmp_path):
    data, spec = _source_case(tmp_path)
    root = tmp_path / "run"
    work = root / "si/receiver_noise"
    _observations(work, spec)
    (work / "noise.sp").write_text(noise.deck(tmp_path, spec, "source_run"))
    (work / "noise.rss").write_text("2048\n")
    record = {"run_id": "source_run"}
    assert noise.verify(tmp_path, data, root, record)["metrics"][noise.METRIC]["measured"] == 3e-8
    (work / "noise.sp").write_text((work / "noise.sp").read_text() + "* changed\n")
    with pytest.raises(Refusal) as refused:
        noise.verify(tmp_path, data, root, record)
    assert refused.value.rule == "CONTRADICTS_NATIVE_OUTPUT"
