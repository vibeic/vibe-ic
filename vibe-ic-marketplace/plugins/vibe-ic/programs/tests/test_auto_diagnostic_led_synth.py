#!/usr/bin/env python3
"""Tests for auto_diagnostic_led_synth.py"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
import pytest

PROG = Path(__file__).resolve().parent.parent / "auto_diagnostic_led_synth.py"

def _run(args: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG)] + args, capture_output=True, text=True, **kw)

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0

def test_no_fpga_wrapper(tmp_path):
    (tmp_path / "top.v").write_text("module top; endmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 0

def test_with_fsm_and_leds(tmp_path):
    rtl = tmp_path / "chip_fpga_top.v"
    rtl.write_text("module chip_fpga_top(\n    input MAX10_CLK1_50,\n    output [9:0] LEDR\n);\n    reg [3:0] state;\n    localparam S_IDLE = 4'd0, S_RUN = 4'd1, S_DONE = 4'd2;\n    always @(posedge MAX10_CLK1_50) begin\n        case (state)\n            S_IDLE: state <= S_RUN;\n            S_RUN:  state <= S_DONE;\n            S_DONE: state <= S_IDLE;\n        endcase\n    end\n    assign LEDR[0] = 1'b0;\nendmodule\n")
    r = _run([str(tmp_path)])
    assert r.returncode == 0


# --- the verdict-to-EXIT-CODE mapping, which nothing above measures ---------
#
# Every test above asserts `returncode == 0`, and this program's contract is
# "exit 0 always (advisory tool, never fails CI)" — so all three stay green
# when `main()` is replaced by `return 0`. `gate_cli_mutation_probe` measured
# exactly that and reported SILENT: the flow reads this program's EXIT CODE
# (`advisory_program_exit_zero`, cwd = the project, `--out-dir reports/...`),
# and nothing here drove that mapping.
#
# "Advisory" does not mean "has no refusal". It has exactly one, and it is the
# only content-earned non-zero this program can produce: an unreadable
# `project_dir` returns 2 rather than emitting a proposal about a project that
# is not there. That is the input it should refuse, so that is what is asserted
# — as a subprocess, on the exit code, not on the return value of a call.

def test_a_missing_project_dir_is_REFUSED_with_a_non_zero_exit_code(tmp_path):
    absent = tmp_path / "no_such_project"
    r = _run([str(absent)])
    assert r.returncode == 2, (
        "an unreadable project_dir must be refused through the exit code the "
        "flow reads, not merely reported on stdout; got rc=%d\n%s%s"
        % (r.returncode, r.stdout, r.stderr))
    assert "project_dir not found" in r.stderr


def test_the_flow_invocation_shape_emits_the_proposal_and_exits_zero(tmp_path):
    """cwd = the project, `.` as project_dir, a RELATIVE --out-dir — the exact
    argv the `advisory_program_exit_zero` clause uses. A proposal that is
    silently not written still exits 0, so the artifacts are asserted too."""
    (tmp_path / "chip_fpga_top.v").write_text(
        "module chip_fpga_top(\n"
        "    input MAX10_CLK1_50,\n"
        "    output [9:0] LEDR\n"
        ");\n"
        "    reg [3:0] ctrl_state;\n"
        "    localparam S_IDLE = 4'd0, S_RUN = 4'd1;\n"
        "    always @(posedge MAX10_CLK1_50)\n"
        "        ctrl_state <= ctrl_state + 1'b1;\n"
        "    assign LEDR[0] = 1'b0;\n"
        "endmodule\n")
    out_rel = "reports/phase2/fpga/led_synth"
    r = _run([".", "--out-dir", out_rel], cwd=str(tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    out_dir = tmp_path / out_rel
    patch = out_dir / "led_synth_proposal.patch"
    md = out_dir / "led_synth_proposal.md"
    assert patch.is_file() and md.is_file(), (
        "the clause runs this to EMIT; exit 0 with no proposal on disk is the "
        "shape that reads as a pass and produced nothing:\n" + r.stdout + r.stderr)
    assert "ctrl_state" in patch.read_text()
