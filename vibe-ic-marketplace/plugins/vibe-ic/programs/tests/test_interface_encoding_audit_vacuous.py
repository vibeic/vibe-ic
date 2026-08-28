"""#559 — `interface_encoding_audit` printed an error and exited 0.

Found while triaging the gates the P0 umbrella cannot invoke. Pointed at a
directory that does not exist:

    ERROR: RTL directory not found: /nope
    interface_encoding_audit: 0 MISMATCH, 0 MATCH, 0 UNKNOWN (0 interfaces analyzed)
    rc=0

The error path returned an empty result list, and the verdict was
`1 if mismatches > 0 else 0`. Zero files scanned and zero mismatches found
produce the same exit code, so a caller reading rc — which the umbrella does —
records "no encoding mismatch here" for a directory that is not there.

Note the message WAS honest: it said `0 interfaces analyzed` on stdout and
named the missing directory on stderr. `gate_discloses_denominator_check`
audits 493 gates for exactly that disclosure and passes this one, correctly:
its contract is "a PASS must say how much it looked at", and this gate said so.
Disclosing the denominator and refusing on a zero denominator are two different
properties, and only the first was enforced anywhere.

rc=2 rather than 1: this is "could not check", not "found a defect", and the CI
dispatcher already distinguishes them (`run_tolerating_uncheckable`).
"""
from __future__ import annotations

import pathlib
import sys

import pytest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
PROG = _PROGRAMS / "interface_encoding_audit.py"

CLEAN_RTL = """\
module top(input wire clk, input wire rst_n, output wire q);
endmodule
"""


def _run(rtl_dir, out_dir):
    return _pr.run(
        [sys.executable, str(PROG), "--rtl-dir", str(rtl_dir),
         "--top-module", "top", "--out-dir", str(out_dir)],
        capture_output=True, text=True)


def test_missing_rtl_dir_does_not_exit_zero(tmp_path):
    proc = _run(tmp_path / "does-not-exist", tmp_path / "out")
    assert proc.returncode == 2, (
        f"a missing RTL directory exited {proc.returncode}; a caller reading "
        f"the exit code cannot tell that from a clean audit")
    assert "VACUOUS_PASS" in proc.stderr


def test_empty_rtl_dir_does_not_exit_zero(tmp_path):
    """Directory exists, holds no .v/.sv — the second no-input path."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    proc = _run(rtl, tmp_path / "out")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "VACUOUS_PASS" in proc.stderr


def test_real_rtl_still_passes(tmp_path):
    """The accept case.

    Every change here makes the gate refuse more, so without this a program
    that refused everything would satisfy the two tests above.
    """
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.v").write_text(CLEAN_RTL, encoding="utf-8")
    proc = _run(rtl, tmp_path / "out")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "VACUOUS_PASS" not in proc.stderr


def test_the_denominator_is_still_stated(tmp_path):
    """The disclosure that was already correct must survive the fix."""
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.v").write_text(CLEAN_RTL, encoding="utf-8")
    proc = _run(rtl, tmp_path / "out")
    assert "interfaces analyzed" in proc.stdout, proc.stdout


def test_the_reason_is_named_not_generic(tmp_path):
    """Two different no-input causes must not print the same sentence."""
    missing = _run(tmp_path / "gone", tmp_path / "o1")
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    empty = _run(rtl, tmp_path / "o2")
    assert "not found" in missing.stderr
    assert "no .v/.sv" in empty.stderr
    assert missing.stderr != empty.stderr
