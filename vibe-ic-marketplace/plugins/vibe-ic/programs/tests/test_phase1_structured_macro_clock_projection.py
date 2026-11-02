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


def emit(tmp_path, data, emitter=runner.gen_l8_timing_waveform_doc, extra="", l5=None):
    prefix, _ = contract()
    text = prefix + "```json\n" + json.dumps(data, indent=2) + "\n```\n" + extra
    return emit_text(tmp_path, text, emitter, l5)


def emit_text(tmp_path, text, emitter=runner.gen_l8_timing_waveform_doc, l5=None):
    source = tmp_path / "input/docs/contract.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text)
    docs = {source.name: runner.extract_one(source)}
    runner.gen_l1_datasheet(tmp_path, docs)
    if l5 is not None:
        (tmp_path / "phase1/generated_docs/L5_ADI_SPEC.json").write_text(json.dumps(l5))
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


@pytest.mark.parametrize("complete", [False, True])
def test_same_type_blocks_require_their_own_declared_instances(tmp_path, complete):
    _, data = contract()
    data["analog_blocks"] = data["analog_blocks"][:1]
    l5 = {"analog_blocks": [{"name": "bias_source", "type": "regulator", "count": 1},
                            {"name": "second_source", "type": "regulator", "count": 1}]}
    if complete:
        second = copy.deepcopy(data["analog_blocks"][0])
        second["name"] = "second_source"
        second["instances"][0]["name"] = "second_regulator_unit"
        data["analog_blocks"].append(second)
    l9, _ = emit(tmp_path, data, l5=l5)
    refusals = l9.get("declared_instance_refusals", [])
    assert not any(r.get("block") == "bias_source" for r in refusals)
    missing = [r for r in refusals if r.get("block") == "second_source"]
    assert bool(missing) is not complete
    if not complete:
        assert missing[0]["reason"] == "L9_ANALOG_MACRO_INSTANCE_DECLARATION_UNRESOLVED"
        assert missing[0]["represented_count"] == 0
    assert len(l9["instances"]) == (2 if complete else 1)


def test_missing_explicit_instance_is_reported_by_identity(tmp_path):
    _, data = contract()
    l5 = {"analog_blocks": [{"name": "bias_source", "type": "regulator", "count": 2,
                            "instances": [{"name": "regulator_unit"}, {"name": "missing_unit"}]}]}
    l9, _ = emit(tmp_path, data, l5=l5)
    missing = l9.get("declared_instance_refusals", [])
    assert [(r["block"], r["instance"], r["represented_count"]) for r in missing] == [
        ("bias_source", "missing_unit", 1)]


def test_unscoped_same_type_instance_cannot_cover_two_blocks(tmp_path):
    _, data = contract()
    instance = copy.deepcopy(data["analog_blocks"][0]["instances"][0])
    instance["block_type"] = "regulator"
    data["analog_blocks"] = []
    data["instances"] = [instance]
    l5 = {"analog_blocks": [{"name": name, "type": "regulator", "count": 1}
                            for name in ("bias_source", "second_source")]}
    l9, _ = emit(tmp_path, data, l5=l5)
    assert {r["block"] for r in l9.get("declared_instance_refusals", [])} == {"bias_source", "second_source"}
    assert all(r["represented_count"] == 0 for r in l9["declared_instance_refusals"])


def test_same_instance_requested_by_two_blocks_is_not_credited_to_either(tmp_path):
    _, data = contract()
    l5 = {"analog_blocks": [{"name": name, "type": "regulator", "count": 1,
                            "instances": ["regulator_unit"]}
                            for name in ("bias_source", "second_source")]}
    l9, _ = emit(tmp_path, data, l5=l5)
    assert {r["block"] for r in l9.get("declared_instance_refusals", [])} == {"bias_source", "second_source"}
    assert all(r["instance"] == "regulator_unit" and r["represented_count"] == 0
               for r in l9["declared_instance_refusals"])


def instance_table(ports, omit=None):
    columns = [key for key in ("name", "direction", "type", "net") if key != omit]
    labels = {"name": "Port", "direction": "Direction", "type": "Type", "net": "Net"}
    return ("\n## Instance regulator_unit (regulator)\n"
            + "| " + " | ".join(labels[k] for k in columns) + " |\n"
            + "|" + "---|" * len(columns) + "\n"
            + "".join("| " + " | ".join(p[k] for k in columns) + " |\n" for p in ports))


@pytest.mark.parametrize("field", ["type", "direction", "both"])
def test_table_and_json_must_agree_on_each_port_type_and_direction(tmp_path, field):
    _, data = contract()
    ports = copy.deepcopy(data["analog_blocks"][0]["instances"][0]["ports"])
    for port in ports:
        if field in ("type", "both"):
            port["type"] = "digital"
        if field in ("direction", "both"):
            port["direction"] = "output"
    l9, _ = emit(tmp_path, data, extra=instance_table(ports))
    assert [r["name"] for r in l9.get("instances", [])] == ["processing_unit"]
    assert any(r["name"] == "regulator_unit" and r["reason"] == "L9_DECLARED_INSTANCE_CONFLICT"
               for r in l9.get("declared_instance_refusals", []))
    assert all(wire.get("child_inst") != "regulator_unit" for wire in l9["internal_wires"])


@pytest.mark.parametrize("field", ["type", "direction"])
@pytest.mark.parametrize("with_json", [False, True])
def test_incomplete_table_cannot_leave_partial_typed_ports(tmp_path, field, with_json):
    _, data = contract()
    table = instance_table(data["analog_blocks"][0]["instances"][0]["ports"], omit=field)
    if not with_json:
        data = {"nets": data["nets"]}
    l9, _ = emit(tmp_path, data, extra=table)
    assert all(r["name"] != "regulator_unit" for r in l9.get("instances", []))
    assert any(r["name"] == "regulator_unit" and r["reason"] == "L9_DECLARED_INSTANCE_PORT_UNRESOLVED"
               for r in l9.get("declared_instance_refusals", []))
    assert all(wire.get("child_inst") != "regulator_unit" for wire in l9["internal_wires"])


def test_equivalent_typed_table_and_json_can_merge_with_different_port_order(tmp_path):
    _, data = contract()
    ports = list(reversed(data["analog_blocks"][0]["instances"][0]["ports"]))
    l9, _ = emit(tmp_path, data, extra=instance_table(ports))
    assert len(l9.get("instances", [])) == 2
    assert not l9.get("declared_instance_refusals")
    row = next(r for r in l9["instances"] if r["name"] == "regulator_unit")
    assert row["block"] == "bias_source"
    assert row["master"] == "regulator_macro"
    assert row["ports"][0]["name"] == "regulated"
    assert row["ports"][0]["type"] == "power"
    assert len(l9["internal_wires"]) == 8


@pytest.mark.parametrize("emitter", [runner.gen_l8_timing_waveform, runner.gen_l8_timing_waveform_doc])
@pytest.mark.parametrize("statement", ["sample_i and service_i are asynchronous.",
                                        "Clock group named_pair: sample_i and service_i are asynchronous."])
def test_prose_cannot_declare_or_name_a_clock_group(tmp_path, emitter, statement):
    prefix, _ = contract()
    _, l8 = emit_text(tmp_path, prefix + "\n## Relationships\n" + statement + "\n", emitter)
    assert l8["clock_groups"] == []
    assert l8["declared_clock_group_refusals"][0]["reason"] == "L8_CLOCK_GROUP_PROSE_UNRESOLVED"


@pytest.mark.parametrize("emitter", [runner.gen_l8_timing_waveform, runner.gen_l8_timing_waveform_doc])
@pytest.mark.parametrize("table", [
    "| Clocks | Relationship |\n|---|---|\n| sample_i, service_i | asynchronous |\n",
    "| Group | Clocks | Relationship |\n|---|---|---|\n| | sample_i, service_i | asynchronous |\n",
])
def test_clock_group_tables_cannot_synthesize_missing_names(tmp_path, emitter, table):
    prefix, _ = contract()
    _, l8 = emit_text(tmp_path, prefix + table, emitter)
    assert l8["clock_groups"] == []
    assert l8["declared_clock_group_refusals"][0]["reason"] == "L8_DECLARED_CLOCK_GROUP_UNRESOLVED"
