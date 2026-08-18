#!/usr/bin/env python3
"""Tests for cmd_response_otp_provenance_check.py — see ROOT_CAUSE_ANALYSIS Area 3."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "cmd_response_otp_provenance_check.py"


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True, text=True,
    )


def _l3(tmp_path: Path, commands: list):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "commands": commands,
    }))


def _otp(tmp_path: Path, content: str, name: str = "otp_image.ver"):
    """Write a Verilog $readmemh-format file."""
    d = tmp_path / "input" / "otp"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content)


def test_no_l3_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no L3" in r.stdout


def test_no_examples_silent_pass(tmp_path):
    """L3 commands without example responses → skip."""
    _l3(tmp_path, [{"opcode": "0x76", "name": "READ"}])
    _otp(tmp_path, "00 11 22 33 44 55\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no opcode" in r.stdout


def test_no_otp_image_silent_pass(tmp_path):
    """No .ver/.hex/.mem present → skip."""
    _l3(tmp_path, [{
        "opcode": "0x76",
        "rsp_example": {"response_hex": "AA BB CC DD EE"},
    }])
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no .ver" in r.stdout or "OTP image present" in r.stdout


def test_no_overlap_passes(tmp_path):
    """Example bytes don't match any OTP slice → literal is acceptable."""
    _l3(tmp_path, [{
        "opcode": "0x76",
        "rsp_example": {"response_hex": "AA BB CC DD EE"},
    }])
    _otp(tmp_path, "00 11 22 33 44 55 66 77\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS" in r.stdout


def test_overlap_with_literal_fails(tmp_path):
    """Example matches OTP[base..] AND response_source missing → FAIL."""
    _l3(tmp_path, [{
        "opcode": "0x78",
        "rsp_example": {"response_hex": "33 44 55 66 77"},
    }])
    _otp(tmp_path, "00 11 22 33 44 55 66 77 88\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "OTP[" in r.stdout


def test_overlap_with_otp_range_passes(tmp_path):
    """Example matches OTP slice BUT response_source = otp_range → PASS."""
    _l3(tmp_path, [{
        "opcode": "0x78",
        "response_source": "otp_range",
        "otp_range": {"base": 3, "length": 5},
        "rsp_example": {"response_hex": "33 44 55 66 77"},
    }])
    _otp(tmp_path, "00 11 22 33 44 55 66 77 88\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_waiver_skips(tmp_path):
    _l3(tmp_path, [{
        "opcode": "0x78",
        "rsp_example": {"response_hex": "33 44 55 66 77"},
    }])
    _otp(tmp_path, "00 11 22 33 44 55 66 77\n")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "cmd_response_otp_provenance_alternative":
            "Example bytes are coincidentally an OTP factory default",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


def test_readmemh_atdirective_handled(tmp_path):
    """Verilog $readmemh `@addr` directives are stripped before search."""
    _l3(tmp_path, [{
        "opcode": "0x7A",
        "rsp_example": {"response_hex": "AA BB CC DD"},
    }])
    _otp(tmp_path, """
@00000000 11 22
@00000010 AA BB CC DD EE FF
""")
    r = _run(tmp_path)
    # Address 0x10 == byte 8 in the concatenated stream.
    assert r.returncode == 1
    assert "OTP[" in r.stdout
