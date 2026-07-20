"""ORGANIC #597 — the off-grid geometry that blocks GDS signoff (live:
46,614 of 61,324 = 76% off-grid) is the deferred root-cause half of #594.

Root-cause isolation (verified on a real routed DEF, 1.88M coordinate
ints): the routed DEF is ~100% on-grid (84 off-grid = 0.004% via
residue), so the OFFGRID DRC wall is introduced DOWNSTREAM at the
DEF→GDS streamout / boolean-merge stage — a tool behaviour, NOT routing
or floorplan. def_manufacturing_grid_check.py makes that finding durable
and step_drc records WHERE the off-grid is born (source-clean →
streamout tool defect, container-side; source-off-grid → floorplan
regression the plugin owns).

The final acceptance (GDS DRC ZERO OFFGRID) is tool/PDK-specific and
needs container-side streamout remediation + real-hardware re-verify
(the issue itself scopes part-c that way); this gate delivers the
deterministic root-cause isolation + the #594 classifier holds the
residual visible.
"""
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import def_manufacturing_grid_check as DMG  # noqa: E402
import phase3_one_shot_runner as R  # noqa: E402
from _hostpaths import require_repo  # noqa: E402


def _def(coords, dbu=1000):
    """Minimal DEF carrying the given (x,y) coordinate pairs."""
    body = "".join(f"  ( {x} {y} )" for x, y in coords)
    return (f"VERSION 5.8 ;\nUNITS DISTANCE MICRONS {dbu} ;\n"
            f"DIEAREA ( 0 0 ) ( 900000 900000 ) ;\n"
            f"NETS 1 ;\n- n0 + ROUTED met1{body} ;\nEND NETS\nEND DESIGN\n")


# ── source classification semantics ─────────────────────────────────────────

def test_on_grid_source_is_clean():
    """All coords multiples of 5 DBU → GRID_CLEAN_SOURCE (off-grid is a
    downstream streamout defect, not the routing source)."""
    rep = DMG.classify_def(_def([(0, 0), (340, 460), (1000, 5000)]))
    assert rep["verdict"] == "GRID_CLEAN_SOURCE"
    assert rep["offgrid_coords"] == 0


def test_via_residue_below_floor_is_clean():
    """The issue's exact 現象 (verified on the real DEF): a handful of
    off-grid via-enclosure coords among many on-grid is BELOW the 1%
    floor → still GRID_CLEAN_SOURCE → off-grid DRC is downstream."""
    coords = [(i * 5, i * 5) for i in range(200)] + [(242, 243)]  # 1/402
    rep = DMG.classify_def(_def(coords))
    assert rep["verdict"] == "GRID_CLEAN_SOURCE"
    assert rep["offgrid_coords"] == 2          # both 242 and 243 off-grid
    assert rep["offgrid_fraction"] < 0.01


def test_materially_offgrid_source_flagged():
    """A floorplan/track-origin misalignment puts a LARGE fraction
    off-grid → FLOW_OFFGRID_SOURCE (the plugin owns this)."""
    coords = [(i * 5 + 2, i * 5 + 3) for i in range(100)]  # 100% off-grid
    rep = DMG.classify_def(_def(coords))
    assert rep["verdict"] == "FLOW_OFFGRID_SOURCE"
    assert rep["offgrid_fraction"] >= 0.01


def test_grid_dbu_derived_from_units_and_mfg_grid():
    rep = DMG.classify_def(_def([(0, 0)], dbu=2000), mfg_grid_um=0.005)
    assert rep["grid_dbu"] == 10            # 0.005µm × 2000 dbu/µm


def test_read_mfg_grid_from_tech_lef(tmp_path):
    lef = tmp_path / "tech.lef"
    lef.write_text("VERSION 5.7 ;\nMANUFACTURINGGRID 0.005 ;\nEND LIBRARY\n")
    assert DMG.read_mfg_grid_um(str(lef)) == 0.005


def test_read_mfg_grid_default_when_absent(tmp_path):
    assert DMG.read_mfg_grid_um(None) == 0.005
    assert DMG.read_mfg_grid_um(str(tmp_path / "nope.lef")) == 0.005


def test_error_on_no_units():
    rep = DMG.classify_def("DIEAREA ( 0 0 ) ( 10 10 ) ;\n")
    assert rep["verdict"] == "ERROR"


# ── CLI end-state ────────────────────────────────────────────────────────────

def test_cli_clean_source_exit_zero(tmp_path):
    d = tmp_path / "clean.def"
    d.write_text(_def([(0, 0), (340, 460)]))
    r = subprocess.run(
        [sys.executable, str(PROG / "def_manufacturing_grid_check.py"), str(d)],
        capture_output=True, text=True)
    assert r.returncode == 0
    assert "GRID-CLEAN" in r.stdout
    assert "DOWNSTREAM" in r.stdout


def test_cli_offgrid_source_exit_one(tmp_path):
    d = tmp_path / "bad.def"
    d.write_text(_def([(i * 5 + 2, i * 5 + 3) for i in range(50)]))
    r = subprocess.run(
        [sys.executable, str(PROG / "def_manufacturing_grid_check.py"), str(d)],
        capture_output=True, text=True)
    assert r.returncode == 1
    assert "FLOW_OFFGRID_SOURCE" in r.stdout


# ── live-corpus canary (content-gated): the real routed DEF is on-grid ──────

def test_real_routed_def_is_grid_clean_when_present():
    art = require_repo("benchmark_ic/5th__opentitan_aes_v0338/phase3/"
                       "stage3/pnr/routed_preantenna.def")
    if not art.is_file():
        pytest.skip("real routed DEF not on this host (live corpus)")
    txt = art.read_text(errors="replace")
    if "UNITS DISTANCE MICRONS" not in txt:
        pytest.skip("DEF reshaped (live corpus)")
    rep = DMG.classify_def(txt)
    # routing source is on-grid → off-grid DRC is a downstream tool defect
    assert rep["verdict"] == "GRID_CLEAN_SOURCE", rep["offgrid_fraction"]
    assert rep["offgrid_fraction"] < 0.01


# ── step_drc wiring ──────────────────────────────────────────────────────────

def test_step_drc_isolates_offgrid_source():
    src = inspect.getsource(R.step_drc)
    assert "def_manufacturing_grid_check" in src
    assert "offgrid_source" in src
    assert "GRID_CLEAN_SOURCE" in src
    assert "DOWNSTREAM streamout/merge tool defect" in src
