"""v1.3.50 — fork-adaptation batch (same class as v1.3.46: the plugin's
recipe/path went stale against the forked vibeic-eda:0.2.5 image; the fork
tools are correct). Two of the three v1.3.50 fixes are pinned here (R7 lives
in test_project_outputs_in_tree_check.py):

R5 — die-sizer must HONOR an L9-mandated FIXED DIE_AREA (do not auto-size over).
    `phase3_one_shot_runner` auto-sized the die from the netlist cell count and
    ignored an L9/floorplan-spec-mandated FIXED die (caravel needs 2920×3520 for
    its macro harness). FIX: `_l9_declared_die_area` reads an explicit fixed
    DIE_AREA from L9; `_effective_die_um` enforces the precedence
    explicit `--die-um` flag > L9 fixed DIE_AREA > auto-size.

R8 — `pnr_exclude_cell_file` librelane-first + filename tolerance (3rd stale
    LibreLane path). The fork MOVED+RENAMED libs.tech/openlane/*/drc_exclude.cells
    → libs.tech/librelane/*/pnr_excluded.cells. FIX: `_resolve_pnr_exclude_cell_file`
    (host-side glob) + `_dont_use_tcl` (container-side brace glob) resolve
    librelane-first, openlane fallback, tolerating BOTH filenames.

All chip/PDK/image-AGNOSTIC + deterministic (no LLM judgment).
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGS))
import phase3_one_shot_runner as R  # noqa: E402

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")


# ══════════════════════════════════════════════════════════════════════════
# R5 — L9-mandated fixed DIE_AREA
# ══════════════════════════════════════════════════════════════════════════

def _proj_with_l9(tmp_path, body, name="L9_floorplan.md"):
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / name).write_text(body)
    return tmp_path


def test_r5_die_area_rect_markdown_table(tmp_path):
    proj = _proj_with_l9(tmp_path, "| DIE_AREA | 0 0 2920 3520 |\n")
    assert R._l9_declared_die_area(proj) == "2920x3520"


def test_r5_die_area_rect_tcl_env(tmp_path):
    proj = _proj_with_l9(tmp_path, 'set ::env(DIE_AREA) "0 0 1500.5 900"\n',
                         name="L9_constraints.md")
    # 1500.5 rounds to 1500 (int(round))
    assert R._l9_declared_die_area(proj) == "1500x900"


def test_r5_die_area_rect_json_config(tmp_path):
    proj = _proj_with_l9(tmp_path, '  "DIE_AREA": "0 0 400 500",\n')
    assert R._l9_declared_die_area(proj) == "400x500"


def test_r5_die_area_nonzero_origin(tmp_path):
    # W = urx-llx, H = ury-lly (origin need not be 0,0).
    proj = _proj_with_l9(tmp_path, "DIE_AREA = 10 20 1010 1520\n")
    assert R._l9_declared_die_area(proj) == "1000x1500"


def test_r5_die_width_height_pair(tmp_path):
    proj = _proj_with_l9(tmp_path, "- DIE_WIDTH = 800 um\n- DIE_HEIGHT = 1200 um\n")
    assert R._l9_declared_die_area(proj) == "800x1200"


def test_r5_no_declaration_returns_none(tmp_path):
    # "plugin decides" cell (no adjacent 4-number rect) + a util row that must
    # NOT be mis-read as a die.
    proj = _proj_with_l9(tmp_path,
                         "| DIE_AREA | plugin decides |\n| FP_CORE_UTIL | 45 |\n")
    assert R._l9_declared_die_area(proj) is None


def test_r5_die_width_only_returns_none(tmp_path):
    # DIE_WIDTH without DIE_HEIGHT → ambiguous → None (both required).
    proj = _proj_with_l9(tmp_path, "- DIE_WIDTH = 800 um\n")
    assert R._l9_declared_die_area(proj) is None


def test_r5_none_project(tmp_path):
    assert R._l9_declared_die_area(None) is None
    # A project with NO L9 doc at all → None (auto-size path unchanged).
    assert R._l9_declared_die_area(tmp_path) is None


# --- precedence: explicit --die-um flag > L9 fixed DIE_AREA > auto ---

def test_r5_precedence_explicit_flag_wins_over_l9(tmp_path):
    """An explicit `--die-um WxH` flag is returned verbatim and L9 is NOT even
    consulted (a fixed L9 die must NOT override the caller's explicit flag)."""
    proj = _proj_with_l9(tmp_path, "| DIE_AREA | 0 0 2920 3520 |\n")
    die, note = R._effective_die_um("1200x1200", proj)
    assert die == "1200x1200"
    assert note is None


def test_r5_precedence_l9_used_when_flag_is_auto(tmp_path):
    proj = _proj_with_l9(tmp_path, "| DIE_AREA | 0 0 2920 3520 |\n")
    die, note = R._effective_die_um("auto", proj)
    assert die == "2920x3520"
    assert note and "2920x3520" in note


def test_r5_precedence_auto_passes_through_without_l9(tmp_path):
    """`--die-um auto` with NO L9 fixed die stays 'auto' → the netlist-based
    auto-sizer runs unchanged (regression guard: R5 must not alter this path)."""
    die, note = R._effective_die_um("auto", tmp_path)
    assert die == "auto"
    assert note is None


def test_r5_effective_die_is_pinned_not_auto(tmp_path):
    """A resolved L9 die is a concrete WxH, so the downstream over-sparse
    downsize retry (gated on die_um == 'auto') will NOT fire — the die is
    honored verbatim."""
    proj = _proj_with_l9(tmp_path, "DIE_AREA = 0 0 2920 3520\n")
    die, _ = R._effective_die_um("auto", proj)
    assert str(die).lower() != "auto"
    assert die == "2920x3520"


# ══════════════════════════════════════════════════════════════════════════
# R8 — librelane-first PnR cell-exclusion resolution
# ══════════════════════════════════════════════════════════════════════════

def _stage_exclude(root: Path, subdir: str, filename: str):
    d = root / "libs.tech" / subdir / "sky130_fd_sc_hd"
    d.mkdir(parents=True, exist_ok=True)
    f = d / filename
    f.write_text("sky130_fd_sc_hd__probe_p_8\n"
                 "# comment line\n"
                 "sky130_fd_sc_hd__lpflow_isobufsrc_1\n")
    return f


def test_r8_resolve_librelane_found(tmp_path):
    _stage_exclude(tmp_path, "librelane", "pnr_excluded.cells")
    got = R._resolve_pnr_exclude_cell_file(tmp_path)
    assert got is not None
    assert "/libs.tech/librelane/" in got
    assert got.endswith("pnr_excluded.cells")


def test_r8_resolve_openlane_fallback(tmp_path):
    _stage_exclude(tmp_path, "openlane", "drc_exclude.cells")
    got = R._resolve_pnr_exclude_cell_file(tmp_path)
    assert got is not None
    assert "/libs.tech/openlane/" in got
    assert got.endswith("drc_exclude.cells")


def test_r8_resolve_prefers_librelane_when_both_present(tmp_path):
    _stage_exclude(tmp_path, "librelane", "pnr_excluded.cells")
    _stage_exclude(tmp_path, "openlane", "drc_exclude.cells")
    got = R._resolve_pnr_exclude_cell_file(tmp_path)
    assert "/libs.tech/librelane/" in got, got


def test_r8_resolve_neither_returns_none(tmp_path):
    assert R._resolve_pnr_exclude_cell_file(tmp_path) is None


def test_r8_dont_use_tcl_globs_both_dirs_and_names():
    pdk = R.PdkConfig(
        name="sky130A", liberty="x", tech_lef="x", cell_lef="x", cell_gds=None,
        site="unithd", drc_deck=None,
        pnr_exclude_cell_file="/foss/pdks/sky130A/libs.tech/librelane/"
        "sky130_fd_sc_hd/pnr_excluded.cells")
    tcl = R._dont_use_tcl(pdk)
    assert "{librelane openlane}" in tcl        # librelane first
    assert "{pnr_excluded.cells drc_exclude.cells}" in tcl
    assert "set _du_root /foss/pdks/sky130A" in tcl
    # get_lib_cells family fallback still runs first (belt-and-suspenders).
    assert "DONT_USE_FALLBACK_APPLIED" in tcl


def test_r8_dont_use_tcl_none_file_skips_with_fallback():
    pdk = R.PdkConfig(
        name="x", liberty="", tech_lef="", cell_lef="", cell_gds=None,
        site="", drc_deck=None, pnr_exclude_cell_file=None)
    tcl = R._dont_use_tcl(pdk)
    assert "DONT_USE_SKIPPED: no PNR" in tcl
    assert "DONT_USE_FALLBACK_APPLIED" in tcl   # fallback still present


def _run_tclsh(script: Path):
    return subprocess.run([tclsh, str(script)], capture_output=True,
                          text=True, timeout=60)


_TCL_STUB = "proc unknown {args} { return \"\" }\n"


@needs_tclsh
@pytest.mark.parametrize("subdir,filename", [
    ("librelane", "pnr_excluded.cells"),
    ("openlane", "drc_exclude.cells"),
])
def test_r8_dont_use_tcl_resolves_in_tclsh(tmp_path, subdir, filename):
    """The emitted glob must resolve the exclude file whether it lives under the
    new-image librelane/pnr_excluded.cells or the old-image
    openlane/drc_exclude.cells — evaluated in a real tclsh with tool commands
    stubbed (exercises the identical glob/open/gets logic OpenROAD's tclsh runs)."""
    pdk_root = tmp_path / "pdk"
    resolved = _stage_exclude(pdk_root, subdir, filename)
    # The configured PRIMARY hint points at the librelane path; the glob derives
    # the root from it and finds whichever image actually shipped the file.
    pdk = R.PdkConfig(
        name="sky130A", liberty="x", tech_lef="x", cell_lef="x", cell_gds=None,
        site="unithd", drc_deck=None,
        pnr_exclude_cell_file=str(pdk_root / "libs.tech" / "librelane"
                                  / "sky130_fd_sc_hd" / "pnr_excluded.cells"))
    script = tmp_path / "dont_use.tcl"
    script.write_text(_TCL_STUB + R._dont_use_tcl(pdk))
    r = _run_tclsh(script)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DONT_USE_APPLIED: 2 cells from" in r.stdout, r.stdout
    assert str(resolved) in r.stdout


@needs_tclsh
def test_r8_dont_use_tcl_prefers_librelane_in_tclsh(tmp_path):
    pdk_root = tmp_path / "pdk"
    lib = _stage_exclude(pdk_root, "librelane", "pnr_excluded.cells")
    _stage_exclude(pdk_root, "openlane", "drc_exclude.cells")
    pdk = R.PdkConfig(
        name="sky130A", liberty="x", tech_lef="x", cell_lef="x", cell_gds=None,
        site="unithd", drc_deck=None,
        pnr_exclude_cell_file=str(pdk_root / "libs.tech" / "librelane"
                                  / "sky130_fd_sc_hd" / "pnr_excluded.cells"))
    script = tmp_path / "dont_use.tcl"
    script.write_text(_TCL_STUB + R._dont_use_tcl(pdk))
    r = _run_tclsh(script)
    assert r.returncode == 0, r.stdout + r.stderr
    assert str(lib) in r.stdout, r.stdout          # librelane wins
    assert "/libs.tech/openlane/" not in r.stdout


@needs_tclsh
def test_r8_dont_use_tcl_neither_present_skips_in_tclsh(tmp_path):
    """Neither image's file present → NONFATAL skip (prior behavior preserved);
    the get_lib_cells family fallback above still covers the resizer."""
    pdk_root = tmp_path / "pdk"
    (pdk_root / "libs.tech").mkdir(parents=True)
    pdk = R.PdkConfig(
        name="sky130A", liberty="x", tech_lef="x", cell_lef="x", cell_gds=None,
        site="unithd", drc_deck=None,
        pnr_exclude_cell_file=str(pdk_root / "libs.tech" / "librelane"
                                  / "sky130_fd_sc_hd" / "pnr_excluded.cells"))
    script = tmp_path / "dont_use.tcl"
    script.write_text(_TCL_STUB + R._dont_use_tcl(pdk))
    r = _run_tclsh(script)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "DONT_USE_SKIPPED" in r.stdout


def test_r8_detect_pdk_sky130A_points_at_librelane():
    """Regression guard: the container sky130A config's primary hint is the
    librelane path (not the stale openlane one)."""
    pdk = R._detect_pdk(Path("/nonexistent"), override="sky130A")
    assert pdk is not None
    assert "/libs.tech/librelane/" in pdk.pnr_exclude_cell_file
    assert pdk.pnr_exclude_cell_file.endswith("pnr_excluded.cells")
