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
    """An empty / non-RTL directory yields SKIP, never a crash or false flag.

    CONTRACT CHANGE (2026-08-03): rc is 2, not 0. This case used to exit 0,
    which `flow_compliance_check._check_program_exit_zero` credits as a plain
    PASS — so "this project has no FPGA top" and "the FPGA top was audited and
    is clean" produced the same verdict. rc 2 is the VACUOUS_PASS tier.
    """
    empty = tmp_path / "empty_dir"
    empty.mkdir()
    res, report = _run(str(empty))
    assert res.returncode == 2, res.stderr
    assert report["status"] == "SKIP"
    assert report["findings"] == []
    # The declaration must be visible to gate_skip_routing_check._skip_token,
    # which matches its vocabulary at LINE START.
    assert res.stderr.lstrip().startswith("[SKIP]"), res.stderr


def test_unexpected_content_no_crash(tmp_path):
    """A non-Verilog spec file with no LED constructs → SKIP, no findings.

    CONTRACT CHANGE (2026-08-03): rc is 2, not 0. Prose that merely mentions
    LEDs contains no LED drive for the lint to examine; a PASS there certifies
    an examination that never happened. Not crashing is still the point — the
    file is read and reported, it is simply not credited.
    """
    f = _write(tmp_path, "spec.txt",
               "This design uses 10 LEDs for debug. No code here.\n")
    res, report = _run(str(f))
    assert res.returncode == 2, res.stderr
    assert report["findings"] == []


# ---------------------------------------------------------------------------
# vibe-ic#693 — repairs made before this gate was wired. Each case below is a
# defect MEASURED on real published data, not a hypothetical.
# ---------------------------------------------------------------------------
def test_held_handshake_level_is_a_warning_not_an_error(tmp_path):
    """`test_done` set in one state and HELD in the terminal state.

    The corpus's only real FPGA top does exactly this, and the gate called it a
    1-cycle pulse on the identifier alone: renaming `test_done` -> `test_finished`
    and changing nothing else removed the finding. A weak handshake token with
    no structural pulse shape is now a WARNING — reported, never a red.
    """
    body = """
// LED PROBE TABLE
module top(input clk, input rst_n, output [9:0] LEDR);
    reg [1:0] st;
    reg test_done;
    always @(posedge clk) begin
        if (!rst_n) begin
            st <= 2'd0; test_done <= 0;
        end else begin
            case (st)
            2'd0: begin test_done <= 1'b1; st <= 2'd1; end
            2'd1: begin test_done <= 1'b1; end
            default: st <= 2'd1;
            endcase
        end
    end
    assign LEDR[1] = test_done;
endmodule
"""
    f = _write(tmp_path, "held.v", body)
    res, report = _run(str(f))
    assert res.returncode == 0, res.stderr
    assert _rules(report) == [], _rules(report)
    warn = [w["rule"] for w in report["warnings"]]
    assert warn == ["instantaneous-on-pulse"], report["warnings"]
    assert report["warnings"][0]["severity"] == "WARNING"


def test_structural_pulse_with_bare_literals_is_an_error(tmp_path):
    """`sig <= 1;` / `sig <= 0;` is a pulse shape too — and the reset clear of
    a HELD flag must not be mistaken for the deassert half of one."""
    body = """
// LED PROBE TABLE
module top(input clk, input rst_n, input go, output [9:0] LEDR);
    reg blip;
    always @(posedge clk) begin
        if (!rst_n) blip <= 0;
        else begin
            blip <= 0;
            if (go) blip <= 1;
        end
    end
    assign LEDR[0] = blip;
endmodule
"""
    f = _write(tmp_path, "shape.v", body)
    res, report = _run(str(f))
    assert res.returncode == 1, res.stderr
    assert "instantaneous-on-pulse" in _rules(report)
    detail = report["findings"][0]["detail"]
    assert "shape" in detail, detail


def test_reset_clear_alone_is_not_a_pulse_shape(tmp_path):
    """Set to 1 in normal code, cleared ONLY by reset → held level, not a pulse.

    This is the negative control for `_strip_reset_branches`: without it the
    widened `<= 0` match would read the reset clear as a pulse deassert and
    re-introduce the false positive the two-tier name rule just removed.
    """
    body = """
// LED PROBE TABLE
module top(input clk, input rst_n, input go, output [9:0] LEDR);
    reg latched;
    always @(posedge clk) begin
        if (!rst_n) begin
            latched <= 0;
        end else begin
            if (go) latched <= 1;
        end
    end
    assign LEDR[0] = latched;
endmodule
"""
    f = _write(tmp_path, "heldshape.v", body)
    res, report = _run(str(f))
    assert res.returncode == 0, res.stderr
    assert "instantaneous-on-pulse" not in _rules(report)


def test_identifier_ending_in_end_does_not_truncate_the_reset_branch(tmp_path):
    """`frame_end` inside the reset branch must not close the `begin`.

    `_strip_reset_branches` walks begin/end to find the matching `end`. A
    trailing-side-only token test keeps `endcase`/`endmodule` out but lets the
    `end` inside `frame_end` count: the walk then stops early, the rest of the
    reset branch is NOT blanked, and `latched <= 0;` — a reset clear — is read
    as the deassert half of a pulse. Measured: with the leading-side check
    removed and nothing else changed, this exact file goes rc=1
    `instantaneous-on-pulse` on 'latched'.
    """
    body = """
// LED PROBE TABLE
module top(input clk, input rst_n, input go, output [9:0] LEDR);
    reg frame_end;
    reg latched;
    always @(posedge clk) begin
        if (!rst_n) begin
            frame_end <= 0;
            latched   <= 0;
        end else begin
            if (go) latched <= 1;
        end
    end
    assign LEDR[0] = latched;
endmodule
"""
    f = _write(tmp_path, "kwtoken.v", body)
    res, report = _run(str(f))
    assert res.returncode == 0, res.stderr
    assert "instantaneous-on-pulse" not in _rules(report)
    assert report["warnings"] == [], report["warnings"]


def test_mode_mix_ignores_the_instantaneous_baseline_mode(tmp_path):
    """SKILL.md counts {pulse, sticky, byte}. `instantaneous` is the BASELINE
    mode; a byte column plus one plain level probe is the SKILL's own
    recommended layout, not an anti-pattern."""
    body = """
module top(input clk, output [9:0] LEDR);
    wire fsm_ok;
    wire [7:0] resp_byte;
    assign LEDR[9]   = fsm_ok;      // instantaneous level probe
    assign LEDR[7:0] = resp_byte;   // byte-display
endmodule
"""
    f = _write(tmp_path, "instbyte.v", body)
    res, report = _run(str(f))
    assert res.returncode == 0, res.stderr
    assert "mode-mix-without-table" not in _rules(report)
    assert "inst" in report["modes_detected"]
    assert "byte" in report["modes_detected"]


def test_commented_led_map_counts_as_a_probe_table(tmp_path):
    """A real LED map in comments IS a probe table even without the literal
    title `LED PROBE TABLE`. The rule must fire on a missing TABLE, not on a
    missing STRING."""
    body = """
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
    f = _write(tmp_path, "maptable.v", body)
    res, report = _run(str(f))
    assert res.returncode == 0, res.stderr
    assert "mode-mix-without-table" not in _rules(report)


def test_dangling_symlink_in_tree_does_not_abort_the_lint(tmp_path):
    """A dangling symlink used to abort with rc=2 — the VACUOUS_PASS tier — so
    an aborted lint was credited as a benign skip. 31 dangling symlinks exist
    under the published corpus, and one of them silently false-cleaned the only
    run with an FPGA top."""
    import os
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.v").write_text("""
// LED PROBE TABLE
module top(input clk, output [9:0] LEDR);
    wire tx_done_pulse;
    assign LEDR[9] = tx_done_pulse;
endmodule
""")
    os.symlink(str(tmp_path / "nowhere" / "gone.v"), str(rtl / "dangling.v"))
    res, report = _run(str(rtl))
    # The real top is still linted and its real defect still fires.
    assert res.returncode == 1, res.stderr
    assert "instantaneous-on-pulse" in _rules(report)
    assert len(report["files_scanned"]) == 1


def test_unreadable_file_is_disclosed_not_swallowed(tmp_path):
    """Coverage loss must be visible in the report, never silent."""
    import os
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "top.v").write_text("""
// LED PROBE TABLE
module top(input clk, output [9:0] LEDR);
    wire steady_level;
    assign LEDR[0] = steady_level;
endmodule
""")
    bad = rtl / "locked.v"
    bad.write_text("module x(); endmodule\n")
    os.chmod(bad, 0o000)
    try:
        res, report = _run(str(rtl))
    finally:
        os.chmod(bad, 0o644)
    assert res.returncode == 0, res.stderr
    assert len(report["unreadable"]) == 1, report
    assert report["led_drives_examined"] >= 1


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
