"""#565 — a bounded selection that does not say what it dropped reads as full coverage.

`ci_targeted_test_select`'s default `ownership` mode maps a changed module to
tests by FILENAME, so a test named after the chip or the feature is invisible
however directly it imports the module. Measured over the tests tree: 2035 of
2850 import edges — 71% — are unseeable by name.

WHETHER TO WIDEN THE DEFAULT IS A COST DECISION and stays the owner's; #534
built the `--mode import-edge` lane and left the default where it is with the
reason written down. This is the other half of the issue's own ask:

    "If the measured cost turns out to be unacceptable, the fallback must
     DISCLOSE what it dropped rather than silently narrow."

MEASURED ON THIS REPO'S OWN LANDINGS, which is what makes it worth the 3 s:

    #628 landing (formal_property_run)   selected 18   4 importers not selected
    #627 landing (phase3_one_shot_runner) selected 20  161 importers not selected

The gate stamped `targeted tests (20 file(s)) PASS` on the second one. 161 test
files that import the module that landing changed did not run, and nothing said
so. That is the shape this repo keeps finding — an absence rendering as a pass —
sitting inside the gate that certifies every landing.

THE SELECTION IS UNCHANGED. This adds a sentence, not a test.
"""
from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

C = importlib.import_module("ci_targeted_test_select")

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent


#: MEASURED: this whole file runs in ~8 s and one CLI invocation is ~4 s (the
#: import-edge index over the tests tree dominates). 60 is the harness ceiling
#: for an inner subprocess bound — above it the bound outlives the 180 s harness
#: and kills the SESSION instead of the test.
_BUDGET_S = 60


def _git(repo, *a):
    subprocess.run(["git", "-C", str(repo), *a], capture_output=True,
                   timeout=_BUDGET_S)


def _tree(tmp_path):
    """A plugin tree where one source module is imported by a test whose NAME
    does not own it — the exact shape name-ownership cannot see."""
    prog = tmp_path / "programs"
    tests = prog / "tests"
    tests.mkdir(parents=True)
    (prog / "widget_runner.py").write_text("X = 1\n", encoding="utf-8")
    # owned by name -> selected by rule 1
    (tests / "test_widget_runner.py").write_text(
        "import widget_runner\n", encoding="utf-8")
    # NOT owned by name, but imports it -> the invisible edge
    (tests / "test_acme_chip_flow.py").write_text(
        "import widget_runner\n", encoding="utf-8")
    (tests / "test_other_feature.py").write_text(
        "from widget_runner import X\n", encoding="utf-8")
    return tmp_path


# ── the disclosure, driven as a PURE function against a real tree ──────────
# The CLI resolves `plugin_root` from the SCRIPT's own location, so a fixture
# handed to it is never read — the first version of this file "passed" while
# auditing the real plugin. `import_edge_gap` exists so the computation can be
# driven against a constructed tree, which is the only way these assertions
# mean what they say.
def test_the_gap_names_the_module_and_both_numbers(tmp_path):
    """A count of what ran is not a coverage statement without a count of what
    did not."""
    root = _tree(tmp_path)
    sel = C.select_tests(["programs/widget_runner.py"], root)
    rows, total = C.import_edge_gap(["programs/widget_runner.py"], sel, root)
    assert rows == [("widget_runner", 3, 1, 2)], rows
    assert total == 2


def test_the_invisible_edge_is_the_one_named_after_the_chip(tmp_path):
    """The exact shape name-ownership cannot see: a test that imports the
    module directly but is named for the chip."""
    root = _tree(tmp_path)
    sel = set(C.select_tests(["programs/widget_runner.py"], root))
    imp = C._build_import_edge_index(root, {"widget_runner"})["widget_runner"]
    missed = sorted(imp - sel)
    assert any("acme_chip_flow" in m for m in missed), missed
    assert not any("test_widget_runner" in m for m in missed), (
        "the name-owned test should already be selected")


def test_a_change_with_no_invisible_edge_reports_nothing(tmp_path):
    """THE ACCEPT CASE: when name-ownership covers every importer there is no
    gap, and inventing a line for it trains the reader to skip it."""
    prog = tmp_path / "programs"
    tests = prog / "tests"
    tests.mkdir(parents=True)
    (prog / "solo.py").write_text("X = 1\n", encoding="utf-8")
    (tests / "test_solo.py").write_text("import solo\n", encoding="utf-8")
    sel = C.select_tests(["programs/solo.py"], tmp_path)
    rows, total = C.import_edge_gap(["programs/solo.py"], sel, tmp_path)
    assert total == 0, rows


def test_a_changed_test_file_is_not_treated_as_a_source_module(tmp_path):
    """Rule 2 already selects a directly-changed test, and its stem is not a
    source module — feeding it in would report a gap about the wrong thing.

    NON-VACUOUS BY CONSTRUCTION, which the first version was not: the changed
    test file's stem HAS importers here (the shared-helper shape rule 4 exists
    for), so removing the filter DOES produce a row and the mutation is caught.
    Asserting on a stem nobody imports proves only that nobody imports it."""
    root = _tree(tmp_path)
    tests = root / "programs" / "tests"
    (tests / "test_shared_fixture.py").write_text("X = 1\n", encoding="utf-8")
    (tests / "test_uses_a.py").write_text(
        "import test_shared_fixture\n", encoding="utf-8")
    (tests / "test_uses_b.py").write_text(
        "import test_shared_fixture\n", encoding="utf-8")
    # the stem really is importable-and-imported ...
    idx = C._build_import_edge_index(root, {"test_shared_fixture"})
    assert len(idx.get("test_shared_fixture", set())) == 2, idx
    # ... and it still contributes no gap row, because it is not a source module
    rows, total = C.import_edge_gap(
        ["programs/tests/test_shared_fixture.py"], [], root)
    assert rows == [] and total == 0, rows


def test_a_non_python_change_contributes_nothing(tmp_path):
    root = _tree(tmp_path)
    assert C.import_edge_gap(["flow/phase1_phase2_phase3.yaml"], [], root) \
        == ([], 0)


# ── the CLI prints it, on stderr, with the next move ───────────────────────
def _cli(extra=()):
    """Against the REAL plugin, because that is the only tree the CLI reads."""
    return subprocess.run(
        [sys.executable, str(_PROGRAMS / "ci_targeted_test_select.py"),
         "--base", "HEAD~1", *extra],
        cwd=str(_PLUGIN.parents[1]), capture_output=True, text=True,
        timeout=_BUDGET_S)


def test_the_report_reaches_stderr_not_stdout():
    """stdout is the test list a runner consumes; a disclosure written there
    would be handed to pytest as a filename."""
    r = _cli()
    if "IMPORT-EDGE GAP" not in r.stderr:
        return          # the previous commit touched no source module
    assert "IMPORT-EDGE GAP" not in r.stdout
    assert "imported by" in r.stderr and "NOT selected" in r.stderr
    assert "--mode import-edge" in r.stderr, "no next move is stated"


def test_opting_out_is_possible_and_silent():
    assert "IMPORT-EDGE GAP" not in _cli(("--no-gap-report",)).stderr


def test_the_selection_itself_is_unchanged(tmp_path):
    """LOAD-BEARING. The cost decision stays the owner's; this adds a sentence,
    not a test.

    Compared against `select_tests` computed INDEPENDENTLY, not against the CLI
    run with the report off: the report is emitted after the list is printed, so
    a mutation that widened `selected` afterwards left stdout identical and the
    two-CLI comparison could not see it. The invariant is that the CLI emits
    exactly what the pure selector returns."""
    root = _tree(tmp_path)
    expected = C.select_tests(["programs/widget_runner.py"], root)
    rows, _total = C.import_edge_gap(["programs/widget_runner.py"], expected,
                                     root)
    assert rows, "the fixture must have a gap or this proves nothing"
    after = C.select_tests(["programs/widget_runner.py"], root)
    assert after == expected, "computing the gap perturbed the selection"
    assert not any(r[0] in set(after) for r in rows), (
        "a gap ROW leaked into the selection")


def test_a_failed_report_says_the_shortfall_is_UNKNOWN_not_zero(monkeypatch):
    """The disclosure is not a dependency — a selection that dies computing its
    own footnote selects nothing. But silence on failure is the defect again."""
    import contextlib
    import io
    monkeypatch.setattr(C, "import_edge_gap",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        rc = C.main(["--base", "HEAD~1"])
    assert rc == 0, "the selection must survive its own footnote failing"
    out = err.getvalue()
    assert "gap report unavailable" in out and "UNKNOWN, not zero" in out


# ── the shipped tree has the gap this is about ────────────────────────────
def test_the_worst_case_module_is_still_the_worst_case():
    """The issue's headline number, re-derived so it cannot rot into a claim
    nobody re-measures."""
    idx = C._build_import_edge_index(_PLUGIN, {"phase3_one_shot_runner"})
    imp = idx.get("phase3_one_shot_runner", set())
    if not imp:
        return
    sel = set(C.select_tests(["programs/phase3_one_shot_runner.py"], _PLUGIN))
    assert len(imp) > 100 and len(imp - sel) > 100, (
        f"imported by {len(imp)}, not selected {len(imp - sel)} — if the gap "
        f"has closed, re-derive the issue's numbers rather than leaving this "
        f"assertion describing a world that no longer exists")
