"""Tests for rsp_example_otp_consistency_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROGRAM = Path(__file__).parent.parent / "rsp_example_otp_consistency_check.py"


def _run(tmp_path, l3_doc, otp_doc, poly="0x8C", init="0xFF"):
    l3_p = tmp_path / "L3.json"
    otp_p = tmp_path / "L11.json"
    l3_p.write_text(json.dumps(l3_doc))
    otp_p.write_text(json.dumps(otp_doc))
    r = subprocess.run(
        [sys.executable, str(PROGRAM), str(l3_p),
         "--otp", str(otp_p), "--poly", poly, "--init", init, "--json"],
        capture_output=True, text=True,
    )
    return r.returncode, json.loads(r.stdout) if r.stdout else {}


# CRC-8/MAXIM (poly 0x8C reflected, init 0xFF) of [0x75, 0x10, 0x00*5] = 0x47.
# (First byte is opcode|0x01, then 6 ID bytes from OTP.)

OTP_REAL = {"otp_bytes": [
    0x10, 0x00, 0x00, 0x00, 0x00, 0x00,  # ID[0..5]
    # (rest unused for 0x74 test)
]}

OTP_SPEC_TEMPLATE = {"otp_bytes": [
    0x10, 0x09, 0x08, 0x00, 0x00, 0x00,  # different chip's ID
]}


def test_consistent_example_passes(tmp_path):
    """rsp_example aligns with OTP + CRC matches — PASS."""
    l3 = {
        "opcodes": [
            {"opcode": "0x74",
             "rsp_example": "75 10 00 00 00 00 00 47"}
        ]
    }
    rc, out = _run(tmp_path, l3, OTP_REAL)
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_v068_mismatch_flagged(tmp_path):
    """v068 real bug: rsp_example uses spec-template ID (10 09 08 ...),
    but L11 OTP is the actual chip ID (10 00 00 ...)."""
    l3 = {
        "opcodes": [
            {"opcode": "0x74",
             "rsp_example": "75 10 09 08 00 00 00 A8"}
        ]
    }
    rc, out = _run(tmp_path, l3, OTP_REAL)
    assert rc == 1
    rules = [f["rule"] for f in out["findings"]]
    assert "rsp_example_otp_mismatch" in rules


def test_crc_mismatch_alone_flagged(tmp_path):
    """rsp_example has right ID but wrong CRC — CRC check fails."""
    l3 = {
        "opcodes": [
            {"opcode": "0x74",
             "rsp_example": "75 10 00 00 00 00 00 FF"}  # wrong CRC
        ]
    }
    rc, out = _run(tmp_path, l3, OTP_REAL)
    assert rc == 1
    rules = [f["rule"] for f in out["findings"]]
    assert "rsp_example_crc_mismatch" in rules


def test_runtime_compute_silences_crc(tmp_path):
    """Opcode marked `crc_policy: runtime-compute` — CRC check skipped."""
    l3 = {
        "opcodes": [
            {"opcode": "0x74",
             "crc_policy": "runtime-compute",
             "rsp_example": "75 10 00 00 00 00 00 FF"}  # wrong CRC, but runtime
        ]
    }
    rc, out = _run(tmp_path, l3, OTP_REAL)
    # CRC no longer checked, but OTP mismatch not flagged either since rsp matches OTP_REAL
    # Wait — the rsp_example above uses 10 00 00 00 00 00 = OTP_REAL. So OTP matches.
    # Only CRC differs, which is silenced. → PASS.
    assert rc == 0


def test_illustrative_tag_silences_crc(tmp_path):
    l3 = {
        "opcodes": [
            {"opcode": "0x74",
             "crc_policy": "illustrative",
             "rsp_example": "75 10 00 00 00 00 00 00"}  # dummy CRC
        ]
    }
    rc, out = _run(tmp_path, l3, OTP_REAL)
    assert rc == 0


def test_non_otp_sourced_opcode_only_crc_checked(tmp_path):
    """0x70 is NOT OTP-sourced; only CRC self-consistency matters."""
    l3 = {
        "opcodes": [
            {"opcode": "0x70",
             "rsp_example": "71 93"}  # known correct CRC for 0x71
        ]
    }
    rc, out = _run(tmp_path, l3, OTP_REAL)
    assert rc == 0


def test_hex_list_form(tmp_path):
    """rsp_example may be a list of hex strings instead of string."""
    l3 = {
        "opcodes": [
            {"opcode": "0x74",
             "rsp_example": ["0x75", "0x10", "0x00", "0x00",
                             "0x00", "0x00", "0x00", "0x47"]}
        ]
    }
    rc, out = _run(tmp_path, l3, OTP_REAL)
    assert rc == 0


def test_otp_dict_form(tmp_path):
    """L11 OTP as {addr_hex: value_hex} dict."""
    otp = {"otp": {
        "0x00": "0x10",
        "0x01": "0x00",
        "0x02": "0x00",
        "0x03": "0x00",
        "0x04": "0x00",
        "0x05": "0x00",
    }}
    l3 = {
        "opcodes": [
            {"opcode": "0x74",
             "rsp_example": "75 10 00 00 00 00 00 47"}
        ]
    }
    rc, out = _run(tmp_path, l3, otp)
    assert rc == 0


def test_too_short_example_flagged(tmp_path):
    """0x74 expects opcode + 6 ID + CRC = 8 bytes; shorter flagged."""
    l3 = {
        "opcodes": [
            {"opcode": "0x74",
             "rsp_example": "75 10 00 47"}  # 4 bytes, too short
        ]
    }
    rc, out = _run(tmp_path, l3, OTP_REAL)
    assert rc == 1
    rules = [f["rule"] for f in out["findings"]]
    assert "rsp_example_too_short" in rules


def test_no_opcodes_error(tmp_path):
    l3 = {"unrelated": "data"}
    rc, out = _run(tmp_path, l3, OTP_REAL)
    assert rc == 1
    rules = [f["rule"] for f in out["findings"]]
    assert "no_opcodes_found" in rules


def test_missing_file_error(tmp_path):
    otp_p = tmp_path / "otp.json"
    otp_p.write_text(json.dumps(OTP_REAL))
    r = subprocess.run(
        [sys.executable, str(PROGRAM),
         str(tmp_path / "nope.json"), "--otp", str(otp_p)],
        capture_output=True)
    assert r.returncode == 2
