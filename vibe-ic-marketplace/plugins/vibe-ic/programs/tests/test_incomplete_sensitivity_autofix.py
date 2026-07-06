#!/usr/bin/env python3
"""test_incomplete_sensitivity_autofix.py — pins the `--fix` for
rule_incomplete_sensitivity: a combinational `always @(<explicit list>)` whose body
reads an unlisted signal is rewritten to `always @(*)` (value-preserving), while
complete-list and edge-triggered blocks are left untouched.

Distilled from a combinational multi-block divider (RTLLM div_16bit class): the
second `always @(A or B)` read intermediate regs written by the first block, an
order-dependent stale-read RACE that failed 50/100 TB vectors; rewriting only that
block's list to `@(*)` recovers it. General, chip-AGNOSTIC.
"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINT = HERE.parent / "rtl_hygiene_lint.py"


def _fix(tmp_path, text):
    f = tmp_path / "dut.v"
    f.write_text(text)
    r = subprocess.run([sys.executable, str(LINT), "--fix", str(f)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return f.read_text(), r.stdout


def test_incomplete_block_rewritten_to_star(tmp_path):
    # Second block reads a_reg/b_reg (NOT in its @(A or B) list) -> the race.
    out, log = _fix(tmp_path, (
        "module t(input [3:0] A, input [3:0] B, output reg [3:0] q);\n"
        "  reg [3:0] a_reg, b_reg;\n"
        "  always @(A or B) begin a_reg = A; b_reg = B; end\n"
        "  always @(A or B) begin q = a_reg + b_reg; end\n"
        "endmodule\n"))
    # The FIRST block reads only A/B (both listed) -> left alone.
    assert "always @(A or B) begin a_reg = A; b_reg = B; end" in out
    # The SECOND block (reads unlisted a_reg/b_reg) -> rewritten to @(*).
    assert "always @(*) begin q = a_reg + b_reg; end" in out
    assert "rewrote 1 incomplete sensitivity list" in log


def test_complete_list_untouched(tmp_path):
    # Everything the block reads is listed -> no false-positive rewrite.
    src = ("module t(input a, input b, output reg y);\n"
           "  always @(a or b) y = a & b;\n"
           "endmodule\n")
    out, log = _fix(tmp_path, src)
    assert "always @(a or b)" in out
    assert "@(*)" not in out
    assert "rewrote 0 incomplete sensitivity list" in log


def test_edge_block_untouched(tmp_path):
    # A clocked block is exempt even if it reads an unlisted signal.
    src = ("module t(input clk, input d, input e, output reg q);\n"
           "  always @(posedge clk) q <= d & e;\n"
           "endmodule\n")
    out, _ = _fix(tmp_path, src)
    assert "always @(posedge clk)" in out
    assert "@(*)" not in out
