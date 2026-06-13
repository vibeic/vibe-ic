#!/usr/bin/env python3
"""Tests for opcode_dispatch_completeness_check.py (Wave 13)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROG = (Path(__file__).resolve().parent.parent
        / "opcode_dispatch_completeness_check.py")


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make_fsm_rtl(opcodes_listed: list[int],
                  default_only: list[int] | None = None,
                  grouped: list[int] | None = None) -> str:
    """Synthesise an FSM RTL whose dispatch arm decodes only opcodes in
    `opcodes_listed`. `grouped` opcodes appear in a multi-opcode arm.
    `default_only` opcodes get nothing — fall through to default."""
    lines = [
        "module main_fsm(input logic clk, input logic [7:0] cmd_op,",
        "                output logic [7:0] resp);",
        "  typedef enum logic [3:0] { S_IDLE, S_DISPATCH } st_t;",
        "  st_t state;",
        "  always_ff @(posedge clk) begin",
        "    case (cmd_op)",
    ]
    for op in opcodes_listed:
        lines.append(f"      8'h{op:02X}: resp <= 8'h{op + 1:02X};")
    if grouped:
        arm = ", ".join(f"8'h{op:02X}" for op in grouped)
        lines.append(f"      {arm}: resp <= 8'h00;")
    lines.append("      default: resp <= 8'h00;")
    lines.append("    endcase")
    lines.append("  end")
    lines.append("endmodule")
    return "\n".join(lines) + "\n"


def _proj(tmp_path: Path,
          l3_opcodes: list[int],
          fsm_rtl: str,
          waivers: dict | None = None) -> Path:
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    l3 = {
        "doc_id": "L3",
        "opcodes": [
            {"op_hex": f"{op:02X}", "name": f"OP_{op:02X}"}
            for op in l3_opcodes
        ],
    }
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps(l3))
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "main_fsm.sv").write_text(fsm_rtl)
    if waivers is not None:
        (proj / "waivers.json").write_text(json.dumps(waivers))
    return proj


def test_full_dispatch_pass(tmp_path):
    ops = [0x70, 0x72, 0x74, 0x76, 0x78, 0x7A, 0xE0, 0xE2]
    proj = _proj(tmp_path, ops, _make_fsm_rtl(ops))
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_missing_opcode_fail(tmp_path):
    ops = [0x70, 0x72, 0x74, 0x76, 0x78, 0x7A, 0xE0, 0xE2]
    rtl_ops = [op for op in ops if op != 0x74]  # drop 0x74
    proj = _proj(tmp_path, ops, _make_fsm_rtl(rtl_ops))
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "OPCODE_DISPATCH_MISSING" in r.stdout
    assert "0x74" in r.stdout.lower() or "0x74" in r.stdout


def test_grouped_warn(tmp_path):
    # 0x70 is decoded individually; 0x72 and 0x74 only appear in a
    # multi-opcode shared arm.
    ops = [0x70, 0x72, 0x74]
    rtl = _make_fsm_rtl([0x70], grouped=[0x72, 0x74])
    proj = _proj(tmp_path, ops, rtl)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    # 0x72 / 0x74 ONLY appear grouped → WARN
    assert "WARN" in r.stdout or "OPCODE_DISPATCH_GROUPED" in r.stdout


def test_no_l3_opcodes_skip(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "phase1" / "generated_docs").mkdir(parents=True)
    (proj / "phase1" / "generated_docs" / "L3_CMD.json").write_text(
        json.dumps({"doc_id": "L3"}))
    (proj / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (proj / "phase2" / "stage1" / "rtl" / "main_fsm.sv").write_text("module main_fsm(); endmodule")
    r = _run(proj)
    assert r.returncode == 0
    assert "SKIP" in r.stdout


def test_with_waiver_pass(tmp_path):
    ops = [0x70, 0x72, 0x74, 0x76]
    rtl_ops = [0x70]
    proj = _proj(
        tmp_path, ops, _make_fsm_rtl(rtl_ops),
        waivers={
            "opcode_decode_intentionally_grouped": (
                "Engineering decision to collapse 0x72/0x74/0x76 onto "
                "default arm pending vendor confirmation of payload "
                "alignment per L3 §4.2; tracked in JIRA IC-9901."
            )
        },
    )
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "WAIVER" in r.stdout


def test_alternative_hex_format(tmp_path):
    """RTL uses 'h74 (no width prefix) — must still match."""
    ops = [0x74]
    rtl = (
        "module main_fsm(input logic [7:0] cmd_op,\n"
        "                output logic [7:0] resp);\n"
        "  always_comb begin\n"
        "    if (cmd_op == 'h74) resp = 8'h75;\n"
        "    else resp = 8'h00;\n"
        "  end\n"
        "endmodule\n"
    )
    proj = _proj(tmp_path, ops, rtl)
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_help_works():
    r = subprocess.run(
        [sys.executable, str(PROG), "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
