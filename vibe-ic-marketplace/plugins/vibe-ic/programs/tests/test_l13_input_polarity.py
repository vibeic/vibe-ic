"""Source-backed L13 polarity through the ordinary emitter and overlay."""
import json
from pathlib import Path

import pytest

import phase1_doc_one_shot_runner as p1
import spi_protocol_synth as spi


def _emit(tmp_path, text):
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True)
    (docs / "calibration.md").write_text(text, encoding="utf-8")
    p1.gen_l13_lab_calibration(tmp_path, {"calibration.md": text})
    gd = tmp_path / "phase1" / "generated_docs"
    spi.apply_spi_synth(gd, False, None)
    return json.loads((gd / "L13_LAB_CALIBRATION.json").read_text())


def test_original_negative_calibration_stays_provenance(tmp_path):
    text = (Path(__file__).parent / "fixtures" / "subservient_input_docs" /
            "L6_calibration.md").read_text(encoding="utf-8")
    doc = _emit(tmp_path, text)
    assert doc["calibration_steps"] == doc["test_cases"] == doc["trim_loop"] == []
    assert doc["calibration_targets"] == []
    for key in ("no_lab_calibration_in_input", "no_calibration_steps_in_input",
                "no_l13_test_cases_in_input"):
        assert doc[key] is True
    assert doc["lab_calibration_present"] is False
    assert doc["source_documents"] == ["input/docs/calibration.md"]
    evidence = doc["extraction_evidence"]["input/docs/calibration.md"]
    assert any("無 trimming" in e["literal"] for e in evidence)
    assert any("不需產生 calibration controller" in e["literal"] for e in evidence)
    assert "BusClock" not in doc.get("notes", "")


@pytest.mark.parametrize("prefix", ["", "No OTP calibration is required; "])
def test_affirmative_procedure_survives_independent_denial(tmp_path, prefix):
    actions = ["1. Measure oscillator frequency.",
               "2. Adjust TRIM_OSC until frequency is 10 MHz."]
    doc = _emit(tmp_path, "# Calibration / Lab Procedures\n" + prefix +
                "\n".join(actions))
    assert [step["action"] for step in doc["calibration_steps"]] == actions
    assert doc["test_cases"] == doc["trim_loop"] == doc["calibration_steps"]
    assert {target["name"] for target in doc["calibration_targets"]} == {"TRIM_OSC"}
    assert doc["no_lab_calibration_in_input"] is False
    assert doc["no_calibration_steps_in_input"] is False
    assert doc["lab_calibration_present"] is True
    assert "BusClock" not in doc.get("notes", "")


def test_negated_target_and_postposed_na_are_not_procedures(tmp_path):
    doc = _emit(tmp_path, "# Calibration\nCalibration is not required.\n"
                "1. No TRIM_OSC or measurement procedure.\nCalibration: N/A\n")
    assert doc["calibration_steps"] == doc["calibration_targets"] == []
    assert doc["no_lab_calibration_in_input"] is True


def test_declared_name_vendor_row_is_not_reported_absent(tmp_path):
    doc = _emit(tmp_path, "Rigol DM3068 | Keysight\n")
    assert doc["lab_equipment"] == [{
        "name": "Rigol DM3068", "vendor": "Keysight",
        "purpose": "lab equipment (extracted)",
        "evidence": "input/docs/calibration.md",
    }]
    assert doc["no_lab_equipment_in_input"] is False
    # Equipment alone does not assert that calibration is present.
    assert doc["no_lab_calibration_in_input"] is True
    assert doc["lab_calibration_present"] is False


@pytest.mark.parametrize("clause", [
    "TRIM_OSC isn't required.\n",
    "TRIM_OSC N/A.\n",
    "TRIM_OSC is N/A.\n",
    "TRIM_OSC are N/A.\n",
    "TRIM_OSC: N/A.\n",
])
def test_postposed_negative_forms_are_not_targets(tmp_path, clause):
    doc = _emit(tmp_path, clause)
    assert doc["calibration_targets"] == []
    assert doc["no_lab_calibration_in_input"] is True


@pytest.mark.parametrize("is_spi", [False, True])
def test_generic_overlay_does_not_invent_calibration_or_baud_implementation(
        tmp_path, is_spi):
    path = tmp_path / "L13_LAB_CALIBRATION.json"
    path.write_text(json.dumps({"calibration_steps": [{"action": "Measure frequency"}],
                                "notes": "Input calls for a frequency measurement."}))
    spi.apply_spi_synth(tmp_path, is_spi, None)
    doc = json.loads(path.read_text())
    assert doc["lab_calibration_present"] is True
    assert doc["notes"] == "Input calls for a frequency measurement."


def _operator_answers(project, answers):
    from _submission_template import DESIGN_ANSWERS_REL

    path = project / DESIGN_ANSWERS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    provenance = {key: {"answered_by": "owner", "citation": "neutral lab operator answer"}
                  for key in answers}
    path.write_text(json.dumps({"answers": answers, "answer_provenance": provenance}))
    return provenance


@pytest.mark.parametrize("individual_params", [False, True])
def test_answered_adc_criterion_reaches_consumer(tmp_path, individual_params):
    import l13_bringup_contract_check as gate
    import yaml
    from _hostpaths import require_repo

    bank = yaml.safe_load(require_repo("vibe-ic-marketplace", "plugins", "vibe-ic",
                                      "agents", "qbank", "any-ic_L13.yaml").read_text())
    paths = {key: f"{bank['layer']}.{key}" for key in bank["qbank"]}
    answers = {paths["criterion"]: "monotonic_adc_sweep", paths["tester"]: "neutral bench rig"}
    params = {"min_samples": 7}
    if individual_params:
        answers[paths["criterion_params.min_samples"]] = 7
    else:
        answers["L13.criterion_params"] = params
    provenance = _operator_answers(tmp_path, answers)
    doc = _emit(tmp_path, "1. Sweep the input and record output samples.\n")
    assert doc["lab_calibration_present"] is True
    result = gate.check(doc, phase=1)
    assert [f for f in result["findings"] if f["severity"] == "FAIL"] == []
    assert doc["criterion"] == "monotonic_adc_sweep"
    assert doc["criterion_params"] == params
    assert doc["tester"] == "neutral bench rig"
    assert doc["answer_provenance"] == provenance
    assert not doc.get("known_pass_bitstream")
    assert not doc.get("known_pass_transcript")
    assert gate.main([str(tmp_path)]) == 0


def test_unknown_answered_criterion_is_refused_before_publication(tmp_path):
    _operator_answers(tmp_path, {"L13.criterion": "unregistered_neutral_kind"})
    with pytest.raises(ValueError, match="L13_CRITERION_UNKNOWN"):
        p1.gen_l13_lab_calibration(tmp_path, {})
    assert not (tmp_path / "phase1/generated_docs/L13_LAB_CALIBRATION.json").exists()


@pytest.mark.parametrize("answers", [{}, {"L13.criterion": "NOT_DETERMINED"},
                                   {"L13.criterion": ""}])
def test_unanswered_contract_stays_unresolved(tmp_path, answers):
    import l13_bringup_contract_check as gate

    _operator_answers(tmp_path, answers)
    doc = _emit(tmp_path, "1. Sweep the input and record output samples.\n")
    assert not {"criterion", "criterion_params", "tester", "answer_provenance"} & doc.keys()
    assert doc["lab_calibration_present"] is True
    result = gate.check(doc, phase=1)
    assert "l13_contract_complete" in {f["rule"] for f in result["findings"]}


def test_criterion_in_prose_cannot_answer_contract(tmp_path):
    doc = _emit(tmp_path, "L13.criterion: monotonic_adc_sweep\n"
                "L13.criterion_params: {min_samples: 7}\nL13.tester: neutral bench rig\n")
    assert not {"criterion", "criterion_params", "tester"} & doc.keys()


def test_producer_uses_live_consumer_registry(tmp_path, monkeypatch):
    import hardware_pass_attestation_check as consumer

    monkeypatch.setitem(consumer._CRITERIA, "neutral_future_kind", lambda tx, params: (True, "ok"))
    _operator_answers(tmp_path, {"L13.criterion": "neutral_future_kind"})
    doc = _emit(tmp_path, "")
    assert doc["criterion"] == "neutral_future_kind"
