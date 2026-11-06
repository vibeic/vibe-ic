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


















def _executable_source(path: str, start: str, stop: str) -> str:
    """The named span with COMMENTS AND DOCSTRINGS REMOVED.

    The distinction is load-bearing and it is the repo's own: a docstring may
    name a PDK because it is REPORTING a measurement made on one ("this
    library calls its terminal ASIG5V"), and that is evidence. LOGIC may not,
    because logic that names a PDK only works on that PDK. So the guard is
    applied to what executes.
    """
    import io
    import tokenize
    src = open(path).read()
    span = src[src.index(start):src.index(stop)]
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(span).readline):
        if tok.type == tokenize.COMMENT:
            continue
        if tok.type == tokenize.STRING and tok.line.strip().startswith(
                (chr(34) * 3, chr(39) * 3)):
            continue
        out.append(tok.string)
    return " ".join(out)


def test_the_pin_and_orient_readers_carry_no_pdk_literal():
    body = _executable_source(PR.__file__, "def parse_lef_pin_ports",
                              "def parse_lef_sites")
    # The union of both rounds' literal lists: the landed version's
    # single-quoted "'PAD'" is kept, because stripping docstrings is what
    # makes it pass here and a single-quoted PAD in LOGIC must still fail.
    for literal in ("gf180", "sky130", "sg13", chr(34) + "PAD" + chr(34),
                    chr(39) + "PAD" + chr(39), "GF_IO"):
        assert literal not in body, f"{literal!r} baked into the reader"


def test_the_pad_face_resolver_carries_no_pdk_literal_either():
    """The same guard over the rule the core-side wiring is decided by."""
    body = _executable_source(PR.__file__, "def parse_liberty_pad_cells",
                              "#: Every DEF orientation")
    for pin in ("PAD", "OE", "PU", "IE", "gf180", "sky130", "sg13"):
        assert chr(34) + pin + chr(34) not in body, (
            f"{pin!r} baked into the resolver")
