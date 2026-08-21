#!/usr/bin/env python3
"""Tests for rx_last_bit_frame_end_commit_check.py — Wave 29 PRIMARY."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "rx_last_bit_frame_end_commit_check.py")


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, **kw)


def _make(tmp_path: Path,
          rtl: dict[str, str] | None = None,
          waiver: str | None = None) -> Path:
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    if rtl:
        (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True, exist_ok=True)
        for name, body in rtl.items():
            (proj / "phase2" / "stage1" / "rtl" / name).write_text(body)
    if waiver is not None:
        (proj / "waivers.json").write_text(json.dumps(
            {"rx_last_bit_loss_intentional": waiver}))
    return proj


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


# ----- next-edge classify, NO commit  → FAIL  (the v0.119.59 bug) -----
NEXT_EDGE_NO_COMMIT_RTL = """\
module main_fsm(input clk, input rx_low, input rx_high);
  reg [3:0] bit_idx;
  reg [7:0] byte_buf [0:7];
  reg [7:0] shift_byte;
  reg [11:0] high_cnt, low_cnt;
  reg [4:0] state;
  localparam S_RX_LOW = 5'd1, S_RX_HIGH = 5'd2,
             S_RX_FRAME_END = 5'd3, S_VALIDATE = 5'd4;
  always @(posedge clk) begin
    case (state)
      S_RX_LOW: begin
        if (rx_low) low_cnt <= low_cnt + 1;
      end
      S_RX_HIGH: begin
        if (rx_low) begin
          // classify previous LOW pulse based on low_cnt
          if (low_cnt < 12'd100) shift_byte[bit_idx] <= 1'b1;
          else                   shift_byte[bit_idx] <= 1'b0;
          bit_idx <= bit_idx + 1;
        end
      end
      S_RX_FRAME_END: begin
        // BUG: no commit of in-progress bit
        high_cnt <= 0;
        state <= S_VALIDATE;
      end
      S_VALIDATE: begin
        // CRC check
      end
    endcase
  end
endmodule
"""


def test_next_edge_no_commit_fail(tmp_path):
    """v0.119.59 bug case: next-edge classify, no frame-end commit."""
    proj = _make(tmp_path,
                 rtl={"main_fsm.sv": NEXT_EDGE_NO_COMMIT_RTL})
    r = _run([str(proj)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "RX_LAST_BIT_FRAME_END_COMMIT_MISSING" in r.stdout


# ----- next-edge classify WITH frame-end commit → PASS (Pattern B) ----
NEXT_EDGE_WITH_COMMIT_RTL = """\
module main_fsm(input clk, input rx_low, input rx_high);
  reg [3:0] bit_idx;
  reg [7:0] byte_buf [0:7];
  reg [7:0] shift_byte;
  reg [11:0] high_cnt, low_cnt;
  reg last_classified_bit;
  reg [4:0] state;
  localparam S_RX_LOW = 5'd1, S_RX_HIGH = 5'd2,
             S_RX_FRAME_END = 5'd3, S_VALIDATE = 5'd4;
  always @(posedge clk) begin
    case (state)
      S_RX_LOW: begin
        if (rx_low) low_cnt <= low_cnt + 1;
      end
      S_RX_HIGH: begin
        if (rx_low) begin
          if (low_cnt < 12'd100) begin
            shift_byte[bit_idx] <= 1'b1;
            last_classified_bit <= 1'b1;
          end else begin
            shift_byte[bit_idx] <= 1'b0;
            last_classified_bit <= 1'b0;
          end
          bit_idx <= bit_idx + 1;
        end
      end
      S_RX_FRAME_END: begin
        // Pattern B — commit pending bit before validate
        if (bit_idx > 0) shift_byte[bit_idx-1] <= last_classified_bit;
        state <= S_VALIDATE;
      end
      S_VALIDATE: begin
      end
    endcase
  end
endmodule
"""


def test_next_edge_with_commit_pass(tmp_path):
    proj = _make(tmp_path,
                 rtl={"main_fsm.sv": NEXT_EDGE_WITH_COMMIT_RTL})
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# ----- rising-edge classify (Pattern A) → PASS -----
RISING_EDGE_RTL = """\
module main_fsm(input clk, input rx_low, input rx_high,
                input rx_high_edge);
  reg [3:0] bit_idx;
  reg [7:0] byte_buf [0:7];
  reg [7:0] shift_byte;
  reg [11:0] low_cnt;
  reg [4:0] state;
  localparam S_RX_LOW = 5'd1, S_RX_HIGH = 5'd2,
             S_RX_FRAME_END = 5'd3, S_VALIDATE = 5'd4;
  always @(posedge clk) begin
    case (state)
      S_RX_LOW: begin
        if (rx_high) begin
          // LOW pulse just ended; classify NOW
          if (low_cnt < 12'd100) shift_byte[bit_idx] <= 1'b1;
          else                   shift_byte[bit_idx] <= 1'b0;
          bit_idx <= bit_idx + 1;
          state <= S_RX_HIGH;
        end
      end
      S_RX_HIGH: begin
        if (rx_low) state <= S_RX_LOW;
      end
      S_RX_FRAME_END: begin
        state <= S_VALIDATE;
      end
      S_VALIDATE: begin
      end
    endcase
  end
endmodule
"""


def test_rising_edge_classify_pass(tmp_path):
    """Pattern A — vendor style, classification on rising edge."""
    proj = _make(tmp_path, rtl={"main_fsm.sv": RISING_EDGE_RTL})
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# ----- waiver path -----
def test_with_waiver_pass(tmp_path):
    proj = _make(tmp_path, rtl={"main_fsm.sv": NEXT_EDGE_NO_COMMIT_RTL},
                 waiver=("RX path classified next-edge with no frame-end "
                         "commit; intentional for unit-test fixture (≥40 chars)"))
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout


# ----- no RX FSM → SKIP -----
def test_no_rx_fsm_skip(tmp_path):
    rtl = {"adder.v": """\
module adder(input [7:0] a, b, output [7:0] s);
  assign s = a + b;
endmodule
"""}
    proj = _make(tmp_path, rtl=rtl)
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_SKIP" in r.stdout
