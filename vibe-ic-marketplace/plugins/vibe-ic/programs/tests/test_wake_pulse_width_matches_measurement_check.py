#!/usr/bin/env python3
"""Tests for wake_pulse_width_matches_measurement_check.py (Wave 18)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "wake_pulse_width_matches_measurement_check.py"
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


def _write_l8(tmp_path: Path, body: dict) -> None:
    d = tmp_path / "phase1" / "generated_docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / "L8_TIMING_WAVEFORM.json").write_text(json.dumps(body))


def _write_pptx(tmp_path: Path, name: str = "量測時序.pptx") -> None:
    d = tmp_path / "input" / "docs"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(b"\x00\x00fake-pptx-bytes\x00\x00")


WAKE_RTL_TEMPLATE = """\
module wake_gen(input logic clk, input logic rst_n,
                input logic enable,
                input logic bus_active,
                output logic wake_oe);
  localparam int T_TWK_PULSE_TICKS = {ticks};
  logic [31:0] cnt;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
        cnt <= 32'd0; wake_oe <= 1'b0;
    end else if (!enable || bus_active) begin
        cnt <= 32'd0; wake_oe <= 1'b0;
    end else begin
        cnt <= cnt + 32'd1;
        if (cnt < T_TWK_PULSE_TICKS) wake_oe <= 1'b1;
        else wake_oe <= 1'b0;
    end
  end
endmodule
"""


def test_within_tolerance_pass(tmp_path):
    # RTL = 22.0 us (1100 ticks @ 50 MHz), L8 = 22.7 us → 3% deviation, PASS.
    _write_rtl(tmp_path, "wake_gen.sv",
               WAKE_RTL_TEMPLATE.format(ticks=1100))
    _write_l8(tmp_path, {"wake_pulse_us": 22.7,
                         "rtl_constants": {"clock_mhz": 50}})
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_too_short_fail(tmp_path):
    # RTL = 16 us (800 ticks @ 50 MHz), L8 = 22.7 us → ~30% deviation, FAIL.
    _write_rtl(tmp_path, "wake_gen.sv",
               WAKE_RTL_TEMPLATE.format(ticks=800))
    _write_l8(tmp_path, {"wake_pulse_us": 22.7,
                         "rtl_constants": {"clock_mhz": 50}})
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "RTL_VS_MEASUREMENT_DEVIATION" in r.stdout


def test_no_l8_measurement_with_pptx_fail(tmp_path):
    # L8 has no wake_pulse measurement field but a PPTX is present.
    _write_rtl(tmp_path, "wake_gen.sv",
               WAKE_RTL_TEMPLATE.format(ticks=800))
    _write_l8(tmp_path, {"rtl_constants": {"clock_mhz": 50}})
    _write_pptx(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "MEASUREMENT_DOC_NOT_EXTRACTED" in r.stdout


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


def test_with_waiver_pass(tmp_path):
    _write_rtl(tmp_path, "wake_gen.sv",
               WAKE_RTL_TEMPLATE.format(ticks=800))
    _write_l8(tmp_path, {"wake_pulse_us": 22.7,
                         "rtl_constants": {"clock_mhz": 50}})
    (tmp_path / "waivers.json").write_text(json.dumps({
        "wake_pulse_intentional_offset":
            "Chip uses an alternate wake-pulse profile validated by "
            "the foundry HW lab on 2026-04-30, ticket WP-22.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout
