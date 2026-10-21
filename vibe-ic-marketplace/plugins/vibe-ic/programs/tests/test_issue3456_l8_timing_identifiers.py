"""Regression for #3456: L8 timing identifiers must come from bindings.

The real OpenTitan AES Phase-1 input used ordinary prose around timing
literals.  The inline harvester treated the preceding English word as a
constant name (``The 2 ns`` -> ``The``), while the bare-value harvester gave
every distinct value under one heading the same name.  These tests exercise
the public L8 producer and keep both reverse controls executable.
"""
from __future__ import annotations

import json
from pathlib import Path

from programs import phase1_doc_one_shot_runner as producer


_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "phase1_local"
    / "opentitan_aes_sky130a_l8_timing"
    / "timing_prose.md"
)


def _emit(tmp_path: Path, name: str, text: str) -> dict:
    project = tmp_path / name
    result = producer.gen_l8_timing_waveform_doc(
        project, {f"{name}_timing.md": text}
    )
    return json.loads(result.path.read_text(encoding="utf-8"))


def test_narrative_words_are_not_timing_identifiers(tmp_path):
    text = _FIXTURE.read_text(encoding="utf-8")
    doc = _emit(tmp_path, "narrative", text)

    assert doc["timing_windows"] == []
    constants = doc["timing_constants"]
    assert {row["value"] for row in constants} == {0.0, 2.0, 18.0, 20.0}
    names = [row["name"] for row in constants]
    assert len(names) == len(set(names)), names


def test_explicit_assignments_retain_exact_names(tmp_path):
    doc = _emit(
        tmp_path,
        "assigned",
        "# Proposed timing targets\n"
        "t_setup = 2 ns\n"
        "t_hold = 0 ns\n"
        "t_period = 20 ns\n",
    )

    assert {row["name"] for row in doc["timing_windows"]} == {
        "t_setup", "t_hold", "t_period"
    }
    constant_names = [row["name"] for row in doc["timing_constants"]]
    assert len(constant_names) == len(set(constant_names)), constant_names


def test_space_bound_structural_identifier_is_preserved(tmp_path):
    doc = _emit(
        tmp_path,
        "legacy_space_binding",
        "# Timing table\ntBR 9.4 us\ntREC 3.2 us\ntWAIT 1.1 us\n",
    )
    assert {row["name"] for row in doc["timing_windows"]} == {
        "tBR", "tREC", "tWAIT"
    }


def test_no_numeric_timing_emits_no_typed_records(tmp_path):
    doc = _emit(
        tmp_path,
        "reverse",
        "# Proposed timing targets\nNo numeric timing value is declared here.\n",
    )
    assert doc["timing_windows"] == []
    assert doc["timing_constants"] == []


def test_duplicate_max_length_name_keeps_unique_suffix():
    used: set[str] = set()
    base = "n" * 80
    assert producer._issue3456_unique_timing_name(base, used) == base
    second = producer._issue3456_unique_timing_name(base, used)
    assert second.endswith("_2")
    assert len(second) == 80
    assert second != base
