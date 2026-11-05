"""A fresh front door whose SoC top is still owed must not crash phase 2.

MEASURED on subservient x gf180mcuD, IC path (DIE), main 90738d258, a fresh
input-only copy on 8HD-3 (2026-09-29): rtl_gen fetched the reused core and
handed the SoC glue to `catalog-glue-author`, so `rtl/` held the core's leaves
and no `subservient` module. The generic full-stack TB
(`tb_subservient_full.v`, `subservient u_dut (`) was compiled inside the EDA
container and iverilog answered

    /foss/designs/<proj>/phase2/stage1/sim_full_stack/tb_subservient_full.v:36:
    error: Unknown module type: subservient

Two defects, one crash:
  1. the step booked that as FAIL "real structural defect" -- a design not
     written yet is not a structural defect;
  2. the detail quoted the stderr in the CONTAINER's spelling of the project,
     `_refuse_relocated_copy_in_record` read `/foss/designs/<proj>/...` as a
     relocated copy, and phase 2 died with `_RecordNamesRelocatedCopy` and no
     report at all.

Now: the top is NOT_MEASURED (awaiting_agent_pass) ONLY on positive evidence
that it is owed in THIS run -- the current rtl_gen result handed authoring to a
skill it staged, passed in by the caller -- AND no module of that name exists
anywhere under rtl/ (recursively, any accepted header form) nor in the TB.
Otherwise it is compiled and an Unknown-module error FAILs (review wave58 S1,
S2, S3, S5). Tool output from the container comes back in host spelling from
the container's own mount table.
The simulator and the docker client are stand-ins; the sources are synthetic.
"""
from __future__ import annotations

import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import design_one_shot_runner as runner  # noqa: E402

CONT_ROOT = "/foss/designs"
TB = """`timescale 1ns/1ps
module tb_soc_top_full;
  reg i_clk = 0;
  reg i_rst = 1;
  wire o_led;
  always #10 i_clk = ~i_clk;
  // the design top instantiated from L9.top_ports
  soc_top u_dut (
    .i_clk(i_clk),
    .i_rst(i_rst),
    .o_led(o_led)
  );
  initial begin #100 $display("FULL_STACK_TB_DONE"); $finish; end
endmodule
"""
LEAF = "module core_leaf(input i_clk, output o_q); assign o_q = i_clk; endmodule\n"
TOP = ("module soc_top(input i_clk, input i_rst, output o_led);\n"
       "  core_leaf u_leaf(.i_clk(i_clk), .o_q(o_led));\nendmodule\n")
SKILL = ("---\nname: catalog-glue-author\ndescription: author the SoC glue\n"
         "---\n")
















def test_a_path_no_mount_covers_is_left_as_printed(monkeypatch):
    monkeypatch.setattr(runner, "_container_mounts",
                        lambda c: [("/data/x", CONT_ROOT),
                                   ("/same", "/same")])
    f = getattr(runner, "_container_text_to_host", None)
    assert f is not None
    text = ("/foss/designs/p/a.v:1: e\n/foss/designsX/p/b.v\n"
            "/foss/pdks/lib.v\n/same/q.v\n'/foss/designs'")
    assert f(text, "c") == ("/data/x/p/a.v:1: e\n/foss/designsX/p/b.v\n"
                            "/foss/pdks/lib.v\n/same/q.v\n'/data/x'")




# ---------------------------------------------------------------------------
# review wave58 (integrity, MAJOR): absence alone never books "owed".
# Each must FAIL (compiled, Unknown module / real error) -- on the old code
# they were NOT_MEASURED.
# ---------------------------------------------------------------------------


UNUSED = "module spare_unused(input a, output b); assign b = a; endmodule\n"
