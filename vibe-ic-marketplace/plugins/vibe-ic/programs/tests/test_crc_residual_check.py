"""Unit tests for crc_residual_check.py.

Tests verify detection of the IC-A v041 fresh-agent CRC bug:
`crc_out == 0` residual check alongside CRC init=0xFF → silently drops every frame.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "crc_residual_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import crc_residual_check as crc_chk  # noqa: E402


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Test 1: CRC init=0xFF + residual == 0 → FAIL
# ---------------------------------------------------------------------------
def test_init_ff_with_zero_check_fails(tmp_path):
    bad = """\
module crc_buggy (input clk, input rstn, input [7:0] data,
                  input crc_clear, input crc_en, output [7:0] cmd_crc_out);
    reg [7:0] cmd_crc_reg;
    always @(posedge clk or negedge rstn) begin
        if (!rstn)           cmd_crc_reg <= 8'hFF;
        else if (crc_clear)  cmd_crc_reg <= 8'hFF;
    end
    assign cmd_crc_out = cmd_crc_reg;

    always @(posedge clk) begin
        if (cmd_crc_out == 8'h00) begin
            dispatch <= 1'b1;
        end
    end
endmodule
"""
    p = _write(tmp_path, "crc_buggy.v", bad)
    findings = crc_chk.analyze_tree([p])
    errors = [f for f in findings if f.severity == "error"]
    assert errors, f"Expected FAIL; got {findings}"
    assert "zero-on-init-ff" in errors[0].rule


# ---------------------------------------------------------------------------
# Test 2: CRC init=0x00 + residual == 0 → PASS (classic, correct)
# ---------------------------------------------------------------------------
def test_init_zero_with_zero_check_passes(tmp_path):
    ok = """\
module crc_ok (input clk, input rstn, input [7:0] data,
               input crc_clear, input crc_en, output [7:0] cmd_crc_out);
    reg [7:0] cmd_crc_reg;
    always @(posedge clk or negedge rstn) begin
        if (!rstn)           cmd_crc_reg <= 8'h00;
        else if (crc_clear)  cmd_crc_reg <= 8'h00;
    end
    assign cmd_crc_out = cmd_crc_reg;

    always @(posedge clk) begin
        if (cmd_crc_out == 8'h00) begin
            dispatch <= 1'b1;
        end
    end
endmodule
"""
    p = _write(tmp_path, "crc_ok.v", ok)
    findings = crc_chk.analyze_tree([p])
    errors = [f for f in findings if f.severity == "error"]
    assert not errors, f"Expected PASS; got {findings}"


# ---------------------------------------------------------------------------
# Test 3: CRC init=0xFF + cmd_cnt-based dispatch (no == 0 check) → PASS
# ---------------------------------------------------------------------------
def test_init_ff_without_zero_check_passes(tmp_path):
    ok = """\
module crc_cntbased (input clk, input rstn,
                     input [3:0] cmd_cnt,
                     input crc_clear, output [7:0] cmd_crc_out);
    reg [7:0] cmd_crc_reg;
    always @(posedge clk or negedge rstn) begin
        if (!rstn)           cmd_crc_reg <= 8'hFF;
        else if (crc_clear)  cmd_crc_reg <= 8'hFF;
    end
    assign cmd_crc_out = cmd_crc_reg;

    always @(posedge clk) begin
        if (cmd_cnt >= 4'd2) dispatch <= 1'b1;
    end
endmodule
"""
    p = _write(tmp_path, "crc_cntbased.v", ok)
    findings = crc_chk.analyze_tree([p])
    errors = [f for f in findings if f.severity == "error"]
    assert not errors, f"Expected PASS; got {findings}"


# ---------------------------------------------------------------------------
# Test 4: No CRC at all → PASS
# ---------------------------------------------------------------------------
def test_no_crc_passes(tmp_path):
    ok = """\
module simple_fsm (input clk, input rstn, output reg out);
    always @(posedge clk) begin
        if (!rstn) out <= 1'b0;
        else       out <= ~out;
    end
endmodule
"""
    p = _write(tmp_path, "simple.v", ok)
    findings = crc_chk.analyze_tree([p])
    errors = [f for f in findings if f.severity == "error"]
    assert not errors
