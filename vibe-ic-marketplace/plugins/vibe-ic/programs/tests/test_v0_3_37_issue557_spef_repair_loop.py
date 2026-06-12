"""ORGANIC #557 — post-route SPEF-domain repair loop + SPEF-true Step-23.

Pre-fix: pnr.tcl ran repair_design/repair_timing only on estimate_parasitics
(HPWL / global-routing-estimate); after detailed_route there was no repair
and no SPEF STA → WNS -15.87 at sign-off while in-flow estimate said -1.09.

Fixes:
(a) CTS-domain repair refreshes parasitic estimate before hold repair;
(b) new _post_route_spef_repair_tcl() inserts OpenRCX extraction → read_spef
    → repair_design/repair_timing → incremental reroute into pnr.tcl;
(c) Step-23 verdict is SPEF-based when available (#527, confirmed here).

Defect artifact: quick_spef_sta.log / quick_spef_drv.rpt from benchmark_ic/6th__ibex
showing WNS -15.87 / TNS -22156 / 4958 DRV post-route vs. estimate -1.09.
"""
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402
import sdc_constraints as sdc  # noqa: E402


# ── (b) _post_route_spef_repair_tcl — TCL content checks ────────────────────

def test_spef_repair_tcl_contains_spef_repair_complete_marker(tmp_path):
    tcl = R._post_route_spef_repair_tcl("/out", "/tech.lef")
    (tmp_path / "spef_repair.tcl").write_text(tcl)
    result = subprocess.run(
        ["python3", "-c",
         f"txt=open(r'{tmp_path}/spef_repair.tcl').read();"
         "assert 'SPEF_REPAIR_COMPLETE' in txt,'marker missing'"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_spef_repair_tcl_contains_extract_parasitics(tmp_path):
    tcl = R._post_route_spef_repair_tcl("/out", "/tech.lef")
    (tmp_path / "spef_repair.tcl").write_text(tcl)
    result = subprocess.run(
        ["python3", "-c",
         f"txt=open(r'{tmp_path}/spef_repair.tcl').read();"
         "assert 'extract_parasitics' in txt,'extract missing'"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_spef_repair_tcl_contains_repair_timing(tmp_path):
    """#581 r2 — the repair set is repair_timing setup+hold (the shared
    post-buffered builder), NOT repair_design (Signal-11 segfault when
    pass-1 buffers are present; see test_v0_3_39_issue581r2)."""
    tcl = R._post_route_spef_repair_tcl("/out", "/tech.lef")
    (tmp_path / "spef_repair.tcl").write_text(tcl)
    result = subprocess.run(
        ["python3", "-c",
         f"txt=open(r'{tmp_path}/spef_repair.tcl').read();"
         "assert 'repair_timing -setup' in txt,'setup repair missing';"
         "assert 'repair_timing -hold' in txt,'hold repair missing'"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_spef_repair_tcl_contains_incremental_reroute(tmp_path):
    tcl = R._post_route_spef_repair_tcl("/out", "/tech.lef")
    (tmp_path / "spef_repair.tcl").write_text(tcl)
    result = subprocess.run(
        ["python3", "-c",
         f"txt=open(r'{tmp_path}/spef_repair.tcl').read();"
         "assert 'detailed_route' in txt,'reroute missing'"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_spef_repair_tcl_contains_skip_path(tmp_path):
    """No captable → SPEF_REPAIR_SKIP emitted (not a hard failure)."""
    tcl = R._post_route_spef_repair_tcl("/out", "/tech.lef")
    (tmp_path / "spef_repair.tcl").write_text(tcl)
    result = subprocess.run(
        ["python3", "-c",
         f"txt=open(r'{tmp_path}/spef_repair.tcl').read();"
         "assert 'SPEF_REPAIR_SKIP' in txt,'skip marker missing'"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0


def test_spef_repair_tcl_write_spef_to_outdir(tmp_path):
    tcl = R._post_route_spef_repair_tcl("/the_out", "/tech.lef")
    (tmp_path / "spef_repair.tcl").write_text(tcl)
    result = subprocess.run(
        ["python3", "-c",
         f"txt=open(r'{tmp_path}/spef_repair.tcl').read();"
         "assert '/the_out/post_route_repair.spef' in txt,'spef path missing'"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0


# ── (c) Step-23 SPEF-based verdict ───────────────────────────────────────────

def test_spef_sta_prerequisites_missing_returns_false_with_notes(tmp_path):
    """_emit_spef_sta returns False and appends a note when prerequisites
    (SPEF, pnr netlist, SDC) are absent — Step-23 falls back to estimate."""
    notes = []
    ok = R._emit_spef_sta(
        project=tmp_path,
        top="chip_top",
        pdk=None,          # not reached — prereq check exits early
        container="",
        spef_path=tmp_path / "missing.spef",
        rpt_out=tmp_path / "sta_spef.rpt",
        notes=notes,
    )
    assert ok is False
    assert any("SPEF-based STA prerequisites missing" in n for n in notes)


def test_spef_repair_tcl_captable_discovery_uses_libs_ref_anchor(tmp_path):
    """Captable discovery must use the /libs.ref/ anchor from the tech-LEF
    path (chip-AGNOSTIC: no PDK-name literal in the Python code)."""
    tcl = R._post_route_spef_repair_tcl("/out", "/pdk/libs.ref/sky130A/tech.lef")
    assert "/libs.ref/" in tcl
    assert "rules.openrcx" in tcl
