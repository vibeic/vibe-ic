#!/usr/bin/env python3
"""`spec.json:interface.pins[]` is a gate's declared golden source, and nothing
emitted it.

MEASURED. `analog_hardmacro_pinname_consistency_check` names
`analog/<block>/spec.json — interface.pins[].name` as the golden source it
compares LEF and Verilog against. The L5 block record carries the block's
PERFORMANCE and no pins, so `_interface` correctly declined to invent one, the
gate self-skipped having compared nothing that mattered, and two producers
derived the interface independently — the Phase-2 RTL blackbox from the doc
prose, the A2 topology emitter from its topology library. They disagreed about
every block, and the disagreement first surfaced at PnR as OpenROAD
`STA-0201 port not found`, after A8 had cleared ORD-2013 and not before.

The missing link is a DECLARATION, not a guess: a design that stages one gets
its own interface; a design that stages none still gets no `interface` key and
the gate still self-skips, exactly as before.

chip/PDK-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analog_a1_spec_emit as A  # noqa: E402


def _project(tmp_path: Path, submodules) -> Path:
    p = tmp_path / "proj"
    gd = p / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"submodules": submodules}))
    return p


def test_a_staged_declaration_supplies_the_port_list(tmp_path: Path):
    p = _project(tmp_path, [{"name": "blk", "ports": ["vdd", "vss", "a"]}])
    assert A._staged_interface_ports(p, "blk", "blk_type") == [
        "vdd", "vss", "a"]


def test_a_block_matched_by_TYPE_is_also_found(tmp_path: Path):
    p = _project(tmp_path, [{"name": "ldo", "ports": ["vin", "vout"]}])
    assert A._staged_interface_ports(p, "u_reg", "ldo") == ["vin", "vout"]


def test_a_portless_record_does_not_shadow_the_declaration(tmp_path: Path):
    """A block can appear twice: a multiplicity pass contributes the NAME with
    no ports, the staged declaration contributes the ports. Taking the first
    entry BY NAME lost the declaration on one block while its sibling — which
    had no such record — resolved fine."""
    p = _project(tmp_path, [
        {"name": "blk", "extraction_strategy": "multiplicity"},
        {"name": "blk", "ports": ["vdd", "vss", "a"]},
    ])
    assert A._staged_interface_ports(p, "blk", "blk") == ["vdd", "vss", "a"]


def test_no_declaration_stays_none(tmp_path: Path):
    p = _project(tmp_path, [{"name": "other", "ports": ["x"]}])
    assert A._staged_interface_ports(p, "blk", "blk") is None
    assert A._staged_interface_ports(tmp_path / "nothing", "blk", "b") is None


def test_normalized_ports_are_preferred_when_present(tmp_path: Path):
    p = _project(tmp_path, [{"name": "blk", "ports": ["wrong"],
                             "ports_normalized": [{"name": "right"}]}])
    assert A._staged_interface_ports(p, "blk", "blk") == ["right"]


def test_the_block_lists_own_pins_still_win(tmp_path: Path):
    """`_interface` is unchanged and still first: a block list that names pins
    is a more specific declaration than a staged netlist header."""
    assert A._interface({"pins": ["p", "q"]}) == {
        "pins": [{"name": "p"}, {"name": "q"}]}
    assert A._interface({}) is None
