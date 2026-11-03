"""Typed declarations outrank partial derived rows; real conflicts still refuse (#112)."""
import json
from pathlib import Path

import pytest

import phase1_doc_one_shot_runner as runner

PINS = "# Part\n"
SUPPLY = ("\n| Instance | L5 Block | Core supply | Ground |\n|---|---|---|---|\n"
          "| U1 | unit_kind | RAIL | GND |\n")
PROSE = "\nOne 25 pF MIM capacitor between the REFP net and GND.\n"


def port(name, net, kind="analog", direction="inout"):
    return {"name": name, "net": net, "type": kind, "direction": direction}


UNIT_PORTS = [port("vdd", "RAIL", "power", "input"), port("vss", "GND", "ground"),
              port("vin", "AIN", "analog", "input")]


def l9_for(tmp_path, prose, data):
    source = tmp_path / "input/docs/contract.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    data = {"nets": ["RAIL", "OTHER", "GND", "AIN", "REFP"], **data}
    source.write_text(PINS + prose + "\n```json\n" + json.dumps(data) + "\n```\n")
    docs = {source.name: runner.extract_one(source)}
    runner.gen_l1_datasheet(tmp_path, docs)
    return json.loads(Path(runner.gen_l9_integration_spec(tmp_path, docs, {}).path).read_text())


def rows(l9):
    return {row["name"]: row for row in l9.get("instances", [])}


def conflicts(l9):
    return [r["name"] for r in l9.get("declared_instance_refusals", [])
            if r["reason"] == "L9_DECLARED_INSTANCE_CONFLICT"]


def test_portless_supply_row_takes_the_typed_ports(tmp_path):
    l9 = l9_for(tmp_path, SUPPLY, {"instances": [
        {"name": "U1", "block_type": "unit_kind", "master": "unit_kind", "ports": UNIT_PORTS}]})
    assert conflicts(l9) == []
    row = rows(l9)["U1"]
    assert row["master"] == "unit_kind"
    assert set(row["port_map"]) == {"vdd", "vss", "vin"}
    assert row["connections"] == row["port_map"]
    assert row["power_net"] == "RAIL" and row["ground_net"] == "GND"
    wires = {w["child_port"] for w in l9["internal_wires"] if w.get("child_inst") == "U1"}
    assert wires == {"vdd", "vss", "vin"}


def test_supply_row_disagreeing_on_the_rail_is_still_a_conflict(tmp_path):
    ports = [port("vdd", "OTHER", "power", "input"), *UNIT_PORTS[1:]]
    l9 = l9_for(tmp_path, SUPPLY, {"instances": [
        {"name": "U1", "block_type": "unit_kind", "ports": ports}]})
    assert conflicts(l9) == ["U1"]
    assert "U1" not in rows(l9)


def test_supply_row_disagreeing_on_the_block_is_still_a_conflict(tmp_path):
    l9 = l9_for(tmp_path, SUPPLY, {"instances": [
        {"name": "U1", "block_type": "other_kind", "ports": UNIT_PORTS}]})
    assert conflicts(l9) == ["U1"]


def derived_name(l9):
    return next(row["name"] for row in l9["instances"] if row.get("identity_derivation"))


def test_generic_derived_passive_takes_the_typed_terminals(tmp_path):
    name = derived_name(l9_for(tmp_path / "probe", PROSE, {}))
    ports = [port("top", "REFP"), port("vss", "GND", "ground")]
    l9 = l9_for(tmp_path, PROSE, {"instances": [
        {"name": name, "block_type": "capacitor", "master": "decap_macro", "ports": ports}]})
    assert conflicts(l9) == []
    row = rows(l9)[name]
    assert row["block_type"] == "capacitor" and row["master"] == "decap_macro"
    assert set(row["port_map"]) == {"top", "vss"}
    assert row["parameters"]["capacitance_pf"] == 25.0
    assert "identity_derivation" not in row
    assert {w["child_port"] for w in l9["internal_wires"] if w.get("child_inst") == name} == {"top", "vss"}


def test_derived_passive_on_other_nets_is_still_a_conflict(tmp_path):
    name = derived_name(l9_for(tmp_path / "probe", PROSE, {}))
    ports = [port("top", "AIN"), port("vss", "GND", "ground")]
    l9 = l9_for(tmp_path, PROSE, {"instances": [{"name": name, "block_type": "capacitor", "ports": ports}]})
    assert conflicts(l9) == [name]


def test_derived_passive_with_other_capacitance_is_still_a_conflict(tmp_path):
    name = derived_name(l9_for(tmp_path / "probe", PROSE, {}))
    ports = [port("top", "REFP"), port("vss", "GND", "ground")]
    l9 = l9_for(tmp_path, PROSE, {"instances": [{"name": name, "block_type": "capacitor", "ports": ports,
                                                 "parameters": {"capacitance_pf": 10.0}}]})
    assert conflicts(l9) == [name]


def test_explicit_ports_on_both_sides_that_differ_still_conflict(tmp_path):
    table = ("\n## Instance U1 (unit_kind)\n| Port | Direction | Type | Net |\n|---|---|---|---|\n"
             "| vdd | in | power | RAIL |\n")
    l9 = l9_for(tmp_path, table, {"instances": [{"name": "U1", "block_type": "unit_kind", "ports": UNIT_PORTS}]})
    assert conflicts(l9) == ["U1"]


CAP_SPEC = {"specs": [{"name": "capacitance", "target_raw": "25", "range_raw": "22.5-27.5", "unit": "pF"}]}
HEADING = ("# Analog\n\nAnalog front end.\n\n## Block A — `pll` : generator (×6 copies)\n\n"
           "| Parameter | Typ | Min | Max | Unit | Note |\n|---|---|---|---|---|---|\n"
           "| Fout | 100 | 90 | 110 | MHz | output |\n")


def decl(count=2, kind="capacitor", instances=("C1", "C2"), **extra):
    return {"analog_blocks": [{
        "name": "shared_cap", "type": kind, "count": count, "spec": CAP_SPEC, **extra,
        "instances": [{"name": name, "ports": [port("top", "REFP"), port("vss", "GND", "ground")]}
                      for name in instances]}]}


def answers(project, value):
    path = project / "input/step_0_5ic_answers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"answers": {"analog_block_multiplicity": value}, "answer_provenance": {
        "analog_block_multiplicity": {"answered_by": "agent", "citation": "input/docs/spec.md:1 sha256:00"}}}))


def l5_for(project, data):
    text = HEADING + "\n```json\n" + json.dumps(data) + "\n```\n"
    return json.loads(Path(runner.gen_l5_adi_spec(project, {"spec.md": text}).path).read_text())


def test_typed_declaration_gives_a_block_its_identity_without_a_keyword(tmp_path):
    assert "shared_cap" not in runner._ANALOG_KEYWORDS
    answers(tmp_path, {"shared_cap": 2})
    doc = l5_for(tmp_path, decl())
    block = next(b for b in doc["analog_blocks"] if b["name"] == "shared_cap")
    assert block["type"] == "capacitor" and block["count"] == 2
    assert block["instances"] == ["C1", "C2"]
    assert block["spec"] == CAP_SPEC
    assert block["low_confidence"] is False
    assert block["multiplicity_evidence"]["low_confidence"] is False


def test_declaration_without_typed_answer_adds_no_block(tmp_path):
    assert all(b["name"] != "shared_cap" for b in l5_for(tmp_path, decl())["analog_blocks"])


@pytest.mark.parametrize("data", [{}, {"analog_blocks": [{"name": "shared_cap", "instances": [
    {"name": "C1", "ports": []}]}]}])
def test_block_without_a_typed_identity_stays_unknown(tmp_path, data):
    answers(tmp_path, {"shared_cap": 1})
    with pytest.raises(ValueError, match="L5_BLOCK_MULTIPLICITY_UNKNOWN_BLOCK: shared_cap"):
        l5_for(tmp_path, data)


@pytest.mark.parametrize("data", [decl(count=3), decl(instances=("C1",)), decl(count=2, instances=("C1", "C2", "C3"))])
def test_declared_block_contradicting_the_answer_is_refused(tmp_path, data):
    answers(tmp_path, {"shared_cap": 2})
    with pytest.raises(ValueError, match="L5_BLOCK_MULTIPLICITY_CONTRADICTION: shared_cap"):
        l5_for(tmp_path, data)


def test_two_declarations_of_one_block_that_differ_are_refused(tmp_path):
    answers(tmp_path, {"shared_cap": 2})
    docs = {"a.md": HEADING + "\n```json\n" + json.dumps(decl()) + "\n```\n",
            "b.md": "```json\n" + json.dumps(decl(kind="resistor")) + "\n```\n"}
    with pytest.raises(ValueError, match="L5_BLOCK_MULTIPLICITY_CONTRADICTION: shared_cap"):
        runner.gen_l5_adi_spec(tmp_path, docs)


CAP_PORTS = [port("top", "REFP"), port("vss", "GND", "ground")]


@pytest.mark.parametrize("block_type,parameters", [
    ("resistor", {}), ("inductor", {"resistance_ohm": 5}), ("unit_kind", {}), ("mom_capacitor", {}),
    ("mim_capacitor", {"capacitance_pf": 10.0})])
def test_derived_passive_never_yields_to_another_kind(tmp_path, block_type, parameters):
    name = derived_name(l9_for(tmp_path / "probe", PROSE, {}))
    l9 = l9_for(tmp_path, PROSE, {"instances": [
        {"name": name, "block_type": block_type, "ports": CAP_PORTS, "parameters": parameters}]})
    assert conflicts(l9) == [name]
    assert name not in rows(l9)


@pytest.mark.parametrize("block_type", ["capacitor", "mim_capacitor"])
def test_derived_passive_yields_to_the_same_kind(tmp_path, block_type):
    name = derived_name(l9_for(tmp_path / "probe", PROSE, {}))
    l9 = l9_for(tmp_path, PROSE, {"instances": [{"name": name, "block_type": block_type, "ports": CAP_PORTS}]})
    assert conflicts(l9) == []
    assert rows(l9)[name]["block_type"] == block_type


def test_derived_passive_with_a_third_port_is_a_conflict(tmp_path):
    name = derived_name(l9_for(tmp_path / "probe", PROSE, {}))
    ports = [*CAP_PORTS, port("x", "RAIL")]
    l9 = l9_for(tmp_path, PROSE, {"instances": [{"name": name, "block_type": "capacitor", "ports": ports}]})
    assert conflicts(l9) == [name]


def test_portless_row_with_a_differing_parameter_does_not_yield():
    prior = {"block_type": "unit_kind", "parameters": {"capacitance_pf": 25.0}}
    assert not runner._typed_instance_supersedes(
        prior, "unit_kind", UNIT_PORTS, {"capacitance_pf": 10.0}, {})


def test_keyword_class_declared_as_another_type_is_refused(tmp_path):
    answers(tmp_path, {"pll": 6})
    data = {"analog_blocks": [{"name": "pll", "type": "capacitor", "count": 6, "instances": [
        {"name": f"P{i}"} for i in range(6)]}]}
    with pytest.raises(ValueError, match="L5_BLOCK_MULTIPLICITY_CONTRADICTION: pll"):
        l5_for(tmp_path, data)


@pytest.mark.parametrize("instances,count,typed", [
    ([{"ports": []}, {"ports": []}], 2, 2),
    ([{"name": "C1"}, {"name": "C1"}], 2, 2),
    ([{"name": 1}, {"name": 2}], None, 2),
    (["C1", "C2"], 2, 2),
    ([{"name": "C1"}], True, 1),
    ([{"name": "C1"}, {"name": "C2"}], "2", 2),
])
def test_malformed_declared_rows_never_make_a_count_explicit(tmp_path, instances, count, typed):
    answers(tmp_path, {"shared_cap": typed})
    data = {"analog_blocks": [{"name": "shared_cap", "type": "capacitor", "count": count,
                               "spec": CAP_SPEC, "instances": instances}]}
    with pytest.raises(ValueError, match="L5_BLOCK_MULTIPLICITY_INVALID: shared_cap"):
        l5_for(tmp_path, data)


def test_declared_block_alone_keeps_the_analog_flags_consistent(tmp_path):
    answers(tmp_path, {"shared_cap": 1})
    data = {"analog_blocks": [{"name": "shared_cap", "type": "capacitor", "spec": CAP_SPEC,
                               "instances": [{"name": "C1"}]}]}
    text = "# Part\n\nA digital part.\n\n```json\n" + json.dumps(data) + "\n```\n"
    doc = json.loads(Path(runner.gen_l5_adi_spec(tmp_path, {"spec.md": text}).path).read_text())
    assert doc["no_analog"] is False and doc["analog_blocks_detected"] is True
    assert [b["name"] for b in doc["analog_blocks"]] == ["shared_cap"]


def test_declared_block_is_not_also_listed_as_spurious(tmp_path):
    answers(tmp_path, {"adc": 1})
    data = {"analog_blocks": [{"name": "adc", "type": "adc", "instances": [{"name": "A1"}]}]}
    text = (HEADING + "\nAn ADC front end.\n\n```json\n" + json.dumps(data) + "\n```\n")
    doc = json.loads(Path(runner.gen_l5_adi_spec(tmp_path, {"spec.md": text}).path).read_text())
    assert "adc" in [b["name"] for b in doc["analog_blocks"]]
    assert "adc" not in [b["name"] for b in doc.get("spurious_analog_blocks", [])]
