import json

import pytest

import flow109_metric_acceptance as metrics
import phase1_expert_parse_track as track


def raw_project(tmp_path, text):
    folder = tmp_path / "phase1/generated_docs"
    folder.mkdir(parents=True)
    (folder / "L22_VERIFICATION_PLAN.json").write_text(text)
    return tmp_path


def expectation(token, path="/quantity/target"):
    return {"id": "quantity", "layer": "L22_VERIFICATION_PLAN",
            "field_path": path, "expected_tokens": [token]}


def assert_both_readers(case, item, expected):
    result = track.converge_ai_expectation(case, item)
    assert result["usable"] is True
    assert result["met"] is expected, result
    json.dumps(result)
    actual, unresolved, unrouted = metrics._d0102_compare(
        case, {"expectations": [item]}, {})
    assert bool(actual) is expected, actual
    assert unresolved == [] and unrouted == []


@pytest.mark.parametrize("key, token, expected", [
    ("frequency_mHz", "1 MHz", False),
    ("frequency_mHz", "1 mHz", True),
    ("frequency_mHz", "0.001 Hz", True),
    ("frequency_MHz", "1 MHz", True),
    ("frequency_mhz", "1 MHz", True),
    ("voltage_MV", "1 mV", False),
    ("voltage_MV", "1 MV", True),
    ("voltage_mV", "1 mV", True),
    ("voltage_mv", "1 mV", True),
])
def test_field_units_preserve_si_prefix_case(tmp_path, key, token, expected):
    case = raw_project(tmp_path, json.dumps({key: 1}))
    assert_both_readers(case, expectation(token, f"/{key}"), expected)


@pytest.mark.parametrize("unit, token, expected", [
    ("°V", "1 V", False),
    ("V°", "1 V", False),
    ("m°V", "1 mV", False),
    ("°°C", "1 °C", False),
    ("°C", "1 °C", True),
    ("℃", "1 °C", True),
    ("°F", "1 F", False),
    ("°F", "1 °F", True),
    ("F", "1 F", True),
])
def test_degree_signs_are_temperature_units_only(tmp_path, unit, token, expected):
    case = raw_project(tmp_path, json.dumps({"quantity": {"target": 1, "unit": unit}}))
    assert_both_readers(case, expectation(token), expected)


@pytest.mark.parametrize("unit, token, expected", [
    ("V", "1 V", False),
    ("V", "1000.0000000000001 mV", True),
    ("—", "1", False),
    ("—", "1.0000000000000001", True),
])
@pytest.mark.parametrize("path", ["/quantity", "/quantity/target", "quantity.target"])
def test_json_decimal_precision_is_retained_locally(tmp_path, unit, token, expected, path):
    text = '{"quantity":{"target":1.0000000000000001,"unit":' + json.dumps(unit) + '}}'
    case = raw_project(tmp_path, text)
    assert_both_readers(case, expectation(token, path), expected)


@pytest.mark.parametrize("token, expected", [("1 V", False),
                                           ("1000.0000000000001 mV", True)])
def test_ownership_and_carriage_keep_json_decimal_precision(tmp_path, token, expected):
    case = raw_project(tmp_path, '{"quantity":{"target":1.0000000000000001,"unit":"V"}}')
    folder = case / "phase1/generated_docs"
    for stem in ("L5_ADI_SPEC", "L19_CONSTRAINTS_PDK"):
        (folder / f"{stem}.json").write_text('{}')
    answer = track.owning_layers_answer(case, [token])
    assert bool(answer["layers"]) is expected, answer
    carriage = track.token_carriage(case, [token])
    assert (carriage["verdict"] == track.CARRIAGE_NAMED_FIELD) is expected, carriage


@pytest.mark.parametrize("relative", ["input/request.json", "steps/D1/outputs.json",
                                      "reports/audit/ai_judgements/D1.json"])
def test_comparator_precision_does_not_change_other_d0102_json_reads(tmp_path, relative):
    case = raw_project(tmp_path, '{}')
    source = case / relative
    source.parent.mkdir(parents=True)
    source.write_text('{"target":1.0000000000000001}')
    observed = metrics._d0102_read(case, relative, {})
    assert type(observed["target"]) is float
    assert observed["target"] == 1.0

