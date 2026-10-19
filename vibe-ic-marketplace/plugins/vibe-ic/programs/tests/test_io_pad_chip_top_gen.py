#!/usr/bin/env python3
"""The producer that instantiates the IO pad cells, and its refusals.

WHAT THESE TESTS ARE THE CONTROL FOR
====================================
Before this producer existed, `pad_assignment_gen` refused every design on the
chip path for a reason it stated in its own docstring: the four side lists and
`SIGNAL_MAP` name NETLIST INSTANCES, and no step of this flow instantiated an
IO cell, so there were no instances to name. MEASURED on one benchmark IC and
one open 5 V PDK at plugin 1.15.65:

    pad_assignment_gen rc=1 — "3 of 8 answered ... still owes 10 of the 13
    variables `pad_ring_gen` requires"

`test_the_producer_closes_the_owed_set` is the BIDIRECTIONAL control for that:
one fixture tree, `pad_assignment_gen` run twice, differing only in whether the
producer has run. Without it five variables are owed and the program refuses;
with it none of the five is. `test_removing_the_record_puts_the_owed_set_back`
runs the same control as a MUTATION, so a guard that only ever sees the fixed
state cannot pass by coincidence.

The remaining tests pin REFUSALS. They matter more than the happy path: a pad
ring that is wrong is a pin-out nobody chose wearing the artefact of one
somebody did, and the value of this producer is that it declines to invent the
parts nobody stated.

`test_the_die_the_ring_needs_is_the_three_terms_pad_ring_gen_subtracts` pins
the arithmetic that two separate measured refusals came out of — first the
corner term, then the edge-spacing term — against the exact expression
`pad_ring_gen.side_width` uses.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import io_pad_chip_top_gen as PAD  # noqa: E402

GEN = PROGRAMS / "io_pad_chip_top_gen.py"
ASSIGN = PROGRAMS / "pad_assignment_gen.py"


def test_declared_bus_controls_reach_the_pad_faces_without_zero_defaulting(tmp_path):
    doc = tmp_path / 'interface.md'
    doc.write_text('# Pad Auxiliary Controls\n'
                   'data[0]: ENABLE=1, MODE[0]=0, MODE[1]=1, MODE[2]=1\n')
    levels = PAD.declared_aux_levels([doc])
    pins = {
        'BOND': {'direction': 'inout', 'is_pad': True,
                 'function': 'CORE', 'three_state': 'OE'},
        'CORE': {'direction': 'input'}, 'OE': {'direction': 'input'},
        'ENABLE': {'direction': 'input'},
        **{f'MODE[{bit}]': {'direction': 'input'} for bit in range(3)},
    }
    faces = PAD.PR.pad_cell_faces(pins, 'output', levels.get('data[0]'))
    assert not faces.refused
    assert [faces.ties[f'MODE[{bit}]'] for bit in (2, 1, 0)] == [1, 1, 0]
    assert faces.ties['ENABLE'] == 1 and faces.ties['OE'] == 0
    assert all(faces.reasons[f'MODE[{bit}]'] == 'declared by the design'
               for bit in range(3))


@pytest.mark.parametrize('value', ['2', '10', '-1'])
def test_aux_bus_boolean_declaration_does_not_accept_a_partial_number(tmp_path, value):
    doc = tmp_path / 'interface.md'
    doc.write_text(f'# Pad Auxiliary Controls\ndata: MODE[1]={value}\n')
    assert PAD.declared_aux_levels([doc]) == {}

#: The five variables that were owed because nothing instantiated a pad.
INSTANCE_NAMED_VARS = ("PAD_SOUTH", "PAD_EAST", "PAD_NORTH", "PAD_WEST",
                       "SIGNAL_MAP")

DOC = """---
layer: L3
---

# L3 — External Interface

The I/O cell library is delegated to the PDK i/o pad defaults.

## Physical Pad Placement

| Pad side | signals |
|---|---|
| **South (S)** | `rst` |
| **East (E)** | `clk` |
| **North (N)** | `d[w-1:0]` |
| **West (W)** | `q` |

## Design Parameters

| Parameter | default |
|---|---|
| `w` | 2 |
"""

SPEC = {
    "top_module": "core",
    "top_ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst", "direction": "input", "width": 1},
        {"name": "d", "direction": "input", "width": 2, "msb": 1, "lsb": 0},
        {"name": "q", "direction": "output", "width": 1},
    ],
}

GROUP_DOC = """---
layer: L3
---

# L3 — External Interface

The I/O cell library is delegated to the PDK i/o pad defaults.

## Physical Pad Placement

| Pad side | signals |
|---|---|
| **North (N)** | payload data bus |
| **South (S)** | address + control valid / ready |
| **East (E)** | `clk` / `rst` |
| **West (W)** | status pin(s) |
"""

GROUP_SPEC = {
    "top_module": "core",
    "top_ports": [
        {"name": "clk", "direction": "input", "width": 1},
        {"name": "rst", "direction": "input", "width": 1},
        {"name": "i_payload_data", "direction": "input", "width": 2,
         "msb": 1, "lsb": 0},
        {"name": "o_payload_data", "direction": "output", "width": 2,
         "msb": 1, "lsb": 0},
        {"name": "o_address", "direction": "output", "width": 1},
        {"name": "o_control_valid", "direction": "output", "width": 1},
        {"name": "i_control_ready", "direction": "input", "width": 1},
        {"name": "o_status", "direction": "output", "width": 1},
    ],
}


def _macro(name: str, cls: str, w: float = 10.0, h: float = 100.0,
           pins=()) -> str:
    body = [f"MACRO {name}", f"  CLASS {cls} ;", f"  SIZE {w:.3f} BY {h:.3f} ;"]
    for pin, use in pins:
        body += [f"  PIN {pin}", "    DIRECTION INOUT ;", f"    USE {use} ;",
                 f"  END {pin}"]
    body += [f"END {name}", ""]
    return "\n".join(body)


#: A library in the distribution layout `_pad_ring.discover_io_lefs` reads.
#: No real PDK is copied and no vendor, foundry or process name appears.
CORNER_W = 40.0
PAD_W = 10.0
EDGE = 5.0

FULL_MACROS = (
    _macro("testlib_io__in", "PAD INPUT", PAD_W, 100.0, [("PAD", "SIGNAL")])
    + _macro("testlib_io__bi", "PAD INOUT", PAD_W, 100.0, [("PAD", "SIGNAL")])
    + _macro("testlib_io__fill", "PAD SPACER", 1.0, 100.0)
    + _macro("testlib_io__cor", "ENDCAP BOTTOMLEFT", CORNER_W, CORNER_W)
)
FULL_TERMINALS = "testlib_io__in/PAD testlib_io__bi/PAD"


def _pdk(root: Path, *, macros: str = FULL_MACROS,
         terminals: str = FULL_TERMINALS, edge: float = EDGE) -> Path:
    lef = root / "testpdk" / "libs.ref" / "testlib_io" / "lef"
    lef.mkdir(parents=True)
    (lef / "testlib_io.lef").write_text(macros)
    tech = root / "testpdk" / "libs.tech" / "someflow" / "testlib_io"
    tech.mkdir(parents=True)
    cfg = ['set ::env(PAD_SITE_NAME) "IO_Site"',
           'set ::env(PAD_CORNER_SITE_NAME) "COR_Site"',
           f'set ::env(PAD_EDGE_SPACING) "{edge:g}"',
           'set ::env(PAD_CORNER) "$::env(PAD_CELL_LIBRARY)__cor"',
           'set ::env(PAD_FILLERS) "$::env(PAD_CELL_LIBRARY)__fill"']
    if terminals:
        cfg.append(f'set ::env(PAD_PLACE_IO_TERMINALS) "{terminals}"')
    (tech / "config.tcl").write_text("\n".join(cfg) + "\n")
    return root


def _project(tmp: Path, *, doc: str = DOC, spec=None) -> Path:
    proj = tmp / "proj"
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "L3_external_interface.md").write_text(doc)
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps(SPEC if spec is None else spec))
    return proj


def _run(script: Path, proj: Path, pdk_root: Path, extra=()):
    return subprocess.run(
        [sys.executable, str(script), str(proj),
         "--pdk-root", str(pdk_root), "--pdk", "testpdk", *extra],
        capture_output=True, text=True)


def _record(proj: Path) -> dict:
    return json.loads(
        (proj / "reports" / "phase3" / "io_pad_chip_top.json").read_text())


def _digital_gpio_pdk(root: Path) -> Path:
    """A documented GPIO interface, without copying the PDK or its layout."""
    master = "sky130_ef_io__gpiov2_pad"
    macros = (_macro(master, "PAD INOUT", pins=[("PAD", "SIGNAL")])
              + _macro("sky130_ef_io__fill", "PAD SPACER", 1, 100)
              + _macro("sky130_ef_io__cor", "ENDCAP BOTTOMLEFT", 40, 40))
    _pdk(root, macros=macros, terminals=f"{master}/PAD")
    io = root / "testpdk/libs.ref/sky130_ef_io"
    (root / "testpdk/libs.ref/testlib_io").rename(io)
    cfg = root / "testpdk/libs.tech/someflow/testlib_io/config.tcl"
    cfg.write_text(cfg.read_text().replace('$::env(PAD_CELL_LIBRARY)', 'sky130_ef_io'))
    lib = io / "lib"
    lib.mkdir()
    controls = ["OE_N", "INP_DIS", "ENABLE_H", "HLD_H_N",
                "ENABLE_VDDIO", "ENABLE_VSWITCH_H", "ENABLE_INP_H",
                "ENABLE_VDDA_H", "SLOW", "IB_MODE_SEL", "VTRIP_SEL",
                "ANALOG_EN", "ANALOG_SEL", "ANALOG_POL", "HLD_OVR",
                "DM[0]", "DM[1]", "DM[2]"]
    hv = {"ENABLE_H", "HLD_H_N", "ENABLE_VSWITCH_H", "ENABLE_INP_H"}
    pins = ['pin("PAD") { direction: inout; is_pad: true; '
            'function: "OUT"; three_state: "OE_N"; }',
            'pin("OUT") { direction: input; related_power_pin: "VCCD"; }',
            'pin("IN") { direction: output; function: "!INP_DIS * PAD"; '
            'related_power_pin: "VCCD"; }']
    for control in controls:
        pins.append(f'pin("{control}") {{ direction: input; '
                    f'related_power_pin: "{"VDDIO" if control in hv else "VCCD"}"; }}')
    for name, value in [("TIE_HI_ESD", 1), ("TIE_LO_ESD", 0)]:
        pins.append(f'pin("{name}") {{ direction: output; function: "{value}"; '
                    'related_power_pin: "VDDIO"; }')
    # The parser reads line-oriented Liberty attributes, as the real PDK does.
    text = 'cell("' + master + '") {\n' + '\n'.join(pins) + '\n}\n'
    text = text.replace('{ ', '{\n').replace('; ', ';\n').replace(' }', '\n}')
    (lib / "gpio.lib").write_text(text)
    verilog = io / "verilog"
    verilog.mkdir()
    (verilog / "gpio.v").write_text(
        f'module {master}(input [2:0] DM); endmodule\n')
    return root


def test_digital_gpio_defaults_operate_instead_of_disabling_the_chip(tmp_path):
    proj = _project(tmp_path)
    res = _run(GEN, proj, _digital_gpio_pdk(tmp_path / "pdk"), (
        "--tie-high-cell", "TIEHI", "--tie-high-pin", "Y",
        "--tie-low-cell", "TIELO", "--tie-low-pin", "Y"))
    assert res.returncode == 0, res.stdout + res.stderr
    record = _record(proj)
    pads = [p for p in record["pad_instances"].values() if p.get("core_pin")]
    assert len(pads) == 5
    for pad in pads:
        t = pad["ties"]
        # PDK operating truth table: enable=0 or DM=000 disables digital IO;
        # hold=0 freezes data. These are functional requirements, not tuning.
        assert t["ENABLE_H"] == t["HLD_H_N"] == 1
        assert t["ENABLE_VDDIO"] == t["ENABLE_VSWITCH_H"] == 1
        dm = sum(t[f"DM[{bit}]"] << bit for bit in range(3))
        assert dm == (6 if pad["direction"] == "output" else 1)
        assert t["INP_DIS"] == int(pad["direction"] == "output")
        assert t["OE_N"] == int(pad["direction"] == "input")
        assert pad["tie_reasons"]["ENABLE_H"].startswith("PDK operating profile:")
    rows = record["aux_pin_signal_connections"]
    text = (proj / record["chip_top_verilog"]).read_text()
    for inst, pad in record["pad_instances"].items():
        if not pad.get("core_pin"):
            continue
        high = [r for r in rows if r["instance"] == inst and
                r["pin"] in {"ENABLE_H", "HLD_H_N", "ENABLE_VSWITCH_H"}]
        assert len(high) == 3
        assert all(r["tie_instance"] == inst and r["tie_pin"] == "TIE_HI_ESD"
                   for r in high)
        assert len({r["net"] for r in high}) == 1
        assert f'.TIE_HI_ESD({high[0]["net"]})' in text


def test_declared_gpio_aux_controls_take_precedence_over_the_profile(tmp_path):
    proj = _project(tmp_path, doc=DOC +
                    '\n# Pad Auxiliary Controls\nq: SLOW=1, DM[0]=1\n')
    res = _run(GEN, proj, _digital_gpio_pdk(tmp_path / "pdk"), (
        "--tie-high-cell", "TIEHI", "--tie-high-pin", "Y",
        "--tie-low-cell", "TIELO", "--tie-low-pin", "Y"))
    assert res.returncode == 0, res.stdout + res.stderr
    q = next(p for p in _record(proj)["pad_instances"].values() if p["port"] == "q")
    assert q["ties"]["SLOW"] == q["ties"]["DM[0]"] == 1
    assert q["tie_reasons"]["SLOW"] == "declared by the design"
    assert q["ties"]["DM[2]"] == q["ties"]["DM[1]"] == 1


def _owed(report: Path) -> list:
    """The variables `pad_assignment_gen` says are still owed.

    It carries them on the FINDING, not at the top level, so reading a
    top-level `owed` key returns an empty list for a refusing run as well as a
    satisfied one — which would make every assertion below vacuous in the
    flattering direction.
    """
    obj = json.loads(report.read_text())
    out = []
    for f in obj.get("findings") or []:
        out.extend(f.get("variables_owed") or [])
    return out


# --------------------------------------------------------------------------- #
# the happy path — asserted, not assumed, because every refusal below is
# measured against it
# --------------------------------------------------------------------------- #
def test_one_pad_instance_per_declared_pin(tmp_path):
    proj = _project(tmp_path)
    res = _run(GEN, proj, _pdk(tmp_path / "pdk"))
    assert res.returncode == 0, res.stdout + res.stderr
    rec = _record(proj)
    # 5 declared pins: rst, clk, d[1], d[0], q — the bus expanded one pad per
    # bit by the design's OWN rule, read by `_l_doc_pad_placement`.
    assert len(rec["pad_instances"]) == 5, rec["pad_instances"]
    masters = {r["master"] for r in rec["pad_instances"].values()}
    assert masters <= {"testlib_io__in", "testlib_io__bi"}, masters
    # The master came off the LEF CLASS record, not off a name table.
    inp = [i for i, r in rec["pad_instances"].items()
           if r["direction"] == "input"]
    assert all(rec["pad_instances"][i]["master"] == "testlib_io__in"
               for i in inp)
    v = (proj / rec["chip_top_verilog"]).read_text()
    for master in masters:
        assert master in v


def test_named_port_groups_resolve_without_a_design_specific_name_table(
        tmp_path):
    """A group row is a real declaration when port identifiers resolve it.

    This is not fuzzy prose matching: every semantic atom of each selected
    port occurs in the row, bus bits are still taken from L9, and the record
    exposes the exact statement-to-port mapping for review.
    """
    proj = _project(tmp_path, doc=GROUP_DOC, spec=GROUP_SPEC)
    res = _run(GEN, proj, _pdk(tmp_path / "pdk"))
    assert res.returncode == 0, res.stdout + res.stderr
    rec = _record(proj)
    mapped = {r["side"]: r["matched_ports"]
              for r in rec["pad_group_resolution"]}
    assert mapped == {
        "N": ["i_payload_data", "o_payload_data"],
        "S": ["o_address", "o_control_valid", "i_control_ready"],
        "W": ["o_status"],
    }
    assert sum(len(v) for v in rec["derived_answers"]
               ["pad_order_by_side"].values()) == 10


def test_an_unresolved_group_is_refused_not_applied_to_every_port(tmp_path):
    doc = GROUP_DOC.replace("status pin(s)", "observability pins")
    proj = _project(tmp_path, doc=doc, spec=GROUP_SPEC)
    res = _run(GEN, proj, _pdk(tmp_path / "pdk"))
    assert res.returncode == 1, res.stdout + res.stderr
    assert "PAD_GROUP_UNRESOLVED" in res.stdout + res.stderr
    assert not (proj / "phase3/stage3/pnr/chip_top_io.v").exists()


def test_the_terminal_name_comes_from_the_library_not_from_a_constant(tmp_path):
    """A pad's signal pin is not always called `PAD`. The library states it in
    `PAD_PLACE_IO_TERMINALS`, and the emitted connection must use that name."""
    macros = (_macro("testlib_io__in", "PAD INPUT", PAD_W, 100.0,
                     [("ASIG", "SIGNAL")])
              + _macro("testlib_io__bi", "PAD INOUT", PAD_W, 100.0,
                       [("ASIG", "SIGNAL")])
              + _macro("testlib_io__fill", "PAD SPACER", 1.0, 100.0)
              + _macro("testlib_io__cor", "ENDCAP BOTTOMLEFT", CORNER_W,
                       CORNER_W))
    proj = _project(tmp_path)
    res = _run(GEN, proj, _pdk(tmp_path / "pdk", macros=macros,
                              terminals="testlib_io__in/ASIG "
                                        "testlib_io__bi/ASIG"))
    assert res.returncode == 0, res.stdout + res.stderr
    v = (proj / _record(proj)["chip_top_verilog"]).read_text()
    assert ".ASIG(" in v and ".PAD(" not in v, v[:400]


def test_a_design_that_declares_no_pad_placement_writes_nothing(tmp_path):
    """Nobody was asked. No chip top, no record of instances, and
    `pad_assignment_gen` keeps the branch it has today."""
    proj = _project(tmp_path, doc="# L3\n\nNothing about pads.\n")
    res = _run(GEN, proj, _pdk(tmp_path / "pdk"))
    assert res.returncode == 2, res.stdout
    assert not (proj / "phase3/stage3/pnr/chip_top_io.v").exists()


def test_pad_placement_in_an_ordinary_design_document_is_consumed(tmp_path):
    proj = _project(tmp_path)
    doc = proj / "input/docs/L3_external_interface.md"
    doc.rename(doc.with_name("design.md"))
    result = _run(GEN, proj, _pdk(tmp_path / "pdk"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_record(proj)["pad_instances"]) == 5


def test_reviewed_implementation_pad_plan_is_a_fallback_input(tmp_path):
    proj = _project(tmp_path, doc="# Interface\nNo fixed pad placement.\n")
    plan = proj / "phase3/stage3/pnr/io_pad_placement_plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(DOC)
    result = _run(GEN, proj, _pdk(tmp_path / "pdk"))
    assert result.returncode == 0, result.stdout + result.stderr
    placement, _, errors, _ = PAD.LPP.read_project_placement(proj)
    assert not errors
    assert placement.source == "phase3/stage3/pnr/io_pad_placement_plan.md"
    assert len(_record(proj)["pad_instances"]) == 5


def test_declared_pad_placement_precedes_implementation_plan(tmp_path):
    proj = _project(tmp_path)
    plan = proj / "phase3/stage3/pnr/io_pad_placement_plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(DOC.replace("`rst`", "`not_a_port`"))
    result = _run(GEN, proj, _pdk(tmp_path / "pdk"))
    assert result.returncode == 0, result.stdout + result.stderr
    placement, _, errors, _ = PAD.LPP.read_project_placement(proj)
    assert not errors
    assert placement.source == "input/docs/L3_external_interface.md"


# --------------------------------------------------------------------------- #
# refusals
# --------------------------------------------------------------------------- #
def test_an_absent_io_library_is_refused_not_worked_around(tmp_path):
    proj = _project(tmp_path)
    empty = tmp_path / "emptypdk"
    (empty / "testpdk").mkdir(parents=True)
    res = _run(GEN, proj, empty)
    assert res.returncode != 0, res.stdout
    assert "NO_IO_LIBRARY" in res.stdout + res.stderr


def test_a_pad_placement_naming_a_port_the_design_does_not_declare_is_refused(
        tmp_path):
    """The document and the port list disagree, and choosing between them is
    not this producer's decision."""
    # ADDED, not renamed: renaming a placed port leaves it on no edge and the
    # producer refuses that first, with a different rule. The question here is
    # the other one — a side naming a net the design does not declare.
    doc = DOC.replace("`rst`", "`rst`、`nonesuch`")
    proj = _project(tmp_path, doc=doc)
    res = _run(GEN, proj, _pdk(tmp_path / "pdk"))
    assert res.returncode == 1, res.stdout
    assert "SIDE_NAMES_UNKNOWN_PORT" in res.stdout + res.stderr
    assert "nonesuch" in res.stdout + res.stderr


def test_a_library_with_no_master_for_a_direction_is_refused(tmp_path):
    """Only a SPACER and a corner: nothing that can bring a signal out."""
    macros = (_macro("testlib_io__fill", "PAD SPACER", 1.0, 100.0)
              + _macro("testlib_io__cor", "ENDCAP BOTTOMLEFT", CORNER_W,
                       CORNER_W))
    proj = _project(tmp_path)
    res = _run(GEN, proj, _pdk(tmp_path / "pdk", macros=macros, terminals=""))
    assert res.returncode == 1, res.stdout


# --------------------------------------------------------------------------- #
# the die the ring needs
# --------------------------------------------------------------------------- #
def test_the_die_is_the_three_terms_pad_ring_gen_subtracts(tmp_path):
    """THE ARITHMETIC, PINNED AGAINST ITS CONSUMER.

    `pad_ring_gen.side_width` computes, for each side,

        side = (die extent) - 2 * PAD_EDGE_SPACING - 2 * (corner extent)

    so a die sized without either term refuses a ring that fits. BOTH were
    measured as real refusals before this test existed: without the corner
    term the side came out negative on all four sides at once, and with the
    corner term but not the edge term the north side was short by exactly
    twice the library's declared 26 um spacing. This asserts the SAME three
    terms, computed from the fixture's own declared widths, so a change to
    either program that drops one of them reddens here.
    """
    proj = _project(tmp_path)
    assert _run(GEN, proj, _pdk(tmp_path / "pdk")).returncode == 0
    req = _record(proj)["die_required_um"]
    # The north side carries the 2-bit bus; the longest side decides the die.
    longest = 2 * PAD_W
    assert req["die_side_um"] == 2 * EDGE + 2 * CORNER_W + longest, req
    assert req["edge_spacing_um"] == EDGE
    assert req["corner_width_um"] == CORNER_W


def test_a_library_declaring_no_edge_spacing_contributes_zero_not_a_default(
        tmp_path):
    proj = _project(tmp_path)
    pdk = _pdk(tmp_path / "pdk", edge=0.0)
    assert _run(GEN, proj, pdk).returncode == 0
    req = _record(proj)["die_required_um"]
    assert req["edge_spacing_um"] == 0.0
    assert req["die_side_um"] == 2 * CORNER_W + 2 * PAD_W


@pytest.mark.parametrize("inset", [37, 3])
def test_declared_inset_reaches_geometry(tmp_path, inset):
    """The producer and assignment consume one effective spacing value.

    Both values differ from the library's 5 um fact, in opposite directions,
    so this catches a max() policy as well as a library-only policy.
    """
    proj = _project(tmp_path)
    decl = proj / "input/submission_template/tapeout_declaration.json"
    decl.parent.mkdir(parents=True)
    decl.write_text(json.dumps({"answers": {"pad_edge_spacing_um": inset}}))
    pdk = _pdk(tmp_path / "pdk")

    made = _run(GEN, proj, pdk)
    assert made.returncode == 0, made.stdout + made.stderr
    assigned = _run(ASSIGN, proj, pdk)
    assert assigned.returncode == 0, assigned.stdout + assigned.stderr

    assignment = json.loads(
        (proj / "phase3/stage3/pnr/pad_assignment.json").read_text())
    record = _record(proj)
    assert assignment["PAD_EDGE_SPACING"] == inset
    assert float(record["pdk_declared"]["PAD_EDGE_SPACING"]) == EDGE
    assert record["pdk_declared_sources"]["PAD_EDGE_SPACING"].endswith(
        "config.tcl:3")
    assert record["die_required_um"]["edge_spacing_um"] == inset
    assert record["die_required_um"]["die_side_um"] == (
        2 * inset + 2 * CORNER_W + 2 * PAD_W)
    assert record["die_required_um"]["ring_depth_um"] == 100 + inset
    assert record["die_required_um"]["edge_spacing_source"] == (
        "declaration answer pad_edge_spacing_um")
    assert record["effective_pad_edge_spacing"] == {
        "value_um": float(inset),
        "source": "declaration answer pad_edge_spacing_um",
    }


def test_an_unreadable_spacing_declaration_is_refused(tmp_path):
    proj = _project(tmp_path)
    decl = proj / "input/submission_template/tapeout_declaration.json"
    decl.parent.mkdir(parents=True)
    decl.write_text("{not-json")

    made = _run(GEN, proj, _pdk(tmp_path / "pdk"))
    assert made.returncode == 1, made.stdout + made.stderr
    assert _record(proj)["rule"] == "PAD_EDGE_SPACING_SOURCE_UNREADABLE"


@pytest.mark.parametrize(
    "inset", ["not-a-number", -1, float("inf")],
    ids=["nonnumeric", "negative", "nonfinite"])
def test_an_invalid_declared_inset_is_refused(tmp_path, inset):
    proj = _project(tmp_path)
    decl = proj / "input/submission_template/tapeout_declaration.json"
    decl.parent.mkdir(parents=True)
    decl.write_text(json.dumps({"answers": {"pad_edge_spacing_um": inset}}))

    made = _run(GEN, proj, _pdk(tmp_path / "pdk"))
    assert made.returncode == 1, made.stdout + made.stderr
    assert _record(proj)["rule"] == "PAD_EDGE_SPACING_INVALID"


# --------------------------------------------------------------------------- #
# THE BIDIRECTIONAL CONTROL
# --------------------------------------------------------------------------- #
def test_the_producer_closes_the_owed_set(tmp_path):
    """ONE tree, `pad_assignment_gen` twice, the producer's record the only
    difference.

    RED DIRECTION (the pre-fix state, reproduced rather than described): with
    no record, the four side lists and `SIGNAL_MAP` are owed and the program
    refuses — exactly what it reported for every design on the chip path.

    GREEN DIRECTION: with the record present, none of the five is owed.

    The assertion is on the OWED SET, not the exit code, so it stays a
    statement about these five variables even if another is owed for an
    unrelated reason.
    """
    proj = _project(tmp_path)
    pdk = _pdk(tmp_path / "pdk")
    report = proj / "pa.json"

    before = _run(ASSIGN, proj, pdk, ("--json", str(report)))
    assert before.returncode == 1, before.stdout
    owed_before = json.dumps(_owed(report))
    for var in INSTANCE_NAMED_VARS:
        assert var in owed_before, (var, owed_before)

    assert _run(GEN, proj, pdk).returncode == 0

    after = _run(ASSIGN, proj, pdk, ("--json", str(report)))
    owed_after = _owed(report)
    for var in INSTANCE_NAMED_VARS:
        assert not any(str(o).startswith(var) for o in owed_after), (
            f"{var} is still owed after the producer ran", owed_after)
    assert after.returncode == 0, after.stdout


def test_removing_the_record_puts_the_owed_set_back(tmp_path):
    """The control's other end, run as a MUTATION rather than asserted."""
    proj = _project(tmp_path)
    pdk = _pdk(tmp_path / "pdk")
    report = proj / "pa.json"
    assert _run(GEN, proj, pdk).returncode == 0
    assert _run(ASSIGN, proj, pdk, ("--json", str(report))).returncode == 0

    (proj / "reports" / "phase3" / "io_pad_chip_top.json").unlink()
    res = _run(ASSIGN, proj, pdk, ("--json", str(report)))
    assert res.returncode == 1
    owed = json.dumps(_owed(report))
    for var in INSTANCE_NAMED_VARS:
        assert var in owed, (var, owed)


def test_the_two_tcl_spelled_variables_are_resolved_and_checked(tmp_path):
    """`PAD_CORNER` and `PAD_FILLERS` are spelled with a Tcl substitution in
    the library's own config, so `parse_pad_env_declarations` correctly returns
    neither and they stayed owed. The producer expands the ONE substitution it
    has measured — the library the LEFs were read from — and publishes the
    result only after confirming it is a macro that library carries."""
    proj = _project(tmp_path)
    pdk = _pdk(tmp_path / "pdk")
    assert _run(GEN, proj, pdk).returncode == 0
    d = _record(proj)["derived_answers"]
    assert d["pad_corner_master"] == "testlib_io__cor"
    assert d["pad_fillers"] == ["testlib_io__fill"]


def test_a_corner_name_the_library_does_not_carry_is_not_published(tmp_path):
    """The other direction of the test above: the expansion is CHECKED, so a
    config naming a master the LEF has no MACRO for publishes nothing rather
    than a real-looking name."""
    proj = _project(tmp_path)
    root = tmp_path / "pdk"
    _pdk(root)
    cfg = root / "testpdk" / "libs.tech" / "someflow" / "testlib_io" / "config.tcl"
    cfg.write_text(cfg.read_text().replace("__cor", "__nosuchcorner"))
    assert _run(GEN, proj, root).returncode == 0
    assert _record(proj)["derived_answers"]["pad_corner_master"] is None


# --------------------------------------------------------------------------- #
# the conflict direction, at this producer's own call sites
#
# The producer folds every discovered IO LEF through `merge_source_records`
# twice -- once for the macro CLASSES, once for the macro SIZES -- and writes
# `on_conflict="richer"` at both. `policy_direction_pin_check` reported both
# sites UNPINNED on b309595f06 with ZERO candidate tests: no test file named
# this program together with the parameter or the callee, so nothing here could
# ever have died when the literal was flipped to `"sparser"`.
#
# ONE LEF IS NOT ENOUGH TO REACH THE PARAMETER, which is why the gap survived a
# file this size. Every fixture above ships a single library; a single source
# produces one `distinct` record per macro and `merge_source_records` returns
# it before `on_conflict` is read. Two libraries that both SPEAK about the same
# macro and disagree is the only input that reaches the branch, so that is what
# these build -- through the producer's CLI, in both discovery orders.
# --------------------------------------------------------------------------- #

#: Everything both libraries agree about in the two tests below.
AGREED_MACROS = (
    _macro("testlib_io__in", "PAD INPUT", PAD_W, 100.0, [("PAD", "SIGNAL")])
    + _macro("testlib_io__fill", "PAD SPACER", 1.0, 100.0)
    + _macro("testlib_io__cor", "ENDCAP BOTTOMLEFT", CORNER_W, CORNER_W)
)


def _pdk_two(root: Path, first: str, second: str, terminals: str) -> Path:
    """A PDK whose IO library ships TWO LEFs. `discover_io_lefs` returns them
    sorted by file name, so the caller decides the discovery order by choosing
    which text is written to which name."""
    lef = root / "testpdk" / "libs.ref" / "testlib_io" / "lef"
    lef.mkdir(parents=True)
    (lef / "a_first.lef").write_text(first)
    (lef / "z_second.lef").write_text(second)
    tech = root / "testpdk" / "libs.tech" / "someflow" / "testlib_io"
    tech.mkdir(parents=True)
    (tech / "config.tcl").write_text("\n".join([
        'set ::env(PAD_SITE_NAME) "IO_Site"',
        'set ::env(PAD_CORNER_SITE_NAME) "COR_Site"',
        f'set ::env(PAD_EDGE_SPACING) "{EDGE:g}"',
        'set ::env(PAD_CORNER) "$::env(PAD_CELL_LIBRARY)__cor"',
        'set ::env(PAD_FILLERS) "$::env(PAD_CELL_LIBRARY)__fill"',
        f'set ::env(PAD_PLACE_IO_TERMINALS) "{terminals}"']) + "\n")
    return root


def _both_orders(tmp_path: Path, rich: str, poor: str, terminals: str):
    """The producer run twice over the same two libraries, swapped."""
    out = []
    for i, (first, second) in enumerate(((rich, poor), (poor, rich))):
        proj = _project(tmp_path / f"run{i}")
        res = _run(GEN, proj, _pdk_two(tmp_path / f"pdk{i}", first, second,
                                       terminals))
        rec_path = proj / "reports" / "phase3" / "io_pad_chip_top.json"
        rec = json.loads(rec_path.read_text()) if rec_path.is_file() else {}
        out.append((res, rec))
    return out


def _masters(rec: dict):
    return sorted({r["master"] for r in (rec.get("pad_instances") or {}).values()})


def test_the_richer_class_record_is_what_makes_a_master_selectable(tmp_path):
    """SITE 1 -- the `parse_lef_macro_classes` fold.

    A macro record here is the CLASS STRING, so the fuller description is
    literally the longer one: one library calls `testlib_io__bi`
    `PAD INOUT`, the other only manages `PAD`. `CLASS_PREFERENCE` needs
    `PAD INOUT` for an output port, and `PAD` is not it. Keeping the fuller
    record instantiates the design; keeping the sparser one refuses it,
    NO_PAD_MASTER_FOR_DIRECTION, over a library that does carry the master.
    """
    rich = AGREED_MACROS + _macro("testlib_io__bi", "PAD INOUT", PAD_W, 100.0,
                                  [("PAD", "SIGNAL")])
    poor = AGREED_MACROS + _macro("testlib_io__bi", "PAD", PAD_W, 100.0,
                                  [("PAD", "SIGNAL")])
    terminals = "testlib_io__in/PAD testlib_io__bi/PAD"

    (res_a, rec_a), (res_b, rec_b) = _both_orders(
        tmp_path, rich, poor, terminals)

    assert res_a.returncode == 0, res_a.stdout + res_a.stderr
    assert res_b.returncode == 0, res_b.stdout + res_b.stderr
    assert _masters(rec_a) == _masters(rec_b) == ["testlib_io__bi",
                                                  "testlib_io__in"], (
        "the fuller CLASS record did not win the disagreement, in one order "
        "or in both")

    # The control: the sparser library ALONE really does refuse, so the
    # assertion above is about which record won and not about the fixture.
    proj = _project(tmp_path / "poor_alone")
    only = _run(GEN, proj, _pdk(tmp_path / "pdk_poor", macros=poor,
                               terminals=terminals))
    assert only.returncode == 1, only.stdout
    assert "NO_PAD_MASTER_FOR_DIRECTION" in only.stdout + only.stderr


def test_the_richer_size_record_decides_which_master_is_narrowest(tmp_path):
    """SITE 2 -- the `parse_lef_macros` fold, which is a SIZE and nothing else.

    A macro record here is a `(width, height)` pair of fixed arity, so "more
    content" is not what separates the two policies -- both are total orders
    over the same two numbers and `"richer"` takes the larger. It is still a
    direction and it is still observable: `_select_master` breaks a tie between
    two masters of the same class BY WIDTH, so which SIZE record won decides
    which master the design's output port is brought out on.

    Both libraries agree about every CLASS here. Only `testlib_io__bi`'s SIZE
    disagrees, so this site is measured on its own.
    """
    other = _macro("testlib_io__cb", "PAD INOUT", 50.0, 100.0,
                   [("PAD", "SIGNAL")])
    rich = AGREED_MACROS + other + _macro("testlib_io__bi", "PAD INOUT", 80.0,
                                          100.0, [("PAD", "SIGNAL")])
    poor = AGREED_MACROS + other + _macro("testlib_io__bi", "PAD INOUT", 20.0,
                                          100.0, [("PAD", "SIGNAL")])
    terminals = ("testlib_io__in/PAD testlib_io__bi/PAD "
                 "testlib_io__cb/PAD")

    (res_a, rec_a), (res_b, rec_b) = _both_orders(
        tmp_path, rich, poor, terminals)

    assert res_a.returncode == 0, res_a.stdout + res_a.stderr
    assert res_b.returncode == 0, res_b.stdout + res_b.stderr
    # 80 um wide beats 50, so the narrowest INOUT master is `__cb`.
    assert _masters(rec_a) == _masters(rec_b) == ["testlib_io__cb",
                                                  "testlib_io__in"], (
        "the larger (richer) SIZE record did not win the disagreement, in one "
        "order or in both")

    # The control: with the sparser record `__bi` is 20 um wide and wins the
    # same tie, so the assertion above is about which record won.
    proj = _project(tmp_path / "poor_alone")
    only = _run(GEN, proj, _pdk(tmp_path / "pdk_poor", macros=poor,
                                terminals=terminals))
    assert only.returncode == 0, only.stdout + only.stderr
    assert _masters(json.loads(
        (proj / "reports" / "phase3" / "io_pad_chip_top.json").read_text())
    ) == ["testlib_io__bi", "testlib_io__in"], (
        "precondition: the two SIZE records really do read differently")


def _scan_project(tmp_path):
    """Neutral published scan core, bound to an explicit integration choice."""
    import hashlib
    proj = _project(tmp_path)
    synth = proj / "phase2/stage2/synth"
    synth.mkdir(parents=True)
    text = """module core(clk, rst, d, q, serial_in, serial_out, scan_enable);
input clk;
input rst;
input [1:0] d;
output q;
input serial_in;
output logic serial_out;
input scan_enable;
assign serial_out = serial_in;
assign q = d[0];
endmodule
"""
    net = synth / "post_dft_netlist.v"
    net.write_text(text)
    meta = proj / "reports/phase2/dft/scan_chain.json"
    meta.parent.mkdir(parents=True)
    meta.write_text(json.dumps({"published": True, "chain_length_matches_flop_count": True,
        "authorized_by_l20_contract": True,
        "dft_ports": ["serial_in", "serial_out", "scan_enable"],
        "functional_mode_tieoff": {"serial_in": 0, "scan_enable": 0},
        "scan_out_port": "serial_out"}))
    plan = {"schema": "vibeic.dft-test-access.v1", "mapping": "dedicated_pads",
        "authority": "synthetic integration declaration",
        "netlist_sha256": hashlib.sha256(net.read_bytes()).hexdigest(),
        "scan_metadata_sha256": hashlib.sha256(meta.read_bytes()).hexdigest(),
        "functional_mode": {"serial_in": 0, "scan_enable": 0},
        "ports": [{"name": n, "direction": d, "side": "W"} for n, d in
            [("serial_in", "input"), ("serial_out", "output"), ("scan_enable", "input")]]}
    cfg = proj / "config/dft_test_access.json"
    cfg.parent.mkdir()
    cfg.write_text(json.dumps(plan))
    return proj, cfg, plan


def test_declared_scan_access_reaches_the_wrapper_and_pad_map(tmp_path):
    proj, _, _ = _scan_project(tmp_path)
    pdk = _pdk(tmp_path / "pdk")
    run = _run(GEN, proj, pdk)
    assert run.returncode == 0, run.stdout + run.stderr
    wrapper = (proj / "phase3/stage3/pnr/chip_top_io.v").read_text()
    rec = _record(proj)
    for name in ["serial_in", "serial_out", "scan_enable"]:
        assert f".{name}({name})" in wrapper
        assert f"u_pad_{name}" in wrapper
    assert rec["scan_interface"]["unconnected_controls"] == []
    assert rec["test_access"]["permanent_control_tieoffs"] is False


@pytest.mark.parametrize("defect", ["missing", "stale", "duplicate", "wrong_direction", "wrong_mode"])
def test_invalid_or_missing_scan_plan_still_refuses(tmp_path, defect):
    proj, cfg, plan = _scan_project(tmp_path)
    pdk = _pdk(tmp_path / "pdk")
    if defect == "missing":
        cfg.unlink()
    else:
        if defect == "stale":
            plan["netlist_sha256"] = "0" * 64
        elif defect == "duplicate":
            plan["ports"].append(plan["ports"][0])
        elif defect == "wrong_direction":
            plan["ports"][0]["direction"] = "output"
        else:
            plan["functional_mode"]["scan_enable"] = 1
        cfg.write_text(json.dumps(plan))
    run = _run(GEN, proj, pdk)
    assert run.returncode == 1, run.stdout + run.stderr
    rec = _record(proj)
    assert rec["rule"] == ("DFT_CONTROL_UNCONNECTED" if defect == "missing" else "DFT_TEST_ACCESS_INVALID")
    assert not (proj / "phase3/stage3/pnr/chip_top_io.v").exists()


def test_bussed_pad_connection_is_one_ordered_verilog_connection():
    """A PDK-declared `[2:0]` port is emitted MSB to LSB, never as an
    illegal named bit-select. The emitted fragment is parsed separately by
    the pinned-image acceptance run."""
    ports = PAD.io_bus_ports([
        "module neutral_pad(input [2:0] DM); endmodule\n"
    ])
    got = PAD._named_connections(
        "u_pad", "neutral_pad",
        [("DM[0]", "x"), ("DM[1]", "y"), ("DM[2]", "z")], ports)
    assert got == [".DM({z, y, x})"]
    assert all("[" not in item.split("(", 1)[0] for item in got)
    reverse = PAD._named_connections(
        "u_pad", "reverse_pad",
        [("DM[0]", "x"), ("DM[1]", "y"), ("DM[2]", "z")],
        {"reverse_pad": {"DM": (0, 2)}})
    assert reverse == [".DM({x, y, z})"]


def test_emitted_bussed_pad_verilog_parses_in_the_pinned_eda_image(tmp_path):
    """The real parser is the pinned EDA image, not a string-only proxy."""
    wrapper = PAD._emit_verilog(
        "chip", "core", {"S": ["u_pad"], "E": [], "N": [], "W": []},
        {"u_pad": {"port": "rail", "master": "neutral_pad",
                    "terminal": "DM[0]",
                    "supply_connections": {"DM[0]": "x", "DM[1]": "y",
                                           "DM[2]": "z"}}}, [],
        bus_ports={"neutral_pad": {"DM": (2, 0)}})
    source = ("module neutral_pad(input [2:0] DM); endmodule\n"
              "module core(); endmodule\n" + wrapper)
    dut = tmp_path / "chip.v"
    dut.write_text(source)
    image = os.environ.get("VIBEIC_EDA_IMAGE", "ghcr.io/vibeic/vibeic-eda:0.3.84")
    run = subprocess.run(
        ["docker", "run", "--rm", "--memory=1g", "-v",
         f"{tmp_path}:/work:ro", image, "--skip", "/foss/tools/bin/iverilog", "-g2012",
         "-s", "chip", "/work/chip.v"], capture_output=True, text=True,
        timeout=120)
    assert run.returncode == 0, run.stdout + run.stderr


@pytest.mark.parametrize("pairs,buses,rule", [
    ([("DM[0]", "x"), ("DM[0]", "again")],
     {"neutral_pad": {"DM": (2, 0)}}, "PAD_BUS_BIT_CONNECTED_TWICE"),
    ([("DM[0]", "x")], {}, "PAD_BUS_PIN_UNDECLARED"),
    ([("DM[0]", "x"), ("DM[2]", "z")],
     {"neutral_pad": {"DM": (2, 0)}}, "PAD_BUS_PARTIALLY_CONNECTED"),
])
def test_bussed_pad_connection_refuses_when_the_pdk_cannot_prove_it(
        pairs, buses, rule):
    with pytest.raises(PAD.Refusal) as exc:
        PAD._named_connections("u_pad", "neutral_pad", pairs, buses)
    assert exc.value.rule == rule


def test_conflicting_pdk_bus_declarations_refuse_instead_of_taking_file_order():
    with pytest.raises(PAD.Refusal) as exc:
        PAD.io_bus_ports([
            "module neutral_pad(input [2:0] DM); endmodule\n",
            "module neutral_pad(input [0:2] DM); endmodule\n",
        ])
    assert exc.value.rule == "PAD_BUS_DECLARATION_CONFLICT"
