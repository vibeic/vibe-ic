#!/usr/bin/env python3
"""Tests for half_duplex_frame_end_idle_reset_check.py (LL-14)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "half_duplex_frame_end_idle_reset_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _make_half_duplex(tmp_path: Path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_FRS.json").write_text(json.dumps({
        "tSRS_min_us": 20.0, "ibt_us": [20.0, 22.0],
    }))


def _write_rtl(tmp_path: Path, body: str, name: str = "core.sv"):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(body)


def test_non_half_duplex_silent_pass(tmp_path):
    """No L2 + no L3 → not half-duplex → silent skip."""
    _write_rtl(tmp_path, "module m; endmodule")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "not detected as half-duplex" in r.stdout


def test_no_rtl_silent_pass(tmp_path):
    _make_half_duplex(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0


def test_counter_with_low_reset_passes(tmp_path):
    """Properly written counter — has bus-LOW reset branch."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module rx_fsm(input logic clk, input logic id_bus_rx,
              input logic rx_byte_vld, output logic eof);
  logic [15:0] gap_cnt;
  always_ff @(posedge clk) begin
    if (rx_byte_vld) begin
        gap_cnt <= '0;
    end else if (!id_bus_rx) begin
        gap_cnt <= '0;
    end else if (id_bus_rx) begin
        gap_cnt <= gap_cnt + 1;
    end
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_counter_without_low_reset_fails(tmp_path):
    """Buggy counter — increments on bus-HIGH but never resets on LOW."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module rx_fsm(input logic clk, input logic id_bus_rx,
              input logic rx_byte_vld);
  logic [15:0] gap_cnt;
  always_ff @(posedge clk) begin
    if (rx_byte_vld) begin
        gap_cnt <= '0;
    end else if (id_bus_rx) begin
        gap_cnt <= gap_cnt + 1;
    end
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "gap_cnt" in r.stdout
    assert "lack bus-LOW reset" in r.stdout


def test_waiver_skips(tmp_path):
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module rx_fsm(input logic clk, input logic id_bus_rx,
              input logic rx_byte_vld);
  logic [15:0] gap_cnt;
  always_ff @(posedge clk) begin
    if (id_bus_rx) gap_cnt <= gap_cnt + 1;
  end
endmodule
""")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "frame_end_idle_reset_alternative":
            "Uses EOM bit in CRC byte instead of gap counter",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


def test_low_reset_via_registered_bus_passes(tmp_path):
    """v0.119.19: vendor-benchmark RTL used `id_bus_rx_q1 == 1'b0` to test
    bus-LOW. The earlier narrow regex (`!id_bus_rx` or `id_bus_rx==1'b0`)
    silently missed it; the loose regex now accepts the registered form.
    Both `id_bus_rx_q1` and the literal `id_bus_rx` should satisfy."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module rx_fsm(input logic clk, input logic id_bus_rx,
              input logic rx_byte_vld);
  logic id_bus_rx_q1;
  logic [15:0] gap_cnt;
  always_ff @(posedge clk) id_bus_rx_q1 <= id_bus_rx;
  always_ff @(posedge clk) begin
    if (rx_byte_vld) begin
        gap_cnt <= '0;
    end else if (id_bus_rx_q1 == 1'b0) begin
        gap_cnt <= '0;
    end else if (id_bus_rx_q1) begin
        gap_cnt <= gap_cnt + 1;
    end
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_low_reset_via_bitwise_not_passes(tmp_path):
    """`~id_bus_rx` (bitwise NOT) is also a valid bus-LOW test."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module rx_fsm(input logic clk, input logic id_bus_rx,
              input logic rx_byte_vld);
  logic [15:0] gap_cnt;
  always_ff @(posedge clk) begin
    if (rx_byte_vld | ~id_bus_rx)
        gap_cnt <= '0;
    else if (id_bus_rx)
        gap_cnt <= gap_cnt + 1;
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_no_false_positive_on_pulse_width_measurement_counter(tmp_path):
    """v0.119.24: agent's pulse-width counter `pw_cnt` was mis-flagged
    because an OUTER `if (id_bus_rx)` block existed elsewhere. The fix
    pins the check to the IMMEDIATE enclosing `if` only — a counter
    whose direct guard is `!id_bus_rx` is a measurement counter, not
    an idle-gap counter, and must NOT be flagged."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module rx_decoder(input logic clk, input logic id_bus_rx,
                  input logic rx_byte_vld);
  logic [15:0] gap_cnt;
  logic [15:0] pw_cnt;
  always_ff @(posedge clk) begin
    // Outer block: gap counter that DOES have bus-LOW reset (good)
    if (rx_byte_vld) begin
        gap_cnt <= '0;
    end else if (!id_bus_rx) begin
        gap_cnt <= '0;
    end else if (id_bus_rx) begin
        gap_cnt <= gap_cnt + 1;
    end
    // Separate: pw_cnt measures the LOW pulse width — increments
    // under `!id_bus_rx`, NOT a missing-LOW-reset bug. The earlier
    // "last 4 conditions" walker accepted because it found
    // `id_bus_rx` (without !) elsewhere; the fix pins to immediate
    // guard only, which is `!id_bus_rx`, so this is no longer flagged.
    if (id_bus_rx) begin
        pw_cnt <= '0;
    end else if (!id_bus_rx) begin
        pw_cnt <= pw_cnt + 1;
    end
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0, \
        f"pw_cnt under !id_bus_rx must not be flagged: {r.stdout}"


def test_no_false_positive_on_unrelated_zero_clear(tmp_path):
    """Negative: the loose regex must NOT pass when the only `<= 0`
    in the file is for a *different* counter unrelated to bus-LOW. The
    counter-bus-LOW correlation is required (within 200 chars)."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module rx_fsm(input logic clk, input logic id_bus_rx, input logic rx_byte_vld);
  logic [15:0] gap_cnt;
  logic [15:0] unrelated_cnt;
  always_ff @(posedge clk) begin
    // Bus-LOW path resets unrelated_cnt only — not gap_cnt!
    if (!id_bus_rx)
        unrelated_cnt <= 16'd0;
    if (rx_byte_vld)
        gap_cnt <= '0;
    else if (id_bus_rx)
        gap_cnt <= gap_cnt + 1;
    // gap_cnt has no bus-LOW reset; should FAIL.
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1, \
        f"loose regex must not satisfy gap_cnt's missing reset: {r.stdout}"
