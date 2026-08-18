"""Unit tests for crc_completeness_check.py.

Tests verify correct detection of TX strobes without CRC feeds in the
same scope, accepted combinational CRC feeds, modules without CRC
signals, and empty directories.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'crc_completeness_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import crc_completeness_check as crc  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: Every tx strobe has a CRC feed in the same case branch → PASS
# ---------------------------------------------------------------------------
def test_all_tx_bytes_feed_crc_passes(tmp_path):
    verilog = """\
module tx_with_crc (
    input  wire       clk,
    input  wire       rstn,
    input  wire [1:0] state,
    output reg        tx_byte_valid,
    output reg        crc_calc,
    output reg  [7:0] tx_byte,
    output reg  [7:0] crc_data_in
);
    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            tx_byte_valid <= 1'b0;
            crc_calc      <= 1'b0;
            tx_byte       <= 8'h00;
            crc_data_in   <= 8'h00;
        end else begin
            tx_byte_valid <= 1'b0;
            crc_calc      <= 1'b0;
            case (state)
                2'd0: begin
                    tx_byte       <= 8'hA5;
                    crc_data_in   <= 8'hA5;
                    tx_byte_valid <= 1'b1;
                    crc_calc      <= 1'b1;
                end
                2'd1: begin
                    tx_byte       <= 8'h5A;
                    crc_data_in   <= 8'h5A;
                    tx_byte_valid <= 1'b1;
                    crc_calc      <= 1'b1;
                end
            endcase
        end
    end
endmodule
"""
    (tmp_path / "tx_with_crc.v").write_text(verilog)

    result = crc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["violations"] == 0


# ---------------------------------------------------------------------------
# Test 2: TX strobe without CRC feed in same branch → FAIL
# ---------------------------------------------------------------------------
def test_tx_without_crc_fails(tmp_path):
    verilog = """\
module tx_missing_crc (
    input  wire       clk,
    input  wire       rstn,
    input  wire [1:0] state,
    output reg        tx_byte_valid,
    output reg        crc_calc,
    output reg  [7:0] tx_byte,
    output reg  [7:0] crc_data_in
);
    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            tx_byte_valid <= 1'b0;
            crc_calc      <= 1'b0;
            tx_byte       <= 8'h00;
            crc_data_in   <= 8'h00;
        end else begin
            tx_byte_valid <= 1'b0;
            crc_calc      <= 1'b0;
            case (state)
                2'd0: begin
                    tx_byte       <= 8'hA5;
                    crc_data_in   <= 8'hA5;
                    tx_byte_valid <= 1'b1;
                    crc_calc      <= 1'b1;
                end
                2'd1: begin
                    // bug: payload byte emitted without feeding CRC
                    tx_byte       <= 8'h5A;
                    tx_byte_valid <= 1'b1;
                end
            endcase
        end
    end
endmodule
"""
    (tmp_path / "tx_missing_crc.v").write_text(verilog)

    result = crc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.rule == "TX_WITHOUT_CRC_FEED"]
    assert len(errors) >= 1


# ---------------------------------------------------------------------------
# Test 3: Combinational `assign crc_data_in = tx_byte;` → PASS
# ---------------------------------------------------------------------------
def test_combinational_feed_passes(tmp_path):
    verilog = """\
module tx_comb_crc (
    input  wire       clk,
    input  wire       rstn,
    input  wire [1:0] state,
    output reg        tx_byte_valid,
    output reg  [7:0] tx_byte,
    output wire [7:0] crc_data_in,
    output reg        crc_calc
);
    assign crc_data_in = tx_byte;

    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            tx_byte_valid <= 1'b0;
            crc_calc      <= 1'b0;
            tx_byte       <= 8'h00;
        end else begin
            tx_byte_valid <= 1'b0;
            case (state)
                2'd0: begin
                    tx_byte       <= 8'hA5;
                    tx_byte_valid <= 1'b1;
                end
                2'd1: begin
                    tx_byte       <= 8'h5A;
                    tx_byte_valid <= 1'b1;
                end
            endcase
        end
    end
endmodule
"""
    (tmp_path / "tx_comb_crc.v").write_text(verilog)

    result = crc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["violations"] == 0


# ---------------------------------------------------------------------------
# Test 4: No CRC signals present → no check performed → PASS
# ---------------------------------------------------------------------------
def test_no_crc_no_check(tmp_path):
    verilog = """\
module no_crc (
    input  wire clk,
    input  wire rstn,
    output reg  tx_byte_valid,
    output reg  [7:0] tx_byte
);
    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            tx_byte_valid <= 1'b0;
            tx_byte       <= 8'h00;
        end else begin
            tx_byte       <= 8'hA5;
            tx_byte_valid <= 1'b1;
        end
    end
endmodule
"""
    (tmp_path / "no_crc.v").write_text(verilog)

    result = crc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["violations"] == 0


# ---------------------------------------------------------------------------
# Test 5: Empty directory → PASS
# ---------------------------------------------------------------------------
def test_empty_dir_passes(tmp_path):
    result = crc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["files_scanned"] == 0
    assert result.summary["violations"] == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
