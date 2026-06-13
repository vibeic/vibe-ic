"""Unit tests for reset_dependency_check.py.

Tests verify correct detection of circular reset dependencies via
reset-combining assigns, clean reset chains that should pass, trivial
designs without reset chains, and empty directories.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'reset_dependency_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import reset_dependency_check as rdc  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: Clean reset chain → PASS
#   drst produces sys_rstn from POR_BO.
#   otp_ctrl is reset by por_sync_out (not sys_rstn) — no cycle.
# ---------------------------------------------------------------------------
def test_clean_reset_chain_passes(tmp_path):
    verilog = """\
module top (
    input  wire clk,
    input  wire POR_BO,
    output wire otp_done
);
    wire sys_rstn;
    wire por_sync_out;

    drst u_drst (
        .clk          (clk),
        .por_in       (POR_BO),
        .por_sync_out (por_sync_out),
        .sys_rstn     (sys_rstn)
    );

    otp_ctrl u_otp (
        .clk      (clk),
        .rstn     (por_sync_out),
        .otp_done (otp_done)
    );
endmodule
"""
    (tmp_path / "top.v").write_text(verilog)

    result = rdc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["violations"] == 0


# ---------------------------------------------------------------------------
# Test 2: Circular dependency → FAIL
#   assign sys_rstn = por & otp_done;
#   otp_ctrl instantiated with .rstn(sys_rstn) and produces otp_done
# ---------------------------------------------------------------------------
def test_circular_dep_fails(tmp_path):
    verilog = """\
module top (
    input  wire clk,
    input  wire por,
    output wire otp_done
);
    wire sys_rstn;

    assign sys_rstn = por & otp_done;

    otp_ctrl u_otp (
        .clk      (clk),
        .rstn     (sys_rstn),
        .otp_done (otp_done)
    );
endmodule
"""
    (tmp_path / "top.v").write_text(verilog)

    result = rdc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.rule == "CIRCULAR_RESET_DEPENDENCY"]
    assert len(errors) >= 1
    assert any("sys_rstn" in f.message for f in errors)


# ---------------------------------------------------------------------------
# Test 3: Trivial design with no reset chain → PASS
# ---------------------------------------------------------------------------
def test_no_reset_chain_passes(tmp_path):
    verilog = """\
module trivial (
    input  wire       clk,
    input  wire       rstn,
    input  wire [7:0] d,
    output reg  [7:0] q
);
    always @(posedge clk or negedge rstn) begin
        if (!rstn)
            q <= 8'h00;
        else
            q <= d;
    end
endmodule
"""
    (tmp_path / "trivial.v").write_text(verilog)

    result = rdc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["violations"] == 0


# ---------------------------------------------------------------------------
# Test 4: Empty directory → PASS
# ---------------------------------------------------------------------------
def test_empty_dir_passes(tmp_path):
    result = rdc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["files_scanned"] == 0
    assert result.summary["violations"] == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
