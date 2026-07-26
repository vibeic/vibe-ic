#!/usr/bin/env python3
"""Tests for checker_execution_wiring_audit (vibe-ic#381).

Bidirectional by construction: every case that must FIRE is paired with the
same tree made clean, because either assertion alone proves nothing.

Two of these pin bugs this program actually had while it was being written,
and both were the SAME shape — a matcher whose own assumption produced a
confident false accusation:

  * `".git" in path` also swallows `.github/`, emptying the CI haystack, so
    every CI-wired checker was reported as unwired.
  * matching only the QUOTED stem missed the flow definition, which writes
    gate names bare, so 12 wired gates were reported as wired nowhere.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "checker_execution_wiring_audit.py"
sys.path.insert(0, str(PROG.parent))
import checker_execution_wiring_audit as M  # noqa: E402


def _tree(root: Path, *, ci="", flow="", skill="", prog="", test="", index=""):
    """Build a minimal repo whose only checker is `sample_check.py`."""
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    for d in ("programs/tests", "flow", "skills", "agents", "commands", "tests"):
        (plugin / d).mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (plugin / "programs" / "sample_check.py").write_text("def main():\n    return 0\n")
    (root / ".github" / "workflows" / "ci.yml").write_text(ci or "name: CI\n")
    (plugin / "flow" / "flow.yaml").write_text(flow or "steps: []\n")
    (plugin / "skills" / "s.md").write_text(skill or "# skill\n")
    (plugin / "programs" / "other.py").write_text(prog or "x = 1\n")
    (plugin / "programs" / "tests" / "test_sample.py").write_text(test or "pass\n")
    (plugin / "programs" / "INDEX.md").write_text(index or "# index\n")
    return plugin


def _run(root: Path):
    return M.audit(root / "vibe-ic-marketplace" / "plugins" / "vibe-ic", root)


def test_test_only_checker_is_a_finding(tmp_path):
    """Only its own unit test runs it -> zero coverage of real inputs."""
    _tree(tmp_path, test="import sample_check\n")
    rep = _run(tmp_path)
    assert "sample_check.py" in rep["test_only"]
    assert rep["no_runner_at_all"] == []


def test_same_checker_wired_into_ci_is_clean(tmp_path):
    """The paired half: add a real runner and the finding must disappear."""
    _tree(tmp_path,
          test="import sample_check\n",
          ci="name: CI\njobs:\n  a:\n    steps:\n"
             "      - run: python3 programs/sample_check.py\n")
    rep = _run(tmp_path)
    assert rep["test_only"] == []
    assert rep["no_runner_at_all"] == []


def test_dot_github_is_not_eaten_by_the_dot_git_exclusion(tmp_path):
    """REGRESSION: `".git" in path` also matches `.github/`.

    With a substring exclusion the CI haystack is EMPTY, so a CI-wired
    checker is reported as unwired — a confident finding manufactured by
    the scanner's own filter. Assert the haystack is populated, not merely
    that the verdict is clean, so the reason stays pinned.
    """
    _tree(tmp_path, ci="run: python3 sample_check.py\n")
    hay = M._haystacks(tmp_path / "vibe-ic-marketplace/plugins/vibe-ic", tmp_path)
    assert hay["CI"], "the .github haystack must not be excluded as '.git'"


def test_bare_unquoted_flow_reference_counts(tmp_path):
    """REGRESSION: the flow definition writes gate names BARE.

    A matcher that only accepts the quoted stem or the `.py` filename
    reports wired gates as wired nowhere.
    """
    _tree(tmp_path, test="import sample_check\n",
          flow="steps:\n  - gate: sample_check\n")
    assert _run(tmp_path)["test_only"] == []


def test_catalogue_listing_is_not_a_runner(tmp_path):
    """INDEX.md NAMES checkers and runs none.

    Counting a catalogue would let a checker be 'wired' by being listed —
    the exact paper-only wiring this gate exists to find.
    """
    _tree(tmp_path, test="import sample_check\n",
          index="- sample_check.py — does a thing\n")
    assert "sample_check.py" in _run(tmp_path)["test_only"]


def test_substring_neighbour_does_not_count_as_a_reference(tmp_path):
    """`sample_check_extra` must not satisfy `sample_check`."""
    _tree(tmp_path, test="import sample_check\n",
          ci="run: python3 sample_check_extra.py\n")
    assert "sample_check.py" in _run(tmp_path)["test_only"]


def test_checker_referenced_by_nothing_is_reported_separately(tmp_path):
    _tree(tmp_path)
    rep = _run(tmp_path)
    assert rep["no_runner_at_all"] == ["sample_check.py"]
    assert rep["test_only"] == []


def test_baseline_refuses_to_grow(tmp_path):
    """A checker LOSING its only real runner is a regression, not a fact."""
    _tree(tmp_path)
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": []}) + "\n")
    rc = subprocess.run(
        [sys.executable, str(PROG), "--repo-root", str(tmp_path),
         "--baseline", str(bl), "--write-baseline"],
        capture_output=True, text=True)
    assert rc.returncode == 1, rc.stdout
    assert "refusing to GROW" in rc.stdout


def test_baseline_shrink_is_accepted_and_triage_survives(tmp_path):
    """The paired half of the growth refusal, plus: triage is not discarded.

    A register of bare names invites the worst repair — deleting the test so
    the entry disappears — so what was found when an entry was investigated
    has to survive a rewrite.
    """
    _tree(tmp_path, ci="run: python3 sample_check.py\n")
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps(
        {"known": ["sample_check.py", "gone_check.py"],
         "triage": {"sample_check.py": "why", "gone_check.py": "stale"}}) + "\n")
    rc = subprocess.run(
        [sys.executable, str(PROG), "--repo-root", str(tmp_path),
         "--baseline", str(bl), "--write-baseline"],
        capture_output=True, text=True)
    assert rc.returncode == 0, rc.stdout
    d = json.loads(bl.read_text())
    assert d["known"] == []
    assert d["triage"] == {}


def test_resolved_entry_forces_the_baseline_to_shrink(tmp_path):
    """A recorded entry that gained a runner must FAIL until it is removed,
    so the register can never quietly become permission."""
    _tree(tmp_path, ci="run: python3 sample_check.py\n")
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": ["sample_check.py"]}) + "\n")
    rc = subprocess.run(
        [sys.executable, str(PROG), "--repo-root", str(tmp_path),
         "--baseline", str(bl)], capture_output=True, text=True)
    assert rc.returncode == 1, rc.stdout
    assert "now HAVE a real runner" in rc.stdout


def test_real_repo_runs_and_is_deterministic():
    """End-to-end on this repo: two runs must agree."""
    root = PROG.parents[4]
    if not (root / "vibe-ic-marketplace").is_dir():
        pytest.skip("not in the repo layout")
    a = M.audit(PROG.parents[1], root)
    b = M.audit(PROG.parents[1], root)
    assert a == b
    assert a["checkers"] > 100
