#!/usr/bin/env python3
"""The history-register-reset-to-a-constant advisory.

Distilled from a blind CVDP failure, specified in full, and then NOT SHIPPED —
after which the same design failed again in the next clean-room round by the
identical mechanism, byte for byte. This file is the difference between a
record and enforcement.

The tests also pin the honest limit: the signature does NOT separate the defect
from legitimate use, so every finding is WARN and the check never blocks.
"""
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
from edge_history_reset_phantom_check import check_text  # noqa: E402

PROG = PLUGIN / "programs" / "edge_history_reset_phantom_check.py"

DEFECT = """
module m(input clk, input rst_n, input sig, output rise);
  reg prev;
  always @(posedge clk)
    if (!rst_n) prev <= 1'b0;
    else        prev <= sig;
  assign rise = sig & ~prev;
endmodule
"""

FIXED = """
module m(input clk, input rst_n, input sig, output rise);
  reg prev;
  always @(posedge clk)
    if (!rst_n) prev <= sig;
    else        prev <= sig;
  assign rise = sig & ~prev;
endmodule
"""

NO_EDGE_TERM = """
module m(input clk, input rst_n, input [7:0] d, output reg [7:0] q);
  reg [7:0] stage;
  always @(posedge clk)
    if (!rst_n) begin stage <= 8'b0; q <= 8'b0; end
    else        begin stage <= d;    q <= stage; end
endmodule
"""


def test_the_defect_shape_is_reported():
    f, status = check_text(DEFECT)
    assert status == "FAIL" and len(f) == 1, f
    assert f[0].symbol == "prev"
    assert "prev <= sig" in f[0].message, "the message must name the repair"


def test_resetting_the_history_to_its_source_is_silent():
    """The fix the message recommends must actually satisfy the check."""
    f, status = check_text(FIXED)
    assert not f and status == "PASS", f


def test_a_plain_pipeline_register_is_not_a_history_register():
    """No edge term over the pair — resetting a pipeline stage to 0 is correct
    and extremely common; flagging it would drown the signal in noise."""
    f, _ = check_text(NO_EDGE_TERM)
    assert not f, f


def test_findings_are_advisory_and_the_cli_does_not_fail(tmp_path):
    """The measurement forbids blocking, so the exit code must not block either.

    Swept over the CVDP corpus this fires on 7 of 57 genuinely-failing drafts
    AND on 9 of 302 officially-passing ones — and the two populations are
    structurally identical (`edge_detector_0001`, which passes, has the same
    input-sourced history register reset to a constant as the jitter detector,
    which fails). What separates them lives in the stimulus, not the RTL.
    """
    f, _ = check_text(DEFECT)
    assert all(x.severity == "WARN" for x in f), (
        "an ERROR finding would make _structural_finding_gate BLOCK the emit, "
        "and this signature cannot carry that weight")
    src = tmp_path / "m.v"
    src.write_text(DEFECT)
    cp = subprocess.run([sys.executable, str(PROG), str(src)],
                        capture_output=True, text=True, timeout=60)
    assert cp.returncode == 0, "advisory by default"
    assert "EDGE_HISTORY_RESET_TO_CONSTANT" in cp.stdout
    strict = subprocess.run([sys.executable, str(PROG), str(src), "--strict"],
                            capture_output=True, text=True, timeout=60)
    assert strict.returncode == 1, "--strict exists for callers that want a stop"


def test_falling_edge_and_xor_spellings_are_recognised():
    for term in ("assign f = ~sig & prev;", "assign x = sig ^ prev;"):
        code = DEFECT.replace("assign rise = sig & ~prev;", term)
        f, _ = check_text(code)
        assert f, f"missed the edge term spelling: {term}"
