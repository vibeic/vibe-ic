"""Unit tests for handshake_check.py.

Tests verify detection of pulse-vs-countdown races, latched-valid
handshakes (which should pass), modules without pulse signals, and
empty directories.
"""
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / 'handshake_check.py'
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"

sys.path.insert(0, str(SCRIPT.parent))
import handshake_check as hsc  # noqa: E402


# ---------------------------------------------------------------------------
# Test 1: Pulse producer + timer-gated consumer → FAIL
# ---------------------------------------------------------------------------
def test_pulse_with_timer_wait_fails(tmp_path):
    # Producer generates a 1-cycle pulse on done_valid
    producer = """\
module producer (
    input  wire clk,
    input  wire rstn,
    input  wire cond,
    output reg  done_valid
);
    always @(posedge clk or negedge rstn) begin
        if (!rstn)
            done_valid <= 1'b0;
        else begin
            done_valid <= 1'b0;
            if (cond)
                done_valid <= 1'b1;
        end
    end
endmodule
"""
    # Consumer samples the pulse at the tail of a countdown
    consumer = """\
module consumer (
    input  wire clk,
    input  wire rstn,
    input  wire done_valid,
    output reg  done_out
);
    reg [7:0] timer;
    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            timer    <= 8'd10;
            done_out <= 1'b0;
        end else begin
            if (timer != 0)
                timer <= timer - 1;
            if (timer == 0) begin
                if (done_valid)
                    done_out <= 1'b1;
            end
        end
    end
endmodule
"""
    # Put both producers/consumers in a single file so the analyzer sees
    # pulse producer AND countdown consumer pattern in one src text. The
    # analyzer is file-scoped, so the signals must be visible together.
    combined = producer + "\n" + consumer
    (tmp_path / "combined.v").write_text(combined)

    result = hsc.audit(str(tmp_path))
    assert result.passed is False
    errors = [f for f in result.findings if f.rule == "POTENTIAL_HANDSHAKE_RACE"]
    assert any("done_valid" in f.message for f in errors)


# ---------------------------------------------------------------------------
# Test 2: Latched-on-arrival → PASS
# ---------------------------------------------------------------------------
def test_latched_valid_passes(tmp_path):
    # Producer creates the pulse.
    producer = """\
module producer (
    input  wire clk,
    input  wire rstn,
    input  wire cond,
    output reg  done_valid
);
    always @(posedge clk or negedge rstn) begin
        if (!rstn)
            done_valid <= 1'b0;
        else begin
            done_valid <= 1'b0;
            if (cond)
                done_valid <= 1'b1;
        end
    end
endmodule
"""
    # Consumer latches on arrival — does NOT check the raw pulse at the
    # countdown tail; only checks a latched flag (named without the
    # valid/done/ready suffix so it isn't treated as a handshake pulse).
    consumer = """\
module consumer (
    input  wire clk,
    input  wire rstn,
    input  wire done_valid,
    output reg  done_out
);
    reg [7:0] timer;
    reg       pending_flag;
    always @(posedge clk or negedge rstn) begin
        if (!rstn) begin
            timer        <= 8'd10;
            pending_flag <= 1'b0;
            done_out     <= 1'b0;
        end else begin
            if (done_valid)
                pending_flag <= 1'b1;
            if (timer != 0)
                timer <= timer - 1;
            if (timer == 0) begin
                if (pending_flag)
                    done_out <= 1'b1;
            end
        end
    end
endmodule
"""
    combined = producer + "\n" + consumer
    (tmp_path / "combined.v").write_text(combined)

    result = hsc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["violations"] == 0


# ---------------------------------------------------------------------------
# Test 3: No pulse producers → PASS (nothing to check)
# ---------------------------------------------------------------------------
def test_no_pulse_no_check(tmp_path):
    verilog = """\
module nopulse (
    input  wire clk,
    input  wire rstn,
    output reg  [7:0] cnt
);
    always @(posedge clk or negedge rstn) begin
        if (!rstn)
            cnt <= 8'd0;
        else
            cnt <= cnt + 1;
    end
endmodule
"""
    (tmp_path / "nopulse.v").write_text(verilog)

    result = hsc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["violations"] == 0


# ---------------------------------------------------------------------------
# Test 4: Empty directory → PASS
# ---------------------------------------------------------------------------
def test_empty_dir_passes(tmp_path):
    result = hsc.audit(str(tmp_path))
    assert result.passed is True
    assert result.summary["files_scanned"] == 0
    assert result.summary["violations"] == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
