#!/usr/bin/env python3
"""A pad cell has TWO faces, and the flow had been wiring the core to the
outward one.

THE MEASUREMENT
===============
Round 4 placed every padded port's BTerm on its pad's terminal, and the router
still reported 38 x `[ERROR DRT-0073] No access point for u_pad_*/PAD`. The
errors name the pad's ITerm: in `spm.def`, across all 36 pads, ONLY the `PAD`
pin appeared in any net and the pad's core face `Y` appeared in none — the core
and the bond pad were on ONE net, so the router had to reach the bond terminal
under the pad's own obstruction.

THE RULE, AND WHERE EVERY CLAUSE OF IT COMES FROM
=================================================
The core connects to the pad's CORE-SIDE pin; the port net terminates on the
bond terminal alone; the auxiliary pins are DECLARED, never silent. All of it
is read out of the IO library's own Liberty, so nothing is a naming convention:

    is_pad : true                  -> the bond terminal (not the name "PAD")
    Y  function : "((IE*PAD))"     -> Y is the core face, and IE enables it
    PAD function : "((A))"         -> A is the core-side driver
    PAD three_state : "((!OE))"    -> OE=1 drives, OE=0 is Hi-Z

An expression this cannot read, a master with no `is_pad`, more than one
candidate face, a pin the library gives no DIRECTION, corner Liberty views that
disagree, or an INOUT port with no declared direction: each REFUSES that port
BY NAME and leaves it exactly as it was.

Every remaining auxiliary input is tied. A tie the design declared is recorded
as declared; a tie nobody declared is tied inactive and recorded in
`aux_pins_defaulted` with its reason — a default that is written down is a
design decision the reviewer can see.

No EDA tool: these grade the role algebra and the emitted netlist text.
"""
from __future__ import annotations

import re

import pytest

import _pad_ring as PR
import io_pad_chip_top_gen as G

#: An invented library, in Liberty's own shape. Two masters: a receiver whose
#: core face is gated by an enable, and a bidirectional one.
_LIB = """
library (fixture) {
  cell ("fixture_io__in_c") {
    pin ("PU") {
      direction : "input";
    }
    pin ("PD") {
      direction : "input";
    }
    pin ("BOND") {
      is_pad : true;
      direction : "input";
    }
    pin ("Y") {
      function : "((BOND))";
      direction : "output";
    }
  }
  cell ("fixture_io__bi") {
    pin ("A") {
      direction : "input";
    }
    pin ("OE") {
      direction : "input";
    }
    pin ("IE") {
      direction : "input";
    }
    pin ("PU") {
      direction : "input";
    }
    pin ("BOND") {
      is_pad : true;
      direction : "inout";
      function : "((A))";
      three_state : "((!OE))";
    }
    pin ("Y") {
      function : "((IE*BOND))";
      direction : "output";
    }
  }
}
"""


def _cells():
    return PR.parse_liberty_pad_cells(_LIB)


def test_the_terminal_is_the_is_pad_pin_not_a_name():
    faces = PR.pad_cell_faces(_cells()["fixture_io__in_c"], "input")
    assert faces.refused == ""
    assert faces.terminal == "BOND" and faces.core_pin == "Y"


def test_an_input_port_takes_the_face_that_repeats_the_terminal():
    faces = PR.pad_cell_faces(_cells()["fixture_io__bi"], "input")
    assert faces.core_pin == "Y"
    assert faces.ties["IE"] == 1, "the enable of the core face must be asserted"
    assert faces.ties["OE"] == 0, "an input port must leave the terminal Hi-Z"


def test_an_output_port_drives_the_terminals_function_pin():
    faces = PR.pad_cell_faces(_cells()["fixture_io__bi"], "output")
    assert faces.core_pin == "A"
    assert faces.ties["OE"] == 1, "three_state ((!OE)) means OE=1 DRIVES"
    assert "enables the driver" in faces.reasons["OE"]


def test_every_auxiliary_pin_is_tied_and_every_tie_has_a_reason():
    faces = PR.pad_cell_faces(_cells()["fixture_io__bi"], "output")
    inputs = {p for p, r in _cells()["fixture_io__bi"].items()
              if r["direction"] == "input"} - {faces.core_pin}
    assert inputs <= set(faces.ties), "an untied pad input is an undefined chip"
    assert all(faces.reasons.get(p) for p in faces.ties)
    assert faces.reasons["PU"].startswith("DEFAULTED")
    assert not faces.reasons["OE"].startswith("DEFAULTED")


def test_the_design_can_declare_an_auxiliary_pin_and_is_recorded_as_declaring():
    faces = PR.pad_cell_faces(_cells()["fixture_io__in_c"], "input",
                              declared={"PU": 1})
    assert faces.ties["PU"] == 1
    assert faces.reasons["PU"] == "declared by the design"
    assert faces.reasons["PD"].startswith("DEFAULTED")


def test_a_pin_with_no_declared_role_refuses_the_port_by_name():
    """CONTROL (c). A role the library does not state is not inferred."""
    lib = _LIB.replace('pin ("PU") {\n      direction : "input";',
                       'pin ("PU") {', 1)
    cells = PR.parse_liberty_pad_cells(lib)
    faces = PR.pad_cell_faces(cells["fixture_io__in_c"], "input")
    assert faces.core_pin == ""
    assert "PU" in faces.refused and "not guessed" in faces.refused


def test_an_unreadable_expression_refuses_rather_than_approximating():
    lib = _LIB.replace('three_state : "((!OE))"', 'three_state : "((!OE)+CS)"')
    cells = PR.parse_liberty_pad_cells(lib)
    faces = PR.pad_cell_faces(cells["fixture_io__bi"], "output")
    assert faces.core_pin == "" and "three_state" in faces.refused


def test_a_bidirectional_port_with_no_declared_direction_is_refused():
    faces = PR.pad_cell_faces(_cells()["fixture_io__bi"], "inout")
    assert faces.core_pin == ""
    assert "declare which way it faces" in faces.refused


def test_a_master_with_no_is_pad_is_refused():
    lib = _LIB.replace("      is_pad : true;\n", "", 1)
    cells = PR.parse_liberty_pad_cells(lib)
    faces = PR.pad_cell_faces(cells["fixture_io__in_c"], "input")
    assert "bond terminal must be exactly one" in faces.refused


def test_corner_libraries_that_disagree_refuse_that_master_by_name():
    """A role is a property of the cell, not of the corner."""
    import pathlib, tempfile
    with tempfile.TemporaryDirectory() as td:
        a = pathlib.Path(td) / "tt.lib"
        b = pathlib.Path(td) / "ss.lib"
        a.write_text(_LIB)
        b.write_text(_LIB.replace('function : "((A))"', 'function : "((PU))"'))
        table, conflicts = G.merge_liberty_pad_cells([a, b])
        assert "fixture_io__bi" in conflicts
        assert "disagree" in conflicts["fixture_io__bi"]
        assert "fixture_io__in_c" in table


# ── CONTROL (b): the emitted netlist, graded ───────────────────────────────
_PORTS = [{"name": "clk", "direction": "input", "width": 1},
          {"name": "d", "direction": "input", "width": 2, "msb": 1, "lsb": 0},
          {"name": "q", "direction": "output", "width": 1}]


def _emit():
    cells = _cells()
    chosen, ordered = {}, {s: [] for s in G.SIDES}
    for port, direction, master in (("clk", "input", "fixture_io__in_c"),
                                    ("d[1]", "input", "fixture_io__in_c"),
                                    ("d[0]", "input", "fixture_io__in_c"),
                                    ("q", "output", "fixture_io__bi")):
        faces = PR.pad_cell_faces(cells[master], direction)
        assert faces.refused == ""
        inst = "u_pad_" + re.sub(r"\W", "_", port)
        chosen[inst] = {"port": port, "master": master, "direction": direction,
                        "terminal": faces.terminal, "core_pin": faces.core_pin,
                        "ties": faces.ties, "tie_reasons": faces.reasons}
        ordered["S"].append(inst)
    tie_cells = {
        0: {"master": "fixture_tie_low", "pin": "ZN"},
        1: {"master": "fixture_tie_high", "pin": "Z"},
    }
    return (G._emit_verilog("chip_top", "core", ordered, chosen, _PORTS,
                            ("VDD", "VSS"), tie_cells), chosen)


def test_the_emitted_netlist_puts_the_core_on_the_core_face():
    text, chosen = _emit()
    seen_tie_nets = set()
    for inst, rec in chosen.items():
        line = [l for l in text.splitlines() if f" {inst} (" in l][0]
        # the port net is on the terminal, and on nothing else
        assert f".{rec['terminal']}({rec['port']})" in line
        assert f".{rec['core_pin']}(" in line
        assert re.search(rf"\.{rec['core_pin']}\((\w+)__core", line), line
        # The ties are neither constants nor direct rails: they land on routed
        # signal nets driven by concrete PDK tie cells.
        for pin, level in rec["ties"].items():
            assert f".{pin}(1'b" not in line, (
                f"{pin} tied as a netlist constant on {inst}")
            match = re.search(rf"\.{pin}\((_vibeic_aux_tie_\d{{4}})\)", line)
            assert match, line
            tie_net = match.group(1)
            assert tie_net not in seen_tie_nets, (
                f"{inst}/{pin} shares tie driver net {tie_net}")
            seen_tie_nets.add(tie_net)
            assert f".{pin}({'VDD' if level else 'VSS'})" not in line
            assert rec["tie_reasons"].get(pin), f"{pin} tied with no reason"
            tie_master = "fixture_tie_high" if level else "fixture_tie_low"
            tie_pin = "Z" if level else "ZN"
            suffix = tie_net.rsplit("_", 1)[1]
            assert (f"{tie_master} _vibeic_aux_tie_cell_{suffix} "
                    f"(.{tie_pin}({tie_net}))") in text
    assert len(seen_tie_nets) == sum(
        len(rec["ties"]) for rec in chosen.values())


def test_an_auxiliary_control_without_derived_tie_cells_is_refused():
    """Negative control: a recorded tie may not remain prose-only/floating."""
    with pytest.raises(G.Refusal) as exc:
        cells = _cells()
        faces = PR.pad_cell_faces(cells["fixture_io__bi"], "output")
        chosen = {"u_pad_q": {
            "port": "q", "master": "fixture_io__bi", "direction": "output",
            "terminal": faces.terminal, "core_pin": faces.core_pin,
            "ties": faces.ties, "tie_reasons": faces.reasons,
        }}
        G._emit_verilog("chip_top", "core", {"S": ["u_pad_q"]}, chosen,
                        [_PORTS[-1]])
    assert exc.value.rule == "AUXILIARY_PAD_TIE_CELL_ABSENT"


def test_the_core_instance_takes_the_internal_nets_not_the_ports():
    text, _ = _emit()
    core = [l for l in text.splitlines() if " core u_core (" in l][0]
    assert ".clk(clk__core)" in core and ".d(d__core)" in core
    assert ".q(q__core)" in core
    assert "wire [1:0] d__core;" in text and "wire clk__core;" in text


def test_a_refused_port_keeps_the_single_net_shape():
    """CONTROL. A refusal changes nothing but the record."""
    chosen = {"u_pad_clk": {"port": "clk", "master": "fixture_io__in_c",
                            "direction": "input", "terminal": "BOND"}}
    text = G._emit_verilog("chip_top", "core", {"S": ["u_pad_clk"]}, chosen,
                           [_PORTS[0]])
    assert ".BOND(clk)" in text
    assert "clk__core" not in text
    assert ".clk(clk)" in [l for l in text.splitlines()
                           if " core u_core (" in l][0]
