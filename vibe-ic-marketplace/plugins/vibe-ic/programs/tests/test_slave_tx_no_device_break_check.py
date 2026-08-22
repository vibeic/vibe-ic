#!/usr/bin/env python3
"""Tests for slave_tx_no_device_break_check.py (Wave 25)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "slave_tx_no_device_break_check.py"
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


def test_no_device_br_pass(tmp_path):
    # Vendor PASS-oracle pattern: turnaround → TX_BIT directly,
    # no BR-emit state.
    _write_rtl(
        tmp_path,
        "main_fsm.sv",
        """
module main_fsm(input clk, input rst_n);
  typedef enum {
    S_IDLE, S_RX_LOW, S_RX_DONE, S_VALIDATE, S_WAIT_TURN,
    S_TX_BIT, S_TX_IBT, S_DONE
  } state_t;
  state_t state;
  always_ff @(posedge clk) begin
    case (state)
      S_RX_DONE: state <= S_VALIDATE;
      S_VALIDATE: state <= S_WAIT_TURN;
      S_WAIT_TURN: begin
        if (gap_cnt < T_TSRS_MIN_TICKS) gap_cnt <= gap_cnt + 1;
        else state <= S_TX_BIT;
      end
      S_TX_BIT: begin
        id_tx_oe <= (cnt < tx_low_width);
        // ... bit cell logic
      end
    endcase
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout


def test_device_br_state_fail(tmp_path):
    # The v0.119.56 anti-pattern: S_TX_BR drives LOW for
    # T_TWK_BR_TX_TICKS before the first TX_BIT.
    _write_rtl(
        tmp_path,
        "main_fsm.sv",
        """
module main_fsm(input clk, input rst_n);
  localparam int T_TWK_BR_TX_TICKS = 1200;
  localparam int T_TSRS_MIN_TICKS  = 1000;
  typedef enum {
    S_IDLE, S_RX_LOW, S_RX_DONE, S_WAIT_TURN, S_TX_BR,
    S_TX_BIT, S_TX_IBT
  } state_t;
  state_t state;
  always_ff @(posedge clk) begin
    case (state)
      S_WAIT_TURN: begin
        if (gap_cnt < T_TSRS_MIN_TICKS) gap_cnt <= gap_cnt + 1;
        else begin
          id_tx_oe <= 1'b1;
          state <= S_TX_BR;
        end
      end
      S_TX_BR: begin
        id_tx_oe <= 1'b1;
        if (cnt < T_TWK_BR_TX_TICKS) cnt <= cnt + 1;
        else begin
          state <= S_TX_BIT;
        end
      end
      S_TX_BIT: begin
        id_tx_oe <= (cnt < tx_low_width);
      end
    endcase
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "SLAVE_TX_DEVICE_BREAK_PRESENT" in r.stdout
    assert "S_TX_BR" in r.stdout
    assert "T_TWK_BR_TX_TICKS" in r.stdout


def test_short_low_burst_pass(tmp_path):
    # Brief LOW pulse during turnaround that's < BR_MIN — settle
    # constants like T_SETTLE_TICKS / fixed 30-tick literal — must
    # NOT trip the gate (no BR_MIN-class constant referenced).
    _write_rtl(
        tmp_path,
        "main_fsm.sv",
        """
module main_fsm(input clk, input rst_n);
  localparam int T_SETTLE_TICKS = 30;
  typedef enum {
    S_IDLE, S_RX_DONE, S_WAIT_TURN, S_TX_SETTLE,
    S_TX_BIT
  } state_t;
  state_t state;
  always_ff @(posedge clk) begin
    case (state)
      S_WAIT_TURN: state <= S_TX_SETTLE;
      S_TX_SETTLE: begin
        // Short driver-warmup pulse — NOT a BR_MIN counter.
        id_tx_oe <= 1'b1;
        if (cnt < T_SETTLE_TICKS) cnt <= cnt + 1;
        else state <= S_TX_BIT;
      end
      S_TX_BIT: begin
        id_tx_oe <= (cnt < tx_low_width);
      end
    endcase
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_with_waiver_pass(tmp_path):
    # Same FAIL pattern as test_device_br_state_fail, silenced by
    # a valid ≥40-char waiver.
    _write_rtl(
        tmp_path,
        "main_fsm.sv",
        """
module main_fsm(input clk);
  localparam int T_TWK_BR_TX_TICKS = 1200;
  typedef enum { S_WAIT_TURN, S_TX_BR, S_TX_BIT } state_t;
  state_t state;
  always_ff @(posedge clk) begin
    case (state)
      S_WAIT_TURN: state <= S_TX_BR;
      S_TX_BR: begin
        id_tx_oe <= 1'b1;
        if (cnt < T_TWK_BR_TX_TICKS) cnt <= cnt + 1;
        else state <= S_TX_BIT;
      end
      S_TX_BIT: id_tx_oe <= 1'b0;
    endcase
  end
endmodule
""",
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "slave_tx_break_intentional":
            "Custom protocol variant where DUT issues a leading break "
            "to assert framing alignment; documented in vendor spec "
            "section 7.4.2 with explicit host firmware support.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVER" in r.stdout


def test_v0119_64_pattern_fail(tmp_path):
    """Wave 33 regression: v0.119.64 escape — `tx_oe_low` LHS +
    `T_TB_TICKS` constant. The Wave 25 narrow regex missed both."""
    _write_rtl(
        tmp_path,
        "chip_top.sv",
        """
module chip_top(input clk);
  localparam int T_TB_TICKS = 690;
  typedef enum {
    S_RX_DONE, S_VALIDATE, S_WAIT_TURN,
    S_TX_BR, S_TX_BR_END, S_TX_BIT_LOW, S_TX_BIT_HIGH
  } state_t;
  state_t state;
  logic tx_oe_low;
  logic [15:0] tx_cnt;
  always_ff @(posedge clk) begin
    case (state)
      S_WAIT_TURN: begin
        tx_oe_low <= 1'b1;
        state     <= S_TX_BR;
      end
      S_TX_BR: begin
        tx_oe_low <= 1'b1;
        if (tx_cnt + 16'd1 >= T_TB_TICKS[15:0]) begin
          state     <= S_TX_BR_END;
          tx_oe_low <= 1'b0;
        end
      end
      S_TX_BIT_LOW: tx_oe_low <= 1'b1;
    endcase
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "SLAVE_TX_DEVICE_BREAK_PRESENT" in r.stdout
    assert "S_TX_BR" in r.stdout
    assert "T_TB_TICKS" in r.stdout


def test_synonym_oe_low_fail(tmp_path):
    """Wave 33: various LOW-driver naming patterns must trip the
    gate. `id_tx_oe_low`, `bus_drive_low`, `pad_oe_low`."""
    _write_rtl(
        tmp_path,
        "main_fsm.sv",
        """
module main_fsm(input clk);
  localparam int T_BREAK_LEN = 1024;
  typedef enum { S_WAIT_TURN, S_LEADING_BR, S_TX_BIT } state_t;
  state_t state;
  logic id_tx_oe_low;
  logic [15:0] cnt;
  always_ff @(posedge clk) begin
    case (state)
      S_WAIT_TURN: state <= S_LEADING_BR;
      S_LEADING_BR: begin
        id_tx_oe_low <= 1'b1;
        if (cnt >= T_BREAK_LEN) state <= S_TX_BIT;
      end
      S_TX_BIT: id_tx_oe_low <= 1'b0;
    endcase
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "SLAVE_TX_DEVICE_BREAK_PRESENT" in r.stdout
    assert "S_LEADING_BR" in r.stdout


def test_synonym_br_const_fail(tmp_path):
    """Wave 33: BR_MIN-class constants beyond Wave 25 whitelist —
    `T_TB_TICKS`, `T_BR_LOW_TICKS`, `BREAK_MIN_TICKS`,
    `LP_BR_MIN_TICKS` — must each trigger FAIL."""
    for const_name in (
        "T_TB_TICKS",
        "T_BR_LOW_TICKS",
        "BREAK_MIN_TICKS",
        "LP_BR_MIN_TICKS",
        "T_BREAK_LEN",
    ):
        rtl_dir = tmp_path / f"sub_{const_name}" / "phase2" / "stage1" / "rtl"
        rtl_dir.mkdir(parents=True, exist_ok=True)
        (rtl_dir / "main_fsm.sv").write_text(f"""
module main_fsm(input clk);
  localparam int {const_name} = 690;
  typedef enum {{
    S_WAIT_TURN, S_TX_BR, S_TX_BIT_LOW
  }} state_t;
  state_t state;
  logic tx_oe;
  logic [15:0] cnt;
  always_ff @(posedge clk) begin
    case (state)
      S_WAIT_TURN: state <= S_TX_BR;
      S_TX_BR: begin
        tx_oe <= 1'b1;
        if (cnt >= {const_name}) state <= S_TX_BIT_LOW;
      end
      S_TX_BIT_LOW: tx_oe <= 1'b0;
    endcase
  end
endmodule
""")
        r = subprocess.run(
            [sys.executable, str(PROG), str(tmp_path / f"sub_{const_name}")],
            capture_output=True, text=True,
        )
        assert r.returncode == 1, (
            f"const={const_name!r} should FAIL but returned "
            f"{r.returncode}\n{r.stdout}"
        )
        assert "SLAVE_TX_DEVICE_BREAK_PRESENT" in r.stdout, const_name


def test_fallback_no_whitelist_const_still_fails(tmp_path):
    """Wave 33 fallback: BR-named state with LOW drive + counter wait
    + TX-bit successor must FAIL even if the constant name is not
    in the BR_MIN keyword list."""
    _write_rtl(
        tmp_path,
        "main_fsm.sv",
        """
module main_fsm(input clk);
  localparam int FOO_GENERIC_TICKS = 800;
  typedef enum { S_WAIT_TURN, S_TX_BREAK, S_TX_BIT_LOW } state_t;
  state_t state;
  logic tx_oe_low;
  logic [15:0] cnt;
  always_ff @(posedge clk) begin
    case (state)
      S_WAIT_TURN: state <= S_TX_BREAK;
      S_TX_BREAK: begin
        tx_oe_low <= 1'b1;
        if (cnt >= FOO_GENERIC_TICKS) state <= S_TX_BIT_LOW;
      end
      S_TX_BIT_LOW: tx_oe_low <= 1'b0;
    endcase
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "SLAVE_TX_DEVICE_BREAK_PRESENT" in r.stdout
    assert "S_TX_BREAK" in r.stdout


def test_v0119_65_pattern_fail(tmp_path):
    """Wave 34 regression: v0.119.65 escape used innocuous-sounding
    state name `S_TX_HEADER` and custom constant
    `T_TX_HEADER_TICKS = 690` to drive `id_bus_drive_low <= 1'b1`
    for 690 ticks — fully bypassing Wave 33 substring matching of
    state name and constant name. Wave 34 behavior-based detection
    must catch it because 690 ≥ BR_MIN=613 ticks.
    """
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "0_rtl_constants_pkg.sv").write_text(
        """
        package rtl_constants_pkg;
          localparam int H1_MAX            = 192;
          localparam int H0_MIN            = 193;
          localparam int H0_MAX            = 612;
          localparam int BR_MIN            = 613;
          localparam int T_TX_HEADER_TICKS = 690;
          localparam int T_TSRS_MIN_TICKS  = 1000;
        endpackage
        """
    )
    (rtl / "main_fsm.sv").write_text(
        """
        module main_fsm(input clk);
          import rtl_constants_pkg::*;
          typedef enum {
            S_IDLE, S_RX_LOW, S_RX_DONE, S_TURNAROUND_WAIT,
            S_TX_HEADER, S_TX_BIT_LOW, S_TX_BIT_HIGH
          } state_t;
          state_t state;
          logic id_bus_drive_low;
          logic [15:0] tx_low_cnt;
          always_ff @(posedge clk) begin
            case (state)
              S_TURNAROUND_WAIT: state <= S_TX_HEADER;
              S_TX_HEADER: begin
                id_bus_drive_low <= 1'b1;
                tx_low_cnt       <= tx_low_cnt + 16'd1;
                if (tx_low_cnt + 16'd1 >= T_TX_HEADER_TICKS[15:0]) begin
                  id_bus_drive_low <= 1'b0;
                  state            <= S_TX_BIT_LOW;
                end
              end
              S_TX_BIT_LOW: id_bus_drive_low <= 1'b1;
            endcase
          end
        endmodule
        """
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "SLAVE_TX_DEVICE_BREAK_PRESENT" in r.stdout, r.stdout
    assert "S_TX_HEADER" in r.stdout
    assert "690" in r.stdout
    assert "613" in r.stdout


def test_short_low_burst_with_br_min_pass(tmp_path):
    """Wave 34: a state with a short LOW pulse below BR_MIN must NOT
    trip the gate even when BR_MIN is resolvable.
    """
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "0_rtl_constants_pkg.sv").write_text(
        """
        package pkg;
          localparam int BR_MIN          = 613;
          localparam int T_SETTLE_TICKS  = 30;
        endpackage
        """
    )
    (rtl / "main_fsm.sv").write_text(
        """
        module main_fsm(input clk);
          import pkg::*;
          typedef enum {
            S_RX_DONE, S_WAIT_TURN, S_TX_SETTLE, S_TX_BIT
          } state_t;
          state_t state;
          logic tx_oe;
          logic [15:0] cnt;
          always_ff @(posedge clk) begin
            case (state)
              S_WAIT_TURN: state <= S_TX_SETTLE;
              S_TX_SETTLE: begin
                tx_oe <= 1'b1;
                if (cnt + 16'd1 >= T_SETTLE_TICKS[15:0]) state <= S_TX_BIT;
              end
              S_TX_BIT: tx_oe <= 1'b1;
            endcase
          end
        endmodule
        """
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout


def test_l8_br_min_takes_priority(tmp_path):
    """Wave 34: L8.rx_classifier_ticks.br_min overrides RTL
    localparam — in case the RTL renames its BR_MIN to something the
    keyword list does not match.
    """
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "main_fsm.sv").write_text(
        """
        module main_fsm(input clk);
          localparam int CUSTOM_NAME_750 = 750;
          typedef enum { S_WAIT_TURN, S_TX_PREAMBLE, S_TX_BIT } state_t;
          state_t state;
          logic tx_oe;
          logic [15:0] cnt;
          always_ff @(posedge clk) begin
            case (state)
              S_WAIT_TURN: state <= S_TX_PREAMBLE;
              S_TX_PREAMBLE: begin
                tx_oe <= 1'b1;
                if (cnt + 16'd1 >= CUSTOM_NAME_750[15:0]) state <= S_TX_BIT;
              end
              S_TX_BIT: tx_oe <= 1'b1;
            endcase
          end
        endmodule
        """
    )
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L8.json").write_text(json.dumps({
        "rx_classifier_ticks": {"br_min": 600},
    }))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "SLAVE_TX_DEVICE_BREAK_PRESENT" in r.stdout
    assert "S_TX_PREAMBLE" in r.stdout
    assert "750" in r.stdout
    assert "600" in r.stdout


def test_no_fsm_skip(tmp_path):
    # Non-FSM RTL: SKIP.
    _write_rtl(
        tmp_path,
        "alu.sv",
        """
module alu(input wire [7:0] a, output wire [7:0] y);
  assign y = a + 1;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "SKIP" in r.stdout
