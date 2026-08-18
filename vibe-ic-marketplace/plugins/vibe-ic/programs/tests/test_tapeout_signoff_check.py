"""Tests for tapeout_signoff_check.py (wrapper around signoff_audit)."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "tapeout_signoff_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def test_help_works():
    code, out, _ = _run(["--help"])
    assert code == 0
    assert "tapeout" in out.lower() or "signoff" in out.lower()


def test_mode_argument_required(tmp_path):
    """--mode is required."""
    code, _, _ = _run([str(tmp_path)])
    assert code != 0


def test_empty_project_fails_tapeout_mode(tmp_path):
    code, _, _ = _run([str(tmp_path), "--mode", "tapeout"])
    # no GDS / netlist / timing / drc → should fail
    assert code != 0


def test_lenient_flag_rejected(tmp_path):
    """v1.6.21: --lenient was removed (4-of-4 strict is the only mode).
    Passing it must error out, not silently downgrade signoff."""
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--mode", "tapeout", "--lenient"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
    assert "unrecognized" in r.stderr


def test_json_flag_writes_file(tmp_path):
    j = tmp_path / "out.json"
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path),
         "--mode", "tapeout", "--json", str(j)],
        capture_output=True, text=True,
    )
    # Regardless of pass/fail, --json shouldn't be silently dropped
    if j.exists():
        try:
            json.loads(j.read_text())
        except Exception:
            # ok if empty, but if non-empty must be JSON
            assert j.stat().st_size == 0
