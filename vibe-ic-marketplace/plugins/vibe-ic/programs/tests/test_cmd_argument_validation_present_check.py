#!/usr/bin/env python3
"""Tests for cmd_argument_validation_present_check.py — see ROOT_CAUSE Area 4."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "cmd_argument_validation_present_check.py"


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True, text=True,
    )


def _l3(tmp_path: Path, commands: list, **extra):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    body = {"commands": commands}
    body.update(extra)
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps(body))


def test_no_l3_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no L3" in r.stdout


def test_no_protocol_silent_pass(tmp_path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "protocol_present": False,
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no protocol" in r.stdout


def test_no_multi_arg_opcode_silent_pass(tmp_path):
    """Every opcode has 0 or 1 arg byte → skip."""
    _l3(tmp_path, [
        {"opcode": "0x70", "arg_bytes": 0},
        {"opcode": "0x71", "arg_bytes": 1},
    ])
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no opcode takes" in r.stdout


def test_predicate_present_passes(tmp_path):
    _l3(tmp_path, [
        {"opcode": "0xE0", "arg_bytes": 4,
         "argument_validation_predicate": "L11.VID == arg[0..1]"},
        {"opcode": "0xE2", "arg_bytes": 2,
         "argument_validation_predicate": "addr in [0x00, 0x7F]"},
    ])
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_missing_predicate_fails(tmp_path):
    _l3(tmp_path, [
        {"opcode": "0xE0", "arg_bytes": 4},
        {"opcode": "0xE2", "arg_bytes": 2,
         "argument_validation_predicate": "addr in [0x00, 0x7F]"},
    ])
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "0xE0" in r.stdout
    assert "lack argument_validation_predicate" in r.stdout


def test_empty_predicate_fails(tmp_path):
    _l3(tmp_path, [
        {"opcode": "0xE6", "arg_bytes": 2,
         "argument_validation_predicate": "   "},
    ])
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "0xE6" in r.stdout


def test_derived_arg_count_from_rx_len_fails(tmp_path):
    """rx_len_bytes=6 implies arg_bytes = 6-2 = 4 inbound args; no
    predicate → FAIL."""
    _l3(tmp_path, [
        {"opcode": "0xEC", "rx_len_bytes": 6},
    ])
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "0xEC" in r.stdout
    assert "4 inbound" in r.stdout


def test_derived_from_fields_rx_skips_framing(tmp_path):
    """fields_rx with framing slots stripped: ['0x77', VID0, VID1, CRC]
    → 2 args (VID0/VID1). Missing predicate → FAIL."""
    _l3(tmp_path, [
        {"opcode": "0xE8",
         "fields_rx": ["0x77", "VID0", "VID1", "CRC"]},
    ])
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "0xE8" in r.stdout


def test_waiver_skips(tmp_path):
    _l3(tmp_path, [{"opcode": "0xE0", "arg_bytes": 4}])
    (tmp_path / "waivers.json").write_text(json.dumps({
        "cmd_argument_validation_present_alternative":
            "Open-protocol variant: chip accepts any host without VID gate",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout
