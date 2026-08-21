"""#626 — M1 picked the DEF that describes the design BY ALPHABETICAL ORDER.

#612 gave M1 its missing placement half: read the macro positions out of the
design's own DEF `COMPONENTS` and instantiate the macros there. It picked WHICH
DEF by walking ``sorted(pnr_dir.glob("*.def"))`` and taking the first entry that
placed anything.

A PnR directory holds one DEF per stage — floorplan, macro_placed, placed,
post_cts, post_hold, routed, routed_preantenna, filled, and the design's own —
and an earlier iteration's DEF is still on disk with the macros somewhere else.
They do not all agree. Measured on a real run (IHP SG13G2 `u_hawaii_adc`), nine
DEFs, eight agreeing, and the glob returned the ninth:

    u_hawaii_adc.def   - u_ds1 delta_sigma + FIXED ( 30080 439350 ) N
                       ^ the DEF the sign-off GDS was streamed FROM
                         (orchestrator record: `stream_tail: file=u_hawaii_adc.def`)
    filled.def         - u_ds1 delta_sigma + FIXED ( 15080 760610 ) FS
                       ^ taken, because "f" sorts first

    merge.log:  KLAYOUT_MERGE_PLACED delta_sigma u_ds1 FS 15.08 760.61

so the analog macros were instantiated 15.0 x 321.3 um from where the digital
layout they were merged INTO carries them, one of them mirrored — and the merged
GDS came back with one clean top cell while being wrong. This is the exact
failure the orientation guard beside it was written to prevent ("a placement at
the wrong orientation is worse than none: it looks integrated and is not"),
reached one level up, through the choice of file.

`gds_port_label_check` — the OTHER half of the same landed change — already
pairs a layout with a DEF by the design's own name, and its docstring says so in
as many words: "THE DEF AND THE GDS ARE PAIRED BY THE DESIGN'S OWN NAME, never
by directory position." That rule was private to it. It is now `def_rank` in
`def_gds_port_power_restore`, and BOTH consumers call it, so the flow cannot
hold two answers to "which DEF describes this layout".

DISAGREEMENT IS DISCLOSED, NOT SILENTLY RESOLVED. Every other DEF that places
the same macros is still parsed and compared, and any that puts them elsewhere
is named in `macro_placements.json`. A stale DEF sitting next to a live one is a
real fact about the project; picking correctly and saying nothing would leave
the next reader with no way to see it. It is a DISCLOSURE and not a REFUSAL,
because a refusal means a macro was not placed and this merge placed them all.

NEGATIVE CONTROL. `test_the_stale_def_is_not_the_one_chosen` and
`test_the_chosen_def_is_recorded_in_the_artefact` both FAIL against the pre-fix
`resolve_macro_placements` (which returns filled.def's coordinates, and returns
no `def_source` at all). Run in both directions before landing.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load("def_gds_port_power_restore")
M = _load("mixed_signal_top_lvs_run")

#: The macros this fixture's DEFs place. Names are the fixture's own; nothing in
#: the code under test knows them.
_CELLS = ["blk_a", "blk_b"]

_LIVE = """DESIGN top_design ;
UNITS DISTANCE MICRONS 1000 ;
COMPONENTS 2 ;
    - u_a1 blk_a + FIXED ( 30080 439350 ) N ;
    - u_b1 blk_b + FIXED ( 15080 1103370 ) N ;
END COMPONENTS
"""

#: Same design, same instances, DIFFERENT positions and one flipped — an earlier
#: iteration left on disk. This is the file the pre-fix glob returned.
_STALE = """DESIGN top_design ;
UNITS DISTANCE MICRONS 1000 ;
COMPONENTS 2 ;
    - u_a1 blk_a + FIXED ( 15080 760610 ) FS ;
    - u_b1 blk_b + FIXED ( 15080 1103370 ) N ;
END COMPONENTS
"""


def _project(tmp_path, **defs):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    for name, text in defs.items():
        (pnr / name.replace("__", ".")).write_text(text)
    return tmp_path


# ── the shared rule ─────────────────────────────────────────────────────────
def test_the_designs_own_def_outranks_every_stage_def():
    P = pathlib.Path
    ranked = sorted([P("filled.def"), P("routed.def"), P("placed.def"),
                     P("top_design.def"), P("floorplan.def")],
                    key=lambda p: R.def_rank(p, "top_design"))
    assert [p.name for p in ranked][0] == "top_design.def", ranked


def test_without_a_design_name_only_the_preference_order_applies():
    P = pathlib.Path
    ranked = sorted([P("zzz.def"), P("routed.def"), P("filled.def")],
                    key=lambda p: R.def_rank(p, None))
    assert [p.name for p in ranked] == ["filled.def", "routed.def", "zzz.def"]


def test_the_label_check_and_the_merge_share_ONE_rule():
    """Not "both have a rule that agrees today" — the SAME object."""
    G = _load("gds_port_label_check")
    assert G._def_rank is R.def_rank


# ── the defect ──────────────────────────────────────────────────────────────
def test_the_stale_def_is_not_the_one_chosen(tmp_path):
    """The pre-fix glob returns filled.def because "f" sorts first."""
    p = _project(tmp_path, filled__def=_STALE, top_design__def=_LIVE)
    res = M.resolve_macro_placements_detailed(p, _CELLS, "top_design")
    a1 = [q for q in res["placements"]["blk_a"] if q["inst"] == "u_a1"][0]
    assert (a1["x_um"], a1["y_um"], a1["orient"]) == (30.08, 439.35, "N"), a1


def test_the_chosen_def_is_recorded_in_the_artefact(tmp_path):
    """`merge.json` recorded the coordinates but never the FILE, so nothing in
    the artefact could be audited for this."""
    p = _project(tmp_path, filled__def=_STALE, top_design__def=_LIVE)
    res = M.resolve_macro_placements_detailed(p, _CELLS, "top_design")
    assert res["def_source"] == "top_design.def", res
    assert set(res["defs_considered"]) == {"top_design.def", "filled.def"}


def test_a_disagreeing_sibling_def_is_disclosed_by_name(tmp_path):
    p = _project(tmp_path, filled__def=_STALE, top_design__def=_LIVE)
    res = M.resolve_macro_placements_detailed(p, _CELLS, "top_design")
    assert res["defs_disagreeing"] == ["filled.def"], res
    assert any("filled.def" in d for d in res["disclosures"]), res


def test_disagreement_is_a_disclosure_and_never_a_refusal(tmp_path):
    """A refusal means a macro was NOT placed. All of these were."""
    p = _project(tmp_path, filled__def=_STALE, top_design__def=_LIVE)
    res = M.resolve_macro_placements_detailed(p, _CELLS, "top_design")
    assert res["refusals"] == [], res
    assert sum(len(v) for v in res["placements"].values()) == 2


def test_agreeing_defs_produce_no_disclosure(tmp_path):
    """The disclosure must fire on DISAGREEMENT, not on "more than one DEF"."""
    p = _project(tmp_path, routed__def=_LIVE, top_design__def=_LIVE)
    res = M.resolve_macro_placements_detailed(p, _CELLS, "top_design")
    assert res["defs_disagreeing"] == [], res
    assert res["disclosures"] == [], res


def test_the_same_positions_on_different_instances_is_a_disagreement(tmp_path):
    """Two DEFs that place the same cell the same number of times at the same
    coordinates, attached to DIFFERENT instances, have not agreed."""
    swapped = _LIVE.replace("u_a1", "u_aX")
    p = _project(tmp_path, routed__def=swapped, top_design__def=_LIVE)
    res = M.resolve_macro_placements_detailed(p, _CELLS, "top_design")
    assert res["defs_disagreeing"] == ["routed.def"], res


# ── a DEF for another design says nothing about this one ────────────────────
def test_a_def_naming_a_different_design_is_not_consulted(tmp_path):
    other = _STALE.replace("DESIGN top_design", "DESIGN some_other_top")
    p = _project(tmp_path, filled__def=other, top_design__def=_LIVE)
    res = M.resolve_macro_placements_detailed(p, _CELLS, "top_design")
    assert res["defs_considered"] == ["top_design.def"], res
    assert res["defs_disagreeing"] == [], res


def test_a_def_with_no_design_line_is_still_read(tmp_path):
    """Not every DEF carries `DESIGN`; dropping those would lose the only DEF a
    thinner project has."""
    p = _project(tmp_path, routed__def=_LIVE.split("\n", 1)[1])
    res = M.resolve_macro_placements_detailed(p, _CELLS, "top_design")
    assert res["def_source"] == "routed.def", res


# ── the half that must not change ───────────────────────────────────────────
def test_no_def_at_all_places_nothing_and_says_why(tmp_path):
    p = _project(tmp_path)
    res = M.resolve_macro_placements_detailed(p, _CELLS, "top_design")
    assert res["placements"] == {}
    assert res["def_source"] is None
    assert res["refusals"] and "no DEF" in res["refusals"][0]


def test_a_macro_the_def_does_not_place_is_still_refused_by_name(tmp_path):
    p = _project(tmp_path, top_design__def=_LIVE)
    res = M.resolve_macro_placements_detailed(
        p, _CELLS + ["blk_missing"], "top_design")
    assert any("blk_missing" in r for r in res["refusals"]), res


def test_an_unmappable_orientation_is_still_refused_by_name(tmp_path):
    bad = _LIVE.replace("( 30080 439350 ) N", "( 30080 439350 ) FE")
    p = _project(tmp_path, top_design__def=bad)
    res = M.resolve_macro_placements_detailed(p, _CELLS, "top_design")
    assert any("u_a1" in r and "FE" in r for r in res["refusals"]), res


def test_the_pre_fix_call_shape_ALSO_stops_taking_the_stale_def(tmp_path):
    """THE BEHAVIOURAL NEGATIVE CONTROL. Every other test here reaches for an
    API that did not exist before, so against pre-fix code they fail on
    `AttributeError` — which proves the API is new, not that the defect is
    fixed. This one calls the function with the EXACT pre-fix signature, two
    positional arguments and no design name, and asserts the answer. Against
    `origin/main` it returns filled.def's `(15.08, 760.61) FS`; it must now
    return the live DEF's, because the design name is read out of the DEFs
    themselves when the caller does not supply one."""
    p = _project(tmp_path, filled__def=_STALE, top_design__def=_LIVE)
    got, _ref = M.resolve_macro_placements(p, _CELLS)
    a1 = [q for q in got["blk_a"] if q["inst"] == "u_a1"][0]
    assert (a1["x_um"], a1["y_um"], a1["orient"]) == (30.08, 439.35, "N"), a1


def test_two_designs_in_one_pnr_dir_cannot_be_resolved_by_silence(tmp_path):
    """When the DEFs name DIFFERENT designs, no single name can be inferred, so
    the preference order stands rather than one being picked at random."""
    other = _LIVE.replace("DESIGN top_design", "DESIGN some_other_top")
    p = _project(tmp_path, filled__def=_STALE, zz_other__def=other)
    res = M.resolve_macro_placements_detailed(p, _CELLS)
    assert res["def_source"] == "filled.def", res
    assert set(res["defs_considered"]) == {"filled.def", "zz_other.def"}


def test_the_two_value_wrapper_keeps_its_shape(tmp_path):
    p = _project(tmp_path, filled__def=_STALE, top_design__def=_LIVE)
    got, ref = M.resolve_macro_placements(p, _CELLS, "top_design")
    assert isinstance(got, dict) and isinstance(ref, list)
    a1 = [q for q in got["blk_a"] if q["inst"] == "u_a1"][0]
    assert (a1["x_um"], a1["y_um"]) == (30.08, 439.35), a1


def test_the_artefact_the_merge_reads_is_still_shaped_the_way_it_reads_it(
        tmp_path):
    """The KLayout merge template does `_pj.get("placements", _pj)`. The record
    grew fields; that key must still be the map."""
    p = _project(tmp_path, top_design__def=_LIVE)
    res = M.resolve_macro_placements_detailed(p, _CELLS, "top_design")
    round_tripped = json.loads(json.dumps(res))
    assert set(round_tripped["placements"]) == {"blk_a", "blk_b"}
    assert 'PLACEMENTS_JSON' in M._KLAYOUT_MERGE_PY
