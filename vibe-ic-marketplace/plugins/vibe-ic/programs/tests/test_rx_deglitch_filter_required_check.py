#!/usr/bin/env python3
"""Tests for rx_deglitch_filter_required_check.py (Wave 22)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "rx_deglitch_filter_required_check.py"
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


def test_3ff_2of2_pass(tmp_path):
    # Vendor PASS-oracle pattern: 3 sync stages + AND-based 2-of-2.
    _write_rtl(
        tmp_path,
        "top.sv",
        """
module top(
  input  wire clk,
  inout  wire id_bus,
  output wire id_bus_low_n
);
  wire id_bus_rx;
  reg  id_bus_rx_syn1;
  reg  id_bus_rx_syn2;
  reg  id_bus_rx_syn3;
  always @(posedge clk) begin
    id_bus_rx_syn1 <= id_bus_rx;
    id_bus_rx_syn2 <= id_bus_rx_syn1;
    id_bus_rx_syn3 <= id_bus_rx_syn2;
  end
  assign id_bus_low_n = id_bus_rx_syn3 & id_bus_rx_syn2;
  assign id_bus = 1'bz;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout


def test_2ff_only_fail(tmp_path):
    # The 27th-attempt anti-pattern: 2-FF synchronizer fed straight
    # into the consumer with only a self-RX OR mask, no deglitch.
    _write_rtl(
        tmp_path,
        "top.sv",
        """
module top(
  input  wire clk,
  inout  wire id_bus
);
  reg id_ff1, id_ff2;
  always @(posedge clk) begin
    id_ff1 <= id_bus;
    id_ff2 <= id_ff1;
  end
  wire id_in = id_ff2;
  assign id_bus = 1'bz;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RX_SYNC_CHAIN_TOO_SHORT" in r.stdout


def test_3ff_no_filter_warn(tmp_path):
    # 3 stages, but consumer reads the last FF directly — no AND/OR
    # combination. Emits WARN, returns 0.
    _write_rtl(
        tmp_path,
        "top.sv",
        """
module top(
  input  wire clk,
  inout  wire bus_pad
);
  reg s1, s2, s3;
  always @(posedge clk) begin
    s1 <= bus_pad;
    s2 <= s1;
    s3 <= s2;
  end
  wire bus_in = s3;
  assign bus_pad = 1'bz;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "WARN" in r.stdout
    assert "RX_DEGLITCH_FILTER_MISSING" in r.stdout


def test_3ff_or_filter_pass(tmp_path):
    # 3 stages + OR-based 2-of-2 also counts.
    _write_rtl(
        tmp_path,
        "top.sv",
        """
module top(
  input  wire clk,
  inout  wire kline
);
  reg s1, s2, s3;
  always @(posedge clk) begin
    s1 <= kline;
    s2 <= s1;
    s3 <= s2;
  end
  assign kline_low_evt = s3 | s2;
  assign kline = 1'bz;
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_no_rx_path_skip(tmp_path):
    # No inout / no rx-phy file → SKIP.
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


def test_with_waiver_pass(tmp_path):
    # 2-FF chain (would FAIL) silenced by valid waiver.
    _write_rtl(
        tmp_path,
        "top.sv",
        """
module top(
  input  wire clk,
  inout  wire id_bus
);
  reg id_ff1, id_ff2;
  always @(posedge clk) begin
    id_ff1 <= id_bus;
    id_ff2 <= id_ff1;
  end
  wire id_in = id_ff2;
  assign id_bus = 1'bz;
endmodule
""",
    )
    (tmp_path / "waivers.json").write_text(json.dumps({
        "rx_deglitch_intentionally_omitted":
            "On-chip pad already has analog Schmitt trigger + RC "
            "filter equivalent to ≥3-stage deglitch per pad spec.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout
