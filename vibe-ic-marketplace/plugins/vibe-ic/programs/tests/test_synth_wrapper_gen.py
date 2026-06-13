#!/usr/bin/env python3
"""Tests for synth_wrapper_gen.py — generates synth wrapper for inout-port designs.

Wave 83 — coverage for previously untested wired program.

The program scans rtl/<top>.sv for `inout` ports and emits a tri-state
expansion wrapper (each inout becomes _i / _o / _oe nets) so synthesis
tools like Yosys don't optimise the open-drain bus away.

Cases:
  1. POSITIVE_PASS — top.sv with one inout → wrapper emitted with _i/_o/_oe.
  2. POSITIVE_PASS_MULTI — multiple inouts → all expanded.
  3. SKIP_NO_RTL_DIR — no rtl/ → SKIP exit 0.
  4. SKIP_NO_INOUT — top.sv has no inout → SKIP exit 0.
  5. SKIP_TOP_NOT_FOUND — custom --top points at nothing → SKIP.
  6. EDGE_VECTOR_INOUT — `inout [3:0] bus` is detected.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "synth_wrapper_gen.py"


def _run(args: list, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, timeout=timeout,
    )


def _seed_rtl(project: Path, body: str, top: str = "chip_top",
              ext: str = ".sv") -> None:
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / f"{top}{ext}").write_text(body)


def test_positive_pass_single_inout(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_rtl(project,
        """module chip_top (
  input  wire clk,
  input  wire reset_n,
  inout  wire id_bus
);
endmodule
""")
    cp = _run([str(project)])
    assert cp.returncode == 0, cp.stderr
    assert "[PASS] synth_wrapper_gen" in cp.stdout
    assert "id_bus" in cp.stdout
    out = project / "phase2" / "stage1" / "rtl" / "chip_top_synth.sv"
    assert out.is_file()
    text = out.read_text()
    assert "id_bus_i" in text
    assert "id_bus_o" in text
    assert "id_bus_oe" in text


def test_positive_pass_multiple_inouts(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_rtl(project,
        """module chip_top (
  input  wire clk, reset_n,
  inout  wire bus_a,
  inout  wire bus_b
);
endmodule
""")
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "2 inout" in cp.stdout
    text = (project / "phase2" / "stage1" / "rtl" / "chip_top_synth.sv").read_text()
    for sig in ("bus_a", "bus_b"):
        assert f"{sig}_i" in text
        assert f"{sig}_o" in text
        assert f"{sig}_oe" in text


def test_skip_no_rtl_dir(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "[SKIP]" in cp.stdout


def test_skip_no_inout(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_rtl(project,
        "module chip_top (input clk, output reg led); endmodule\n")
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "[SKIP]" in cp.stdout
    assert "no inout" in cp.stdout


def test_skip_top_not_found(tmp_path):
    project = tmp_path / "proj"
    (project / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    cp = _run([str(project), "--top", "nonexistent_top"])
    assert cp.returncode == 0
    assert "[SKIP]" in cp.stdout


def test_edge_vector_inout(tmp_path):
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_rtl(project,
        """module chip_top (
  input  wire clk, reset_n,
  inout  wire [3:0] data_bus
);
endmodule
""")
    cp = _run([str(project)])
    assert cp.returncode == 0
    assert "data_bus" in cp.stdout
    text = (project / "phase2" / "stage1" / "rtl" / "chip_top_synth.sv").read_text()
    assert "data_bus_i" in text


def test_edge_no_chip_specific_strings_in_output(tmp_path):
    """Wrapper output is generic — must not mention any specific chip."""
    project = tmp_path / "proj"
    project.mkdir(parents=True, exist_ok=True)
    _seed_rtl(project,
        "module chip_top (input clk, reset_n, inout id_bus); endmodule\n")
    cp = _run([str(project)])
    assert cp.returncode == 0
    text = (project / "phase2" / "stage1" / "rtl" / "chip_top_synth.sv").read_text()
    for f in ("EXAMPLE_CHIP", "EXAMPLE_TESTER", "ACC_ID", "A1101"):
        assert f not in text
