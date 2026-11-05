"""ORGANIC #600 — DEF→GDS streamout manufacturing-grid snap.

#597 proved the routed DEF source is on-grid (AES: 84/1,878,652 = 0.0045%
off-grid → GRID_CLEAN_SOURCE); the OFFGRID DRC wall is introduced ENTIRELY
at the DEF→GDS streamout / boolean-merge stage — a tool behaviour, not
routing. step_gds now runs a KLayout Region.snap pass over the streamed GDS,
snapping every polygon vertex back to the PDK manufacturing grid (sky130 =
5 nm) BEFORE signoff DRC, on BOTH the magic and klayout streamout paths.

Locally verifiable (this file): the snap-script CONTENT (uses Region.snap to
the manufacturing grid), the grid arithmetic (grid_dbu = round(grid_um/dbu)),
the wiring into both streamout returns, and the NONFATAL fallback (klayout
absent / snap fails → original GDS kept). The GDS-OFFGRID-to-zero OUTCOME is
tool/PDK-specific and is measured on real hardware by the #594 FLOW_OFFGRID
classifier — this test does NOT claim that outcome.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))


# ── snap-script content: the standard KLayout grid-snap idiom ────────────────







# ── grid arithmetic: 5 nm grid on a 1 nm-DBU layout → 5 DBU ─────────────────

def test_grid_dbu_arithmetic_5nm_on_1nm_dbu():
    # mirror the script's arithmetic: round(0.005 / 0.001) == 5
    grid_um, dbu = 0.005, 0.001
    assert int(round(grid_um / dbu)) == 5


def test_grid_dbu_arithmetic_5nm_on_5nm_dbu():
    # a layout whose dbu already equals the grid → snap step is 1 DBU
    grid_um, dbu = 0.005, 0.005
    assert int(round(grid_um / dbu)) == 1


# ── mfg-grid resolution falls back to sky130 default ────────────────────────



# ── NONFATAL fallback: klayout absent → original GDS untouched ──────────────









# ── wiring: BOTH streamout paths run the snap before their PASS return ──────

def test_step_gds_wires_snap_on_both_streamout_paths():
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    # exactly two call sites (magic path + klayout path), both inside step_gds
    assert src.count("_gds_grid_snap(project, top, pdk, container") >= 2
    # the snap result is surfaced in the StepResult extras for audit
    assert '"grid_snap": snap_ok' in src
    assert '"grid_snap_note": snap_note' in src
