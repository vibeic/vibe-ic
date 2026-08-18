#!/usr/bin/env python3
"""Tests for tristate_active_drive_check.py (P1.1)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "tristate_active_drive_check.py"


def _run(tmp_path: Path, *extra_args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", "-", *extra_args],
        capture_output=True,
        text=True,
    )


def test_pass_active_drive(tmp_path):
    """RTL with active-drive tristate → PASS."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top.v").write_text(
        "module top(inout wire bus_data);\n"
        "  wire oe, data_out;\n"
        "  assign bus_data = oe ? data_out : 1'bz;\n"
        "endmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    assert j["passed"] is True
    assert j["summary"]["active_drive_patterns"] >= 1


def test_fail_open_drain(tmp_path):
    """Pure open-drain pattern on a non-half-duplex pad → FAIL.

    Wave 35: a pad named `id_bus` is now itself sufficient evidence
    of half-duplex single-wire and is deferred to LL-17. To exercise
    the open-drain FAIL path on this gate, use a pad name that is
    NOT in HALF_DUPLEX_PIN_HINTS (e.g., generic `dbg_bus`).
    """
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "phy.v").write_text(
        "module phy(inout wire dbg_bus);\n"
        "  wire drive_low;\n"
        "  assign dbg_bus = drive_low ? 1'b0 : 1'bz;\n"
        "endmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 1
    j = json.loads(r.stdout)
    assert j["passed"] is False
    rules = [f["rule"] for f in j["findings"]]
    assert "OPEN_DRAIN_FPGA_WARN" in rules


def test_skip_i2c(tmp_path):
    """L2 says a multi-master protocol -> VACUOUS (#521): open-drain is correct there, so this gate holds no opinion."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "i2c.v").write_text(
        "module i2c(inout wire sda);\n"
        "  assign sda = drive ? 1'b0 : 1'bz;\n"
        "endmodule\n"
    )
    gen = tmp_path / "phase1" / "generated_docs"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "L2_functional_spec.json").write_text(
        json.dumps({"protocol_type": "i2c"})
    )
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    j = json.loads(r.stdout)
    assert j["passed"] is True
    rules = [f["rule"] for f in j["findings"]]
    assert "SKIP_MULTI_MASTER" in rules


def test_skip_no_inout(tmp_path):
    """RTL with no inout ports -> VACUOUS (#521)."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "core.v").write_text(
        "module core(input clk, output reg [7:0] data);\n"
        "endmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    j = json.loads(r.stdout)
    assert j["passed"] is True
    rules = [f["rule"] for f in j["findings"]]
    assert "SKIP_NO_INOUT" in rules


def test_exit2_missing_dir():
    """Nonexistent path → exit 2."""
    r = subprocess.run(
        [sys.executable, str(PROG), "/nonexistent/path/xyz"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2


def test_skip_when_half_duplex_single_wire_owns_via_ll17(tmp_path):
    """v0.119.19 fix: when L2 has half-duplex timing keys (tSRS / ibt /
    frame_end_gap), LL-17 (half_duplex_wrapper_open_drain_check) is the
    authoritative gate for pad form. P1.1 must SKIP rather than emit a
    contradicting WARN on the same pad. Without this fix, the agent
    sees `[FAIL]` from P1.1 and `PASS` from LL-17 simultaneously and
    can't tell which form is correct."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    # Open-drain pattern that LL-17 explicitly REQUIRES (oracle-validated).
    (rtl / "fpga_top.sv").write_text(
        "module fpga_top(inout wire id_bus);\n"
        "  wire oe, tx;\n"
        "  assign id_bus = (oe && !tx) ? 1'b0 : 1'bz;\n"
        "endmodule\n"
    )
    gen = tmp_path / "phase1" / "generated_docs"
    gen.mkdir(parents=True, exist_ok=True)
    # L2 has half-duplex timing keys → triggers the new skip path
    (gen / "L2_FRS.json").write_text(json.dumps({
        "tSRS_us": [20.0, 80.0],
        "ibt_us":  [8.5, 22.0],
        "frame_end_gap_us": 27.0,
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    j = json.loads(r.stdout)
    assert j["passed"] is True
    rules = [f["rule"] for f in j["findings"]]
    assert "SKIP_HALF_DUPLEX_SINGLE_WIRE" in rules, \
        f"expected half-duplex skip, got rules={rules}"
    # v0.119.20: SKIP is now pad-scoped; summary lists the skipped pad.
    assert "id_bus" in j["summary"]["half_duplex_pads_skipped"]
    # The half-duplex pad's line should NOT also have produced an
    # OPEN_DRAIN_FPGA_WARN.
    assert "OPEN_DRAIN_FPGA_WARN" not in rules


def test_pad_scoped_skip_other_tristate_still_warned(tmp_path):
    """v0.119.20: when project is half-duplex AND has BOTH a half-duplex
    pad (handed to LL-17) AND an unrelated debug tristate pad with
    `oe ? 1'b0 : 1'bz`, the half-duplex pad must be SKIPped per-pad
    while the debug pad still gets OPEN_DRAIN_FPGA_WARN. Previously
    the project-wide SKIP swallowed both."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "fpga_top.sv").write_text(
        "module fpga_top(inout wire id_bus, inout wire dbg_pad);\n"
        "  wire oe, tx, dbg_oe;\n"
        "  // half-duplex pad — LL-17's endorsed split-data form\n"
        "  assign id_bus  = (oe && !tx) ? 1'b0 : 1'bz;\n"
        "  // unrelated debug tristate — pure tristate, P1.1 must still WARN\n"
        "  assign dbg_pad = dbg_oe ? 1'b0 : 1'bz;\n"
        "endmodule\n"
    )
    gen = tmp_path / "phase1" / "generated_docs"
    gen.mkdir(parents=True, exist_ok=True)
    (gen / "L2_FRS.json").write_text(json.dumps({
        "tSRS_us": [20.0, 80.0],
        "ibt_us":  [8.5, 22.0],
    }))
    r = _run(tmp_path)
    j = json.loads(r.stdout)
    rules = [f["rule"] for f in j["findings"]]
    # id_bus → SKIP
    assert "SKIP_HALF_DUPLEX_SINGLE_WIRE" in rules
    assert "id_bus" in j["summary"]["half_duplex_pads_skipped"]
    assert "dbg_pad" not in j["summary"]["half_duplex_pads_skipped"]
    # dbg_pad → still WARNed
    assert "OPEN_DRAIN_FPGA_WARN" in rules, \
        "non-half-duplex tristate pad must still be analyzed"
    # Verdict FAIL because debug pad has open-drain with no active-drive
    assert j["passed"] is False
    assert r.returncode == 1


def test_no_skip_when_l2_absent(tmp_path):
    """Without L2 timing keys, the half-duplex skip must NOT engage —
    a generic FPGA project with active-drive RTL still gets evaluated
    by P1.1 normally."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top.v").write_text(
        "module top(inout wire bus_data);\n"
        "  assign bus_data = oe ? data_out : 1'bz;\n"
        "endmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    j = json.loads(r.stdout)
    rules = [f["rule"] for f in j["findings"]]
    # Should NOT be the half-duplex skip; should be normal evaluation
    assert "SKIP_HALF_DUPLEX_SINGLE_WIRE" not in rules


def test_wave35_pad_name_alone_triggers_skip(tmp_path):
    """Wave 35: an inout port named id_bus is itself sufficient evidence
    of half-duplex single-wire; pad-form verdict is deferred to LL-17
    even when L2 schema doesn't carry tSRS/ibt timing keys.
    """
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "chip_top.sv").write_text(
        "module chip_top(input clk, inout wire id_bus);\n"
        "  wire id_bus_drive_low;\n"
        "  assign id_bus = id_bus_drive_low ? 1'b0 : 1'bz;\n"
        "endmodule\n"
    )
    # No L2 docs at all — the pad name is the only evidence
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    j = json.loads(r.stdout)
    rules = [f["rule"] for f in j["findings"]]
    assert "SKIP_HALF_DUPLEX_SINGLE_WIRE" in rules
