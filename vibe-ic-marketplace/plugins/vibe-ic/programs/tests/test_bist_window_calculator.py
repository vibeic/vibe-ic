"""Tests for bist_window_calculator.py (BIST sample-window sizing)."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "bist_window_calculator.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def test_help_works():
    code, out, _ = _run(["--help"])
    assert code == 0


def test_missing_required_args_errors():
    code, _, _ = _run([])
    assert code != 0


def test_aid_protocol_calculation():
    """Typical AID BIST: 22 bytes max, 10us per bit, 2.5 MHz sample clk."""
    code, out, err = _run([
        "--max-bytes", "22",
        "--bit-period-us", "10",
        "--clk-mhz", "2.5",
    ])
    assert code == 0
    # Output should mention a window size in cycles/us
    assert any(tok in out.lower() for tok in ("window", "cycles", "us", "μs", "bytes"))


def test_margin_option_accepted():
    code, out, _ = _run([
        "--max-bytes", "10",
        "--bit-period-us", "10",
        "--clk-mhz", "2.5",
        "--margin", "1.5",
    ])
    assert code == 0


def test_ibt_option_affects_output():
    code_no_ibt, out_no, _ = _run([
        "--max-bytes", "10",
        "--bit-period-us", "10",
        "--clk-mhz", "2.5",
        "--ibt-us", "0",
    ])
    code_with_ibt, out_with, _ = _run([
        "--max-bytes", "10",
        "--bit-period-us", "10",
        "--clk-mhz", "2.5",
        "--ibt-us", "12",
    ])
    assert code_no_ibt == 0 and code_with_ibt == 0
    # Different IBT → different output (window grows with IBT)
    assert out_no != out_with
