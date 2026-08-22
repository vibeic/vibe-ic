"""Unit tests for `analog_a2_topology_emit` — the A2 topology PRODUCER.

The A2 gate measures VOCABULARY, not structure: 200 bytes plus one
circuit-specific word. Several BLOCK NAMES are themselves in its panel
(`ldo`, `bandgap`, `oscillator`, `comparator`, `charge pump`), so a
content-free paragraph headed `# Topology - ldo` PASSES it. The first test
below therefore strips the block name out of the emitted document before
handing it to the gate: if the producer were leaning on the loophole, the
stripped copy would fail.
"""
from __future__ import annotations

import json

import pytest

from _analog_producer_fixture import (
    A1, A2, GATE_A2, PROGRAMS, block, make_project, run_prog, bdir, read_json)


def _emit(tmp_path, blocks):
    p = make_project(tmp_path, blocks)
    run_prog(A1, p)
    cp = run_prog(A2, p)
    return p, cp


# ── the substance floor, cleared on content and not on the name ───────────
def test_topology_md_clears_the_gate_with_the_block_name_removed(tmp_path):
    p, cp = _emit(tmp_path, [block("blk_alpha", "comparator")])
    assert cp.returncode == 0, cp.stderr
    md = bdir(p, "blk_alpha") / "topology.md"
    assert md.is_file()
    assert run_prog(GATE_A2, p, "--block", "blk_alpha").returncode == 0

    # Now prove the name is not what satisfied the gate.
    stripped = md.read_text(encoding="utf-8").replace("blk_alpha", "the block")
    q = make_project(tmp_path / "stripped", [block("blk_alpha", "comparator")])
    (q / "phase3/analog/blk_alpha").mkdir(parents=True, exist_ok=True)
    (q / "phase3/analog/blk_alpha/topology.md").write_text(stripped,
                                                           encoding="utf-8")
    gate = run_prog(GATE_A2, q, "--block", "blk_alpha")
    assert gate.returncode == 0, (
        "the document must describe a circuit on its own prose; with the "
        f"block name removed it no longer does: {gate.stdout}{gate.stderr}")


def test_topology_md_names_the_devices_and_their_function(tmp_path):
    p, _ = _emit(tmp_path, [block("blk_alpha", "comparator")])
    text = (bdir(p, "blk_alpha") / "topology.md").read_text(encoding="utf-8")
    for needed in ("NMOS transistor", "PMOS transistor", "Design trade-offs",
                   "Provenance"):
        assert needed in text, f"topology.md carries no `{needed}` section"


# ── the IR: the first real A2 -> A3 data path ─────────────────────────────
def test_topology_json_is_a_renderable_ir(tmp_path):
    p, _ = _emit(tmp_path, [block("vreg_alpha", "ldo",
                                  [{"name": "Vout", "target": 1.8,
                                    "unit": "V"}])])
    ir = read_json(bdir(p, "vreg_alpha") / "topology.json")
    assert ir["ir_schema"] >= 1
    assert ir["ports"] and ir["devices"]
    rails = set(ir["rails"].values())
    terms = ir["role_terminals"]
    for d in ir["devices"]:
        assert d["role"] in terms, d
        assert len(d["nets"]) == terms[d["role"]], (
            f"{d['name']} declares {len(d['nets'])} nets but its role takes "
            f"{terms[d['role']]}")
        if d["role"] == "pmos":
            assert d["nets"][-1] in rails and d["nets"][-1] == ir["rails"]["vdd"]
        if d["role"] == "nmos":
            assert d["nets"][-1] == ir["rails"]["vss"]
    # Every internal net must be visible to the connectivity checker, which
    # only parses X cards carrying >= 3 nets.
    visible = {}
    for d in ir["devices"]:
        if len(d["nets"]) >= 3:
            for n in d["nets"]:
                visible[n] = visible.get(n, 0) + 1
    for net in ir["internal_nets"]:
        assert visible.get(net, 0) >= 2, (
            f"internal net {net} would be reported FLOATING_NODE")


def test_the_ir_records_whether_a_spec_reached_the_topology(tmp_path):
    with_spec, _ = _emit(tmp_path / "a", [
        block("vreg_alpha", "ldo", [{"name": "Vout", "target": 1.8,
                                     "unit": "V"},
                                    {"name": "Vref", "target": 0.6,
                                     "unit": "V"}])])
    ir = read_json(bdir(with_spec, "vreg_alpha") / "topology.json")
    assert ir["selection_basis"] == "block_type_and_spec"
    assert ir["knob_sources"]["divider_ratio"] == "spec"
    assert ir["knobs"]["divider_ratio"] == pytest.approx(3.0)
    assert ir["_provenance"]["fields_defaulted"] == []

    without, _ = _emit(tmp_path / "b", [block("keeper_x", "pull")])
    ir2 = read_json(bdir(without, "keeper_x") / "topology.json")
    assert ir2["selection_basis"] == "block_type_only"
    assert ir2["design_inputs_bound"] == []
    md = (bdir(without, "keeper_x") / "topology.md").read_text()
    assert "No A1 spec was bound for this block" in md, (
        "a class-library topology must SAY that no number from this design "
        "entered it")


def test_a_library_default_is_recorded_as_a_default(tmp_path):
    """Vout alone cannot fix the feedback divider ratio. The producer must
    fall back AND say so, in both artefacts."""
    p, _ = _emit(tmp_path, [block("vreg_alpha", "ldo",
                                  [{"name": "Vout", "target": 1.8,
                                    "unit": "V"}])])
    ir = read_json(bdir(p, "vreg_alpha") / "topology.json")
    assert ir["knob_sources"]["divider_ratio"] == "library_default"
    assert ir["_provenance"]["fields_defaulted"] == ["divider_ratio"]
    assert ir["_provenance"]["defaults_used"] is True
    assert "library_default" in (bdir(p, "vreg_alpha")
                                 / "topology.md").read_text()


# ── THE HONEST ABSENCE ────────────────────────────────────────────────────
def test_a_class_the_library_does_not_carry_gets_NO_topology(tmp_path):
    p, cp = _emit(tmp_path, [block("widget_q", "charge_pump")])
    assert cp.returncode == 2, cp.stdout + cp.stderr
    d = bdir(p, "widget_q")
    assert not (d / "topology.md").exists(), (
        "emitting the nearest library topology under this block's name would "
        "read as a selection and be a substitution — and the A2 gate cannot "
        "tell them apart")
    assert not (d / "topology.json").exists()

    gap = read_json(d / "topology_gap.json")
    assert gap["status"] == "NO_TOPOLOGY_IN_LIBRARY"
    assert gap["topology_md_written"] is False
    assert gap["ai_handoff"]["skill"] == "analog-topology-select"
    assert gap["reason"] and gap["reason"] != gap["why_not_defaulted"]
    assert gap["library_types"], "the gap must name what the library DOES hold"

    assert run_prog(GATE_A2, p, "--block", "widget_q").returncode == 2


# ── constants are read, not retyped ───────────────────────────────────────
def test_the_process_constants_come_from_the_registry(tmp_path):
    reg = json.loads((PROGRAMS / "pdk_registry.json").read_text())
    fam = next(e for e in reg["pdks"] if e.get("analog_device_params"))
    params = fam["analog_device_params"]

    p, _ = _emit(tmp_path, [block("blk_alpha", "comparator")])
    md = (bdir(p, "blk_alpha") / "topology.md").read_text(encoding="utf-8")
    for key, val in params.items():
        if key == "note":
            continue
        assert f"`{key}`" in md and str(val) in md, (
            f"{key}={val} is declared in pdk_registry.json and does not "
            f"appear in the emitted topology.md — the document is quoting "
            f"process constants from somewhere else")


def test_a_topology_this_producer_did_not_write_is_never_overwritten(tmp_path):
    p = make_project(tmp_path, [block("blk_alpha", "comparator")])
    d = bdir(p, "blk_alpha")
    d.mkdir(parents=True, exist_ok=True)
    authored = ("# Topology\n\nA folded-cascode amplifier with an nmos "
                "input pair was selected by hand.\n" + "x" * 300)
    (d / "topology.md").write_text(authored)
    assert run_prog(A2, p).returncode == 0
    assert (d / "topology.md").read_text() == authored
