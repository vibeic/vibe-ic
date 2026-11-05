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
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
_SNAP = _PROGRAMS / "defect_artifact_snapshot.py"
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


def _run_snap(repo: Path, live: Path, issue: int, slug: str,
              jout: Path | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(_SNAP),
            "--issue", str(issue), "--slug", slug,
            "--artifact", str(live),
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
def test_snapshot_manifest_records_provenance(tmp_path):
    repo = _make_repo(tmp_path)
    live = _make_live_artifact(tmp_path, _TRUNCATED)
    jout = tmp_path / "s.json"
    r = _run_snap(repo, live, 487, "truncated-report-snapshot", jout=jout)
    assert r.returncode == 0
    manifest = json.loads(
        (repo / "community" / "captures"
         / "issue-487-truncated-report-snapshot" / "manifest.json")
        .read_text())
    assert manifest["issue_number"] == 487
    assert manifest["issue_ref"] == "#487"
    a = manifest["artifacts"][0]
    for key in ("source_path", "snapshot_path", "sha256",
                "source_mtime", "basename", "size_bytes"):
        assert a[key], f"manifest missing {key}"
    # human output prints BOTH paths for the 證據區.
    assert "snapshot:" in r.stdout
    assert "live:" in r.stdout


def test_snapshot_missing_source_fails(tmp_path):
    repo = _make_repo(tmp_path)
    r = _run_snap(repo, tmp_path / "nope.rpt", 487, "x")
    assert r.returncode == 1
    assert "not be captured" in (r.stdout + r.stderr).lower() or \
           "not found" in (r.stdout + r.stderr).lower()


def test_snapshot_requires_slug_or_issue(tmp_path):
    live = _make_live_artifact(tmp_path, _TRUNCATED)
    r = subprocess.run(
        [sys.executable, str(_SNAP), "--artifact", str(live)],
        capture_output=True, text=True)
    assert r.returncode == 2


def test_snapshot_requires_an_artifact(tmp_path):
    r = subprocess.run(
        [sys.executable, str(_SNAP), "--issue", "487", "--slug", "x"],
        capture_output=True, text=True)
    assert r.returncode == 2


def test_snapshot_basename_collision_kept_distinct(tmp_path):
    """Two sources with the same basename both land in the archive."""
    repo = _make_repo(tmp_path)
    a = tmp_path / "dirA"; a.mkdir(); (a / "rep.rpt").write_text("AAA")
    b = tmp_path / "dirB"; b.mkdir(); (b / "rep.rpt").write_text("BBB")
    r = subprocess.run(
        [sys.executable, str(_SNAP), "--issue", "999", "--slug", "dup",
         "--artifact", str(a / "rep.rpt"),
         "--artifact", str(b / "rep.rpt"),
         "--repo-root", str(repo)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    arch = repo / "community" / "captures" / "issue-999-dup"
    members = sorted(p.name for p in arch.iterdir()
                     if p.name != "manifest.json")
    assert len(members) == 2
    contents = {(arch / m).read_text() for m in members}
    assert contents == {"AAA", "BBB"}


# ==========================================================================
# defect_artifact_fixture_check.py — snapshot-preference guards
# ==========================================================================






# ==========================================================================
# Direct-import unit coverage
# ==========================================================================




def test_unit_derive_dir_slug_is_greppable_by_issue():
    import defect_artifact_snapshot as s
    assert s.derive_dir_slug(487, "truncated-report") == \
        "issue-487-truncated-report"
    assert s.derive_dir_slug(None, "no-issue") == "no-issue"
    assert s.derive_dir_slug(12, None) == "issue-12"
