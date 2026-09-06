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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _hostpaths import require_docker_cli  # noqa: E402

import design_one_shot_runner as R          # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

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


def _stage_neutralized(tmp_path):
    proj = tmp_path / "proj"
    rtl = proj / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (proj / "input" / "docs").mkdir(parents=True)
    (proj / "input" / "docs" / "design_description.md").write_text(
        "# counter — 8-bit up counter\n\nInput ports:\n    clk: clock input\n"
        "    resetn: active-low synchronous reset\nOutput ports:\n"
        "    cnt: 8-bit count value\n")
    core = ("module counter__rcvar_inner (\n    input clk,\n    input resetn,\n"
            "    output reg [7:0] cnt\n);\n"
            "    always @(posedge clk) begin\n"
            "        if (!resetn) cnt <= 8'd0;\n"
            "        else cnt <= cnt + 8'd1;\n    end\nendmodule\n")
    (rtl / "counter.v").write_text(core + "\n" + _NEUTRALIZED_WRAPPER)
    (rtl / "top_wrap.v").write_text(
        "module counter_sync (\n    input clk,\n    input resetn,\n"
        "    output [7:0] cnt\n);\n"
        "    counter__rcvar_inner u_c (.clk(clk), .resetn(resetn), .cnt(cnt));\n"
        "endmodule\n")
    return proj


def test_reemit_restores_pull_and_design_resets(tmp_path):
    """The #119 artifact repro as the end state: a project whose inner wrapper
    is ALREADY neutralized, chip_top absent -> synth re-emits chip_top -> the
    outermost faces must carry the restored VERILATOR pull, and the design
    must actually reset through the two-level chain on the host simulator."""
    require_docker_cli("test_reemit_restores_pull_and_design_resets")
    import os
    container = os.environ.get("VIBEIC_IVERILOG13_CONTAINER", "vibeic-eda")
    probe = subprocess.run(["docker", "exec", container, "sh", "-c", "true"],
                           capture_output=True)
    if probe.returncode != 0:
        pytest.skip(f"container {container!r} not running")
    proj = _stage_neutralized(tmp_path)
    r = R.step_yosys_synth(proj, "chip_top")
    assert r.status == "PASS", r.detail
    ct = (proj / "phase2" / "stage1" / "rtl" / "chip_top.v").read_text()
    assert ct.count("tri1") == 2, "re-emitted chip_top must carry the restored pull"
    assert ct.count("`ifdef VERILATOR") == 2
    if not shutil.which("iverilog"):
        return
    for sp in ("resetn", "rst_n"):
        tb = tmp_path / f"tb_{sp}.v"
        tb.write_text(
            "module tb;\n  reg clk=0, r; wire [7:0] cnt; reg ok=1;\n"
            f"  chip_top u (.{sp}(r), .clk(clk), .cnt(cnt));\n"
            "  always #1 clk = ~clk;\n"
            "  initial begin\n"
            "    r = 0; #6; if (cnt !== 8'd0) ok = 0;\n"
            "    r = 1; #6; if (cnt === 8'd0 || cnt === 8'hxx) ok = 0;\n"
            "    r = 0; #6; if (cnt !== 8'd0) ok = 0;\n"
            "    if (ok) $display(\"RESET_OK\"); else $display(\"RESET_DEAD\");\n"
            "    $finish;\n  end\nendmodule\n")
        binp = tmp_path / f"b_{sp}"
        c = subprocess.run(
            ["iverilog", "-g2012", "-s", "tb", "-o", str(binp), str(tb),
             str(proj / "phase2" / "stage1" / "rtl" / "chip_top.v"),
             str(proj / "phase2" / "stage1" / "rtl" / "counter.v")],
            capture_output=True, text=True)
        assert c.returncode == 0, c.stderr
        rr = _pr.run(["vvp", str(binp)], capture_output=True,
                            text=True)
        assert "RESET_OK" in rr.stdout, (sp, rr.stdout)
