#!/usr/bin/env python3
"""Tests for rx_byte_assembler_ibt_flush_recovery_check.py (Wave 15 Gate 3)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "rx_byte_assembler_ibt_flush_recovery_check.py"
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


def test_recovery_path_present_pass(tmp_path):
    _write_rtl(
        tmp_path,
        "bit_assembler.sv",
        """\
module bit_assembler(input logic clk, input logic clr,
                     input logic rx_bit_vld, input logic rx_bit,
                     input logic ibt_overflow,
                     output logic rx_byte_vld);
  logic [3:0] bit_idx;
  logic [7:0] sr;
  always_ff @(posedge clk) begin
    rx_byte_vld <= 1'b0;
    if (clr) begin
        bit_idx <= 4'd0;
    end else if (ibt_overflow && bit_idx > 0 && bit_idx < 8) begin
        bit_idx <= 4'd0;
        sr      <= 8'd0;
    end else if (rx_bit_vld) begin
        sr <= {rx_bit, sr[7:1]};
        if (bit_idx == 4'd7) begin
            rx_byte_vld <= 1'b1;
            bit_idx <= 4'd0;
        end else begin
            bit_idx <= bit_idx + 4'd1;
        end
    end
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_no_recovery_fail(tmp_path):
    _write_rtl(
        tmp_path,
        "bit_assembler.sv",
        """\
module bit_assembler(input logic clk, input logic clr,
                     input logic rx_bit_vld, input logic rx_bit,
                     output logic rx_byte_vld);
  logic [3:0] bit_idx;
  logic [7:0] sr;
  always_ff @(posedge clk) begin
    rx_byte_vld <= 1'b0;
    if (clr) begin
        bit_idx <= 4'd0;
    end else if (rx_bit_vld) begin
        sr <= {rx_bit, sr[7:1]};
        if (bit_idx == 4'd7) begin
            rx_byte_vld <= 1'b1;
            bit_idx <= 4'd0;
        end else begin
            bit_idx <= bit_idx + 4'd1;
        end
    end
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "NO_IBT_FLUSH_PATH" in r.stdout


def test_with_waiver_pass(tmp_path):
    _write_rtl(
        tmp_path,
        "bit_assembler.sv",
        """\
module bit_assembler(input logic clk, input logic clr,
                     input logic rx_bit_vld, input logic rx_bit,
                     output logic rx_byte_vld);
  logic [3:0] bit_idx;
  logic [7:0] sr;
  always_ff @(posedge clk) begin
    rx_byte_vld <= 1'b0;
    if (clr) bit_idx <= 4'd0;
    else if (rx_bit_vld) begin
      if (bit_idx == 4'd7) begin
         rx_byte_vld <= 1'b1; bit_idx <= 4'd0;
      end else bit_idx <= bit_idx + 4'd1;
    end
  end
endmodule
""",
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "rx_partial_byte_recovery_skipped":
            "Frames are short and host re-sends on timeout; flush "
            "handled at higher protocol layer per design review.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


def test_no_assembler_skip(tmp_path):
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


def test_wave35_rx_br_flush_pass(tmp_path):
    """Wave 35: assembler that flushes bit_idx on `rx_br` (Break) is the
    canonical half-duplex EXAMPLE_PROTOCOL-class recovery; gate must accept rx_br as
    an IBT-class signal.
    """
    _write_rtl(
        tmp_path,
        "byte_assembler.sv",
        """\
module byte_assembler(
  input logic clk, rst_n,
  input logic rx_bit_valid, rx_bit, rx_br,
  output logic byte_valid, output logic [7:0] byte_data
);
  logic [3:0] bit_idx;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) bit_idx <= 4'd0;
    else begin
      byte_valid <= 1'b0;
      if (rx_br) begin
        bit_idx <= 4'd0;
      end else if (rx_bit_valid) begin
        if (bit_idx == 4'd7) begin
          byte_valid <= 1'b1; bit_idx <= 4'd0;
        end else bit_idx <= bit_idx + 4'd1;
      end
    end
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_wave35_tx_phy_excluded_skip(tmp_path):
    """Wave 35: tx_phy.sv files (TX-named) must be excluded from the
    bit-assembler heuristic even when they contain bit_idx + byte_valid.
    """
    _write_rtl(
        tmp_path,
        "tx_phy.sv",
        """\
module tx_phy(
  input logic clk, rst_n,
  input logic [7:0] tx_byte,
  input logic byte_valid,
  output logic id_bus_drive_low
);
  logic [3:0] bit_idx;
  always_ff @(posedge clk) begin
    if (!rst_n) bit_idx <= 4'd0;
    else if (byte_valid) bit_idx <= bit_idx + 4'd1;
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    # tx_phy is no longer counted; SKIP because no real assembler.
    assert "SKIP" in r.stdout
