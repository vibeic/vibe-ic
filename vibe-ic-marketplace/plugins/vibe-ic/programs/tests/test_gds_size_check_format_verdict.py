#!/usr/bin/env python3
"""tests/test_gds_size_check_format_verdict.py

Reachability tests for `gds_size_check`'s "this artefact is not a GDSII"
verdict.

THE DEFECT. The program's docstring advertised INVALID_GDS_FORMAT as one of the
things it catches, but the finding was hard-coded `severity="WARNING"` while the
verdict is `pass = all(f.severity != "ERROR")`, and the sole caller — flow step
37, `program_exit_zero: "gds_size_check --gds-file phase3/stage4/gds/*.gds
--json reports/phase3/gds_size.json"` — consumes nothing but the exit code. No
input could reach a FAIL for it. Any blob above the size floor that was not a
GDSII at all signed off `pass: true`, exit 0. The `except OSError: pass` arm had
the same shape: an existing-but-unreadable file also signed off green.

BOTH DIRECTIONS ARE TESTED HERE, deliberately:

  * `TestFailVerdictIsReachable` — the forward control. Every case FAILS against
    the pre-fix program (which returned exit 0 / `pass: true` for all of them).
  * `TestPassVerdictIsStillReachable` — the non-degeneracy control. A "fix" that
    reddened everything would satisfy the forward control alone, so proving one
    direction is half the property. These cases are written VERSION-AGNOSTIC on
    purpose: they touch only fields that exist before AND after the fix (exit
    code, `summary.pass`, `summary.errors_count`, finding categories), so they
    PASS against the pre-fix program too and are a real control rather than a
    test that happens to die on a missing new key.
  * `TestHeaderVerdictIsReported` — the new evidence field. Part of the forward
    control: it also fails pre-fix, because pre-fix there was no such field.

Every assertion is on a returned value, an exit code, or emitted JSON. No test
here inspects the source text of the program.

Fixtures are synthetic byte blobs. No design, PDK, or part number appears.
"""
from __future__ import annotations

import json
import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "gds_size_check.py"
sys.path.insert(0, str(SCRIPT.parent))
import gds_size_check as gsc  # noqa: E402


#: The first four bytes of every GDSII stream: length 0x0006, record type 0x00
#: (HEADER), data type 0x02. Built from struct so the constant is derived, not
#: copied out of the program under test.
_HEADER = struct.pack(">HH", 6, 0x0002)

_KB = 1024
_ABOVE_FLOOR = 200 * _KB          # comfortably over the 100 KB default floor
_FLOOR_KB = 100.0


def _valid_stream(size: int = _ABOVE_FLOOR) -> bytes:
    """A blob whose FIRST RECORD is a real GDSII HEADER, padded to `size`."""
    return _HEADER + struct.pack(">h", 600) + b"\x00" * (size - 6)


def _renamed_text_artefact(size: int = _ABOVE_FLOOR) -> bytes:
    """A plain-text netlist-ish artefact renamed to .gds — the real loophole."""
    body = b"VERSION 5.8 ;\nDIVIDERCHAR \"/\" ;\nBUSBITCHARS \"[]\" ;\n"
    return (body * (size // len(body) + 1))[:size]


def _binary_non_gdsii(size: int = _ABOVE_FLOOR) -> bytes:
    """Deterministic non-GDSII binary: a byte ramp. Seedless and reproducible.

    A regenerated-every-run random blob would make the verdict a draw, so the
    bytes are fixed.
    """
    return bytes((i * 7 + 3) & 0xFF for i in range(256)) * (size // 256)


#: Parametrised BY NAME, never by the blob itself: a 200 KB bytes object used as
#: a pytest param becomes part of the test id and overflows the argv of the
#: subprocess these cases spawn.
_NON_GDSII_BUILDERS = {
    "renamed_text": _renamed_text_artefact,
    "binary_non_gdsii": _binary_non_gdsii,
}


def _cli(args: list) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True, text=True, timeout=120)


def _cli_report(tmp_path: Path, name: str, args: list):
    """Run the CLI with --json and return (returncode, parsed report)."""
    out = tmp_path / f"{name}.json"
    r = _cli(args + ["--json", str(out)])
    return r.returncode, json.loads(out.read_text())


def _errors(findings):
    return [f for f in findings if f.severity == "ERROR"]


def _categories(findings):
    return {f.category for f in findings}


# ===========================================================================
# FORWARD CONTROL — these FAIL against the unfixed program.
# ===========================================================================
class TestFailVerdictIsReachable:

    @pytest.mark.parametrize("name", sorted(_NON_GDSII_BUILDERS))
    def test_non_gdsii_above_the_size_floor_is_a_hard_error(
            self, tmp_path, name):
        """200 KB that is not a GDSII must reach the ERROR verdict.

        Pre-fix: one WARNING, zero ERRORs, `pass` True.
        """
        f = tmp_path / f"{name}.gds"
        f.write_bytes(_NON_GDSII_BUILDERS[name]())

        findings, stats = gsc.audit_gds(f, min_size_kb=_FLOOR_KB)

        assert stats["file_size_bytes"] >= _FLOOR_KB * _KB, (
            "fixture must clear the size floor, or this proves nothing")
        assert stats["gdsii_header_ok"] is False
        assert "INVALID_GDS_FORMAT" in _categories(_errors(findings)), (
            f"{name}: expected a hard ERROR, got "
            f"{[(x.severity, x.category) for x in findings]}")

    @pytest.mark.parametrize("name", sorted(_NON_GDSII_BUILDERS))
    def test_non_gdsii_above_the_size_floor_exits_nonzero(
            self, tmp_path, name):
        """The gate is `program_exit_zero`, so only the exit code is consumed.

        Pre-fix: rc 0 and `summary.pass` True for both blobs.
        """
        f = tmp_path / f"{name}.gds"
        f.write_bytes(_NON_GDSII_BUILDERS[name]())

        rc, report = _cli_report(
            tmp_path, name,
            ["--gds-file", str(f), "--min-size-kb", str(_FLOOR_KB)])

        assert rc == 1, f"{name}: exit {rc}; step 37 would sign this off"
        assert report["summary"]["pass"] is False
        assert report["summary"]["errors_count"] >= 1
        assert report["summary"]["gdsii_header_ok"] is False
        assert "INVALID_GDS_FORMAT" in {
            x["category"] for x in report["findings"]}

    def test_short_file_with_no_size_floor_is_still_a_hard_error(
            self, tmp_path):
        """A 2-byte file cannot hold a HEADER record.

        With `--min-size-kb 0` the size arm cannot fire, so this isolates the
        format verdict. Pre-fix: zero findings at all, `pass` True, rc 0 —
        `len(header) >= 4` skipped the check entirely and nothing replaced it.
        """
        f = tmp_path / "stub.gds"
        f.write_bytes(b"\x00\x06")

        findings, stats = gsc.audit_gds(f, min_size_kb=0.0)
        assert "TOO_SMALL" not in _categories(findings), (
            "size arm must stay silent, otherwise this is not a format test")
        assert "INVALID_GDS_FORMAT" in _categories(_errors(findings))
        assert stats["gdsii_header_ok"] is False

        rc, report = _cli_report(
            tmp_path, "stub", ["--gds-file", str(f), "--min-size-kb", "0"])
        assert rc == 1
        assert report["summary"]["pass"] is False

    @pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                        reason="root ignores the read bit")
    def test_existing_but_unreadable_file_is_a_hard_error(self, tmp_path):
        """`exists()` says nothing about readability.

        Pre-fix the OSError was swallowed with `pass`, so an unreadable file
        above the floor signed off green.
        """
        f = tmp_path / "locked.gds"
        f.write_bytes(_valid_stream())
        os.chmod(f, 0o000)
        try:
            findings, stats = gsc.audit_gds(f, min_size_kb=_FLOOR_KB)
            assert "UNREADABLE_GDS" in _categories(_errors(findings)), (
                f"got {[(x.severity, x.category) for x in findings]}")
            assert stats["gdsii_header_ok"] is None, (
                "readability was never established, so the header verdict "
                "must be 'not determined', not a fabricated True/False")

            rc, report = _cli_report(
                tmp_path, "locked",
                ["--gds-file", str(f), "--min-size-kb", str(_FLOOR_KB)])
            assert rc == 1
            assert report["summary"]["pass"] is False
        finally:
            os.chmod(f, 0o600)


# ===========================================================================
# NON-DEGENERACY CONTROL — these pass BEFORE and AFTER the fix.
# A gate that can only ever say FAIL has not been repaired, it has been broken.
# ===========================================================================
class TestPassVerdictIsStillReachable:

    def test_valid_stream_above_the_floor_passes(self, tmp_path):
        f = tmp_path / "ok.gds"
        f.write_bytes(_valid_stream())

        findings, _ = gsc.audit_gds(f, min_size_kb=_FLOOR_KB)
        assert _errors(findings) == [], (
            f"a real GDSII header above the floor must PASS, got "
            f"{[(x.severity, x.category) for x in findings]}")

        rc, report = _cli_report(
            tmp_path, "ok",
            ["--gds-file", str(f), "--min-size-kb", str(_FLOOR_KB)])
        assert rc == 0
        assert report["summary"]["pass"] is True
        assert report["summary"]["errors_count"] == 0

    def test_valid_stream_exactly_at_the_floor_passes(self, tmp_path):
        f = tmp_path / "boundary.gds"
        f.write_bytes(_valid_stream(int(_FLOOR_KB) * _KB))

        rc, report = _cli_report(
            tmp_path, "boundary",
            ["--gds-file", str(f), "--min-size-kb", str(_FLOOR_KB)])
        assert rc == 0
        assert report["summary"]["pass"] is True

    def test_size_and_format_verdicts_stay_independent(self, tmp_path):
        """A valid stream below the floor fails on SIZE ONLY.

        Guards against a fix that collapses the two arms into one always-red
        answer: the report must still name which of the two failed.
        """
        f = tmp_path / "small_but_real.gds"
        f.write_bytes(_valid_stream(10 * _KB))

        rc, report = _cli_report(
            tmp_path, "small_but_real",
            ["--gds-file", str(f), "--min-size-kb", str(_FLOOR_KB)])
        cats = {x["category"] for x in report["findings"]}
        assert rc == 1
        assert cats == {"TOO_SMALL"}, f"expected TOO_SMALL alone, got {cats}"

    def test_missing_file_still_reports_exactly_missing_gds(self, tmp_path):
        """Absence must not acquire a second, invented failure reason."""
        findings, _ = gsc.audit_gds(
            tmp_path / "absent.gds", min_size_kb=_FLOOR_KB)
        assert _categories(findings) == {"MISSING_GDS"}

    def test_empty_file_still_reports_exactly_empty_gds(self, tmp_path):
        """A 0-byte deliverable is the flow's own GDS_BAD fixture. It must keep
        answering EMPTY_GDS and nothing else — the format arm returns before it.
        """
        f = tmp_path / "zero.gds"
        f.write_bytes(b"")
        findings, _ = gsc.audit_gds(f, min_size_kb=_FLOOR_KB)
        assert _categories(findings) == {"EMPTY_GDS"}

        rc, report = _cli_report(
            tmp_path, "zero",
            ["--gds-file", str(f), "--min-size-kb", str(_FLOOR_KB)])
        assert rc == 1
        assert report["summary"]["pass"] is False


# ===========================================================================
# The new evidence field. Forward control: pre-fix the report carried no
# statement at all about whether the artefact was a GDSII.
# ===========================================================================
class TestHeaderVerdictIsReported:

    def test_valid_stream_reports_header_ok_true(self, tmp_path):
        f = tmp_path / "ok.gds"
        f.write_bytes(_valid_stream())
        _, stats = gsc.audit_gds(f, min_size_kb=_FLOOR_KB)
        assert stats["gdsii_header_ok"] is True

        rc, report = _cli_report(
            tmp_path, "ok",
            ["--gds-file", str(f), "--min-size-kb", str(_FLOOR_KB)])
        assert rc == 0
        assert report["summary"]["gdsii_header_ok"] is True

    def test_missing_file_reports_header_verdict_as_undetermined(
            self, tmp_path):
        """Absence must not be reported as a format opinion either way."""
        _, stats = gsc.audit_gds(
            tmp_path / "absent.gds", min_size_kb=_FLOOR_KB)
        assert stats["gdsii_header_ok"] is None
