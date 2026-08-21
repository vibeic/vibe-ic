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
def test_acceptance_snapshot_survives_live_mutation(tmp_path):
    repo = _make_repo(tmp_path)

    # (1) fixture run-dir file (truncated-report shape).
    live = _make_live_artifact(tmp_path, _TRUNCATED)
    import hashlib
    orig_sha = "sha256:" + hashlib.sha256(_TRUNCATED.encode()).hexdigest()

    # (2) run the snapshot helper for a synthetic issue.
    snap_json = tmp_path / "snap.json"
    rs = _run_snap(repo, live, 487, "truncated-report-snapshot",
                   jout=snap_json)
    assert rs.returncode == 0, f"snapshot failed: {rs.stderr}"
    snap_data = json.loads(snap_json.read_text())
    assert snap_data["verdict"] == "PASS"
    rec = snap_data["artifacts"][0]
    # the manifest froze the ORIGINAL truncated content + fs mtime + issue ref
    assert rec["sha256"] == orig_sha
    assert snap_data["issue_ref"] == "#487"
    assert rec["source_mtime"]            # fs mtime captured
    snap_rel = rec["snapshot_rel"]
    snap_abs = repo / snap_rel
    assert snap_abs.is_file()
    assert snap_abs.read_text() == _TRUNCATED   # immutable copy

    # (3) MUTATE the live file (simulate the healthy rerun).
    live.write_text(_HEALTHY, encoding="utf-8")
    assert live.read_text() != _TRUNCATED

    # (4) issue body citing BOTH the live path and the snapshot path.
    issue_body = tmp_path / "issue.md"
    issue_body.write_text(textwrap.dedent(f"""\
        ## 現象
        The signoff gate cited a truncated report at `{live}` (live).
        Frozen snapshot: `{snap_rel}`.

        ## 根因
        Run dir evolved; the live file was replaced by a healthy rerun.

        ## 驗收
        - run the gate against the snapshot `{snap_rel}` → defect reproduces
        """), encoding="utf-8")

    # A compliant regression test that binds to the SNAPSHOT path and asserts
    # an END state via a real gate invocation.
    test_file = tmp_path / "test_snap.py"
    test_file.write_text(textwrap.dedent(f"""\
        import subprocess
        from pathlib import Path

        def test_defect_reproduces():
            snap = Path("{repo}") / "{snap_rel}"
            r = subprocess.run(
                ["python3", "programs/some_signoff_gate.py",
                 "--report", str(snap)],
                capture_output=True, text=True)
            assert r.returncode == 1
            assert "truncated" in (r.stdout + r.stderr).lower()
        """), encoding="utf-8")

    check_json = tmp_path / "check.json"
    rc = _run_check(repo, issue_body, test_file, jout=check_json)

    # END STATE: the check PASSes by resolving the SNAPSHOT.
    assert rc.returncode == 0, (
        f"check should PASS via snapshot; rc={rc.returncode}\n"
        f"stdout={rc.stdout}\nstderr={rc.stderr}")
    v = json.loads(check_json.read_text())
    sr = v["snapshot_resolution"]
    assert v["verdict"] == "PASS"
    assert sr["has_snapshot"] is True
    assert sr["has_live"] is True
    # the snapshot's sha256 was re-verified against the manifest -> the
    # resolution is to the FROZEN (original truncated) content.
    assert sr["sha256_verified"] is True
    assert str(live) in sr["live_paths"]

    # The verdict does NOT depend on the mutated (or even deleted) live file.
    live.unlink()
    rc2 = _run_check(repo, issue_body, test_file)
    assert rc2.returncode == 0, (
        "verdict must be independent of the live file once a snapshot "
        f"exists; rc={rc2.returncode}\n{rc2.stderr}")


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
def test_check_s2_archive_on_disk_without_snapshot_path_in_body(tmp_path):
    """S2: body cites only the live path, but a matching archive exists on
    disk for this issue → the check still prefers the snapshot."""
    repo = _make_repo(tmp_path)
    live = _make_live_artifact(tmp_path, _TRUNCATED)
    r = _run_snap(repo, live, 487, "truncated-report-snapshot")
    assert r.returncode == 0
    live.write_text(_HEALTHY)   # mutate

    snap_rel = ("community/captures/issue-487-truncated-report-snapshot/"
                "drc_signoff.rpt")
    issue_body = tmp_path / "issue.md"
    issue_body.write_text(textwrap.dedent(f"""\
        ## 現象
        Truncated report at `{live}`. (issue #487)

        ## 驗收
        - reproduce the defect from the run dir
        """), encoding="utf-8")
    # Test binds to the snapshot member (the archive on disk).
    test_file = tmp_path / "t.py"
    test_file.write_text(textwrap.dedent(f"""\
        import subprocess
        from pathlib import Path
        def test_x():
            snap = Path("{repo}") / "{snap_rel}"
            r = subprocess.run(["python3","programs/g.py",str(snap)],
                               capture_output=True, text=True)
            assert r.returncode == 1
        """), encoding="utf-8")
    jout = tmp_path / "v.json"
    rc = _run_check(repo, issue_body, test_file, jout=jout)
    v = json.loads(jout.read_text())
    assert v["snapshot_resolution"]["has_snapshot"] is True
    assert "S2" in " ".join(v["snapshot_resolution"]["notes"])
    assert v["snapshot_resolution"]["sha256_verified"] is True


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


def test_check_mutated_snapshot_archive_flags_mismatch(tmp_path):
    """If the snapshot ARCHIVE itself is mutated after capture, sha256
    re-verification reports False (the snapshot is no longer frozen)."""
    repo = _make_repo(tmp_path)
    live = _make_live_artifact(tmp_path, _TRUNCATED)
    r = _run_snap(repo, live, 487, "truncated-report-snapshot")
    assert r.returncode == 0
    # tamper with the captured member
    member = (repo / "community" / "captures"
              / "issue-487-truncated-report-snapshot" / "drc_signoff.rpt")
    member.write_text("TAMPERED")

    import defect_artifact_fixture_check as m
    body = (f"## 現象\nlive `{live}` snapshot "
            f"`community/captures/issue-487-truncated-report-snapshot/"
            f"drc_signoff.rpt`\n## 驗收\n- repro\n")
    res = m.resolve_defect_artifact_source(body, repo_root=repo)
    assert res.has_snapshot is True
    assert res.sha256_verified is False


# ==========================================================================
# Direct-import unit coverage
# ==========================================================================
def test_unit_snapshot_paths_and_live_paths():
    import defect_artifact_fixture_check as m
    body = ("snapshot `community/captures/issue-487-foo/r.rpt` "
            "live `/abs/run/reports/r.rpt`")
    snaps = m.snapshot_paths_in_body(body)
    assert any("community/captures/issue-487-foo/r.rpt" in s for s in snaps)
    lives = m.live_paths_in_body(body, snaps)
    assert any("/abs/run/reports/r.rpt" in l for l in lives)
    # snapshot path must not appear among the live paths
    assert not any("community/captures" in l for l in lives)


def test_unit_resolve_prefers_snapshot_over_live():
    import defect_artifact_fixture_check as m
    body = ("## 驗收\nsnapshot `community/captures/issue-1-x/a.json` "
            "live `/run/a.json`\n")
    res = m.resolve_defect_artifact_source(body, repo_root=Path("/nonexist"))
    assert res.prefer_snapshot is True
    assert "community/captures/issue-1-x/a.json" in res.snapshot_path


def test_unit_derive_dir_slug_is_greppable_by_issue():
    import defect_artifact_snapshot as s
    assert s.derive_dir_slug(487, "truncated-report") == \
        "issue-487-truncated-report"
    assert s.derive_dir_slug(None, "no-issue") == "no-issue"
    assert s.derive_dir_slug(12, None) == "issue-12"
