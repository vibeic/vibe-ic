"""Unit tests for gds_size_check.py.

Tests verify correct detection of missing/empty/malformed/too-small GDS.

v1.2.0 fixture change — every "this should PASS" case previously used a
raw ``b'\\x00' * N`` blob. That fixture asserted, as EXPECTED BEHAVIOUR,
that 200 KB of zeros is an acceptable sign-off GDS. It is not: a blob of
zeros is equally consistent with "clean layout" and "the streamer wrote
nothing", which is the exact false-PASS class this program exists to
catch. The passing fixtures now open with a real GDSII HEADER record so
they exercise the SIZE logic without also asserting that a non-GDS file
is a GDS. The negative-control coverage for the old behaviour lives in
``TestInvalidFormatIsFatal`` below.
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


# GDSII HEADER record: length 0x0006, record type 0x0002, version 3.
_GDS_HEADER = b'\x00\x06\x00\x02\x00\x03'


def gds_bytes(total: int) -> bytes:
    """A buffer of `total` bytes opening with a real GDSII HEADER record.

    Only the header is meaningful to gds_size_check (it reads 4 bytes);
    full record-stream well-formedness is
    gds_deliverable_plausibility_check's job.
    """
    if total <= len(_GDS_HEADER):
        return _GDS_HEADER[:total]
    return _GDS_HEADER + b'\x00' * (total - len(_GDS_HEADER))


# ===========================================================================
# Test 1: Valid large GDS — PASS
# ===========================================================================
class TestValidLargeGds:
    def test_200kb_pass(self, tmp_path):
        """GDS file of 200 KB with min=100 KB → PASS (no ERRORs)."""
        f = tmp_path / "design.gds"
        f.write_bytes(gds_bytes(200 * 1024))
        findings, stats = gsc.audit_gds(f, min_size_kb=100)
        errors = [x for x in findings if x.severity == "ERROR"]
        assert len(errors) == 0
        assert stats["file_exists"] is True
        assert stats["file_size_kb"] >= 200

    def test_cli_pass(self, tmp_path):
        """CLI returns exit 0 for valid GDS."""
        f = tmp_path / "design.gds"
        f.write_bytes(gds_bytes(200 * 1024))
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
        f.write_bytes(gds_bytes(10 * 1024))  # 10 KB
        findings, stats = gsc.audit_gds(f, min_size_kb=100)
        errors = [x for x in findings if x.severity == "ERROR"]
        assert len(errors) == 1
        assert errors[0].category == "TOO_SMALL"

    def test_cli_fail_small(self, tmp_path):
        """CLI returns exit 1 for too-small GDS."""
        f = tmp_path / "design.gds"
        f.write_bytes(gds_bytes(10 * 1024))

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
        f.write_bytes(gds_bytes(100 * 1024))  # exactly 100 KB
        findings, stats = gsc.audit_gds(f, min_size_kb=100)
        errors = [x for x in findings if x.severity == "ERROR"]
        assert len(errors) == 0

    def test_one_byte_below_threshold(self, tmp_path):
        """GDS file 1 byte below threshold → TOO_SMALL."""
        f = tmp_path / "design.gds"
        f.write_bytes(gds_bytes(100 * 1024 - 1))
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
        f.write_bytes(gds_bytes(1024))

        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--gds-file', str(f),
             '--min-size-kb', '0.5'],
            capture_output=True, text=True)
        assert res.returncode == 0


# ===========================================================================
# Test 7 (v1.2.0 NEGATIVE CONTROL): a non-GDS blob is not a deliverable
# ===========================================================================
class TestInvalidFormatIsFatal:
    """Pins the v1.1.0 -> v1.2.0 severity fix.

    Under v1.1.0 INVALID_GDS_FORMAT was a WARNING, so every case below
    exited 0 and the wired Step-37 gate reported PASS. These assertions
    FAIL against v1.1.0 by construction — that is what makes them a
    negative control rather than a restatement of current behaviour.
    """

    def test_zero_blob_above_floor_is_error(self, tmp_path):
        """150 KB of 0x00 is above the byte floor but is not a GDS."""
        f = tmp_path / "design.gds"
        f.write_bytes(b'\x00' * 150_000)
        findings, _ = gsc.audit_gds(f, min_size_kb=100)
        cats = {x.category for x in findings if x.severity == "ERROR"}
        assert "INVALID_GDS_FORMAT" in cats

    def test_renamed_text_log_is_error(self, tmp_path):
        """A tool error log renamed to .gds must not pass sign-off."""
        f = tmp_path / "design.gds"
        f.write_bytes(b"ERROR: detailed route failed, no layout produced\n" * 3200)
        findings, _ = gsc.audit_gds(f, min_size_kb=100)
        cats = {x.category for x in findings if x.severity == "ERROR"}
        assert "INVALID_GDS_FORMAT" in cats

    # Explicit ids: pytest derives node ids from parameter values, and a
    # 150 KB bytes literal would produce a node id long enough to blow the
    # PYTEST_CURRENT_TEST env var past E2BIG in any subprocess call.
    @pytest.mark.parametrize("payload", [
        b'\x00' * 150_000,
        b"ERROR: no layout produced\n" * 6000,
    ], ids=["zero_blob", "renamed_error_log"])
    def test_cli_exit_1_for_non_gds(self, tmp_path, payload):
        """CLI must exit 1 — under v1.1.0 both of these exited 0."""
        f = tmp_path / "design.gds"
        f.write_bytes(payload)
        res = subprocess.run(
            [sys.executable, str(SCRIPT),
             '--gds-file', str(f), '--min-size-kb', '100'],
            capture_output=True, text=True)
        assert res.returncode == 1, (
            "a non-GDS blob above the byte floor exited 0 — this is the "
            "v1.1.0 false PASS")
