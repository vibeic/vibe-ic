#!/usr/bin/env python3
"""Tests for frame_end_gap_in_l8_check.py (LL-2)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "frame_end_gap_in_l8_check.py"


def _run(tmp_path: Path, strict: bool = False):
    cmd = [sys.executable, str(PROG), str(tmp_path),
           "--json", str(tmp_path / "rep.json")]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


def _make_l2_half_duplex(tmp_path: Path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
    }))


def _make_l8(tmp_path: Path, content: dict):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L8_RTL_CONSTANTS.json").write_text(json.dumps(content))


def test_non_half_duplex_skipped(tmp_path):
    # No L2 with half-duplex markers
    r = _run(tmp_path)
    assert r.returncode == 0
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["summary"]["is_half_duplex"] is False


def test_half_duplex_missing_l8_errors(tmp_path):
    _make_l2_half_duplex(tmp_path)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "L8_RTL_CONSTANTS_MISSING"
               for f in rep["findings"])


def test_half_duplex_l8_without_frame_end_gap_errors(tmp_path):
    _make_l2_half_duplex(tmp_path)
    _make_l8(tmp_path, {
        "internal_clock_MHz": 50,
        "tSRS_min_ticks_50MHz": 1500,
    })
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "L8_FRAME_END_GAP_MISSING"
               for f in rep["findings"])


def test_half_duplex_l8_with_frame_end_gap_passes(tmp_path):
    _make_l2_half_duplex(tmp_path)
    _make_l8(tmp_path, {
        "internal_clock_MHz": 50,
        "frame_end_gap_us": 27.0,
    })
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_half_duplex_via_l3_command_table(tmp_path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "command_table": [
            {"opcode": "0x74", "response_payload": "0x75 + 6 OTP"}
        ]
    }))
    r = _run(tmp_path, strict=True)
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["summary"]["is_half_duplex"] is True
    # Should ERROR because no L8
    assert r.returncode == 1


def test_non_strict_does_not_fail(tmp_path):
    _make_l2_half_duplex(tmp_path)
    r = _run(tmp_path, strict=False)
    assert r.returncode == 0  # exits 0 without --strict


def test_l3_length_field_mechanism_skips(tmp_path):
    """L3 declares non-gap frame-end mechanism → silent."""
    _make_l2_half_duplex(tmp_path)
    docs = tmp_path / "phase1" / "generated_docs"
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "frame_end_mechanism": "length_field",
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert "length_field" in rep["summary"]["skipped_reason"]


def test_l3_trailing_br_pulse_mechanism_skips(tmp_path):
    _make_l2_half_duplex(tmp_path)
    docs = tmp_path / "phase1" / "generated_docs"
    (docs / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "frame_end_mechanism": "trailing_br_pulse",
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_waiver_skips(tmp_path):
    _make_l2_half_duplex(tmp_path)
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{
            "id": "frame_end_gap_alternative",
            "rationale": "protocol uses length-prefix framing per spec",
        }],
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0
