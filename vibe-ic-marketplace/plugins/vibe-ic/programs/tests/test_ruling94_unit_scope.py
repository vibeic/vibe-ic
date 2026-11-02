import json

import pytest

import phase1_expert_parse_track as track
import flow109_metric_acceptance as metrics
from programs.tests._hostpaths import require_repo


def project(tmp_path, blob):
    folder = tmp_path / "phase1/generated_docs"
    folder.mkdir(parents=True)
    (folder / "L22_VERIFICATION_PLAN.json").write_text(json.dumps(blob))
    return tmp_path


def expectation(tokens, path="/quantity"):
    return {"id": "quantity", "layer": "L22_VERIFICATION_PLAN",
            "field_path": path, "expected_tokens": tokens}


@pytest.mark.parametrize("token, quantity, expected", [
    ("40 °C", {"min": 40, "unit": "dB"}, False),
    ("40", {"min": 40, "unit": "dB"}, False),
    ("1 V", {"value": 1000, "unit": "mV"}, True),
    ("1000 mV", {"value": 1, "unit": "V"}, True),
    ("2", {"value": 2}, True),
    ("2", {"value": 2, "unit": "unrecognized"}, False),
    ("2", {"value": 2, "unit": "—"}, True),
    ("14 bit", {"min": 14, "unit": "bit"}, True),
])
def test_numeric_tokens_need_compatible_dimensions(tmp_path, token, quantity, expected):
    result = track.converge_ai_expectation(
        project(tmp_path, {"quantity": quantity}), expectation([token]))
    assert result["usable"] is True
    assert result["met"] is expected


@pytest.mark.parametrize("selector", [None, "", " ", "."])
def test_missing_scope_is_an_authoring_refusal(tmp_path, selector):
    result = track.converge_ai_expectation(
        project(tmp_path, {"quantity": 40}), expectation(["40"], selector))
    assert result["met"] is False
    assert result["usable"] is False
    assert result["scope"] == "UNSCOPED"


@pytest.mark.parametrize("selector", ["absent.value", "/absent/value"])
def test_invalid_scope_never_borrows_a_value_from_the_layer(tmp_path, selector):
    result = track.converge_ai_expectation(
        project(tmp_path, {"quantity": 40}), expectation(["40"], selector))
    assert result["met"] is False
    assert result["usable"] is False
    assert result["field_path_status"] == "UNDECLARED"


def test_d02_corner_expectation_requires_its_typed_temperature_scope(tmp_path):
    case = project(tmp_path, {"fields": {"verification_plan": {
        "corner_matrix": {"corners": ["TT", "SS", "FF"],
                          "temperature_c": [-40, 27, 125]},
        "analog": [{"specifications": [{"name": "PSRR", "min": 40, "unit": "dB"}]}],
    }}})
    original = expectation(["TT", "SS", "FF", "40", "27", "125"], None)
    original["id"] = "analog_corner_results"
    actual, unresolved, unrouted = metrics._d0102_compare(
        case, {"expectations": [original]}, {})
    assert actual == []
    assert unrouted == []
    assert len(unresolved) == 1
    assert unresolved[0]["scope"] == "UNSCOPED"

    corrected = {**original, "field_path": "/fields/verification_plan/corner_matrix",
                 "expected_tokens": ["TT", "SS", "FF", "-40 °C", "27 °C", "125 °C"]}
    actual, unresolved, unrouted = metrics._d0102_compare(
        case, {"expectations": [corrected]}, {})
    assert actual == [{"id": "analog_corner_results"}]
    assert unresolved == []
    assert unrouted == []


def test_dimensionless_adapter_cannot_override_shared_numeric_equality(tmp_path):
    case = project(tmp_path, {"quantity": {"target": 1.000000000000001, "unit": "—"}})
    for token, expected in [("1.000000000000001", True), ("1", False)]:
        item = expectation([token, "—"])
        actual, unresolved, _ = metrics._d0102_compare(case, {"expectations": [item]}, {})
        assert bool(actual) is expected
        assert unresolved == []


def test_checked_in_typed_voltage_supports_only_its_dimension(tmp_path):
    source = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
                          "fixtures", "stage_analog_on_pass_review", "accept_adc_conv",
                          "phase1", "generated_docs", "L5_ADI_SPEC.json")
    blocks = json.loads(source.read_text())["analog_blocks"]
    quantity = next(row for block in blocks for row in block["spec"]["specs"]
                    if row.get("unit") == "V" and type(row.get("target")) in (int, float))
    case = project(tmp_path, {"quantity": quantity})
    value = quantity["target"]
    assert track.converge_ai_expectation(case, expectation([f"{value} V"]))["met"] is True
    assert track.converge_ai_expectation(case, expectation([f"{value} °C"]))["met"] is False
