"""tests/test_byte_assembler_explicit_9bit_reject_check.py
Wave 37 (v0.119.69) — BACKLOG v0.119.70 Item 1.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = (
    Path(__file__).resolve().parent.parent / "byte_assembler_explicit_9bit_reject_check.py"
)


def _run(project: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(project)],
        capture_output=True, text=True,
    )


def _make_aid_l_docs(project: Path) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "interface": "EXAMPLE_PROTOCOL single-wire half-duplex",
    }))
    (gd / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "protocol_type": "single_wire_half_duplex",
    }))
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "physical_layer": "EXAMPLE_PROTOCOL half-duplex single-wire",
        "commands": [{"opcode": "0x74", "name": "GET_ID"}],
    }))
    (gd / "L6_CONTROL_LOGIC.json").write_text(json.dumps({
        "ic_name": "EXAMPLE_PROTOCOL-X",
        "fsm_states": [{"name": "IDLE"}],
    }))


def _make_uart_l_docs(project: Path) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "UART-X", "interface": "UART",
    }))
    (gd / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "UART-X", "protocol_type": "UART",
    }))
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps({
        "ic_name": "UART-X",
        "commands": [{"opcode": "0x01", "name": "READ"}],
    }))


def _make_pmic_l_docs(project: Path) -> None:
    gd = project / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({
        "ic_name": "PMIC-X", "interface": "pure analog",
    }))
    (gd / "L2_FRS.json").write_text(json.dumps({
        "ic_name": "PMIC-X", "interface": "pure analog",
    }))
    (gd / "L5_ADI_SPEC.json").write_text(json.dumps({
        "ic_name": "PMIC-X",
        "analog_blocks": [{"name": "BANDGAP_REF"}],
    }))


def _byte_assembler_no_reject() -> str:
    return """
module byte_assembler (
    input clk, input rst,
    input bit_vld, input bit_data,
    output reg byte_valid, output reg [7:0] byte_out
);
    reg [3:0] bit_idx;
    always_ff @(posedge clk) begin
        if (rst) begin
            bit_idx <= 4'd0;
            byte_valid <= 1'b0;
        end else if (bit_vld) begin
            byte_out[bit_idx] <= bit_data;
            if (bit_idx == 4'd7) begin
                bit_idx <= 4'd0;
                byte_valid <= 1'b1;
            end else begin
                bit_idx <= bit_idx + 4'd1;
                byte_valid <= 1'b0;
            end
        end
    end
endmodule
"""


def _byte_assembler_with_reject() -> str:
    return """
module byte_assembler (
    input clk, input rst,
    input bit_vld, input bit_data,
    input byte_committed,
    output reg byte_valid, output reg [7:0] byte_out,
    output reg ninth_bit_detected
);
    reg [3:0] bit_idx;
    always_ff @(posedge clk) begin
        if (rst | byte_committed) begin
            bit_idx <= 4'd0;
            ninth_bit_detected <= 1'b0;
            byte_valid <= 1'b0;
        end else if (bit_vld) begin
            if (bit_idx == 4'd8) begin
                ninth_bit_detected <= 1'b1;
            end else begin
                byte_out[bit_idx] <= bit_data;
                if (bit_idx == 4'd7) begin
                    bit_idx <= 4'd0;
                    byte_valid <= 1'b1;
                end else begin
                    bit_idx <= bit_idx + 4'd1;
                end
            end
        end
    end
endmodule
"""


def _main_fsm_with_drop() -> str:
    return """
module main_fsm (
    input clk, input rst,
    input ninth_bit_detected,
    input [7:0] op,
    output reg [3:0] state
);
    localparam S_IDLE = 4'd0;
    localparam S_DROP = 4'd1;
    localparam S_RX_DATA = 4'd2;

    always_ff @(posedge clk) begin
        if (rst) state <= S_IDLE;
        else case (op)
            8'h74: state <= S_RX_DATA;
            default: begin
                if (ninth_bit_detected) state <= S_DROP;
                else state <= S_IDLE;
            end
        endcase
    end
endmodule
"""


def _main_fsm_no_drop() -> str:
    return """
module main_fsm (
    input clk, input rst,
    input [7:0] op,
    output reg [3:0] state
);
    localparam S_IDLE = 4'd0;
    localparam S_RX_DATA = 4'd2;

    always_ff @(posedge clk) begin
        if (rst) state <= S_IDLE;
        else case (op)
            8'h74: state <= S_RX_DATA;
            default: state <= S_IDLE;
        endcase
    end
endmodule
"""


# ---------------------------------------------------------------
# 1. Positive PASS
# ---------------------------------------------------------------
def test_pass_aid_with_explicit_reject(tmp_path: Path):
    project = tmp_path / "aid_pass"
    project.mkdir(parents=True, exist_ok=True)
    _make_aid_l_docs(project)
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "byte_assembler.sv").write_text(_byte_assembler_with_reject())
    (rtl / "main_fsm.sv").write_text(_main_fsm_with_drop())
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


# ---------------------------------------------------------------
# 2. Positive FAIL — aid_class chip without explicit reject
# ---------------------------------------------------------------
def test_fail_aid_no_explicit_reject(tmp_path: Path):
    project = tmp_path / "aid_fail"
    project.mkdir(parents=True, exist_ok=True)
    _make_aid_l_docs(project)
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "byte_assembler.sv").write_text(_byte_assembler_no_reject())
    (rtl / "main_fsm.sv").write_text(_main_fsm_no_drop())
    r = _run(project)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "NO_EXPLICIT_REJECT_SIGNAL" in r.stdout


# ---------------------------------------------------------------
# 3. SKIP for non-applicable IC (UART)
# ---------------------------------------------------------------
def test_skip_uart_no_misfire(tmp_path: Path):
    project = tmp_path / "uart"
    project.mkdir(parents=True, exist_ok=True)
    _make_uart_l_docs(project)
    # No RTL — should still SKIP cleanly.
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout


# ---------------------------------------------------------------
# 4. SKIP for pure_analog
# ---------------------------------------------------------------
def test_skip_pure_analog(tmp_path: Path):
    project = tmp_path / "pmic"
    project.mkdir(parents=True, exist_ok=True)
    _make_pmic_l_docs(project)
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SKIP" in r.stdout


# ---------------------------------------------------------------
# 5. Edge — reject signal in main_fsm but no FSM drop path
# ---------------------------------------------------------------
def test_fail_reject_signal_no_fsm_path(tmp_path: Path):
    project = tmp_path / "aid_partial"
    project.mkdir(parents=True, exist_ok=True)
    _make_aid_l_docs(project)
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "byte_assembler.sv").write_text(_byte_assembler_with_reject())
    (rtl / "main_fsm.sv").write_text(_main_fsm_no_drop())
    r = _run(project)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REJECT_SIGNAL_WITHOUT_FSM_PATH" in r.stdout


# ---------------------------------------------------------------
# 6. Waiver
# ---------------------------------------------------------------
def test_waiver_silences_fail(tmp_path: Path):
    project = tmp_path / "aid_waived"
    project.mkdir(parents=True, exist_ok=True)
    _make_aid_l_docs(project)
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "byte_assembler.sv").write_text(_byte_assembler_no_reject())
    (rtl / "main_fsm.sv").write_text(_main_fsm_no_drop())
    (project / "waivers.json").write_text(json.dumps({
        "byte_assembler_implicit_reject_intentional":
            "Half-duplex bus with hardware-level glitch filter "
            "in front; partial-byte recovery proven by lab oracle "
            "trace 2026-04-02."
    }))
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS_WITH_WAIVER" in r.stdout


# ---------------------------------------------------------------
# 7. Wave 42 / MF1 — unknown class with byte_assembler RTL evidence
#    must fall through to FAIL, NOT silently SKIP.
# ---------------------------------------------------------------
def test_unknown_class_fail_closed_when_evidence_present(
        tmp_path: Path):
    """ic_class=unknown but byte_assembler RTL exists w/o reject signal —
    gate must produce FAIL (fault-injection hardening)."""
    project = tmp_path / "unknown_evidence"
    project.mkdir(parents=True, exist_ok=True)
    # No L docs at all → detect_ic_class returns "unknown".
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "byte_assembler.sv").write_text(_byte_assembler_no_reject())
    (rtl / "main_fsm.sv").write_text(_main_fsm_no_drop())
    r = _run(project)
    out = r.stdout + r.stderr
    # The pre-Wave-42 behaviour was an early SKIP on unknown class
    # without bit-bang asm evidence.  Now (a) we have asm evidence
    # AND (b) `unknown` is NOT auto-skipped → must FAIL.
    assert "SKIP — ic_class=unknown" not in out, (
        f"MF1 broken: unknown class auto-SKIPped\n{out}")
    assert r.returncode == 1, (
        f"unknown+evidence should FAIL, got exit={r.returncode}\n{out}")
