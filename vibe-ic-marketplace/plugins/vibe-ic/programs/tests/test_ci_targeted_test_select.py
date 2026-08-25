"""Tests for ci_targeted_test_select.py — the patch-cadence CI test selector.

Feeds SYNTHETIC changed-file lists (no real git) and asserts:
  * a changed source module selects its owned test file(s),
  * a changed test file is included directly,
  * no code change (docs / version only) -> smoke set only,
  * the smoke set is ALWAYS present (the coverage floor),
  * longest-owning-stem prevents cross-module over-selection,
  * the CLI --base path works with git monkeypatched,
  * git-unavailable falls back to the smoke set (never empty),
  * a changed SHARED TEST-HELPER module under programs/tests/ selects the tests
    that import it, without selecting the tree (rule 4, vibe-ic#534).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

import ci_targeted_test_select as sel

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent   # …/vibe-ic
TESTS_REL = "programs/tests"


def _smoke_present(paths):
    smoke = sel._smoke_set(PLUGIN_ROOT)
    assert smoke, "curated smoke set resolved to zero existing files"
    for s in smoke:
        assert s in paths, f"smoke floor missing: {s}"


def test_smoke_set_resolves_to_real_files():
    """Every curated smoke basename that we ship must exist on disk."""
    smoke = sel._smoke_set(PLUGIN_ROOT)
    # At least the governance core must resolve.
    assert f"{TESTS_REL}/test_source_chip_agnostic_check.py" in smoke
    assert f"{TESTS_REL}/test_version_bump_monotonic_check.py" in smoke
    for s in smoke:
        assert (PLUGIN_ROOT / s).is_file()


def test_changed_source_module_selects_owned_test():
    """Changing programs/flow_compliance_check.py selects its owned tests."""
    out = sel.select_tests(
        ["vibe-ic-marketplace/plugins/vibe-ic/programs/flow_compliance_check.py"],
        PLUGIN_ROOT,
        plugin_prefix="vibe-ic-marketplace/plugins/vibe-ic",
    )
    assert f"{TESTS_REL}/test_flow_compliance_check.py" in out
    # Filename-owned sibling (…_gate) is captured too.
    assert f"{TESTS_REL}/test_flow_compliance_check_gate.py" in out
    _smoke_present(out)


def test_plugin_relative_input_also_works():
    """A plugin-relative changed path (no repo prefix) resolves identically."""
    out = sel.select_tests(
        ["programs/flow_compliance_check.py"], PLUGIN_ROOT, plugin_prefix="",
    )
    assert f"{TESTS_REL}/test_flow_compliance_check.py" in out


def test_changed_test_file_included_directly():
    """A directly-changed test file is selected even with no source change."""
    tf = f"{TESTS_REL}/test_aging_derate_sta_check.py"
    assert (PLUGIN_ROOT / tf).is_file()
    out = sel.select_tests([tf], PLUGIN_ROOT, plugin_prefix="")
    assert tf in out
    _smoke_present(out)


def test_no_code_change_is_smoke_only():
    """A diff of PROSE only -> exactly the smoke set, never empty.

    vibe-ic#1058 narrowed this deliberately. It used to also assert that
    `.claude-plugin/plugin.json` contributes nothing, which was the DEFECT being
    asserted as the contract: the manifest is not prose, and the tests that read
    it say so in their own source —

        test_issue636_prepush_gates_by_destination:58
            _PJSON = _REPO / "…/.claude-plugin/plugin.json"
        test_v1_1_7_gatekeeper_assign_version:69
            (plugin_root / ".claude-plugin" / "plugin.json").write_text(…)

    Those are dependencies, not mentions, and rule 7 now selects them; the
    sibling test below pins that. What survives here is the part that was always
    right and must not regress: a genuinely prose diff stays at the floor.
    `README.md` is the honest case — 41 files in this repo share that basename,
    so no suffix identifies which one changed and the selector declines to guess.
    """
    out = sel.select_tests(
        ["README.md", "CONTRIBUTING.md", "docs/some-note.md"],
        PLUGIN_ROOT,
        plugin_prefix="vibe-ic-marketplace/plugins/vibe-ic",
    )
    assert out, "selection must never be empty"
    assert set(out) == sel._smoke_set(PLUGIN_ROOT)


def test_the_plugin_manifest_reaches_the_tests_that_read_it():
    """The half split out of the test above (vibe-ic#1058).

    Measured before the fix: 35 test files name the manifest and a change to it
    selected 0 of them beyond the smoke floor.
    """
    floor = sel._smoke_set(PLUGIN_ROOT)
    out = set(sel.select_tests(
        ["vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json"],
        PLUGIN_ROOT, plugin_prefix="vibe-ic-marketplace/plugins/vibe-ic"))
    beyond = out - floor
    assert beyond, "the manifest again selects nothing that reads it"
    for t in ("test_v1_1_7_gatekeeper_assign_version.py",
              "test_issue636_prepush_gates_by_destination.py"):
        assert f"{TESTS_REL}/{t}" in beyond, t


def test_longest_owning_stem_no_cross_module_bleed():
    """A test whose name extends a longer module stem is owned by the longer one.

    test_analog_corner_sweep_check.py must be owned by analog_corner_sweep_check
    (a real module), NOT pulled in by a hypothetical shorter stem.
    """
    stems = sel._source_stems(PLUGIN_ROOT)
    assert "analog_corner_sweep_check" in stems
    owner = sel._owning_stem("analog_corner_sweep_check", stems)
    assert owner == "analog_corner_sweep_check"
    # And the index maps that test only under the longest owner.
    index = sel._build_test_index(PLUGIN_ROOT, stems)
    tf = f"{TESTS_REL}/test_analog_corner_sweep_check.py"
    assert tf in index.get("analog_corner_sweep_check", set())


def test_benchmark_module_recognised_as_source():
    """A top-level benchmark/*.py counts as a source module for selection."""
    # cvdp_gate is a real benchmark module; if it owns a test, it is selected.
    stems = sel._source_stems(PLUGIN_ROOT)
    assert "cvdp_gate" in stems
    out = sel.select_tests(
        ["vibe-ic-marketplace/plugins/vibe-ic/benchmark/cvdp_gate.py"],
        PLUGIN_ROOT,
        plugin_prefix="vibe-ic-marketplace/plugins/vibe-ic",
    )
    # Whether or not cvdp_gate owns a test, smoke must still be present and the
    # result non-empty.
    _smoke_present(out)


def test_all_selected_paths_exist_and_are_tests():
    out = sel.select_tests(
        ["programs/flow_compliance_check.py", f"{TESTS_REL}/test_rtl_hygiene_lint.py"],
        PLUGIN_ROOT, plugin_prefix="",
    )
    for p in out:
        assert p.startswith(TESTS_REL + "/") and Path(p).name.startswith("test_")
        assert (PLUGIN_ROOT / p).is_file()
    assert out == sorted(out), "output must be sorted"


# ---- CLI path (git monkeypatched) -----------------------------------------

def test_cli_main_with_monkeypatched_git(monkeypatch, capsys):
    """--base drives git; monkeypatch returns a synthetic diff."""
    monkeypatch.setattr(sel, "_repo_root", lambda pr: PLUGIN_ROOT.parent.parent.parent)
    monkeypatch.setattr(
        sel, "_git_changed_files",
        lambda base, repo_root: [
            "vibe-ic-marketplace/plugins/vibe-ic/programs/rtl_hygiene_lint.py",
        ],
    )
    rc = sel.main(["--base", "deadbeef"])
    assert rc == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert f"{TESTS_REL}/test_rtl_hygiene_lint.py" in lines
    # smoke floor present on stdout too
    for s in sel._smoke_set(PLUGIN_ROOT):
        assert s in lines


def test_cli_git_unavailable_falls_back_to_smoke(monkeypatch, capsys):
    monkeypatch.setattr(sel, "_repo_root", lambda pr: None)
    rc = sel.main(["--base", "whatever"])
    assert rc == 0
    lines = [l for l in capsys.readouterr().out.splitlines() if l.strip()]
    assert set(lines) == sel._smoke_set(PLUGIN_ROOT)
    assert lines, "must never emit an empty subset"


def test_git_changed_files_bad_repo_returns_none(tmp_path):
    """A non-repo dir yields None (fallback signal), not a crash."""
    assert sel._git_changed_files("HEAD~1", tmp_path) is None


def test_cli_help_exits_zero():
    r = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "programs" / "ci_targeted_test_select.py"),
         "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "--base" in r.stdout


# ---- opt-in --mode (vibe-ic#452) -------------------------------------------
#
# The reference modes exist so the owner can evaluate the measured cost/coverage
# frontier without re-deriving it. They are OPT-IN: CI passes no --mode, so the
# default path must stay byte-identical to what shipped before the flag.

def _ref_index():
    return sel._build_reference_index(PLUGIN_ROOT, sel._source_stems(PLUGIN_ROOT))


def test_default_mode_never_builds_the_reference_index(monkeypatch):
    """MUTATION CONTROL, as a test.

    The whole safety argument for landing an unused mode is that the default
    path does not execute any of it. Poison the reference-index builder: if the
    default ever starts consulting it, this raises instead of silently paying
    the cost (and the coverage change) in the lane CI actually runs.
    """
    def _poisoned(*a, **k):
        raise AssertionError(
            "default (ownership) mode consulted the reference index")

    monkeypatch.setattr(sel, "_build_reference_index", _poisoned)
    out = sel.select_tests(["programs/flow_compliance_check.py"],
                           PLUGIN_ROOT, plugin_prefix="")
    assert f"{TESTS_REL}/test_flow_compliance_check.py" in out
    _smoke_present(out)

    # ...and the poison is real: the opt-in mode DOES consult it.
    with pytest.raises(AssertionError, match="consulted the reference index"):
        sel.select_tests(["programs/flow_compliance_check.py"], PLUGIN_ROOT,
                         plugin_prefix="", mode=sel.MODE_REFERENCE)


def test_default_mode_equals_explicit_ownership_mode():
    changed = ["programs/flow_compliance_check.py",
               "programs/source_chip_agnostic_check.py",
               f"{TESTS_REL}/test_rtl_hygiene_lint.py"]
    assert (sel.select_tests(changed, PLUGIN_ROOT, plugin_prefix="")
            == sel.select_tests(changed, PLUGIN_ROOT, plugin_prefix="",
                                mode=sel.MODE_OWNERSHIP))


def test_reference_mode_reaches_tests_the_ownership_rule_cannot():
    """The gap #452 is about: 54.5% of test files have no owning stem at all."""
    changed = ["programs/source_chip_agnostic_check.py"]
    own = set(sel.select_tests(changed, PLUGIN_ROOT, plugin_prefix=""))
    ref = set(sel.select_tests(changed, PLUGIN_ROOT, plugin_prefix="",
                               mode=sel.MODE_REFERENCE))
    assert own < ref, "reference mode must be a strict superset of ownership"

    stems = sel._source_stems(PLUGIN_ROOT)
    owner = sel._owning_stem
    extra = ref - own
    orphans = [t for t in extra
               if owner(Path(t).name[len("test_"):-len(".py")], stems) is None]
    assert orphans, (
        "reference mode added nothing that the filename rule could not already "
        "reach — the measured 45.5%-vs-98.9% gap would not exist")


def test_reference_capped_bounds_the_giant_stems_but_keeps_the_small_ones():
    """The cost knob: a stem named by more test files than the cap contributes
    nothing extra; a stem under the cap contributes its full reference set."""
    idx = _ref_index()
    cap = sel.DEFAULT_REF_MAX_TESTS
    big = [s for s, v in idx.items() if len(v) > cap]
    small = [s for s, v in idx.items() if 1 < len(v) <= cap]
    assert big and small, "tree no longer exercises both sides of the cap"

    for stem in (max(big, key=lambda s: len(idx[s])),):
        changed = [f"programs/{stem}.py"]
        own = sel.select_tests(changed, PLUGIN_ROOT, plugin_prefix="")
        capped = sel.select_tests(changed, PLUGIN_ROOT, plugin_prefix="",
                                  mode=sel.MODE_REFERENCE_CAPPED)
        assert capped == own, f"{stem}: over-cap stem must add nothing"

    for stem in (max(small, key=lambda s: len(idx[s])),):
        changed = [f"programs/{stem}.py"]
        capped = set(sel.select_tests(changed, PLUGIN_ROOT, plugin_prefix="",
                                      mode=sel.MODE_REFERENCE_CAPPED))
        full = set(sel.select_tests(changed, PLUGIN_ROOT, plugin_prefix="",
                                    mode=sel.MODE_REFERENCE))
        assert capped == full, f"{stem}: under-cap stem must add its full set"


def test_reference_matches_whole_identifiers_not_substrings(tmp_path):
    """A mention of `alpha_beta` must NOT count as a reference to `alpha`.

    Substring matching would silently inflate every short stem's reference set —
    the exact thing the cap exists to control — so this is asserted on a
    synthetic tree where the answer is known, not on the shipped tree (where
    the index is built by the rule under test and any check would be circular).
    """
    (tmp_path / "programs" / "tests").mkdir(parents=True)
    (tmp_path / "programs" / "alpha.py").write_text("x = 1\n")
    (tmp_path / "programs" / "alpha_beta.py").write_text("y = 2\n")
    (tmp_path / "programs" / "tests" / "test_only_long.py").write_text(
        "import alpha_beta\n")
    (tmp_path / "programs" / "tests" / "test_short.py").write_text(
        "from alpha import x\n")

    stems = sel._source_stems(tmp_path)
    assert stems == {"alpha", "alpha_beta"}
    idx = sel._build_reference_index(tmp_path, stems)

    assert idx.get("alpha_beta") == {f"{TESTS_REL}/test_only_long.py"}
    assert idx.get("alpha") == {f"{TESTS_REL}/test_short.py"}, (
        "`alpha` was matched inside `alpha_beta` — the rule is substring, "
        "not whole-identifier")


def test_every_mode_keeps_the_smoke_floor():
    for mode in sel.MODES:
        out = sel.select_tests([], PLUGIN_ROOT, plugin_prefix="", mode=mode)
        _smoke_present(out)
        assert out, f"{mode}: must never emit an empty subset"


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError, match="unknown mode"):
        sel.select_tests([], PLUGIN_ROOT, plugin_prefix="", mode="whatever")


def test_cli_mode_flag_plumbs_through(monkeypatch, capsys):
    monkeypatch.setattr(sel, "_repo_root", lambda pr: PLUGIN_ROOT.parent.parent.parent)
    monkeypatch.setattr(
        sel, "_git_changed_files",
        lambda base, repo_root: [
            "vibe-ic-marketplace/plugins/vibe-ic/programs/source_chip_agnostic_check.py",
        ],
    )
    assert sel.main(["--base", "deadbeef"]) == 0
    default = {l for l in capsys.readouterr().out.splitlines() if l.strip()}
    assert sel.main(["--base", "deadbeef", "--mode", "reference"]) == 0
    ref = {l for l in capsys.readouterr().out.splitlines() if l.strip()}
    assert default < ref, "--mode reference must widen the CLI selection"


# ---- rule 4: shared TEST-HELPER modules (vibe-ic#534) ----------------------
#
# The gap these pin: `programs/tests/matrix/waivers.py` is the single
# central waiver registry that #527 (v1.7.86) and #530 (v1.7.88) consolidated
# — one accepted gap, one text — and BEFORE rule 4 a change to it selected
# nothing but the smoke floor, so the eight dimension modules whose verdicts it
# can flip never ran. Both #527's and #530's authors were told BY HAND to run
# the matrix files instead.
#
# These tests deliberately do NOT hard-code the consumer filenames. A list here
# would be a second registry beside the first, free to drift from it — the exact
# defect #527/#530 removed — and it would already have been wrong: the report
# that opened #534 said ten consumers, the tree has eleven. The expected set is
# re-derived from the tests' own import lines by a regex that shares no code
# with the selector's `ast` implementation, so the two can disagree.

_MATRIX_PKG = "matrix"
_REGISTRY_REL = f"{TESTS_REL}/{_MATRIX_PKG}/waivers.py"
_IMPORTS_MATRIX = re.compile(rf"^[ \t]*(?:from|import)[ \t]+{_MATRIX_PKG}\b", re.M)


#: A test file may reach the registry through a HELPER in `programs/tests/`
#: rather than importing the package itself — `matrix_d7_artifact_graph.py`
#: carries `from matrix import flowref` at its own line 207, so a test that
#: imports only that helper is a genuine consumer and the selector is right to
#: pick it. Matching direct imports alone made this oracle NARROWER than the
#: truth, and the first test file to consume a helper without also importing the
#: package itself read as over-selection.
#:
#: ONE HOP, NOT A GRAPH WALK. The point of this oracle is that it shares no code
#: with the selector's `ast` implementation, so the two can disagree; following
#: the chain to its end would re-implement the selector and the disagreement
#: would stop being possible. One hop is what the tree actually contains, and a
#: second hop appearing should FAIL here and be widened deliberately rather than
#: be absorbed silently.
_HELPER_GLOB = "*.py"


def _matrix_helper_modules() -> set[str]:
    """Helper module names under `tests/` whose own source imports the package."""
    out = set()
    for hf in (PLUGIN_ROOT / TESTS_REL).glob(_HELPER_GLOB):
        if hf.name.startswith("test_"):
            continue
        if _IMPORTS_MATRIX.search(hf.read_text(encoding="utf-8", errors="replace")):
            out.add(hf.stem)
    return out


def _matrix_consumers_by_independent_scan() -> set[str]:
    """Every test file whose SOURCE reaches the matrix package.

    Independent oracle: a line-anchored regex over the import statements, not
    the selector's ast walk. Line-anchored so a mention inside a string literal
    (`"from _hostpaths import require_repo\\n"`, a real pattern in this tree)
    is not counted as an import.

    Reaches = imports the package, OR imports a `tests/` helper that does.
    """
    helpers = _matrix_helper_modules()
    via_helper = (re.compile(r"^[ \t]*(?:from|import)[ \t]+(?:" +
                             "|".join(sorted(map(re.escape, helpers))) + r")\b", re.M)
                  if helpers else None)
    out = set()
    for tf in (PLUGIN_ROOT / TESTS_REL).glob("test_*.py"):
        src = tf.read_text(encoding="utf-8", errors="replace")
        if _IMPORTS_MATRIX.search(src) or (via_helper and via_helper.search(src)):
            out.add(f"{TESTS_REL}/{tf.name}")
    return out


def test_changed_waiver_registry_selects_every_test_that_reads_it():
    """A change to the central registry must select ALL of its consumers.

    Fails if the helper mapping is removed: without rule 4 the selection is
    exactly the smoke floor and every consumer is missing.
    """
    assert (PLUGIN_ROOT / _REGISTRY_REL).is_file(), (
        f"{_REGISTRY_REL} moved — re-point this guard, do not delete it")
    expected = _matrix_consumers_by_independent_scan()
    assert len(expected) >= 8, (
        f"independent scan found only {len(expected)} consumers of "
        f"{_MATRIX_PKG}; the matrix has eight dimensions plus its meta-tests, "
        f"so the scan itself is broken — fix the oracle before trusting a PASS")

    out = set(sel.select_tests([_REGISTRY_REL], PLUGIN_ROOT, plugin_prefix=""))
    missing = sorted(expected - out)
    assert not missing, (
        f"changing the central waiver registry {_REGISTRY_REL} selected none of "
        f"{missing} — those tests resolve their verdicts against it, so a green "
        f"targeted CI on such a change means nothing (vibe-ic#534)")
    _smoke_present(out)


def test_waiver_registry_change_does_not_select_the_whole_tree():
    """Both directions: catching the consumers must not mean catching everyone.

    A selector that returns everything is as useless as one that returns
    nothing — it just moves the cost instead of the blindness.
    """
    all_tests = {f"{TESTS_REL}/{p.name}"
                 for p in (PLUGIN_ROOT / TESTS_REL).glob("test_*.py")}
    out = set(sel.select_tests([_REGISTRY_REL], PLUGIN_ROOT, plugin_prefix=""))
    allowed = _matrix_consumers_by_independent_scan() | sel._smoke_set(PLUGIN_ROOT)
    assert out <= allowed, (
        f"over-selection: {sorted(out - allowed)} neither import the registry "
        f"nor belong to the smoke floor")
    assert len(out) < len(all_tests) // 4, (
        f"selected {len(out)} of {len(all_tests)} test files for a one-module "
        f"change — that is a full-suite run wearing a selector's name")


def test_helper_rule_does_not_widen_unrelated_selections():
    """Rule 4 must be inert for diffs that touch no tests-dir helper.

    vibe-ic#1058 changed ONE fixture here and nothing about the intent. The
    "docs only" row used to pass `{TESTS_REL}/{_MATRIX_PKG}/README.md`, which is
    not docs: `test_matrix_census_freshness.py:66` does
    `text = README.read_text(...)` and asserts on its contents. Four tests read
    it. Rule 7 selects them, correctly — so that fixture no longer isolates
    rule 4, which is all this test was ever measuring.

    Swapped for a path that is genuinely inert (nothing reads it), so the test
    still fails if rule 4 leaks. The now-covered artefact is asserted positively
    in `test_a_read_artefact_selects_the_tests_that_read_it` instead — the
    coverage is kept, not dropped.

    vibe-ic#1387 broke the LAST assertion the same way, one rule further on, and
    the remedy is the same shape: subtract the newly-legitimate contributor by
    NAME instead of relaxing the bound. Rule 8 routes a changed `programs/*.py`
    to every tests-tree file that globs `*.py`, and three of those are matrix
    consumers (`test_matrix_d1_wiring`, `test_matrix_d7_outputs_list_complete`,
    `test_selector_second_hop_helpers`). They walk every program in the tree, so
    a change to any one of them really can break them — that selection is rule
    8 working, not rule 4 leaking, and it is the whole point of #1387.

    So the bound is taken against `select_tests - _dir_consumers`, which still
    fails the moment rule 4 pulls in a matrix consumer of its own. Asserting
    `not (src & matrix_consumers)` outright would now be asserting that #1387
    did not land.
    """
    for changed, label in (
        ([], "empty diff"),
        (["README.md", "docs/unread-prose.md"], "docs only"),
        ([f"{TESTS_REL}/{_MATRIX_PKG}/waivers.txt"], "non-.py in the helper dir"),
    ):
        out = set(sel.select_tests(changed, PLUGIN_ROOT, plugin_prefix=""))
        assert out == sel._smoke_set(PLUGIN_ROOT), (
            f"{label}: rule 4 leaked {sorted(out - sel._smoke_set(PLUGIN_ROOT))}")

    changed = ["programs/flow_compliance_check.py"]
    src = set(sel.select_tests(changed, PLUGIN_ROOT, plugin_prefix=""))
    assert f"{TESTS_REL}/test_flow_compliance_check.py" in src

    # Rule 8's own contribution, recomputed from the selector rather than listed
    # here: a hand-written exemption list would rot the first time a test gains
    # or drops a glob, and would then silence rule 4 for whatever moved into it.
    by_glob = sel._dir_consumers(PLUGIN_ROOT, changed,
                                 sel._source_stems(PLUGIN_ROOT))
    leaked = (src - by_glob) & _matrix_consumers_by_independent_scan()
    assert not leaked, (
        f"a plain source-module change pulled in matrix consumers that rule 8's "
        f"glob edges do not explain: {sorted(leaked)}")


# ---- the mapping is DERIVED, proven on a synthetic tree --------------------

def _fake_plugin(tmp_path: Path) -> Path:
    root = tmp_path / "vibe-ic"
    (root / "programs" / "tests").mkdir(parents=True)
    return root


def test_helper_mapping_is_derived_from_imports_not_a_filename_list(tmp_path):
    """Names that exist nowhere in this repo still map correctly.

    This is what separates a derived rule from a hand-list: a hand-list can only
    know the filenames someone remembered to add to it, and the whole point of
    #534 is that such a list drifts from the registry it is supposed to track.
    """
    root = _fake_plugin(tmp_path)
    t = root / "programs" / "tests"
    (t / "brandnewpkg").mkdir()
    (t / "brandnewpkg" / "__init__.py").write_text("", encoding="utf-8")
    (t / "brandnewpkg" / "reg.py").write_text("VALUES = {}\n", encoding="utf-8")
    (t / "brandnewpkg" / "other.py").write_text("X = 1\n", encoding="utf-8")
    (t / "test_reads_reg.py").write_text(
        "from brandnewpkg import reg\n", encoding="utf-8")
    (t / "test_reads_other.py").write_text(
        "from brandnewpkg import other as O\n", encoding="utf-8")
    (t / "test_unrelated.py").write_text("import os\n", encoding="utf-8")

    out = set(sel.select_tests(["programs/tests/brandnewpkg/reg.py"],
                               root, plugin_prefix=""))
    assert f"{TESTS_REL}/test_reads_reg.py" in out, "direct import edge missing"
    assert f"{TESTS_REL}/test_reads_other.py" in out, (
        "package-ancestor edge missing: a test reading a SIBLING module of the "
        "changed registry resolves through the same package and must be run — "
        "this is the margin a hand-list of today's filenames cannot have")
    assert f"{TESTS_REL}/test_unrelated.py" not in out, "over-selection"


def test_helper_rule_ignores_the_name_in_string_literals(tmp_path):
    """Precision: a MENTION is not an import.

    Real pattern in this tree — test_real_artefact_test_backing_check.py embeds
    `"from _hostpaths import require_repo\\n"` as fixture text. A grep-based
    rule selects it; the ast rule correctly does not.
    """
    root = _fake_plugin(tmp_path)
    t = root / "programs" / "tests"
    (t / "helper_mod.py").write_text("Y = 2\n", encoding="utf-8")
    (t / "test_mentions.py").write_text(
        'SRC = "from helper_mod import thing\\n"\n', encoding="utf-8")
    (t / "test_imports.py").write_text("import helper_mod\n", encoding="utf-8")

    out = set(sel.select_tests(["programs/tests/helper_mod.py"],
                               root, plugin_prefix=""))
    assert f"{TESTS_REL}/test_imports.py" in out
    assert f"{TESTS_REL}/test_mentions.py" not in out, (
        "a string literal naming the helper was read as an import")


def test_helper_rule_follows_helper_to_helper_edges(tmp_path):
    """A change two hops away still reaches the test.

    `matrix_d4_probe` imports `matrix.flowref` and the d4 test imports the
    probe; without transitivity a flowref change would miss that test whenever
    it stops importing flowref itself.
    """
    root = _fake_plugin(tmp_path)
    t = root / "programs" / "tests"
    (t / "pkg").mkdir()
    (t / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (t / "pkg" / "base.py").write_text("B = 1\n", encoding="utf-8")
    (t / "probe.py").write_text("from pkg import base\n", encoding="utf-8")
    (t / "test_via_probe.py").write_text("import probe\n", encoding="utf-8")
    (t / "test_nothing.py").write_text("import sys\n", encoding="utf-8")

    out = set(sel.select_tests(["programs/tests/pkg/base.py"],
                               root, plugin_prefix=""))
    assert f"{TESTS_REL}/test_via_probe.py" in out, (
        "helper -> helper -> test edge not followed")
    assert f"{TESTS_REL}/test_nothing.py" not in out


def test_helper_rule_resolves_relative_intra_package_imports(tmp_path):
    """`from . import x` / `from .x import y` inside a package must resolve.

    The matrix package uses exactly this form (`from . import flowref`), so a
    resolver that skipped relative imports would silently lose every intra-
    package edge while still looking like it worked from the outside.
    """
    root = _fake_plugin(tmp_path)
    t = root / "programs" / "tests"
    (t / "p").mkdir()
    (t / "p" / "__init__.py").write_text("", encoding="utf-8")
    (t / "p" / "leaf.py").write_text("L = 1\n", encoding="utf-8")
    # Consumes leaf ONLY through relative imports.
    (t / "p" / "mid.py").write_text(
        "from . import leaf\nfrom .leaf import L\n", encoding="utf-8")
    (t / "test_uses_mid.py").write_text("from p import mid\n", encoding="utf-8")

    assert sel._imported_module_names("from . import leaf\n", "p") >= {"p", "p.leaf"}
    assert sel._imported_module_names("from .leaf import L\n", "p") >= {"p.leaf"}
    out = set(sel.select_tests(["programs/tests/p/leaf.py"], root, plugin_prefix=""))
    assert f"{TESTS_REL}/test_uses_mid.py" in out


def test_bare_alias_withheld_when_it_collides_with_a_source_module(tmp_path):
    """A tests-dir helper must not hijack a top-level source module's name.

    `import waivers_schema_check` is a rule-1 source module; if a helper's bare
    basename were emitted unconditionally, a same-named helper would start
    claiming that module's tests.
    """
    root = _fake_plugin(tmp_path)
    (root / "programs" / "collider.py").write_text("Z = 0\n", encoding="utf-8")
    t = root / "programs" / "tests"
    (t / "sub").mkdir()
    (t / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (t / "sub" / "collider.py").write_text("Z = 1\n", encoding="utf-8")

    names = sel._helper_module_names(root, sel._source_stems(root))
    assert names[f"{TESTS_REL}/sub/collider.py"] == {"sub.collider"}, (
        "bare alias emitted despite colliding with a top-level source stem")


def test_package_init_maps_to_the_package_not_to_a_module_named_init(tmp_path):
    """`pkg/__init__.py` is the module `pkg`, never `pkg.__init__`.

    Pinned on its own because the package-ancestor edge currently MASKS a wrong
    answer here — `pkg.__init__`'s ancestors include `pkg`, so the selection
    comes out identical (measured). The day someone tightens or removes that
    edge, this becomes load-bearing, and a mutation that survives only because
    another rule is covering for it is not a tested property.
    """
    root = _fake_plugin(tmp_path)
    t = root / "programs" / "tests"
    (t / "apkg").mkdir()
    (t / "apkg" / "__init__.py").write_text("", encoding="utf-8")
    names = sel._helper_module_names(root, sel._source_stems(root))
    assert names[f"{TESTS_REL}/apkg/__init__.py"] == {"apkg"}, (
        "a package's __init__.py must map to the package name")

    real = sel._helper_module_names(PLUGIN_ROOT, sel._source_stems(PLUGIN_ROOT))
    init_rel = f"{TESTS_REL}/{_MATRIX_PKG}/__init__.py"
    if (PLUGIN_ROOT / init_rel).is_file():
        assert _MATRIX_PKG in real[init_rel]


def test_helper_index_not_built_when_no_helper_changed(monkeypatch):
    """Cost guard: rule 4 must be lazy, exactly like the reference index.

    vibe-ic#1387 made "was `_helper_consumers` called at all?" the wrong
    question. Rule 8 (`_dir_consumers`) resolves its glob-matched HELPERS
    through rule 4 by design — that is the documented path from
    `programs/eda_report_audit.py` to `test_matrix_d7_outputs_list_complete.py`
    — so the function now has two legitimate callers and a bare call-count
    cannot tell rule 4 firing from rule 8 composing. Counting calls made this
    test red on clean main from the moment #1387 landed.

    The PROPERTY is unchanged and still worth guarding, so it is measured at the
    thing that actually distinguishes the two callers: the ARGUMENT. Rule 4
    passes the helpers that are IN THE DIFF; rule 8 passes helpers it found by
    globbing the tests tree. A diff carrying no helper can therefore produce
    calls, but none of them may name a path from that diff — and if rule 4 ever
    stops being lazy, its call does name one, and this reddens.
    """
    calls: list[tuple] = []
    real = sel._helper_consumers
    monkeypatch.setattr(
        sel, "_helper_consumers",
        lambda plugin_root, helpers, stems, *a, **k:
            calls.append(tuple(helpers)) or real(plugin_root, helpers, stems, *a, **k))

    no_helper = ["programs/flow_compliance_check.py"]
    sel.select_tests(no_helper, PLUGIN_ROOT, plugin_prefix="")
    from_diff = {h for c in calls for h in c} & set(no_helper)
    assert not from_diff, (
        f"rule 4 ran for a diff with no tests-dir helper: it was handed "
        f"{sorted(from_diff)}, which came from the diff itself")

    calls.clear()
    sel.select_tests([_REGISTRY_REL], PLUGIN_ROOT, plugin_prefix="")
    assert _REGISTRY_REL in {h for c in calls for h in c}, (
        f"rule 4 did NOT run for a changed tests-dir helper ({_REGISTRY_REL}); "
        f"calls seen: {calls}")


def test_unparseable_helper_or_test_does_not_silence_the_selector(tmp_path):
    """A broken file must not turn the selector quiet.

    `_imported_module_names` returns None for unparseable text and the caller
    treats that as UNKNOWN — select it — rather than as "imports nothing".
    """
    assert sel._imported_module_names("def (\n", None) is None
    root = _fake_plugin(tmp_path)
    t = root / "programs" / "tests"
    (t / "h.py").write_text("Q = 1\n", encoding="utf-8")
    (t / "test_broken.py").write_text("import h\ndef (\n", encoding="utf-8")
    out = set(sel.select_tests(["programs/tests/h.py"], root, plugin_prefix=""))
    assert f"{TESTS_REL}/test_broken.py" in out


# ── owner decision (vibe-ic#565): the default follows import edges ──────────
def test_the_default_mode_is_import_edge():
    """OWNER DECISION. A test named after the chip or the feature rather than
    after the module it pins was never selected by filename ownership — and a
    734-line edit silently reverted a landed fix for three releases because of
    it.

    MEASURED at the switch, on this repo's own landings:

        ownership     19 files      ~33 s
        import-edge  184 files     879 s / 6102 tests   (on the heaviest base)

    That cost is the decision, and it is the reason the number is written here
    rather than left to be rediscovered."""
    import importlib
    M = importlib.import_module("ci_targeted_test_select")
    ap = M.build_parser() if hasattr(M, "build_parser") else None
    src = __import__("pathlib").Path(M.__file__).read_text(encoding="utf-8")
    body = "\n".join(l for l in src.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "default=MODE_IMPORT_EDGE" in body
    assert "default=MODE_OWNERSHIP" not in body


def test_ownership_is_still_reachable_as_an_opt_in():
    """The narrowing did not disappear — it became opt-IN. A landing that
    genuinely needs the cheap set must still be able to ask for it, and say so."""
    import importlib
    M = importlib.import_module("ci_targeted_test_select")
    assert M.MODE_OWNERSHIP in M.MODES
    assert M.MODE_IMPORT_EDGE in M.MODES
