#!/usr/bin/env python3
"""Tests for wake_gen_bus_active_reset_check.py (Wave 15 Gate 4)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "wake_gen_bus_active_reset_check.py"
)


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True,
        text=True,
    )


def _write_rtl(tmp_path: Path, name: str, body: str) -> None:
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(body)


def test_bus_gating_present_pass(tmp_path):
    _write_rtl(
        tmp_path,
        "wake_gen.sv",
        """\
module wake_gen(input logic clk, input logic rst_n,
                input logic bus_active,
                output logic wake_oe);
  logic [31:0] cnt;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        cnt <= 32'd0; wake_oe <= 1'b0;
    end else if (bus_active) begin
        cnt <= 32'd0; wake_oe <= 1'b0;
    end else begin
        cnt <= cnt + 32'd1;
        if (cnt >= 32'd250000) begin
            wake_oe <= 1'b1;
        end
    end
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_no_bus_gating_fail(tmp_path):
    _write_rtl(
        tmp_path,
        "wake_gen.sv",
        """\
module wake_gen(input logic clk, input logic rst_n,
                input logic enable,
                output logic wake_oe);
  logic [31:0] cnt;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        cnt <= 32'd0; wake_oe <= 1'b0;
    end else if (!enable) begin
        cnt <= 32'd0; wake_oe <= 1'b0;
    end else begin
        cnt <= cnt + 32'd1;
        if (cnt >= 32'd250000) begin
            wake_oe <= 1'b1;
        end
    end
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "NO_BUS_ACTIVE_GATING" in r.stdout


def test_with_waiver_pass(tmp_path):
    _write_rtl(
        tmp_path,
        "wake_gen.sv",
        """\
module wake_gen(input logic clk, input logic rst_n, input logic enable,
                output logic wake_oe);
  logic [31:0] cnt;
  always_ff @(posedge clk) cnt <= cnt + 32'd1;
  assign wake_oe = (cnt == 32'd250000);
endmodule
""",
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "wake_pulse_collision_acceptable":
            "Wake collisions filtered out by external pull-up bias "
            "and tester firmware tolerates them per spec note 4.7.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


def test_no_wake_module_skip(tmp_path):
    _write_rtl(
        tmp_path,
        "alu.sv",
        """\
module alu(input logic [7:0] a, output logic [7:0] y);
  assign y = a + 1;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "SKIP" in r.stdout
