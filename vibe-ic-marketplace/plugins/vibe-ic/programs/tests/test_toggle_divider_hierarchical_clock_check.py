#!/usr/bin/env python3
"""Tests for toggle_divider_hierarchical_clock_check.py (LL-31).

Extends LL-27 across submodule boundaries. Chip-agnostic.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "toggle_divider_hierarchical_clock_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _put_rtl(tmp_path: Path, name: str, body: str):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(body)


def _mark_fpga(tmp_path: Path):
    (tmp_path / "project.qsf").write_text("# fpga marker")


# 1. Silent-skip: no rtl dir.
def test_no_rtl_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0


# 2. Silent-skip: no FPGA artifacts → pure ASIC.
def test_asic_project_silent_pass(tmp_path):
    _put_rtl(tmp_path, "top.v",
             "module top; always_ff @(posedge mclk) clk_div <= ~clk_div;"
             " chip u_chip(.clk(clk_div)); endmodule\n"
             "module chip(input clk); always_ff @(posedge clk) x <= 1; "
             "endmodule")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "not an FPGA" in r.stdout


# 3. PASS — no toggle dividers anywhere.
def test_no_toggles_pass(tmp_path):
    _mark_fpga(tmp_path)
    _put_rtl(tmp_path, "top.v",
             "module top(input mclk); chip u_chip(.clk(mclk)); endmodule\n"
             "module chip(input clk); always_ff @(posedge clk) x <= 1; "
             "endmodule")
    r = _run(tmp_path)
    assert r.returncode == 0


# 4. FAIL — toggle in parent feeds submodule clock port.
def test_hierarchical_crossing_fails(tmp_path):
    _mark_fpga(tmp_path)
    _put_rtl(tmp_path, "top.v",
             "module top(input mclk);\n"
             "  reg clk_div;\n"
             "  always_ff @(posedge mclk) clk_div <= ~clk_div;\n"
             "  chip u_chip(.clk(clk_div));\n"
             "endmodule\n"
             "module chip(input clk);\n"
             "  always_ff @(posedge clk) x <= 1;\n"
             "endmodule")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "clk_div" in r.stdout


# 5. PASS_WITH_WAIVER.
def test_waiver_allows(tmp_path):
    _mark_fpga(tmp_path)
    _put_rtl(tmp_path, "top.v",
             "module top(input mclk);\n"
             "  reg clk_div;\n"
             "  always_ff @(posedge mclk) clk_div <= ~clk_div;\n"
             "  chip u_chip(.clk(clk_div));\n"
             "endmodule\n"
             "module chip(input clk);\n"
             "  always_ff @(posedge clk) x <= 1;\n"
             "endmodule")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "toggle_divider_hierarchical_intentional":
            "Intentional cross-module divider with verified clock-tree route",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


# 6. PASS — toggle exists but has matching create_generated_clock SDC.
def test_sdc_constraint_passes(tmp_path):
    _mark_fpga(tmp_path)
    _put_rtl(tmp_path, "top.v",
             "module top(input mclk);\n"
             "  reg clk_div;\n"
             "  always_ff @(posedge mclk) clk_div <= ~clk_div;\n"
             "  chip u_chip(.clk(clk_div));\n"
             "endmodule\n"
             "module chip(input clk);\n"
             "  always_ff @(posedge clk) x <= 1;\n"
             "endmodule")
    (tmp_path / "project.sdc").write_text(
        "create_generated_clock -name clk_div -source [get_ports mclk] "
        "-divide_by 2 [get_registers clk_div]\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0


# 7. PASS — toggle exists but submodule doesn't use port as posedge.
def test_no_posedge_in_submod_pass(tmp_path):
    _mark_fpga(tmp_path)
    _put_rtl(tmp_path, "top.v",
             "module top(input mclk);\n"
             "  reg clk_div;\n"
             "  always_ff @(posedge mclk) clk_div <= ~clk_div;\n"
             "  chip u_chip(.clk(clk_div));\n"
             "endmodule\n"
             "module chip(input clk);\n"
             "  assign y = clk;  // not used as posedge\n"
             "endmodule")
    r = _run(tmp_path)
    assert r.returncode == 0
