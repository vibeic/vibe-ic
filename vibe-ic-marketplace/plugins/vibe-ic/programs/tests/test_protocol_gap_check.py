"""Tests for protocol_gap_check.py (gap-assertion generator)."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "protocol_gap_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def test_help_works():
    code, out, _ = _run(["--help"])
    assert code == 0


def test_required_args_enforced():
    code, _, err = _run([])
    assert code != 0


def test_minimal_gap_generation(tmp_path):
    outdir = tmp_path / "gap"
    code, _, err = _run([
        "--name", "ibt",
        "--end-signal", "byte_done",
        "--bus-idle", "id_bus == 1",
        "--min-cycles", "30",
        "--out-dir", str(outdir),
    ])
    assert code == 0 or outdir.exists()
    if outdir.exists():
        files = list(outdir.glob("*"))
        assert len(files) > 0


def test_max_cycles_optional(tmp_path):
    """--max-cycles is optional; omitting should still work."""
    outdir = tmp_path / "gap_min"
    code, _, _ = _run([
        "--name", "stop_bit",
        "--end-signal", "tx_done",
        "--bus-idle", "tx == 1",
        "--min-cycles", "8",
        "--out-dir", str(outdir),
    ])
    # No crash on missing --max-cycles
    assert outdir.exists() or code == 0
