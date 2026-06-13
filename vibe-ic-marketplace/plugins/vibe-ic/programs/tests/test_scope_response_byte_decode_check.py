#!/usr/bin/env python3
"""Tests for scope_response_byte_decode_check.py (P0.3 gate)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "scope_response_byte_decode_check.py"


def _run(tmp_path: Path, *extra_args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", "-", *extra_args],
        capture_output=True, text=True,
    )


# -- L2 timing fixture (pulse-width protocol) ------------------------------

L2_TIMING = {
    "bit_0_low_us": 6.0,
    "bit_1_low_us": 1.0,
    "br_low_us": 14.0,
    "ibt_gap_us": 20.0,
    "t_srs_min_us": 40.0,
}


def _make_scope_csv(path: Path, pulses: list[tuple[float, float, float]]) -> None:
    """Write scope CSV. Each tuple: (time_us, voltage_high, voltage_low)
    generates a HIGH→LOW→HIGH transition.  pulses = [(start, LOW_dur, gap_after), ...]
    """
    rows = []
    t = 0.0
    for low_start, low_dur, gap in pulses:
        while t < low_start:
            rows.append(f"{t:.6f},3.3")
            t += 0.1
        end_low = low_start + low_dur
        while t < end_low:
            rows.append(f"{t:.6f},0.0")
            t += 0.1
        t = end_low + gap
    rows.append(f"{t:.6f},3.3")
    path.write_text("\n".join(rows) + "\n")


def _make_bit_pulses(byte_val: int, timing: dict, start_us: float) -> list[tuple[float, float, float]]:
    """Generate LOW pulses for one byte MSB-first."""
    pulses = []
    t = start_us
    for i in range(7, -1, -1):
        bit = (byte_val >> i) & 1
        dur = timing["bit_1_low_us"] if bit else timing["bit_0_low_us"]
        pulses.append((t, dur, 0.5))
        t += dur + 0.5
    return pulses


def _setup_l2(tmp_path: Path) -> None:
    gen = tmp_path / "phase1" / "generated_docs"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "L2_FRS.json").write_text(json.dumps(L2_TIMING))


def _setup_oracle(tmp_path: Path, expected_hex: str) -> None:
    gen = tmp_path / "phase1" / "generated_docs"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "L10_TB_CONFORMANCE.json").write_text(json.dumps({
        "opcode_oracle_vectors": [{
            "name": "GET_ID",
            "opcode_hex": "0x74",
            "expected_response_hex": expected_hex,
        }]
    }))


# -- Tests ------------------------------------------------------------------

def test_skip_no_scope(tmp_path):
    """No scope CSV → PASS (skip)."""
    _setup_l2(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["passed"] is True
    rules = [f["rule"] for f in j["findings"]]
    assert "SKIP_NO_SCOPE" in rules


def test_skip_no_l2(tmp_path):
    """Scope CSV present but no L2 timing → PASS (skip)."""
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "scope_capture.csv").write_text("0.0,3.3\n1.0,0.0\n2.0,3.3\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["passed"] is True
    rules = [f["rule"] for f in j["findings"]]
    assert "SKIP_NO_L2" in rules


def test_decode_no_oracle(tmp_path):
    """Scope + L2 but no oracle → decode succeeds, PASS (informational)."""
    _setup_l2(tmp_path)
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    pulses = _make_bit_pulses(0xAB, L2_TIMING, 100.0)
    _make_scope_csv(reports / "scope_capture.csv", pulses)
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["passed"] is True
    rules = [f["rule"] for f in j["findings"]]
    assert "SCOPE_DECODE_OK" in rules


def test_empty_scope(tmp_path):
    """Scope CSV exists but no detectable pulses → PASS (skip)."""
    _setup_l2(tmp_path)
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "scope_capture.csv").write_text("0.0,3.3\n1.0,3.3\n2.0,3.3\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["passed"] is True
    rules = [f["rule"] for f in j["findings"]]
    assert "SKIP_NO_SCOPE" in rules


def test_exit2_missing_dir():
    r = subprocess.run(
        [sys.executable, str(PROG), "/nonexistent/path/xyz"],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


def test_help():
    r = subprocess.run(
        [sys.executable, str(PROG), "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "scope_response_byte_decode_check" in r.stdout
