#!/usr/bin/env python3
"""Tests for project_outputs_in_tree_check.py — chip-AGNOSTIC volatile-
storage gate.

Covers:
  1. POSITIVE_PASS — RESULT.md / waivers.json / reports/ have no /tmp
                     references.
  2. POSITIVE_FAIL — RESULT.md cites a /tmp/<file> AND that file exists
                     on disk (live external artifact).
  3. SKIP_NON_APPLICABLE — project tree is empty (no scan target files
                     at all → no findings → PASS, the SKIP analogue).
  4. SKIP_NO_CONSTRUCT — same (covered by #3).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "project_outputs_in_tree_check.py"


def _run(project_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project_dir)],
        capture_output=True, text=True,
    )


# -- Test 1: POSITIVE_PASS — clean project --

def test_positive_pass_clean_project(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "# Project results\n"
        "All artifacts under reports/ and rtl/ — no volatile paths.\n"
    )
    (tmp_path / "waivers.json").write_text(json.dumps({}))
    (tmp_path / "reports").mkdir(parents=True, exist_ok=True)
    (tmp_path / "reports" / "build.json").write_text(json.dumps({
        "status": "PASS", "artifact": "phase2/stage1/rtl/chip_top.sv",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout
    assert "no /tmp" in r.stdout


# -- Test 2: POSITIVE_FAIL — live /tmp artifact --

def test_positive_fail_live_tmp(tmp_path):
    # Create an artifact in /tmp that actually exists.
    sentinel = Path("/tmp") / f"vibe_test_artifact_{tmp_path.name}.gds"
    sentinel.write_text("# fake GDS\n")
    try:
        (tmp_path / "RESULT.md").write_text(
            f"GDS produced at: {sentinel}\n"
        )
        r = _run(tmp_path)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "[FAIL]" in r.stdout
        assert "live external-storage" in r.stdout
        assert str(sentinel) in r.stdout
    finally:
        try:
            sentinel.unlink()
        except FileNotFoundError:
            pass


# -- Test 3: SKIP_NON_APPLICABLE — empty project (no scan files) --

def test_skip_empty_project(tmp_path):
    # Empty project — no RESULT.md, no waivers.json, no reports/.
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout
    assert "no /tmp" in r.stdout


# -- Test 4: SKIP_NO_CONSTRUCT — only unrelated files --

def test_skip_unrelated_files(tmp_path):
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "top.sv").write_text(
        "module top();\nendmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


# -- Test 5: WARN — dangling /tmp reference (file gone) --

def test_dangling_tmp_reference(tmp_path):
    """Reference to /tmp/<file> that no longer exists → still FAIL
    (because findings list is non-empty), with WARN sub-line."""
    (tmp_path / "RESULT.md").write_text(
        "# Lost results\n"
        "Used /tmp/dead_artifact_xyz_does_not_exist_anywhere.gds\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    # No live findings, but dangling counted in fail_count.
    assert "[WARN]" in r.stdout
    assert "dangling external-path" in r.stdout


# -- Test 6: PASS_WITH_WAIVER --

def test_pass_with_waiver(tmp_path):
    (tmp_path / "RESULT.md").write_text(
        "Cache: /tmp/build_cache_123/intermediate.json\n"
    )
    rationale = (
        "Build cache lives in /tmp by design — never used as audit "
        "evidence; ticket BUILD-101 documents the cache architecture "
        "and rotation policy."
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "project_artifacts_external_storage_intentional": rationale,
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS_WITH_WAIVER]" in r.stdout


# -- Test 7: usage error --

def test_usage_error():
    r = subprocess.run([sys.executable, str(PROG)], capture_output=True,
                       text=True)
    assert r.returncode == 2
