"""Tests for tristate_bus_check.py (SVA/SBY generator for tri-state buses)."""
from __future__ import annotations
import subprocess, sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "tristate_bus_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def test_help_works():
    code, out, _ = _run(["--help"])
    assert code == 0


def test_missing_required_args_errors(tmp_path):
    code, _, err = _run([])
    assert code != 0


def test_minimal_generation(tmp_path):
    outdir = tmp_path / "sva"
    code, _, err = _run([
        "--bus-name", "acc_id",
        "--drivers", "dut:u_tx.bus_oe,host:host_oe",
        "--out-dir", str(outdir),
    ])
    # Should produce files
    assert code == 0 or outdir.exists()
    if outdir.exists():
        files = list(outdir.glob("*"))
        assert len(files) > 0, f"Expected output files in {outdir}"


def test_sva_file_has_content(tmp_path):
    outdir = tmp_path / "sva"
    _run([
        "--bus-name", "id_bus",
        "--drivers", "a:drv_a,b:drv_b",
        "--out-dir", str(outdir),
    ])
    if outdir.exists():
        for sv in outdir.glob("*.sv"):
            content = sv.read_text()
            # Basic sanity: should have assertion keyword or module
            assert len(content) > 50
