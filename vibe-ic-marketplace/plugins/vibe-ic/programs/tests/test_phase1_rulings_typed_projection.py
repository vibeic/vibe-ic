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
