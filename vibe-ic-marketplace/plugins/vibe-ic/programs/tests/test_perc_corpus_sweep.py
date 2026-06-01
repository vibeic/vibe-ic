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
