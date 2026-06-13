#!/usr/bin/env python3
"""Unit tests for programs/picker_fixture_thrash_guard.py.

Pins the real issue-#5 anti-thrash gate:
  - a staged change that FLIPS an existing project's expected ic_name in
    tests/test_phase1_fixtures_regression.py::_EXPECTED is REJECTED
    (rc=1) unless the commit message carries a matching
    `fixture-flip-acknowledged: <proj>:<old> -> <new>` line.
  - pure additions / deletions (not value flips) are allowed (rc=0).
  - no fixture change at all -> rc=0.
Logic-pinned. Driven through the module's pure helpers AND end-to-end
via subprocess against a real temp git repo.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import picker_fixture_thrash_guard as mod

PROG = Path(__file__).resolve().parent.parent / \
    "picker_fixture_thrash_guard.py"
FIXTURE_REL = mod._FIXTURE_TEST_REL


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(repo),
                          capture_output=True, text=True, check=True)


def _init_repo(tmp_path: Path, initial: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t.com")
    _git(repo, "config", "user.name", "t")
    fix = repo / FIXTURE_REL
    fix.parent.mkdir(parents=True, exist_ok=True)
    fix.write_text(initial)
    _git(repo, "add", str(FIXTURE_REL))
    _git(repo, "commit", "-qm", "init")
    return repo


def _stage(repo: Path, new_content: str) -> None:
    (repo / FIXTURE_REL).write_text(new_content)
    _git(repo, "add", str(FIXTURE_REL))


def _run(repo: Path, msg: str, tmp_path: Path) -> subprocess.CompletedProcess:
    msg_file = tmp_path / "COMMIT_MSG"
    msg_file.write_text(msg)
    return subprocess.run(
        [sys.executable, str(PROG), "--repo-root", str(repo),
         "--commit-msg-file", str(msg_file)],
        capture_output=True, text=True,
    )


_BEFORE = '_EXPECTED = {\n    "spm": "old_name",\n    "sha256": "sha256_core",\n}\n'
_FLIPPED = '_EXPECTED = {\n    "spm": "new_name",\n    "sha256": "sha256_core",\n}\n'
_ADDED = ('_EXPECTED = {\n    "spm": "old_name",\n    "sha256": "sha256_core",\n'
          '    "newproj": "brand_new",\n}\n')


# ---------------------------------------------------------------------------
# pure-helper logic (deterministic, no git)
# ---------------------------------------------------------------------------
def test_flips_detects_value_change():
    flips = mod._flips({"spm": "new"}, {"spm": "old"})
    assert flips == [("spm", "old", "new")]


def test_flips_ignores_pure_addition():
    # project only in `added` (a new fixture) is NOT a flip
    assert mod._flips({"newproj": "x"}, {}) == []


def test_acknowledged_parses_ack_line():
    acks = mod._acknowledged(
        "fix\n\nfixture-flip-acknowledged: spm:old_name -> new_name\n")
    assert acks["spm"] == ("old_name", "new_name")


# ---------------------------------------------------------------------------
# FAIL fixture: unacknowledged flip is rejected
# ---------------------------------------------------------------------------
def test_flip_without_ack_rejected(tmp_path):
    repo = _init_repo(tmp_path, _BEFORE)
    _stage(repo, _FLIPPED)
    r = _run(repo, "just a normal message\n", tmp_path)
    assert r.returncode == 1
    assert "FAIL" in r.stdout
    assert "spm" in r.stdout


def test_flip_with_wrong_ack_target_rejected(tmp_path):
    repo = _init_repo(tmp_path, _BEFORE)
    _stage(repo, _FLIPPED)
    # ack target does not match the diff's new value
    r = _run(repo,
             "fix\n\nfixture-flip-acknowledged: spm:old_name -> WRONG\n",
             tmp_path)
    assert r.returncode == 1


# ---------------------------------------------------------------------------
# PASS fixture: acknowledged flip is allowed
# ---------------------------------------------------------------------------
def test_flip_with_matching_ack_allowed(tmp_path):
    repo = _init_repo(tmp_path, _BEFORE)
    _stage(repo, _FLIPPED)
    r = _run(repo,
             "fix\n\nfixture-flip-acknowledged: spm:old_name -> new_name\n",
             tmp_path)
    assert r.returncode == 0
    assert "all acknowledged" in r.stdout


# ---------------------------------------------------------------------------
# edge: no flip / pure addition -> allowed regardless of message
# ---------------------------------------------------------------------------
def test_no_staged_fixture_change_passes(tmp_path):
    repo = _init_repo(tmp_path, _BEFORE)
    # nothing staged for the fixture file
    r = _run(repo, "unrelated commit\n", tmp_path)
    assert r.returncode == 0
    assert "no fixture" in r.stdout.lower()


def test_pure_addition_passes_without_ack(tmp_path):
    repo = _init_repo(tmp_path, _BEFORE)
    _stage(repo, _ADDED)
    r = _run(repo, "add a new fixture\n", tmp_path)
    assert r.returncode == 0
