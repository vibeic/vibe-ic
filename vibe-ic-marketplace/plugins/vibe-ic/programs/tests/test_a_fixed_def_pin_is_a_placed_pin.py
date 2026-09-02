#!/usr/bin/env python3
"""A DEF PIN may be PLACED, FIXED or COVER — the pad-side check saw only one.

MEASURED. On a chip-path run whose padded ports' BTerms are written `+ FIXED`
(they are FIXED: they sit on a pad the ring placed, and nothing may move them),
`pad_side_constraint_check` reported

    VACUOUS_PASS: pad-side table present but no DEF pins matched its patterns

over 36 pins that were in the file. The same design with `+ PLACED` pins had
reported `PASS: all 36 constrained pin(s) are on the correct side`. The check
did not become wrong about a side — it stopped seeing its subject, and kept
saying PASS. That is the vacuity shape this repo refuses.

Both directions are pinned: a FIXED pin on the wrong side must still FAIL, or
this change has bought the green by widening the reader into a defaulter.
"""
from __future__ import annotations

import pad_side_constraint_check as PSC

DIE = 1000000


def _def(status: str, x: int, y: int) -> str:
    return ("VERSION 5.8 ;\nDESIGN chip_top ;\nUNITS DISTANCE MICRONS 2000 ;\n"
            f"DIEAREA ( 0 0 ) ( {DIE} {DIE} ) ;\n"
            "PINS 1 ;\n"
            "    - a + NET a + DIRECTION INPUT + USE SIGNAL\n"
            "      + PORT\n"
            "        + LAYER Metal5 ( 0 0 ) ( 100 100 )\n"
            f"        + {status} ( {x} {y} ) N ;\n"
            "END PINS\nEND DESIGN\n")


def test_every_def_placement_status_is_read():
    for status in ("PLACED", "FIXED", "COVER"):
        pins, die = PSC._parse_def_pins(_def(status, 500000, 1000))
        assert pins == {"a": (500000, 1000)}, f"{status} pin not read"
        assert die == (0, 0, DIE, DIE)


def test_a_fixed_pin_on_the_wrong_side_is_still_wrong():
    """THE CONTROL. The reader is wider; the verdict is not softer."""
    pins, die = PSC._parse_def_pins(_def("FIXED", 500000, 1000))
    assert PSC._side_of_pin(*pins["a"], die) == "S"
    pins, die = PSC._parse_def_pins(_def("FIXED", 500000, DIE - 1000))
    assert PSC._side_of_pin(*pins["a"], die) == "N"


def test_an_unplaced_pin_is_still_not_a_position():
    """A PIN record with no placement statement at all yields nothing —
    reading it as (0, 0) would put every unplaced pin on the south-west."""
    text = _def("PLACED", 1, 1).replace("        + PLACED ( 1 1 ) N ;", "        ;")
    pins, _die = PSC._parse_def_pins(text)
    assert pins == {}
