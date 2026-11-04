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
    assert result["usable"] is True, result
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


def test_bare_hex_words_keep_literal_value_and_word_boundaries(tmp_path):
    words = ["8f01cfea", "248d6a61", "9914fb92", "123456db", "123456ff"]
    blob = {"quantity": {"target": " ".join(words + ["9f01cfeaa"])},
            "physical": {"target": 12345678, "unit": "F"}}
    case = raw_project(tmp_path, json.dumps(blob))
    for token in words:
        assert_both_readers(case, expectation(token), True)
        assert track.token_paths(blob, token) == ["quantity.target"]
    for token in ("8f01cfeb", "8f01cfea0", "08f01cfea", "9f01cfea"):
        assert_both_readers(case, expectation(token), False)
        assert track.token_paths(blob, token) == []
    assert_both_readers(case, expectation("12345678F", "/physical/target"), True)
    assert_both_readers(case, expectation("12345678", "/physical/target"), False)
    for token, scalar in [("123456db", "123456 dB"),
                          ("123456db", "123456dB"),
                          ("123456ff", "123456fF"),
                          ("123456db", "limit: 123456dB"),
                          ("1e999999999999999999999db", "1e999999999999999999999dB"),
                          ("1e999999999999999999999ff", "1e999999999999999999999fF"),
                          ("123456db", "-123456db"),
                          ("123456db", "-123456 dB"),
                          ("8f01cfea", "8f01 cf ea"),
                          ("8f01cfea", "+8f01cfea"),
                          ("8f01cfea", "−8f01cfea"),
                          ("8f01cfea", "_8f01cfea"),
                          ("8f01cfea", "8f01cfea_"),
                          ("8f01cfea", "08f01cfea"),
                          ("8f01cfea", "8f01cfea0")]:
        blob = {"quantity": {"target": scalar}}
        (case / "phase1/generated_docs/L22_VERIFICATION_PLAN.json").write_text(
            json.dumps(blob))
        assert_both_readers(case, expectation(token), False)
        assert track.token_paths(blob, token) == []


def test_byte_counts_keep_exact_value_sign_and_dimension(tmp_path):
    blob = {"quantity": {"target": ["55 bytes", "56 bytes", "119 bytes",
                                    "120 bytes", "1024 bytes"]}}
    case = raw_project(tmp_path, json.dumps(blob))
    for token in [*blob["quantity"]["target"], "55 byte"]:
        assert_both_readers(case, expectation(token), True)
        assert track.token_paths(blob, token) == ["quantity.target"]
    for token in ("57 bytes", "-55 bytes", "55 bit", "55"):
        assert_both_readers(case, expectation(token), False)
        assert track.token_paths(blob, token) == []
    for token in ("55 byets", "55 Bytes", "10db", "1e+", "5.5 [ns]",
                  "1e999999999999999999999F", "1e999999999999999999999A",
                  "1e999999999999999999999dB"):
        result = track.converge_ai_expectation(case, expectation(token))
        assert result["usable"] is False
        assert result["tokens_unaskable"][0]["reason"] == "NUMERIC_UNIT_UNSUPPORTED"
        assert track.token_paths({"target": token}, token) == []


@pytest.mark.parametrize("scalar, token", [
    ("Power must remain below 5 mW", "0.005 W"),
    ("| area | 100,000 µm² | maximum |", "100000 um2"),
    ("Operate at −40 °C through startup", "-40 °C"),
    ("offset (+1.25e-3 V) at nominal bias", "1.25 mV"),
    ("delay [5.5 ns] measured", "5500 ps"),
    ("packet 512-bit plus 66 cycles", "512 bit"),
    ("packet 512-bit plus 66 cycles", "66 cycles"),
    ("lengths 55 bytes / 56 bytes / 119 bytes", "55 byte"),
    ("lengths 55 bytes / 56 bytes / 119 bytes", "56 bytes"),
    ("lengths 55 bytes / 56 bytes / 119 bytes", "119 bytes"),
    ("Set 1.0000000000000001 V before sampling", "1000.0000000000001 mV"),
    ("Temperature is 27 deg C during sampling", "27 °C"),
    ("Rate exceeds 2 MS/s during sampling", "2000000 S/s"),
    ("Power <5 mW.", "5 mW"),
])
def test_explicit_prose_quantities_use_shared_readers(tmp_path, scalar, token):
    blob = {"quantity": {"target": scalar}}
    case = raw_project(tmp_path, json.dumps(blob))
    for path in ("/quantity", "/quantity/target", "quantity.target"):
        assert_both_readers(case, expectation(token, path), True)
    assert track.token_paths(blob, token) == ["quantity.target"]


@pytest.mark.parametrize("record", [{"unit": "unrecognized"}, {"unit": "mV"}, {}])
def test_inline_prose_unit_keeps_ownership_and_scope(tmp_path, record):
    blob = {"quantity": {"target": "Supply is 1 V during operation", **record},
            "other": {"target": "Supply is 2 V during operation"}}
    case = raw_project(tmp_path, json.dumps(blob))
    for stem in ("L5_ADI_SPEC", "L19_CONSTRAINTS_PDK"):
        (case / "phase1/generated_docs" / f"{stem}.json").write_text('{}')
    for path in ("/quantity", "/quantity/target", "quantity.target"):
        assert_both_readers(case, expectation("1 V", path), True)
        assert_both_readers(case, expectation("2 V", path), False)
    assert track.token_paths(blob, "1 V") == ["quantity.target"]
    assert track.owning_layers_answer(case, ["1 V"])["layers"] == ["L22_VERIFICATION_PLAN"]
    assert track.token_carriage(case, ["1 V"])["verdict"] == track.CARRIAGE_NAMED_FIELD


@pytest.mark.parametrize("scalar, token", [
    ("Power is 5 mWextra", "5 mW"), ("Power is 5 mW/s", "5 mW"),
    ("Power is 5 mystery mW", "5 mW"), ("Power is 5 frobs", "5"),
    ("Power is 5 mw", "5 mW"), ("Power is 5 mW", "5"),
    ("Power is -5 mW", "5 mW"), ("Power is 5 mW", "-5 mW"),
    ("Power is 5 mW", "5 V"), ("Value is 1,00 V", "100 V"),
    ("Value is 1,00 V", "0 V"), ("Value is 1e+ V", "1 V"),
    ("Value is 1e+ 5 V", "5 V"), ("Value is 1.5.5 V", "5 V"),
    ("Value is v1.5.5 V", "5 V"), ("Value is id5 V", "5 V"),
    ("Value is _5 V", "5 V"), ("Value is 0x5 V", "5 V"),
    ("Value is 1e999999999999999999999 V", "1 V"),
    ("Range is 0–5 V", "5 V"), ("Range is 0-5 V", "5 V"),
    ("Range is 0 - 5 V", "5 V"), ("Range is 0 -5 V", "-5 V"),
    ("Range is 0 to 5 V", "5 V"),
    ("Range is 0 V to 5 V", "0 V"), ("Range is 0 V – 5 V", "0 V"),
    ("Power is 5 mW / s", "5 mW"), ("Power is 5 mW /s", "5 mW"),
    ("Power is 5 mW /", "5 mW"), ("Power is 5 V / mW", "5 V"),
    ("See source.md:55 V", "55 V"), ("See source.md: 55 V", "55 V"),
    ("See line 55", "55"), ("See source.md:55", "55"),
    ("Use 66 cycles", "66"),
    ("Use 55 / 56 bytes", "55 bytes"),
    ("Power is 1.0000000000000001 V", "1 V"),
])
def test_prose_quantity_atoms_never_rescue_invalid_prefixes(tmp_path, scalar, token):
    blob = {"quantity": {"target": scalar}}
    case = raw_project(tmp_path, json.dumps(blob))
    assert_both_readers(case, expectation(token), False)
    assert track.token_paths(blob, token) == []


@pytest.mark.parametrize("blob, path, token", [
    ({"quantity": {"line": "Limit is 5 V"}}, "/quantity/line", "5 V"),
    ({"quantity": {"header_line": "Limit is 5 V"}}, "/quantity/header_line", "5 V"),
    ({"quantity": {"sha256": "Limit is 5 V"}}, "/quantity/sha256", "5 V"),
    ({"quantity": {"digest": "Limit is 5 V"}}, "/quantity/digest", "5 V"),
    ({"quantity": {"target": True}}, "/quantity/target", "1"),
    ({"quantity": {"5 V": "absent"}}, "/quantity", "5 V"),
    ({"quantity_mHZ": {"target": "Limit is 5 Hz", "unit": "Hz"}},
     "/quantity_mHZ/target", "5 Hz"),
    ({"quantity": {"target": ["Limit is 5", "V"]}}, "/quantity/target", "5 V"),
    ({"quantity": {"target": "absent"}, "other": "Limit is 5 V"},
     "/quantity/target", "5 V"),
])
def test_prose_quantity_discovery_keeps_leaf_eligibility(tmp_path, blob, path, token):
    case = raw_project(tmp_path, json.dumps(blob))
    assert_both_readers(case, expectation(token, path), False)
    if "other" not in blob:
        assert track.token_paths(blob, token) == []
