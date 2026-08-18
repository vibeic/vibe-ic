"""Round-trip tests for L10/L11/L12/L13 rendering (v0.59 H1+H2).

v0.58 declared L10-L13 in schema.LAYER_FILE_NAMES but never:
  • shipped qbank YAML asking for the facts
  • added round-trip tests proving render works
  • aligned L13's filename with `hardware_pass_attestation_check.py`'s
    expected `L13_LAB_CALIBRATION.json` (v0.58 used `L13_HARDWARE_OBSERVED.json`)

This test file pins all three.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Add repo root to path so we can import tools.phase1_engine
_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO))

from tools.phase1_engine.schema import (  # noqa: E402
    Fact,
    FactGraph,
    LAYER_FILE_NAMES,
    Provenance,
)
from tools.phase1_engine.render import render_human_docs, render_layers  # noqa: E402


def _make_prov() -> Provenance:
    return Provenance(source="user_stated", origin="test")


def _add(graph: FactGraph, path: str, value, view: str) -> None:
    graph.facts.append(
        Fact(path=path, value=value, views=[view], provenance=_make_prov())
    )


# ---------------------------------------------------------------------------
# Filename alignment (H2)
# ---------------------------------------------------------------------------
def test_l13_filename_aligns_with_attestation_gate():
    """`hardware_pass_attestation_check.py` reads `L13_LAB_CALIBRATION.json`.
    The fact-graph render MUST write to the same filename or the gate
    silently fails with file-not-found. v0.58 shipped with the wrong
    name (`L13_HARDWARE_OBSERVED.json`); v0.59 H2 fixed it."""
    assert LAYER_FILE_NAMES["L13"] == "L13_LAB_CALIBRATION.json"


def test_all_extension_layer_filenames_known():
    for code in ("L10", "L11", "L12", "L13"):
        assert code in LAYER_FILE_NAMES
        assert LAYER_FILE_NAMES[code].endswith(".json")


# ---------------------------------------------------------------------------
# L10 — TEST_CASES
# ---------------------------------------------------------------------------
def test_l10_renders_test_cases_list(tmp_path):
    g = FactGraph(ic_name="X", class_path="cable-side-id-ic")
    _add(g, "L10.test_cases[0].id", "TC01_GET_ID", "L10")
    _add(g, "L10.test_cases[0].category", "cmd_response", "L10")
    _add(g, "L10.test_cases[0].cmd_hex", "70", "L10")
    _add(g, "L10.test_cases[0].expected_rsp_hex",
         "F2 02 02 02 02 02 BE AB BA D1 FA", "L10")
    _add(g, "L10.test_cases[1].id", "TC02_WAKE", "L10")
    _add(g, "L10.test_cases[1].category", "state_transition", "L10")

    out = render_layers(g, tmp_path)
    assert "L10" in out
    data = json.loads(out["L10"].read_text())
    assert isinstance(data["test_cases"], list)
    assert len(data["test_cases"]) == 2
    assert data["test_cases"][0]["cmd_hex"] == "70"
    assert data["test_cases"][1]["id"] == "TC02_WAKE"


# ---------------------------------------------------------------------------
# L11 — CALIBRATION
# ---------------------------------------------------------------------------
def test_l11_renders_calibration_tables(tmp_path):
    g = FactGraph(ic_name="X", class_path="cable-side-id-ic")
    _add(g, "L11.tables[0].name", "rx_window_us_to_cycles", "L11")
    _add(g, "L11.tables[0].domain_clock", "5MHz", "L11")
    _add(g, "L11.tables[0].source_clock", "absolute_us", "L11")
    _add(g, "L11.tables[0].scale_factor", 5.0, "L11")
    _add(g, "L11.tables[0].entries[0].name", "bit0_min", "L11")
    _add(g, "L11.tables[0].entries[0].value_us", 0.6, "L11")

    out = render_layers(g, tmp_path)
    data = json.loads(out["L11"].read_text())
    assert data["tables"][0]["domain_clock"] == "5MHz"
    assert data["tables"][0]["scale_factor"] == 5.0
    # Nested entries[] survive the round-trip
    assert data["tables"][0]["entries"][0]["name"] == "bit0_min"


# ---------------------------------------------------------------------------
# L12 — BEHAVIORAL_SEQUENCES
# ---------------------------------------------------------------------------
def test_l12_renders_sequences_with_categories(tmp_path):
    g = FactGraph(ic_name="X", class_path="cable-side-id-ic")
    _add(g, "L12.sequences[0].id", "ENGR_MODE_UNLOCK", "L12")
    _add(g, "L12.sequences[0].category", "validation_chain", "L12")
    _add(g, "L12.sequences[0].description", "Two-byte 0x74 0x74 unlock", "L12")
    _add(g, "L12.sequences[0].steps[0].action", "send_byte", "L12")
    _add(g, "L12.sequences[0].steps[0].args", "0x74", "L12")
    _add(g, "L12.sequences[0].steps[1].action", "send_byte", "L12")
    _add(g, "L12.sequences[0].steps[1].args", "0x74", "L12")

    out = render_layers(g, tmp_path)
    data = json.loads(out["L12"].read_text())
    assert data["sequences"][0]["category"] == "validation_chain"
    # Both steps survive
    assert len(data["sequences"][0]["steps"]) == 2
    assert data["sequences"][0]["steps"][1]["args"] == "0x74"


# ---------------------------------------------------------------------------
# L13 — LAB_CALIBRATION (Phase-1 contract part)
# ---------------------------------------------------------------------------
def test_l13_renders_phase1_contract(tmp_path):
    """Phase-1 fills only the contract block; evidence stays empty
    until Phase 2b real-hardware testing."""
    g = FactGraph(ic_name="X", class_path="analog-front-end")
    _add(g, "L13.criterion", "monotonic_adc_sweep", "L13")
    _add(g, "L13.criterion_params.min_samples", 5, "L13")
    _add(g, "L13.tester", "Keysight 3458A bench rig", "L13")

    out = render_layers(g, tmp_path)
    assert out["L13"].name == "L13_LAB_CALIBRATION.json"
    data = json.loads(out["L13"].read_text())
    assert data["criterion"] == "monotonic_adc_sweep"
    assert data["criterion_params"]["min_samples"] == 5
    assert data["tester"] == "Keysight 3458A bench rig"
    # Phase 1 should NOT pretend to have evidence
    assert "known_pass_bitstream" not in data
    assert "known_pass_transcript" not in data


def test_l13_supports_all_5_criterion_types(tmp_path):
    """Each of the 5 v0.56 B4 criteria must render cleanly."""
    for crit in ("distinct_non_padding_bytes", "monotonic_adc_sweep",
                 "memory_readback_match", "register_write_read_roundtrip",
                 "comparator_alert_on_threshold"):
        g = FactGraph(ic_name="X", class_path="any-ic")
        _add(g, "L13.criterion", crit, "L13")
        _add(g, "L13.tester", "stub", "L13")
        out = render_layers(g, tmp_path / crit)
        data = json.loads(out["L13"].read_text())
        assert data["criterion"] == crit


# ---------------------------------------------------------------------------
# Cross-layer rendering — all 4 extension layers in one call
# ---------------------------------------------------------------------------
def test_all_l10_l13_render_in_one_call(tmp_path):
    g = FactGraph(ic_name="X", class_path="cable-side-id-ic")
    _add(g, "L10.test_cases[0].id", "TC01", "L10")
    _add(g, "L11.tables[0].name", "tab1", "L11")
    _add(g, "L12.sequences[0].id", "SEQ1", "L12")
    _add(g, "L13.criterion", "distinct_non_padding_bytes", "L13")
    out = render_layers(g, tmp_path)
    for code in ("L10", "L11", "L12", "L13"):
        assert code in out, f"L*.json not written for {code}"
        assert out[code].exists()


# ---------------------------------------------------------------------------
# Layer isolation — L10 fact does NOT leak into L11/L12/L13 file
# ---------------------------------------------------------------------------
def test_l10_fact_does_not_leak_to_other_layers(tmp_path):
    g = FactGraph(ic_name="X", class_path="cable-side-id-ic")
    _add(g, "L10.test_cases[0].cmd_hex", "70", "L10")
    out = render_layers(g, tmp_path)
    # Only L10 file should exist when only L10 facts are present
    assert "L10" in out
    for absent in ("L11", "L12", "L13"):
        assert absent not in out


# ---------------------------------------------------------------------------
# v0.60 R1 — render_human_docs
# ---------------------------------------------------------------------------
def test_human_docs_emit_one_md_per_layer(tmp_path):
    g = FactGraph(ic_name="X", class_path="cable-side-id-ic")
    _add(g, "L1.ic_name", "X", "L1")
    _add(g, "L3.commands[0].opcode", "0x70", "L3")
    _add(g, "L13.criterion", "distinct_non_padding_bytes", "L13")
    md = render_human_docs(g, tmp_path)
    assert sorted(p.name for p in md.values()) == [
        "L13_LAB_CALIBRATION.md",
        "L1_DATASHEET.md",
        "L3_CMD_PROTOCOL.md",
    ]


def test_human_docs_filenames_mirror_json(tmp_path):
    """Each .md must share the JSON's stem (so reviewers can pair them)."""
    g = FactGraph(ic_name="X", class_path="cable-side-id-ic")
    _add(g, "L1.ic_name", "X", "L1")
    _add(g, "L8R.clock_frequency_hz", 5000000, "L8R")
    _add(g, "L13.tester", "rig", "L13")
    out = tmp_path
    json_paths = render_layers(g, out / "json")
    md_paths = render_human_docs(g, out / "md")
    for code in json_paths:
        assert code in md_paths, f"missing md for {code}"
        assert json_paths[code].stem == md_paths[code].stem


def test_human_docs_include_title_and_provenance_header(tmp_path):
    g = FactGraph(ic_name="MyIC", class_path="analog-front-end")
    _add(g, "L1.ic_name", "MyIC", "L1")
    md = render_human_docs(g, tmp_path)
    text = md["L1"].read_text()
    assert text.startswith("# L1 — Datasheet")
    # Provenance header line names IC + class + JSON source-of-truth
    assert "MyIC" in text
    assert "analog-front-end" in text
    assert "L1_DATASHEET.json" in text


def test_human_docs_render_nested_dict_as_indented_bullets(tmp_path):
    g = FactGraph(ic_name="X", class_path="cable-side-id-ic")
    _add(g, "L1.electrical_characteristics.supply_vbus.typ", 5.0, "L1")
    _add(g, "L1.electrical_characteristics.supply_vbus.unit", "V", "L1")
    md = render_human_docs(g, tmp_path)
    text = md["L1"].read_text()
    assert "**electrical_characteristics**" in text
    assert "**supply_vbus**" in text
    assert "**typ**: 5.0" in text


def test_human_docs_render_list_of_dicts_as_indexed(tmp_path):
    g = FactGraph(ic_name="X", class_path="cable-side-id-ic")
    _add(g, "L3.commands[0].opcode", "0x70", "L3")
    _add(g, "L3.commands[0].name", "GET_ID", "L3")
    _add(g, "L3.commands[1].opcode", "0x72", "L3")
    md = render_human_docs(g, tmp_path)
    text = md["L3"].read_text()
    assert "_0_" in text
    assert "_1_" in text
    assert "**opcode**: 0x70" in text


def test_human_docs_skip_empty_layers(tmp_path):
    """Layers with no facts shouldn't get an empty .md."""
    g = FactGraph(ic_name="X", class_path="cable-side-id-ic")
    _add(g, "L1.ic_name", "X", "L1")
    md = render_human_docs(g, tmp_path)
    assert "L1" in md
    assert "L2" not in md
    assert "L13" not in md
