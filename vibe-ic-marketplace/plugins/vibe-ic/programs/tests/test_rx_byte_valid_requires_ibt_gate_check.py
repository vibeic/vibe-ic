#!/usr/bin/env python3
"""Tests for rx_byte_valid_requires_ibt_gate_check.py (Wave 26 / v0.119.58)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "rx_byte_valid_requires_ibt_gate_check.py")


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, **kw)


def _make_project(tmp_path: Path,
                  rtl_files: dict[str, str],
                  waiver: str | None = None) -> Path:
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    for fname, body in rtl_files.items():
        (proj / "phase2" / "stage1" / "rtl" / fname).write_text(body)
    if waiver:
        (proj / "waivers.json").write_text(json.dumps(
            {"rx_byte_valid_no_ibt_gate_intentional": waiver}))
    return proj


# ----------------------------------------------------------------------

def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_ibt_gated_pass(tmp_path):
    """byte_valid <= 1 inside `if (bit_idx==8 && ibt_cnt >= IBT_MIN)`."""
    rtl = """
    module rx_phy(input clk, input rxd, output reg byte_valid);
      localparam int IBT_MIN_TICKS = 234;
      reg [3:0] bit_idx;
      reg [15:0] ibt_cnt;
      always @(posedge clk) begin
        byte_valid <= 1'b0;
        if (bit_idx == 4'd8 && ibt_cnt >= IBT_MIN_TICKS) begin
          byte_valid <= 1'b1;
          bit_idx <= 0;
        end
      end
    endmodule
    """
    proj = _make_project(tmp_path, {"rx_phy.sv": rtl})
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout


def test_bit_idx_only_fail(tmp_path):
    """byte_valid <= 1 only on bit_idx == 8, no IBT gate → FAIL."""
    rtl = """
    module rx_phy(input clk, input rxd, output reg byte_valid);
      reg [3:0] bit_idx;
      always @(posedge clk) begin
        byte_valid <= 1'b0;
        if (bit_idx == 4'd8) begin
          byte_valid <= 1'b1;
          bit_idx <= 0;
        end
      end
    endmodule
    """
    proj = _make_project(tmp_path, {"rx_phy.sv": rtl})
    r = _run([str(proj), "--json"])
    assert r.returncode == 1
    out = json.loads(r.stdout)
    assert out["verdict"] == "FAIL"


def test_with_waiver_pass(tmp_path):
    """Waiver ≥40 chars → PASS_WITH_WAIVER on otherwise-FAIL code."""
    rtl = """
    module rx_phy(input clk, output reg byte_valid);
      reg [3:0] bit_idx;
      always @(posedge clk) begin
        byte_valid <= 1'b0;
        if (bit_idx == 4'd8) begin
          byte_valid <= 1'b1;
        end
      end
    endmodule
    """
    proj = _make_project(
        tmp_path, {"rx_phy.sv": rtl},
        waiver=("Test bench feeds clean stimulus only; deferring "
                "the IBT gate to a follow-up patch after silicon "
                "noise sweep completes."))
    r = _run([str(proj), "--json"])
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["verdict"] == "PASS_WITH_WAIVER"


def test_no_assembler_skip(tmp_path):
    """No RX assembler / no byte-strobe → SKIP."""
    rtl = """
    module pure_combinational(input a, input b, output y);
      assign y = a & b;
    endmodule
    """
    proj = _make_project(tmp_path, {"glue.v": rtl})
    r = _run([str(proj), "--json"])
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out["verdict"] == "SKIP"
