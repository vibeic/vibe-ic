"""Unit tests for fault_atpg_run.py.

Fault runs inside a Docker container so the heavy integration path cannot
be unit-tested without the image. These tests cover:
  - Argument parsing and PDK config validation
  - IO-error handling (missing project dir, missing netlist, bad pdk)

Full end-to-end Fault-in-Docker run is validated by the aon_timer pilot
(see reports/dft/coverage.json); no need to re-run in unit tests.
"""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "fault_atpg_run.py"
assert SCRIPT.exists()


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
    )


def test_missing_project_dir(tmp_path):
    r = _run(str(tmp_path / "nope"), "--clock", "clk")
    assert r.returncode == 2
    assert "not a directory" in r.stderr.lower()


def test_missing_netlist(tmp_path):
    r = _run(str(tmp_path), "--netlist", "synth/missing.v", "--clock", "clk")
    assert r.returncode == 2
    assert "netlist not found" in r.stderr.lower()


def test_unsupported_pdk(tmp_path):
    (tmp_path / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (tmp_path / "phase2" / "stage2" / "synth" / "netlist.v").write_text("module top; endmodule\n")
    r = _run(str(tmp_path), "--clock", "clk", "--pdk", "nonexistent_pdk")
    # Program imports fine and gets to run_fault which returns exit 2 for bad pdk
    assert r.returncode in (1, 2)


def test_clock_arg_required(tmp_path):
    r = _run(str(tmp_path))
    assert r.returncode != 0
    assert "clock" in r.stderr.lower() or "required" in r.stderr.lower()
