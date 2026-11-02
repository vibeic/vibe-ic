"""Neutral source documents exercise the Phase-1 extractor boundaries."""
import json
from pathlib import Path

import pytest

import phase1_doc_one_shot_runner as runner


@pytest.mark.parametrize("declaration", [
    "Top module name: **`example_shell`**",
    "The top-level module is named `example_shell`.",
    "The module `example_shell` exposes input `enable_i`.",
])
def test_module_declaration_is_not_a_pin(declaration):
    text = ("# External Interface\n\n" + declaration + "\n"
            "- Input `enable_i`.\n- Output `result_o`.\n")
    pins = runner._v455_interface_pins({"interface.md": text})
    assert {pin["name"] for pin in pins} == {"enable_i", "result_o"}


def test_real_pin_can_share_a_module_spelling():
    text = ("# External Interface\n\nTop module name: `example_shell`\n"
            "- Input `example_shell`.\n")
    pins = runner._v455_interface_pins({"interface.md": text})
    assert [(pin["name"], pin["mode"]) for pin in pins] == [
        ("example_shell", "input")]


@pytest.mark.parametrize("statement,low_confidence", [
    ("The analog section contains six copies of the PLL at 1.8 V.", False),
    ("The analog section contains 6 identical copies of the PLL at 1.8 V.", False),
    ("The analog section contains six PLL blocks at 1.8 V.", False),
    ("The analog section contains 6x PLL at 1.8 V.", False),
    ("The analog PLL at 1.8 V supports six operating modes.", True),
    ("The analog section might contain six copies of the PLL at 1.8 V.", True),
])
def test_multiplicity_confidence_follows_source(tmp_path, statement, low_confidence):
    source = tmp_path / "input/docs/overview.md"
    source.parent.mkdir(parents=True)
    source.write_text(statement)
    emitted = runner.gen_l5_adi_spec(tmp_path, {source.name: statement})
    l5 = json.loads(Path(emitted.path).read_text())
    l9 = {}
    runner._v1_6_403_mirror_analog_multiplicity_to_l9(l5, l9)
    row = next(row for row in l9.get("submodules", []) if row["name"] == "pll")
    assert row["instance_count"] == 6
    assert row["multiplicity_evidence"]["low_confidence"] is low_confidence
    assert row["low_confidence"] is True  # Count evidence supplies no port contract.


def test_count_without_evidence_remains_low_confidence():
    l9 = {}
    runner._v1_6_403_mirror_analog_multiplicity_to_l9(
        {"analog_blocks": [{"type": "pll", "count": 6, "low_confidence": False}]}, l9)
    assert l9["submodules"][0]["low_confidence"] is True


def test_authoritative_heading_preserves_count_evidence():
    blocks = [{"type": "pll", "count": None}]
    docs = {"blocks.md": "## Block A - PLL (×6)\n"}
    runner._v466_apply_block_layer_multiplicity(blocks, docs)
    l9 = {}
    runner._v1_6_403_mirror_analog_multiplicity_to_l9({"analog_blocks": blocks}, l9)
    row = l9["submodules"][0]
    assert (row["instance_count"], row["low_confidence"]) == (6, True)
    assert row["multiplicity_evidence"]["low_confidence"] is False


def test_count_only_declaration_preserves_interface_audit_warning(tmp_path):
    import integration_spec_audit as consumer
    text = ("# Neutral analog unit\n## External Interface\n"
            "Top module name: `neutral_shell`\n"
            "| Signal | Direction | Width | Description |\n|---|---|---|---|\n"
            "| enable_i | input | 1 | digital input |\n"
            "| result_o | output | 1 | digital output |\n## Analog contract\n"
            "The analog section contains six copies of the PLL at 1.8 V.\n")
    source = tmp_path / "input/docs/contract.md"
    source.parent.mkdir(parents=True)
    source.write_text(text)
    docs = {source.name: text}
    runner.gen_l1_datasheet(tmp_path, docs)
    l5 = json.loads(Path(runner.gen_l5_adi_spec(tmp_path, docs).path).read_text())
    result = runner.gen_l9_integration_spec(tmp_path, docs, {})
    l9 = json.loads(Path(result.path).read_text())
    runner._v1_6_403_mirror_analog_multiplicity_to_l9(l5, l9)
    Path(result.path).write_text(json.dumps(l9))
    row = next(row for row in l9["submodules"] if row["name"] == "pll")
    assert row["instance_count"] == 6
    assert row["multiplicity_evidence"]["low_confidence"] is False
    assert row["low_confidence"] is True
    assert not row.get("ports")
    audit = consumer.audit(str(tmp_path))
    assert audit.passed
    assert [f.severity for f in audit.findings if f.rule == "INVALID_SUBMODULE"] == ["WARNING"]


@pytest.mark.parametrize("emitter", [
    runner.gen_l8_timing_waveform, runner.gen_l8_timing_waveform_doc])
@pytest.mark.parametrize("relationship", ["asynchronous", "exclusive", "synchronous"])
def test_declared_clock_groups_are_emitted(tmp_path, emitter, relationship):
    quote = f"| clock_group_1 | compute_clk_i, fabric_clk_i and service_clk_i | {relationship} |"
    text = "| Group | Clocks | Relationship |\n|---|---|---|\n" + quote + "\n"
    source = tmp_path / "input/docs/timing.md"
    source.parent.mkdir(parents=True)
    source.write_text(text)
    emitted = emitter(tmp_path, {source.name: text})
    l8 = json.loads(Path(emitted.path).read_text())
    groups = l8.get("clock_groups", [])
    assert groups == [{
        "name": "clock_group_1",
        "clocks": ["compute_clk_i", "fabric_clk_i", "service_clk_i"],
        "relationship": relationship,
        "evidence": {"doc": "input/docs/timing.md", "line": 3, "quote": quote}}]


def test_clock_relationship_table_is_emitted(tmp_path):
    text = ("# Timing contract\n\n"
            "| Group | Clocks | Relationship |\n|---|---|---|\n"
            "| peripheral | `io_clk_i`, `bus_clk_i` | asynchronous |\n")
    emitted = runner.gen_l8_timing_waveform(tmp_path, {"timing.md": text})
    groups = json.loads(Path(emitted.path).read_text()).get("clock_groups", [])
    assert groups == [{"name": "peripheral", "clocks": ["io_clk_i", "bus_clk_i"],
                       "relationship": "asynchronous", "evidence": {
                           "doc": "input/docs/timing.md", "line": 5,
                           "quote": text.splitlines()[4]}}]


@pytest.mark.parametrize("text", [
    "The clocks `compute_clk_i` and `service_clk_i` run independently.\n",
    "Clock group `compute`: `compute_clk_i`, `service_clk_i`.\n",
    "compute_clk_i and service_clk_i are not asynchronous.\n",
    "compute_clk_i and service_clk_i might be asynchronous.\n",
    "compute_clk_i and service_clk_i are asynchronous?\n",
    "compute_clk_i and service_clk_i have asynchronous reset.\n",
    "# Historical comparison\ncompute_clk_i and service_clk_i are asynchronous.\n",
])
def test_clock_mentions_do_not_declare_a_group(tmp_path, text):
    emitted = runner.gen_l8_timing_waveform(tmp_path, {"timing.md": text})
    l8 = json.loads(Path(emitted.path).read_text())
    assert l8.get("clock_groups", []) == []
