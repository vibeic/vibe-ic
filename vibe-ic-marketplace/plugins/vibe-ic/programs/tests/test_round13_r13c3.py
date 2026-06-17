"""Round-13 cluster R13C3 regression test (ORGANIC, cvdp_copilot_ir_receiver_0001).

spec_coverage_check.py --strict hard-blocked (rc=1) a structurally LSB-first-faithful
testbench on correct LSB-first RTL: the TB drives bit[0] first..bit[11] last and
asserts `ir_frame_out === frame` (proving LSB-first packing), but the gate demanded a
literal coverage token ("lsb first") it could not find. byte_order was uniquely
DOUBLE-unprotected vs the other behavioral PROSE_HEURISTIC kinds: (a) no
structural-stimulus coverage path (it fell into the literal-token "Normal item" path),
and (b) no corroboration elif branch in run() — so corr stayed UNKNOWN and
is_block_eligible(PROSE_HEURISTIC, UNKNOWN) returned True. A spec-faithful TB could
only "pass" by injecting the functionless literal 'lsb first' (gaming a token).

The fix gives byte_order (and signedness) the same two protections the other
behavioral kinds already have: an RTL bit-ordering corroboration signature
(shift-insert {bit, reg[N-1:1]} = LSB-first / {reg[N-2:0], bit} = MSB-first) and a
TB structural-stimulus coverage detector (indexed per-bit drive + ordering equality
assertion in a loop).

Asserts:
  (a) POSITIVE — the affected id's spec-faithful TB+RTL now passes (rc 0) with NO
      literal "lsb first" token anywhere in the TB.
  (b) §4.05 NO-LEAK NEGATIVE — a TB that does NOT structurally exercise the bit
      ordering (no indexed per-bit loop, no ordering equality) still hard-blocks (rc 1).
  (c) §4.05 NO-LEAK — a byte_order stated in a markdown TABLE (a STRUCTURAL source)
      keeps its hard block when the TB does not exercise it.

Self-contained: inline fixtures, resolves the programs dir via __file__ so it runs
in CI against the repo programs/ directory.
"""
import subprocess
import sys
from pathlib import Path

import pytest

# Resolve the programs/ dir: in CI the test sits at programs/tests/<this>, so
# .parent.parent is programs/. When the test sits directly alongside the program
# (the staging dir), fall back to .parent.
import os
_HERE = Path(__file__).resolve()
_CANDIDATES = [Path(os.environ["VIBE_PROGRAMS"])] if os.environ.get("VIBE_PROGRAMS") else []
_CANDIDATES += [_HERE.parent.parent, _HERE.parent]
PROGRAMS_DIR = next(
    (c for c in _CANDIDATES if (c / "spec_coverage_check.py").is_file()), None)
assert PROGRAMS_DIR is not None, (
    f"spec_coverage_check.py not found near {_HERE} (tried {_CANDIDATES})")
PROG = PROGRAMS_DIR / "spec_coverage_check.py"


# ---- inline fixtures -------------------------------------------------------

SPEC_PROSE = """# IR (Infrared) Receiver Protocol Specification

Decodes a 12-bit IR frame.

## Output Latency
- The output latency is 1 clock cycle after the 12-bit decoding completes.

## Example Operations
### Example 1: Valid Frame Decoding
- Input: a valid IR signal with a 2.4 ms start bit followed by 12 data bits
  (LSB First after the start bit and MSB Last).

## Clocking
- reset_in is Active HIGH reset.

## Ports
- input  logic        reset_in       : Active HIGH reset
- input  logic        clk_in         : System clock
- input  logic        ir_signal_in   : Input signal (IR)
- output logic [11:0] ir_frame_out   : Decoded 12-bit frame
- output logic        ir_frame_valid : Indicates validity of the decoded frame
"""

# byte_order stated in a MARKDOWN TABLE -> STRUCTURAL source -> keeps hard block.
SPEC_TABLE = """# IR Receiver

Decodes a 12-bit IR frame.

## Packing
| Attribute  | Value     |
|------------|-----------|
| Bit order  | LSB First |

## Ports
- input  logic        reset_in
- input  logic        clk_in
- input  logic        ir_signal_in
- output logic [11:0] ir_frame_out
- output logic        ir_frame_valid
"""

# Correct LSB-first RTL: shift-insert {decoded_bit, ir_frame_reg[11:1]}.
RTL_LSB = r"""module ir_receiver (
    input  logic        reset_in,
    input  logic        clk_in,
    input  logic        ir_signal_in,
    output logic [11:0] ir_frame_out,
    output logic        ir_frame_valid
);
    logic [11:0] ir_frame_reg;
    logic        decoded_bit;
    always_ff @(posedge clk_in or posedge reset_in) begin
        if (reset_in) begin
            ir_frame_reg   <= 12'd0;
            ir_frame_out   <= 12'd0;
            ir_frame_valid <= 1'b0;
        end else begin
            // LSB first: insert decoded bit at the MSB, shift right.
            ir_frame_reg <= {decoded_bit, ir_frame_reg[11:1]};
        end
    end
endmodule
"""

# POSITIVE TB: drives bit[0] first..bit[11] last (indexed per-bit loop) and asserts
# ir_frame_out === frame (the ordering equality). Contains NO literal "lsb first".
TB_FAITHFUL = r"""`timescale 1ns/1ps
module tb;
    logic reset_in, clk_in, ir_signal_in;
    logic [11:0] ir_frame_out;
    logic ir_frame_valid;
    ir_receiver dut (.*);
    always #5000 clk_in = ~clk_in;
    task hold(input bit val, input int n);
        for (int k = 0; k < n; k++) @(posedge clk_in) ir_signal_in <= val;
    endtask
    task send_bit(input bit b);
        hold(1'b0, 60);
        hold(1'b1, b ? 120 : 60);
    endtask
    logic [11:0] frame;
    integer i;
    initial begin
        clk_in = 0; reset_in = 1; ir_signal_in = 0;
        repeat (3) @(posedge clk_in);
        reset_in <= 0;
        @(posedge clk_in);
        hold(1'b1, 240);
        frame = 12'h456;
        for (i = 0; i < 12; i++) send_bit(frame[i]);   // first bit -> frame[0]
        repeat (5) @(posedge clk_in);
        if (ir_frame_out !== frame)                     // ordering equality assert
            $display("ORDER MISMATCH got=0x%03h exp=0x%03h", ir_frame_out, frame);
        else
            $display("ORDER OK got=0x%03h", ir_frame_out);
        $finish;
    end
endmodule
"""

# §4.05 NEGATIVE TB: drives a fixed pattern but never indexes a vector per-bit and
# never asserts an ordering equality -> does NOT exercise the bit order -> GAP.
TB_NO_ORDER = r"""`timescale 1ns/1ps
module tb;
    logic reset_in, clk_in, ir_signal_in;
    logic [11:0] ir_frame_out;
    logic ir_frame_valid;
    ir_receiver dut (.*);
    always #5000 clk_in = ~clk_in;
    task hold(input bit val, input int n);
        for (int k = 0; k < n; k++) @(posedge clk_in) ir_signal_in <= val;
    endtask
    initial begin
        clk_in = 0; reset_in = 1; ir_signal_in = 0;
        repeat (3) @(posedge clk_in);
        reset_in <= 0;
        @(posedge clk_in);
        hold(1'b1, 240);
        hold(1'b0, 60); hold(1'b1, 60);
        repeat (5) @(posedge clk_in);
        $display("done valid=%b", ir_frame_valid);
        $finish;
    end
endmodule
"""


def _run(tmp_path, spec, rtl, tb):
    spec_p = tmp_path / "spec.md"
    rtl_p = tmp_path / "ir_receiver.sv"
    tb_p = tmp_path / "tb.sv"
    spec_p.write_text(spec)
    rtl_p.write_text(rtl)
    tb_p.write_text(tb)
    res = subprocess.run(
        [sys.executable, str(PROG),
         "--prompt", str(spec_p),
         "--rtl", str(rtl_p),
         "--tb", str(tb_p),
         "--strict"],
        capture_output=True, text=True, cwd=str(PROGRAMS_DIR))
    return res.returncode, res.stdout + res.stderr


def test_positive_lsb_faithful_tb_passes(tmp_path):
    """The affected id's spec-faithful TB (indexed per-bit drive + ordering
    equality, NO literal 'lsb first') on correct LSB-first RTL now passes."""
    assert "lsb first" not in TB_FAITHFUL.lower(), "fixture must not game the token"
    rc, out = _run(tmp_path, SPEC_PROSE, RTL_LSB, TB_FAITHFUL)
    assert rc == 0, f"expected rc=0 (pass), got rc={rc}\n{out}"
    assert "[OK]   byte_order" in out, out


def test_no_leak_tb_not_exercising_order_still_blocks(tmp_path):
    """§4.05: a TB that does NOT structurally exercise the bit order (no indexed
    per-bit loop, no ordering equality) still hard-blocks."""
    rc, out = _run(tmp_path, SPEC_PROSE, RTL_LSB, TB_NO_ORDER)
    assert rc == 1, f"expected rc=1 (block), got rc={rc}\n{out}"
    assert "byte_order" in out and "UNCOVERED" in out, out


def test_no_leak_markdown_table_byte_order_keeps_block(tmp_path):
    """§4.05: a byte_order stated in a MARKDOWN TABLE is a STRUCTURAL source and
    keeps its hard block when the TB does not exercise it (never reaches the new
    prose-heuristic corroboration branch)."""
    rc, out = _run(tmp_path, SPEC_TABLE, RTL_LSB, TB_NO_ORDER)
    assert rc == 1, f"expected rc=1 (structural block), got rc={rc}\n{out}"
    assert "byte_order" in out and "UNCOVERED" in out, out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
