"""Regression for #3462: preserve explicit L2 duplex bindings."""
from __future__ import annotations

import json
from pathlib import Path

from programs import phase1_doc_one_shot_runner as producer


_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "phase1_local"
    / "neutral_explicit_full_duplex_l2"
    / "interface_decisions.md"
)


def _emit(tmp_path: Path, name: str, text: str, filename: str = "input.md") -> dict:
    result = producer.gen_l2_frs(tmp_path / name, {filename: text})
    return json.loads(result.path.read_text(encoding="utf-8"))


def test_explicit_false_binding_reaches_protocol_overview(tmp_path):
    doc = _emit(tmp_path, "false", _FIXTURE.read_text(encoding="utf-8"),
                "interface_decisions.md")
    actual = (doc["protocol_overview"], doc["no_protocol_overview_in_input"])
    assert actual == ({
        "half_duplex": False,
        "wire_count": None,
        "byte_order": None,
        "wake_required_pre_command": None,
        "evidence": (
            "explicit protocol_overview.half_duplex=false binding in "
            "input/docs/interface_decisions.md"
        ),
    }, False)


def test_explicit_true_binding_is_symmetric(tmp_path):
    doc = _emit(
        tmp_path,
        "true",
        "# Interface topology\n"
        "The command interface has separate receive and transmit phases.\n"
        "Explicitly set `protocol_overview.half_duplex` to `true`.\n",
    )
    actual = (doc["protocol_overview"], doc["no_protocol_overview_in_input"])
    assert actual == ({
        "half_duplex": True,
        "wire_count": None,
        "byte_order": None,
        "wake_required_pre_command": None,
        "evidence": (
            "explicit protocol_overview.half_duplex=true binding in "
            "input/docs/input.md"
        ),
    }, False)


def test_conflicting_explicit_bindings_fail_closed(tmp_path):
    doc = _emit(
        tmp_path,
        "conflict",
        "# Interface topology\n"
        "Set `protocol_overview.half_duplex` to `true`.\n"
        "Set `protocol_overview.half_duplex` to `false`.\n",
    )
    assert doc["protocol_overview"] is None
    assert doc["no_protocol_overview_in_input"] is False
    conflicts = doc["extraction_evidence"].get(
        "protocol_overview.explicit_half_duplex_conflict", [])
    assert conflicts and "true" in conflicts[0]["literal"]
    assert "false" in conflicts[0]["literal"]


def test_negated_binding_is_not_selected(tmp_path):
    doc = _emit(
        tmp_path,
        "negated",
        "# Design note\nDo not set `protocol_overview.half_duplex` to `false`.\n",
        "design_note.md",
    )
    assert doc["protocol_overview"] is None


def test_no_protocol_reverse_control_stays_absent(tmp_path):
    doc = _emit(
        tmp_path,
        "absent",
        "# Functional overview\nThe accelerator transforms one data block.\n",
        "functional_overview.md",
    )
    assert doc["protocol_overview"] is None
    assert doc["no_protocol_overview_in_input"] is True
