"""#686 — nothing intersected emitted geometry with a placed macro's OBS.

MEASURED on a routed DEF from a run the flow called clean but for one unrelated
gap: 28 of 292 MET1 FOLLOWPIN segments run straight through a placed macro's
full-footprint MET1 obstruction, declared in the very LEF the run loaded.

SILENT BY CONSTRUCTION, which is the part worth naming. Every existing check is

  * a COUNT OF ATTACHMENTS — `PG_NET_OWNERSHIP_AUDIT: total=3337 no_net=1` tests
    whether a terminal has a net. A wire crossing a blockage is attached to
    exactly the right net. (Spelled `PG_CONNECT_AUDIT: unconnected=N` through
    v1.9.62, until vibe-ic#699 renamed it to what it measures.)
  * a GEOMETRIC DRC AGAINST THE PDK DECK — `drc_signoff.json: passed: true`,
    `detailed route: violation report: 0`. A macro obstruction is not in the PDK
    deck; it is in the macro's LEF.

A macro obstruction is neither, so it was invisible to all of them at once.

MEASURED after the fix, on the shape the issue describes:

    40 supply segments, 28 of them crossing a 100x60 macro   -> 28 findings
    one of those shortened to END INSIDE the macro           -> 27
    an asymmetric 100x20 obstruction, orient N               -> 10
    the same, orient E                                       -> 40
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "macro_obs_geometry_intersect_check",
    _PROGRAMS / "macro_obs_geometry_intersect_check.py")
M = importlib.util.module_from_spec(_spec)
sys.modules["macro_obs_geometry_intersect_check"] = M
try:
    _spec.loader.exec_module(M)
except SystemExit:
    pass

_LEF = """
MACRO big_ip
  SIZE 100.0 BY 60.0 ;
  OBS
    LAYER OVERLAP ;
      RECT 0 0 100.0 60.0 ;
    LAYER MET1 ;
      RECT 0 0 100.0 60.0 ;
  END
END big_ip
"""


def _def(n_through=28, n_clear=12, orient="N", short_first=False):
    rows = []
    for i in range(n_through):
        y = 102000 + i * 2000
        x2 = 250000 if (short_first and i == 0) else 400000
        rows.append(f"- VDD ( * VDD ) + USE POWER + ROUTED MET1 140 + SHAPE "
                    f"FOLLOWPIN ( 100000 {y} ) ( {x2} {y} ) ;")
    for i in range(n_clear):
        y = 20000 + i * 2000
        rows.append(f"- VSS ( * VSS ) + USE GROUND + ROUTED MET1 140 + SHAPE "
                    f"FOLLOWPIN ( 100000 {y} ) ( 400000 {y} ) ;")
    return ("UNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 1 ;\n"
            f"- u_ip big_ip + FIXED ( 200000 100000 ) {orient} ;\n"
            "END COMPONENTS\nSPECIALNETS 2 ;\n" + "\n".join(rows)
            + "\nEND SPECIALNETS\n")


# ── the finding ───────────────────────────────────────────────────────────
def test_it_finds_the_segments_that_span_the_obstruction():
    r = M.audit(_def(), [_LEF])
    assert len(r["findings"]) == 28
    assert all(f["followpin"] for f in r["findings"])
    assert r["special_segments"] == 40, "and the 12 rows below it are not flagged"


def test_a_segment_that_ends_inside_is_not_a_span():
    """LOAD-BEARING. A fragment near an edge is ordinary; flagging it would bury
    the real finding under noise, and a gate people scroll past enforces
    nothing."""
    r = M.audit(_def(short_first=True), [_LEF])
    assert len(r["findings"]) == 27


def test_LAYER_OVERLAP_is_not_treated_as_metal():
    """OVERLAP declares the macro's extent. Counting it would make every macro
    block every layer and the gate would fire on everything."""
    o = M.parse_macro_obs(_LEF)["big_ip"]
    assert [layer for layer, *_ in o["obs"]] == ["MET1"]


# ── orientation, with a control that can tell the difference ──────────────
_ASYM = """
MACRO ip
  SIZE 100.0 BY 20.0 ;
  OBS
    LAYER MET1 ;
      RECT 0 0 100.0 20.0 ;
  END
END ip
"""


def _asym_def(orient):
    rows = "\n".join(
        f"- VDD ( * VDD ) + USE POWER + ROUTED MET1 140 + SHAPE FOLLOWPIN "
        f"( 100000 {102000 + i * 2000} ) ( 400000 {102000 + i * 2000} ) ;"
        for i in range(40))
    return ("UNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 1 ;\n"
            f"- u ip + FIXED ( 200000 100000 ) {orient} ;\n"
            "END COMPONENTS\nSPECIALNETS 1 ;\n" + rows + "\nEND SPECIALNETS\n")


def test_orientation_changes_the_answer():
    """An ASYMMETRIC obstruction, because a square one gives the same count
    either way and would prove nothing. Ignoring orientation measures a rotated
    macro against an unrotated obstruction, and a fabricated finding is worse
    than none."""
    n = len(M.audit(_asym_def("N"), [_ASYM])["findings"])
    e = len(M.audit(_asym_def("E"), [_ASYM])["findings"])
    assert (n, e) == (10, 40), (n, e)


# ── it must never pass by finding nothing ─────────────────────────────────
def test_no_macro_declares_an_OBS_is_not_a_pass(tmp_path):
    lef = tmp_path / "m.lef"
    lef.write_text("MACRO plain\n  SIZE 10.0 BY 10.0 ;\nEND plain\n")
    d = tmp_path / "phase3/stage3/pnr"
    d.mkdir(parents=True)
    (d / "routed.def").write_text(_def())
    rc = M.main([str(tmp_path), "--macro-lef", str(lef)])
    assert rc == 2


def test_no_placed_instance_is_not_a_pass(tmp_path):
    lef = tmp_path / "m.lef"
    lef.write_text(_LEF)
    d = tmp_path / "phase3/stage3/pnr"
    d.mkdir(parents=True)
    (d / "routed.def").write_text(
        "UNITS DISTANCE MICRONS 1000 ;\nCOMPONENTS 0 ;\nEND COMPONENTS\n"
        "SPECIALNETS 0 ;\nEND SPECIALNETS\n")
    assert M.main([str(tmp_path), "--macro-lef", str(lef)]) == 2


def test_no_def_is_not_a_pass(tmp_path):
    assert M.main([str(tmp_path)]) == 2


# ── both exit codes on a real tree shape ──────────────────────────────────
def test_it_blocks_when_it_finds_one(tmp_path):
    lef = tmp_path / "m.lef"
    lef.write_text(_LEF)
    d = tmp_path / "phase3/stage3/pnr"
    d.mkdir(parents=True)
    (d / "routed.def").write_text(_def())
    assert M.main([str(tmp_path), "--macro-lef", str(lef)]) == 1


def test_it_passes_when_nothing_crosses(tmp_path):
    """THE ACCEPT CASE. A design whose supply metal respects the obstruction
    must go green, or the gate is unusable."""
    lef = tmp_path / "m.lef"
    lef.write_text(_LEF)
    d = tmp_path / "phase3/stage3/pnr"
    d.mkdir(parents=True)
    (d / "routed.def").write_text(_def(n_through=0, n_clear=12))
    assert M.main([str(tmp_path), "--macro-lef", str(lef)]) == 0
