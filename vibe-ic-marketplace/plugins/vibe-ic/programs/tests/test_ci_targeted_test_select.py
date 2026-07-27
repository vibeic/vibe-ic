"""Tests for ci_targeted_test_select.py — the patch-cadence CI test selector.

Feeds SYNTHETIC changed-file lists (no real git) and asserts:
  * a changed source module selects its owned test file(s),
  * a changed test file is included directly,
  * no code change (docs / version only) -> smoke set only,
  * the smoke set is ALWAYS present (the coverage floor),
  * longest-owning-stem prevents cross-module over-selection,
  * the CLI --base path works with git monkeypatched,
  * git-unavailable falls back to the smoke set (never empty).
"""
from __future__ import annotations

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
    """Docs / version-only diff -> exactly the smoke set, never empty."""
    out = sel.select_tests(
        [
            "README.md",
            "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json",
            "vibe-ic-marketplace/plugins/vibe-ic/skills/phase1/SKILL.md",
        ],
        PLUGIN_ROOT,
        plugin_prefix="vibe-ic-marketplace/plugins/vibe-ic",
    )
    assert out, "selection must never be empty"
    assert set(out) == sel._smoke_set(PLUGIN_ROOT)


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
