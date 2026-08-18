#!/usr/bin/env python3
"""A test that reads a source directory by GLOB must be selected — vibe-ic#1387.

WHY THIS FILE EXISTS, measured on #1265
=======================================
#1265 swapped `Path(args.json).write_text(...)` for
`_atomic_output.atomic_write_text(...)` in `programs/eda_report_audit.py`. The
targeted selection ran 40 files and reported **NEW 0**. Run by hand,
`test_matrix_d7_outputs_list_complete.py` was **11 red against main's 10**:

    em_report_check's --json no longer resolves through its delegate;
    local modules seen: ('eda_report_audit',)

The test was never selected, and no rule could have selected it:
`matrix_d7_artifact_graph.py:524` reaches every program through
`F.PROGRAMS_DIR.glob("*.py")`, so there is no import to follow (rules 4/5) and
`grep -c eda_report_audit` over BOTH the test and the helper returns 0, so there
is no name to match (rule 3). The dependency is total, real, and expressed only
as a directory read.

The failure mode is SILENT and one-directional: it always under-selects, so it
always makes a PR look cleaner than it is. That is why this is guarded rather
than left to the next reader to notice.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PLUGIN = _HERE.parent.parent
_PREFIX = "vibe-ic-marketplace/plugins/vibe-ic"
_D7 = "programs/tests/test_matrix_d7_outputs_list_complete.py"


import _private_tree as _T  # noqa: E402


def _selector():
    path = _PLUGIN / "programs" / "ci_targeted_test_select.py"
    spec = importlib.util.spec_from_file_location("_sel_1387", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_sel_1387"] = mod
    spec.loader.exec_module(mod)
    return mod


def _select(paths, plugin=None):
    return _selector().select_tests(
        [f"{_PREFIX}/{p}" for p in paths], plugin or _PLUGIN,
        plugin_prefix=_PREFIX)


def _private_plugin_with_a_probe(tmp_path, name: str, body: str):
    """A plugin-shaped hardlink farm carrying one brand-new test file.

    THE PROBE USED TO BE WRITTEN INTO THE LIVE `programs/tests/` DIR and
    unlinked in a `finally`. The landing gate's per-file recovery path runs
    many pytest sessions at once over ONE shared checkout, so for the body of
    these two tests every neighbour saw an extra `test_zz1387_*.py` in the
    tree — and a spurious TEST file is worse than a spurious program, because
    the selectors, the per-file schedulers and the "every program has a test"
    audits all enumerate exactly that directory. The `finally` removes it, so
    `git status --porcelain` is clean and the manufactured red has no trace.

    `select_tests` takes the plugin root as an argument, so a farm is a
    complete substitute: every shipped file is the SAME INODE, and the probe is
    a new one that cannot reach the real tree.
    """
    plugin = _T.private_plugin(tmp_path, include_tests=True)
    probe = plugin / "programs" / "tests" / name
    probe.write_text(body, encoding="utf-8")
    return plugin


def test_the_1265_case_selects_the_glob_consumer():
    """The regression itself: the d7 delegate test must come with the program.

    Pinned to the real file rather than "some d7 test", because the whole defect
    was that this one specific consumer never ran.
    """
    if not (_PLUGIN / _D7).is_file():
        pytest.skip(f"{_D7} is not in this tree")
    sel = _select(["programs/eda_report_audit.py"])
    assert _D7 in sel, (
        f"a change to programs/eda_report_audit.py did not select {_D7}, which "
        f"reads every programs/*.py by glob — this is vibe-ic#1265 verbatim, "
        f"where the selection returned NEW 0 while that test was 11 red "
        f"against main's 10. Selected {len(sel)} file(s).")


def test_the_edge_is_DERIVED_not_a_hand_list(tmp_path, monkeypatch):
    """A consumer nobody has heard of must be selected on its own say-so.

    The module docstring's standing objection to hand-lists (rule 4, #527/#530)
    applies here too: a list of the 23 known globbers would be a second registry
    free to drift, and it would be wrong the first time anyone writes a new
    corpus-walking test. So the guard is that a BRAND-NEW file, never named
    anywhere, is picked up with no edit to the selector.
    """
    plugin = _private_plugin_with_a_probe(
        tmp_path, "test_zz1387_derived_probe.py",
        "import pathlib\n\n\n"
        "def test_probe():\n"
        "    list(pathlib.Path('programs').glob('*.py'))\n")
    sel = _select(["programs/eda_report_audit.py"], plugin)
    _T.assert_live_tree_unplanted("tests/test_zz1387_*.py")
    assert "programs/tests/test_zz1387_derived_probe.py" in sel, (
        "a newly written test that globs `*.py` was not selected — the rule is "
        "behaving like a hand-list, which is the defect #527/#530 removed and "
        "rule 4's docstring forbids")


def test_an_UNSHAPED_glob_is_not_an_edge(tmp_path):
    """`tmp_path.glob('*')` must not couple a fixture to the whole source tree.

    ANTI-COST guard, and it is load-bearing: measured on this tree, 38 of the 56
    files that matched `programs/eda_report_audit.py` matched ONLY via `"*"`,
    and they are temp-directory assertions with nothing to do with `programs/`.
    Admitting them took the #1265 case from +18 files to +53. A pattern that
    matches everything names no shape, exactly the objection that keeps
    `iterdir()` out.
    """
    plugin = _private_plugin_with_a_probe(
        tmp_path, "test_zz1387_unshaped_probe.py",
        "import pathlib\n\n\n"
        "def test_probe(tmp_path):\n"
        "    list(tmp_path.glob('*'))\n")
    sel = _select(["programs/eda_report_audit.py"], plugin)
    _T.assert_live_tree_unplanted("tests/test_zz1387_*.py")
    assert "programs/tests/test_zz1387_unshaped_probe.py" not in sel, (
        "a `glob('*')` over a tmp_path was treated as a dependency on the "
        "source tree; that edge is unshaped and would select 38 extra files "
        "per source change")


def test_rule_8_does_not_fire_without_a_changed_source_file():
    """Cost is paid only when it can buy something.

    Rules 4/6/7 are all lazy for this reason, and rule 8 must be too — a changed
    TEST file has no glob edge to resolve, so the index must not even be built.
    """
    sel = _select(["programs/tests/test_cvdp_gate.py"])
    assert _D7 not in sel, (
        "a changed test file dragged in the glob-consumer population; rule 8 "
        "should only fire for a changed SOURCE file")
