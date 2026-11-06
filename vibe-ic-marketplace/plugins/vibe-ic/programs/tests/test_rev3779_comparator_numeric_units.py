import json

import pytest

import phase1_expert_parse_track as track


def raw_project(tmp_path, text):
    folder = tmp_path / "phase1/generated_docs"
    folder.mkdir(parents=True)
    (folder / "L22_VERIFICATION_PLAN.json").write_text(text)
    return tmp_path












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
