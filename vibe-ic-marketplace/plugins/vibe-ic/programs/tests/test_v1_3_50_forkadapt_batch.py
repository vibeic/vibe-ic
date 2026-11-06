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
import shutil
import sys
from pathlib import Path


_PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGS))
import phase3_one_shot_runner as R  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

tclsh = shutil.which("tclsh")


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









# ══════════════════════════════════════════════════════════════════════════
# R8 — librelane-first PnR cell-exclusion resolution
# ══════════════════════════════════════════════════════════════════════════

















_TCL_STUB = "proc unknown {args} { return \"\" }\n"
