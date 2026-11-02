import json

import pytest

import phase1_expert_parse_track as track
import flow109_metric_acceptance as metrics
import ic_expert_backup_pack as pack
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


@pytest.mark.parametrize("token, scalar", [
    ("5.5 [ns]", "55 ns"), ("5.5 ns(cycle)", "55 ns cycle"),
    ("1e+", "prose 1e"), ("1.2.3", "prose 123"), ("--40", "prose 40"),
    ("1e9999999999999999999", "irrelevant"),
    ("16-bit 4-to-1", "16-bit 4-to-1"),
])
def test_malformed_numeric_tokens_are_refused_without_text_matching(tmp_path, token, scalar):
    result = track.converge_ai_expectation(
        project(tmp_path, {"quantity": scalar}), expectation([token]))
    assert result["met"] is False
    assert result["tokens_unaskable"]


@pytest.mark.parametrize("blob, path", [
    ({"unit": "V", "quantity": {"target": 2}}, "/quantity"),
    ({"quantity_v": {"target": 2}}, "/quantity_v"),
    ({"quantity": {"target": 2, "units": "V"}}, "/quantity"),
])
def test_dimensionless_consumer_keeps_the_selectors_unit_context(tmp_path, blob, path):
    case = project(tmp_path, blob)
    item = expectation(["2"], path)
    assert track.converge_ai_expectation(case, item)["met"] is False
    actual, _, _ = metrics._d0102_compare(case, {"expectations": [item]}, {})
    assert actual == []


@pytest.mark.parametrize("declared", [None, 42, ["mV"]])
def test_malformed_unit_metadata_cannot_borrow_outer_units(tmp_path, declared):
    case = project(tmp_path, {"unit": "V", "quantity": {"target": 2, "unit": declared}})
    result = track.converge_ai_expectation(case, expectation(["2 V"]))
    assert result["met"] is False


@pytest.mark.parametrize("declarations", [{"unit": "", "units": "V"},
                                        {"units": "V", "unit": ""}])
def test_conflicting_unit_aliases_do_not_depend_on_object_order(tmp_path, declarations):
    case = project(tmp_path, {"quantity": {"target": 2, **declarations}})
    assert track.converge_ai_expectation(case, expectation(["2"]))["met"] is False


def test_split_number_and_unit_tokens_are_an_authoring_refusal(tmp_path):
    case = project(tmp_path, {"quantity": {"target": 1, "unit": "V"}})
    result = track.converge_ai_expectation(case, expectation(["1", "V"]))
    assert result["usable"] is False
    assert {x["reason"] for x in result["tokens_unaskable"]} == {"SEPARATE_UNIT_TOKEN"}
    actual, unresolved, _ = metrics._d0102_compare(
        case, {"expectations": [expectation(["1", "V"])]}, {})
    assert actual == [] and len(unresolved) == 1


def test_large_exponent_unit_normalization_does_not_raise(tmp_path):
    token = "1e999999999999999999 GV"
    case = project(tmp_path, {"quantity": token})
    assert track.converge_ai_expectation(case, expectation([token]))["met"] is True


def test_an_invalid_observed_number_does_not_abort_a_text_expectation(tmp_path):
    case = project(tmp_path, {"quantity": {"label": "TT", "value": "1e9999999999999999999"}})
    assert track.converge_ai_expectation(case, expectation(["TT"]))["met"] is True


def test_split_refusal_retains_the_scope_of_each_branch(tmp_path):
    case = project(tmp_path, {"quantity": 2})
    result = track.converge_ai_expectation(case, {
        "id": "split", "sub_expectations": [expectation(["2"], None), expectation(["2"])],
    })
    assert result["usable"] is False and result["met"] is False
    assert [child["scope"] for child in result["sub_results"]] == ["UNSCOPED", "json_pointer"]


@pytest.mark.parametrize("token, scalar", [
    ("(5.5 ns)", "55 ns"), ("{1e+}", "1e"),
    ("[[−40 °C]]", "40 C"), ("≥ 10", "10"),
    ("[NaN]", "NaN"), ("NaN V", "NaN V"),
])
def test_wrapping_punctuation_cannot_hide_numeric_intent(tmp_path, token, scalar):
    case = project(tmp_path, {"quantity": scalar})
    result = track.converge_ai_expectation(case, expectation([token]))
    assert result["met"] is False
    assert result["tokens_unaskable"]
    actual, unresolved, _ = metrics._d0102_compare(
        case, {"expectations": [expectation([token])]}, {})
    assert actual == [] and len(unresolved) == 1


def test_bad_path_authoring_advice_never_recommends_omitting_scope(tmp_path):
    case = project(tmp_path, {"quantity": 2})
    reason = track.refuse_undeclared_field_path(
        track.authoring_schema(case), "L22_VERIFICATION_PLAN", "bad.path")
    assert reason is not None and "or omit" not in reason


def test_expert_handoff_requires_scopes_for_single_and_split_branches(tmp_path):
    case = project(tmp_path, {"quantity": 1})
    handoff = pack.assemble("Review this typed quantity.", None, None, [], [],
                            tmp_path / "handoff", k=0, output_target="l_doc_expectations.json",
                            authoring_schema=track.authoring_schema(case))
    contract = handoff["answer_contract"]
    paths = [contract["shape"]["expectations"][0]["field_path"],
             contract["split_shape"]["expectations"][0]["sub_expectations"][0]["field_path"]]
    assert all("required" in path.lower() for path in paths)
    assert all("or omitted" not in rule for rule in contract["rules"])
