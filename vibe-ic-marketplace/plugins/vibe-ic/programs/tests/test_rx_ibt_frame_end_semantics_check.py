#!/usr/bin/env python3
"""Tests for rx_ibt_frame_end_semantics_check.py (Wave 15 Gate 2)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "rx_ibt_frame_end_semantics_check.py"
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


def test_distinct_thresholds_pass(tmp_path):
    """IBT_MIN drives byte_done; IBT_MAX drives frame_end → PASS."""
    _write_rtl(
        tmp_path,
        "rx_phy.sv",
        """\
module rx_phy(input logic clk);
  localparam int IBT_MIN_THRESHOLD = 234;
  localparam int IBT_MAX_THRESHOLD = 2000;
  logic [11:0] ibt_cnt;
  logic        byte_done;
  logic        frame_end;
  always_ff @(posedge clk) begin
    byte_done <= 1'b0;
    frame_end <= 1'b0;
    if (ibt_cnt == IBT_MIN_THRESHOLD) begin
        byte_done <= 1'b1;
    end
    if (ibt_cnt == IBT_MAX_THRESHOLD) begin
        frame_end <= 1'b1;
    end
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_shared_threshold_fail(tmp_path):
    """Same IBT constant drives byte_done AND frame_end → FAIL."""
    _write_rtl(
        tmp_path,
        "rx_phy.sv",
        """\
module rx_phy(input logic clk);
  localparam int IBT_MAX = 2000;
  logic [11:0] ibt_cnt;
  logic        byte_done;
  logic        frame_end;
  always_ff @(posedge clk) begin
    if (ibt_cnt > IBT_MAX) begin
        byte_done <= 1'b1;
        frame_end <= 1'b1;
    end
  end
endmodule
""",
    )
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "SHARED_IBT_THRESHOLD" in r.stdout


def test_with_waiver_pass(tmp_path):
    _write_rtl(
        tmp_path,
        "rx_phy.sv",
        """\
module rx_phy(input logic clk);
  localparam int IBT_MAX = 2000;
  logic [11:0] ibt_cnt;
  logic        byte_done;
  logic        frame_end;
  always_ff @(posedge clk) begin
    if (ibt_cnt > IBT_MAX) begin
        byte_done <= 1'b1;
        frame_end <= 1'b1;
    end
  end
endmodule
""",
    )
    (tmp_path / "waivers.json").write_text(
        json.dumps({
            "rx_ibt_single_threshold_intentional":
                "Protocol uses a single inter-byte threshold by design; "
                "frame-end inferred from byte_count==N. Logged 2026-04-12.",
        })
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVER" in r.stdout


def test_no_ibt_logic_skip(tmp_path):
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
    assert r.returncode == 0
    assert "SKIP" in r.stdout
