"""Tests for dispatcher_tx_arm_order_check.py (R6)."""
from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "dispatcher_tx_arm_order_check.py"

PASS_ARM_SEPARATE_STATE = textwrap.dedent("""\
    module dispatcher(input clk, input rst_n);
      reg [2:0] state;
      reg [7:0] tx_byte;
      reg tx_arm;
      localparam S_IDLE = 0, S_LOAD = 1, S_TX = 2;
      always @(posedge clk) begin
        if (!rst_n) begin
          state <= S_IDLE;
          tx_arm <= 0;
          tx_byte <= 0;
        end else begin
          case (state)
            S_IDLE: begin
              tx_arm <= 0;
              state <= S_LOAD;
            end
            S_LOAD: begin
              tx_byte <= 8'hAB;
              state <= S_TX;
            end
            S_TX: begin
              tx_arm <= 1;
              state <= S_IDLE;
            end
          endcase
        end
      end
    endmodule
""")

PASS_NO_TX_ARM = textwrap.dedent("""\
    module simple_counter(input clk, input rst_n);
      reg [7:0] cnt;
      always @(posedge clk) begin
        if (!rst_n) cnt <= 0;
        else cnt <= cnt + 1;
      end
    endmodule
""")

FAIL_ARM_SAME_STATE = textwrap.dedent("""\
    module dispatcher(input clk, input rst_n);
      reg [2:0] state;
      reg [7:0] tx_byte;
      reg tx_arm;
      localparam S_IDLE = 0, S_TX = 1;
      always @(posedge clk) begin
        if (!rst_n) begin
          state <= S_IDLE;
          tx_arm <= 0;
        end else begin
          case (state)
            S_IDLE: begin
              state <= S_TX;
            end
            S_TX: begin
              tx_byte <= 8'hCD;
              tx_arm <= 1;
              state <= S_IDLE;
            end
          endcase
        end
      end
    endmodule
""")

FAIL_ARM_BEFORE_DATA = textwrap.dedent("""\
    module dispatcher(input clk, input rst_n);
      reg [2:0] state;
      reg [7:0] tx_data;
      reg tx_start;
      localparam S_IDLE = 0, S_SEND = 1;
      always @(posedge clk) begin
        if (!rst_n) begin
          state <= S_IDLE;
          tx_start <= 0;
        end else begin
          case (state)
            S_IDLE: begin
              state <= S_SEND;
            end
            S_SEND: begin
              tx_start <= 1;
              tx_data <= 8'hEF;
              state <= S_IDLE;
            end
          endcase
        end
      end
    endmodule
""")

PASS_SILENCED = textwrap.dedent("""\
    module dispatcher(input clk, input rst_n);
      reg [2:0] state;
      reg [7:0] tx_byte;
      reg tx_arm;
      localparam S_IDLE = 0, S_TX = 1;
      always @(posedge clk) begin
        if (!rst_n) begin
          state <= S_IDLE;
        end else begin
          case (state)
            S_IDLE: state <= S_TX;
            S_TX: begin
              tx_byte <= 8'hAA;
              tx_arm <= 1; // tx-arm-order-ok
              state <= S_IDLE;
            end
          endcase
        end
      end
    endmodule
""")

FAIL_NO_CASE = textwrap.dedent("""\
    module raw_driver(input clk, input rst_n, input go);
      reg [7:0] tx_byte;
      reg tx_arm;
      always @(posedge clk) begin
        if (!rst_n) begin
          tx_arm <= 0;
          tx_byte <= 0;
        end else if (go) begin
          tx_byte <= 8'hFF;
          tx_arm <= 1;
        end
      end
    endmodule
""")


def _run(tmp_path: Path, *rtl_files: tuple[str, str], extra_args=()) -> subprocess.CompletedProcess:
    for name, content in rtl_files:
        (tmp_path / name).write_text(content)
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", *extra_args],
        capture_output=True, text=True,
    )


def test_pass_arm_in_separate_state(tmp_path):
    r = _run(tmp_path, ("dispatch.v", PASS_ARM_SEPARATE_STATE))
    assert r.returncode == 0
    assert '"verdict": "PASS"' in r.stdout


def test_pass_no_tx_arm(tmp_path):
    r = _run(tmp_path, ("counter.v", PASS_NO_TX_ARM))
    assert r.returncode == 0
    assert '"verdict": "PASS"' in r.stdout


def test_fail_arm_same_state_as_data(tmp_path):
    r = _run(tmp_path, ("dispatch.v", FAIL_ARM_SAME_STATE))
    assert r.returncode == 1
    assert '"verdict": "FAIL"' in r.stdout
    assert "tx_arm_data_same_state" in r.stdout


def test_fail_arm_before_data(tmp_path):
    r = _run(tmp_path, ("dispatch.v", FAIL_ARM_BEFORE_DATA))
    assert r.returncode == 1
    assert '"verdict": "FAIL"' in r.stdout
    assert "tx_start" in r.stdout


def test_no_files_exit2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json"],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


def test_nonexistent_dir():
    r = subprocess.run(
        [sys.executable, str(PROG), "/nonexistent_xyzzy", "--json"],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


def test_help():
    r = subprocess.run(
        [sys.executable, str(PROG), "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "arm" in r.stdout.lower() or "tx" in r.stdout.lower()


def test_pass_silenced(tmp_path):
    r = _run(tmp_path, ("dispatch.v", PASS_SILENCED))
    assert r.returncode == 0
    assert '"verdict": "PASS"' in r.stdout


def test_fail_no_case_structure(tmp_path):
    r = _run(tmp_path, ("raw.v", FAIL_NO_CASE))
    assert r.returncode == 1
    assert '"verdict": "FAIL"' in r.stdout
    assert "tx_arm_data_same_block" in r.stdout
