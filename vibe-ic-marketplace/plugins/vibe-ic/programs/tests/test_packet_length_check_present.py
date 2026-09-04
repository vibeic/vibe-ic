"""Unit tests for packet_length_check_present.py."""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "packet_length_check_present.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))

import packet_length_check_present as chk  # noqa: E402


# ---------------------------------------------------------------------------
# PASS paths
# ---------------------------------------------------------------------------
def test_non_dispatcher_passes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "plain.v").write_text(
        "module plain (input wire a, output wire b);\n"
        "  assign b = a;\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["checked"] == 0
    assert not any(f.severity == "ERROR" for f in findings)


def test_case_dispatcher_with_len_check_passes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "mac.v").write_text(
        "module mac (input wire clk);\n"
        "  reg [7:0] cmd_op;\n"
        "  reg [5:0] rsp_len;\n"
        "  reg last;\n"
        "  always @(posedge clk) begin\n"
        "    case (cmd_op)\n"
        "      8'h70: rsp_len <= 6'd1;\n"
        "      8'h72: rsp_len <= 6'd5;\n"
        "      default: rsp_len <= 6'd0;\n"
        "    endcase\n"
        "    last <= (rsp_len == 6'd1);\n"
        "  end\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["checked"] == 1
    assert not any(f.severity == "ERROR" for f in findings)


def test_if_cascade_with_len_check_passes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "mac2.v").write_text(
        "module mac2 (input wire clk);\n"
        "  reg [7:0] cmd;\n"
        "  reg [5:0] payload_len;\n"
        "  always @(posedge clk) begin\n"
        "    if (cmd == 8'h70) ;\n"
        "    else if (cmd == 8'h72) ;\n"
        "    else if (cmd == 8'h74) ;\n"
        "    if (payload_len == 6'd3) ;\n"
        "  end\n"
        "endmodule\n"
    )
    findings, _ = chk.audit(rtl)
    assert not any(f.severity == "ERROR" for f in findings)


# ---------------------------------------------------------------------------
# FAIL paths
# ---------------------------------------------------------------------------
def test_case_dispatcher_without_len_fails(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "bad.v").write_text(
        "module bad (input wire clk);\n"
        "  reg [7:0] opcode;\n"
        "  reg rsp;\n"
        "  always @(posedge clk) begin\n"
        "    case (opcode)\n"
        "      8'h70: rsp <= 1'b1;\n"
        "      8'h72: rsp <= 1'b0;\n"
        "    endcase\n"
        "  end\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["checked"] == 1
    errors = [f for f in findings if f.severity == "ERROR"]
    assert len(errors) == 1
    assert errors[0].category == "NO_LENGTH_CHECK"


def test_if_cascade_without_len_fails(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "bad.v").write_text(
        "module bad2 (input wire clk);\n"
        "  reg [7:0] cmd;\n"
        "  reg y;\n"
        "  always @(posedge clk) begin\n"
        "    if (cmd == 8'h70) y <= 1'b1;\n"
        "    else if (cmd == 8'h72) y <= 1'b0;\n"
        "    else if (cmd == 8'h74) y <= 1'b1;\n"
        "    else if (cmd == 8'h76) y <= 1'b0;\n"
        "  end\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["checked"] == 1
    errors = [f for f in findings if f.severity == "ERROR"]
    assert len(errors) == 1


def test_missing_dir_fails(tmp_path):
    findings, _ = chk.audit(tmp_path / "ghost")
    assert any(f.severity == "ERROR" and f.category == "IO"
               for f in findings)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------
def test_cli_exit_codes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "ok.v").write_text(
        "module ok (input wire clk);\n"
        "  reg [7:0] cmd_op;\n"
        "  reg [5:0] rsp_len;\n"
        "  always @(posedge clk) begin\n"
        "    case (cmd_op) 8'h70: rsp_len <= 6'd1; endcase\n"
        "    if (rsp_len == 6'd1) ;\n"
        "  end\n"
        "endmodule\n"
    )
    assert chk.main(["--rtl-dir", str(rtl)]) == 0


# ── ambiguous selector needs corroboration (opentitan_aes, 2026-09-02) ──────
def test_enum_field_decode_on_bare_op_is_not_a_dispatcher(tmp_path):
    """The MEASURED false positive: a control-register enum decode.

    `aes_ctrl_reg_shadowed` decodes an `aes_op_e` field with `unique case (op)`
    and two symbolic arms. There is no command, no packet and no length, and
    the run's own class profile declares `command_protocol_applicable=false`.
    Before the two-tier discriminator this reported an ERROR — twice, once
    directly and once through `rtl_precheck_gate`.
    """
    rtl = tmp_path / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "ctrl_reg.sv").write_text(
        "module ctrl_reg (input wire clk);\n"
        "  aes_op_e op;\n"
        "  always_comb begin\n"
        "    unique case (op)\n"
        "      AES_ENC: ctrl_wd.operation = AES_ENC;\n"
        "      AES_DEC: ctrl_wd.operation = AES_DEC;\n"
        "      default: ctrl_wd.operation = AES_ENC;\n"
        "    endcase\n"
        "  end\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["checked"] == 0, summary
    assert not any(f.severity == "ERROR" for f in findings)


def test_bare_op_WITH_byte_opcode_literals_is_still_a_dispatcher(tmp_path):
    """The control that must keep failing: same selector, real opcode bytes.

    This is the direction a fix could quietly break — narrowing the
    discriminator until nothing can trip it. `case (op)` over `8'hXX` arms and
    no length comparison is exactly the bug this gate exists to catch, and it
    must still be caught.
    """
    rtl = tmp_path / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "mac.v").write_text(
        "module mac (input wire clk);\n"
        "  reg [7:0] op;\n"
        "  always @(posedge clk) begin\n"
        "    case (op)\n"
        "      8'h70: rsp <= 1'b1;\n"
        "      8'h72: rsp <= 1'b0;\n"
        "      default: rsp <= 1'b0;\n"
        "    endcase\n"
        "  end\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["checked"] == 1, summary
    assert any(f.category == "NO_LENGTH_CHECK" for f in findings)


def test_bare_cmd_with_byte_literals_and_a_len_check_passes(tmp_path):
    """Corroborated dispatcher that DOES assert a length — still a PASS."""
    rtl = tmp_path / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "mac.v").write_text(
        "module mac (input wire clk);\n"
        "  reg [7:0] cmd;\n"
        "  reg [5:0] rx_len;\n"
        "  always @(posedge clk) begin\n"
        "    case (cmd)\n"
        "      8'h70: ok <= (rx_len == 6'd3);\n"
        "      default: ok <= 1'b0;\n"
        "    endcase\n"
        "  end\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["checked"] == 1
    assert not any(f.severity == "ERROR" for f in findings)


def test_command_specific_selector_needs_no_corroboration(tmp_path):
    """`case (cmd_op)` with symbolic arms is STILL a dispatcher.

    The narrowing applies only to the two reused short names; an unambiguous
    opcode selector keeps the standalone force it always had.
    """
    rtl = tmp_path / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "d.v").write_text(
        "module d (input wire clk);\n"
        "  always @(posedge clk) begin\n"
        "    case (cmd_op)\n"
        "      OP_READ: rsp <= 1'b1;\n"
        "      default: rsp <= 1'b0;\n"
        "    endcase\n"
        "  end\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["checked"] == 1
    assert any(f.category == "NO_LENGTH_CHECK" for f in findings)


def test_seven_bit_instruction_opcode_is_outside_packet_population(tmp_path):
    """A processor instruction decoder is not a received-command packet."""
    rtl = tmp_path / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "core.v").write_text(
        "module core(input [31:0] instruction, output reg action);\n"
        "  wire [6:0] opcode = instruction[6:0];\n"
        "  always @* begin\n"
        "    case (opcode)\n"
        "      OP_LOAD: action = 1'b1;\n"
        "      OP_STORE: action = 1'b0;\n"
        "      default: action = 1'b0;\n"
        "    endcase\n"
        "  end\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["checked"] == 0, summary
    assert not any(f.severity == "ERROR" for f in findings)
