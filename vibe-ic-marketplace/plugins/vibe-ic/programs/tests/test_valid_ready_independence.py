#!/usr/bin/env python3
"""test_valid_ready_independence.py — VALID must not wait on the consumer's READY.

The rule is only worth having if it separates the ILLEGAL dependency from the two
neighbouring LEGAL idioms, because both of those put `ready` right next to `valid`:

    legal    tvalid <= 1'b0       when (tready)            deassert on transfer
    legal    tvalid <= src_valid  when (tready || !tvalid)  skid-buffer load
    ILLEGAL  tvalid <= 1'b1       when (tready)             assertion gated by ready
    ILLEGAL  assign tvalid = have_data && tready

A checker that fires on the first two is useless — it would flag most correct
stream sources. So each of the four is asserted here, not just the violations.

The `ready` of a pair must also be an INPUT. Only a ready the DOWNSTREAM drives can
deadlock us; a same-named signal the module also DRIVES is its own back-pressure
output on a command interface, where gating valid on it is correct. That narrowing
was written against a real false positive (a converted-string module whose `ready`
is an output) and the motivating true positives were re-measured after it — see
`test_the_narrowing_did_not_delete_the_true_positive`.
"""
import subprocess
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROG = PLUGIN / "programs" / "valid_ready_independence_check.py"


def _run(tmp_path, name, src):
    f = tmp_path / f"{name}.v"
    f.write_text(src)
    cp = subprocess.run([sys.executable, str(PROG), str(f)],
                        capture_output=True, text=True, timeout=60)
    return cp.returncode, cp.stdout


LEGAL_DEASSERT = """
module m(input clk, input rstn, input src_valid, input [7:0] d,
         output reg m_axis_tvalid, input m_axis_tready, output reg [7:0] m_axis_tdata);
always @(posedge clk) if(!rstn) m_axis_tvalid <= 1'b0;
  else begin
    if (m_axis_tready) m_axis_tvalid <= 1'b0;
    else if (src_valid) begin m_axis_tvalid <= 1'b1; m_axis_tdata <= d; end
  end
endmodule
"""

LEGAL_SKID = """
module m(input clk, input src_valid, output reg m_axis_tvalid, input m_axis_tready);
always @(posedge clk)
  if (m_axis_tready || !m_axis_tvalid) m_axis_tvalid <= src_valid;
endmodule
"""

ILLEGAL_SEQ = """
module m(input clk, input have_data, output reg out_valid, input out_ready);
always @(posedge clk) if (out_ready) out_valid <= 1'b1;
endmodule
"""

ILLEGAL_COMB = """
module m(input have_data, output out_valid, input out_ready);
assign out_valid = have_data && out_ready;
endmodule
"""

# `ready` is an OUTPUT of this module: its own back-pressure on a command port,
# not a downstream sink's. Gating valid on it cannot deadlock a consumer.
READY_IS_OURS = """
module m(input clk, input start, input [7:0] c, output reg [7:0] o,
         output reg valid, output reg ready);
always @(posedge clk) begin
  if (start && ready) begin o <= c; valid <= 1'b1; ready <= 1'b0; end
end
endmodule
"""


def test_deassert_on_transfer_is_silent(tmp_path):
    rc, out = _run(tmp_path, "deassert", LEGAL_DEASSERT)
    assert rc == 0, f"flagged the deassert-on-handshake idiom:\n{out}"


def test_skid_buffer_load_is_silent(tmp_path):
    rc, out = _run(tmp_path, "skid", LEGAL_SKID)
    assert rc == 0, (
        "flagged the skid-buffer load. `tready || !tvalid` is a DISJUNCTION — "
        f"ready is not necessary for the condition to hold:\n{out}")


def test_sequential_assertion_gated_by_ready_is_caught(tmp_path):
    rc, out = _run(tmp_path, "seq", ILLEGAL_SEQ)
    assert rc == 1, f"missed valid asserted only under ready:\n{out}"
    assert "VALID_ASSERTION_GATED_BY_READY" in out, out


def test_combinational_dependency_is_caught(tmp_path):
    rc, out = _run(tmp_path, "comb", ILLEGAL_COMB)
    assert rc == 1, f"missed `assign valid = ... && ready`:\n{out}"
    assert "VALID_GATED_BY_READY" in out, out


def test_the_narrowing_did_not_delete_the_true_positive(tmp_path):
    """The input-driven-ready narrowing must not silence a real violation."""
    rc_ours, _ = _run(tmp_path, "ours", READY_IS_OURS)
    assert rc_ours == 0, "a module's OWN ready output is not a downstream ready"
    # the same shape, but with ready as an input, is the real defect and must
    # still be caught — this is the pair that proves the narrowing is a
    # distinction and not just a way to go quiet
    rc_real, out = _run(tmp_path, "real", READY_IS_OURS
                        .replace("output reg valid, output reg ready",
                                 "output reg valid, input ready")
                        .replace("ready <= 1'b0;", ""))
    assert rc_real == 1, f"narrowing silenced the genuine violation too:\n{out}"
