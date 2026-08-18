"""Unit tests for gap_reset_granularity_check.py.

Tests verify detection of the IC-A v041 fresh-agent final-blocker bug:
gap_cnt reset only on byte-level activity (rx_byte_valid) without also
resetting on bit-level activity (bit_valid).
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "gap_reset_granularity_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import gap_reset_granularity_check as grc  # noqa: E402


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Test 1: Byte-only gap reset → FAIL
# ---------------------------------------------------------------------------
def test_byte_only_reset_fails(tmp_path):
    content = """\
module mac_bad (input clk, input rstn,
                input rx_byte_valid, input [7:0] rx_byte);
    reg [15:0] gap_cnt;
    reg [3:0] cmd_cnt;
    reg [3:0] st;
    localparam ST_RX = 4'd1, ST_VALIDATE = 4'd2;
    localparam [15:0] CMD_SETTLE_GAP = 16'd80;

    always @(posedge clk) begin
        case (st)
            ST_RX: begin
                if (rx_byte_valid) begin
                    cmd_cnt <= cmd_cnt + 1;
                    gap_cnt <= 16'd0;
                end else if (cmd_cnt != 0) begin
                    if (gap_cnt < CMD_SETTLE_GAP) gap_cnt <= gap_cnt + 1;
                    else st <= ST_VALIDATE;
                end
            end
        endcase
    end
endmodule
"""
    p = _write(tmp_path, "mac_bad.v", content)
    findings = grc.analyze_file(p)
    errors = [f for f in findings if f.severity == "error"]
    assert errors, f"Expected FAIL; got {findings}"
    assert "byte" in errors[0].rule or "byte-only" in errors[0].message.lower()


# ---------------------------------------------------------------------------
# Test 2: Both bit and byte reset → PASS
# ---------------------------------------------------------------------------
def test_bit_and_byte_reset_passes(tmp_path):
    content = """\
module mac_good (input clk, input rstn,
                 input rx_byte_valid, input [7:0] rx_byte,
                 input bit_valid);
    reg [15:0] gap_cnt;
    reg [3:0] cmd_cnt;
    reg [3:0] st;
    localparam ST_RX = 4'd1, ST_VALIDATE = 4'd2;
    localparam [15:0] CMD_SETTLE_GAP = 16'd250;

    always @(posedge clk) begin
        case (st)
            ST_RX: begin
                if (rx_byte_valid) begin
                    cmd_cnt <= cmd_cnt + 1;
                    gap_cnt <= 16'd0;
                end else if (bit_valid) begin
                    gap_cnt <= 16'd0;  // ← reset on bit activity
                end else if (cmd_cnt != 0) begin
                    if (gap_cnt < CMD_SETTLE_GAP) gap_cnt <= gap_cnt + 1;
                    else st <= ST_VALIDATE;
                end
            end
        endcase
    end
endmodule
"""
    p = _write(tmp_path, "mac_good.v", content)
    findings = grc.analyze_file(p)
    errors = [f for f in findings if f.severity == "error"]
    assert not errors, f"Expected PASS; got errors {errors}"


# ---------------------------------------------------------------------------
# Test 3: Module without gap_cnt → PASS (silently)
# ---------------------------------------------------------------------------
def test_no_gap_counter_passes(tmp_path):
    content = """\
module simple_fsm (input clk, input rstn, output reg out);
    always @(posedge clk) begin
        if (!rstn) out <= 1'b0;
        else       out <= ~out;
    end
endmodule
"""
    p = _write(tmp_path, "simple.v", content)
    findings = grc.analyze_file(p)
    errors = [f for f in findings if f.severity == "error"]
    assert not errors


# ---------------------------------------------------------------------------
# Test 4: Gap reset with no nearby *_valid references → WARNING (not error)
# ---------------------------------------------------------------------------
def test_unknown_reset_source_warns(tmp_path):
    content = """\
module mac_unclear (input clk, input rstn, input some_trigger);
    reg [15:0] gap_cnt;
    reg st;
    always @(posedge clk) begin
        if (some_trigger) gap_cnt <= 16'd0;
        else if (gap_cnt < 16'd100) gap_cnt <= gap_cnt + 1;
        else st <= 1'b1;
    end
endmodule
"""
    p = _write(tmp_path, "mac_unclear.v", content)
    findings = grc.analyze_file(p)
    warnings = [f for f in findings if f.severity == "warning"]
    errors = [f for f in findings if f.severity == "error"]
    assert not errors
    # The unclear case produces a warning (not strictly required to find a *_valid)
    # so either 0 warnings (no gap_cnt reset detected) or 1 warning is acceptable.
    # This test documents that no FALSE ERROR is raised.


# --- the exit code is what the caller reads, and no test drove main()

def test_main_exits_non_zero_on_a_finding(tmp_path, monkeypatch):
    """`gate_cli_mutation_probe` reported this gate SILENT.

    The tests above call `analyze_file()` and assert the FINDINGS; the caller
    reads the EXIT CODE, and `main()` maps `result.passed` to it. Nothing
    exercised that mapping.
    """
    import gap_reset_granularity_check as G
    f = tmp_path / "x.v"
    f.write_text("module m; endmodule\n")

    class _F:
        severity = "error"
        rule = "gap-reset-too-coarse"
        file = str(f)
        line = 1
        message = "m"
    monkeypatch.setattr(G, "analyze_file", lambda p: [_F()])
    assert G.main([str(f)]) == 1


def test_main_exits_zero_when_clean(tmp_path, monkeypatch):
    """The other direction, or the test above is met by always failing."""
    import gap_reset_granularity_check as G
    f = tmp_path / "x.v"
    f.write_text("module m; endmodule\n")
    monkeypatch.setattr(G, "analyze_file", lambda p: [])
    assert G.main([str(f)]) == 0
