"""Unit tests for fpga_led_probe_lint.py.

Validates the four deterministic FPGA LED-probe anti-patterns documented in
skills/fpga-led-probe-allocation/SKILL.md:

  1. instantaneous-on-pulse        — assign LED[N] = <1-cycle pulse>;
  2. sticky-without-reset-clear    — sticky latch LED with no reset clear
  3. shared-pin-vs-QSF             — RTL-driven LED bit not allocated in .qsf
  4. mode-mix-without-table        — >=2 probe modes, no LED PROBE TABLE comment

Contract:
  * clean spec  -> exactly zero findings (no false alerts)
  * each anti-pattern -> exactly its finding fires
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "fpga_led_probe_lint.py"
assert SCRIPT.exists(), f"fpga_led_probe_lint.py not found at {SCRIPT}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _run(*args: str):
    """Run the lint CLI; return (CompletedProcess, parsed_json_from_stdout)."""
    res = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True,
    )
    report = json.loads(res.stdout)
    return res, report


def _write(tmp: Path, name: str, body: str) -> Path:
    p = tmp / name
    p.write_text(body)
    return p


def _rules(report) -> list[str]:
    return [f["rule"] for f in report["findings"]]


# ---------------------------------------------------------------------------
# Clean, fully-correct top: zero findings
# ---------------------------------------------------------------------------
CLEAN_TOP = """
//-----------------------------------------------------------------
// LED PROBE TABLE  (kept in sync with host capture script)
//
// LEDR[9]    sticky      tx_done_q          packet TX completed at least once
// LEDR[8]    sticky      cmd_decoded_q      RTL ever decoded a CMD
// LEDR[7:0]  byte-disp   last_response_byte most recent response byte
//-----------------------------------------------------------------
module fpga_top(
    input  CLK_50M,
    input  KEY_n_reset,
    output [9:0] LEDR
);
    wire tx_done_pulse, cmd_decoded_pulse;
    wire [7:0] last_response_byte;

    reg tx_done_q, cmd_decoded_q;
    always @(posedge CLK_50M or negedge KEY_n_reset) begin
        if (!KEY_n_reset) {tx_done_q, cmd_decoded_q} <= 2'b00;
        else begin
            if (tx_done_pulse)     tx_done_q     <= 1'b1;
            if (cmd_decoded_pulse) cmd_decoded_q <= 1'b1;
        end
    end

    assign LEDR[9]   = tx_done_q;
    assign LEDR[8]   = cmd_decoded_q;
    assign LEDR[7:0] = last_response_byte;
endmodule
"""

CLEAN_QSF = """
set_global_assignment -name TOP_LEVEL_ENTITY fpga_top
set_location_assignment PIN_A8 -to LEDR[0]
set_location_assignment PIN_A9 -to LEDR[1]
set_location_assignment PIN_A10 -to LEDR[2]
set_location_assignment PIN_B10 -to LEDR[3]
set_location_assignment PIN_D13 -to LEDR[4]
set_location_assignment PIN_C13 -to LEDR[5]
set_location_assignment PIN_E14 -to LEDR[6]
set_location_assignment PIN_D14 -to LEDR[7]
set_location_assignment PIN_A11 -to LEDR[8]
set_location_assignment PIN_B11 -to LEDR[9]
"""


def test_clean_top_no_findings(tmp_path):
    f = _write(tmp_path, "clean_top.v", CLEAN_TOP)
    res, report = _run(str(f))
    assert res.returncode == 0, res.stderr
    assert report["status"] == "PASS"
    assert report["findings"] == []


def test_clean_top_with_qsf_no_findings(tmp_path):
    f = _write(tmp_path, "clean_top.v", CLEAN_TOP)
    q = _write(tmp_path, "clean.qsf", CLEAN_QSF)
    res, report = _run(str(f), "--qsf", str(q))
    assert res.returncode == 0, res.stderr
    assert report["status"] == "PASS"
    assert report["qsf_checked"] is True
    assert report["findings"] == []


# ---------------------------------------------------------------------------
# Anti-pattern 1: instantaneous-on-pulse
# ---------------------------------------------------------------------------
def test_instantaneous_on_pulse_fires(tmp_path):
    body = """
// LED PROBE TABLE
module top(input CLK_50M, output [9:0] LEDR);
    wire tx_done_pulse;
    // BUG: 1-cycle pulse wired straight to an LED — camera never catches it
    assign LEDR[9] = tx_done_pulse;
endmodule
"""
    f = _write(tmp_path, "bad1.v", body)
    res, report = _run(str(f))
    assert res.returncode == 1
    assert "instantaneous-on-pulse" in _rules(report)


def test_instantaneous_on_pulse_shape_only(tmp_path):
    """Signal is not named *_pulse but is structurally pulse-shaped."""
    body = """
// LED PROBE TABLE
module top(input clk, output [9:0] LEDR);
    reg blip;
    always @(posedge clk) begin
        blip <= 1'b1;
        blip <= 1'b0;
    end
    assign LEDR[0] = blip;
endmodule
"""
    f = _write(tmp_path, "bad1b.v", body)
    res, report = _run(str(f))
    assert res.returncode == 1
    assert "instantaneous-on-pulse" in _rules(report)


def test_stretched_pulse_is_not_flagged(tmp_path):
    """A pulse fed through pulse_stretch must NOT be flagged (no false alert)."""
    body = """
// LED PROBE TABLE
module top(input clk_50m, output [9:0] LEDR);
    wire tx_done_pulse;
    pulse_stretch #(50000) u_st(.clk(clk_50m), .pulse_in(tx_done_pulse), .led_out(LEDR[9]));
endmodule
"""
    f = _write(tmp_path, "ok1.v", body)
    res, report = _run(str(f))
    assert res.returncode == 0, res.stderr
    assert "instantaneous-on-pulse" not in _rules(report)


def test_level_signal_not_flagged_as_pulse(tmp_path):
    """A steady-state level (busy/enable) on an instantaneous LED is fine."""
    body = """
// LED PROBE TABLE
module top(input clk, output [9:0] LEDR);
    wire fsm_busy;
    assign LEDR[5] = fsm_busy;
endmodule
"""
    f = _write(tmp_path, "ok2.v", body)
    res, report = _run(str(f))
    assert res.returncode == 0, res.stderr
    assert _rules(report) == []


# ---------------------------------------------------------------------------
# Anti-pattern 2: sticky-without-reset-clear
# ---------------------------------------------------------------------------
def test_sticky_without_reset_clear_fires(tmp_path):
    body = """
// LED PROBE TABLE
module top(input clk, input event_in, output [9:0] LEDR);
    reg seen_q;
    // BUG: no reset path clears seen_q — LED stuck ON forever
    always @(posedge clk) begin
        if (event_in) seen_q <= 1'b1;
    end
    assign LEDR[9] = seen_q;
endmodule
"""
    f = _write(tmp_path, "bad2.v", body)
    res, report = _run(str(f))
    assert res.returncode == 1
    assert "sticky-without-reset-clear" in _rules(report)


def test_sticky_with_reset_clear_ok(tmp_path):
    body = """
// LED PROBE TABLE
module top(input clk, input rst_n, input event_in, output [9:0] LEDR);
    reg seen_q;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) seen_q <= 1'b0;
        else if (event_in) seen_q <= 1'b1;
    end
    assign LEDR[9] = seen_q;
endmodule
"""
    f = _write(tmp_path, "ok3.v", body)
    res, report = _run(str(f))
    assert res.returncode == 0, res.stderr
    assert "sticky-without-reset-clear" not in _rules(report)


def test_sticky_group_clear_ok(tmp_path):
    """Group-style reset clear `{a,b} <= 2'b00;` must satisfy the check."""
    body = """
// LED PROBE TABLE
module top(input clk, input rst_n, input e1, input e2, output [9:0] LEDR);
    reg a_q, b_q;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) {a_q, b_q} <= 2'b00;
        else begin
            if (e1) a_q <= 1'b1;
            if (e2) b_q <= 1'b1;
        end
    end
    assign LEDR[9] = a_q;
    assign LEDR[8] = b_q;
endmodule
"""
    f = _write(tmp_path, "ok4.v", body)
    res, report = _run(str(f))
    assert res.returncode == 0, res.stderr
    assert "sticky-without-reset-clear" not in _rules(report)


# ---------------------------------------------------------------------------
# Anti-pattern 3: shared-pin-vs-QSF
# ---------------------------------------------------------------------------
def test_shared_pin_vs_qsf_fires(tmp_path):
    body = """
// LED PROBE TABLE
module top(input clk, output [9:0] LEDR);
    wire steady;
    assign LEDR[9] = steady;   // driven in RTL but missing from QSF
endmodule
"""
    qsf = """
set_location_assignment PIN_A8 -to LEDR[0]
"""
    f = _write(tmp_path, "bad3.v", body)
    q = _write(tmp_path, "partial.qsf", qsf)
    res, report = _run(str(f), "--qsf", str(q))
    assert res.returncode == 1
    rules = _rules(report)
    assert "shared-pin-vs-QSF" in rules
    detail = [x for x in report["findings"] if x["rule"] == "shared-pin-vs-QSF"][0]["detail"]
    assert "LEDR[9]" in detail


def test_no_qsf_means_shared_pin_skipped(tmp_path):
    """Without a .qsf the shared-pin check is SKIPPED — never a false FAIL."""
    body = """
// LED PROBE TABLE
module top(input clk, output [9:0] LEDR);
    wire steady;
    assign LEDR[9] = steady;
endmodule
"""
    f = _write(tmp_path, "ok5.v", body)
    res, report = _run(str(f))
    assert res.returncode == 0, res.stderr
    assert report["qsf_checked"] is False
    assert "shared-pin-vs-QSF" not in _rules(report)


# ---------------------------------------------------------------------------
# Anti-pattern 4: mode-mix-without-table
# ---------------------------------------------------------------------------
def test_mode_mix_without_table_fires(tmp_path):
    """Mixes sticky + byte modes but has NO LED PROBE TABLE comment."""
    body = """
module top(input clk, input rst_n, input event_in, output [9:0] LEDR);
    reg seen_q;
    wire [7:0] resp_byte;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) seen_q <= 1'b0;
        else if (event_in) seen_q <= 1'b1;
    end
    assign LEDR[9]   = seen_q;       // sticky mode
    assign LEDR[7:0] = resp_byte;    // byte-display mode
endmodule
"""
    f = _write(tmp_path, "bad4.v", body)
    res, report = _run(str(f))
    assert res.returncode == 1
    assert "mode-mix-without-table" in _rules(report)
    assert "sticky" in report["modes_detected"]
    assert "byte" in report["modes_detected"]


def test_mode_mix_with_table_ok(tmp_path):
    """Same mix but WITH the LED PROBE TABLE comment → no finding."""
    body = """
// LED PROBE TABLE
// LEDR[9]   sticky    seen_q     event happened at least once
// LEDR[7:0] byte-disp resp_byte  most recent response byte
module top(input clk, input rst_n, input event_in, output [9:0] LEDR);
    reg seen_q;
    wire [7:0] resp_byte;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) seen_q <= 1'b0;
        else if (event_in) seen_q <= 1'b1;
    end
    assign LEDR[9]   = seen_q;
    assign LEDR[7:0] = resp_byte;
endmodule
"""
    f = _write(tmp_path, "ok6.v", body)
    res, report = _run(str(f))
    assert res.returncode == 0, res.stderr
    assert "mode-mix-without-table" not in _rules(report)


def test_single_mode_no_table_required(tmp_path):
    """One mode only → a missing table is NOT an anti-pattern (no over-flag)."""
    body = """
module top(input clk, input rst_n, input event_in, output [9:0] LEDR);
    reg seen_q;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) seen_q <= 1'b0;
        else if (event_in) seen_q <= 1'b1;
    end
    assign LEDR[9] = seen_q;
endmodule
"""
    f = _write(tmp_path, "ok7.v", body)
    res, report = _run(str(f))
    assert res.returncode == 0, res.stderr
    assert "mode-mix-without-table" not in _rules(report)


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------
def test_missing_input_skips_gracefully(tmp_path):
    """An empty / non-RTL directory yields SKIP, never a crash or false flag."""
    empty = tmp_path / "empty_dir"
    empty.mkdir()
    res, report = _run(str(empty))
    assert res.returncode == 0
    assert report["status"] == "SKIP"
    assert report["findings"] == []


def test_unexpected_content_no_crash(tmp_path):
    """A non-Verilog spec file with no LED constructs → PASS, no findings."""
    f = _write(tmp_path, "spec.txt",
               "This design uses 10 LEDs for debug. No code here.\n")
    res, report = _run(str(f))
    assert res.returncode == 0
    assert report["findings"] == []


def test_each_antipattern_fires_only_its_own(tmp_path):
    """Isolation: anti-pattern-1 fixture must NOT also trip the other rules."""
    body = """
// LED PROBE TABLE
module top(input CLK_50M, output [9:0] LEDR);
    wire tx_done_pulse;
    assign LEDR[9] = tx_done_pulse;
endmodule
"""
    f = _write(tmp_path, "iso1.v", body)
    res, report = _run(str(f))
    assert res.returncode == 1
    rules = _rules(report)
    assert rules == ["instantaneous-on-pulse"], rules


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
