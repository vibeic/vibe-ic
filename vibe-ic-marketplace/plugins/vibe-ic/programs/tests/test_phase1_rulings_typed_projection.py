"""Neutral input documents exercise explicit cross-layer projections."""
import json
from pathlib import Path

import phase1_doc_one_shot_runner as runner
import l9_l19_contract_carrythrough as carry


def source(tmp_path, text, name="L9_constraints.md"):
    path = tmp_path / "input/docs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return {name: text}


def test_seal_ring_geometry_has_typed_placement_and_approximation(tmp_path):
    source(tmp_path, "# Current geometry\nThe seal ring lies outside this die.\n"
           "| Field | Value |\n|---|---|\n| With seal ring | ~920 × 940 µm |\n")
    value = carry._l19_contract(tmp_path, carry._source_documents(tmp_path), {})
    ring = value.get("tapeout_geometry", {}).get("seal_ring", {})
    assert (ring.get("placement"), ring.get("outer_envelope_um"), ring.get("approximate")) == (
        "outside", {"width": 920.0, "height": 940.0}, True)
    assert {row["line"] for row in ring["evidence"]} == {2, 5}
    assert all(row["doc"] == "input/docs/L9_constraints.md" for row in ring["evidence"])


def test_block_device_class_is_typed_and_mirrored_to_l22(tmp_path):
    import l22_analog_verification_plan_emit as plan
    docs = source(tmp_path, "# Analog constraint\nAn analog LDO operates at 2.7 V.\n"
                  "HV devices (`neutral_hv_*`) for the 2.7 V LDO pass path.\n")
    result = runner.gen_l5_adi_spec(tmp_path, docs)
    blocks = json.loads(Path(result.path).read_text())["analog_blocks"]
    block = next(row for row in blocks if row["type"] == "ldo")
    constraints = block.get("device_class_constraints", [])
    assert [(c["device_class"], c["model_pattern"], c["voltage_v"]) for c in constraints] == [
        ("HV", "neutral_hv_*", 2.7)]
    assert constraints[0]["evidence"]["line"] == 3
    mirrored = next(row for row in plan._plan("ldo", blocks, [])["analog"] if row["block_type"] == "ldo")
    assert mirrored["device_class_constraints"] == constraints


def test_pad_order_by_side_retains_source_sequence(tmp_path):
    source(tmp_path, "# Pad placement\n"
           "Pads go counterclockwise from the SW corner and face outward. South is W→E; east is S→N.\n"
           "south: power_a, return_a.\neast: sense_b, sense_a.\n"
           "north: clock_b, clock_a.\nwest: input_b, input_a.\n")
    value = carry._l19_contract(tmp_path, carry._source_documents(tmp_path), {})
    order = value["pad_order_by_side"]
    assert order.get("south") == ["power_a", "return_a"]
    assert order["east"] == ["sense_b", "sense_a"]
    assert order["north"] == ["clock_b", "clock_a"]
    assert order["west"] == ["input_b", "input_a"]
    assert (order["traversal"], order["start_corner"], order["facing"]) == ("counterclockwise", "SW", "outward")
    assert order["side_directions"]["south"] == ["W", "E"]
    assert len(order["evidence"]) == 5


def test_instance_table_projects_supplies_without_clock_binding(tmp_path):
    docs = source(tmp_path, "# Neutral unit\n## External Interface\n"
                  "| Signal | Direction | Width |\n|---|---|---|\n"
                  "| rail_a | input | 1 |\n| common | inout | 1 |\n"
                  "## Instance allocations\n"
                  "| Instance | L5 block | Core supply | Ground | Clock |\n|---|---|---|---|---|\n"
                  "| copy_one | pll | rail_a | common | owner_clock |\n")
    runner.gen_l1_datasheet(tmp_path, docs)
    result = runner.gen_l9_integration_spec(tmp_path, docs, {})
    l9 = json.loads(Path(result.path).read_text())
    rows = l9.get("instances", [])
    assert [(r["name"], r["block_type"], r["power_net"], r["ground_net"]) for r in rows] == [
        ("copy_one", "pll", "rail_a", "common")]
    assert not {"clock", "clock_pin", "clock_binding"} & set(rows[0])
    assert rows[0]["evidence"]["quote"].startswith("| copy_one |")
    assert l9["no_internal_wires_in_input"] is True
