#!/usr/bin/env python3
"""Tests for crc_q_settle_cycle_after_last_feed_check.py — Wave 16 Gate 3."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "crc_q_settle_cycle_after_last_feed_check.py"
)


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, **kw,
    )


def _make(tmp_path: Path, rtl: dict | None = None,
          waivers: dict | None = None) -> Path:
    proj = tmp_path
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True, exist_ok=True)
    if rtl:
        for name, body in rtl.items():
            (proj / "phase2" / "stage1" / "rtl" / name).write_text(body)
    if waivers is not None:
        (proj / "waivers.json").write_text(json.dumps(waivers))
    return proj


def test_settle_cycle_present_pass(tmp_path):
    """FSM separates crc_feed pulse and crc_q read into different state
    arms (a settle state) → PASS."""
    proj = _make(tmp_path, rtl={
        "crc.v": """\
module crc(input clk, input feed, input [7:0] din, output reg [7:0] crc_q);
  always @(posedge clk) if (feed) crc_q <= crc_q ^ din;
endmodule

module fsm(input clk);
  reg crc_feed;
  reg [7:0] crc_q;
  reg [7:0] tx_byte;
  reg [3:0] state;
  always @(posedge clk) begin
    case (state)
      S_FEED: begin
        crc_feed <= 1'b1;
        state <= S_SETTLE;
      end
      S_SETTLE: begin
        tx_byte <= crc_q;
        state <= S_DONE;
      end
    endcase
  end
endmodule
"""
    })
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout


def test_no_settle_fail(tmp_path):
    """Same state arm pulses crc_feed AND samples crc_q → FAIL."""
    proj = _make(tmp_path, rtl={
        "crc.v": """\
module crc(input clk, input feed, input [7:0] din, output reg [7:0] crc_q);
  always @(posedge clk) if (feed) crc_q <= crc_q ^ din;
endmodule

module fsm(input clk);
  reg crc_feed;
  reg [7:0] crc_q;
  reg [7:0] tx_byte;
  reg [3:0] state;
  always @(posedge clk) begin
    case (state)
      S_TX: begin
        crc_feed <= 1'b1;
        tx_byte  <= crc_q;       // <-- BUG: same cycle as feed pulse
        state    <= S_DONE;
      end
    endcase
  end
endmodule
"""
    })
    r = _run([str(proj)])
    assert r.returncode == 1, r.stdout
    assert "CRC_SETTLE_MISSING" in r.stdout


def test_combinational_crc_skip(tmp_path):
    """CRC module is combinational (assign crc_q = ...) → SKIP."""
    proj = _make(tmp_path, rtl={
        "crc.v": """\
module crc(input [7:0] din, output [7:0] crc_q);
  assign crc_q = din ^ 8'h5A;
endmodule

module fsm(input clk);
  reg crc_feed;
  reg [7:0] tx_byte;
  reg [3:0] state;
  wire [7:0] crc_q;
  always @(posedge clk) begin
    case (state)
      S_TX: begin
        crc_feed <= 1'b1;
        tx_byte  <= crc_q;
      end
    endcase
  end
endmodule
"""
    })
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout
    assert "SKIP" in r.stdout


def test_with_waiver_pass(tmp_path):
    """Bug present + waiver → PASS_WITH_WAIVER."""
    proj = _make(
        tmp_path,
        rtl={
            "crc.v": """\
module crc(input clk, input feed, input [7:0] din, output reg [7:0] crc_q);
  always @(posedge clk) if (feed) crc_q <= crc_q ^ din;
endmodule

module fsm(input clk);
  reg crc_feed;
  reg [7:0] crc_q;
  reg [7:0] tx_byte;
  reg [3:0] state;
  always @(posedge clk) begin
    case (state)
      S_TX: begin
        crc_feed <= 1'b1;
        tx_byte  <= crc_q;
        state    <= S_DONE;
      end
    endcase
  end
endmodule
"""
        },
        waivers={
            "crc_settle_unnecessary_combinational_crc": (
                "CRC engine has 0-cycle latency by construction; verified "
                "by formal equivalence run NX-72-A"
            )
        },
    )
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVER" in r.stdout


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0
