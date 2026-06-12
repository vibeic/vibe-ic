"""ORGANIC #557 / #581 — post-route SPEF EXTRACTION (measure-only) +
SPEF-true Step-23.

Pre-fix (#557): after detailed_route there was no SPEF STA → WNS -15.87
at sign-off while in-flow estimate said -1.09.

#581 round-3 evolution: the post-route block was originally a REPAIR loop
(extract → repair_timing → reroute), but every RSZ repair-move
(repair_design r2, then repair_timing -setup r3) SEGFAULTS (Signal 11) on
a post-detailed-route SPEF-annotated design, killing the whole openroad
process so GDS was never written. The block is now MEASURE-ONLY: OpenRCX
extract → write_spef → SPEF_MEASURE_COMPLETE, with NO repair_timing /
repair_design / reroute. The SPEF feeds #527's SPEF-true Step-23 STA;
residual post-route timing goes via the pre-route #561 ECO path.
"""
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402
import sdc_constraints as sdc  # noqa: E402


# ── (b) _post_route_spef_repair_tcl — TCL content checks ────────────────────

def test_spef_repair_tcl_contains_measure_complete_marker(tmp_path):
    """#581 r3 — the success marker is SPEF_MEASURE_COMPLETE (extract-only)."""
    tcl = R._post_route_spef_repair_tcl("/out", "/tech.lef")
    (tmp_path / "spef_repair.tcl").write_text(tcl)
    result = subprocess.run(
        ["python3", "-c",
         f"txt=open(r'{tmp_path}/spef_repair.tcl').read();"
         "assert 'SPEF_MEASURE_COMPLETE' in txt,'marker missing'"],
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


def test_spef_repair_tcl_is_measure_only_no_repair(tmp_path):
    """#581 r3 — the post-route block calls NO repair_timing /
    repair_design and does NO reroute: the RSZ repair-move family
    segfaults on a post-detailed-route SPEF-annotated design (catch
    cannot contain a segfault → openroad dies → GDS never written).
    Timing repair is pre-route only."""
    tcl = R._post_route_spef_repair_tcl("/out", "/tech.lef")
    # COMMAND lines only — the doctrine comment names the banned commands.
    cmds = "\n".join(ln for ln in tcl.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "repair_timing" not in cmds
    assert "repair_design" not in cmds
    # no reroute either (the segfault is in the repair that PRECEDED it,
    # but reroute on the already-converged route is also pointless here)
    assert "detailed_route" not in cmds
    assert "global_route" not in cmds


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
