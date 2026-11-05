"""Contracts for sources consumed as raw text retain every source sentence."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _specrtl_common as common
import deterministic_emit_chain as chain


PULSE = """Module name:
    pulse_detect
Pulse detection: when data_in changes from 0 to 1 to 0 this is a pulse.
Input ports:
 clk: Clock.
 rst_n: Reset.
 data_in: One-bit input.
Output ports:
 data_out: pulse indicator.
"""
RESTRICTIONS = (
    "Every primitive in the final netlist has to be a Sheffer stroke.",
    "Build this out of Peirce arrows, and nothing else may appear.",
    "Keep the silicon footprint as tiny as you possibly can.",
    "Favour the cheapest realisation you can find over any readable form.",
    "Stick to a single kind of universal primitive throughout the design.",
)
KMAP = """Implement a module named TopModule.
 - input a
 - input b
 - output q
The module should implement the function shown in the Karnaugh map below.
       a
  b   0   1
  0 | 0 | 1 |
  1 | 1 | 0 |
"""
STRUCTURED = {
    "module": "selected_table",
    "ports": [{"name": "a", "direction": "input", "width": 1},
              {"name": "q", "direction": "output", "width": 1}],
    "inputs": [{"name": "a"}],
    "outputs": [{"name": "q"}],
    "rows": [{"in": "0", "out": "1"}, {"in": "1", "out": "0"}],
    "default": "0",
}










def test_raw_json_fields_do_not_create_a_structured_logic_authority():
    sentence = "Use only NAND gates."
    text = json.dumps({"module": "TopModule", "logic_obligations": [{
        "kind": "logic_basis", "family": ["nand"], "source_span": [0, len(sentence)],
        "source_sentence": sentence, "module": "TopModule"}]})
    contract = common.prose_emission_spec_contract(text, top="TopModule")
    assert contract.logic_obligations == []
    assert contract.source != "json"


@pytest.mark.parametrize("sentence", [
    "The testbench is only able to be compiled, nor are there any test entries.",
    "Only the build is supported; neither tests nor sequences are implemented.",
    "Only compilation is supported, no tests run nor any sequences exist.",
])
def test_prose_conjunction_does_not_declare_a_gate_basis(sentence):
    contract = common.prose_emission_spec_contract(PULSE + sentence, top="pulse_detect")
    assert contract.logic_obligations == []


@pytest.mark.parametrize("sentence", ["Use only NOR logic.",
                                      "Implement using only nor primitives.",
                                      "Use only nor gates.", "Use nor-only logic.",
                                      "Use only nor.",
                                      "Implement the circuit using nor exclusively.",
                                      "Neither clock nor reset is required; use only nor gates.",
                                      "Neither clock nor reset is required, use only nor gates."])
def test_explicit_nor_basis_remains_an_implementation_obligation(sentence):
    contract = common.prose_emission_spec_contract(PULSE + sentence, top="pulse_detect")
    assert [(row.kind, row.family) for row in contract.logic_obligations] == [
        ("logic_basis", ("nor",))]


def test_raw_prose_and_decoded_entry_share_typed_interface_obligation_override():
    def row(sentence, module):
        return {"kind": "logic_basis", "family": ["nand"],
                "source_span": [0, len(sentence)], "source_sentence": sentence,
                "module": module}

    interface = json.dumps({"module": "TopModule", "logic_obligations": [
        row("Use only NAND gates.", "TopModule"),
        row("Only NAND gates are allowed.", None),
        row("Implement using only NAND gates.", "OtherModule")]})
    raw = common.prose_emission_spec_contract(KMAP, interface, "TopModule")
    decoded = common.emission_spec_contract(KMAP, interface, "TopModule")
    assert [item.source_sentence for item in raw.logic_obligations] == [
        "Use only NAND gates.", "Only NAND gates are allowed."]
    assert raw.logic_obligations == decoded.logic_obligations
    assert len(common.unsupported_logic_obligations(raw)) == 2


def test_fully_accounted_kmap_keeps_the_raw_contract_and_direct_chain_rtl():
    raw = common.prose_emission_spec_contract(KMAP, top="TopModule")
    decoded = common.emission_spec_contract(KMAP, top="TopModule")
    assert raw == decoded
    assert raw.module == "TopModule"
    assert [(port.name, port.direction, port.width) for port in raw.ports] == [
        ("a", "input", 1), ("b", "input", 1), ("q", "output", 1)]
    kind, rtl, rejected = chain.try_emit_ex(KMAP, top="TopModule", check=False)
    assert kind == "karnaugh_map"
    assert "module TopModule" in rtl
    assert rejected == []


@pytest.mark.parametrize("codec", ["yaml", "json"])
def test_decoded_structured_contract_and_direct_chain_guard_remain_unchanged(codec):
    import yaml

    text = yaml.safe_dump(STRUCTURED) if codec == "yaml" else json.dumps(STRUCTURED)
    contract = common.emission_spec_contract(text)
    assert contract.source == "json"
    assert contract.module == "selected_table"
    assert [(port.name, port.direction, port.width) for port in contract.ports] == [
        ("a", "input", 1), ("q", "output", 1)]
    assert contract.logic_obligations == []
    assert chain.try_emit_ex(text, check=False) == (None, None, [])


@pytest.mark.parametrize("data, message", [
    ({"module": "bad", "ports": "input a"}, "invalid structured ports"),
    ({"module": "bad", "ports": [None]}, "invalid structured ports"),
    ({"module": "bad", "reset": "active low"}, "invalid structured reset"),
])
@pytest.mark.parametrize("codec", ["yaml", "json"])
def test_decoded_structured_malformed_guards_remain_named_failures(codec, data, message):
    import yaml

    text = yaml.safe_dump(data) if codec == "yaml" else json.dumps(data)
    with pytest.raises(ValueError, match=message):
        common.emission_spec_contract(text)
    kind, rtl, rejected = chain.try_emit_ex(text, check=False)
    assert kind is None and rtl is None
    assert rejected[0][0] == "DECLARED_LOGIC_OBLIGATION_INVALID"
    assert message in rejected[0][1][0]
