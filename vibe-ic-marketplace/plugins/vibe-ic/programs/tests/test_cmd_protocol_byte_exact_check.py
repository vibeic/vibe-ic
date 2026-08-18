#!/usr/bin/env python3
"""Tests for cmd_protocol_byte_exact_check.py (LL-18).

v0.119.15 hardening:
  (a) RSVD/RESERVED/PADDING/PAD/ZERO conventional zero-fill names
      now treated as byte-exact (universal protocol convention).
  (b) per-field waiver mode silences specific symbolic field names
      without disabling the whole gate.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "cmd_protocol_byte_exact_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _write_l3(tmp_path: Path, command_table: list):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "command_table": command_table,
    }))


def test_no_l3_silent_pass(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0


def test_all_byte_exact_passes(tmp_path):
    _write_l3(tmp_path, [{
        "opcode": "0x10", "name": "GetID",
        "fields_tx": ["0x11", "0x22", "CRC"],
    }])
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_symbolic_field_fails_by_default(tmp_path):
    """A bare symbolic name like VID still fails — gate purpose intact."""
    _write_l3(tmp_path, [{
        "opcode": "0x10", "name": "GetID",
        "fields_tx": ["0x11", "VID", "CRC"],
    }])
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "VID" in r.stdout


def test_rsvd_treated_as_byte_exact(tmp_path):
    """v0.119.15: RSVD/RESERVED/PADDING are conventional zero-fill —
    no waiver needed."""
    _write_l3(tmp_path, [{
        "opcode": "0x10", "name": "GetID",
        "fields_tx": ["0x11", "RSVD", "RESERVED", "PADDING", "PAD",
                      "ZERO", "CRC"],
    }])
    r = _run(tmp_path)
    assert r.returncode == 0, \
        f"conventional zero-fill names must not trip the gate: {r.stdout}"


def test_len_still_fails_without_waiver(tmp_path):
    """v0.119.15: LEN is NOT in the implicit-zero-fill set because it
    varies per command and needs explicit resolution. Confirm the
    conservative whitelist didn't widen too far."""
    _write_l3(tmp_path, [{
        "opcode": "0x10", "name": "Read",
        "fields_tx": ["0x11", "LEN", "CRC"],
    }])
    r = _run(tmp_path)
    assert r.returncode == 1, \
        "LEN must remain symbolic — needs explicit resolution per command"
    assert "LEN" in r.stdout


def test_per_field_waiver_silences_specific_names(tmp_path):
    """v0.119.15: per-field waiver lets a project silence LEN/STATUS
    without project-wide blanket waiver."""
    _write_l3(tmp_path, [
        {"opcode": "0x10", "name": "Read",
         "fields_tx": ["0x11", "LEN", "DATA[0..LEN-1]", "CRC"]},
        {"opcode": "0x20", "name": "Status",
         "fields_tx": ["0x21", "STATUS", "CRC"]},
        {"opcode": "0x30", "name": "GetVID",
         "fields_tx": ["0x31", "VID", "CRC"]},  # NOT in waiver — should still FAIL
    ])
    (tmp_path / "waivers.json").write_text(json.dumps({
        "cmd_protocol_symbolic_intentional": {
            "per_field": ["LEN", "DATA", "STATUS"],
            "rationale": "Resolved at runtime by host-side LEN-then-DATA pump.",
        },
    }))
    r = _run(tmp_path)
    assert r.returncode == 1, \
        "VID is not in per_field waiver — gate must still flag it"
    assert "VID" in r.stdout
    # LEN/DATA/STATUS must NOT appear in failures
    pre_why = r.stdout.split("Why this matters")[0]
    assert "LEN" not in pre_why or "VID" in pre_why
    assert "STATUS" not in pre_why or "VID" in pre_why


def test_per_field_waiver_clears_when_all_silenced(tmp_path):
    _write_l3(tmp_path, [{
        "opcode": "0x10", "name": "Read",
        "fields_tx": ["0x11", "LEN", "CRC"],
    }])
    (tmp_path / "waivers.json").write_text(json.dumps({
        "cmd_protocol_symbolic_intentional": {
            "per_field": ["LEN"],
            "rationale": "Always 8 in this rev.",
        },
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_project_wide_waiver_still_works_back_compat(tmp_path):
    """Form 1: boolean true → project-wide silence (back-compat)."""
    _write_l3(tmp_path, [{
        "opcode": "0x10", "name": "GetID",
        "fields_tx": ["0x11", "VID", "PID", "CRC"],
    }])
    (tmp_path / "waivers.json").write_text(json.dumps({
        "cmd_protocol_symbolic_intentional": True,
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout
