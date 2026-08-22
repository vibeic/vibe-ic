"""v1.3.46 — TWO plugin-adaptation fixes to phase3_one_shot_runner.py, both
pinned here. Neither is a fork bug; the fork tools are correct and the plugin's
phase3 recipe / captable path went stale against the fork's newer OpenROAD
behavior + PDK layout.

FIX 1 — antenna GRT-0121 (plugin recipe).
    The pre-v1.3.46 `_antenna_repair_tcl` emitted `repair_antennas -iterations 5`
    (which trips GRT-0121: repair_antennas in `grt` cannot itself re-route, so
    N>1 iterations is illegal) followed by a single FULL `global_route` +
    `detailed_route` with NO outer loop. That left antenna residuals on
    sha256/caravel and full-rerouted ~1900 nets on ibex (timeout). The fix
    rewrites the emitted block to an incremental repair -> reroute -> repair
    OUTER loop that DROPS the full global_route: `repair_antennas -iterations 1`
    (no GRT-0121, marks only diode nets dirty) then `detailed_route` (incremental,
    re-routes only the dirty nets), converging on `check_antennas == 0`.

FIX 2 — OpenRCX empty-SPEF (plugin path).
    The image ships the sky130A OpenRCX captable at the fork's newer
    libs.tech/librelane/rules.openrcx.sky130A.{min,nom,max}.magic; the plugin
    hardcoded the OLD libs.tech/openlane at 3 sites -> 0 glob hits -> estimate
    fallback -> RCX-0134 -> empty SPEF. The fix tolerates BOTH dirs, preferring
    librelane and falling back to openlane (backward-compat for the old image).

Both fixes are chip/PDK/image-AGNOSTIC.
"""
import glob as _glob
import shlex as _shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")

_STUB = 'proc unknown {args} { return "" }\n'


def _run_tclsh(script_path: Path):
    return subprocess.run([tclsh, str(script_path)],
                          capture_output=True, text=True, timeout=60)


def _pdk() -> "R.PdkConfig":
    return R.PdkConfig(
        name="fixture_pdk",
        liberty="/pdk/lib.lib", tech_lef="/pdk/tech.lef",
        cell_lef="/pdk/cells.lef", cell_gds=None,
        site="unithd", drc_deck=None, metal_prefix="met",
        tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
        antenna_diode_cell="sky130_fd_sc_hd__diode_2",
        pnr_exclude_cell_file="/pdk/drc_exclude.cells",
    )


def _cmd_lines(block: str) -> str:
    """Return only the COMMAND lines (strip `#` comment lines) so a doctrine
    comment naming a banned command never trips a command-shape assertion."""
    return "\n".join(
        ln for ln in block.splitlines() if not ln.lstrip().startswith("#"))


# ── FIX 1: antenna incremental-loop SHAPE (v0.1.49 sequence-pinning) ──────────

def test_antenna_block_has_incremental_outer_loop():
    """The emitted antenna block must drive an OUTER loop over
    repair -> reroute -> re-check (not a single pass)."""
    block = R._antenna_repair_tcl(_pdk())
    cmds = _cmd_lines(block)
    assert "set _ant_cap" in cmds
    assert "for {set _i 0} {$_i < $_ant_cap} {incr _i}" in cmds


def test_antenna_block_repair_iterations_is_one_not_five():
    """`-iterations 1` kills GRT-0121 (repair_antennas can only run once per
    detailed-route). The pre-v1.3.46 `-iterations 5` must be gone."""
    block = R._antenna_repair_tcl(_pdk())
    cmds = _cmd_lines(block)
    assert "-iterations 1" in cmds
    assert "-iterations 5" not in cmds
    # the diode cell is still a POSITIONAL arg to repair_antennas
    assert "repair_antennas sky130_fd_sc_hd__diode_2 -iterations 1" in cmds


def test_antenna_block_drops_full_global_route():
    """No `global_route` COMMAND inside the antenna block — the full reroute is
    exactly what caused the ibex ~1900-net timeout. (Comments may still explain
    WHY it was dropped, hence command-line-only scan.)"""
    block = R._antenna_repair_tcl(_pdk())
    cmds = _cmd_lines(block)
    assert "global_route" not in cmds
    # incremental reroute IS present (dirty-net-only detailed_route)
    assert "detailed_route -verbose 0" in cmds


def test_antenna_block_check_antennas_break_on_zero():
    """The loop's convergence gate: re-measure with check_antennas each turn and
    break when 0 net violations remain; plus the authoritative final check."""
    block = R._antenna_repair_tcl(_pdk())
    cmds = _cmd_lines(block)
    assert "check_antennas" in cmds
    assert "$_nv == 0" in cmds
    assert "break" in cmds
    # final authoritative in-session check + terminal marker
    assert "ANTENNA_POSTROUTE_DONE" in block


def test_antenna_block_skips_when_pdk_has_no_diode():
    pdk = _pdk()
    pdk.antenna_diode_cell = None
    block = R._antenna_repair_tcl(pdk)
    assert "ANTENNA_REPAIR_SKIPPED" in block
    assert "repair_antennas" not in block


@needs_tclsh
def test_antenna_block_parses_and_evaluates_in_tclsh():
    """The emitted block must survive a REAL Tcl parse/eval (OpenROAD is a Tcl
    interpreter). tclsh with every tool command stubbed exercises the identical
    parser; the block must reach ANTENNA_POSTROUTE_DONE with returncode 0."""
    block = R._antenna_repair_tcl(_pdk())
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "ant.tcl"
        script.write_text(_STUB + block)
        result = _run_tclsh(script)
    assert result.returncode == 0, result.stderr
    assert "missing close-bracket" not in result.stderr
    assert "ANTENNA_POSTROUTE_DONE" in result.stdout


# ── FIX 2: OpenRCX captable — librelane-first, openlane fallback ──────────────

def _stage(root: Path, subdir: str, corners=("min", "nom", "max")) -> str:
    """Stage a PDK tree whose captable lives under libs.tech/<subdir>; return the
    tech-LEF path (.../libs.ref/fix/tech.lef) that drives root discovery."""
    d = root / "pdk" / "libs.tech" / subdir
    d.mkdir(parents=True, exist_ok=True)
    for c in corners:
        (d / f"rules.openrcx.sky130A.{c}.magic").write_text("# captable\n")
    ref = root / "pdk" / "libs.ref" / "fix"
    ref.mkdir(parents=True, exist_ok=True)
    return str(ref / "tech.lef")


def _fake_ls(_container, ls_expr, must_contain, timeout=20):
    """Host-filesystem stand-in for `_container_ls_paths` (test container path ==
    host path). Mirrors the real filter: keep lines starting with `/` that
    contain must_contain; sorted for determinism."""
    hits = []
    for pat in _shlex.split(ls_expr):
        for p in sorted(_glob.glob(pat)):
            if p.startswith("/") and must_contain in p and p not in hits:
                hits.append(p)
    return hits


def test_discover_captables_hits_librelane(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_container_ls_paths", _fake_ls)
    tlef = _stage(tmp_path, "librelane")
    pdk = _pdk()
    pdk.tech_lef = tlef
    out = R._discover_openrcx_captables(pdk, container="fake")
    assert set(out) == {"min", "nom", "max"}
    for c in ("min", "nom", "max"):
        assert "/libs.tech/librelane/" in out[c]
        assert out[c].endswith(f".{c}.magic")


def test_discover_captables_backward_compat_openlane(tmp_path, monkeypatch):
    """Old image (captable under libs.tech/openlane) must still be found."""
    monkeypatch.setattr(R, "_container_ls_paths", _fake_ls)
    tlef = _stage(tmp_path, "openlane")
    pdk = _pdk()
    pdk.tech_lef = tlef
    out = R._discover_openrcx_captables(pdk, container="fake")
    assert set(out) == {"min", "nom", "max"}
    for c in ("min", "nom", "max"):
        assert "/libs.tech/openlane/" in out[c]


def test_discover_captables_prefers_librelane_when_both_present(
        tmp_path, monkeypatch):
    monkeypatch.setattr(R, "_container_ls_paths", _fake_ls)
    tlef = _stage(tmp_path, "librelane")
    _stage(tmp_path, "openlane")
    pdk = _pdk()
    pdk.tech_lef = tlef
    out = R._discover_openrcx_captables(pdk, container="fake")
    assert set(out) == {"min", "nom", "max"}
    for c in ("min", "nom", "max"):
        assert "/libs.tech/librelane/" in out[c], out[c]


# ── FIX 2: the two emitted-TCL SPEF globs must hit BOTH dirs ──────────────────

def _stage_tcl(root: Path, subdir: str) -> str:
    d = root / "pdk" / "libs.tech" / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / "rules.openrcx.sky130A.nom.magic").write_text("# captable\n")
    ref = root / "pdk" / "libs.ref" / "fix"
    ref.mkdir(parents=True, exist_ok=True)
    return str(ref / "tech.lef")


@needs_tclsh
@pytest.mark.parametrize("subdir", ["librelane", "openlane"])
def test_post_route_spef_tcl_globs_both_dirs(tmp_path, subdir):
    """The post-route-repair SPEF glob (`_post_route_spef_repair_tcl`) must
    resolve the captable whether it lives under librelane (new image) or
    openlane (old image)."""
    tlef = _stage_tcl(tmp_path / subdir, subdir)
    block = R._post_route_spef_repair_tcl(str(tmp_path / "out"), tlef)
    script = tmp_path / f"prs_{subdir}.tcl"
    script.write_text(_STUB + block)
    result = _run_tclsh(script)
    assert result.returncode == 0, result.stderr
    assert "SPEF_REPAIR_CAPTABLE" in result.stdout
    assert f"/libs.tech/{subdir}/" in result.stdout
    assert "SPEF_MEASURE_COMPLETE" in result.stdout


@needs_tclsh
def test_post_route_spef_tcl_prefers_librelane(tmp_path):
    base = tmp_path / "both"
    tlef = _stage_tcl(base, "librelane")
    _stage_tcl(base, "openlane")
    block = R._post_route_spef_repair_tcl(str(tmp_path / "out"), tlef)
    script = tmp_path / "prs_both.tcl"
    script.write_text(_STUB + block)
    result = _run_tclsh(script)
    assert result.returncode == 0, result.stderr
    assert "/libs.tech/librelane/" in result.stdout


def test_source_has_no_bare_openlane_only_captable_glob():
    """Guard against a regression to a hardcoded openlane-ONLY captable glob:
    every rules.openrcx glob must offer librelane as well."""
    src = (PROG / "phase3_one_shot_runner.py").read_text()
    for ln in src.splitlines():
        if "glob -nocomplain" in ln and "rules.openrcx" in ln:
            assert "librelane" in ln, f"openlane-only captable glob: {ln!r}"
