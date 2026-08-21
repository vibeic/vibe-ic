#!/usr/bin/env python3
"""Tests for scope_reply_preamble_check.py — Wave 58 BACKLOG-v12 P0.4.

Covers four applicability paths:
  1. POSITIVE_PASS — half-duplex project + reply CSV + BR_MIN declared,
                     no isolated BR-class LOW pulse in chip-reply window.
  2. POSITIVE_FAIL — half-duplex project + reply CSV + BR_MIN declared,
                     ISOLATED BR-class LOW pulse in 2nd-half (chip reply).
  3. SKIP_NON_APPLICABLE — half-duplex project but no L8.br_min and no
                     rtl_constants BR_MIN literal (Wave 58 line 28-29
                     applicability boundary).
  4. SKIP_NO_CONSTRUCT — non half-duplex project (no L3 half_duplex
                     declaration, no wake_gen/id_bus RTL).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "scope_reply_preamble_check.py"


def _run(project_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project_dir)],
        capture_output=True, text=True,
    )


def _make_half_duplex_project(project: Path) -> None:
    """Mark project as half-duplex via L3 + add wake_gen module so
    is_half_duplex_project() returns True.
    """
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "doc_class": "cmd_protocol",
        "ic_name": "TEST_IC",
        "physical_layer": "half_duplex single_wire id_bus",
    }))
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "wake_gen.v").write_text(
        "module wake_gen(input clk, output reg pulse);\n"
        "endmodule\n"
    )


def _write_l8_br_min(project: Path, br_min: int) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L8_RTL_CONSTANTS.json").write_text(json.dumps({
        "rx_classifier_ticks": {"br_min": br_min, "h0_max": 612},
    }))


def _write_csv(path: Path, voltages: list) -> None:
    """Single-column scope CSV.  Default sample interval = 100 ns."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# voltage"]
    for v in voltages:
        lines.append(f"{v}")
    path.write_text("\n".join(lines) + "\n")


# -- Test 1: POSITIVE_PASS — reply CSV with no BR-class LOW in 2nd half --

def test_positive_pass_clean_reply(tmp_path):
    _make_half_duplex_project(tmp_path)
    _write_l8_br_min(tmp_path, br_min=613)
    # 2000 sample CSV, all 3.3 V (HIGH) — no LOW pulses at all.
    csv = tmp_path / "reports" / "scope_captures" / "chip_reply_5ms.csv"
    _write_csv(csv, [3.3] * 2000)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    # Either PASS (some samples inspected) or SKIP (no LOW samples).
    assert "PASS" in r.stdout or "SKIP" in r.stdout
    assert "FAIL" not in r.stdout


# -- Test 2: POSITIVE_FAIL — isolated BR-class LOW in 2nd half --

def test_positive_fail_br_in_reply(tmp_path):
    _make_half_duplex_project(tmp_path)
    # br_min = 100 ticks * 20 ns/tick = 2000 ns = 20 samples @100 ns/sample.
    _write_l8_br_min(tmp_path, br_min=100)
    # 1000 samples HIGH, then 50-sample LOW (>= 20 sample BR_MIN), then HIGH.
    voltages = [3.3] * 1000 + [0.0] * 50 + [3.3] * 950
    csv = tmp_path / "reports" / "scope_captures" / "chip_reply_5ms.csv"
    _write_csv(csv, voltages)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "BR-class" in r.stdout


# -- Test 3: SKIP_NON_APPLICABLE — half-duplex but no BR_MIN declared --

def test_skip_no_br_min(tmp_path):
    _make_half_duplex_project(tmp_path)
    # No L8 br_min, no rtl_constants_pkg BR_MIN.
    csv = tmp_path / "reports" / "scope_captures" / "chip_reply.csv"
    _write_csv(csv, [3.3, 0.0, 3.3, 0.0, 3.3])
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "BR_MIN" in r.stdout


# -- Test 4: SKIP_NO_CONSTRUCT — non half-duplex project --

def test_skip_non_half_duplex(tmp_path):
    # No L3 half_duplex hint, no wake_gen / id_bus RTL.
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "spi_master.v").write_text(
        "module spi_master(input clk);\nendmodule\n"
    )
    _write_l8_br_min(tmp_path, br_min=613)
    csv = tmp_path / "reports" / "scope_captures" / "chip_reply.csv"
    _write_csv(csv, [3.3, 0.0, 3.3])
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "half-duplex" in r.stdout.lower() or "single-wire" in \
        r.stdout.lower()


# -- Test 5: SKIP — half-duplex but no scope CSV at all --

def test_skip_no_scope_csv(tmp_path):
    _make_half_duplex_project(tmp_path)
    _write_l8_br_min(tmp_path, br_min=613)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "scope" in r.stdout.lower()


# -- Test 6: PASS_WITH_WAIVER --

def test_pass_with_waiver(tmp_path):
    _make_half_duplex_project(tmp_path)
    _write_l8_br_min(tmp_path, br_min=100)
    voltages = [3.3] * 1000 + [0.0] * 50 + [3.3] * 950
    csv = tmp_path / "reports" / "scope_captures" / "chip_reply_5ms.csv"
    _write_csv(csv, voltages)
    (tmp_path / "waivers.json").write_text(json.dumps({
        "chip_reply_br_preamble_intentional":
        "Bus turnaround per EXAMPLE_PROTOCOL-class spec section 4.2; ticket TR-77 "
        "tracks scope re-capture after revised TX driver.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout
