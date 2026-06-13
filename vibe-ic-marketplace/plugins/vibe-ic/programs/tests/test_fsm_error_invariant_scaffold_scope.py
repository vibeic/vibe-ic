#!/usr/bin/env python3
"""v0.1.62 — fsm_error_invariant must audit DESIGN RTL only, not generated
test/BIST/FPGA scaffolding. spm FAILed because the gate scanned
phase2/stage1/fpga/spm_fpga_bist.v whose `fail_r` latch is by-design.
"""
from __future__ import annotations
import subprocess, sys
from pathlib import Path
PROG = Path(__file__).resolve().parent.parent / "fsm_error_invariant.py"


def _run(target):
    return subprocess.run([sys.executable, str(PROG), str(target)],
                          capture_output=True, text=True)


_BIST = """module spm_fpga_bist(input clk, output reg fail_r);
reg [1:0] st;
always @(posedge clk) begin
  case (st)
    2'd0: st <= 2'd1;          // S_IDLE
    2'd1: begin fail_r <= 1'b1; st <= 2'd2; end  // S_NEXT
  endcase
end
endmodule
"""

_CLEAN = """module spm(input clk, input rst, input [31:0] x, input y, output reg p);
always @(posedge clk) p <= y;
endmodule
"""


def test_excludes_fpga_bist_scaffold(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"; rtl.mkdir(parents=True)
    (rtl / "spm.v").write_text(_CLEAN)
    fpga = tmp_path / "phase2" / "stage1" / "fpga"; fpga.mkdir(parents=True)
    (fpga / "spm_fpga_bist.v").write_text(_BIST)
    r = _run(tmp_path)
    assert "0 error-assertion sites found" in r.stdout, r.stdout
    assert r.returncode == 0


def test_bist_filename_excluded_even_outside_fpga_dir(tmp_path):
    rtl = tmp_path / "rtl"; rtl.mkdir(parents=True)
    (rtl / "core.v").write_text(_CLEAN.replace("spm", "core"))
    (rtl / "core_bist.v").write_text(_BIST.replace("spm_fpga_bist", "core_bist"))
    r = _run(tmp_path)
    assert "0 error-assertion sites found" in r.stdout, r.stdout


def test_real_design_error_site_still_flagged(tmp_path):
    # a genuine design-RTL error latch (not scaffolding) is still reported
    rtl = tmp_path / "phase2" / "stage1" / "rtl"; rtl.mkdir(parents=True)
    (rtl / "mac.v").write_text(
        "module mac(input clk, output reg rx_error);\n"
        "reg [1:0] st;\n"
        "always @(posedge clk) case(st)\n"
        "  2'd1: begin rx_error <= 1'b1; st <= 2'd2; end // S_DECODE\n"
        "endcase\nendmodule\n")
    r = _run(tmp_path)
    assert "error-assertion sites found" in r.stdout
    # at least one site flagged (returncode 1)
    assert r.returncode == 1
