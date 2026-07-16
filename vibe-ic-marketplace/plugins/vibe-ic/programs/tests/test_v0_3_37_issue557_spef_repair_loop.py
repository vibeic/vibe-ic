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
    """#581 r3 / #147 — with the DEFAULT (fork_repair_capable=False, i.e. stock
    or pre-rebake OpenROAD) the post-route block calls NO repair_timing /
    repair_design and does NO reroute: the STOCK RSZ repair-move family
    segfaults on a post-detailed-route SPEF-annotated design (catch cannot
    contain a segfault → openroad dies → GDS never written). Timing repair is
    pre-route only. This is the probe-negative fallback — byte-for-byte the
    same BEHAVIOUR as before #147."""
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


# ── #147 — fork-capable real-SPEF post-route setup repair (probe-gated) ──────
def test_spef_repair_capable_branch_runs_real_setup_repair(tmp_path):
    """#147 — when the running OpenROAD carries the fork crash-fix
    (fork_repair_capable=True) the block reads the sign-off SPEF back and runs
    the real setup repair (repair_design + repair_timing -setup with the fork
    -detailed_routing incremental-reroute flag), each NONFATAL-guarded, and
    reports worst-slack before/after so the improvement is auditable."""
    tcl = R._post_route_spef_repair_tcl("/the_out", "/tech.lef",
                                        fork_repair_capable=True)
    cmds = "\n".join(ln for ln in tcl.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "read_spef /the_out/post_route_repair.spef" in cmds
    assert "repair_design" in cmds
    assert "repair_timing -setup -detailed_routing" in cmds
    assert "SPEF_REPAIR_APPLIED" in cmds
    # STILL measure-first: the sign-off SPEF is extracted before the repair.
    assert "SPEF_MEASURE_COMPLETE" in cmds
    # every repair move is guarded so one failure cannot abort the flow.
    assert "catch {repair_design}" in cmds
    assert "catch {repair_timing -setup -detailed_routing}" in cmds


def test_openroad_postroute_repair_probe(monkeypatch):
    """The #147 capability probe: env opt-in OR the fork `-detailed_routing`
    flag on repair_timing/repair_design help → capable; stock help / error →
    fail-safe False. Cached per container."""
    R._POSTROUTE_REPAIR_CAP_CACHE.clear()

    # (a) explicit env opt-in → capable.
    def _env_on(container, cmd, timeout=1800):
        if "VIBEIC_OPENROAD_POSTROUTE_SPEF_REPAIR" in cmd:
            return 0, "1", ""
        return 0, "", ""
    monkeypatch.setattr(R, "_docker_exec_raw", _env_on)
    assert R._openroad_supports_postroute_spef_repair("c-env") is True

    # (b) no env, but the fork flag is advertised on the repair-command help.
    R._POSTROUTE_REPAIR_CAP_CACHE.clear()

    def _fork_help(container, cmd, timeout=1800):
        if "VIBEIC_OPENROAD_POSTROUTE_SPEF_REPAIR" in cmd:
            return 0, "", ""
        return 0, ("repair_timing [-setup] [-hold] [-detailed_routing]\n"
                   "repair_design [-detailed_routing]\n"), ""
    monkeypatch.setattr(R, "_docker_exec_raw", _fork_help)
    assert R._openroad_supports_postroute_spef_repair("c-fork") is True

    # (c) stock help (no fork flag) → fail-safe False (guarded skip runs).
    R._POSTROUTE_REPAIR_CAP_CACHE.clear()

    def _stock_help(container, cmd, timeout=1800):
        if "VIBEIC_OPENROAD_POSTROUTE_SPEF_REPAIR" in cmd:
            return 0, "", ""
        return 0, "repair_timing [-setup] [-hold] [-recover_power percent]\n", ""
    monkeypatch.setattr(R, "_docker_exec_raw", _stock_help)
    assert R._openroad_supports_postroute_spef_repair("c-stock") is False

    # (d) docker/openroad error → fail-safe False (never speculatively enables).
    R._POSTROUTE_REPAIR_CAP_CACHE.clear()

    def _boom(container, cmd, timeout=1800):
        raise OSError("docker unreachable")
    monkeypatch.setattr(R, "_docker_exec_raw", _boom)
    assert R._openroad_supports_postroute_spef_repair("c-err") is False


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
