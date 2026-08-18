#!/usr/bin/env python3
"""Tests for self_rx_mask_required_check.py — Wave 16 Gate 2."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (
    Path(__file__).resolve().parent.parent / "self_rx_mask_required_check.py"
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


def test_with_mask_pass(tmp_path):
    """Wrapper has explicit RX-during-TX mask → PASS."""
    proj = _make(tmp_path, rtl={
        "top.sv": """\
module top(input clk, inout id_bus, output reg [3:0] led);
  reg id_ff1, id_ff2;
  always @(posedge clk) begin
    id_ff1 <= id_bus;
    id_ff2 <= id_ff1;
  end
  wire tx_drive_low;
  wire wake_oe;
  wire id_in = (tx_drive_low | wake_oe) ? 1'b1 : id_ff2;
  assign id_bus = (tx_drive_low | wake_oe) ? 1'b0 : 1'bz;
endmodule
"""
    })
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout


def test_no_mask_fail(tmp_path):
    """Wrapper consumes id_ff2 directly without OE-family gate → FAIL."""
    proj = _make(tmp_path, rtl={
        "top.sv": """\
module top(input clk, inout id_bus, output reg [3:0] led);
  reg id_ff1, id_ff2;
  always @(posedge clk) begin
    id_ff1 <= id_bus;
    id_ff2 <= id_ff1;
  end
  wire tx_drive_low;
  wire wake_oe;
  wire id_in = id_ff2;   // <-- BUG: no mask
  assign id_bus = (tx_drive_low | wake_oe) ? 1'b0 : 1'bz;
endmodule
"""
    })
    r = _run([str(proj)])
    assert r.returncode == 1, r.stdout
    assert "SELF_RX_MASK_MISSING" in r.stdout


def test_no_top_wrapper_skip(tmp_path):
    """No inout + open-drain wrapper → SKIP."""
    proj = _make(tmp_path, rtl={
        "core.v": """\
module core(input clk, input din, output dout);
  reg q;
  always @(posedge clk) q <= din;
  assign dout = q;
endmodule
"""
    })
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout
    assert "SKIP" in r.stdout


def test_with_waiver_pass(tmp_path):
    """Self-RX mask missing but waiver present → PASS_WITH_WAIVER."""
    proj = _make(
        tmp_path,
        rtl={
            "top.sv": """\
module top(input clk, inout id_bus);
  reg id_ff1, id_ff2;
  always @(posedge clk) begin id_ff1 <= id_bus; id_ff2 <= id_ff1; end
  wire tx_drive_low;
  wire id_in = id_ff2;
  assign id_bus = tx_drive_low ? 1'b0 : 1'bz;
endmodule
"""
        },
        waivers={
            "self_rx_no_mask_intentional": (
                "External pull-up + tester firmware tolerates self-RX; "
                "verified on bench against EXAMPLE_TESTER oracle SOF"
            )
        },
    )
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVER" in r.stdout


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_wave35_module_instance_synchronizer_pass(tmp_path):
    """Wave 35: synchronizer is a module instance and the mask consumes
    the post-sync alias (`id_bus_in`) directly. Earlier the gate
    required inline `<x>_ff* <= bus;` NBAs and missed this pattern.
    """
    proj = _make(tmp_path, rtl={
        "chip_top.sv": """\
module chip_top(input clk, input reset_n, inout wire id_bus);
  logic id_bus_in_raw, id_bus_in, id_bus_in_masked;
  logic id_bus_drive_low_pre, tx_busy;
  // module instance does the 2-FF sync; behavior-based check shouldn't care.
  cdc_sync_pad u_sync(.clk(clk), .rst_n(reset_n),
                      .async_in(id_bus_in_raw), .sync_out(id_bus_in));
  assign id_bus_in_raw = id_bus;
  // mask: ternary HIGH on OE-family signal, RHS is the post-sync alias
  assign id_bus_in_masked = (id_bus_drive_low_pre || tx_busy) ? 1'b1 : id_bus_in;
  logic id_bus_drive_low;
  assign id_bus = id_bus_drive_low ? 1'b0 : 1'bz;
endmodule
"""
    })
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout


def test_wave35_drive_low_pre_oe_family_pass(tmp_path):
    """Wave 35: OE-family regex should accept `*_drive_low_pre`,
    `*_drive_low_q`, `tx_busy` etc — pipelined OE signals.
    """
    proj = _make(tmp_path, rtl={
        "chip_top.sv": """\
module chip_top(input clk, inout wire id_bus);
  reg id_ff1, id_ff2;
  always @(posedge clk) begin id_ff1 <= id_bus; id_ff2 <= id_ff1; end
  wire id_bus_drive_low_pre;
  wire id_bus_in = id_bus_drive_low_pre ? 1'b1 : id_ff2;
  assign id_bus = id_bus_drive_low_pre ? 1'b0 : 1'bz;
endmodule
"""
    })
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout
