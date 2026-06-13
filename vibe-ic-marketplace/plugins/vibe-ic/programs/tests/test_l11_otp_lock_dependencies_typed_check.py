#!/usr/bin/env python3
"""Tests for l11_otp_lock_dependencies_typed_check.py (Wave 38 / B5)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "l11_otp_lock_dependencies_typed_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make(tmp_path, l11):
    proj = tmp_path / "p"
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L11_OTP_CONTENT.json").write_text(
        json.dumps(l11)
    )
    return proj


def test_skip_when_no_l11(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    r = _run(proj)
    assert r.returncode == 2


def test_skip_when_no_lock_bits(tmp_path):
    proj = _make(tmp_path, {"otp_table": []})
    r = _run(proj)
    assert r.returncode == 2


def test_fail_when_locks_lack_affects(tmp_path):
    proj = _make(tmp_path, {"otp_lock_bits": [
        {"name": "lock_0x40", "address": "0x40"},
    ]})
    r = _run(proj)
    assert r.returncode == 1
    assert "affects" in r.stdout


def test_fail_when_locks_lack_trigger_value(tmp_path):
    proj = _make(tmp_path, {"otp_lock_bits": [
        {"name": "lock_0x40", "address": "0x40",
         "affects": ["0x60..0x7F"]},
    ]})
    r = _run(proj)
    assert r.returncode == 1
    assert "trigger" in r.stdout


def test_pass_when_typed_full(tmp_path):
    proj = _make(tmp_path, {"otp_lock_bits": [
        {"name": "lock_0x40", "address": "0x40",
         "affects": ["0x60..0x7F"], "trigger_value": "0x80",
         "evidence": "EXAMPLE_CHIP_OTP_Table.txt:30"},
        {"name": "lock_master", "bit": "0x41",
         "protects_range": "0x00..0x5F", "arming_pattern": "0xFF"},
    ]})
    r = _run(proj)
    assert r.returncode == 0
    assert "PASS" in r.stdout


# Wave 43 (v0.119.75) — ic_class_profile SKIP case.
def test_skip_on_bare_fpga(tmp_path):
    """Bare-FPGA scaffolds have no OTP image."""
    proj = tmp_path / "p"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "facts.yaml").write_text("name: my_fpga_eval\n")
    r = _run(proj)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "ic_class=bare_fpga" in r.stdout
