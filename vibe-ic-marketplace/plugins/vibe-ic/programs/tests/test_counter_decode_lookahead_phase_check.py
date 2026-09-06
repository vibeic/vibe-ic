"""A level decoded from a counter lookahead is published one cycle early.

Two designs in one RTLLM clean-room run failed the hidden reference harness for
this one structural reason, in two different subsystems:

    freq_divbyodd   clk_div1 <= (cnt1_next < NUM_DIV/2);   cnt1 <= cnt1_next;
    asyn_fifo       wptr     <= bin2gray(waddr_bin + wen); waddr_bin <= waddr_bin + wen;

Both forms are self-consistent and both read as MORE correct than the reference
form — the flop appears to describe the value it is about to hold. Neither is
visible to the oracles that were already in place: a ratio/duty check sees a
perfect period and duty, and a write-then-read FIFO test never reaches the
full/empty boundary where the pointer's phase matters.

The gate must stay narrow. `data_out <= acc + data_in` in an accumulator is the
design's arithmetic result, not a phase decode, and flagging it was a real false
positive against a design that passed. The discriminator is what the lookahead
FEEDS: a comparison or a gray encoding publishes a phase; a bare sum does not.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import counter_decode_lookahead_phase_check as C  # noqa: E402


BROKEN_DIVIDER = """
module d #(parameter NUM_DIV = 5) (input clk, input rst_n, output clk_div);
    reg [31:0] cnt1;
    reg clk_div1;
    wire [31:0] cnt1_next = (cnt1 == NUM_DIV - 1) ? 32'd0 : cnt1 + 32'd1;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt1 <= 32'd0;
            clk_div1 <= 1'b1;
        end else begin
            cnt1 <= cnt1_next;
            clk_div1 <= (cnt1_next < (NUM_DIV / 2));
        end
    end
    assign clk_div = clk_div1;
endmodule
"""

FIXED_DIVIDER = """
module d #(parameter NUM_DIV = 5) (input clk, input rst_n, output clk_div);
    reg [31:0] cnt1;
    reg clk_div1;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            cnt1 <= 32'd0;
            clk_div1 <= 1'b1;
        end else if (cnt1 == NUM_DIV - 1) begin
            cnt1 <= 32'd0;
            clk_div1 <= 1'b0;
        end else begin
            cnt1 <= cnt1 + 32'd1;
            clk_div1 <= (cnt1 < (NUM_DIV / 2));
        end
    end
    assign clk_div = clk_div1;
endmodule
"""

BROKEN_FIFO = """
module f (input wclk, input wrstn, input wen);
    reg [4:0] waddr_bin, wptr;
    function [4:0] bin2gray(input [4:0] b); bin2gray = b ^ (b >> 1); endfunction
    always @(posedge wclk or negedge wrstn) begin
        if (!wrstn) begin
            waddr_bin <= 5'd0;
            wptr      <= 5'd0;
        end else begin
            waddr_bin <= waddr_bin + wen;
            wptr      <= bin2gray(waddr_bin + wen);
        end
    end
endmodule
"""

FIXED_FIFO = BROKEN_FIFO.replace("bin2gray(waddr_bin + wen)", "bin2gray(waddr_bin)")

#: The accumulator that was a false positive: a sum, not a phase decode.
ACCUMULATOR = """
module a (input clk, input rst_n, input [7:0] data_in, output reg [9:0] data_out);
    reg [9:0] acc;
    reg [1:0] cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            acc <= 10'd0;
            cnt <= 2'd0;
            data_out <= 10'd0;
        end else begin
            acc      <= acc + data_in;
            cnt      <= cnt + 1;
            data_out <= acc + data_in;
        end
    end
endmodule
"""


def test_the_divider_lookahead_is_reported():
    """THE REGRESSION, alias form: the decode reads `cnt1_next`."""
    findings = C.scan(BROKEN_DIVIDER)
    assert findings, "a level decoded from cnt1_next was not reported"
    assert {f["signal"] for f in findings} == {"clk_div1"}
    assert findings[0]["counter"] == "cnt1"
    assert findings[0]["via"] == "alias"


def test_the_fifo_lookahead_is_reported():
    """THE REGRESSION, inline form: the encoding reads `waddr_bin + wen`."""
    findings = C.scan(BROKEN_FIFO)
    assert {f["signal"] for f in findings} == {"wptr"}
    assert findings[0]["counter"] == "waddr_bin"
    assert findings[0]["via"] == "inline"


@pytest.mark.parametrize("src,label", [(FIXED_DIVIDER, "divider"),
                                       (FIXED_FIFO, "fifo")])
def test_the_reference_form_is_clean(src, label):
    """THE BIDIRECTIONAL CONTROL. Decoding the PRE-increment value — the form
    the references use and the form that passes the harness — must not be
    reported, or the gate would reject the fix it exists to produce."""
    assert C.scan(src) == [], f"the correct {label} form was reported"


def test_an_accumulator_sum_is_not_a_phase_decode():
    """THE FALSE POSITIVE THIS GATE ALREADY HAD. `data_out <= acc + data_in` is
    the accumulator's result. It was flagged against a design that passed the
    official harness; only a lookahead feeding a COMPARISON or a gray encoding
    publishes a phase."""
    assert C.scan(ACCUMULATOR) == []


def test_a_comment_naming_the_pattern_cannot_cause_a_finding():
    """Comments are stripped first: prose must never decide a verdict."""
    src = FIXED_FIFO.replace(
        "module f", "// wptr <= bin2gray(waddr_bin + wen); is the WRONG form\nmodule f")
    assert C.scan(src) == []


def test_a_counter_with_no_dependent_decode_is_clean():
    """A design that computes `cnt_next` and uses it ONLY to advance the counter
    is the ordinary pattern, not a finding."""
    src = """
    module c (input clk, input rst_n);
        reg [3:0] cnt;
        wire [3:0] cnt_next = cnt + 1;
        always @(posedge clk or negedge rst_n) begin
            if (!rst_n) cnt <= 4'd0;
            else        cnt <= cnt_next;
        end
    endmodule
    """
    assert C.scan(src) == []


def test_cli_exit_codes(tmp_path):
    """Advisory by default, non-zero under --strict: a lookahead decode is
    legitimate when a spec asks the level to lead, so the default must not
    block."""
    p = tmp_path / "broken.v"
    p.write_text(BROKEN_FIFO, encoding="utf-8")
    prog = str(_PROGRAMS / "counter_decode_lookahead_phase_check.py")

    advisory = subprocess.run([sys.executable, prog, str(p)],
                              capture_output=True, text=True)
    assert advisory.returncode == 0
    assert "FINDING" in advisory.stdout

    strict = subprocess.run([sys.executable, prog, str(p), "--strict"],
                            capture_output=True, text=True)
    assert strict.returncode == 1

    clean = tmp_path / "clean.v"
    clean.write_text(FIXED_FIFO, encoding="utf-8")
    ok = subprocess.run([sys.executable, prog, str(clean), "--strict"],
                        capture_output=True, text=True)
    assert ok.returncode == 0
    assert "PASS" in ok.stdout


def test_a_missing_file_is_cannot_check_not_a_pass(tmp_path):
    """MISSING is not a pass: an unreadable input must not read as clean."""
    prog = str(_PROGRAMS / "counter_decode_lookahead_phase_check.py")
    r = subprocess.run([sys.executable, prog, str(tmp_path / "nope.v")],
                       capture_output=True, text=True)
    assert r.returncode == 2
    assert "CANNOT CHECK" in r.stdout
