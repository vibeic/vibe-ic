#!/usr/bin/env python3
"""Tests for dispatch_handler_completeness.py — Wave 58 BACKLOG-v12 P0.2.

Covers four applicability paths:
  1. POSITIVE_PASS — every L3 opcode has a `8'hNN:` case arm.
  2. POSITIVE_FAIL — L3 opcode missing AND default arm is a TX-emitter.
  3. SKIP_NON_APPLICABLE — RTL has no `case (op)` block at all (FSM may
     use if-elif chain or external decoder).
  4. SKIP_NO_CONSTRUCT — no L3 opcodes declared.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "dispatch_handler_completeness.py"


def _run(project_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project_dir)],
        capture_output=True, text=True,
    )


def _write_l3(project: Path, opcodes_hex: list) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "doc_class": "cmd_protocol",
        "ic_name": "TEST_IC",
        "opcodes": [{"hex": h, "name": f"OP_{h[2:]}"} for h in opcodes_hex],
    }))


def _write_rtl_with_dispatch(project: Path, arms_hex: list,
                             default_emits_tx: bool) -> None:
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    arms = "\n".join(
        f"      8'h{h[2:].upper()}: state <= S_REPLY_{h[2:].upper()};"
        for h in arms_hex
    )
    if default_emits_tx:
        default_body = "tx_start <= 1'b1; state <= S_TX_REPLY;"
    else:
        default_body = "state <= S_DROP;"
    (rtl / "main_fsm.sv").write_text(
        "module main_fsm(input clk, input [7:0] op, output reg tx_start);\n"
        "  reg [3:0] state;\n"
        "  always @(posedge clk) begin\n"
        "    case (op)\n"
        f"{arms}\n"
        f"      default: begin {default_body} end\n"
        "    endcase\n"
        "  end\n"
        "endmodule\n"
    )


# -- Test 1: POSITIVE_PASS — all opcodes have case arms --

def test_positive_pass_all_opcodes_handled(tmp_path):
    _write_l3(tmp_path, ["0x70", "0x72", "0x74"])
    _write_rtl_with_dispatch(tmp_path, ["0x70", "0x72", "0x74"],
                             default_emits_tx=False)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "3 L3 opcode" in r.stdout


# -- Test 2: POSITIVE_FAIL — opcode missing + default is spam responder --

def test_positive_fail_missing_with_spam_default(tmp_path):
    _write_l3(tmp_path, ["0x70", "0xE0", "0xE2"])
    _write_rtl_with_dispatch(tmp_path, ["0x70"],  # E0/E2 missing
                             default_emits_tx=True)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL" in r.stdout
    assert "0xE0" in r.stdout
    assert "0xE2" in r.stdout


# -- Test 3: PASS_WITH_WARN — opcode missing but default is silent reject --

def test_pass_warn_missing_with_silent_default(tmp_path):
    _write_l3(tmp_path, ["0x70", "0xE0"])
    _write_rtl_with_dispatch(tmp_path, ["0x70"],  # E0 missing
                             default_emits_tx=False)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout
    assert "silent-reject" in r.stdout
    assert "0xE0" in r.stdout


# -- Test 4: SKIP_NON_APPLICABLE — no `case (op)` block in RTL --

def test_skip_no_case_arms(tmp_path):
    _write_l3(tmp_path, ["0x70"])
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    # RTL with no opcode case block — pure if-elif.
    (rtl / "decoder.v").write_text(
        "module decoder(input [7:0] op, output reg hit);\n"
        "  always @* begin\n"
        "    if (op == 8'h70) hit = 1'b1;\n"
        "    else hit = 1'b0;\n"
        "  end\n"
        "endmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "no opcode dispatch case arms" in r.stdout


# -- Test 5: SKIP_NO_CONSTRUCT — no L3 opcodes at all --

def test_skip_no_l3_opcodes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "blank.v").write_text(
        "module blank(input clk);\n  case (op) 8'h70: ;\n"
        "  default: ; endcase\nendmodule\n"
    )
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "no L3 opcodes" in r.stdout


# -- Test 6: SKIP_NO_RTL --

def test_skip_no_rtl_dir(tmp_path):
    _write_l3(tmp_path, ["0x70"])
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout
    assert "no rtl" in r.stdout.lower()


# -- Test 7: PASS_WITH_WAIVER --

def test_pass_with_waiver(tmp_path):
    _write_l3(tmp_path, ["0x70", "0xE0"])
    _write_rtl_with_dispatch(tmp_path, ["0x70"], default_exits_tx=True) \
        if False else _write_rtl_with_dispatch(tmp_path, ["0x70"],
                                                default_emits_tx=True)
    (tmp_path / "waivers.json").write_text(json.dumps({
        "dispatch_handler_intentionally_default_routed":
        "Reduced opcode set during bring-up; see ticket DH-9876 for "
        "promotion plan to full dispatch.",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout
