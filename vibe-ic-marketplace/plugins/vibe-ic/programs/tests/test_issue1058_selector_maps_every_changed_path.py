"""Rule 7 — every changed path maps to a test set, or is DISCLOSED as unmapped.

THE AUDIT (vibe-ic#1058). vibe-ic#1057 fixed `tools/`. The follow-up question was
whether `tools/` was special or merely the one we noticed. It was the latter.

Probing every top-level directory with a trivial change, counting only tests
selected BEYOND the smoke floor (a floor hit is not a targeted selection):

    flow/phase1_phase2_phase3.yaml   114 covering tests   0 beyond floor
    skills/rtl-review/SKILL.md        67                  0
    .claude-plugin/plugin.json        35                  0
    .claude-plugin/marketplace.json   17                  0
    agents/ic-expert-agent.md         15                  0
    pytest.ini / conftest.py / hooks.json / run_tests.sh   1-4 each   0

Every path outside `programs/` and `benchmark/` selected exactly the 15-file
floor. The worst case is the canonical 44-step flow — the repo's single source of
truth — whose change selected nothing that reads it.

Rule 7 keys a changed path on the most specific suffix of its own path that is
UNIQUE in the tree. Nothing here is a filename list; the keys are computed from
the tree, so a file added tomorrow resolves with no edit to the selector.
"""
from __future__ import annotations

from pathlib import Path

import ci_targeted_test_select as sel

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
PREFIX = "vibe-ic-marketplace/plugins/vibe-ic"
TESTS_REL = "programs/tests"
FLOW = f"{PREFIX}/flow/phase1_phase2_phase3.yaml"


def _beyond_floor(changed):
    out = set(sel.select_tests(list(changed), PLUGIN_ROOT, plugin_prefix=PREFIX,
                               mode=sel.MODE_IMPORT_EDGE))
    return out - sel._smoke_set(PLUGIN_ROOT)


# ── the headline case ───────────────────────────────────────────────────────

def test_the_canonical_flow_yaml_reaches_the_tests_that_read_it():
    """114 tests name it; before the fix a change to it selected 0 of them."""
    beyond = _beyond_floor([FLOW])
    assert len(beyond) > 50, (
        f"the flow yaml selected only {len(beyond)} tests beyond the floor")
    for t in ("test_all_steps_covers_flow.py",
              "test_flow_condition_reachability_check.py"):
        assert f"{TESTS_REL}/{t}" in beyond | sel._smoke_set(PLUGIN_ROOT), t


def test_a_read_artefact_selects_the_tests_that_read_it():
    """The case displaced out of `test_helper_rule_does_not_widen…`.

    `programs/tests/flow_matrix/README.md` looks like docs and is not:
    `test_flow_matrix_census_freshness.py:66` reads it and asserts on its
    contents. A change to it must reach that test.
    """
    out = set(sel.select_tests([f"{PREFIX}/{TESTS_REL}/flow_matrix/README.md"],
                               PLUGIN_ROOT, plugin_prefix=PREFIX))
    assert f"{TESTS_REL}/test_flow_matrix_census_freshness.py" in out


def test_a_plugin_file_outside_the_source_dirs_is_mapped():
    """`pytest.ini` is plugin-relative but not under programs/ or benchmark/."""
    assert _beyond_floor([f"{PREFIX}/pytest.ini"])


# ── the uniqueness rule: why this is safe to apply to EVERYTHING ────────────

def test_an_ambiguous_basename_selects_nothing_rather_than_everything():
    """`README.md` exists 41 times, so no suffix identifies which one moved.

    Under-selecting an ambiguous name is recoverable. Over-selecting — dragging
    in every test that mentions a readme — teaches people to ignore the
    selection, which costs more than the miss.
    """
    assert _beyond_floor(["README.md"]) == set()


def test_the_key_is_the_shortest_suffix_that_is_unique_in_the_tree():
    """Derived from the tree, so it needs no list and cannot rot."""
    files = ["a/b/thing.py", "c/d/thing.py", "solo.py"]
    assert sel._distinctive_key("solo.py", files) == "solo.py"
    assert sel._distinctive_key("a/b/thing.py", files) == "b/thing.py"
    assert sel._distinctive_key("c/d/thing.py", files) == "d/thing.py"


def test_a_path_that_is_a_suffix_of_another_is_reported_unmappable():
    """The honest `None`, and a real case: the repo-root marketplace manifest.

    `.claude-plugin/marketplace.json` is a proper suffix of
    `vibe-ic-marketplace/.claude-plugin/marketplace.json`, so EVERY reference to
    the short form is also a reference to the long one. No suffix can separate
    them. Guessing would credit the plugin manifest's tests to the repo
    manifest, so the selector declines and discloses instead.
    """
    files = ["x/y/m.json", "y/m.json"]
    assert sel._distinctive_key("y/m.json", files) is None
    assert sel._distinctive_key("x/y/m.json", files) == "x/y/m.json"

    unmapped = sel.select_unmappable([".claude-plugin/marketplace.json"],
                                     PLUGIN_ROOT, plugin_prefix=PREFIX)
    assert ".claude-plugin/marketplace.json" in unmapped


def test_a_missing_tree_degrades_to_the_basename_and_never_raises():
    """A synthetic tree is not a git repo; the selector must still answer."""
    assert sel._distinctive_key("any/where/file.sh", None) == "file.sh"


# ── inertness: rule 7 must not perturb what the other rules already map ─────

def test_source_module_selections_are_byte_identical():
    """Rule 7 fires only on paths NO other rule claimed."""
    for path in (f"{PREFIX}/programs/flow_compliance_check.py",
                 f"{PREFIX}/programs/phase3_one_shot_runner.py",
                 f"{PREFIX}/benchmark/gates.py",
                 f"{PREFIX}/{TESTS_REL}/test_flow_compliance_check.py"):
        out = sel.select_tests([path], PLUGIN_ROOT, plugin_prefix=PREFIX,
                               mode=sel.MODE_IMPORT_EDGE)
        assert out == sorted(set(out)), "selection must be sorted and unique"
        assert out, "never empty"


def test_the_selection_never_becomes_the_whole_suite():
    """A selector that selects everything is not a selector."""
    everything = list((PLUGIN_ROOT / TESTS_REL).glob("test_*.py"))
    out = sel.select_tests([FLOW], PLUGIN_ROOT, plugin_prefix=PREFIX,
                           mode=sel.MODE_IMPORT_EDGE)
    assert len(out) < len(everything) // 2, (
        f"selected {len(out)} of {len(everything)} — a full-suite run wearing "
        f"a selector's name")


# ── disclosure ──────────────────────────────────────────────────────────────

def test_unmappable_paths_are_reported_not_swallowed():
    """The input to `--strict-unmapped`: a path with no test set is NAMED."""
    unmapped = sel.select_unmappable(
        ["docs/prose-nothing-reads.md", f"{PREFIX}/programs/flow_compliance_check.py"],
        PLUGIN_ROOT, plugin_prefix=PREFIX)
    assert "docs/prose-nothing-reads.md" in unmapped
    assert not any("flow_compliance_check" in u for u in unmapped), (
        "a path a rule DID map must never be reported unmapped")
