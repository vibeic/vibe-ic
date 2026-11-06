"""#119 — chip_top RE-EMIT after the inner reset-alias wrapper was already
neutralized (#115 follow-up's documented latent fragility, now closed).

DEFECT (artifact-level, reproduced): the neutralize step (v1.3.85) rewrites
the inner wrapper's port faces to plain inputs IN PLACE; a later chip_top
re-emit (chip_top.v deleted, wrapper NOT regenerated) copied the now-plain
block verbatim -> a PULL-LESS chip_top. Under Verilator an unbound plain
input ties to 0 — for an active-low reset that is PERMANENTLY ASSERTED: the
re-emitted design was frozen in reset (RESET_DEAD cnt=00; iverilog unaffected
via the wrapper's internal else-arm pulls).

FIX: `_chip_top_restore_vl_port_tri` — when the copied block carries NO
`ifdef VERILATOR tri (already-neutralized inner) but the inner text carries
the additive-wrapper body signature (`tri0/tri1 <face>__rcvar_pull;`), wrap
each such face's declaration in chip_top's block with the `ifdef VERILATOR
tri qualifier (canonical order: direction, guarded net type, range, name).
Verified end-to-end: re-emit -> chip_top tri x2 -> RESET_OK on Verilator
5.048 AND iverilog 12, both spellings.
"""
import re
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))



import design_one_shot_runner as R          # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_NEUTRALIZED_WRAPPER = """\
module counter (
    input clk,
    input
    resetn,
    input
    rst_n,
    output [7:0] cnt
);
`ifdef VERILATOR
    wire resetn__rcvar_net = resetn & rst_n;
`elsif YOSYS
    wire resetn__rcvar_net = resetn & rst_n;
`else
    tri1 resetn__rcvar_pull;
    tri1 rst_n__rcvar_pull;
    assign resetn__rcvar_pull = resetn;
    assign rst_n__rcvar_pull = rst_n;
    wire resetn__rcvar_net = resetn__rcvar_pull & rst_n__rcvar_pull;
`endif
    counter__rcvar_inner u_counter__rcvar_inner (
        .clk(clk),
        .resetn(resetn__rcvar_net),
        .cnt(cnt)
    );
endmodule
"""


def test_restore_wraps_pull_faces_with_vl_tri():
    block = "(\n    input clk,\n    input resetn,\n    input rst_n,\n    output [7:0] cnt\n)"
    out = R._chip_top_restore_vl_port_tri(block, _NEUTRALIZED_WRAPPER)
    assert out is not None
    assert out.count("`ifdef VERILATOR") == 2
    assert out.count("tri1") == 2
    # tri wraps ONLY the reset faces; clk/cnt untouched
    assert re.search(r"input\s+clk", out)
    assert "output [7:0] cnt" in out
    # canonical order: direction, guarded tri, name — parses round-trip
    for face in ("resetn", "rst_n"):
        assert re.search(
            rf"input\s*\n`ifdef VERILATOR\s*\n\s*tri1\s*\n`endif\s*\n\s*{face}",
            out), out


def test_restore_noop_without_pull_signature():
    block = "(\n    input clk,\n    input resetn,\n    output [7:0] cnt\n)"
    plain = "module counter (input clk, input resetn, output [7:0] cnt);\nendmodule\n"
    assert R._chip_top_restore_vl_port_tri(block, plain) is None
