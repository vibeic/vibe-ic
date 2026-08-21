"""#612 — M1 merged the macros in and never placed them.

Step M1 is "Mixed-Signal Top-Level Integration (A+D GDS merge + macro
placement)". The merge half ran. The placement half did not happen at all.

Measured on a real run before the fix:

    TOP CELLS = ['ldo', 'delta_sigma', 'u_hawaii_adc']
    u_hawaii_adc   child_insts = 0

Both macros sat as their OWN top cells at the origin, and `Layout.top_cell()`
raised "The layout has multiple top cells". `merge.json` recorded
`"action": "added"` for both, which was accurate and beside the point: **reading
a GDS adds STRUCTURES to the library; it does not create an instance.**

A merged GDS with more than one top cell is on its face not an integrated
design. Top-level extraction of the design sees no macro devices at all, so it
can never match a schematic that instantiates them, and no overlap / halo /
track check means anything about a cell that is nowhere.

NOT #597. That one was the merge DOUBLING shapes and is fixed; the issue
verified it on this same design (`added None -> 45678`, no x2). This is the
separate question of whether anything is ever placed.

POSITIONS ARE THE DESIGN'S OWN, never invented: the DEF `COMPONENTS` entry for
each macro instance. A macro the DEF does not place, or places at an
orientation this merge cannot back, is REFUSED BY NAME — `FE` / `FW` are
deliberately absent from the map, because a placement at the wrong orientation
is worse than none: it looks integrated and is not.

VERIFIED AGAINST THE REAL KLAYOUT, both directions, on a synthetic pair:

    with placements     KLAYOUT_MERGE_PLACED delta_sigma u_ds3 N 12.0 34.0
                        KLAYOUT_MERGE_TOPS u_top                     rc 0
    without             KLAYOUT_MERGE_TOPS u_top,delta_sigma
                        KLAYOUT_MERGE_MULTITOP                       rc 3

The second is the issue's exact symptom, and it is now a loud refusal rather
than a file that travels downstream as an "integrated" design.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "mixed_signal_top_lvs_run", _PROGRAMS / "mixed_signal_top_lvs_run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mixed_signal_top_lvs_run"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()
SRC = M._KLAYOUT_MERGE_PY

_DEF = """UNITS DISTANCE MICRONS 1000 ;
COMPONENTS 4 ;
    - u_ds3 delta_sigma + PLACED ( 123000 456000 ) N ;
    - u_ldo ldo + FIXED ( 700500 12000 ) FS ;
    - u_w  weird + PLACED ( 1000 2000 ) FE ;
END COMPONENTS
"""


# ── the placements come from the design, not from the merge ─────────────────
def test_a_placed_macro_is_read_with_its_position_and_orientation():
    got, _ = M.def_macro_placements(_DEF, ["delta_sigma"])
    assert got["delta_sigma"] == [{
        "inst": "u_ds3", "orient": "N", "rot": 0, "mirror": False,
        "x_um": 123.0, "y_um": 456.0}], got


def test_def_units_are_applied_not_assumed():
    """`UNITS DISTANCE MICRONS 1000` means the integers are nanometres here.
    A different UNITS line must move the answer."""
    got, _ = M.def_macro_placements(
        _DEF.replace("MICRONS 1000", "MICRONS 2000"), ["delta_sigma"])
    assert got["delta_sigma"][0]["x_um"] == 61.5


def test_a_missing_units_line_refuses_rather_than_defaulting():
    got, ref = M.def_macro_placements(
        "COMPONENTS 1 ;\n - a b + PLACED ( 1 2 ) N ;\n", ["b"])
    assert got == {} and any("UNITS" in r for r in ref), (got, ref)


def test_the_flip_this_can_back_is_mapped():
    got, _ = M.def_macro_placements(_DEF, ["ldo"])
    assert got["ldo"][0]["rot"] == 0 and got["ldo"][0]["mirror"] is True


def test_an_orientation_this_cannot_back_is_refused_by_name():
    """LOAD-BEARING. A placement at a guessed transform looks integrated and is
    wrong, which is worse than the defect it replaces."""
    got, ref = M.def_macro_placements(_DEF, ["weird"])
    assert "weird" not in got
    assert any("FE" in r and "weird" in r for r in ref), ref


def test_an_unplaced_macro_is_refused_by_name():
    _got, ref = M.def_macro_placements(_DEF, ["nowhere"])
    assert any("nowhere" in r and "not placed" in r for r in ref), ref


def test_a_macro_placed_twice_yields_two_instances():
    d = _DEF.replace("END COMPONENTS",
                     "    - u_ds4 delta_sigma + PLACED ( 1000 2000 ) S ;\n"
                     "END COMPONENTS")
    got, _ = M.def_macro_placements(d, ["delta_sigma"])
    assert len(got["delta_sigma"]) == 2
    assert {p["inst"] for p in got["delta_sigma"]} == {"u_ds3", "u_ds4"}


# ── the merge script places, and refuses a multi-top result ─────────────────
def test_the_embedded_script_parses():
    ast.parse(SRC)


def test_it_inserts_an_instance_rather_than_only_reading():
    assert "CellInstArray" in SRC, (
        "the merge reads the macro in and never instantiates it — the defect")
    assert "top.insert(" in SRC


def test_the_transform_uses_the_declared_rotation_and_mirror():
    """A placement that ignores `orient` is a placement at the wrong
    orientation, which is the failure mode the refusal above exists for."""
    assert 'pya.Trans(int(pl["rot"]), bool(pl["mirror"])' in SRC


def test_a_multi_top_result_is_a_loud_refusal():
    assert "KLAYOUT_MERGE_MULTITOP" in SRC
    assert "raise SystemExit(3)" in SRC
    # ...and it must fire BEFORE the DONE line, or a caller keyed on DONE reads
    # a multi-top file as a completed merge.
    assert SRC.index("KLAYOUT_MERGE_MULTITOP") < SRC.index("KLAYOUT_MERGE_DONE")


def test_the_record_carries_the_placements_and_the_top_count():
    for field in ('"placed"', '"top_cells_after"', '"single_top"',
                  '"design_top"'):
        assert field in SRC, f"{field} is not recorded"


def test_the_caller_supplies_both_the_top_and_the_placements():
    """A script that reads `DESIGN_TOP` from an environment nobody sets places
    nothing and reports success."""
    src = (_PROGRAMS / "mixed_signal_top_lvs_run.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "DESIGN_TOP={top}" in code
    assert "PLACEMENTS_JSON=" in code
    assert "resolve_macro_placements(" in code


def test_the_caller_actually_resolves_placements_from_the_project(tmp_path):
    """DRIVEN, not scanned. The first version asserted the call's NAME appeared
    in the source, which a short-circuit like `({}, []) or f(...)` satisfies
    while placing nothing."""
    d = tmp_path / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    (d / "routed.def").write_text(_DEF, encoding="utf-8")
    got, _ref = M.resolve_macro_placements(tmp_path, ["delta_sigma", "ldo"])
    assert set(got) == {"delta_sigma", "ldo"}, got
    assert got["delta_sigma"][0]["x_um"] == 123.0


def test_a_project_with_no_def_refuses_rather_than_returning_an_empty_map(tmp_path):
    """An empty map and "there is no DEF" are the same value to the merge, so
    the refusal has to say which it was."""
    got, ref = M.resolve_macro_placements(tmp_path, ["delta_sigma"])
    assert got == {} and ref, (got, ref)


def test_the_script_accepts_the_shape_the_caller_writes():
    """The caller writes {"placements": …, "refusals": …} so the refusals
    travel with the map; the script must unwrap it rather than treat the
    wrapper as the map and place nothing."""
    assert '.get("placements"' in SRC
