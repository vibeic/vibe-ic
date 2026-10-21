"""Regression for #3464: negative status text is not semantic carriage."""
from __future__ import annotations

import json
from pathlib import Path

from programs import phase1_expert_parse_track as track


def _project(tmp_path: Path, l3: dict) -> tuple[Path, Path]:
    project = tmp_path
    generated = project / "phase1" / "generated_docs"
    generated.mkdir(parents=True)
    l2 = generated / "L2_FRS.json"
    l2.write_text(json.dumps({
        "protocol_overview": None,
        "no_protocol_overview_in_input": False,
    }))
    (generated / "L3_CMD_PROTOCOL.json").write_text(json.dumps(l3))
    # Keep the breadth floor meaningful: one hit across five searched layers
    # is discriminating and therefore cannot be refused as corpus-wide.
    for stem in ("L4_REGMAP", "L5_ADI_SPEC", "L6_CONTROL_LOGIC",
                 "L7_TEST_DEBUG"):
        (generated / f"{stem}.json").write_text(json.dumps({
            "content": "unrelated",
        }))
    return project, l2


def test_negative_diagnostic_and_absence_flag_do_not_own_fact(tmp_path):
    project, addressed = _project(tmp_path, {
        "opcodes": [],
        "opcode_synthesis_skipped_reason": (
            "L2.protocol_overview.half_duplex is not True and no explicit "
            "opcode heading was found."
        ),
        "no_opcode_names_in_input": False,
    })

    ownership = track.owning_layers_answer(
        project, ["half_duplex", "false"], exclude=addressed)
    assert ownership["status"] == "OK"
    assert ownership["layers"] == []

    carriage = track.token_carriage(
        project, ["half_duplex", "false"], exclude=addressed)
    assert carriage["verdict"] == track.CARRIAGE_NOWHERE
    assert carriage["tokens_in_no_layer"] == ["false", "half_duplex"]


def test_real_semantic_boolean_field_remains_positive_carriage(tmp_path):
    project, addressed = _project(tmp_path, {
        "protocol_topology": {"half_duplex": False},
    })

    ownership = track.owning_layers_answer(
        project, ["half_duplex", "false"], exclude=addressed)
    assert ownership["layers"] == ["L3_CMD_PROTOCOL"]

    carriage = track.token_carriage(
        project, ["half_duplex", "false"], exclude=addressed)
    assert carriage["verdict"] == track.CARRIAGE_NAMED_FIELD
    assert carriage["per_token"]["false"]["named"] == {
        "L3_CMD_PROTOCOL": ["protocol_topology.half_duplex"]
    }


def test_nested_negative_status_fields_are_excluded(tmp_path):
    project, addressed = _project(tmp_path, {
        "analysis": {
            "binding_refusal": "half_duplex false was not established",
            "no_binding_in_input": False,
        }
    })
    ownership = track.owning_layers_answer(
        project, ["half_duplex", "false"], exclude=addressed)
    assert ownership["layers"] == []
    carriage = track.token_carriage(
        project, ["half_duplex", "false"], exclude=addressed)
    assert carriage["verdict"] == track.CARRIAGE_NOWHERE


def test_unrelated_false_does_not_render_a_whole_fact_owner_claim(tmp_path):
    project, addressed = _project(tmp_path, {
        "unrelated_feature_enabled": False,
    })
    carriage = track.token_carriage(
        project, ["half_duplex", "false"], exclude=addressed)

    # Preserve #2150's published OR-over-token machine record while making
    # its human-facing conclusion state the missing half of the match.
    assert carriage["verdict"] == track.CARRIAGE_NAMED_FIELD
    assert carriage["tokens_carried_elsewhere"] == ["false"]
    assert carriage["tokens_in_no_layer"] == ["half_duplex"]
    sentence = track.carriage_sentence(carriage)
    assert "only part of the fact" in sentence
    assert "does not establish that another layer owns the fact" in sentence
