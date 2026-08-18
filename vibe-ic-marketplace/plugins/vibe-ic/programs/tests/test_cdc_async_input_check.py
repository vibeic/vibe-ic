"""Unit tests for cdc_async_input_check.py.

Tests verify correct detection of 2-stage synchronizer chains, directly
used async inputs, clock/reset exceptions, *_pad suffix flagging, and
empty directories.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'cdc_async_input_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import cdc_async_input_check as cdc  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: 2-stage synchronizer → PASS
# ---------------------------------------------------------------------------
def test_with_2stage_sync_passes(tmp_path):
    verilog = """\
module synced (
    input  wire clk,
    input  wire rstn,
    input  wire raw,
    output reg  out
);
    reg sync_d1, sync_d2;

    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            sync_d1 <= 1'b0;
            sync_d2 <= 1'b0;
            out     <= 1'b0;
        end else begin
            sync_d1 <= raw;
            sync_d2 <= sync_d1;
            if (sync_d2)
                out <= 1'b1;
        end
    end
endmodule
"""
    (tmp_path / "synced.v").write_text(verilog)

    result = cdc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["violations"] == 0


# ---------------------------------------------------------------------------
# Test 2: Async input used directly → FAIL
# ---------------------------------------------------------------------------
def test_async_input_used_directly_fails(tmp_path):
    verilog = """\
module bad (
    input  wire clk,
    input  wire rstn,
    input  wire bus_pad,
    output reg  out
);
    always @(posedge clk or negedge rstn) begin
        if (!rstn)
            out <= 1'b0;
        else if (bus_pad)
            out <= 1'b1;
    end
endmodule
"""
    (tmp_path / "bad.v").write_text(verilog)

    result = cdc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.rule == "ASYNC_INPUT_NO_SYNC"]
    assert any("bus_pad" in f.message for f in errors)


# ---------------------------------------------------------------------------
# Test 3: clk/rst/rstn should be skipped (not flagged)
# ---------------------------------------------------------------------------
def test_clk_rst_skipped(tmp_path):
    verilog = """\
module clk_rst_only (
    input  wire clk,
    input  wire rstn,
    output reg  q
);
    always @(posedge clk or negedge rstn) begin
        if (!rstn)
            q <= 1'b0;
        else
            q <= ~q;
    end
endmodule
"""
    (tmp_path / "clk_rst_only.v").write_text(verilog)

    result = cdc.audit(str(tmp_path))
    assert result.passed is True
    # No findings should mention clk/rst/rstn
    for f in result.findings:
        assert "clk" not in f.message
        assert "rstn" not in f.message


# ---------------------------------------------------------------------------
# Test 4: *_pad suffix used in always without sync → FAIL
# ---------------------------------------------------------------------------
def test_pad_suffix_flagged(tmp_path):
    verilog = """\
module pad_user (
    input  wire clk,
    input  wire rstn,
    input  wire foo_pad,
    output reg  state
);
    always @(posedge clk or negedge rstn) begin
        if (!rstn)
            state <= 1'b0;
        else if (foo_pad)
            state <= 1'b1;
    end
endmodule
"""
    (tmp_path / "pad_user.v").write_text(verilog)

    result = cdc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.rule == "ASYNC_INPUT_NO_SYNC"]
    assert any("foo_pad" in f.message for f in errors)


# ---------------------------------------------------------------------------
# Test 5: Empty directory → PASS (no violations)
# ---------------------------------------------------------------------------
def test_empty_dir_passes(tmp_path):
    result = cdc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["files_scanned"] == 0
    assert result.summary["violations"] == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
