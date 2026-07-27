#!/usr/bin/env python3
"""Behavioural tests for dead_program_reference_check.

The defect this gate exists for: a deletion PR removes a program and leaves
prose elsewhere in the bundle naming it, in backticks, as a live owner of a
contract. Nothing imports it, so every reachability check stays green.

The last test is the one that binds this repo: it runs the gate over the
REAL tree. Reverting any of the three prose repairs that shipped with it
turns that test red.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "dead_program_reference_check.py"
REPO_ROOT = Path(__file__).resolve().parents[5]


def _run(root, *extra):
    return subprocess.run([sys.executable, str(PROG), str(root), *extra],
                          capture_output=True, text=True)


def _bundle(root: Path) -> Path:
    """Minimal shipped-bundle skeleton under a scratch repo root."""
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    for sub in ("programs", "programs/tests", "skills"):
        (plugin / sub).mkdir(parents=True, exist_ok=True)
    return plugin


# --------------------------------------------------------------- FINDS IT
def test_backticked_missing_checker_is_a_finding(tmp_path):
    plugin = _bundle(tmp_path)
    (plugin / "programs" / "live_gate.py").write_text(
        '"""Contract owned by `deleted_thing_gen.py`."""\n')
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "deleted_thing_gen.py" in r.stdout
    assert "live_gate.py" in r.stdout


def test_finding_reported_in_json_with_line_number(tmp_path):
    plugin = _bundle(tmp_path)
    (plugin / "programs" / "live_gate.py").write_text(
        "# line one\n# see `gone_check.py` for the rest\n")
    r = _run(tmp_path, "--json")
    assert r.returncode == 1
    import json
    rep = json.loads(r.stdout)
    assert rep["passed"] is False
    assert rep["findings"][0]["name"] == "gone_check.py"
    assert rep["findings"][0]["line"] == 2
    assert rep["counts"]["unresolved"] == 1


def test_skill_markdown_is_in_scope(tmp_path):
    """The measured third instance was a routing table in a SKILL.md."""
    plugin = _bundle(tmp_path)
    (plugin / "skills" / "SKILL.md").write_text(
        "| Mixed-signal | `absent_merge_check.py` | cosim |\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "absent_merge_check.py" in r.stdout


# ------------------------------------------------ DIRECTION-1: NO FALSE FAIL
def test_reference_resolving_outside_programs_passes(tmp_path):
    """A program may live in tools/ or benchmark/; resolution is by basename."""
    plugin = _bundle(tmp_path)
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "elsewhere_gen.py").write_text("x = 1\n")
    (plugin / "programs" / "live_gate.py").write_text(
        '"""Produced by `elsewhere_gen.py`."""\n')
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_foreign_project_filename_is_not_judged(tmp_path):
    """RTLLM's auto_run.py / efabless's mpw_precheck.py are not ours to keep
    alive; they are outside the covered naming classes."""
    plugin = _bundle(tmp_path)
    (plugin / "programs" / "live_gate.py").write_text(
        '"""RTLLM ships `auto_run.py`; efabless ships `mpw_precheck.py`."""\n')
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_unbackticked_mention_is_not_judged(tmp_path):
    plugin = _bundle(tmp_path)
    (plugin / "programs" / "live_gate.py").write_text(
        '"""Historically emitted by deleted_thing_gen.py (now removed)."""\n')
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_tests_directory_is_excluded(tmp_path):
    """Test bodies build fixture programs with invented names at runtime."""
    plugin = _bundle(tmp_path)
    (plugin / "programs" / "tests" / "test_x.py").write_text(
        '"""Builds a tree whose only checker is `sample_check.py`."""\n')
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


# ------------------------------------------------------------- DISCLOSURE
def test_pass_discloses_its_denominator(tmp_path):
    plugin = _bundle(tmp_path)
    (plugin / "programs" / "live_gate.py").write_text('"""nothing here."""\n')
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "scanned 1 bundle file" in r.stdout
    assert "0 unresolved" in r.stdout


def test_empty_tree_pass_says_it_examined_nothing(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "scanned 0 bundle file" in r.stdout


def test_missing_root_is_rc2():
    r = _run("/nonexistent/root/for/this/test")
    assert r.returncode == 2


# --------------------------------------------------------- THE REAL TREE
@pytest.mark.skipif(
    not (REPO_ROOT / "vibe-ic-marketplace" / "plugins").is_dir(),
    reason="not running inside the repo checkout")
def test_shipped_bundle_has_no_dead_program_reference():
    """PR #462 deleted four programs and left l9_rtl_pin_consistency_check
    naming one of them. Two more instances were on main independently."""
    r = _run(REPO_ROOT)
    assert r.returncode == 0, r.stdout
