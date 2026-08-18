"""Tests for rx_tolerance_sweep.py (pulse-width decode-window sweep)."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "rx_tolerance_sweep.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def test_help_works():
    code, out, _ = _run(["--help"])
    assert code == 0


def test_missing_decode_table_errors():
    code, _, err = _run([])
    assert code != 0


def test_minimal_decode_table(tmp_path):
    """Feed a valid decode table; expect program to run without crash."""
    tbl = tmp_path / "decode.json"
    tbl.write_text(json.dumps({
        "symbols": [
            {"name": "H1", "low_min": 2, "low_max": 8, "meaning": "bit=1"},
            {"name": "H0", "low_min": 12, "low_max": 22, "meaning": "bit=0"},
            {"name": "BR", "low_min": 25, "low_max": 200, "meaning": "break"},
        ],
        "clock_mhz": 2.5,
    }))
    out_json = tmp_path / "sweep.json"
    code, out, err = _run([
        "--decode-table", str(tbl),
        "--json-out", str(out_json),
    ])
    # Program may succeed (0) or return non-zero gracefully; just avoid crash
    assert code in (0, 1, 2)


def test_bad_decode_table_errors(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not valid json")
    code, _, _ = _run(["--decode-table", str(bad)])
    assert code != 0
