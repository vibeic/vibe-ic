"""Neutral input documents exercise explicit cross-layer projections."""
import json
from pathlib import Path
import pytest

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


def test_return_column_binds_each_power_domain_ground(tmp_path):
    import l21_doc_supply_rail_synth as supplies
    source(tmp_path, "# Supplies\n| Rail | Level | Return |\n|---|---|---|\n"
           "| power_a | 1.4 V | return_a |\n| power_b | 1.2 V | return_b |\n")
    rails = supplies.derive(tmp_path)["rails"]
    assert {r["rail"]: r.get("ground_net") for r in rails} == {
        "power_a": "return_a", "power_b": "return_b"}
    runner._emit_l19_to_l23_skeletons(tmp_path)
    assert supplies.main([str(tmp_path), "--apply"]) == 0
    payload = json.loads((tmp_path / "phase1/generated_docs/L21_POWER_INTENT.json").read_text())
    rows = payload.get("fields", payload)["power_domains"]
    assert {r["name"]: r["ground_net"] for r in rows} == {
        "power_a": "return_a", "power_b": "return_b"}
    assert all(r["ground_evidence"]["file"].endswith("L9_constraints.md") for r in rows)


def test_no_external_reset_and_por_start_are_typed_in_l8_l9(tmp_path):
    docs = source(tmp_path, "# Current startup\nThere is no external reset. "
                  "POR initializes the accumulators and tracking latches.\n")
    outputs = [runner.gen_l8_timing_waveform(tmp_path, docs),
               runner.gen_l8_timing_waveform_doc(tmp_path, docs),
               runner.gen_l9_integration_spec(tmp_path, docs, {})]
    for output in outputs:
        payload = json.loads(Path(output.path).read_text())
        strategy = payload.get("reset_strategy", {})
        assert (strategy.get("external_reset"), strategy.get("startup_source")) == (False, "power_on_reset")
        assert strategy["initializes"] == ["accumulators", "tracking latches"]
        assert strategy["evidence"][0]["line"] == 2
        assert strategy["evidence"][0]["doc"] == "input/docs/L9_constraints.md"
    content = {"clock_domains": [{"name": "clk_i", "reset_strategy": "unspecified"}]}
    runner._apply_declared_por_reset_strategy(content, docs)
    assert content["clock_domains"][0]["reset_strategy"] == "power_on_reset"


@pytest.mark.parametrize("claim", [
    "It is not true that POR initializes the accumulators.",
    "Perhaps POR initializes the accumulators.",
    "If POR initializes the accumulators, startup may proceed.",
])
def test_denied_or_uncertain_por_does_not_assert_reset_strategy(tmp_path, claim):
    docs = source(tmp_path, "# Current startup\nThere is no external reset. " + claim + "\n")
    for output in (runner.gen_l8_timing_waveform(tmp_path, docs),
                   runner.gen_l8_timing_waveform_doc(tmp_path, docs),
                   runner.gen_l9_integration_spec(tmp_path, docs, {})):
        payload = json.loads(Path(output.path).read_text())
        assert payload.get("reset_strategy") is None
    content = {"clock_domains": [{"name": "clk_i", "reset_strategy": "unspecified"}]}
    runner._apply_declared_por_reset_strategy(content, docs)
    assert content == {"clock_domains": [{"name": "clk_i", "reset_strategy": "unspecified"}]}
