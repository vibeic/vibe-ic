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

import pytest

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


# ══ the conflict direction, at THIS program's own call sites ════════════════
#
# `run()` folds the discovered IO LEFs through `merge_source_records` and
# writes `on_conflict="richer"` at each fold. `policy_direction_pin_check`
# reported both surviving sites UNPINNED on b309595f06: flipping the literal to
# `"sparser"` changed nothing any test could see, because every test above
# drives `decide()` — one source, no fold at all.
#
# The shape that reaches the parameter is narrow and it is the reason the gap
# existed. One full LEF and one SILENT LEF produces exactly one `distinct`
# record and `merge_source_records` returns it on its `len(distinct) == 1`
# line, several lines before `on_conflict` is read. Only TWO LEFs that both
# SPEAK about the same macro and disagree reach the branch the literal
# controls, so that is what these two build — through `run()`, the program's
# own entry point, never by calling the helper.
#
# Each asserts the same three things: the RICHER record wins, the answer is the
# same in BOTH discovery orders, and it is NOT the answer `"sparser"` would
# have given. The third clause is the one a flip kills.

_M5_TECH = "LAYER Metal5\n  TYPE ROUTING ;\n  WIDTH 0.400 ;\nEND Metal5\n"


def _io_macro(name, w, h, pins):
    """One LEF MACRO with a SIZE and the PORT rectangles it presents."""
    body = [f"MACRO {name}", "  CLASS PAD INOUT ;",
            f"  SIZE {w:.3f} BY {h:.3f} ;"]
    for pin, rects in pins:
        body += [f"  PIN {pin}", "    DIRECTION INOUT ;", "    USE SIGNAL ;",
                 "    PORT"]
        for layer, r in rects:
            body += [f"      LAYER {layer} ;",
                     "      RECT %.3f %.3f %.3f %.3f ;" % r]
        body += ["    END", f"  END {pin}"]
    return "\n".join(body + [f"END {name}", ""])


def _def(orient, pin_rect):
    """A one-pad, one-port DEF: the pad at (20000, 20000), the die-edge BTerm
    where the caller says. Absolute DEF units; `def_pins` adds the PLACED
    origin, so `pin_rect` is stated relative to it exactly as a DEF does."""
    x1, y1, x2, y2 = pin_rect
    return (f"VERSION 5.8 ;\nDESIGN top ;\n"
            f"UNITS DISTANCE MICRONS {UNITS} ;\n"
            f"DIEAREA ( 0 0 ) ( 400000 400000 ) ;\n"
            f"COMPONENTS 1 ;\n"
            f"- u_pad tl__bi + PLACED ( 20000 20000 ) {orient} ;\n"
            f"END COMPONENTS\n"
            f"PINS 1 ;\n"
            f"- sig + NET sig + LAYER Metal5 ( {x1} {y1} ) ( {x2} {y2} )"
            f" + PLACED ( 20000 20000 ) N ;\n"
            f"END PINS\n"
            f"NETS 1 ;\n- sig ( PIN sig ) ( u_pad PAD ) ;\nEND NETS\n"
            f"END DESIGN\n")


def _shared_supply(tmp_path, section, connection, port_x):
    """Two supply pads share a rail; only geometry identifies the BTerm's pad."""
    lef = tmp_path / "rail.lef"
    lef.write_text(_io_macro("rail_bridge", 60.0, 100.0,
                            [("RAIL", [("Metal5", (1, 1, 3, 3))])])
                   .replace("CLASS PAD INOUT", "CLASS PAD POWER")
                   .replace("USE SIGNAL", "USE POWER"))
    text = f"""VERSION 5.8 ;
DESIGN neutral_top ;
UNITS DISTANCE MICRONS {UNITS} ;
DIEAREA ( 0 0 ) ( 400000 400000 ) ;
COMPONENTS 2 ;
- rail_left rail_bridge + FIXED ( 20000 20000 ) N ;
- rail_right rail_bridge + FIXED ( 120000 20000 ) N ;
END COMPONENTS
PINS 1 ;
- supply_port + NET supply + USE POWER
  + LAYER Metal5 ( 2000 2000 ) ( 6000 6000 )
  + PLACED ( {port_x} 20000 ) N ;
END PINS
{section} 1 ;
- supply ( PIN supply_port ) {connection} + USE POWER ;
END {section}
END DESIGN
"""
    return C.run(text, _M5_TECH, [lef])


@pytest.mark.parametrize("section", ["NETS", "SPECIALNETS"])
@pytest.mark.parametrize("port_x,instance", [(20000, "rail_left"),
                                           (120000, "rail_right")])
def test_wildcard_supply_joins_every_matching_pin_and_measures_the_pad(
        tmp_path, section, port_x, instance):
    rc, report = _shared_supply(tmp_path, section, "( * RAIL )", port_x)
    assert report["n_ports_on_a_pad"] == 1
    assert rc == 0 and report["connected_nets"] == ["supply"]
    assert report["nets"][0]["instance"] == instance
    assert report["nets"][0]["terminal"] == "RAIL"


@pytest.mark.parametrize("section", ["NETS", "SPECIALNETS"])
def test_explicit_supply_joins_choose_the_coincident_pad(tmp_path, section):
    rc, report = _shared_supply(
        tmp_path, section, "( rail_left RAIL ) ( rail_right RAIL )", 120000)
    assert rc == 0 and report["connected_nets"] == ["supply"]
    assert report["n_ports_on_a_pad"] == 1
    assert report["nets"][0]["instance"] == "rail_right"


@pytest.mark.parametrize("connection", ["( * RAIL )",
                                       "( rail_left RAIL ) ( rail_right RAIL )"])
def test_supply_connectivity_without_a_coincident_pad_still_refuses(
        tmp_path, connection):
    rc, report = _shared_supply(tmp_path, "SPECIALNETS", connection, 220000)
    assert report["connected_nets"] == []
    assert rc == 2 or report["not_connected_nets"] == ["supply"]
    assert all(r["verdict"] == "NOT_CONNECTED" for r in report["nets"])


def test_a_coincident_endcap_is_not_a_supply_pad(tmp_path):
    lef = tmp_path / "roles.lef"
    lef.write_text(_io_macro("tl__bi", 60, 100,
                            [("PAD", [("Metal5", (1, 1, 3, 3))])])
                   .replace("CLASS PAD INOUT", "CLASS ENDCAP BOTTOMLEFT")
                   + _io_macro("rail_bridge", 60, 100,
                               [("PAD", [("Metal5", (1, 1, 3, 3))])]))
    text = _def("N", (2000, 2000, 6000, 6000))
    text = text.replace("COMPONENTS 1 ;", "COMPONENTS 2 ;")
    text = text.replace("END COMPONENTS", "- proper_pad rail_bridge + FIXED "
                        "( 120000 20000 ) N ;\nEND COMPONENTS")
    text = text.replace("( u_pad PAD )", "( u_pad PAD ) ( proper_pad PAD )")
    _rc, report = C.run(text, _M5_TECH, [lef])
    assert report["connected_nets"] == []
    assert report["not_connected_nets"] == ["sig"]
    assert report["nets"][0]["instance"] == "proper_pad"


def test_routed_wildcard_coordinate_is_not_a_component_pin():
    text = """SPECIALNETS 1 ;
- supply ( * RAIL ) + ROUTED Metal5 100 ( 2000 4000 ) ( * 9000 ) ;
END SPECIALNETS
"""
    assert C.def_net_terminals(text) == {"supply": [("*", "RAIL")]}


def test_subnet_terminal_connections_still_belong_to_the_parent_net():
    text = """NETS 1 ;
- supply ( PIN port ) + SUBNET branch ( pad RAIL )
  + ROUTED Metal5 ( 2000 4000 ) ( * 9000 ) ;
END NETS
"""
    assert C.def_net_terminals(text) == {"supply": [("pad", "RAIL")]}


def test_wildcard_coincidence_reads_a_checked_in_io_outline(tmp_path):
    """The stored IO abstracts have sizes/classes, but omit pin ports.

    Reuse an actual outline with a synthetic terminal for this geometry control;
    this does not claim the synthetic terminal is a native PDK pin.
    """
    from programs.tests._hostpaths import require_repo
    root = require_repo("vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
                        "tests", "fixtures", "u22_perc_sweep_lef_class")
    source = next(p for p in sorted(root.rglob("*.lef"))
                  if any(c.split()[0] == "PAD" for c in
                         C.PR.parse_lef_macro_classes(p.read_text()).values()))
    text = source.read_text()
    sizes = C.PR.parse_lef_macros(text)
    master = next(iter(sizes))
    terminal, layer, rectangle = "TERMINAL", "Metal5", (1, 1, 3, 3)
    lef = tmp_path / "outlined-pad.lef"
    pin = (f"  PIN {terminal}\n    PORT\n      LAYER {layer} ;\n"
           f"      RECT 1 1 3 3 ;\n    END\n  END {terminal}\n")
    lef.write_text(text.replace(f"END {master}", pin + f"END {master}"))
    rect = [round(v * UNITS) for v in rectangle]
    step = round((sizes[master][0] + 100) * UNITS)
    point = 20000 + step
    tech = (f"LAYER {layer}\n TYPE ROUTING ;\n WIDTH "
            f"{min(rectangle[2]-rectangle[0], rectangle[3]-rectangle[1])/2} ;\n"
            f"END {layer}\n")
    native_lef_def = f"""VERSION 5.8 ;
DESIGN neutral_top ;
UNITS DISTANCE MICRONS {UNITS} ;
DIEAREA ( 0 0 ) ( {2*point} {2*point} ) ;
COMPONENTS 2 ;
- first_pad {master} + PLACED ( 20000 20000 ) N ;
- second_pad {master} + PLACED ( {point} 20000 ) N ;
END COMPONENTS
PINS 1 ;
- port + NET rail + LAYER {layer} ( {rect[0]} {rect[1]} ) ( {rect[2]} {rect[3]} )
 + PLACED ( {point} 20000 ) N ;
END PINS
SPECIALNETS 1 ;
- rail ( PIN port ) ( * {terminal} ) + USE POWER ;
END SPECIALNETS
END DESIGN
"""
    rc, report = C.run(native_lef_def, tech, [lef])
    assert rc == 0 and report["connected_nets"] == ["rail"]
    assert report["nets"][0]["instance"] == "second_pad"


def _both_orders(tmp_path, def_text, lef_a, lef_b):
    """`run()` over the two LEFs in each discovery order."""
    a = tmp_path / "a_first.lef"
    z = tmp_path / "z_second.lef"
    a.write_text(lef_a)
    z.write_text(lef_b)
    fwd = C.run(def_text, _M5_TECH, [a, z])
    rev = C.run(def_text, _M5_TECH, [z, a])
    return fwd, rev


def test_the_richer_pin_port_map_decides_which_terminal_is_measured(tmp_path):
    """SITE 1 — the `parse_lef_pin_ports` fold.

    Two libraries describe `tl__bi`, and both SPEAK: one gives it two pins and
    puts `PAD` at (1,1)-(3,3), the other gives it one pin and puts `PAD` at
    (40,40)-(42,42). The DEF's BTerm sits on the first. The fuller map is the
    one that keeps the terminal the design was built against; the sparser one
    moves it 39 um away and the same net reads NOT_CONNECTED — and a net this
    program does not measure CONNECTED is a net the router is still asked to
    reach.
    """
    lef_full = _io_macro("tl__bi", 60.0, 100.0,
                         [("PAD", [("Metal5", (1.0, 1.0, 3.0, 3.0))]),
                          ("VSS", [("Metal5", (9.0, 9.0, 10.0, 10.0))])])
    lef_poor = _io_macro("tl__bi", 60.0, 100.0,
                         [("PAD", [("Metal5", (40.0, 40.0, 42.0, 42.0))])])
    def_text = _def("N", (2000, 2000, 6000, 6000))

    (rc_f, fwd), (rc_r, rev) = _both_orders(
        tmp_path, def_text, lef_full, lef_poor)

    assert fwd == rev, "the verdict depends on the order the LEFs were read"
    assert rc_f == rc_r == 0
    assert fwd["connected_nets"] == ["sig"], (
        "the richer (2-pin) library did not win the disagreement")
    assert fwd["nets"][0]["terminal_rect"] == [22000, 22000, 26000, 26000]
    # The control: the poorer library's own answer, so the assertion above is
    # a statement about WHICH source won and not about the fixture.
    only_poor = tmp_path / "only_poor.lef"
    only_poor.write_text(lef_poor)
    _rc, poor_alone = C.run(def_text, _M5_TECH, [only_poor])
    assert poor_alone["not_connected_nets"] == ["sig"], (
        "precondition: the two libraries really do read differently")
    assert fwd["connected_nets"] != poor_alone["connected_nets"]


def test_the_richer_macro_size_decides_where_the_terminal_lands(tmp_path):
    """SITE 2 — the `parse_lef_macros` fold, which is a SIZE and nothing else.

    A macro record here is a `(width, height)` pair, so "more content" is not
    what separates the two policies: both are total orders over the same fixed
    arity and `"richer"` takes the larger of them. That is still a DIRECTION,
    and it is still observable — the pad is placed `S`, so `orient_rect`
    reflects the terminal through the master's own width and a 20 um
    disagreement about that width moves the measured terminal 40 um.

    Both libraries give `tl__bi` the same PORT rectangle. Only the SIZE
    disagrees, so this site is measured on its own.
    """
    pins = [("PAD", [("Metal5", (1.0, 1.0, 3.0, 3.0))])]
    lef_wide = _io_macro("tl__bi", 80.0, 100.0, pins)
    lef_narrow = _io_macro("tl__bi", 60.0, 100.0, pins)
    # orient S maps x -> (w - x2, w - x1): w=80 puts the terminal at 77..79 um,
    # w=60 at 57..59 um. The BTerm is placed on the first.
    def_text = _def("S", (154000, 194000, 158000, 198000))

    (rc_f, fwd), (rc_r, rev) = _both_orders(
        tmp_path, def_text, lef_wide, lef_narrow)

    assert fwd == rev, "the verdict depends on the order the LEFs were read"
    assert rc_f == rc_r == 0
    assert fwd["connected_nets"] == ["sig"], (
        "the wider (richer) SIZE record did not win the disagreement"
    )
    assert fwd["nets"][0]["terminal_rect"] == [174000, 214000, 178000, 218000]
    only_narrow = tmp_path / "only_narrow.lef"
    only_narrow.write_text(lef_narrow)
    _rc, narrow_alone = C.run(def_text, _M5_TECH, [only_narrow])
    assert narrow_alone["not_connected_nets"] == ["sig"], (
        "precondition: the two SIZE records really do read differently")
    assert fwd["connected_nets"] != narrow_alone["connected_nets"]


# ── a tool ring writes its port nets as SPECIAL ────────────────────────────
_IO_LEF = """MACRO PADX
  CLASS PAD INPUT ;
  SIZE 75 BY 350 ;
  PIN PAD
    DIRECTION INOUT ;
    PORT
      LAYER Metal5 ;
        RECT 7.5 290 67.5 350 ;
    END
  END PAD
END PADX
"""
_TECH = "LAYER Metal5\n  TYPE ROUTING ;\n  WIDTH 0.44 ;\nEND Metal5\n"


def _ring_def(section):
    """One pad at the origin, its port BTerm on the bond terminal; the port net
    listed in `section` (OpenROAD place_io_terminals writes SPECIALNETS)."""
    body = "    - clk ( PIN clk ) ( u_pad_clk PAD ) + USE SIGNAL ;\n"
    nets = f"{section} 1 ;\n{body}END {section}\n"
    return ("VERSION 5.8 ;\nDESIGN chip_top ;\nUNITS DISTANCE MICRONS 2000 ;\n"
            "DIEAREA ( 0 0 ) ( 2000000 2000000 ) ;\n"
            "COMPONENTS 1 ;\n    - u_pad_clk PADX + FIXED ( 0 0 ) N ;\nEND COMPONENTS\n"
            "PINS 1 ;\n    - clk + NET clk + SPECIAL + DIRECTION INPUT + USE SIGNAL\n"
            "      + PORT\n        + LAYER Metal5 ( -60000 -60000 ) ( 60000 60000 )\n"
            "        + FIXED ( 75000 640000 ) N ;\nEND PINS\n" + nets + "END DESIGN\n")


def test_a_port_net_the_tool_wrote_as_special_is_still_measured(tmp_path):
    lef = tmp_path / "io.lef"
    lef.write_text(_IO_LEF)
    for section in ("NETS", "SPECIALNETS"):
        rc, report = C.run(_ring_def(section), _TECH, [lef])
        assert (rc, report["n_ports_on_a_pad"]) == (0, 1), section
        assert report["connected_nets"] == ["clk"], section


def test_a_special_net_off_its_pad_still_goes_back_to_the_router(tmp_path):
    lef = tmp_path / "io.lef"
    lef.write_text(_IO_LEF)
    moved = _ring_def("SPECIALNETS").replace("( 75000 640000 )", "( 1500000 1500000 )")
    rc, report = C.run(moved, _TECH, [lef])
    assert report["connected_nets"] == [] and report["not_connected_nets"] == ["clk"]
