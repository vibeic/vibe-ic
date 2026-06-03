"""Tests for perc_corpus_sweep — the corpus PERC sign-off sweep (captured v0.2.12 from the
2026-06-01 Shape-A 21-IC benchmark_ic sweep). Pins: routed-DEF selection, per-IC sweep wiring
to the SHIPPED phase3 functions, the systemic summary counts, and the no-DEF honest absence.
"""
import json
import subprocess
import sys
from pathlib import Path

import perc_corpus_sweep as s


_CORE_MACRO_DEF = """VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 100000 100000 ) ;
COMPONENTS 3 ;
- _1_ sky130_fd_sc_hd__nor3_1 + PLACED ( 0 0 ) N ;
- _2_ sky130_fd_sc_hd__and3_1 + PLACED ( 100 0 ) N ;
- _3_ sky130_fd_sc_hd__dfxtp_1 + PLACED ( 200 0 ) N ;
END COMPONENTS
SPECIALNETS 2 ;
    - VPWR ( _1_ VPB ) + USE POWER ;
    - VGND ( _1_ VNB ) + USE GROUND ;
END SPECIALNETS
END DESIGN
"""

_WITH_TAPS_DEF = _CORE_MACRO_DEF.replace(
    "END COMPONENTS",
    "- tap0 sky130_fd_sc_hd__tapvpwrvgnd_1 + PLACED ( 300 0 ) N ;\nEND COMPONENTS")


# ---- vintage-guard fixtures (suggested_fix #4) ----------------------------------------
def _big_def(n_std, n_tap=0, design="chip_top"):
    """A DEF with n_std placed transistor-bearing std cells + n_tap rated tap cells."""
    rows = [f"- _{i}_ sky130_fd_sc_hd__nand2_1 + PLACED ( {i*10} 0 ) N ;"
            for i in range(n_std)]
    rows += [f"- tap{j} sky130_fd_sc_hd__tapvpwrvgnd_1 + PLACED ( {j*10} 100 ) N ;"
             for j in range(n_tap)]
    total = n_std + n_tap
    return (f"VERSION 5.8 ;\nDESIGN {design} ;\nUNITS DISTANCE MICRONS 1000 ;\n"
            f"DIEAREA ( 0 0 100000 100000 ) ;\nCOMPONENTS {total} ;\n"
            + "\n".join(rows) + "\nEND COMPONENTS\n"
            "SPECIALNETS 2 ;\n  - VPWR ( _0_ VPB ) + USE POWER ;\n"
            "  - VGND ( _0_ VNB ) + USE GROUND ;\nEND SPECIALNETS\nEND DESIGN\n")


def _mk_design(tmp_path, body, name="ic_a"):
    d = tmp_path / name
    pnr = d / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text(body)
    return d


# ---------------------------------------------------------------- DEF selection
def test_pick_routed_def_prefers_routed(tmp_path):
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    (pnr / "floorplan.def").write_text(_CORE_MACRO_DEF)
    (pnr / "routed.def").write_text(_CORE_MACRO_DEF)
    (pnr / "chip_top.def").write_text(_CORE_MACRO_DEF)
    picked = s._pick_routed_def(str(tmp_path))
    assert picked.endswith("routed.def")    # routed > chip_top > floorplan

def test_pick_routed_def_none_when_absent(tmp_path):
    (tmp_path / "phase3").mkdir()
    assert s._pick_routed_def(str(tmp_path)) is None


# ---------------------------------------------------------------- sweep_one
def test_sweep_one_core_macro_0tap(tmp_path):
    f = tmp_path / "r.def"; f.write_text(_CORE_MACRO_DEF)
    r = s.sweep_one(str(f), name="m")
    assert r["components"] == 3
    assert r["esd_presence"]["status"] == "N/A"             # core macro, no pad ring
    assert r["welltap"]["status"] == "WELLTAP_GAP"          # 0 taps → conclusive
    assert r["welltap"]["n_tap"] == 0
    assert r["xdomain"]["status"] == "N/A"                  # single VPWR/VGND
    assert "esd_topology" not in r                          # skipped (no pad ring)

def test_sweep_one_with_taps_present(tmp_path):
    f = tmp_path / "r.def"; f.write_text(_WITH_TAPS_DEF)
    r = s.sweep_one(str(f), name="m")
    assert r["welltap"]["status"] == "WELLTAP_PRESENT"
    assert r["welltap"]["n_tap"] == 1

def test_sweep_one_missing_def(tmp_path):
    r = s.sweep_one(str(tmp_path / "nope.def"), name="x")
    assert r["error"] == "DEF not found"


# ---------------------------------------------------------------- sweep_dirs
def test_sweep_dirs_mixed_def_and_nodef(tmp_path):
    _mk_design(tmp_path, _CORE_MACRO_DEF, name="has_def")
    (tmp_path / "no_def" / "phase3").mkdir(parents=True)
    rows = s.sweep_dirs([str(tmp_path / "has_def"), str(tmp_path / "no_def")])
    by = {r["name"]: r for r in rows}
    assert by["has_def"]["welltap"]["status"] == "WELLTAP_GAP"
    assert by["no_def"]["error"] == "no routed DEF"          # honest absence, not a pass


# ---------------------------------------------------------------- summary
def test_summarize_systemic_counts(tmp_path):
    _mk_design(tmp_path, _CORE_MACRO_DEF, name="a")
    _mk_design(tmp_path, _WITH_TAPS_DEF, name="b")
    rows = s.sweep_dirs([str(tmp_path / "a"), str(tmp_path / "b")])
    txt = s.summarize(rows)
    assert "welltap WELLTAP_GAP" in txt
    assert "1/2" in txt                                      # a=GAP, b=PRESENT → 1/2 gap
    # the honesty note must be present (stale-artifact lesson)
    assert "NOT a current-runner bug" in txt
    assert "FRESH" in txt


# ---------------------------------------------------------------- CLI
def test_cli_json_array(tmp_path):
    _mk_design(tmp_path, _CORE_MACRO_DEF, name="a")
    r = subprocess.run([sys.executable, str(Path(s.__file__)), "--json", str(tmp_path / "a")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data[0]["welltap"]["status"] == "WELLTAP_GAP"


# ============================================================ artifact-vintage guard (#4)
def _mk_pnr(tmp_path, files, name="dut"):
    """Build <tmp>/<name>/phase3/stage3/pnr with {basename: def_text}; return the dir."""
    pnr = tmp_path / name / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    for fn, body in files.items():
        (pnr / fn).write_text(body)
    return pnr


def test_vintage_FIRES_on_stale_0tap_lineage(tmp_path):
    # routed DEF: 300 std cells, 0 taps; AND every older sibling stage is also 0-tap.
    pnr = _mk_pnr(tmp_path, {
        "floorplan.def": _big_def(300, n_tap=0),
        "placed.def":    _big_def(300, n_tap=0),
        "post_cts.def":  _big_def(300, n_tap=0),
        "routed.def":    _big_def(300, n_tap=0),
    })
    v = s.artifact_vintage_guard(str(pnr / "routed.def"))
    assert v["verdict"] == "STALE_PRE_TAPCELL"
    assert v["warn"] is True
    assert v["n_tap"] == 0 and v["n_std_cells"] == 300
    # the OLDER siblings (floorplan/placed/cts) are cited; routed itself is not a sibling
    assert "floorplan.def" in v["older_zero_tap_siblings"]
    assert "routed.def" not in v["older_zero_tap_siblings"]


def test_vintage_DOES_NOT_FIRE_on_tapped_def(tmp_path):
    # routed DEF HAS taps (the FRESH-control shape: placed/cts/routed all tap-bearing).
    pnr = _mk_pnr(tmp_path, {
        "floorplan.def": _big_def(300, n_tap=0),     # floorplan is 0-tap BY DESIGN
        "routed.def":    _big_def(300, n_tap=67),    # current runner inserted 67 taps
    })
    v = s.artifact_vintage_guard(str(pnr / "routed.def"))
    assert v["verdict"] == "OK"
    assert v["warn"] is False
    assert v["welltap"] == "WELLTAP_PRESENT" and v["n_tap"] == 67


def test_vintage_DOES_NOT_FIRE_on_small_block(tmp_path):
    # small block (<= std_cell_min): 0 taps is not yet a regression signal.
    pnr = _mk_pnr(tmp_path, {
        "floorplan.def": _big_def(10, n_tap=0),
        "routed.def":    _big_def(10, n_tap=0),
    })
    v = s.artifact_vintage_guard(str(pnr / "routed.def"))
    assert v["verdict"] == "OK"
    assert v["warn"] is False
    assert "legit small" in v["reason"]


def test_vintage_DOES_NOT_FIRE_on_floorplan_def(tmp_path):
    # a floorplan DEF (big, 0-tap) is pre-tapcell BY DESIGN — guard called on it directly:
    # it is its own only DEF, so there is no OLDER 0-tap sibling → SUSPECT_LIVE, not STALE,
    # and (separately) sweep deprioritises floorplan so this path is not what gets cited.
    pnr = _mk_pnr(tmp_path, {"floorplan.def": _big_def(300, n_tap=0)})
    v = s.artifact_vintage_guard(str(pnr / "floorplan.def"), sibling_defs=[])
    assert v["verdict"] == "SUSPECT_LIVE"   # no older sibling → cannot prove stale


def test_vintage_SUSPECT_LIVE_when_no_older_zero_tap_sibling(tmp_path):
    # big 0-tap routed DEF but its only older sibling is tap-bearing → looks like a
    # one-off live regression, NOT a stale lineage.
    pnr = _mk_pnr(tmp_path, {
        "placed.def":  _big_def(300, n_tap=67),   # earlier stage HAD taps
        "routed.def":  _big_def(300, n_tap=0),    # routed lost them → suspicious, live
    })
    v = s.artifact_vintage_guard(str(pnr / "routed.def"))
    assert v["verdict"] == "SUSPECT_LIVE"
    assert v["warn"] is True
    assert "possible live regression" in v["reason"].lower()


def test_vintage_missing_def(tmp_path):
    v = s.artifact_vintage_guard(str(tmp_path / "nope.def"))
    assert v["verdict"] == "NA" and v["warn"] is False


def test_vintage_attached_to_sweep_one(tmp_path):
    pnr = _mk_pnr(tmp_path, {
        "placed.def":  _big_def(300, n_tap=0),
        "routed.def":  _big_def(300, n_tap=0),
    })
    r = s.sweep_one(str(pnr / "routed.def"), name="dut")
    assert r["vintage"]["verdict"] == "STALE_PRE_TAPCELL"
    assert r["vintage"]["warn"] is True


def test_vintage_can_be_disabled(tmp_path):
    pnr = _mk_pnr(tmp_path, {"routed.def": _big_def(300, n_tap=0)})
    r = s.sweep_one(str(pnr / "routed.def"), name="dut", vintage=False)
    assert "vintage" not in r


def test_summary_counts_vintage(tmp_path):
    # stale design + a healthy tapped design → 1 STALE, 0 SUSPECT in the systemic block.
    _mk_pnr(tmp_path, {"placed.def": _big_def(300, n_tap=0),
                       "routed.def": _big_def(300, n_tap=0)}, name="stale")
    _mk_pnr(tmp_path, {"routed.def": _big_def(300, n_tap=67)}, name="healthy")
    rows = s.sweep_dirs([str(tmp_path / "stale"), str(tmp_path / "healthy")])
    txt = s.summarize(rows)
    assert "vintage STALE_PRE_TAPCELL" in txt
    assert "1/2" in txt


def test_cli_vintage_only_flag(tmp_path):
    pnr = _mk_pnr(tmp_path, {"placed.def": _big_def(300, n_tap=0),
                             "routed.def": _big_def(300, n_tap=0)})
    r = subprocess.run([sys.executable, str(Path(s.__file__)),
                        "--vintage", str(pnr / "routed.def")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["verdict"] == "STALE_PRE_TAPCELL"
