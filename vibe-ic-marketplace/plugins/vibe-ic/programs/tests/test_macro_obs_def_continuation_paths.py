#!/usr/bin/env python3
"""The obstruction gate must see the whole net, not its first wiring path.

DEF gives a special net's wiring as a sequence of PATHS. Only the first is
introduced by `+ ROUTED`; every later one is introduced by the bare keyword
`NEW`. Within a path, `*` means "the coordinate before it", and N points
describe N-1 segments.

`parse_routed_segments()` anchored on `+`, discarded any point containing `*`,
and read one point-pair per match. All three under-count, and they compound:
on a real routed DEF the gate parsed 2 of 57669 wire paths, found 0 crossings,
and exited 0 — a PASS on a layout with 45 of them.

The layout below is FIXED. Only its spelling changes. A gate whose answer
depends on which legal spelling of the same geometry it is handed is not
measuring the geometry.

Controls, in both directions:
  * the DEFECT form must go from a false PASS to the true count  (regression)
  * the fixture form and a genuinely clean layout must NOT move  (over-reach)
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROGRAMS = os.path.dirname(_HERE)


def _gate():
    p = os.path.join(_PROGRAMS, "macro_obs_geometry_intersect_check.py")
    spec = importlib.util.spec_from_file_location("_macro_obs_gate", p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_macro_obs_gate"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- the layout
# One macro, 100.0 x 60.0, full-footprint obstruction on its own layer, placed
# so that it occupies DEF units x[100000,200000] y[100000,160000].
LEF = """
MACRO big_ip
  SIZE 100.0 BY 60.0 ;
  OBS
    LAYER MET1 ;
      RECT 0 0 100.0 60.0 ;
  END
END big_ip
"""

N_THROUGH, N_CLEAR = 28, 12
_X1, _X2 = 0, 300000                      # spans the macro in x
_Y_THROUGH = [102000 + i * 2000 for i in range(N_THROUGH)]   # inside the macro
_Y_CLEAR = [300000 + i * 2000 for i in range(N_CLEAR)]       # nowhere near it


def _header(body: str) -> str:
    return f"""VERSION 5.8 ;
DESIGN t ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 400000 400000 ) ;
COMPONENTS 1 ;
- u_ip big_ip + PLACED ( 100000 100000 ) N ;
END COMPONENTS
SPECIALNETS 1 ;
{body}
END SPECIALNETS
END DESIGN
"""


def _def_one_entry_per_segment(ys) -> str:
    """The spelling the gate's own fixture uses: every segment its own net
    entry, every entry introduced by `+ ROUTED`."""
    rows = [f"- VDD ( * VDD )\n  + ROUTED MET1 480 + SHAPE FOLLOWPIN "
            f"( {_X1} {y} ) ( {_X2} {y} )\n  + USE POWER ;" for y in ys]
    return _header("\n".join(rows))


def _def_new_continuations(ys) -> str:
    """The spelling real place-and-route writers emit: ONE net entry whose
    first path is `+ ROUTED` and whose every later path is `NEW`, with the
    repeated coordinate written `*`."""
    paths = [f"  + ROUTED MET1 480 + SHAPE FOLLOWPIN "
             f"( {_X1} {ys[0]} ) ( {_X2} * )"]
    paths += [f"    NEW MET1 480 + SHAPE FOLLOWPIN "
              f"( {_X1} {y} ) ( {_X2} * )" for y in ys[1:]]
    return _header("- VDD ( * VDD )\n" + "\n".join(paths) + "\n  + USE POWER ;")


def _def_polyline(ys) -> str:
    """ONE path, many points: a serpentine whose horizontal legs are exactly
    the same follow-pins. N points describe N-1 segments.

    It reverses direction at each end so that every horizontal leg really
    traverses the full width — a staircase that only ever runs one way would
    make every leg after the first a zero-length stub and would be testing the
    fixture rather than the parser."""
    pts = [f"( {_X1} {ys[0]} )"]
    x = _X1
    for i, y in enumerate(ys):
        far = _X2 if x == _X1 else _X1
        pts.append(f"( {far} * )")            # the follow-pin at this y
        x = far
        if i + 1 < len(ys):
            pts.append(f"( * {ys[i + 1]} )")  # turn up to the next one
    return _header("- VDD ( * VDD )\n  + ROUTED MET1 480 + SHAPE FOLLOWPIN "
                   + " ".join(pts) + "\n  + USE POWER ;")


def _crossings(def_text: str) -> int:
    g = _gate()
    return len(g.audit(def_text, [LEF])["findings"])


# ------------------------------------------------------------------ the tests
ALL_YS = _Y_THROUGH + _Y_CLEAR


def test_new_continuation_paths_are_not_dropped():
    """THE DEFECT. Anchoring on `+` sees the first path and no other, so this
    layout reported nothing and the gate exited 0."""
    assert _crossings(_def_new_continuations(ALL_YS)) == N_THROUGH


def test_star_coordinate_is_the_previous_one_not_a_missing_one():
    """A point containing `*` was skipped outright. `*` is how an orthogonal
    segment is normally spelled, so skipping it discards ordinary metal."""
    g = _gate()
    segs = g.parse_routed_segments(_def_new_continuations(ALL_YS[:1]))
    assert len(segs) == 1
    s = segs[0]
    assert (s["x1"], s["x2"]) == (_X1, _X2)
    assert s["y1"] == s["y2"] == ALL_YS[0]


def test_a_path_is_a_polyline_not_its_first_leg():
    """N points are N-1 segments. Reading only the first pair reports on one
    leg and stays silent about the rest."""
    assert _crossings(_def_polyline(ALL_YS)) == N_THROUGH


def test_every_legal_spelling_of_one_layout_gives_one_answer():
    """The property, stated directly: the answer is a fact about the geometry,
    so it may not depend on which legal DEF spelling carries it."""
    answers = {
        "one-entry-per-segment": _crossings(_def_one_entry_per_segment(ALL_YS)),
        "NEW-continuations": _crossings(_def_new_continuations(ALL_YS)),
        "polyline": _crossings(_def_polyline(ALL_YS)),
    }
    assert set(answers.values()) == {N_THROUGH}, answers


# ------------------------------------------------- controls in the other way
def test_the_fixture_spelling_still_reads_the_same(  # REVERSE CASE
):
    """Must NOT move. This is the form the gate was written against; if the
    parser change altered it, the change is doing something other than what it
    claims."""
    assert _crossings(_def_one_entry_per_segment(ALL_YS)) == N_THROUGH


@pytest.mark.parametrize("spelling", [_def_one_entry_per_segment,
                                      _def_new_continuations,
                                      _def_polyline])
def test_metal_that_clears_the_macro_is_not_a_crossing(spelling):
    """REVERSE CASE, the one that matters most: a parser that recovered its
    count by flagging more things would pass every test above and be worse
    than the defect. Nothing here touches the obstruction; the answer is 0 in
    every spelling."""
    assert _crossings(spelling(_Y_CLEAR)) == 0


def test_a_def_with_no_special_nets_yields_nothing_rather_than_guessing():
    g = _gate()
    assert g.parse_routed_segments("VERSION 5.8 ;\nEND DESIGN\n") == []


# ------------------------------------------------- a via changes the layer
# LEF/DEF 5.8: "If you specify a via, layerName for the next routing coordinates
# (if any) is implicitly changed to the other routing layer for the via."
#
# Reading every point of a path under the HEAD layer therefore puts upper-layer
# metal on the lower layer. On a gate that BLOCKS, that is not a missed
# violation — it is an invented one, against an obstruction the metal never came
# near. A false accusation from a blocking gate costs more than a gap.

_VIAS = """VIAS 1 ;
- v12 + VIARULE VIA12 + CUTSIZE 260 260 + LAYERS MET1 VIA1 MET2
  + CUTSPACING 260 260 + ENCLOSURE 60 270 10 60 ;
END VIAS
"""


def _def_with_via(via_name: str = "v12", vias_section: str = _VIAS) -> str:
    """A path that approaches on MET1, rises through a via, and only THEN
    crosses the macro. The crossing metal is on MET2; the obstruction is on
    MET1; so the correct answer is zero crossings."""
    y = _Y_THROUGH[0]
    body = (f"- VDD ( * VDD )\n"
            f"  + ROUTED MET1 480 + SHAPE STRIPE ( {_X1} {y} ) ( 50000 * ) "
            f"{via_name} ( {_X2} * )\n  + USE POWER ;")
    return f"""VERSION 5.8 ;
DESIGN t ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 400000 400000 ) ;
{vias_section}COMPONENTS 1 ;
- u_ip big_ip + PLACED ( 100000 100000 ) N ;
END COMPONENTS
SPECIALNETS 1 ;
{body}
END SPECIALNETS
END DESIGN
"""


def test_metal_after_a_via_is_on_the_other_layer_not_the_head_layer():
    """THE FABRICATION CASE. The segment that crosses the macro is MET2 metal;
    the obstruction is MET1. Attributing it to the head layer reports a
    violation that does not exist."""
    g = _gate()
    segs = g.parse_routed_segments(_def_with_via())
    layers = [s["layer"] for s in segs]
    assert layers == ["MET1", "MET2"], layers
    assert _crossings(_def_with_via()) == 0


def test_the_vias_section_supplies_the_layer_pair():
    g = _gate()
    assert g.parse_via_layers(_def_with_via()) == {"v12": ("MET1", "MET2")}


def test_an_unresolvable_via_stops_rather_than_guessing_the_layer():
    """A via defined in the tech LEF is not in this DEF, so its layers are
    unknown. Continuing under the previous layer would attribute the metal to a
    layer it may not be on — the same fabrication, just quieter. Stop instead.

    STOPPING IS ONLY BETTER THAN GUESSING IF THE STOP IS VISIBLE. This test used
    to end at `_crossings(d) == 0` — which pins the FALSE-CLEAN answer: zero is
    also what a DEF with nothing to report gives, and the caller could not tell
    the two apart. So the assertion is now on the DISCLOSURE."""
    g = _gate()
    d = _def_with_via(via_name="via_from_tech_lef", vias_section="")
    segs, gaps = g.parse_routed_segments_with_gaps(d)
    assert [s["layer"] for s in segs] == ["MET1"]
    assert len(gaps) == 1, gaps
    assert gaps[0]["via"] == "via_from_tech_lef"
    assert gaps[0]["net"] == "VDD"
    assert gaps[0]["points_unread"] > 0
    rep = g.audit(d, [LEF])
    assert rep["findings"] == []
    assert rep["truncated_paths"] == gaps
    assert rep["unread_points"] == gaps[0]["points_unread"]


def test_def_keywords_in_a_path_are_not_read_as_vias():
    """`SHAPE`, `FOLLOWPIN`, `USE`, `POWER` occupy the same syntactic slot as a
    via name. Treating them as unresolvable vias abandons every path at its
    first keyword — which reads as a clean result."""
    assert _crossings(_def_new_continuations(ALL_YS)) == N_THROUGH


# ---------------------------------------------------------------------------
# AN INCOMPLETE READ MAY NOT EXIT LIKE A CLEAN ONE
#
# Driven through the REAL entry point (`main`, in a subprocess, on files on
# disk) rather than through `audit`, because the defect was in what the exit
# code and the printed verdict said — neither of which `audit` produces.
#
# ONE geometry, TWO legal spellings of the SAME via:
#   A) declared in the DEF's own VIAS section       -> resolvable
#   B) coming from the tech LEF, not in the DEF     -> unresolvable
# `M1M2_PR`-style tech-LEF vias are the ORDINARY case, so B is not a corner.
# This file already asserts that "the answer is a fact about the geometry, so it
# may not depend on which legal DEF spelling carries it". Before the disclosure
# it did: A said FAIL with 3 crossings, B said `[PASS] ... 1 supply segment(s)
# — none spans an obstruction` and exited 0, with three MET1 follow-pin legs
# running straight through the obstruction and nothing anywhere saying so.
# ---------------------------------------------------------------------------
_JOG_VIAS = """VIAS 1 ;
- vjog + VIARULE VIA12 + CUTSIZE 260 260 + LAYERS MET1 VIA1 MET2
  + CUTSPACING 260 260 + ENCLOSURE 60 270 10 60 ;
END VIAS
"""


def _def_followpin_jog(vias_section: str, via: str) -> str:
    """A follow-pin that rises through a via and comes straight back down — the
    ordinary way a PDN steps over an obstacle. After the second via it is on
    MET1 again, and its next three legs run the full width at y = 102000 /
    104000 / 106000, all inside the macro's obstruction."""
    pts = (f"( 0 102000 ) ( 20000 * ) {via} ( 30000 * ) {via} ( 300000 * ) "
           f"( * 104000 ) ( 0 * ) ( * 106000 ) ( 300000 * )")
    body = (f"- VDD ( * VDD )\n"
            f"  + ROUTED MET1 480 + SHAPE FOLLOWPIN {pts}\n  + USE POWER ;")
    return f"""VERSION 5.8 ;
DESIGN t ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 400000 400000 ) ;
{vias_section}COMPONENTS 1 ;
- u_ip big_ip + PLACED ( 100000 100000 ) N ;
END COMPONENTS
SPECIALNETS 1 ;
{body}
END SPECIALNETS
END DESIGN
"""


def _drive(tmp_path, def_text: str, tag: str):
    """Run the program the way CI runs it and give back (rc, stdout+stderr)."""
    cell = tmp_path / tag
    (cell / "phase3/stage3/pnr").mkdir(parents=True, exist_ok=True)
    (cell / "input/pdk").mkdir(parents=True, exist_ok=True)
    (cell / "phase3/stage3/pnr/routed.def").write_text(def_text)
    (cell / "input/pdk/macro.lef").write_text(LEF)
    prog = os.path.join(_PROGRAMS, "macro_obs_geometry_intersect_check.py")
    r = subprocess.run([sys.executable, prog, str(cell),
                        "--json", str(cell / "rep.json")],
                       capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr, json.loads(
        (cell / "rep.json").read_text())


def test_a_truncated_read_does_not_exit_like_a_clean_one(tmp_path):
    """THE DEFECT. rc was 0 and the line was an unqualified [PASS]."""
    rc, out, rep = _drive(
        tmp_path, _def_followpin_jog("", "via_from_tech_lef"), "unresolvable")
    assert rc == 2, f"rc={rc}\n{out}"
    assert "CANNOT DETERMINE" in out, out
    assert "NOT a pass" in out, out
    assert "ABANDONED" in out, out
    assert "via_from_tech_lef" in out, out
    assert len(rep["truncated_paths"]) == 1, rep
    assert rep["unread_points"] > 0, rep


def test_the_same_geometry_with_the_via_declared_reports_the_crossings(
        tmp_path):
    """The other spelling of the identical layout. Three MET1 follow-pin legs
    cross; the gate says so and blocks."""
    rc, out, rep = _drive(
        tmp_path, _def_followpin_jog(_JOG_VIAS, "vjog"), "resolvable")
    assert rc == 1, f"rc={rc}\n{out}"
    assert len(rep["findings"]) == 3, rep["findings"]
    assert all(f["layer"] == "MET1" and f["followpin"]
               for f in rep["findings"]), rep["findings"]
    assert rep["truncated_paths"] == [], rep


def test_a_complete_clean_read_still_passes_and_says_it_read_everything(
        tmp_path):
    """REVERSE CASE, and the one that stops this from being a way to make the
    gate stop answering: a DEF with nothing to report and nothing unread still
    exits 0 — and its PASS line states the abandonment count, so a reader never
    has to assume it."""
    rc, out, rep = _drive(tmp_path, _def_new_continuations(_Y_CLEAR), "clean")
    assert rc == 0, f"rc={rc}\n{out}"
    assert "[PASS]" in out, out
    assert "0 path(s) abandoned" in out, out
    assert "CANNOT DETERMINE" not in out, out
    assert rep["truncated_paths"] == [], rep
    assert rep["unread_points"] == 0, rep


def test_a_finding_still_blocks_when_the_read_was_also_incomplete(tmp_path):
    """rc=2 must not swallow a real violation. The crossings this gate DID find
    are still findings; the truncation only means the count is a floor, and the
    output has to say that rather than imply completeness."""
    # the jog's three crossing legs are readable (via declared), and a SECOND
    # net is abandoned at an unresolvable via.
    d = _def_followpin_jog(_JOG_VIAS, "vjog").replace(
        "SPECIALNETS 1 ;", "SPECIALNETS 2 ;").replace(
        "END SPECIALNETS",
        "- VSS ( * VSS )\n"
        "  + ROUTED MET1 480 + SHAPE FOLLOWPIN ( 0 300000 ) ( 10000 * ) "
        "other_tech_via ( 300000 * )\n  + USE GROUND ;\nEND SPECIALNETS")
    rc, out, rep = _drive(tmp_path, d, "both")
    assert rc == 1, f"rc={rc}\n{out}"
    assert len(rep["findings"]) == 3, rep["findings"]
    assert len(rep["truncated_paths"]) == 1, rep["truncated_paths"]
    # The disclosure moved from a closing sentence to the HEADLINE and to the
    # JSON, and this assertion follows it there rather than being relaxed: the
    # property under test ("the output has to say the count is a floor") is
    # unchanged, and it is now asserted in all three places the number is read
    # — the line a person quotes, the prose, and the field a machine parses.
    assert "at least 3 supply segment(s) SPAN" in out, out
    assert "THIS COUNT IS A FLOOR, NOT A TOTAL" in out, out
    assert rep["count_is_floor"] is True, rep
    assert "other_tech_via" in out, out
