"""Structured declarations reach the normal L9/L8 producer artifacts."""
import copy
import json
from pathlib import Path

import pytest

import phase1_doc_one_shot_runner as runner

FIXTURE = Path(__file__).parent / "fixtures/phase1_local/macro_clock_contract/contract.md"


def contract():
    text = FIXTURE.read_text()
    prefix, tail = text.split("```json\n")
    return prefix, json.loads(tail.split("```")[0])


def emit(tmp_path, data, emitter=runner.gen_l8_timing_waveform_doc, extra=""):
    prefix, _ = contract()
    text = prefix + "```json\n" + json.dumps(data, indent=2) + "\n```\n" + extra
    source = tmp_path / "input/docs/contract.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text)
    docs = {source.name: runner.extract_one(source)}
    runner.gen_l1_datasheet(tmp_path, docs)
    l9 = json.loads(Path(runner.gen_l9_integration_spec(tmp_path, docs, {}).path).read_text())
    l8 = json.loads(Path(emitter(tmp_path, docs).path).read_text())
    return l9, l8


@pytest.mark.parametrize("emitter", [runner.gen_l8_timing_waveform, runner.gen_l8_timing_waveform_doc])
def test_structured_regulator_feeds_another_macro_and_clocks_reach_both_emitters(tmp_path, emitter):
    _, data = contract()
    l9, l8 = emit(tmp_path, data, emitter)
    bindings = {r["name"]: r["connections"] for r in l9.get("instances", [])}
    assert bindings == {
        "regulator_unit": {"source": "source_rail", "return": "return_rail", "sense": "reference_i", "regulated": "regulated_local"},
        "processing_unit": {"supply": "regulated_local", "return": "return_rail", "sample": "sample_i", "result": "result_o"}}
    assert {r["name"]: r["master"] for r in l9["instances"]} == {
        "regulator_unit": "regulator_macro", "processing_unit": "integrator_macro"}
    assert all(r["connections"] == r["port_map"] for r in l9["instances"])
    assert len(l9["internal_wires"]) == 8
    assert l9["instances"][0]["ports"][3]["type"] == "power"
    assert l9["instances"][0]["ports"][3]["direction"] == "output"
    groups = [{k: r[k] for k in ("name", "clocks", "relationship")} for r in l8["clock_groups"]]
    assert groups == data["clock_groups"]
    for row in l9["instances"] + l8["clock_groups"]:
        assert row["evidence"]["doc"] == "input/docs/contract.md"
        assert row["evidence"]["line"] > 1


@pytest.mark.parametrize("field", ["type", "direction", "net"])
def test_missing_typed_binding_does_not_create_partial_regulator(tmp_path, field):
    _, data = contract()
    del data["analog_blocks"][0]["instances"][0]["ports"][0][field]
    l9, _ = emit(tmp_path, data)
    assert [r["name"] for r in l9.get("instances", [])] == ["processing_unit"]
    assert any(r["reason"] == "L9_DECLARED_INSTANCE_PORT_UNRESOLVED" for r in l9["declared_instance_refusals"])
    assert all(r.get("child_inst") != "regulator_unit" for r in l9["internal_wires"])


def test_missing_internal_net_is_unresolved(tmp_path):
    _, data = contract()
    data.pop("nets")
    l9, _ = emit(tmp_path, data)
    assert l9.get("instances", []) == []
    assert len(l9["declared_instance_refusals"]) == 2


def test_macro_type_and_count_do_not_invent_instance_identity(tmp_path):
    _, data = contract()
    data["analog_blocks"] = [{"name": "bias_source", "type": "regulator", "count": 1}]
    l9, _ = emit(tmp_path, data)
    assert l9.get("instances", []) == []
    assert l9["declared_instance_refusals"][0]["reason"] == "L9_ANALOG_MACRO_INSTANCES_UNDECLARED"


@pytest.mark.parametrize("change", ["missing_relationship", "missing_clocks", "duplicate_clock", "unknown_relationship"])
def test_incomplete_clock_declaration_remains_unresolved(tmp_path, change):
    _, data = contract()
    row = data["clock_groups"][0]
    if change.startswith("missing_"):
        row.pop(change.removeprefix("missing_"))
    elif change == "duplicate_clock":
        row["clocks"] = ["sample_i", "sample_i"]
    else:
        row["relationship"] = "independent"
    _, l8 = emit(tmp_path, data)
    assert l8["clock_groups"] == []
    assert l8["declared_clock_group_refusals"][0]["reason"] == "L8_DECLARED_CLOCK_GROUP_UNRESOLVED"


@pytest.mark.parametrize("kind", ["instances", "clock_groups"])
def test_conflicting_declarations_in_two_documents_remove_identity(tmp_path, kind):
    _, data = contract()
    second = copy.deepcopy(data)
    if kind == "instances":
        second["analog_blocks"][0]["instances"][0]["ports"][0]["net"] = "return_rail"
    else:
        second["clock_groups"][0]["relationship"] = "synchronous"
    extra = "```json\n" + json.dumps(second) + "\n```\n"
    l9, l8 = emit(tmp_path, data, extra=extra)
    if kind == "instances":
        assert [r["name"] for r in l9.get("instances", [])] == ["processing_unit"]
        assert any(r["reason"] == "L9_DECLARED_INSTANCE_CONFLICT" for r in l9["declared_instance_refusals"])
    else:
        assert l8["clock_groups"] == []
        assert l8["declared_clock_group_refusals"][0]["reason"] == "L8_DECLARED_CLOCK_GROUP_CONFLICT"


def test_matching_repeated_declarations_are_idempotent(tmp_path):
    _, data = contract()
    l9, l8 = emit(tmp_path, data, extra="```json\n" + json.dumps(data) + "\n```\n")
    assert len(l9.get("instances", [])) == 2
    assert len(l9["internal_wires"]) == 8
    assert len(l8["clock_groups"]) == 1


def test_prose_and_suggestive_names_do_not_supply_missing_fields(tmp_path):
    _, data = contract()
    data["analog_blocks"][0]["instances"][0].pop("ports")
    data["clock_groups"][0].pop("relationship")
    l9, l8 = emit(tmp_path, data, extra="The regulator supplies regulated_local from source_rail.\nThe sample and service groups operate independently.\n")
    assert [r["name"] for r in l9.get("instances", [])] == ["processing_unit"]
    assert l8["clock_groups"] == []


def test_duplicate_json_key_is_not_last_writer_wins(tmp_path):
    _, data = contract()
    extra = '```json\n{"clock_groups": [], "clock_groups": []}\n```\n'
    l9, l8 = emit(tmp_path, data, extra=extra)
    assert any(r["reason"] == "DECLARED_CONNECTIVITY_JSON_DUPLICATE_KEY" for r in l9["declared_instance_refusals"])
    assert any(r["reason"] == "DECLARED_CONNECTIVITY_JSON_DUPLICATE_KEY" for r in l8["declared_clock_group_refusals"])


def test_l5_declared_macro_without_instance_mapping_is_named_unresolved(tmp_path):
    prefix, _ = contract()
    text = prefix + "\n## Analog block contract\nThe analog section contains one regulator at 1.8 V.\n"
    source = tmp_path / "input/docs/contract.md"
    source.parent.mkdir(parents=True)
    source.write_text(text)
    docs = {source.name: text}
    runner.gen_l1_datasheet(tmp_path, docs)
    # This is a typed producer field, not a guess of instance name from type.
    l5path = tmp_path / "phase1/generated_docs/L5_ADI_SPEC.json"
    l5path.write_text(json.dumps({"analog_blocks": [{"name": "bias_source", "type": "regulator", "count": 1}]}))
    l9 = json.loads(Path(runner.gen_l9_integration_spec(tmp_path, docs, {}).path).read_text())
    assert l9.get("instances", []) == []
    refusal = l9["declared_instance_refusals"][0]
    assert refusal["reason"] == "L9_ANALOG_MACRO_INSTANCE_DECLARATION_UNRESOLVED"
    assert refusal["declared_count"] == 1
    assert refusal["represented_count"] == 0


def test_empty_typed_instance_table_is_named_unresolved(tmp_path):
    prefix, _ = contract()
    text = prefix + "## Instance bias_unit (regulator)\n| Port | Type | Net |\n|---|---|---|\n"
    source = tmp_path / "input/docs/contract.md"
    source.parent.mkdir(parents=True)
    source.write_text(text)
    docs = {source.name: text}
    runner.gen_l1_datasheet(tmp_path, docs)
    l9 = json.loads(Path(runner.gen_l9_integration_spec(tmp_path, docs, {}).path).read_text())
    assert l9.get("instances", []) == []
    assert l9["declared_instance_refusals"][0]["reason"] == "L9_DECLARED_INSTANCE_PORT_UNRESOLVED"
