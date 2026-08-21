#!/usr/bin/env python3
"""Wave 93 / v1.6.17 — tests for check_version_sync_with_commit.sh.

The script (tools/ci/check_version_sync_with_commit.sh) gates a commit
when its message advertises a vX.Y.Z that disagrees with plugin.json /
marketplace.json. We exercise four canonical cases:

  (a) versions match → exit 0 (PASS)
  (b) commit msg claims newer version than the JSON files → exit 1 (FAIL)
  (c) commit msg has no version mention → exit 0 (skip — not applicable)
  (d) commit msg only contains a historical reference
      ("supersedes vX.Y.Z") → exit 0 (skip)

Because the script reads plugin.json + marketplace.json from a hard-coded
repo-relative path (PROJECT_ROOT), each test stages a synthetic repo in
tmp_path with the same layout the script expects.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _plugin_tree import repo_resource_or_skip

SCRIPT_REL = "tools/ci/check_version_sync_with_commit.sh"


def _stage_repo(tmp_path: Path, plugin_ver: str, market_ver: str) -> Path:
    """Build a synthetic repo with .git/, the script, plugin.json,
    marketplace.json, set to the requested versions.

    flow #486: tools/ci/ is a repo-root-only CI script that is NOT shipped
    in the flattened install cache. ``repo_resource_or_skip`` yields a
    NAMED pytest.skip there instead of a FileNotFoundError ERROR.
    """
    src_script = repo_resource_or_skip(SCRIPT_REL)
    root = tmp_path / "repo"
    # Layout
    (root / ".git").mkdir(parents=True)
    (root / "tools" / "ci").mkdir(parents=True)
    (root / "vibe-ic-marketplace" / ".claude-plugin").mkdir(parents=True)
    (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / ".claude-plugin").mkdir(parents=True)

    # Copy the script under test (so it resolves PROJECT_ROOT correctly
    # via $(...).../tools/ci → ../..)
    dst_script = root / SCRIPT_REL
    shutil.copy2(src_script, dst_script)
    dst_script.chmod(0o755)

    # plugin.json
    (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
     / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "vibe-ic", "version": plugin_ver}, indent=2)
    )
    # marketplace.json
    (root / "vibe-ic-marketplace" / ".claude-plugin"
     / "marketplace.json").write_text(
        json.dumps({"plugins": [{"name": "vibe-ic",
                                 "source": "./plugins/vibe-ic",
                                 "version": market_ver}]},
                   indent=2)
    )
    return root


def _run(repo: Path, commit_msg: str) -> subprocess.CompletedProcess:
    msg_path = repo / ".git" / "COMMIT_EDITMSG"
    msg_path.write_text(commit_msg)
    return subprocess.run(
        ["bash", str(repo / SCRIPT_REL)],
        cwd=str(repo),
        capture_output=True, text=True, timeout=30,
    )


# (a)
def test_version_match_passes(tmp_path):
    repo = _stage_repo(tmp_path, "1.6.17", "1.6.17")
    msg = ("feat(plugin): v1.6.17 Wave 93 — pre-commit version-sync hook "
           "+ VACUOUS_PASS verdict tier\n")
    r = _run(repo, msg)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "PASS" in r.stdout


# (b)
def test_version_mismatch_fails(tmp_path):
    repo = _stage_repo(tmp_path, "1.6.15", "1.6.15")
    msg = "feat(plugin): v1.6.17 Wave 93 — bump\n"
    r = _run(repo, msg)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "ERROR" in r.stdout
    assert "1.6.17" in r.stdout
    assert "1.6.15" in r.stdout


# (c)
def test_no_version_in_msg_skips(tmp_path):
    repo = _stage_repo(tmp_path, "1.6.15", "1.6.15")
    msg = "chore: tidy whitespace and rename a helper variable\n"
    r = _run(repo, msg)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "SKIP" in r.stdout


# (d) — historical references shouldn't trip the gate.
def test_historical_reference_only_skips(tmp_path):
    repo = _stage_repo(tmp_path, "1.6.15", "1.6.15")
    # Subject has no version. Body only mentions a past version with
    # historical markers ("supersedes", "(was ...)").
    msg = (
        "fix: rebuild backlog cleanup\n"
        "\n"
        "This change supersedes v1.6.10 from earlier (was v1.6.9 originally),\n"
        "but does not declare a new version itself.\n"
    )
    r = _run(repo, msg)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "SKIP" in r.stdout


# Bonus: marketplace.json drift alone trips the gate.
def test_marketplace_drift_only_fails(tmp_path):
    """plugin.json bumped but marketplace.json forgotten — must FAIL."""
    repo = _stage_repo(tmp_path, "1.6.17", "1.6.15")
    msg = "feat(plugin): v1.6.17 Wave 93 — bump\n"
    r = _run(repo, msg)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "marketplace.json" in r.stdout


# Bonus: subject vX.Y.Z takes precedence over body historical mention.
def test_subject_advertises_body_has_history(tmp_path):
    """Subject claims v1.6.17, body references v1.6.16 supersession.
    Plugin/marketplace are at 1.6.17, so this should PASS."""
    repo = _stage_repo(tmp_path, "1.6.17", "1.6.17")
    msg = (
        "feat: v1.6.17 Wave 93 — version-sync hook\n"
        "\n"
        "Supersedes v1.6.16 which only fixed Step 14 CLI signature.\n"
    )
    r = _run(repo, msg)
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "PASS" in r.stdout
