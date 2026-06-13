#!/usr/bin/env python3
"""Tests for tx_phy_bit_cell_total_consumed_check.py (Wave 15 Gate 1)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "tx_phy_bit_cell_total_consumed_check.py"
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


def test_full_cell_consumed_pass(tmp_path):
    """TX has BIT_CY param + bit_idx advance gates on BIT_CY → PASS."""
    _write_rtl(
        tmp_path,
        "rtl_constants_pkg.sv",
        """\
package rtl_constants_pkg;
  localparam int T_BIT_CELL_TX_TICKS = 500; // 10 us at 50 MHz
  localparam int T_HW0_LOW_TICKS     = 350;
  localparam int T_HW1_LOW_TICKS     = 75;
endpackage
""",
    )
    _write_rtl(
        tmp_path,
        "tx_phy.sv",
        """\
module tx_phy(input logic clk, input logic [2:0] tx_kind,
              output logic tx_done);
  import rtl_constants_pkg::*;
  logic [15:0] cnt;
  logic [3:0]  bit_idx;
  logic        in_low;
  always_ff @(posedge clk) begin
    if (in_low && cnt == T_HW0_LOW_TICKS) begin
        in_low <= 1'b0;
    end
    if (!in_low && cnt == T_BIT_CELL_TX_TICKS) begin
        bit_idx <= bit_idx + 4'd1;
        in_low  <= 1'b1;
        cnt     <= 16'd0;
    end
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_truncated_cell_fail(tmp_path):
    """TX advances bit_idx after only LOW + 200 ns gap → FAIL with file:line."""
    # No BIT_CY parameter declared anywhere AND TX uses literal 16'd10
    # for the inter-bit gap.
    _write_rtl(
        tmp_path,
        "main_fsm.sv",
        """\
module main_fsm(input logic clk);
  logic [15:0] gap_cnt;
  logic [3:0]  bit_idx;
  logic [1:0]  tx_kind;
  logic        tx_start;
  logic        tx_done;
  typedef enum logic [3:0] {S_IDLE, S_TX_BIT, S_TX_BIT_GAP} state_t;
  state_t state;
  always_ff @(posedge clk) begin
    case (state)
      S_TX_BIT: begin
        if (tx_done) begin
          bit_idx <= bit_idx + 4'd1;
          gap_cnt <= 16'd0;
          state   <= S_TX_BIT_GAP;
        end
      end
      S_TX_BIT_GAP: begin
        gap_cnt <= gap_cnt + 16'd1;
        if (gap_cnt + 16'd1 >= 16'd10) begin
          bit_idx  <= bit_idx + 4'd1;
          tx_start <= 1'b1;
          state    <= S_TX_BIT;
        end
      end
      default: state <= S_IDLE;
    endcase
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    # The file:line pointer must appear somewhere in the report.
    assert "main_fsm.sv:" in r.stdout


def test_no_bit_cy_param_fail(tmp_path):
    """TX has bit_idx advance + sane HW0/HW1 but NO BIT_CY-class param → FAIL."""
    _write_rtl(
        tmp_path,
        "tx_phy.sv",
        """\
module tx_phy(input logic clk);
  logic [15:0] cnt;
  logic [3:0]  bit_idx;
  logic        tx_start;
  logic        tx_done;
  // Only declares LOW pulse durations — no BIT_CY total cell.
  localparam int T_HW0_TX_TICKS = 350;
  localparam int T_HW1_TX_TICKS = 75;
  always_ff @(posedge clk) begin
    // No reference to a bit-cell total constant anywhere.
    if (tx_done) begin
        bit_idx <= bit_idx + 4'd1;
    end
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "MISSING_BIT_CELL_PARAM" in r.stdout


def test_with_waiver_pass(tmp_path):
    """Waiver ≥40 chars silences a real violation."""
    _write_rtl(
        tmp_path,
        "main_fsm.sv",
        """\
module main_fsm(input logic clk);
  logic [15:0] gap_cnt;
  logic [3:0]  bit_idx;
  logic        tx_done;
  always_ff @(posedge clk) begin
    if (tx_done) begin
      bit_idx <= bit_idx + 4'd1;
      gap_cnt <= 16'd0;
    end
    if (gap_cnt + 16'd1 >= 16'd10) begin
      bit_idx <= bit_idx + 4'd1;
    end
  end
endmodule
""",
    )
    (tmp_path / "waivers.json").write_text(
        json.dumps({
            "tx_bit_cell_intentionally_truncated":
                "Custom edge-only protocol with non-fixed cell duration; "
                "acknowledged by lab capture 2026-04-12.",
        })
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVER" in r.stdout


def test_no_tx_module_skip(tmp_path):
    """Project has no TX bit-emitter file → SKIP (return 0)."""
    _write_rtl(
        tmp_path,
        "alu.sv",
        """\
module alu(input logic [7:0] a, input logic [7:0] b, output logic [7:0] y);
  assign y = a + b;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "SKIP" in r.stdout


def test_short_waiver_does_not_silence(tmp_path):
    """Waiver under 40 chars does NOT silence the FAIL."""
    _write_rtl(
        tmp_path,
        "main_fsm.sv",
        """\
module main_fsm(input logic clk);
  logic [15:0] gap_cnt;
  logic [3:0]  bit_idx;
  logic        tx_done;
  always_ff @(posedge clk) begin
    if (gap_cnt + 16'd1 >= 16'd10) begin
      bit_idx <= bit_idx + 4'd1;
    end
  end
endmodule
""",
    )
    (tmp_path / "waivers.json").write_text(
        json.dumps({"tx_bit_cell_intentionally_truncated": "too short"})
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
