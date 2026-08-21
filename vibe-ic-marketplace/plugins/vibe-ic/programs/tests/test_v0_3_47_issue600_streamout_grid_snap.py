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
import phase3_one_shot_runner as R  # noqa: E402


# ── snap-script content: the standard KLayout grid-snap idiom ────────────────

def test_snap_script_uses_region_snap_to_grid():
    s = R._GDS_GRID_SNAP_PY
    assert "import pya" in s
    assert ".snap(grid_dbu, grid_dbu)" in s, "must snap vertices to the grid"
    # grid in DBU derived from the layout's own dbu, not hardcoded
    assert "grid_dbu = int(round(grid_um / ly.dbu))" in s
    # reads + writes a GDS, driven by env (container-portable)
    assert 'os.environ["GDS_IN"]' in s
    assert 'os.environ["GDS_OUT"]' in s
    assert "ly.write(gds_out)" in s
    # emits a machine-checkable completion marker
    assert "GDS_GRID_SNAP_DONE" in s


def test_snap_script_defaults_to_sky130_5nm_grid():
    s = R._GDS_GRID_SNAP_PY
    # sky130 manufacturing grid is 0.005 µm (5 nm); env override wins
    assert 'os.environ.get("MFG_GRID_UM", "0.005")' in s


def test_snap_script_guards_min_grid():
    """grid_dbu must never collapse to 0 (would no-op or divide-by-zero a
    snap); the script floors it at 1 DBU."""
    s = R._GDS_GRID_SNAP_PY
    assert "if grid_dbu < 1:" in s
    assert "grid_dbu = 1" in s


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

def test_read_mfg_grid_um_default():
    class _Pdk:
        tech_lef = "/nonexistent/path/sky130.tlef"
    assert R._read_mfg_grid_um_for_pdk(_Pdk()) == 0.005


# ── NONFATAL fallback: klayout absent → original GDS untouched ──────────────

def test_grid_snap_nonfatal_when_klayout_absent(tmp_path, monkeypatch):
    gds = tmp_path / "top.gds"
    gds.write_text("dummy gds bytes")
    before = gds.read_text()

    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: False)
    # build a minimal project layout so pnr_dir resolves
    monkeypatch.setattr(R._pl, "pnr_dir", lambda p: tmp_path)

    class _Pdk:
        tech_lef = "/nonexistent/sky130.tlef"

    ok, note = R._gds_grid_snap(tmp_path, "top", _Pdk(), "container", gds)
    assert ok is False
    assert "not in container PATH" in note
    # original GDS untouched (no destructive swap on failure)
    assert gds.read_text() == before


def test_grid_snap_nonfatal_when_no_gds(tmp_path):
    class _Pdk:
        tech_lef = "/nonexistent/sky130.tlef"
    missing = tmp_path / "absent.gds"
    ok, note = R._gds_grid_snap(tmp_path, "top", _Pdk(), "container", missing)
    assert ok is False
    assert "no GDS" in note


def test_grid_snap_success_swaps_in_snapped_gds(tmp_path, monkeypatch):
    """On rc=0 + a written snapped GDS, the snapped file replaces the
    streamed GDS in place (so signoff DRC sees the on-grid geometry)."""
    pnr = tmp_path
    gds = pnr / "top.gds"
    gds.write_text("ORIGINAL")

    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: True)
    monkeypatch.setattr(R._pl, "pnr_dir", lambda p: pnr)
    monkeypatch.setattr(R, "_to_container_path", lambda h, c: h)

    def _fake_exec(container, cmd, timeout=600, **_):
        # simulate klayout writing the snapped GDS
        (pnr / "top.snapped.gds").write_text("SNAPPED-ON-GRID")
        return 0, "GDS_GRID_SNAP_DONE grid_dbu=5 layers=12", ""

    monkeypatch.setattr(R, "_docker_exec", _fake_exec)

    class _Pdk:
        tech_lef = "/nonexistent/sky130.tlef"

    ok, note = R._gds_grid_snap(pnr, "top", _Pdk(), "container", gds)
    assert ok is True
    assert gds.read_text() == "SNAPPED-ON-GRID"   # swapped in place
    assert "0.005" in note                          # grid disclosed


def test_grid_snap_nonfatal_when_exec_fails(tmp_path, monkeypatch):
    pnr = tmp_path
    gds = pnr / "top.gds"
    gds.write_text("ORIGINAL")

    monkeypatch.setattr(R, "_tool_in_path", lambda c, t: True)
    monkeypatch.setattr(R._pl, "pnr_dir", lambda p: pnr)
    monkeypatch.setattr(R, "_to_container_path", lambda h, c: h)
    monkeypatch.setattr(R, "_docker_exec",
                        lambda c, cmd, timeout=600, **_: (1, "", "klayout boom"))

    class _Pdk:
        tech_lef = "/nonexistent/sky130.tlef"

    ok, note = R._gds_grid_snap(pnr, "top", _Pdk(), "container", gds)
    assert ok is False
    assert "NONFATAL" in note
    assert gds.read_text() == "ORIGINAL"            # untouched on failure


# ── wiring: BOTH streamout paths run the snap before their PASS return ──────

def test_step_gds_wires_snap_on_both_streamout_paths():
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    # exactly two call sites (magic path + klayout path), both inside step_gds
    assert src.count("_gds_grid_snap(project, top, pdk, container") >= 2
    # the snap result is surfaced in the StepResult extras for audit
    assert '"grid_snap": snap_ok' in src
    assert '"grid_snap_note": snap_note' in src
