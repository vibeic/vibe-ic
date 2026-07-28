#!/usr/bin/env python3
"""Tests for otp_image_layer_consistency_check.py (P1.3)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "otp_image_layer_consistency_check.py"


def _run(tmp_path: Path, *extra_args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", "-", *extra_args],
        capture_output=True,
        text=True,
    )


def _make_l11(gen_dir: Path, address_map: list[dict]) -> None:
    gen_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / "L11_OTP_CONTENT.json").write_text(
        json.dumps({"address_map": address_map})
    )


def _make_otp_rtl(rtl_dir: Path, mem_inits: str) -> None:
    rtl_dir.mkdir(parents=True, exist_ok=True)
    (rtl_dir / "otp_ctrl.v").write_text(
        "module otp_ctrl(input [6:0] addr, output reg [7:0] dout);\n"
        "  reg [7:0] mem [0:127];\n"
        "  initial begin\n"
        f"{mem_inits}"
        "  end\n"
        "  always @(*) dout = mem[addr];\n"
        "endmodule\n"
    )


def test_pass_matching(tmp_path):
    """L11 and RTL values match → PASS."""
    _make_l11(tmp_path / "phase1" / "generated_docs", [
        {"address": "0x00", "value": "0x10"},
        {"address": "0x01", "value": "0xAB"},
    ])
    _make_otp_rtl(tmp_path / "phase2" / "stage1" / "rtl",
        "    mem[7'h00] = 8'h10;\n"
        "    mem[7'h01] = 8'hAB;\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["passed"] is True
    assert j["summary"]["matches"] == 2
    assert j["summary"]["mismatches"] == 0


def test_fail_hex_confusion(tmp_path):
    """L11 says 0x10 but RTL has 0x0A (decimal 10 mistake) → FAIL."""
    _make_l11(tmp_path / "phase1" / "generated_docs", [
        {"address": "0x00", "value": "0x10"},
    ])
    _make_otp_rtl(tmp_path / "phase2" / "stage1" / "rtl",
        "    mem[7'h00] = 8'h0A;\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    j = json.loads(r.stdout)
    assert j["passed"] is False
    assert j["summary"]["mismatches"] == 1
    rules = [f["rule"] for f in j["findings"] if f["severity"] == "ERROR"]
    assert "OTP_VALUE_MISMATCH" in rules


def test_fail_missing_address(tmp_path):
    """L11 has address not present in RTL → FAIL."""
    _make_l11(tmp_path / "phase1" / "generated_docs", [
        {"address": "0x00", "value": "0x10"},
        {"address": "0x05", "value": "0xFF"},
    ])
    _make_otp_rtl(tmp_path / "phase2" / "stage1" / "rtl",
        "    mem[7'h00] = 8'h10;\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    j = json.loads(r.stdout)
    assert j["passed"] is False
    assert j["summary"]["missing_in_rtl"] >= 1


def test_skip_no_l11(tmp_path):
    """No L11 JSON -> VACUOUS (#521)."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "otp_ctrl.v").write_text("module otp_ctrl; endmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    j = json.loads(r.stdout)
    assert j["passed"] is True
    rules = [f["rule"] for f in j["findings"]]
    assert "SKIP_NO_L11" in rules


def test_skip_no_otp(tmp_path):
    """L11 exists but no OTP module in RTL -> VACUOUS (#521)."""
    _make_l11(tmp_path / "phase1" / "generated_docs", [
        {"address": "0x00", "value": "0x10"},
    ])
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "core.v").write_text("module core; endmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    j = json.loads(r.stdout)
    assert j["passed"] is True
    rules = [f["rule"] for f in j["findings"]]
    assert "SKIP_NO_OTP_MODULE" in rules


def test_pass_override(tmp_path):
    """Mismatch but otp-test-override annotation → PASS."""
    _make_l11(tmp_path / "phase1" / "generated_docs", [
        {"address": "0x00", "value": "0x10"},
    ])
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "otp_ctrl.v").write_text(
        "module otp_ctrl;\n"
        "  reg [7:0] mem [0:127];\n"
        "  initial begin\n"
        "    mem[7'h00] = 8'hFF; // otp-test-override: dev image\n"
        "  end\n"
        "endmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["passed"] is True
    assert j["summary"]["overridden"] == 1


def test_exit2_bad_dir():
    """Nonexistent path → exit 2."""
    r = subprocess.run(
        [sys.executable, str(PROG), "/nonexistent/path/xyz"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2
