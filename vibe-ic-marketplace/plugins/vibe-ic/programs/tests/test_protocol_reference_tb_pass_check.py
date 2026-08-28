#!/usr/bin/env python3
"""Tests for protocol_reference_tb_pass_check.py — Wave 28 gate."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import _watchdog

PROG = (Path(__file__).resolve().parent.parent / "protocol_reference_tb_pass_check.py")

PLUGIN_TB = (Path(__file__).resolve().parent.parent.parent
             / "tools" / "protocol_tb" / "aid_class_reference_tb.v")

IVERILOG = shutil.which("iverilog") is not None and shutil.which("vvp") is not None


def _run(args, **kw):
    """Drive the checker as a subprocess, bounded by NO PROGRESS, not by a clock.

    Six of these calls carried a fixed 60 s budget and the other four carried
    nothing, which is already the tell: 60 is not a property of
    `protocol_reference_tb_pass_check.py`, it is a guess about the host that ran
    it. The calls that carried it are the ones that compile and simulate through
    iverilog/vvp — exactly the ones a busy or slower machine takes longest on —
    so the guess was wrong in the direction that turns "this box is loaded" into
    "the reference TB failed".

    `run_host_supervised` watches CPU and I/O across the child's whole /proc
    tree (an iverilog that shells out has its progress in a grandchild) plus the
    growth of its captured output, and kills only a job where all of that has
    stopped. A slow compile now always finishes; a wedged one still dies, as rc
    `_watchdog.RC_STALLED`, which no verdict of this checker collides with."""
    cmd = [sys.executable, str(PROG)] + args
    return _watchdog.completed_process(
        cmd, _watchdog.run_host_supervised(cmd, **kw))


def _make_proj(tmp_path: Path,
               rtl_files: dict[str, str] | None = None,
               l3: dict | None = None,
               l9: dict | None = None,
               waiver: str | None = None,
               ) -> Path:
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    if rtl_files:
        rtl = proj / "phase2" / "stage1" / "rtl"
        rtl.mkdir(parents=True, exist_ok=True)
        for name, body in rtl_files.items():
            (rtl / name).write_text(body)
    if l3 is not None:
        d = proj / "phase1" / "generated_docs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "L3.json").write_text(json.dumps(l3))
    if l9 is not None:
        d = proj / "phase1" / "generated_docs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "L9.json").write_text(json.dumps(l9))
    if waiver is not None:
        (proj / "waivers.json").write_text(json.dumps(
            {"protocol_reference_tb_skipped_intentional": waiver}))
    return proj


# Wave 34: a minimal "responder" stub that passes the new EXAMPLE_PROTOCOL-class
# reference TB.  Drives ONLY response bits (no device-side BR) +
# opcode 0x75 + 6 ID bytes + correct CRC for any host BR seen on
# id_bus.  Wave 28 stubs that emitted a 14us DUT BR before the bits
# now violate Wave 34 PROTOCOL_VIOLATION_DEVICE_BR and will FAIL.
PASSING_STUB_RTL = r"""
`timescale 1ns/100ps
module chip_top(input clk, input reset_n, inout id_bus);
  reg drv = 0;
  assign id_bus = drv ? 1'b0 : 1'bz;

  function automatic [7:0] crc_step(input [7:0] c, input [7:0] d);
    integer j;
    reg [7:0] x;
    begin
      x = c ^ d;
      for (j=0;j<8;j=j+1)
        if (x[0]) x = (x>>1) ^ 8'h8C; else x = x>>1;
      crc_step = x;
    end
  endfunction

  task drive_bit(input b);
    begin
      drv = 1;
      if (b == 1'b0) #7100; else #1800;
      drv = 0;
      if (b == 1'b0) #1700; else #7000;
    end
  endtask

  task drive_byte(input [7:0] B);
    integer i;
    begin
      for (i=0;i<8;i=i+1) drive_bit(B[i]);
    end
  endtask

  task tx_response(input [7:0] op, input [7:0] B0, input [7:0] B1,
                   input [7:0] B2, input [7:0] B3, input [7:0] B4,
                   input [7:0] B5);
    reg [7:0] crc;
    begin
      crc = 8'hFF;
      crc = crc_step(crc, op);
      crc = crc_step(crc, B0);
      crc = crc_step(crc, B1);
      crc = crc_step(crc, B2);
      crc = crc_step(crc, B3);
      crc = crc_step(crc, B4);
      crc = crc_step(crc, B5);
      // Wave 34: NO device BR.  Start straight into bit transmission.
      drive_byte(op);
      drive_byte(B0); drive_byte(B1); drive_byte(B2);
      drive_byte(B3); drive_byte(B4); drive_byte(B5);
      drive_byte(crc);
    end
  endtask

  initial begin
    drv = 0;
    @(posedge reset_n);
    forever begin
      wait (id_bus === 1'b0);
      #12000;
      if (id_bus === 1'b0) begin
        wait (id_bus !== 1'b0);
        #95000;
        tx_response(8'h75, 8'h11, 8'h22, 8'h33, 8'h44, 8'h55, 8'h66);
      end
    end
  end
endmodule
"""

# Wave 34: stub that emits a leading device BR (14us LOW) before
# response bits.  Should now FAIL the Wave 34 TB with
# PROTOCOL_VIOLATION_DEVICE_BR.
DEVICE_BR_STUB_RTL = r"""
`timescale 1ns/100ps
module chip_top(input clk, input reset_n, inout id_bus);
  reg drv = 0;
  assign id_bus = drv ? 1'b0 : 1'bz;

  task drive_bit(input b);
    begin
      drv = 1;
      if (b == 1'b0) #7100; else #1800;
      drv = 0;
      if (b == 1'b0) #1700; else #7000;
    end
  endtask

  task drive_byte(input [7:0] B);
    integer i;
    begin
      for (i=0;i<8;i=i+1) drive_bit(B[i]);
    end
  endtask

  initial begin
    drv = 0;
    @(posedge reset_n);
    forever begin
      wait (id_bus === 1'b0);
      #12000;
      if (id_bus === 1'b0) begin
        wait (id_bus !== 1'b0);
        #95000;
        // Leading device BR — forbidden under Wave 34
        drv = 1; #14000; drv = 0; #2000;
        drive_byte(8'h75);
        drive_byte(8'h00); drive_byte(8'h00); drive_byte(8'h00);
        drive_byte(8'h00); drive_byte(8'h00); drive_byte(8'h00);
        drive_byte(8'h00);
      end
    end
  end
endmodule
"""

# A "silent" stub: declares an inout id_bus port but never drives it.
SILENT_STUB_RTL = r"""
`timescale 1ns/100ps
module chip_top(input clk, input reset_n, inout id_bus);
  // never drive — pure pull-up keeps id_bus HIGH
  assign id_bus = 1'bz;
endmodule
"""

# A "wrong opcode" stub: drives 0x55 instead of 0x75.
WRONG_OPCODE_STUB_RTL = r"""
`timescale 1ns/100ps
module chip_top(input clk, input reset_n, inout id_bus);
  reg drv = 0;
  assign id_bus = drv ? 1'b0 : 1'bz;

  task drive_bit(input b);
    begin
      drv = 1;
      if (b == 1'b0) #7100; else #1800;
      drv = 0;
      if (b == 1'b0) #1700; else #7000;
    end
  endtask

  task drive_byte(input [7:0] B);
    integer i;
    begin
      for (i=0;i<8;i=i+1) drive_bit(B[i]);
    end
  endtask

  initial begin
    drv = 0;
    @(posedge reset_n);
    forever begin
      wait (id_bus === 1'b0);
      #12000;
      if (id_bus === 1'b0) begin
        wait (id_bus !== 1'b0);
        #95000;
        // Wave 34: NO device BR.
        // Wrong opcode 0x55 instead of 0x75
        drive_byte(8'h55);
        drive_byte(8'h00); drive_byte(8'h00); drive_byte(8'h00);
        drive_byte(8'h00); drive_byte(8'h00); drive_byte(8'h00);
        drive_byte(8'h00); // bogus CRC
      end
    end
  end
endmodule
"""

L3_DEFAULT = {
    "doc": "L3",
    "commands": [
        {"opcode": "0x74", "name": "GET_ID", "rsp_op": "0x75"},
    ],
}


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_no_rtl_skip(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    r = _run([str(proj)])
    assert r.returncode == 0
    assert "PASS_SKIP" in r.stdout


def test_non_protocol_skip(tmp_path):
    """Non-protocol design (no inout id_bus, no L3) → SKIP."""
    rtl = "module top(input a, output b); assign b = a; endmodule"
    proj = _make_proj(tmp_path, rtl_files={"top.v": rtl})
    r = _run([str(proj)])
    assert r.returncode == 0
    assert "PASS_SKIP" in r.stdout


@pytest.mark.skipif(not IVERILOG, reason="iverilog/vvp not available")
def test_passing_rtl_pass(tmp_path):
    """Working responder stub → TB reports PROTOCOL_REFERENCE_TB_PASS."""
    proj = _make_proj(tmp_path,
                      rtl_files={"chip_top.v": PASSING_STUB_RTL},
                      l3=L3_DEFAULT)
    r = _run([str(proj), "--json", str(tmp_path / "out.json")])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS — PROTOCOL_REFERENCE_TB_PASS" in r.stdout
    out = json.loads((tmp_path / "out.json").read_text())
    assert out["pass"] is True
    assert "PROTOCOL_REFERENCE_TB_PASS" in out.get("run_stdout_tail", "")


@pytest.mark.skipif(not IVERILOG, reason="iverilog/vvp not available")
def test_silent_rtl_fail(tmp_path):
    """Silent DUT → TB FAILs with byte count = 0."""
    proj = _make_proj(tmp_path,
                      rtl_files={"chip_top.v": SILENT_STUB_RTL},
                      l3=L3_DEFAULT)
    r = _run([str(proj), "--json", str(tmp_path / "out.json")])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL_GET_ID" in r.stdout
    out = json.loads((tmp_path / "out.json").read_text())
    assert out["pass"] is False
    findings = out.get("findings", [])
    assert any("0 bytes" in f.get("message", "") for f in findings)


@pytest.mark.skipif(not IVERILOG, reason="iverilog/vvp not available")
def test_wrong_opcode_fail(tmp_path):
    """Stub drives 0x55 instead of 0x75 → TB FAILs with opcode error."""
    proj = _make_proj(tmp_path,
                      rtl_files={"chip_top.v": WRONG_OPCODE_STUB_RTL},
                      l3=L3_DEFAULT)
    r = _run([str(proj), "--json", str(tmp_path / "out.json")])
    assert r.returncode == 1, r.stdout + r.stderr
    out = json.loads((tmp_path / "out.json").read_text())
    findings = out.get("findings", [])
    # The TB should call out the wrong opcode (0x55 != 0x75)
    assert any("0x55" in f.get("message", "")
               or "expected 0x75" in f.get("message", "").lower()
               for f in findings)


def test_no_top_module_skip(tmp_path):
    """Project has only a bare logic module — no inout id_bus → SKIP."""
    rtl = ("`timescale 1ns/100ps\n"
           "module foo(input a, output reg b);\n"
           "  always @(*) b = a;\n"
           "endmodule\n")
    proj = _make_proj(tmp_path, rtl_files={"foo.v": rtl})
    r = _run([str(proj)])
    assert r.returncode == 0
    assert "PASS_SKIP" in r.stdout


def test_no_iverilog_warn(tmp_path, monkeypatch):
    """When iverilog is not on PATH, gate WARNs and exits 0."""
    proj = _make_proj(tmp_path,
                      rtl_files={"chip_top.v": SILENT_STUB_RTL},
                      l3=L3_DEFAULT)
    # Build a minimal PATH lacking iverilog/vvp.
    bare_path = tmp_path / "barebin"
    bare_path.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PATH"] = str(bare_path)
    r = subprocess.run(
        [sys.executable, str(PROG), str(proj)],
        env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert ("PASS_WITH_WARN" in r.stdout
            or "PASS_SKIP" in r.stdout)
    if "PASS_WITH_WARN" in r.stdout:
        assert "iverilog" in r.stdout.lower()


@pytest.mark.skipif(not IVERILOG, reason="iverilog/vvp not available")
def test_with_legacy_waiver_still_fails(tmp_path):
    """Wave 29 (v0.119.61): gate is non-waivable.

    Even when the legacy waiver
    ``protocol_reference_tb_skipped_intentional`` is set, a silent
    DUT must still FAIL (returncode 1).  The diagnostic surfaces a
    Wave-29 message indicating the legacy waiver is rejected.
    """
    proj = _make_proj(
        tmp_path,
        rtl_files={"chip_top.v": SILENT_STUB_RTL},
        l3=L3_DEFAULT,
        waiver=("Intentional: project gate-waivered while we wait for "
                "the alternative bench harness to land — see TICKET-X."),
    )
    r = _run([str(proj)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "Wave 29" in r.stdout
    assert "non-waivable" in r.stdout
    assert "PASS_WITH_WAIVER" not in r.stdout


@pytest.mark.skipif(not IVERILOG, reason="iverilog/vvp not available")
def test_device_br_stub_violation(tmp_path):
    """Wave 34: stub that emits a leading device BR (14us LOW) before
    response bits must FAIL the TB with PROTOCOL_VIOLATION_DEVICE_BR.
    """
    proj = _make_proj(tmp_path,
                      rtl_files={"chip_top.v": DEVICE_BR_STUB_RTL},
                      l3=L3_DEFAULT)
    r = _run([str(proj), "--json", str(tmp_path / "out.json")])
    assert r.returncode == 1, r.stdout + r.stderr
    out = json.loads((tmp_path / "out.json").read_text())
    assert out["pass"] is False
    findings = out.get("findings", [])
    # Wave 34 (Task 4): findings must surface the explicit violation
    # code so the agent can diagnose without re-reading TB output.
    assert any(
        "DEVICE_BR" in f.get("rule", "")
        or "DEVICE_BR" in f.get("message", "")
        or "PROTOCOL_VIOLATION_DEVICE_BR" in f.get("message", "")
        for f in findings
    ), f"missing DEVICE_BR signal in findings: {findings}"


def test_plugin_tb_present():
    """Sanity: the plugin reference TB ships with the package."""
    assert PLUGIN_TB.is_file(), (
        f"plugin reference TB not found at {PLUGIN_TB} — "
        "Wave 28 install incomplete")
    txt = PLUGIN_TB.read_text()
    assert "aid_class_reference_tb" in txt
    assert "PROTOCOL_REFERENCE_TB_PASS" in txt
    assert "PROTOCOL_REFERENCE_TB_FAIL" in txt


def test_wave35_extended_scenarios_present():
    """Wave 35 (v0.119.67): extended diagnostic scenarios are wired
    into the TB.  Each scenario has a task definition and is driven
    in the main initial block.
    """
    txt = PLUGIN_TB.read_text()
    # Scenario tasks
    for scen in (
        "run_scenario_get_otp_byte",
        "run_scenario_set_state",
        "run_scenario_crc_corruption",
        "run_scenario_frame_timeout",
        "run_scenario_multi_byte_cmd",
        "run_scenario_wake_then_get_id",
    ):
        assert scen in txt, f"missing scenario task: {scen}"
    # Per-scenario verdict markers
    for marker in (
        "PASS_GET_OTP_BYTE", "SKIP_GET_OTP_BYTE",
        "PASS_SET_STATE", "SKIP_SET_STATE",
        "PASS_CRC_CORRUPTION",
        "PASS_FRAME_TIMEOUT", "WARN_FRAME_TIMEOUT",
        "SKIP_MULTI_BYTE_CMD",
        "PASS_WAKE_THEN_GET_ID", "WARN_WAKE_THEN_GET_ID",
    ):
        assert marker in txt, f"missing scenario verdict marker: {marker}"


@pytest.mark.skipif(not IVERILOG, reason="iverilog/vvp not available")
def test_wave35_scenarios_run_on_silent_stub(tmp_path):
    """Wave 35: even on a silent DUT, the extended scenarios produce
    SKIP / WARN lines (not hard FAIL) so chips that don't implement
    every opcode still see PROTOCOL_REFERENCE_TB_PASS for the canonical
    GET_ID/GET_STATE/GET_INFO trio.  The silent stub here will still
    FAIL on those three; this test only verifies the SCENARIO output
    lines are produced.
    """
    proj = _make_proj(tmp_path,
                      rtl_files={"chip_top.v": SILENT_STUB_RTL},
                      l3=L3_DEFAULT)
    r = _run([str(proj), "--json", str(tmp_path / "out.json")])
    # Don't assert returncode; we just want to see scenario markers.
    out_text = r.stdout
    json_path = tmp_path / "out.json"
    if json_path.exists():
        out = json.loads(json_path.read_text())
        out_text = out_text + out.get("run_stdout_tail", "")
    assert "GET_OTP_BYTE" in out_text or "scenario=GET_OTP_BYTE" in out_text
    assert "CRC_CORRUPTION" in out_text or "scenario=CRC_CORRUPTION" in out_text
