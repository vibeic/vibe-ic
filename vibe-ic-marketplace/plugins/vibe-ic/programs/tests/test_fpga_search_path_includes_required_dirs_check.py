#!/usr/bin/env python3
"""Tests for fpga_search_path_includes_required_dirs_check.py — Wave 16 Gate 4."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "fpga_search_path_includes_required_dirs_check.py"
)


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, **kw,
    )


def _make(tmp_path: Path, rtl: dict | None = None,
          qsf: str | None = None,
          extra_files: dict | None = None,
          waivers: dict | None = None) -> Path:
    proj = tmp_path
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True, exist_ok=True)
    (proj / "phase2" / "stage1" / "fpga").mkdir(parents=True, exist_ok=True)
    if rtl:
        for name, body in rtl.items():
            (proj / "phase2" / "stage1" / "rtl" / name).write_text(body)
    if qsf is not None:
        (proj / "phase2" / "stage1" / "fpga" / "out.qsf").write_text(qsf)
    if extra_files:
        for relpath, body in extra_files.items():
            p = proj / relpath
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(body)
    if waivers is not None:
        (proj / "waivers.json").write_text(json.dumps(waivers))
    return proj


def test_search_path_present_pass(tmp_path):
    """RTL $readmemh references X.hex; QSF SEARCH_PATH covers its dir → PASS."""
    proj = _make(
        tmp_path,
        rtl={
            "rom.v": """\
module rom(input clk, input [6:0] addr, output reg [7:0] q);
  reg [7:0] mem [0:127];
  initial $readmemh("rom.hex", mem);
endmodule
"""
        },
        qsf="set_global_assignment -name SEARCH_PATH ../rtl\n",
        extra_files={"phase2/stage1/rtl/rom.hex": "00\n"},
    )
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_search_path_missing_fail(tmp_path):
    """RTL $readmemh references X.hex; QSF has no covering SEARCH_PATH → FAIL."""
    proj = _make(
        tmp_path,
        rtl={
            "rom.v": """\
module rom(input clk, input [6:0] addr, output reg [7:0] q);
  reg [7:0] mem [0:127];
  initial $readmemh("rom.hex", mem);
endmodule
"""
        },
        qsf="set_global_assignment -name SEARCH_PATH ../somewhere_else\n",
        extra_files={"phase2/stage1/data/rom.hex": "00\n"},
    )
    r = _run([str(proj)])
    assert r.returncode == 1, r.stdout
    assert "FPGA_SEARCH_PATH_MISSING" in r.stdout


def test_no_readmem_skip(tmp_path):
    """No $readmem in RTL → SKIP."""
    proj = _make(
        tmp_path,
        rtl={"comb.v": "module comb(input a, output b); assign b=~a; endmodule\n"},
        qsf="set_global_assignment -name SEARCH_PATH ../rtl\n",
    )
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout
    assert "SKIP" in r.stdout


def test_with_waiver_pass(tmp_path):
    """Search path missing but waiver present → PASS_WITH_WAIVER."""
    proj = _make(
        tmp_path,
        rtl={
            "rom.v": """\
module rom(input clk, input [6:0] addr, output reg [7:0] q);
  reg [7:0] mem [0:127];
  initial $readmemh("rom.hex", mem);
endmodule
"""
        },
        qsf="set_global_assignment -name FAMILY \"MAX 10\"\n",
        extra_files={"phase2/stage1/data/rom.hex": "00\n"},
        waivers={
            "fpga_search_path_runtime_supplied_intentional": (
                "Hex file is supplied at runtime via SignalTap script "
                "rather than baked into bitstream — bench-validated"
            )
        },
    )
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVER" in r.stdout


def test_misc_file_explicit_pass(tmp_path):
    """MISC_FILE explicit listing satisfies requirement."""
    proj = _make(
        tmp_path,
        rtl={
            "rom.v": """\
module rom(input clk, input [6:0] addr, output reg [7:0] q);
  reg [7:0] mem [0:127];
  initial $readmemh("rom.hex", mem);
endmodule
"""
        },
        qsf="set_global_assignment -name MISC_FILE ../data/rom.hex\n",
        extra_files={"phase2/stage1/data/rom.hex": "00\n"},
    )
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0
