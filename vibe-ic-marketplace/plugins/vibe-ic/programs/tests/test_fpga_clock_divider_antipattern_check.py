#!/usr/bin/env python3
"""Tests for fpga_clock_divider_antipattern_check.py (LL-27).

The gate catches the FPGA toggle-divider antipattern surfaced by the
v0.119.22 vendor benchmark: a register output used as a clock without
a corresponding create_generated_clock SDC entry. General — works on
any FPGA project (Quartus / Vivado / Lattice).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "fpga_clock_divider_antipattern_check.py"


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True, text=True,
    )


def _make_fpga_project(tmp_path: Path):
    """Create the FPGA-flow markers (.qsf empty file) so the gate engages."""
    (tmp_path / "fpga_proj.qsf").write_text("# Quartus settings\n")


def _write_rtl(tmp_path: Path, body: str, name: str = "fpga_top.sv"):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(body)


def test_silent_skip_when_no_fpga(tmp_path):
    """No .qsf/.xdc/.qpf → ASIC project → silent skip (no false alert
    on pure-ASIC RTL that might legitimately use derived clocks under
    a different constraints flow)."""
    _write_rtl(tmp_path, """\
module top(input osc);
  logic clk_div;
  always_ff @(posedge osc) clk_div <= ~clk_div;
  always_ff @(posedge clk_div) ;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "not an FPGA project" in r.stdout


def test_silent_skip_no_rtl(tmp_path):
    _make_fpga_project(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0


def test_fail_toggle_divider_no_sdc(tmp_path):
    """The actual vendor failure mode: clk_5m toggle-divider used as
    posedge clock with no SDC entry → FAIL."""
    _make_fpga_project(tmp_path)
    _write_rtl(tmp_path, """\
module fpga_top(input MAX10_CLK1_50);
  logic [3:0] clk_div_cnt;
  logic       clk_5m;
  always_ff @(posedge MAX10_CLK1_50) begin
    if (clk_div_cnt == 4'd9) begin
      clk_div_cnt <= 4'd0;
      clk_5m      <= ~clk_5m;
    end else begin
      clk_div_cnt <= clk_div_cnt + 1'b1;
    end
  end
  always_ff @(posedge clk_5m) ;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "clk_5m" in r.stdout
    assert "FAIL" in r.stdout


def test_pass_when_sdc_constrains_derived_clock(tmp_path):
    """Toggle divider IS present, but a create_generated_clock entry
    in an .sdc file references it → designer knows what they're doing,
    constraint is in place → PASS."""
    _make_fpga_project(tmp_path)
    _write_rtl(tmp_path, """\
module fpga_top(input MAX10_CLK1_50);
  logic clk_5m;
  always_ff @(posedge MAX10_CLK1_50) clk_5m <= ~clk_5m;
  always_ff @(posedge clk_5m) ;
endmodule
""")
    (tmp_path / "fpga_top.sdc").write_text(
        "create_clock -name MAX10_CLK1_50 -period 20.0 [get_ports MAX10_CLK1_50]\n"
        "create_generated_clock -name clk_5m -source [get_ports MAX10_CLK1_50] "
        "-divide_by 10 [get_registers {clk_5m}]\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_pass_when_top_input_used_as_clock(tmp_path):
    """`always_ff @(posedge MAX10_CLK1_50)` where MAX10_CLK1_50 is a
    top-level input port — that's the master clock, NOT a derived
    clock. Gate must not flag it."""
    _make_fpga_project(tmp_path)
    _write_rtl(tmp_path, """\
module fpga_top(input MAX10_CLK1_50, output reg q);
  always_ff @(posedge MAX10_CLK1_50) q <= ~q;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_fail_counter_bit_clock(tmp_path):
    """Variant: derived clock built by assigning a counter bit to a
    signal then using it as posedge. Same antipattern."""
    _make_fpga_project(tmp_path)
    _write_rtl(tmp_path, """\
module fpga_top(input MAX10_CLK1_50);
  logic [9:0] cnt;
  logic       slow_clk;
  always_ff @(posedge MAX10_CLK1_50) cnt <= cnt + 1'b1;
  assign slow_clk = cnt[9];
  always_ff @(posedge slow_clk) ;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "slow_clk" in r.stdout


def test_pass_with_waiver(tmp_path):
    _make_fpga_project(tmp_path)
    _write_rtl(tmp_path, """\
module fpga_top(input MAX10_CLK1_50);
  logic clk_div;
  always_ff @(posedge MAX10_CLK1_50) clk_div <= ~clk_div;
  always_ff @(posedge clk_div) ;
endmodule
""")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "clock_divider_antipattern_intentional":
            "Pattern is intentional for power-down test only; STA verified by "
            "vendor IP report attached as evidence/sta_report.txt",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "WAIVER" in r.stdout


def test_short_waiver_rejected(tmp_path):
    """Anti-rubber-stamp: waiver < 20 chars rejected."""
    _make_fpga_project(tmp_path)
    _write_rtl(tmp_path, """\
module fpga_top(input MAX10_CLK1_50);
  logic clk_div;
  always_ff @(posedge MAX10_CLK1_50) clk_div <= ~clk_div;
  always_ff @(posedge clk_div) ;
endmodule
""")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "clock_divider_antipattern_intentional": "needed",
    }))
    r = _run(tmp_path)
    assert r.returncode == 1, "rubber-stamp waiver must NOT pass"


def test_no_false_alert_pll_output(tmp_path):
    """Negative: derived clock generated by an instantiated PLL block
    (no toggle, no counter-bit assign) must NOT trigger. The gate
    only flags the toggle-register / counter-bit antipattern."""
    _make_fpga_project(tmp_path)
    _write_rtl(tmp_path, """\
module fpga_top(input MAX10_CLK1_50);
  logic pll_out_clk;
  altpll u_pll (.inclk0(MAX10_CLK1_50), .c0(pll_out_clk));
  always_ff @(posedge pll_out_clk) ;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_xdc_vivado_form_recognised(tmp_path):
    """Generality: Vivado uses .xdc with the same create_generated_clock
    syntax. The gate must accept either."""
    (tmp_path / "fpga_proj.tcl").write_text("# Vivado script\n")
    _write_rtl(tmp_path, """\
module fpga_top(input sys_clk);
  logic clk_div;
  always_ff @(posedge sys_clk) clk_div <= ~clk_div;
  always_ff @(posedge clk_div) ;
endmodule
""")
    (tmp_path / "fpga_top.xdc").write_text(
        "create_generated_clock -name clk_div -source [get_ports sys_clk] "
        "-divide_by 2 [get_pins clk_div_reg/Q]\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
