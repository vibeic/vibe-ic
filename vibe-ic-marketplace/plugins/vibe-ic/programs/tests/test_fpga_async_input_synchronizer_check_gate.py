#!/usr/bin/env python3
"""Tests for fpga_async_input_synchronizer_check.py.

Wave 24 / v0.119.56 expanded with 2-FF sync / direct-use / waiver cases.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "fpga_async_input_synchronizer_check.py")


def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args,
                          capture_output=True, text=True, **kw)


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_clean_rtl(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text("module top(input clk, input rst_n); wire a; endmodule\n")
    r = _run([str(tmp_path), "--top", "top"])
    assert r.returncode == 0


def test_2ff_sync_pass(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text(
        "module top(input clk, input id_bus, output reg q);\n"
        "  reg s1, s2;\n"
        "  always @(posedge clk) begin\n"
        "    s1 <= id_bus;\n"
        "    s2 <= s1;\n"
        "    q  <= s2;\n"
        "  end\n"
        "endmodule\n"
    )
    r = _run([str(tmp_path), "--top", "top"])
    assert r.returncode == 0, r.stdout + r.stderr


def test_direct_use_fail(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text(
        "module top(input clk, input id_bus, output reg q);\n"
        "  always @(posedge clk) q <= id_bus;\n"
        "endmodule\n"
    )
    r = _run([str(tmp_path), "--top", "top"])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "missing_async_synchroniser" in r.stdout


def test_with_waiver_pass(tmp_path):
    rtl = tmp_path / "top.v"
    rtl.write_text(
        "module top(input clk, input id_bus, output reg q);\n"
        "  always @(posedge clk) q <= id_bus;\n"
        "endmodule\n"
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "fpga_async_input_synchronizer_intentional":
            "id_bus is sourced from a clock-aligned BFM in this lab "
            "harness; production builds re-enable the synchronizer chain.",
    }))
    r = _run([str(tmp_path), "--top", "top", "--project", str(tmp_path)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout
