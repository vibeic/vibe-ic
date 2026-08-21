"""Unit tests for gds_size_check.py.

Tests verify correct detection of missing/empty/too-small GDS files.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'gds_size_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import gds_size_check as gsc  # noqa: E402


# ===========================================================================
# Test 1: Valid large GDS — PASS
# ===========================================================================
class TestValidLargeGds:
    def test_200kb_pass(self, tmp_path):
        """GDS file of 200 KB with min=100 KB → PASS (no ERRORs)."""
        f = tmp_path / "design.gds"
        f.write_bytes(b'\x00' * (200 * 1024))  # 200 KB
        findings, stats = gsc.audit_gds(f, min_size_kb=100)
        errors = [x for x in findings if x.severity == "ERROR"]
        assert len(errors) == 0
        assert stats["file_exists"] is True
        assert stats["file_size_kb"] >= 200

    def test_cli_pass(self, tmp_path):
        """CLI returns exit 0 for valid GDS."""
        f = tmp_path / "design.gds"
        f.write_bytes(b'\x00' * (200 * 1024))
        report = tmp_path / "report.json"

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--gds-file', str(f),
             '--min-size-kb', '100',
             '--json', str(report)],
            capture_output=True, text=True)
        assert res.returncode == 0
        data = json.loads(report.read_text())
        assert data["summary"]["pass"] is True


# ===========================================================================
# Test 2: Too small — FAIL
# ===========================================================================
class TestTooSmall:
    def test_10kb_fail(self, tmp_path):
        """GDS file of 10 KB with min=100 KB → TOO_SMALL."""
        f = tmp_path / "design.gds"
        f.write_bytes(b'\x00' * (10 * 1024))  # 10 KB
        findings, stats = gsc.audit_gds(f, min_size_kb=100)
        errors = [x for x in findings if x.severity == "ERROR"]
        assert len(errors) == 1
        assert errors[0].category == "TOO_SMALL"

    def test_cli_fail_small(self, tmp_path):
        """CLI returns exit 1 for too-small GDS."""
        f = tmp_path / "design.gds"
        f.write_bytes(b'\x00' * (10 * 1024))

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--gds-file', str(f),
             '--min-size-kb', '100'],
            capture_output=True, text=True)
        assert res.returncode == 1


# ===========================================================================
# Test 3: Missing GDS — FAIL
# ===========================================================================
class TestMissingGds:
    def test_nonexistent_file(self, tmp_path):
        """Non-existent GDS → MISSING_GDS."""
        findings, stats = gsc.audit_gds(tmp_path / "nonexistent.gds", min_size_kb=100)
        assert len(findings) == 1
        assert findings[0].category == "MISSING_GDS"
        assert stats["file_exists"] is False

    def test_cli_fail_missing(self, tmp_path):
        """CLI returns exit 1 for missing GDS."""
        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--gds-file', str(tmp_path / "nonexistent.gds")],
            capture_output=True, text=True)
        assert res.returncode == 1


# ===========================================================================
# Test 4: Zero-size GDS — FAIL
# ===========================================================================
class TestZeroSize:
    def test_empty_file(self, tmp_path):
        """Zero-byte GDS → EMPTY_GDS."""
        f = tmp_path / "design.gds"
        f.write_bytes(b'')
        findings, stats = gsc.audit_gds(f, min_size_kb=100)
        assert len(findings) == 1
        assert findings[0].category == "EMPTY_GDS"
        assert stats["file_size_bytes"] == 0

    def test_cli_fail_zero(self, tmp_path):
        """CLI returns exit 1 for zero-size GDS."""
        f = tmp_path / "design.gds"
        f.write_bytes(b'')

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--gds-file', str(f)],
            capture_output=True, text=True)
        assert res.returncode == 1


# ===========================================================================
# Test 5: Exact threshold — boundary test
# ===========================================================================
class TestBoundary:
    def test_exactly_at_threshold(self, tmp_path):
        """GDS file exactly at threshold → PASS (no ERRORs)."""
        f = tmp_path / "design.gds"
        f.write_bytes(b'\x00' * (100 * 1024))  # exactly 100 KB
        findings, stats = gsc.audit_gds(f, min_size_kb=100)
        errors = [x for x in findings if x.severity == "ERROR"]
        assert len(errors) == 0

    def test_one_byte_below_threshold(self, tmp_path):
        """GDS file 1 byte below threshold → TOO_SMALL."""
        f = tmp_path / "design.gds"
        f.write_bytes(b'\x00' * (100 * 1024 - 1))
        findings, stats = gsc.audit_gds(f, min_size_kb=100)
        errors = [x for x in findings if x.severity == "ERROR"]
        assert len(errors) == 1
        assert errors[0].category == "TOO_SMALL"


# ===========================================================================
# Test 6: Custom threshold via CLI
# ===========================================================================
class TestCustomThreshold:
    def test_small_threshold(self, tmp_path):
        """1 KB file with min=0.5 KB → PASS."""
        f = tmp_path / "design.gds"
        f.write_bytes(b'\x00' * 1024)

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--gds-file', str(f),
             '--min-size-kb', '0.5'],
            capture_output=True, text=True)
        assert res.returncode == 0
