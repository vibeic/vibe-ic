#!/usr/bin/env python3
"""Excluding a net from routing is one step away from switching the router
off, and this module is the step.

WHY THE EXCLUSION EXISTS. On a padframed die the port net terminates ON the
bond pad, and the pad's OWN obstruction covers its terminal's footprint on
every layer below it — measured on one open 5 V IO library: M2, M3 and M4
under an M5 terminal, and the database carries the same 118 OBS boxes the
vendor LEF declares, so the flow did not draw them. No via can land, no access
point can exist, and TritonRoute says `DRT-0073 No access point` once per
padded port.

WHY IT IS NOT "TELLING THE ROUTER NOT TO LOOK". A net is excluded ONLY when
`pad_bterm_coincidence_check` has MEASURED, from the DEF and the master's own
LEF, that its BTerm and the pad's terminal share a rectangle on one layer that
is at least as wide and as tall as that layer's own minimum width. Per net.
A net it cannot decide, or decides against, stays in the router.

THE CONTROL THAT MATTERS is the reverse one: move a BTerm off its pad and the
verdict must flip and the net must go back to the router. Measured end to end
on the real design, `pin_access` on the same tree:

    36 measured CONNECTED  -> 36 excluded -> [INFO DRT-0166] Complete pin access.
    rst's BTerm moved 1 mm -> 35 excluded -> [ERROR DRT-0073] No access point
                                             for u_pad_rst/PAD, and only it.
"""
from __future__ import annotations

import json

import pad_bterm_coincidence_check as C
import phase3_one_shot_runner as R

UNITS = 2000
MINW = {"Metal5": 800, "Metal4": 560}


def _pin(layer, rect):
    return {"net": "n", "layer": layer, "rect": list(rect), "placement": None}


def test_the_same_rectangle_on_the_same_layer_is_connected():
    v, why, ov = C.decide(_pin("Metal5", (0, 0, 120000, 120000)),
                          "Metal5", [0, 0, 120000, 120000], MINW["Metal5"])
    assert v == "CONNECTED" and ov == [0, 0, 120000, 120000]
    assert "minimum width" in why


def test_a_different_layer_is_never_connected():
    v, why, _ = C.decide(_pin("Metal4", (0, 0, 120000, 120000)),
                         "Metal5", [0, 0, 120000, 120000], MINW["Metal5"])
    assert v == "NOT_CONNECTED" and "do not touch" in why


def test_no_overlap_is_not_connected():
    v, _w, ov = C.decide(_pin("Metal5", (0, 0, 1000, 1000)),
                         "Metal5", [500000, 0, 620000, 120000], MINW["Metal5"])
    assert v == "NOT_CONNECTED" and ov is None


def test_a_touch_narrower_than_the_layer_minimum_is_not_a_conductor():
    """THE POINT OF THE MEASUREMENT. One database unit of overlap is not a
    connection, and a program that accepted it would be declaring, not
    measuring."""
    v, why, ov = C.decide(_pin("Metal5", (0, 0, 120000, 120000)),
                          "Metal5", [119900, 0, 240000, 120000],
                          MINW["Metal5"])
    assert v == "NOT_CONNECTED" and ov == [119900, 0, 120000, 120000]
    assert "minimum width" in why


def test_a_layer_with_no_stated_minimum_width_is_undecided_not_assumed():
    v, why, _ = C.decide(_pin("Metal5", (0, 0, 120000, 120000)),
                         "Metal5", [0, 0, 120000, 120000], None)
    assert v == "UNDECIDED" and "cannot be answered" in why


def test_a_pin_with_no_rectangle_is_undecided():
    v, _w, _o = C.decide({"net": "n", "layer": None, "rect": None},
                         "Metal5", [0, 0, 1, 1], MINW["Metal5"])
    assert v == "UNDECIDED"


def test_the_minimum_widths_come_from_the_tech_lef():
    tech = ("LAYER Metal4\n  TYPE ROUTING ;\n  WIDTH 0.28 ;\nEND Metal4\n"
            "LAYER Metal5\n  TYPE ROUTING ;\n  WIDTH 0.44 ;\nEND Metal5\n")
    got = C.layer_min_widths(tech, UNITS)
    assert got["Metal5"] == 880 and got["Metal4"] == 560


# ── the deck consumer ──────────────────────────────────────────────────────
def _report(connected, not_connected=(), undecided=()):
    rows = [{"net": n, "verdict": "CONNECTED", "pin_layer": "Metal5",
             "overlap": [0, 0, 1, 1], "instance": "u_pad_" + n,
             "terminal": "BOND"} for n in connected]
    rows += [{"net": n, "verdict": "NOT_CONNECTED"} for n in not_connected]
    rows += [{"net": n, "verdict": "UNDECIDED"} for n in undecided]
    return json.dumps({"connected_nets": list(connected),
                       "not_connected_nets": list(not_connected),
                       "undecided_nets": list(undecided), "nets": rows})


def test_the_deck_excludes_exactly_the_measured_nets():
    tcl, names = R._padring_bterm_exclusion_tcl(
        _report(["a", "b[0]"], not_connected=["c"], undecided=["d"]))
    assert names == ["a", "b[0]"]
    assert tcl.count("setSpecial") == 2
    assert "{b[0]}" in tcl, "a bus name must reach Tcl as one word"
    assert "findNet {c}" not in tcl and "findNet {d}" not in tcl


def test_a_net_the_check_could_not_decide_is_never_excluded():
    tcl, names = R._padring_bterm_exclusion_tcl(_report([], undecided=["a"]))
    assert names == [] and tcl == ""


def test_no_measurement_means_a_byte_identical_deck():
    """A design with no pad ring must emit the deck it emitted before."""
    for text in ("", "not json", _report([])):
        tcl, names = R._padring_bterm_exclusion_tcl(text)
        assert tcl == "" and names == []


def test_the_consumer_reads_names_and_never_a_class():
    """The guard against the failure this whole module exists to prevent:
    the deck builder must not be able to exclude 'the port nets'."""
    src = open(R.__file__).read()
    body = src[src.index("def _padring_bterm_exclusion_tcl"):
               src.index("def _tcl_quote")]
    assert "connected_nets" in body
    assert "getBTerms" not in body, (
        "excluding every net that has a BTerm is excluding a CLASS")
    assert "not_connected" not in body.split('"""')[2]
