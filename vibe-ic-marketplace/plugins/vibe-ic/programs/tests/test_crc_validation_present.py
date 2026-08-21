#!/usr/bin/env python3
"""Tests for crc_validation_present.py — Wave 58 BACKLOG-v12 P0.3 gate.

Covers four applicability paths:
  1. POSITIVE_PASS  — L3 declares CRC + RTL instantiates engine + frame_ok
                      consumes crc_q (or assigns crc_ok wire).
  2. POSITIVE_FAIL  — L3 declares CRC + RTL instantiates engine but
                      validate / frame_ok decision path does NOT reference
                      any CRC output signal.
  3. SKIP_NON_APPLICABLE — L3 has crc_parameters but no CRC engine
                      instantiation in rtl/ (covered by a different gate).
  4. SKIP_NO_CONSTRUCT  — No L3 file at all (no crc_parameters declared).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "crc_validation_present.py"


def _run(project_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project_dir)],
        capture_output=True, text=True,
    )


def _write_l3_with_crc(project: Path) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "doc_class": "cmd_protocol",
        "ic_name": "TEST_IC",
        "crc_parameters": {
            "polynomial_hex": "0x31",
            "init_hex": "0xFF",
        },
    }))


def _write_rtl_with_crc_engine(project: Path, frame_ok_uses_crc: bool) -> None:
    """Write a CRC engine + a top module.  When frame_ok_uses_crc is
    True, the top module's frame_ok wire references crc_q.
    """
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    # CRC engine module — name `crc8` (matches _CRC_INST_RE).
    (rtl / "crc8.v").write_text(
        "module crc8(input clk, input data_bit, output reg [7:0] crc_q);\n"
        "  always @(posedge clk) begin\n"
        "    if (crc_q[0] ^ data_bit) crc_q <= {1'b0, crc_q[7:1]} ^ 8'h8C;\n"
        "    else                     crc_q <= {1'b0, crc_q[7:1]};\n"
        "  end\n"
        "endmodule\n"
    )
    # Top module that instantiates crc8.
    if frame_ok_uses_crc:
        # Validate-state body references crc_q.
        top_body = (
            "module chip_top(input clk, output reg tx_start);\n"
            "  wire [7:0] crc_q;\n"
            "  crc8 u_crc(.clk(clk), .data_bit(1'b0), .crc_q(crc_q));\n"
            "  wire crc_ok = (crc_q == 8'h00);\n"
            "  wire frame_ok = crc_ok;\n"
            "  always @* begin tx_start = frame_ok; end\n"
            "endmodule\n"
        )
    else:
        top_body = (
            "module chip_top(input clk, output reg tx_start);\n"
            "  wire [7:0] crc_q;\n"
            "  crc8 u_crc(.clk(clk), .data_bit(1'b0), .crc_q(crc_q));\n"
            "  wire frame_ok = 1'b1;\n"  # ignores crc_q
            "  always @* begin tx_start = frame_ok; end\n"
            "endmodule\n"
        )
    (rtl / "chip_top.sv").write_text(top_body)


# -- Test 1: POSITIVE_PASS — frame_ok consumes crc_q --

def test_positive_pass_crc_in_frame_ok(tmp_path):
    _write_l3_with_crc(tmp_path)
    _write_rtl_with_crc_engine(tmp_path, frame_ok_uses_crc=True)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "validate" in r.stdout.lower() or "frame_ok" in r.stdout.lower() \
        or "decision path" in r.stdout.lower()


# -- Test 2: POSITIVE_FAIL — engine instantiated but unused in validate --

def test_positive_fail_crc_unused(tmp_path):
    _write_l3_with_crc(tmp_path)
    _write_rtl_with_crc_engine(tmp_path, frame_ok_uses_crc=False)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "crc" in r.stdout.lower()


# -- Test 3: SKIP_NON_APPLICABLE — L3 has CRC but no engine in rtl/ --

def test_skip_non_applicable_no_engine(tmp_path):
    _write_l3_with_crc(tmp_path)
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    # A non-CRC module — no crc engine instantiation.
    (rtl / "byte_counter.v").write_text(
        "module byte_counter(input clk, output reg [7:0] q);\n"
        "  always @(posedge clk) q <= q + 1;\n"
        "endmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "no CRC engine" in r.stdout or "crc_completeness_check" \
        in r.stdout


# -- Test 4: SKIP_NO_CONSTRUCT — no L3 file at all --

def test_skip_no_l3_crc(tmp_path):
    # Empty project — no generated_docs/, no rtl/.
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "no L3 crc_parameters" in r.stdout or \
        "crc_parameters" in r.stdout


# -- Test 5: PASS_WITH_WAIVER --

def test_pass_with_waiver(tmp_path):
    _write_l3_with_crc(tmp_path)
    _write_rtl_with_crc_engine(tmp_path, frame_ok_uses_crc=False)
    (tmp_path / "waivers.json").write_text(json.dumps({
        "crc_validation_explicit_bypass":
        "Project ships with externally validated CRC checker; ticket "
        "VC-1234 tracks promotion to in-tree.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout


# -- Test 6: usage error --

def test_usage_error(tmp_path):
    r = subprocess.run([sys.executable, str(PROG)], capture_output=True,
                       text=True)
    assert r.returncode == 2


# -- Test 7 (Wave 82 Fix F): bare_fpga IC + L3 carries crc_parameters --
# Without the secondary trigger, bare_fpga would silently SKIP and
# wrong-CRC frames would PASS. With the fix, presence of L3
# crc_parameters forces the gate to evaluate FAIL/PASS regardless of
# class.

def _write_bare_fpga_l1_l2(project: Path) -> None:
    """L1/L2 with NO commands, NO analog, NO FSM — drives detect_ic_class
    to classify as bare_fpga."""
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "doc_class": "datasheet",
        "ic_name": "FPGA_EVAL",
        "description": "Bare FPGA evaluation kit",
    }))
    (gd / "L2_FRS.json").write_text(json.dumps({
        "doc_class": "frs",
        "ic_name": "FPGA_EVAL",
        "requirements": ["clock distribution"],
    }))


def test_bare_fpga_with_l3_crc_falls_through_to_fail(tmp_path):
    """bare_fpga IC + L3.crc_parameters + CRC engine instantiated but
    not consumed → FAIL (not SKIP).  This is Wave 82 Fix F: CRC
    consumption is evidence-driven (L3), not class-driven."""
    _write_bare_fpga_l1_l2(tmp_path)
    # Add L3 with only crc_parameters (no `commands`) so L3 doesn't
    # flip has_command_protocol.
    (tmp_path / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json").write_text(
        json.dumps({
            "doc_class": "cmd_protocol",
            "ic_name": "FPGA_EVAL",
            "crc_parameters": {
                "polynomial_hex": "0x31",
                "init_hex": "0xFF",
            },
            # no `commands` / `opcodes` — keeps has_command_protocol=False
        })
    )
    _write_rtl_with_crc_engine(tmp_path, frame_ok_uses_crc=False)
    r = _run(tmp_path)
    # MUST not silently SKIP — Fix F: secondary trigger on L3 evidence.
    assert "SKIP" not in r.stdout or "FAIL" in r.stdout, (
        f"bare_fpga + L3 crc_parameters MUST not silent-SKIP. "
        f"stdout={r.stdout!r}"
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout


def test_bare_fpga_with_l3_crc_passes_when_consumed(tmp_path):
    """bare_fpga IC + L3.crc_parameters + frame_ok consumes crc_q →
    PASS (the Fix F secondary trigger correctly evaluates positive)."""
    _write_bare_fpga_l1_l2(tmp_path)
    (tmp_path / "phase1" / "generated_docs" / "L3_CMD_PROTOCOL.json").write_text(
        json.dumps({
            "doc_class": "cmd_protocol",
            "ic_name": "FPGA_EVAL",
            "crc_parameters": {
                "polynomial_hex": "0x31",
                "init_hex": "0xFF",
            },
        })
    )
    _write_rtl_with_crc_engine(tmp_path, frame_ok_uses_crc=True)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "SKIP" not in r.stdout
