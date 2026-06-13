#!/usr/bin/env python3
"""Tests for function_void_with_output_check.py — Wave 29 Gate 1."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "function_void_with_output_check.py")


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
            {"function_void_output_intentional": waiver}))
    return proj


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_function_void_with_output_fail(tmp_path):
    """v0.119.59 bug case — function void with output args → FAIL."""
    rtl = {"main_fsm.sv": """\
module main_fsm(input clk);
  function automatic void dispatch_setup;
    input  [7:0] op;
    output [7:0] rop;
    output [4:0] payload_len;
    begin
      rop         = op | 8'h01;
      payload_len = 5'd0;
    end
  endfunction
endmodule
"""}
    proj = _make(tmp_path, rtl=rtl)
    r = _run([str(proj)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FUNCTION_VOID_WITH_OUTPUT" in r.stdout
    assert "main_fsm.sv:2" in r.stdout
    assert "dispatch_setup" in r.stdout


def test_function_void_no_output_pass(tmp_path):
    """function void with only input args → PASS."""
    rtl = {"helpers.sv": """\
module helpers;
  function automatic void log_event;
    input [31:0] code;
    begin
      $display("event %h", code);
    end
  endfunction
endmodule
"""}
    proj = _make(tmp_path, rtl=rtl)
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_task_with_output_pass(tmp_path):
    """task (not function) with output → PASS (correct usage)."""
    rtl = {"helpers.sv": """\
module helpers;
  task automatic dispatch_setup(
    input  [7:0] op,
    output [7:0] rop,
    output [4:0] payload_len
  );
    begin
      rop         = op | 8'h01;
      payload_len = 5'd0;
    end
  endtask
endmodule
"""}
    proj = _make(tmp_path, rtl=rtl)
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_function_returns_value_pass(tmp_path):
    """function with non-void return type and only inputs → PASS."""
    rtl = {"helpers.sv": """\
module helpers;
  function automatic [7:0] mask_high;
    input [7:0] op;
    begin
      mask_high = op | 8'h80;
    end
  endfunction
endmodule
"""}
    proj = _make(tmp_path, rtl=rtl)
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr


def test_with_waiver_pass(tmp_path):
    """waiver `function_void_output_intentional` ≥40 chars → PASS_WITH_WAIVER."""
    rtl = {"main_fsm.sv": """\
module main_fsm(input clk);
  function automatic void dispatch_setup;
    input  [7:0] op;
    output [7:0] rop;
    begin
      rop = op | 8'h01;
    end
  endfunction
endmodule
"""}
    waiver = ("Wave 29 demonstration project — keeping legacy "
              "function-with-output for vendor BSP compat (≥40 chars)")
    proj = _make(tmp_path, rtl=rtl, waiver=waiver)
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout


def test_no_rtl_skip(tmp_path):
    """No RTL files → PASS_SKIP."""
    proj = _make(tmp_path)
    r = _run([str(proj)])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_SKIP" in r.stdout


def test_ansi_form_with_output_fail(tmp_path):
    """ANSI port-list form `function void NAME(input, output)` →
    FAIL."""
    rtl = {"core.sv": """\
module core;
  function void compute(input [7:0] a, output [7:0] b);
    b = a + 8'd1;
  endfunction
endmodule
"""}
    proj = _make(tmp_path, rtl=rtl)
    r = _run([str(proj)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FUNCTION_VOID_WITH_OUTPUT" in r.stdout
