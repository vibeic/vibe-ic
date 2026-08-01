"""#565 — the import-edge lane was built and its cost was never taken.

`ci_targeted_test_select` already ships `--mode import-edge`; #534 built it and
left the DEFAULT at `ownership` with the reason written down: widening the
default "changes the DEFAULT per-landing cost for many unrelated diffs" and is
"that owner's call". The call was being asked without the one number it turns
on, so the number was taken.

ON THE EXACT REGRESSION #565 IS ABOUT — `phase3_one_shot_runner.py` changes and
`test_spm_ihp_openrcx_captable_layout.py` is the file pinning the behaviour a
734-line edit silently reverted for three releases:

    mode                selects    catches that test
    ownership              16         no
    reference-capped       16         no
    import-edge           176         YES
    reference             258         YES

WALL-CLOCK, real CI command, on this repo's own v1.9.18 diff:

    ownership     27 files     484 tests     49s
    import-edge  158 files    3276 tests    409s      (8.4x)

The default is NOT changed here. What is pinned below is that the two facts the
decision rests on stay true, so the table cannot quietly stop describing the
code.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent


def _load():
    spec = importlib.util.spec_from_file_location(
        "ci_targeted_test_select", _PROGRAMS / "ci_targeted_test_select.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ci_targeted_test_select"] = mod
    spec.loader.exec_module(mod)
    return mod


S = _load()
_PIN = "programs/tests/test_spm_ihp_openrcx_captable_layout.py"
_CHANGED = ["programs/phase3_one_shot_runner.py"]


@pytest.fixture(scope="module")
def selections():
    if not (_PROGRAMS / "phase3_one_shot_runner.py").is_file():
        pytest.skip("the source module is absent from this checkout")
    return {m: set(S.select_tests(_CHANGED, _PLUGIN, mode=m)) for m in S.MODES}


# ── the fact that makes the lane worth its cost ─────────────────────────────
def test_the_default_lane_still_misses_the_regression_this_issue_is_about(
        selections):
    """Not an aspiration — the current, shipped behaviour. If this ever starts
    passing, the cost table below is describing a world that moved on."""
    if _PIN not in {p for s in selections.values() for p in s}:
        pytest.skip("the pinning test is not in this checkout")
    assert _PIN not in selections[S.MODE_OWNERSHIP], (
        "ownership now catches it — re-measure the table; the trade-off it "
        "records has changed")


def test_the_capped_lane_misses_it_too(selections):
    """The cheap middle option does NOT buy this catch, which is the reason
    import-edge is on the table at all."""
    if _PIN not in {p for s in selections.values() for p in s}:
        pytest.skip("the pinning test is not in this checkout")
    assert _PIN not in selections[S.MODE_REFERENCE_CAPPED]


def test_the_import_edge_lane_catches_it(selections):
    if _PIN not in {p for s in selections.values() for p in s}:
        pytest.skip("the pinning test is not in this checkout")
    assert _PIN in selections[S.MODE_IMPORT_EDGE], (
        "the lane no longer buys the catch it costs 8x for")


def test_it_costs_less_than_the_reference_lane(selections):
    """The other half of the trade. If import-edge grew past `reference` there
    would be no reason to keep it as a separate option."""
    assert (len(selections[S.MODE_IMPORT_EDGE])
            < len(selections[S.MODE_REFERENCE]))


def test_it_costs_more_than_the_default(selections):
    """And it is not free — an assertion that would catch the lane silently
    collapsing to the ownership set, which is how it would look if the edge
    index stopped being built."""
    assert (len(selections[S.MODE_IMPORT_EDGE])
            > 4 * len(selections[S.MODE_OWNERSHIP]))


# ── the default is deliberately unchanged ───────────────────────────────────
def test_the_default_is_still_ownership():
    """LOAD-BEARING. Widening it is the owner's call, and this change takes the
    measurement rather than the decision. A default that drifted here would
    make every landing eight times more expensive as a side effect of
    documenting the option."""
    assert S.select_tests.__defaults__ is not None
    import inspect
    assert (inspect.signature(S.select_tests).parameters["mode"].default
            == S.MODE_OWNERSHIP)


def test_the_measured_row_is_recorded_where_the_decision_is_made():
    """The table lives in the module docstring beside the other lanes; a
    measurement kept somewhere else is one the next reader does not have."""
    src = (_PROGRAMS / "ci_targeted_test_select.py").read_text(encoding="utf-8")
    head = src.split('"""')[1]
    assert "import-edge" in head, "the lane is missing from the cost table"
    assert "409s" in head and "8.4x" in head, (
        "the wall-clock the decision turns on is not written down")
    assert "test_spm_ihp_openrcx_captable_layout" in head, (
        "the catch is claimed without naming the test it was measured on")
