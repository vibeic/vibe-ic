#!/usr/bin/env python3
"""Tests for wake_pulse_emit_gated_by_first_rx_command_check.py
(Wave 18)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "wake_pulse_emit_gated_by_first_rx_command_check.py"
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


def test_with_first_cmd_gate_pass(tmp_path):
    _write_rtl(
        tmp_path,
        "wake_gen.sv",
        """\
module wake_gen(input logic clk, input logic rst_n,
                input logic have_received_id_cmd_latch,
                output logic wake_oe);
  logic [31:0] cnt;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        cnt <= 32'd0; wake_oe <= 1'b0;
    end else if (have_received_id_cmd_latch) begin
        // After first valid RX cmd, stop emitting forever.
        cnt <= 32'd0; wake_oe <= 1'b0;
    end else begin
        cnt <= cnt + 32'd1;
        if (cnt >= 32'd250000) wake_oe <= 1'b1;
    end
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout
    assert "have_received_id_cmd_latch" in r.stdout


def test_no_gate_fail(tmp_path):
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
        if (cnt >= 32'd250000) wake_oe <= 1'b1;
    end
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "NO_FIRST_CMD_GATE" in r.stdout


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


def test_data_flow_via_parent_instantiation_pass(tmp_path):
    """Wave 20 (v0.119.52): wake_gen has a generic `enable` port; the
    first-cmd evidence is at the instantiation site
    (`.enable(~awake_latch)`)."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "wake_gen.sv").write_text(
        """\
module wake_gen(input logic clk, input logic rst_n,
                input logic enable, input logic bus_active,
                output logic wake_oe);
  logic [31:0] cnt;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        cnt <= 32'd0; wake_oe <= 1'b0;
    end else if (!enable) begin
        cnt <= 32'd0; wake_oe <= 1'b0;
    end else begin
        cnt <= cnt + 32'd1;
        if (cnt >= 32'd250000) wake_oe <= 1'b1;
    end
  end
endmodule
"""
    )
    (rtl / "example_chip_top.sv").write_text(
        """\
module example_chip_top(input logic clk, input logic rst_n);
  wire awake_latch;
  // Other RTL omitted.
  wake_gen u_wake (
    .clk        (clk),
    .rst_n      (rst_n),
    .enable     (~awake_latch),
    .bus_active (1'b0),
    .wake_oe    ()
  );
endmodule
"""
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout
    assert "awake_latch" in r.stdout


def test_pre_awake_only_synonym_pass(tmp_path):
    """Wave 20 synonym: `pre_awake_only` should also match."""
    _write_rtl(
        tmp_path,
        "wake_gen.sv",
        """\
module wake_gen(input logic clk, input logic rst_n,
                input logic pre_awake_only,
                output logic wake_oe);
  logic [31:0] cnt;
  always_ff @(posedge clk) begin
    if (!pre_awake_only) wake_oe <= 1'b0;
    else cnt <= cnt + 1;
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout
    assert "pre_awake_only" in r.stdout


def test_wake_emit_enable_synonym_pass(tmp_path):
    _write_rtl(
        tmp_path,
        "wake_gen.sv",
        """\
module wake_gen(input logic clk, input logic rst_n,
                input logic wake_emit_enable,
                output logic wake_oe);
  logic [31:0] cnt;
  always_ff @(posedge clk) begin
    if (!wake_emit_enable) wake_oe <= 1'b0;
    else cnt <= cnt + 1;
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_with_waiver_pass(tmp_path):
    _write_rtl(
        tmp_path,
        "wake_gen.sv",
        """\
module wake_gen(input logic clk, input logic rst_n,
                input logic enable,
                output logic wake_oe);
  logic [31:0] cnt;
  always_ff @(posedge clk) cnt <= cnt + 32'd1;
  assign wake_oe = (cnt == 32'd250000);
endmodule
""",
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "wake_pulse_continuous_emit_intentional":
            "This chip is designed for continuous heartbeat per "
            "spec note 8.4 (always-on accessory bus, no handshake).",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVER" in r.stdout
