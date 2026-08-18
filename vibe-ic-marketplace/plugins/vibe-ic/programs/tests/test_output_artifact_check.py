"""Unit tests for output_artifact_check.py.

Tests verify correct detection of missing artifacts, glob pattern matching,
empty lists, missing base directories, relative paths, and min-count checks.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'output_artifact_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import output_artifact_check as oac  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: All artifacts exist
# ---------------------------------------------------------------------------
def test_all_exist(tmp_path):
    (tmp_path / "file1.v").write_text("module m; endmodule")
    (tmp_path / "file2.json").write_text('{"key": "val"}')

    findings, info = oac.audit_artifacts(
        tmp_path, ["file1.v", "file2.json"]
    )
    assert len(findings) == 0
    assert len(info["checked_artifacts"]) == 2


# ---------------------------------------------------------------------------
# Test 2: One artifact missing
# ---------------------------------------------------------------------------
def test_one_missing(tmp_path):
    (tmp_path / "file1.v").write_text("module m; endmodule")
    # file2.json intentionally not created

    findings, info = oac.audit_artifacts(
        tmp_path, ["file1.v", "file2.json"]
    )
    assert len(findings) == 1
    assert findings[0].category == "MISSING_ARTIFACT"
    assert "file2.json" in findings[0].message


# ---------------------------------------------------------------------------
# Test 3: Glob pattern matches
# ---------------------------------------------------------------------------
def test_glob_match(tmp_path):
    rtl_dir = tmp_path / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "top.v").write_text("module top; endmodule")
    (rtl_dir / "sub.v").write_text("module sub; endmodule")

    findings, info = oac.audit_artifacts(
        tmp_path, [], pattern="phase2/stage1/rtl/*.v", min_count=2
    )
    assert len(findings) == 0
    assert len(info["glob_matches"]) == 2


# ---------------------------------------------------------------------------
# Test 4: Glob pattern no match
# ---------------------------------------------------------------------------
def test_glob_no_match(tmp_path):
    findings, info = oac.audit_artifacts(
        tmp_path, [], pattern="rtl/*.v", min_count=1
    )
    assert len(findings) == 1
    assert findings[0].category == "GLOB_NO_MATCH"


# ---------------------------------------------------------------------------
# Test 5: Empty artifact list (should pass)
# ---------------------------------------------------------------------------
def test_empty_list(tmp_path):
    findings, info = oac.audit_artifacts(tmp_path, [])
    assert len(findings) == 0
    assert len(info["checked_artifacts"]) == 0


# ---------------------------------------------------------------------------
# Test 6: Base directory missing
# ---------------------------------------------------------------------------
def test_base_dir_missing(tmp_path):
    missing_dir = tmp_path / "nonexistent"
    findings, info = oac.audit_artifacts(missing_dir, ["file.v"])
    assert len(findings) == 1
    assert findings[0].category == "BASE_DIR_MISSING"


# ---------------------------------------------------------------------------
# Test 7: Relative paths with subdirectory
# ---------------------------------------------------------------------------
def test_relative_paths(tmp_path):
    sub = tmp_path / "dir"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "file3.sv").write_text("module x; endmodule")

    findings, info = oac.audit_artifacts(
        tmp_path, ["dir/file3.sv"]
    )
    assert len(findings) == 0


# ---------------------------------------------------------------------------
# Test 8: Min-count check (glob matches fewer than required)
# ---------------------------------------------------------------------------
def test_min_count_check(tmp_path):
    rtl_dir = tmp_path / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "top.v").write_text("module top; endmodule")

    # Require at least 3, but only 1 exists
    findings, info = oac.audit_artifacts(
        tmp_path, [], pattern="rtl/*.v", min_count=3
    )
    assert len(findings) == 1
    assert findings[0].category == "GLOB_NO_MATCH"
    assert "3" in findings[0].message


# ---------------------------------------------------------------------------
# Test: CLI exit code
# ---------------------------------------------------------------------------
def test_cli_exit_code_pass(tmp_path):
    (tmp_path / "out.v").write_text("module x; endmodule")
    rc = oac.main([
        '--artifacts', 'out.v',
        '--base-dir', str(tmp_path),
    ])
    assert rc == 0


def test_cli_exit_code_fail(tmp_path):
    rc = oac.main([
        '--artifacts', 'missing.v',
        '--base-dir', str(tmp_path),
    ])
    assert rc == 1
