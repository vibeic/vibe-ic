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
    json.dumps(answer)
    assert bool(answer["layers"]) is expected, answer
    carriage = track.token_carriage(case, [token])
    json.dumps(carriage)
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


def test_unrepresentable_json_decimal_is_refused_without_aborting(tmp_path):
    case = raw_project(tmp_path, '{"quantity":{"target":1e9999999999999999999,"unit":"V"}}')
    item = expectation("1 V")
    assert track.converge_ai_expectation(case, item)["met"] is False
    assert track.owning_layers_answer(case, ["1 V"])["layers"] == []
    assert track.token_carriage(case, ["1 V"])["verdict"] == track.CARRIAGE_NOWHERE
    actual, _, _ = metrics._d0102_compare(case, {"expectations": [item]}, {})
    assert actual == []


@pytest.mark.parametrize("key, unit", [("frequency_mHZ", "MHz"), ("voltage_Mv", "V")])
@pytest.mark.parametrize("outer", [False, True])
@pytest.mark.parametrize("value", [1, "1"])
def test_invalid_suffix_never_borrows_outer_or_dimensionless_unit(tmp_path, key, unit, outer, value):
    blob = {key: value, **({"unit": unit} if outer else {})}
    case = raw_project(tmp_path, json.dumps(blob))
    for token in ("1", f"1 {unit}"):
        assert_both_readers(case, expectation(token, f"/{key}"), False)


@pytest.mark.parametrize("key, unit", [("frequency_mHZ", "MHz"), ("voltage_Mv", "V")])
@pytest.mark.parametrize("outer", [False, True])
@pytest.mark.parametrize("shape", ["inline", "record", "child_suffix"])
@pytest.mark.parametrize("selector", ["pointer", "dotted"])
def test_invalid_suffix_stays_invalid_through_its_descendants(tmp_path, key, unit, outer, shape, selector):
    value = {"inline": f"1 {unit}", "record": {"target": 1, "unit": unit},
             "child_suffix": {"value_mV": 1000}}[shape]
    token = "1 V" if shape == "child_suffix" else f"1 {unit}"
    case = raw_project(tmp_path, json.dumps({key: value, **({"unit": unit} if outer else {})}))
    path = f"/{key}" if selector == "pointer" else key
    if shape != "inline":
        leaf = "target" if shape == "record" else "value_mV"
        path += ("/" if selector == "pointer" else ".") + leaf
    assert_both_readers(case, expectation(token, path), False)


@pytest.mark.parametrize("outer", [False, True])
def test_valid_suffix_still_overrides_its_outer_unit(tmp_path, outer):
    case = raw_project(tmp_path, json.dumps({"voltage_mV": 1, **({"unit": "V"} if outer else {})}))
    assert_both_readers(case, expectation("1 mV", "/voltage_mV"), True)
    assert_both_readers(case, expectation("1 V", "/voltage_mV"), False)


def test_ordinary_key_without_unit_suffix_still_inherits_record_unit(tmp_path):
    case = raw_project(tmp_path, '{"unit":"V","quantity":{"target":1}}')
    assert_both_readers(case, expectation("1 V"), True)
    assert_both_readers(case, expectation("1"), False)


def test_invalid_suffix_does_not_change_unknown_record_inline_precedence(tmp_path):
    case = raw_project(tmp_path, '{"quantity":{"unit":"unrecognized","target":"1 V"}}')
    assert_both_readers(case, expectation("1 V"), True)


@pytest.mark.parametrize("key, unit", [("frequency_mHZ", "MHz"), ("voltage_Mv", "V")])
@pytest.mark.parametrize("outer", [False, True])
@pytest.mark.parametrize("inline", [False, True])
def test_invalid_suffix_cannot_supply_ownership_or_carriage(tmp_path, key, unit, outer, inline):
    value = f"1 {unit}" if inline else 1
    token = f"1 {unit}" if inline or outer else "1"
    case = raw_project(tmp_path, json.dumps({key: value, **({"unit": unit} if outer else {})}))
    for stem in ("L5_ADI_SPEC", "L19_CONSTRAINTS_PDK"):
        (case / "phase1/generated_docs" / f"{stem}.json").write_text('{}')
    assert track.owning_layers_answer(case, [token])["layers"] == []
    assert track.token_carriage(case, [token])["verdict"] == track.CARRIAGE_NOWHERE
