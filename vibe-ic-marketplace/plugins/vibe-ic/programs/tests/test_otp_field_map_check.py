#!/usr/bin/env python3
"""Tests for otp_field_map_check.py (LL-19)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "otp_field_map_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _write_l3(tmp_path: Path, fields_tx: list,
              opcode: str = "0x10", name: str = "GetID"):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "command_table": [{
            "opcode": opcode, "name": name, "fields_tx": fields_tx,
        }],
    }))


def _write_l11(tmp_path: Path, content: dict):
    (tmp_path / "phase1" / "generated_docs" / "L11_OTP_CONTENT.json").write_text(
        json.dumps(content))


def test_no_l3_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0


def test_only_literal_bytes_passes(tmp_path):
    _write_l3(tmp_path, ["0x11", "0x22", "CRC"])
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no symbolic names" in r.stdout


def test_symbolic_resolved_via_field_map_passes(tmp_path):
    _write_l3(tmp_path, ["0x11", "VID", "SN", "CRC"])
    _write_l11(tmp_path, {
        "field_map": {
            "VID": {"otp_addr": 0x61},
            "SN":  {"otp_addrs": [0x76, 0x77, 0x78]},
        },
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_symbolic_resolved_via_regions_passes(tmp_path):
    """Legacy `regions[]` schema should also resolve."""
    _write_l3(tmp_path, ["0x11", "VID", "CRC"])
    _write_l11(tmp_path, {
        "regions": [
            {"name": "VID", "otp_addr": 0x61},
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_symbolic_unresolved_fails(tmp_path):
    """Symbolic names with no L11 entry → FAIL."""
    _write_l3(tmp_path, ["0x11", "VID", "PID", "CRC"])
    _write_l11(tmp_path, {"field_map": {"VID": {"otp_addr": 0x61}}})
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "PID" in r.stdout


def test_field_map_entry_without_addr_fails(tmp_path):
    """Entry exists but no otp_addr / otp_addrs → still FAIL."""
    _write_l3(tmp_path, ["0x11", "VID", "CRC"])
    _write_l11(tmp_path, {"field_map": {"VID": {"comment": "todo"}}})
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "no otp_addr/otp_addrs" in r.stdout


def test_per_field_waiver_skips(tmp_path):
    _write_l3(tmp_path, ["0x11", "AV", "CRC"])
    (tmp_path / "waivers.json").write_text(json.dumps({
        "otp_field_map_unresolved": [
            "AV — vendor doc names but does not place the byte",
        ],
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
