"""Declared boundary conditions must survive the normal L1/L5 producers."""
import json
from pathlib import Path

import pytest
import phase1_doc_one_shot_runner as runner
import analog_a1_spec_emit as a1


INTERFACE = """# Neutral interface
## External Interface
| Signal | Direction | Width |
|---|---|---|
| sense_a | input | 1 |
| sense_b | input | 1 |
## Block A — `pll` : analog phase locked loop operating at 1.5 V
| Spec | Target | Range | Unit | Note |
|---|---|---|---|---|
| fclk | 20 | 19–21 | MHz | output |
### pll ports
| Pin | Role |
|---|---|
| sense_a | input reference |
"""


def generate(tmp_path, declaration, interface=INTERFACE):
    docs = {"interface.md": interface, "conditions.md": declaration}
    for name, text in docs.items():
        path = tmp_path / "input/docs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    l1 = json.loads(Path(runner.gen_l1_datasheet(tmp_path, docs).path).read_text())
    l5 = json.loads(Path(runner.gen_l5_adi_spec(tmp_path, docs).path).read_text())
    return l1, l5


def pin_rows(l1, pin="sense_a"):
    return next(p for p in l1["pin_table"] if p["name"] == pin).get("electrical_specs", [])


def block_rows(l5):
    return next(b for b in l5["analog_blocks"] if b["name"] == "pll").get("spec", {}).get("input_conditions", [])


def test_tolerance_reaches_pin_block_and_a1_consumer(tmp_path):
    quote = "The sense_a pin is driven by an external precision reference, 2.0 V +/- 2%."
    l1, l5 = generate(tmp_path, quote)
    rows = pin_rows(l1)
    assert [r.get("min_typ_max") for r in rows] == [{"typ": 2.0, "min": 1.96, "max": 2.04}]
    assert rows[0]["tolerance_percent"] == 2
    assert rows[0]["evidence"] == {"doc": "input/docs/conditions.md", "line": 1, "quote": quote}
    assert block_rows(l5) == rows
    entry = next(b for b in l5["analog_blocks"] if b["name"] == "pll")
    rec = a1.emit_for_block(tmp_path, entry)
    assert rec["emitted"] is True
    body = json.loads((tmp_path / rec["spec_path"]).read_text())
    assert body["input_conditions"] == rows
    import phase1_expert_parse_track as expert
    assert expert.subtree_at(l5, "/analog_blocks/0/spec")[0]["input_conditions"] == rows


@pytest.mark.parametrize("text,expected", [
    ("The sense_a pin is driven by an external reference, nominal 2.0 V (min 1.9 V, max 2.1 V).", {"typ": 2.0, "min": 1.9, "max": 2.1}),
    ("The sense_a pin is driven by an external reference, 2.0 V (1.9 to 2.1 V).", {"typ": 2.0, "min": 1.9, "max": 2.1}),
    ("The sense_a pin is driven by an external reference, 2.0 V.", {"typ": 2.0}),
])
def test_range_and_nominal_without_invented_tolerance(tmp_path, text, expected):
    l1, l5 = generate(tmp_path, text)
    assert [r.get("min_typ_max") for r in pin_rows(l1)] == [expected]
    assert "tolerance_percent" not in pin_rows(l1)[0]
    assert block_rows(l5) == pin_rows(l1)


@pytest.mark.parametrize("text", [
    "The sense_a pin is not driven by an external reference, 2.0 V +/- 2%.",
    "Perhaps the sense_a pin is driven by an external reference, 2.0 V +/- 2%.",
    "If the sense_a pin is driven by an external reference, 2.0 V +/- 2%, use it.",
    "# History\nThe sense_a pin is driven by an external reference, 2.0 V +/- 2%.",
    "Historically the sense_a pin is driven by an external reference, 2.0 V +/- 2%.",
    "The sense_a pin belongs to the pll.",
])
def test_denied_history_speculation_or_membership_has_no_condition(tmp_path, text):
    l1, l5 = generate(tmp_path, text)
    assert pin_rows(l1) == []
    assert block_rows(l5) == []


def test_explicit_supersession_retains_replaced_declaration(tmp_path):
    old = "The sense_a pin is driven by an external reference, 2.0 V +/- 5%."
    new = "The sense_a pin is driven by an external reference, 2.0 V +/- 1%. This replaces the earlier declaration."
    l1, l5 = generate(tmp_path, old + "\n" + new)
    rows = pin_rows(l1)
    assert [r.get("min_typ_max") for r in rows] == [{"typ": 2.0, "min": 1.98, "max": 2.02}]
    assert rows[0]["replaced_declarations"][0]["evidence"]["quote"] == old
    assert block_rows(l5) == rows


def test_conflicting_current_declarations_are_named_refusal(tmp_path):
    text = "The sense_a pin is driven by an external reference, 2.0 V +/- 5%.\nThe sense_a pin is driven by an external reference, 2.0 V +/- 1%."
    with pytest.raises(ValueError, match="PIN_INTERFACE_CONDITION_CONFLICT.*sense_a"):
        generate(tmp_path, text)


def test_unconsumed_pin_has_l1_only(tmp_path):
    l1, l5 = generate(tmp_path, "The sense_b pin is driven by an external reference, 3.0 V +/- 1%.")
    assert [r.get("min_typ_max") for r in pin_rows(l1, "sense_b")] == [{"typ": 3.0, "min": 2.97, "max": 3.03}]
    assert block_rows(l5) == []


@pytest.mark.parametrize("declaration", [
    "The `sense_a` pin is driven by an external reference, 2.0 V ± 0.04 V.",
    "The sense_a pin interface condition: 2.0 V +/- 0.04 V.",
])
def test_absolute_tolerance_and_labelled_condition(tmp_path, declaration):
    l1, l5 = generate(tmp_path, declaration)
    assert [r["min_typ_max"] for r in pin_rows(l1)] == [{"typ": 2.0, "min": 1.96, "max": 2.04}]
    assert "tolerance_percent" not in pin_rows(l1)[0]
    assert block_rows(l5) == pin_rows(l1)


def test_range_cannot_contradict_tolerance(tmp_path):
    with pytest.raises(ValueError, match="PIN_INTERFACE_CONDITION_CONFLICT"):
        generate(tmp_path, "The sense_a pin is driven by an external reference, 2.0 V +/- 1% (1.8 to 2.2 V).")


def test_all_and_only_declared_consuming_blocks(tmp_path):
    interface = INTERFACE + "\n## Block B — `opamp` : analog operational amplifier\n### opamp ports\n| Pin | Role |\n|---|---|\n| sense_a | input |\n"
    l1, l5 = generate(tmp_path, "The sense_a pin is driven by an external reference, 2.0 V +/- 1%.", interface)
    assert {b["name"] for b in l5["analog_blocks"] if b.get("spec", {}).get("input_conditions") == pin_rows(l1)} == {"pll", "opamp"}


@pytest.mark.parametrize("quantity", ["min 1.9 V, max 2.1 V", "1.9 to 2.1 V"])
def test_range_only_has_no_invented_nominal(tmp_path, quantity):
    l1, l5 = generate(tmp_path, "The pin `sense_a` is driven by an external reference, " + quantity + ".")
    assert [r["min_typ_max"] for r in pin_rows(l1)] == [{"min": 1.9, "max": 2.1}]
    assert block_rows(l5) == pin_rows(l1)



def test_input_condition_does_not_invent_an_output_target(tmp_path):
    interface = INTERFACE.replace("| fclk | 20 | 19–21 | MHz | output |", "")
    l1, l5 = generate(tmp_path, "The sense_a pin is driven by an external reference, 2.0 V +/- 1%.", interface)
    entry = next(b for b in l5["analog_blocks"] if b["name"] == "pll")
    rec = a1.emit_for_block(tmp_path, entry)
    assert rec["emitted"] is False
    gap = json.loads((tmp_path / rec["gap_path"]).read_text())
    assert gap["input_conditions"] == pin_rows(l1)
    assert not (tmp_path / "phase3/analog/pll/spec.json").exists()


@pytest.mark.parametrize("replacement", ["This supersedes the earlier declaration.", "This replaces the previous condition."])
def test_affirmative_replacement_keeps_shared_polarity_vocabulary(tmp_path, replacement):
    old = "The sense_a pin is driven by an external reference, 2.0 V +/- 5%."
    new = "The sense_a pin is driven by an external reference, 2.0 V +/- 1%. " + replacement
    l1, l5 = generate(tmp_path, old + "\n" + new)
    rows = pin_rows(l1)
    assert [r["min_typ_max"] for r in rows] == [{"typ": 2.0, "min": 1.98, "max": 2.02}]
    assert rows[0]["replaced_declarations"][0]["evidence"]["quote"] == old
    assert replacement in rows[0]["replacement_evidence"]["quote"]
    assert block_rows(l5) == rows


@pytest.mark.parametrize("heading", ["Proposal", "Draft interface", "Tentative conditions"])
def test_uncertain_parent_heading_never_lends_current_authority(tmp_path, heading):
    l1, l5 = generate(tmp_path, "# " + heading + "\n## Electrical details\nThe sense_a pin is driven by an external reference, 2.0 V +/- 2%.")
    assert pin_rows(l1) == block_rows(l5) == []



def test_replacement_attaches_to_the_nearest_declaration_on_the_same_line(tmp_path):
    text = ("The sense_a pin is driven by an external reference, 2.0 V +/- 5%. "
            "The sense_a pin is driven by an external reference, 2.0 V +/- 1%. "
            "This replaces the earlier declaration.")
    l1, l5 = generate(tmp_path, text)
    rows = pin_rows(l1)
    assert [r["min_typ_max"] for r in rows] == [{"typ": 2.0, "min": 1.98, "max": 2.02}]
    assert rows[0]["replaced_declarations"][0]["tolerance_percent"] == 5.0
    assert block_rows(l5) == rows
