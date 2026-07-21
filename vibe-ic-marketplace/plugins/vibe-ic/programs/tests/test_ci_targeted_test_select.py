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
