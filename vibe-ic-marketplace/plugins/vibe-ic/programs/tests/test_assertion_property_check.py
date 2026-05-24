"""Unit tests for assertion_property_check.py.

Tests verify correct detection of valid SVA files, missing assertion files,
missing property declarations, stub files, and empty directories.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'assertion_property_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import assertion_property_check as apc  # noqa: E402


# ---------------------------------------------------------------------------
# Helper: a valid SVA file with property + assert property (>10 lines)
# ---------------------------------------------------------------------------
VALID_SVA = """\
// SystemVerilog Assertions for UART TX
module uart_tx_sva (
    input wire clk,
    input wire rst_n,
    input wire tx_start,
    input wire tx_busy,
    input wire tx_done
);

    // Property: tx_busy must assert within 2 cycles of tx_start
    property p_tx_busy_after_start;
        @(posedge clk) disable iff (!rst_n)
        tx_start |-> ##[1:2] tx_busy;
    endproperty

    // Property: tx_done must eventually follow tx_busy
    property p_tx_done_after_busy;
        @(posedge clk) disable iff (!rst_n)
        tx_busy |-> ##[1:100] tx_done;
    endproperty

    assert property (p_tx_busy_after_start)
        else $error("tx_busy did not assert after tx_start");

    assert property (p_tx_done_after_busy)
        else $error("tx_done did not follow tx_busy");

endmodule
"""


# ---------------------------------------------------------------------------
# Test 1: Valid SVA file → PASS
# ---------------------------------------------------------------------------
def test_valid_sva_pass(tmp_path):
    (tmp_path / "uart_tx_sva.sv").write_text(VALID_SVA)

    result = apc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["valid_files"] >= 1


# ---------------------------------------------------------------------------
# Test 2: No .sv/.sva files → FAIL
# ---------------------------------------------------------------------------
def test_no_assertion_files_fail(tmp_path):
    # Create a non-assertion file
    (tmp_path / "design.v").write_text("module top(); endmodule")

    result = apc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_ASSERTION_FILE" for f in errors)


# ---------------------------------------------------------------------------
# Test 3: .sv file with assert but no property declaration → FAIL
# ---------------------------------------------------------------------------
def test_no_property_decl_fail(tmp_path):
    sv_content = """\
// Assertions without property declarations
module check_sva (
    input wire clk,
    input wire rst_n,
    input wire data_valid,
    input wire data_ready,
    input wire ack,
    input wire req,
    input wire busy,
    input wire done,
    input wire error
);

    // Immediate assertions only (no property keyword)
    always @(posedge clk) begin
        assert (data_valid || !data_ready)
            else $error("data not valid when ready");
        assert (req |-> !error)
            else $error("error during request");
    end

endmodule
"""
    (tmp_path / "check_sva.sv").write_text(sv_content)

    result = apc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_PROPERTY_DECL" or f.rule == "NO_ASSERT_PROPERTY"
               for f in errors)


# ---------------------------------------------------------------------------
# Test 4: Stub file (<= 10 non-empty lines) → FAIL
# ---------------------------------------------------------------------------
def test_stub_file_fail(tmp_path):
    stub_sv = """\
// Stub assertion file
module stub_sva;
    property p1;
        @(posedge clk) 1;
    endproperty
    assert property (p1);
endmodule
"""
    (tmp_path / "stub_sva.sv").write_text(stub_sv)

    result = apc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "STUB_FILE" for f in errors)


# ---------------------------------------------------------------------------
# Test 5: Empty directory → FAIL
# ---------------------------------------------------------------------------
def test_empty_dir_fail(tmp_path):
    result = apc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.severity == "ERROR"]
    assert any(f.rule == "NO_ASSERTION_FILE" for f in errors)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
