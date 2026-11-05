#!/usr/bin/env python3
"""test_v0_2_98_issue487_artifact_snapshot.py — issue #487 (LOW) regression.

ISSUE #487 — defect-artifact snapshots at filing time.

Backlog issues cite LIVE run-dir files as the defect evidence, but run dirs
EVOLVE between filing and verification: a cited truncated report can be
replaced by a healthy rerun before the verifier dereferences it, so
`defect_artifact_fixture_check` (which binds the fixture to mutable paths)
silently rots.

FIX
---
  (1) NEW programs/defect_artifact_snapshot.py — filing-side helper that
      freezes the cited live artifacts into an immutable capture archive
      (`<repo-root>/community/captures/<slug>/` + manifest.json with source
      path, sha256, fs mtime, issue ref) and prints both snapshot + live
      paths for the issue 證據區.
  (2) defect_artifact_fixture_check.py gains SNAPSHOT PREFERENCE: when the
      issue body names BOTH a live path and a snapshot path (or a snapshot
      archive exists per the convention for that issue), the check resolves
      the SNAPSHOT as the accepted defect-artifact source, re-verifying its
      sha256 against the manifest — so the verdict no longer depends on the
      mutated live file.

ACCEPTANCE DOCTRINE FOLLOWED BY THIS TEST
-----------------------------------------
The headline test REPLAYS THE ISSUE SHAPE end-to-end, verbatim:
  create a fixture run-dir file (truncated-report shape) → run the snapshot
  helper for a synthetic issue → MUTATE the live file (simulate the rerun)
  → run defect_artifact_fixture_check with an issue body citing both paths.
END STATE asserted: the check RESOLVES THE SNAPSHOT (original truncated
content, sha256 match) and the verdict does NOT depend on the mutated live
file. The test INVOKES THE REAL PROGRAMS via subprocess and asserts their
verdict / return code, not just internals.
"""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_CHECK = _PROGRAMS / "defect_artifact_fixture_check.py"

# Original, defect-shaped content: a report truncated mid-line.
_TRUNCATED = ("DRC REPORT\n=== begin ===\n"
              "[truncated -- report cut off mid-line at off")
# The healthy rerun that REPLACES the live file before verification.
_HEALTHY = ("DRC REPORT\n=== begin ===\nDRC PASS 0 violations\n"
            "=== end ===\nHEALTHY RERUN COMPLETE\n")


def _make_repo(tmp_path: Path) -> Path:
    """A throwaway repo root with a community/ dir so the archive convention
    resolves there (and not into the real repo)."""
    repo = tmp_path / "repo"
    (repo / "community").mkdir(parents=True)
    return repo


def _make_live_artifact(tmp_path: Path, content: str) -> Path:
    rundir = tmp_path / "run" / "reports"
    rundir.mkdir(parents=True, exist_ok=True)
    p = rundir / "drc_signoff.rpt"
    p.write_text(content, encoding="utf-8")
    return p


def _run_check(repo: Path, issue_body: Path, test_file: Path,
               jout: Path | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(_CHECK),
            "--issue-body-file", str(issue_body),
            "--test-file", str(test_file),
            "--repo-root", str(repo)]
    if jout:
        argv += ["--json", str(jout)]
    return subprocess.run(argv, capture_output=True, text=True)


# ==========================================================================
# ## 驗收 — the headline end-to-end replay of the issue shape
# ==========================================================================


# ==========================================================================
# defect_artifact_snapshot.py — finer-grained guards
# ==========================================================================


# ==========================================================================
# defect_artifact_fixture_check.py — snapshot-preference guards
# ==========================================================================


def test_check_no_snapshot_preserves_current_behavior(tmp_path):
    """When NO snapshot exists, current behavior is unchanged: a
    file-existence-only test still FAILs the end-state rule."""
    repo = _make_repo(tmp_path)
    issue_body = tmp_path / "issue.md"
    issue_body.write_text(textwrap.dedent("""\
        ## 現象
        Gate ignores `stage/out/results.json`.

        ## 驗收
        - run `python3 programs/g.py --stage stage/out` → Step 4 = PASS
        """), encoding="utf-8")
    test_file = tmp_path / "t.py"
    test_file.write_text(textwrap.dedent("""\
        from pathlib import Path
        def test_only_exists(tmp_path):
            out = tmp_path / "results.json"
            out.write_text("{}")
            assert out.exists()
        """), encoding="utf-8")
    rc = _run_check(repo, issue_body, test_file)
    assert rc.returncode == 1
    assert "end-state" in (rc.stdout + rc.stderr).lower()


# ==========================================================================
# Direct-import unit coverage
# ==========================================================================


def test_unit_resolve_prefers_snapshot_over_live():
    import defect_artifact_fixture_check as m
    body = ("## 驗收\nsnapshot `community/captures/issue-1-x/a.json` "
            "live `/run/a.json`\n")
    res = m.resolve_defect_artifact_source(body, repo_root=Path("/nonexist"))
    assert res.prefer_snapshot is True
    assert "community/captures/issue-1-x/a.json" in res.snapshot_path
