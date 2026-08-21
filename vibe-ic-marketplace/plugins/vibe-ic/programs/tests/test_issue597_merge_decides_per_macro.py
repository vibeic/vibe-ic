"""#597 — the M1 merge appended, so a macro already in the digital GDS doubled.

`Layout.read` APPENDS into a cell that already exists under the same name. Once
OpenROAD's stream-out has been handed the hardmacro GDS, the digital GDS already
carries a REAL body for that macro, and reading the macro file on top of it put
every polygon in twice. Measured on the run that raised this:

    delta_sigma   45678 -> 91356      exactly 2x
    ldo           36887 -> 73774      exactly 2x

Magic then extracts the duplicated geometry as duplicated devices, so the
layout-side device count is 2x the schematic's and LVS can never match — a
failure whose report reads like a design defect rather than like a merge bug.

PRESENCE OF THE CELL NAME IS NOT EVIDENCE THAT IT IS AN ABSTRACT, and the old
merge assumed it was. The branch is now taken on whether the cell actually holds
geometry:

    not present   -> added          (read it in)
    0 shapes      -> filled         (an abstract placeholder — the old intent)
    >0 shapes     -> kept_digital   (a real body; reading would double it)

REPRODUCED AND FIXED AGAINST THE REAL KLAYOUT, not against a mock — a synthetic
pair whose digital GDS already carries the macro's 3 shapes:

    digital input      3
    old merge          6      <- the defect, same 2x ratio
    new merge          3
    merge.json         {"macro": "MACRO_A", "action": "kept_digital",
                        "shapes_before": 3, "shapes_after": 3}

and the accept case, an abstract that must still be filled:

    filled 0 -> 3

Both API corrections in `own_shapes` came from that run rather than from reading
the binding: `cell_name_to_index` does not exist on this Layout, and
`cell_by_name` returns an INDEX, not a cell.

These tests assert the SCRIPT's shape rather than running KLayout, because the
tool is not present on every host that runs the suite. The behavioural evidence
is the measurement above; what is pinned here is that the decision exists, that
all three branches are expressible, and that the artefact records which was
taken — so a doubled body is visible in `merge.json` instead of inferred from an
LVS mismatch two steps later.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "mixed_signal_top_lvs_run", _PROGRAMS / "mixed_signal_top_lvs_run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mixed_signal_top_lvs_run"] = mod
    spec.loader.exec_module(mod)
    return mod


M = _load()
SRC = M._KLAYOUT_MERGE_PY


# ── the merge script is real python and decides rather than appending ────────
def test_the_embedded_script_parses():
    """It runs under KLayout's interpreter, so a syntax error would only
    surface as a failed merge inside a container."""
    ast.parse(SRC)


def test_it_no_longer_reads_every_macro_unconditionally():
    """The defect in one line: `for g in ...: ly.read(g)`."""
    tree = ast.parse(SRC)
    # a bare `ly.read(g)` directly inside the macro loop is what doubled things
    assert "action" in SRC and "kept_digital" in SRC, (
        "the merge no longer records a decision; it is appending again")


def test_all_three_branches_are_expressible():
    for branch in ("added", "filled", "kept_digital"):
        assert f'"{branch}"' in SRC, f"branch {branch} is gone"


def test_a_populated_cell_takes_the_kept_branch():
    """`before > 0` must not read the macro file in."""
    assert "kept_digital" in SRC
    assert 'if all(r["action"] != "kept_digital"' in SRC, (
        "the read is no longer guarded by the decision")


def test_the_abstract_case_is_still_filled():
    """LOAD-BEARING. A fix that simply never merged would pass every
    doubling assertion and break the step's actual purpose."""
    assert 'elif before == 0:' in SRC and '"filled"' in SRC


def test_a_macro_absent_from_the_digital_gds_is_added():
    assert 'if before is None:' in SRC and '"added"' in SRC


# ── the record ───────────────────────────────────────────────────────────────
def test_the_branch_and_the_counts_are_recorded():
    for field in ("shapes_before", "shapes_after", "merged_out", "macros"):
        assert field in SRC, f"{field} is not recorded"


def test_merge_json_is_passed_by_the_caller():
    """A record the script writes to a path nobody supplies is not a record."""
    src = (_PROGRAMS / "mixed_signal_top_lvs_run.py").read_text(encoding="utf-8")
    assert "MERGE_JSON=" in src, "MERGE_JSON is never exported to the merge"


def test_the_klayout_api_corrections_are_kept():
    """Both were found by running against the real tool. `cell_name_to_index`
    is not on this Layout binding, and `cell_by_name` returns an index.

    COMMENTS STRIPPED, and asserted present separately. The comment has to NAME
    the wrong call in order to explain why it is not used, so a scan that cannot
    tell documentation from code fails on its own rationale — which is exactly
    what the first version of this test did.
    """
    code = "\n".join(ln for ln in SRC.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "cell_name_to_index" not in code, (
        "the call that raised AttributeError against the real KLayout is back")
    assert "ly.cell(ly.cell_by_name(" in code
    assert "cell_name_to_index" in SRC, (
        "the comment explaining why that call is avoided is gone; the next "
        "reader restores it as the obvious lookup")


def test_a_missing_merge_json_env_does_not_break_the_merge():
    """The record is additive: a caller that does not ask for it still gets a
    merged GDS."""
    assert 'os.environ.get("MERGE_JSON")' in SRC, (
        "MERGE_JSON is read with [] rather than .get(), so an older caller "
        "would crash the merge")
