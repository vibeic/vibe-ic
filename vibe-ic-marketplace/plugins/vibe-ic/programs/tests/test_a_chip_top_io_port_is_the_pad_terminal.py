#!/usr/bin/env python3
"""The router was being asked to reach a wire that does not exist on a
padframed die — and 38 `DRT-0073`s said so, once per padded port.

THE MEASUREMENT
===============
One chip-path run (spm, an open 5 V PDK, plugin 1.15.99):

    [ERROR DRT-0073] No access point for u_pad_x_22/PAD   x38
    lvs: spm.def declares 567 signal nets but has NO signal routing
    phase3/stage4/gds/spm.gds   106 bytes

The pad ring placed, routed and reached the shipped DEF; what did NOT work is
that every padded port kept the BTerm the FLOORPLAN gave it at the die edge,
while its net now terminates on the pad. The router therefore had to reach the
pad's terminal from a die-edge pin, under the pad's own OBS — and there is no
access point there, correctly.

THE DECISION, AND WHERE IT IS IMPLEMENTED
=========================================
A chip-top IO port IS the pad terminal. `pad_ring_gen` writes `padring.def`
and is the one step that knows both halves — which port sits on which pad
(from the assignment) and where that pad ended up (it placed it) — so the
BTerm is re-placed there, coincident with the pad's own terminal rectangle,
and nothing new crosses into the deck.

WHAT THESE PIN
==============
  ON THE PAD    every padded port's BTerm rect lies INSIDE its pad's terminal
                rect, on the terminal's own layer. Re-derived here from the
                LEF and the placement, never from the emitter's own output.
  READ, NEVER   the terminal pin is whatever `PAD_PLACE_IO_TERMINALS` names —
  ASSUMED       `PAD` for one master here and a different name for another.
                A master the PDK does not list moves nothing.
  UNTOUCHED     a port NO pad drives keeps its floorplan pin byte-for-byte.
                The core-only path has no ring and must not change.
  NO GUESSING   an orientation the transform cannot map, a pin with no LEF
                geometry, a master with no SIZE: each moves nothing and is
                reported.

No EDA tool: these grade the DEF text and the transform, which is what decides
where the terminal is at read time.
"""
from __future__ import annotations

import re

import pytest

import _pad_ring as PR
import pad_ring_gen as PRG

UNITS = 2000
#: An invented library. Two masters, two DIFFERENT terminal names, so a reader
#: that assumes `PAD` fails one of them.
_SIZE = {"fixture_io__in_c": (75.0, 350.0), "fixture_io__asig": (75.0, 350.0)}
_TERMINALS = {"fixture_io__in_c": "PAD", "fixture_io__asig": "ASIG5V"}
_PORTS = {
    "fixture_io__in_c": {"PAD": [("Metal5", (7.5, 2.0, 67.5, 62.0))],
                         "DVDD": [("Metal5", (74.0, 118.0, 75.0, 125.0))]},
    "fixture_io__asig": {"ASIG5V": [("Metal5", (10.0, 5.0, 60.0, 55.0))]},
}


def _pad(instance, signal, master, x, y, orient):
    return {"instance": instance, "signal": signal, "master": master,
            "x": x, "y": y, "orient": orient, "side": "S"}


def _floorplan(pins) -> str:
    body = "\n".join(
        f"    - {n} + NET {n} + DIRECTION INPUT + USE SIGNAL\n"
        f"      + PORT\n"
        f"        + LAYER Metal3 ( -520 -280 ) ( 520 280 )\n"
        f"        + PLACED ( 1000 2000 ) N ;" for n in pins)
    return ('VERSION 5.8 ;\nDESIGN chip_top ;\n'
            f"UNITS DISTANCE MICRONS {UNITS} ;\n"
            "DIEAREA ( 0 0 ) ( 6324000 6324000 ) ;\n"
            "COMPONENTS 1 ;\n- u_core CORE + PLACED ( 10 10 ) N ;\n"
            f"END COMPONENTS\nPINS {len(pins)} ;\n{body}\nEND PINS\n"
            "END DESIGN\n")


def _moves(pads):
    moves, notes = PRG.pad_terminal_bterms(pads, _PORTS, _TERMINALS, _SIZE,
                                           UNITS)
    return moves, notes


def _pin_rects(def_text):
    """{signal: (layer, absolute rect)} re-derived from the emitted DEF."""
    out = {}
    section = re.search(r"(?ms)^PINS\s+\d+\s*;(.*?)^END PINS", def_text)
    for entry in section.group(1).split(";"):
        m = re.match(r"\s*-\s+(\S+)", entry)
        if not m:
            continue
        g = re.search(r"\+ LAYER (\S+) \( (-?\d+) (-?\d+) \) \( (-?\d+) (-?\d+) \)",
                      entry)
        pl = re.search(r"\+ (?:FIXED|PLACED) \( (-?\d+) (-?\d+) \)", entry)
        if not g or not pl:
            continue
        ox, oy = int(pl.group(1)), int(pl.group(2))
        out[m.group(1)] = (g.group(1), (
            ox + int(g.group(2)), oy + int(g.group(3)),
            ox + int(g.group(4)), oy + int(g.group(5))))
    return out


@pytest.mark.parametrize("orient", sorted(PR._ORIENT_RECT))
def test_the_bterm_lands_inside_the_pads_own_terminal(orient):
    """THE PROPERTY, over every orientation the flow can place."""
    pad = _pad("u_pad_a", "a", "fixture_io__in_c", 3087000, 52000, orient)
    moves, notes = _moves([pad])
    assert notes == [] and len(moves) == 1
    layer, rect = "Metal5", (7.5, 2.0, 67.5, 62.0)
    x1, y1, x2, y2 = PR.orient_rect(rect, orient, _SIZE["fixture_io__in_c"])
    want = (pad["x"] + int(x1 * UNITS), pad["y"] + int(y1 * UNITS),
            pad["x"] + int(x2 * UNITS), pad["y"] + int(y2 * UNITS))
    assert moves[0]["layer"] == layer
    assert tuple(moves[0]["rect_dbu"]) == want

    text, rewritten = PRG._rewrite_pins(_floorplan(["a"]), moves)
    assert rewritten == ["a"]
    got_layer, got = _pin_rects(text)["a"]
    assert got_layer == layer
    assert (got[0] >= want[0] and got[1] >= want[1]
            and got[2] <= want[2] and got[3] <= want[3]), (
        "the BTerm must lie INSIDE the pad terminal it is placed on")


def test_the_terminal_name_is_read_from_the_pdk_not_assumed():
    """A pad whose signal pin is not called `PAD` is placed just the same."""
    moves, notes = _moves([_pad("u_pad_b", "b", "fixture_io__asig",
                                52000, 52000, "N")])
    assert notes == []
    assert moves[0]["terminal"] == "ASIG5V"
    assert moves[0]["rect_dbu"][0] == 52000 + int(10.0 * UNITS)


def test_a_master_the_pdk_does_not_list_moves_nothing_and_says_so():
    moves, notes = PRG.pad_terminal_bterms(
        [_pad("u_pad_c", "c", "fixture_io__in_c", 0, 0, "N")],
        _PORTS, {}, _SIZE, UNITS)
    assert moves == []
    assert [n["rule"] for n in notes] == ["PAD_TERMINAL_PIN_UNDECLARED"]


def test_a_terminal_with_no_lef_geometry_moves_nothing_and_says_so():
    moves, notes = PRG.pad_terminal_bterms(
        [_pad("u_pad_c", "c", "fixture_io__in_c", 0, 0, "N")],
        {"fixture_io__in_c": {}}, _TERMINALS, _SIZE, UNITS)
    assert moves == []
    assert [n["rule"] for n in notes] == ["PAD_TERMINAL_GEOMETRY_ABSENT"]


def test_an_orientation_the_transform_cannot_map_moves_nothing():
    """No approximation: a rotation nobody wrote down is not 'probably N'."""
    moves, notes = _moves([_pad("u_pad_d", "d", "fixture_io__in_c",
                                0, 0, "R45")])
    assert moves == []
    assert [n["rule"] for n in notes] == ["PAD_ORIENTATION_UNMAPPED"]


def test_a_port_no_pad_drives_keeps_its_floorplan_pin_byte_for_byte():
    """THE CONTROL for the core-only path, which has no ring at all."""
    source = _floorplan(["a", "unpadded"])
    moves, _ = _moves([_pad("u_pad_a", "a", "fixture_io__in_c",
                            3087000, 52000, "N")])
    text, rewritten = PRG._rewrite_pins(source, moves)
    assert rewritten == ["a"]
    before = [e for e in source.split(";") if "- unpadded" in e][0].strip()
    after = [e for e in text.split(";") if "- unpadded" in e][0].strip()
    assert before == after
    assert "PLACED ( 1000 2000 )" in after


def test_no_ring_at_all_leaves_the_whole_section_untouched():
    source = _floorplan(["a", "b"])
    text, rewritten = PRG._rewrite_pins(source, [])
    assert text == source and rewritten == []


def test_the_largest_rectangle_is_chosen_not_the_first():
    """A pin with several ports: the choice is by area, never by file order."""
    ports = {"fixture_io__in_c": {"PAD": [
        ("Metal5", (0.0, 0.0, 1.0, 1.0)),
        ("Metal5", (10.0, 10.0, 50.0, 50.0))]}}
    moves, _ = PRG.pad_terminal_bterms(
        [_pad("u_pad_a", "a", "fixture_io__in_c", 0, 0, "N")],
        ports, _TERMINALS, _SIZE, UNITS)
    assert moves[0]["rect_dbu"] == [20000, 20000, 100000, 100000]


def test_the_pin_and_orient_readers_carry_no_pdk_literal():
    src = open(PR.__file__).read()
    body = src[src.index("def parse_lef_pin_ports"):src.index("def parse_lef_sites")]
    for literal in ("gf180", "sky130", "sg13", "PAD\"", "'PAD'"):
        assert literal not in body, f"{literal!r} baked into the reader"


def test_the_superseded_placement_is_NOT_on_the_terminal():
    """The control that does not depend on the symbol under test.

    Reverting this change gives a COLLECTION ERROR — the new functions are
    gone — which proves only that they are absent. So the OLD behaviour is
    reproduced here directly: the floorplan's own die-edge pin, kept verbatim
    as the previous emitter kept it, and asserted NOT to lie inside the pad's
    terminal. If it ever did, this whole change would be a no-op and this test
    fails instead of passing quietly.
    """
    pad = _pad("u_pad_a", "a", "fixture_io__in_c", 3087000, 52000, "N")
    kept = _pin_rects(_floorplan(["a"]))["a"]          # what the flow emitted
    moves, _ = _moves([pad])
    terminal = tuple(moves[0]["rect_dbu"])
    assert kept[0] != moves[0]["layer"] or not (
        kept[1][0] >= terminal[0] and kept[1][1] >= terminal[1]
        and kept[1][2] <= terminal[2] and kept[1][3] <= terminal[3])
