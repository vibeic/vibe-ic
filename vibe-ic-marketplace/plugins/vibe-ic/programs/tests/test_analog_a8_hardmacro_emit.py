#!/usr/bin/env python3
"""An analog block had no route to a real abstract, and Phase 3 needs one.

MEASURED. `digital_hardmacro_gen` writes a REAL abstract by Magic through the
PDK's own magicrc, and makes a DEF a precondition — an analog block has none
and never will; it is drawn, not placed. The only other producer was the
runner's deterministic stub (a 100x100 LEF with no pins, and its own text says
so). So A8 sat at VACUOUS_PASS while OpenROAD refused the digital top with
`ORD-2013: LEF master <block> not found`. The capability was never absent:
`lef write -hide` reads the pins from the layout's own port labels.

chip/PDK-AGNOSTIC.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import analog_a8_hardmacro_emit as E  # noqa: E402


def test_rails_and_signals_come_from_the_blocks_own_topology():
    topo = {"ports": ["vdd", "vss", "vin", "vout"],
            "rails": {"vdd": "vdd", "vss": "vss"}}
    assert E.block_ports(topo) == (["vdd", "vss"], ["vin", "vout"])


def test_a_block_that_names_its_rails_differently_needs_no_change_here():
    topo = {"ports": ["avdd", "agnd", "sig"],
            "rails": {"vdd": "avdd", "vss": "agnd"}}
    assert E.block_ports(topo) == (["avdd", "agnd"], ["sig"])


def test_ports_with_no_declared_rails_are_all_signals():
    assert E.block_ports({"ports": ["a", "b"]}) == ([], ["a", "b"])


def test_the_lef_tcl_writes_the_abstract_form():
    tcl = E.build_lef_tcl("blk", "/x/blk.gds", "/x/blk.lef")
    assert "gds read /x/blk.gds" in tcl
    assert "load blk" in tcl
    # `-hide` IS the abstract; without it Magic writes the full geometry and
    # the "abstract" is the implementation again.
    assert "lef write /x/blk.lef -hide" in tcl


def test_the_interface_verilog_declares_every_port_and_marks_no_direction():
    v = E.interface_verilog("blk", ["vdd", "vss"], ["vin", "vout"])
    for p in ("vdd", "vss", "vin", "vout"):
        assert f"inout {p};" in v
    assert "module blk (" in v and "endmodule" in v
    # the A8 gate refuses a file that calls itself a stub, and rightly: an
    # interface is not a behavioural model and must not pretend to be one.
    for marker in ("behavioral stub", "placeholder hardmacro",
                   "do not tape out", "ai_authored_methodology_stub"):
        assert marker not in v.lower()
    assert len(v.encode()) >= 150


def test_the_interface_liberty_declares_pg_pins_and_no_timing_arc():
    lib = E.interface_liberty("blk", ["vdd", "vss"], ["vin", "vout"])
    assert 'pg_pin (vdd)' in lib and 'primary_power' in lib
    assert 'pg_pin (vss)' in lib and 'primary_ground' in lib
    assert 'pin (vin)' in lib and 'is_analog : true' in lib
    # An analog macro has no arc to declare at this level, and inventing one
    # would be a lie a signoff tool would then act on.
    assert "timing" not in lib.replace("interface_timing", "")
    assert len(lib.encode()) >= 200


def test_the_technology_is_read_from_the_layout_that_was_drawn(tmp_path: Path):
    """The abstract has to be written by the technology the layout was DRAWN
    in, and the layout says which that is on line 2 of every .mag Magic
    writes. Picking "the only PDK installed" is not available: a full EDA
    image installs several (four, on the pinned one)."""
    d = tmp_path / "b"
    d.mkdir()
    (d / "layout.mag").write_text("magic\ntech some-tech\nmagscale 1 2\n")
    assert E.layout_tech(d) == "some-tech"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert E.layout_tech(empty) is None
    nomag = tmp_path / "nomag"
    nomag.mkdir()
    (nomag / "x.mag").write_text("magic\ntimestamp 1\n")
    assert E.layout_tech(nomag) is None


def test_a_missing_gds_is_a_named_refusal_not_a_stub(tmp_path: Path):
    p = tmp_path / "proj"
    (p / "phase3" / "analog" / "ldo").mkdir(parents=True)
    r = E.emit_block(p, "ldo", "", "/nowhere")
    assert r["emitted"] is False and r["rc"] == 1
    assert "GDS" in r["reason"]


def test_block_names_come_from_the_shared_loader(tmp_path: Path):
    """A block-list entry is a dict (name + spec + evidence), not a string.
    Rolling a reader here cost a run: `str(entry)` became a 2 KB path the
    filesystem refused with "File name too long" — a refusal that reads like a
    design problem and is a parser problem."""
    p = tmp_path / "proj"
    a = p / "phase3" / "analog"
    a.mkdir(parents=True)
    (a / "analog_block_list.json").write_text(json.dumps(
        {"blocks": [{"name": "ldo", "spec": {"specs": [1, 2, 3]}},
                    "delta_sigma"]}))
    assert sorted(E.declared_blocks(p)) == ["delta_sigma", "ldo"]
