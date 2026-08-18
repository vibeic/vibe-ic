"""Unit tests for quartus_map_audit.py.

Covers silent-failure indicators that Quartus buries in .map.rpt even when
the build returns success.

Tests:
  1. Report with Stuck at GND             — FAIL with stuck-at-gnd
  2. Report with Warning (10030)          — FAIL with no-driver
  3. Report with Warning (10855)          — FAIL with init-not-const
  4. Report with Lost fanout              — FAIL with lost-fanout
  5. Report with Stuck at VCC             — FAIL with stuck-at-vcc
  6. Clean report                         — PASS
  7. Missing file                         — io error (exit 2)
"""
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "quartus_map_audit.py"
assert SCRIPT.exists(), f"quartus_map_audit.py not found at {SCRIPT}"


def _run(report: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(report)],
        capture_output=True,
        text=True,
    )


def _write(tmp: Path, body: str) -> Path:
    p = tmp / "out.map.rpt"
    p.write_text(body)
    return p


def test_stuck_at_gnd(tmp_path):
    f = _write(tmp_path, "; foo|reg  ; Stuck at GND due to stuck port data_in  ;\n")
    r = _run(f)
    assert r.returncode == 1
    assert "stuck-at-gnd" in r.stderr


def test_warning_10030(tmp_path):
    f = _write(tmp_path, "Warning (10030): Net \"rom\" has no driver\n")
    r = _run(f)
    assert r.returncode == 1
    assert "no-driver" in r.stderr


def test_warning_10855(tmp_path):
    f = _write(tmp_path, "Warning (10855): initial value for variable rom should be constant\n")
    r = _run(f)
    assert r.returncode == 1
    assert "init-not-const" in r.stderr


def test_lost_fanout(tmp_path):
    f = _write(tmp_path, "; aid_master:u_master|st~14 ; Lost fanout ;\n")
    r = _run(f)
    assert r.returncode == 1
    assert "lost-fanout" in r.stderr


def test_stuck_at_vcc(tmp_path):
    f = _write(tmp_path, "; foo ; Stuck at VCC ;\n")
    r = _run(f)
    assert r.returncode == 1
    assert "stuck-at-vcc" in r.stderr


def test_clean_report(tmp_path):
    f = _write(tmp_path, "Info: Quartus Prime Full Compilation was successful.\n")
    r = _run(f)
    assert r.returncode == 0


def test_missing_file(tmp_path):
    r = _run(tmp_path / "does-not-exist.map.rpt")
    assert r.returncode == 2
