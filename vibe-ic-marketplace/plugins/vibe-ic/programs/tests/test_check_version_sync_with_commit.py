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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

SCRIPT_REL = "tools/ci/check_version_sync_with_commit.sh"


def _stage_repo(tmp_path: Path, plugin_ver: str, market_ver: str,
                root_ver: str | None = None) -> Path:
    """Build a synthetic repo with .git/, the script, plugin.json, and BOTH
    marketplace.json files, set to the requested versions.

    ``root_ver`` defaults to ``market_ver``: the root manifest is a
    marketplace.json too, so absent a reason it drifts with its sibling.
    Pass it explicitly to move ONLY the root one.

    flow #486: tools/ci/ is a repo-root-only CI script that is NOT shipped
    in the flattened install cache. ``repo_resource_or_skip`` yields a
    NAMED pytest.skip there instead of a FileNotFoundError ERROR.
    """
    src_script = repo_resource_or_skip(SCRIPT_REL)
    root = tmp_path / "repo"
    # Layout
    (root / ".git").mkdir(parents=True)
    (root / "tools" / "ci").mkdir(parents=True)
    (root / ".claude-plugin").mkdir(parents=True)
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
    # THE THIRD MANIFEST, at the REPO ROOT. `/plugin update` reads this one as
    # the version truth, and the script gained a check for it at 7e1aab3e1f --
    # a landing that did not update this fixture, so (a) and the subject/body
    # case began failing on a manifest the fixture never staged. The CHECKER is
    # right and the fixture was the stale side. Staging it is not the whole
    # fix: see `test_a_desynced_root_manifest_is_refused` below, without which
    # this block would merely make the red go away. The tools-side twin,
    # `tools/ci/test_check_version_sync_with_commit.py`, holds both halves --
    # these two tests of one checker must not disagree about what a valid
    # repository is.
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"plugins": [{"name": "vibe-ic",
                                 "source": "./vibe-ic-marketplace/plugins/vibe-ic",
                                 "version": root_ver if root_ver is not None
                                 else market_ver}]},
                   indent=2)
    )
    return root


def _run(repo: Path, commit_msg: str) -> subprocess.CompletedProcess:
    msg_path = repo / ".git" / "COMMIT_EDITMSG"
    msg_path.write_text(commit_msg)
    return _pr.run(
        ["bash", str(repo / SCRIPT_REL)],
        cwd=str(repo),
        capture_output=True, text=True)


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


# The guard that makes the third manifest STAGED above mean something. Without
# it, adding the file to `_stage_repo` would restore the green while leaving the
# root manifest -- the one `/plugin update` actually reads -- unchecked on this
# side of the repo. Mirrors `test_a_desynced_root_manifest_is_refused` in
# `tools/ci/test_check_version_sync_with_commit.py`.
def test_a_desynced_root_manifest_is_refused(tmp_path):
    """The two maintainer manifests agree; ONLY the root one is behind."""
    repo = _stage_repo(tmp_path, "1.6.17", "1.6.17", root_ver="1.6.15")
    r = _run(repo, "feat(plugin): v1.6.17 Wave 93 — bump\n")
    assert r.returncode == 1, (
        "a root-only desync was accepted; the manifest `/plugin update` reads "
        "is unchecked again\n" + r.stdout + r.stderr)
    assert "ROOT" in (r.stdout + r.stderr), (
        "it failed, but not for the root manifest — the message must say which "
        "of the three is wrong or the next reader edits the wrong file")


def test_an_absent_root_manifest_is_not_a_pass(tmp_path):
    """"I could not find the version" is not "the version is right"."""
    repo = _stage_repo(tmp_path, "1.6.17", "1.6.17")
    (repo / ".claude-plugin" / "marketplace.json").unlink()
    r = _run(repo, "feat(plugin): v1.6.17 Wave 93 — bump\n")
    assert r.returncode == 1, (
        "an absent root manifest passed; an unreadable version is not a "
        "matching one\n" + r.stdout + r.stderr)
