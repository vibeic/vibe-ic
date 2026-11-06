"""Neutral source-only A8 positional adapter and deck-consumer controls."""
import hashlib
import json

import pytest

import _analog_a8_extraction_wrapper as adapter
import analog_a8_hardmacro_emit as producer


RAW = """* Self-authored source control, not a PEX observation.
 .SUBCKT Coupler sense open_bulk
  + drive tail_a tail_b tail_c tail_d tail_e tail_f tail_g
Rkeep drive sense 19
Ckeep sense open_bulk 2p
 .ENDS COUPLER
"""


def test_adapter_preserves_native_order_and_open_nodes_through_actual_a8_deck(tmp_path):
    extracted = tmp_path / "neutral_extracted.spice"
    extracted.write_text(RAW)
    before = extracted.read_bytes()
    declared = ["Drive", "Sense"]

    text, mapping = adapter.build_wrapper(extracted.read_text(), "Coupler", declared)

    assert mapping["native_ports"] == ["sense", "open_bulk", "drive", "tail_a", "tail_b",
                                       "tail_c", "tail_d", "tail_e", "tail_f", "tail_g"]
    assert mapping["instance_nodes"] == ["Sense", "a8_rc_p0001", "Drive", "a8_rc_p0003",
                                         "a8_rc_p0004", "a8_rc_p0005", "a8_rc_p0006",
                                         "a8_rc_p0007", "a8_rc_p0008", "a8_rc_p0009"]
    assert len(set(mapping["instance_nodes"])) == len(mapping["native_ports"])
    instance = next(line.split() for line in adapter.logical_lines(text) if line.startswith("Xnative "))
    assert instance == ["Xnative", *mapping["instance_nodes"], "Coupler"]
    assert adapter.native_ports(text, mapping["wrapper_subckt"]) == declared
    assert not any(line.startswith(("R", "C", ".global")) for line in adapter.logical_lines(text))
    wrapper = tmp_path / "interface.spice"
    wrapper.write_text(text)
    block = tmp_path / "phase3/analog/Coupler"
    block.mkdir(parents=True)
    model = block / "declared.lib"
    model.write_text(".lib typ\n* transport-only model declaration\n.endl typ\n")
    (block / "Coupler.sp").write_text(f".lib {model} typ\n.subckt Coupler Drive Sense\n.ends Coupler\n")
    (block / "tb_Coupler.sp").write_text("* source stimulus\nVdrive Drive 0 1\nXDUT Drive 0 Coupler\n.end\n")
    docs = tmp_path / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"instances": [{"block": "Coupler", "ports": [
        {"name": "Drive", "direction": "input", "type": "power"},
        {"name": "Sense", "direction": "inout", "type": "ground"}]}]}))
    deck, _ = producer._delivered_measurement_deck(tmp_path, "Coupler", extracted, declared,
        mapping["wrapper_subckt"], {"ports": declared, "rails": {"vdd": "Drive", "vss": "Sense"}}, wrapper)
    assert f'.include "{extracted}"' in deck
    assert f'.include "{wrapper}"' in deck
    assert "Coupler__a8_interface" in next(line for line in deck.splitlines() if line.startswith("XU "))
    assert extracted.read_bytes() == before
    assert hashlib.sha256(before).hexdigest() == hashlib.sha256(extracted.read_bytes()).hexdigest()


@pytest.mark.parametrize("raw,reason", [
    (".subckt Cell a b\n", "unterminated subckt"),
    (".ends Cell\n", "unmatched subckt end"),
    (".subckt Cell a b\n.ends Other\n", "unmatched subckt end"),
    (".subckt Cell a b\n.subckt Child c d\n.ends\n.ends\n", "malformed/nested subckt header"),
    (".subckt Cell a b\n.ends\n.subckt CELL c d\n.ends\n", "duplicate/ambiguous subckt name"),
])
def test_header_parser_refuses_incomplete_or_ambiguous_hierarchy(raw, reason):
    with pytest.raises(ValueError, match=reason):
        adapter.subckt_headers(raw)


@pytest.mark.parametrize("change,reason", [
    ("duplicate_port", "duplicate/ambiguous port or node"),
    ("global", "global node collision"),
    ("missing_declared", "missing declared port"),
    ("wrapper_name", "wrapper/native subckt name collision"),
    ("unsupported_node", "missing/unsupported port or node token"),
])
def test_adapter_refuses_non_bijective_or_nonisolated_inputs(change, reason):
    raw, declared = RAW, ["Drive", "Sense"]
    if change == "duplicate_port":
        raw = raw.replace("open_bulk", "SENSE")
    elif change == "global":
        raw += ".global OPEN_BULK\n"
    elif change == "missing_declared":
        declared = ["Drive", "Absent"]
    elif change == "wrapper_name":
        raw += ".subckt coupler__a8_interface a b\n.ends\n"
    else:
        raw = raw.replace("open_bulk", "0")
    with pytest.raises(ValueError, match=reason):
        adapter.build_wrapper(raw, "Coupler", declared)


def test_exact_top_identity_is_required_while_spice_end_names_are_case_insensitive():
    assert adapter.subckt_headers(RAW)["Coupler"][0] == "sense"
    with pytest.raises(ValueError, match="no exact declared top-cell"):
        adapter.native_ports(RAW, "coupler")
