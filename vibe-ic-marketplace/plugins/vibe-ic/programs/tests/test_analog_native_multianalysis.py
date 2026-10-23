"""Compound measurement parser/producer controls; no native qualification claim."""
import json
from pathlib import Path

import pytest

import analog_bound_measurements as bound
import analog_native_physical as physical


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


@pytest.fixture
def project(tmp_path):
    project = tmp_path / "project"
    directory = project / "phase3/analog/cell"
    put(directory / "cell.sp", ".subckt cell a b ref vss\nR0 b vss 100\n.ends cell\n")
    put(directory / "spec.json", {"specs": [{"name": "vout", "min": 1.1, "max": 1.3},
        {"name": "iq", "max": 50}, {"name": "dropout", "max": 0.5}, {"name": "psrr", "min": 40}]})
    return project


def studies(project, *, accepted_psrr=False):
    directory = project / "phase3/analog/cell"
    if accepted_psrr:
        source = json.loads((directory / "spec.json").read_text())
        source["specs"][-1]["frequency_hz"] = {"min": 100, "max": 1000}
        put(directory / "spec.json", source)
    declarations = [
        ({"kind": "OP", "temperature_c": 27}, {"vout": {"analysis": "OP", "expression": "v(b)"},
          "iq": {"analysis": "OP", "expression": "(-i(v_supply)-0.0005)*1e6"}}, {"vout": 1.2, "iq": 30}),
        ({"kind": "DC", "source": "v_supply", "start": 1.8, "stop": 1.6, "step": -0.01, "temperature_c": 125},
         {"vout_min_supply": {"analysis": "DC", "expression": "v(b)", "at": "last", "spec_key": "vout"},
          "iq_min_supply": {"analysis": "DC", "expression": "(-i(v_supply)-0.001)*1e6", "at": "last", "spec_key": "iq"},
          "dropout": {"analysis": "DC", "expression": "v(a)-v(b)", "at": "last",
                      "interpretation": "upper_bound_when_regulated", "regulation_measurement": "vout_min_supply"}},
         {"vout_min_supply": 1.18, "iq_min_supply": 28, "dropout": 0.42}),
        ({"kind": "AC", "points": 10, "start_hz": 100, "stop_hz": 1000, "temperature_c": 27},
         {"psrr_point": {"analysis": "AC", "expression": "vecmin(-vdb(b))" if accepted_psrr else "-vdb(b)", "frequency_hz": "last",
                         **({"spec_key": "psrr"} if accepted_psrr else {})}}, {"psrr_point": 44})]
    rows = []
    for index, (analysis, measurements, values) in enumerate(declarations):
        output = project / "post" / str(index)
        template = put(output / "template.sp", '* neutral compound fixture\n.include "' + str(directory / "cell.sp") +
            '"\nv_supply a 0 1.8' + (' ac 1' if analysis["kind"] == "AC" else '') +
            '\nv_ref ref 0 0.8\ni_load b 0 ' + ('0.001' if analysis["kind"] == "DC" else '0.0005') +
            '\nxdut a b ref 0 cell\n.options trtol=1\n.end\n')
        bindings = {"analysis": analysis, "measurements": measurements, "execution": {"threads": 1}}
        path = put(output / "bindings.json", bindings)
        def run(program, argv, **kwargs):
            log = put(output / "native.log", f"Doing analysis at TEMP = {analysis['temperature_c']:.6f} and TNOM = 27\n" +
                      "\n".join(f"MEAS {key}={value}" for key, value in values.items()) + "\n")
            return {"returncode": 0, "log": str(log), "log_sha256": physical._sha(log)}
        record = bound.run_measurements(project, directory / "cell.sp", template, bindings, output / "native", run)
        assert record["status"] == "PASS"
        record["native_inputs"]["bindings"] = {"path": str(path), "sha256": physical._sha(path)}
        result = put(output / "result.json", record)
        rows.append({"index": index, "post_netlist": str(directory / "cell.sp"),
            "post_netlist_sha256": physical._sha(directory / "cell.sp"),
            "native_measurement_study": {"result": str(result), "sha256": physical._sha(result)}})
    return rows


def population(project, sequence, *, wrong_temp=False, bad_output=False):
    study = project / "population"
    for seed in (1, 2):
        values = [{"vout": 0.9 if bad_output and seed == 1 else 1.19 + seed * .001, "iq": 30 + seed},
                  {"vout_min_supply": 1.17 + seed * .001, "iq_min_supply": 28 + seed, "dropout": .43 - seed * .001},
                  {"psrr_point": 43 + seed}]
        lines = []
        for item, measured in zip(sequence["studies"], values):
            index = item["index"]
            temperature = 27 if wrong_temp and index == 1 else item["temperature_c"]
            lines += [f"VIBEIC_STUDY_BEGIN {index}", f"Doing analysis at TEMP = {temperature:.6f} and TNOM = 27"]
            lines += [f"MEAS {item['labels'][key]}={value}" for key, value in measured.items()]
            lines.append(f"VIBEIC_STUDY_END {index}")
        put(study / f"logs/mc_{seed:04d}.log", "\n".join(lines) + "\n")
    return study


def test_combined_mc_uses_one_dut_and_explicit_conditions_without_reset(project):
    text, sequence = physical._compose_measurement_sequence(project, studies(project))
    assert "reset" not in text.lower()
    assert text.count(".include ") == 1
    assert "alter @i_load[dc] = 0.001" in text
    assert "alter @v_supply[acmag] = 1" in text
    assert "set temp=125" in text
    assert "dc v_supply 1.8 1.6000000000000001 -0.01" in text
    assert 'MEAS study0_vout=' in text and 'MEAS study1_vout_min_supply=' in text
    assert len(sequence["studies"]) == 3


def test_public_population_preserves_actual_pre_records_and_dependency_views(project, monkeypatch):
    import analog_mc_yield_run as mc
    rows = studies(project)
    references = [{"path": row["native_measurement_study"]["result"],
                   "sha256": row["native_measurement_study"]["sha256"]} for row in rows]
    _text, sequence = physical.compose_native_measurement_sequence(project, references)
    assert all("source_result" in row and "post_result" not in row for row in sequence["studies"])
    destination = population(project, sequence)
    monkeypatch.setattr(mc, "run_block", lambda *args, **kwargs: {"mc_runs": 2, "mc_log_dir": "logs"})
    record = physical.run_native_measurement_population(project, "cell", references, destination,
        "container", "process", 2, stage="PRE")
    assert record["stage"] == "PRE" and record["mc_runs"] == 2
    assert record["verdict"] == "NOT_MEASURED"  # PSRR domain remains absent.
    assert record["spec_yield"]["vout"]["passed"] == 2
    assert "record:0:netlist" in record["native_inputs"]
    assert "record:0:log:0" in record["native_inputs"]
    assert str(destination) in record["outputs"]
    assert physical._current_native_views(record["native_inputs"])


def test_pre_population_cannot_substitute_postlayout_dut(project, monkeypatch):
    outside = put(project / "extracted/cell.sp", "* extracted circuit\n")
    result = put(project / "post-result.json", {"native_inputs": {
        "netlist": {"path": str(outside), "sha256": physical._sha(outside)}}})
    monkeypatch.setattr(physical, "compose_native_measurement_sequence", lambda *args: ("* deck\n", {}))
    record = physical.run_native_measurement_population(project, "cell",
        [{"path": str(result), "sha256": physical._sha(result)}], project / "new-population",
        "container", "process", 2, stage="PRE")
    assert record["verdict"] == "NOT_MEASURED" and record["mc_runs"] == 0
    assert "PEX records cannot substitute" in record["reason"]
    assert not (project / "new-population").exists()


def test_current_pre_native_failure_keeps_stage_and_failure(project):
    row = studies(project)[0]
    path = Path(row["native_measurement_study"]["result"])
    state = json.loads(path.read_text())
    state["status"] = "FAIL"
    put(path, state)
    record = physical.run_native_measurement_population(project, "cell",
        [{"path": str(path), "sha256": physical._sha(path)}], project / "new-population",
        "container", "process", 2, stage="PRE")
    assert record["stage"] == "PRE" and record["verdict"] == "FAIL"
    assert record["mc_runs"] == 0


def test_post_native_failure_cannot_be_attributed_to_pre(project, monkeypatch):
    path = put(project / "post-result.json", {"status": "FAIL", "native_inputs": {
        "netlist": {"path": str(project / "extracted/cell.sp"), "sha256": "not-the-source"}}})
    monkeypatch.setattr(physical, "compose_native_measurement_sequence",
        lambda *args: (_ for _ in ()).throw(physical.NativeStudyFailed("POST native failure")))
    record = physical.run_native_measurement_population(project, "cell",
        [{"path": str(path), "sha256": physical._sha(path)}], project / "new-population",
        "container", "process", 2, stage="PRE")
    assert record["stage"] == "PRE" and record["verdict"] == "NOT_MEASURED"
    assert "PEX records cannot substitute" in record["reason"]


def test_compound_population_preserves_real_context_values_and_missing_band(project):
    _text, sequence = physical._compose_measurement_sequence(project, studies(project))
    study = population(project, sequence)
    result = physical._grade_measurement_population(project, "cell", study,
        {"mc_log_dir": "logs", "mc_runs": 2}, sequence, 2)
    assert result["verdict"] == "NOT_MEASURED"
    assert result["mc_source_coverage"]["missing"] == ["psrr"]
    assert all(result["spec_yield"][key]["runs_scored"] == 2 for key in ("vout", "iq", "dropout"))
    assert result["samples"][0]["studies"]["0"]["measurements"]["vout"] == pytest.approx(1.191)
    assert result["samples"][0]["studies"]["1"]["measurements"]["vout_min_supply"] == pytest.approx(1.171)


def test_source_selected_psrr_completes_compound_population(project):
    _text, sequence = physical._compose_measurement_sequence(project, studies(project, accepted_psrr=True))
    study = population(project, sequence)
    result = physical._grade_measurement_population(project, "cell", study,
        {"mc_log_dir": "logs", "mc_runs": 2}, sequence, 2)
    assert result["verdict"] == "PASS" and result["mc_yield_pct"] == 100


def test_compound_temperature_mismatch_removes_only_affected_output_coverage(project):
    _text, sequence = physical._compose_measurement_sequence(project, studies(project))
    study = population(project, sequence, wrong_temp=True)
    result = physical._grade_measurement_population(project, "cell", study,
        {"mc_log_dir": "logs", "mc_runs": 2}, sequence, 2)
    assert result["verdict"] == "NOT_MEASURED"
    assert result["spec_yield"]["dropout"]["runs_scored"] == 0
    assert result["samples"][0]["studies"]["1"]["temperature_matched"] is False


def test_actual_source_violation_wins_over_unmeasured_psrr(project):
    _text, sequence = physical._compose_measurement_sequence(project, studies(project))
    study = population(project, sequence, bad_output=True)
    result = physical._grade_measurement_population(project, "cell", study,
        {"mc_log_dir": "logs", "mc_runs": 2}, sequence, 2)
    assert result["verdict"] == "FAIL"
    assert result["spec_yield"]["vout"]["passed"] == 1


def test_dropout_bound_needs_same_point_successful_regulation(tmp_path):
    limits = {"vout": {"min": 1.1, "max": 1.3}, "dropout": {"max": .5}}
    binding = {"measurements": {"vout": {"analysis": "DC", "at": "first"},
        "dropout": {"analysis": "DC", "at": "last", "interpretation": "upper_bound_when_regulated",
                    "regulation_measurement": "vout"}}}
    source = put(tmp_path / "spec.json", {"specs": [{"name": key, **value} for key, value in limits.items()]})
    observed, missing = physical._output_observations(source, binding, {"vout": 1.2, "dropout": .4}, limits)
    assert "dropout" not in observed and missing
    binding["measurements"]["vout"]["at"] = "last"
    observed, missing = physical._output_observations(source, binding, {"vout": .9, "dropout": .4}, limits)
    assert "dropout" not in observed and missing


def test_changed_post_receipt_refuses_compound_execution(project):
    selected = studies(project)
    path = Path(selected[0]["native_measurement_study"]["result"])
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ValueError, match="changed"):
        physical._compose_measurement_sequence(project, selected)
