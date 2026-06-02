#!/usr/bin/env python3
"""Tests for crc_constants_rtl_doc_consistency_check.py (LL-37).

GENERAL: chip-agnostic. Verifies RTL `crc_out <= 8'hXX` literals
match L8.crc8_constants CRC_SEED + reflected poly literals.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "crc_constants_rtl_doc_consistency_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _put_rtl(tmp_path: Path, name: str, text: str):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(text)


def _put_l8(tmp_path: Path, data: dict):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps(data))


# 1. Baseline — no rtl/, no L8. Silent skip.
def test_no_rtl_no_l8_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "skip" in r.stdout.lower()


# 2. RTL but no L8 — silent skip.
def test_no_l8_silent_pass(tmp_path):
    _put_rtl(tmp_path, "crc8.v",
             "module crc8;\n  always @(*) crc_out <= 8'hFF;\nendmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "skip" in r.stdout.lower()


# 3. L8 but no RTL — silent skip.
def test_no_rtl_silent_pass(tmp_path):
    _put_l8(tmp_path, {
        "crc8_constants": [
            {"name": "CRC_SEED", "value": 255},
        ]
    })
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "skip" in r.stdout.lower()


# 4. Positive PASS — RTL init=0xFF, L8 CRC_SEED=255 (=0xFF), refl matches.
def test_positive_consistent_pass(tmp_path):
    _put_rtl(tmp_path, "crc8.v", """
module crc8;
  always @(posedge clk) begin
    if (rst) crc_out <= 8'hFF;
    else if (start) crc_out <= 8'hFF;
    else crc_out <= (crc_out >> 1) ^ 8'h8C;
  end
endmodule
""")
    _put_l8(tmp_path, {
        "crc8_constants": [
            {"name": "CRC_POLY", "value": 49},
            {"name": "CRC_SEED", "value": 255},
            {"name": "CRC_REFLECTED_POLY", "value": 140},
        ]
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout
    assert "0xFF" in r.stdout


# 5. Negative FAIL — RTL says init=0xFF, L8 says CRC_SEED=0 (0x00).
#    This is the v0.119.32 bug.
def test_init_mismatch_fails(tmp_path):
    _put_rtl(tmp_path, "crc8.v", """
module crc8;
  always @(*) crc_out <= 8'hFF;
  always @(*) tmp = (crc_in >> 1) ^ 8'h8C;
endmodule
""")
    _put_l8(tmp_path, {
        "crc8_constants": [
            {"name": "CRC_POLY", "value": 49},
            {"name": "CRC_SEED", "value": 0},
            {"name": "CRC_REFLECTED_POLY", "value": 140},
        ]
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "FAIL" in r.stdout
    assert "init" in r.stdout.lower()


# 6. Negative FAIL — RTL has reflected 0x8C, L8 says 0xE0 (wrong).
def test_reflected_mismatch_fails(tmp_path):
    _put_rtl(tmp_path, "crc8.v", """
module crc8;
  always @(*) crc_out <= 8'hFF;
  always @(*) tmp = (crc_in >> 1) ^ 8'h8C;
endmodule
""")
    _put_l8(tmp_path, {
        "crc8_constants": [
            {"name": "CRC_SEED", "value": 255},
            {"name": "CRC_REFLECTED_POLY", "value": 0xE0},
        ]
    })
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "reflect" in r.stdout.lower()


# 7. Waiver allows RTL/L8 drift.
def test_waiver_allows_drift(tmp_path):
    _put_rtl(tmp_path, "crc8.v",
             "module m; always @(*) crc_out <= 8'hFF; "
             "always @(*) t = (i>>1) ^ 8'h8C; endmodule\n")
    _put_l8(tmp_path, {
        "crc8_constants": [
            {"name": "CRC_SEED", "value": 0},
        ]
    })
    (tmp_path / "waivers.json").write_text(json.dumps({
        "crc_constants_rtl_doc_drift_intentional":
            "Variant SKU uses 0x00 init; full-mask RTL has 0xFF; "
            "drift signed off by lead 2026-05-01."
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS_WITH_WAIVER" in r.stdout


# 8. crc_parameters block accepted as L8 source.
def test_crc_parameters_block_accepted(tmp_path):
    _put_rtl(tmp_path, "crc8.v",
             "module m; always @(*) crc_out <= 8'hFF; "
             "always @(*) t = (i>>1) ^ 8'h8C; endmodule\n")
    _put_l8(tmp_path, {
        "crc_parameters": {
            "polynomial_hex": "0x31",
            "polynomial_reflected_hex": "0x8C",
            "init_hex": "0xFF",
            "bit_order": "lsb_first",
        }
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout
