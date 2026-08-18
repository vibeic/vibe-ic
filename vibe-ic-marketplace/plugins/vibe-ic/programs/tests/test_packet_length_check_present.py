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
