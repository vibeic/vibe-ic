"""Regression — phase-3 must resolve the synthesizable ASIC top STRUCTURALLY,
in parity with phase-2 (design_one_shot_runner._v661_resolve_dut_module).

Defect (caravel_user_project x sky130A clean-run): the orchestrator's
--top-name is the PROJECT / SKU name `caravel_user_project`, but the actual
synthesizable top MODULE in rtl/ is `user_project_wrapper` (the SKU name is
never a Verilog module — it is only the git-repo / L1 product name, and L9's
`top_module` echoes that phantom). Phase-3 main() resolved effective_top by
probing ONLY `<top>_asic` / `<top>_pad_wrapper` .sv variants; neither exists,
so it kept `caravel_user_project` and ran `yosys synth -top caravel_user_project`
→ HIERARCHY pass "Module `caravel_user_project' not found!" → no netlist → no
PnR → no phase3/stage3/pnr/constraint.sdc → step-7's required-output gate
`phase2/stage2/constraints/*.sdc` FAILED → every stage-3/4 gate cascaded to
blocked-by-upstream. Meanwhile phase-2 synth PASSED on the SAME rtl/ because it
uses the structural resolver — a same-project synth-top divergence.

_resolve_asic_top_structural mirrors phase-2's precedence:
  (a) --top-name when it is a real module in rtl/;
  (b) L9.top_module when it is a real module in rtl/;
  (c) the single instantiation-graph root (the module nobody instantiates).
"""
from __future__ import annotations

import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as p3  # noqa: E402


def _rtl(project: Path, name: str, text: str) -> None:
    d = project / "phase2" / "stage1" / "rtl"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text)


# Minimal caravel-shaped rtl/: a parameterised wrapper (`#(...)`) that
# instantiates an example, which instantiates a counter. The SKU name
# `caravel_user_project` is NOT a module here.
_WRAPPER = """\
`default_nettype none
module user_project_wrapper #(
    parameter BITS = 32
) (
    input  wb_clk_i,
    input  [`MPRJ_IO_PADS-1:0] io_in,
    output [`MPRJ_IO_PADS-1:0] io_out
);
    user_proj_example mprj (.wb_clk_i(wb_clk_i));
endmodule
"""
_EXAMPLE = """\
module user_proj_example #(parameter BITS = 32) (input wb_clk_i);
    counter u_c (.clk(wb_clk_i));
endmodule
module counter #(parameter N = 8) (input clk);
endmodule
"""


def test_reproduce_phantom_sku_resolves_to_wrapper(tmp_path):
    """(c) — the SKU/--top-name is not a module → the instantiation-graph root
    (`user_project_wrapper`, the module nobody instantiates) is chosen."""
    _rtl(tmp_path, "user_project_wrapper.v", _WRAPPER)
    _rtl(tmp_path, "user_proj_example.v", _EXAMPLE)
    got = p3._resolve_asic_top_structural(tmp_path, "caravel_user_project", None)
    assert got == "user_project_wrapper", got


def test_negative_control_real_top_name_untouched(tmp_path):
    """(a) — when --top-name IS a real module it is returned unchanged; the
    resolver never rewrites an already-correct top."""
    _rtl(tmp_path, "user_project_wrapper.v", _WRAPPER)
    _rtl(tmp_path, "user_proj_example.v", _EXAMPLE)
    got = p3._resolve_asic_top_structural(tmp_path, "user_project_wrapper", None)
    assert got == "user_project_wrapper", got


def test_phantom_l9_top_module_does_not_win(tmp_path):
    """(b) guard — a phantom L9.top_module (== the SKU name, absent from rtl/)
    must NOT be selected; the graph root wins instead."""
    _rtl(tmp_path, "user_project_wrapper.v", _WRAPPER)
    _rtl(tmp_path, "user_proj_example.v", _EXAMPLE)
    got = p3._resolve_asic_top_structural(
        tmp_path, "caravel_user_project", "caravel_user_project")
    assert got == "user_project_wrapper", got


def test_real_l9_top_module_wins_over_graph_root(tmp_path):
    """(b) — a real L9.top_module is honoured even if it is not the unique
    graph root (defence: L9 naming an actual staged module)."""
    _rtl(tmp_path, "user_project_wrapper.v", _WRAPPER)
    _rtl(tmp_path, "user_proj_example.v", _EXAMPLE)
    got = p3._resolve_asic_top_structural(
        tmp_path, "caravel_user_project", "user_proj_example")
    assert got == "user_proj_example", got


def test_no_rtl_returns_none(tmp_path):
    """(d) — no parseable rtl/ → None so the caller keeps its legacy fallback."""
    assert p3._resolve_asic_top_structural(tmp_path, "whatever", None) is None


def test_comment_mention_is_not_a_module(tmp_path):
    """A module name that appears only in a comment must not be treated as a
    definition or an instantiation (comment-strip correctness)."""
    _rtl(tmp_path, "top.v",
         "// caravel_user_project is the product name, not a module\n"
         "module the_real_top (input clk);\n"
         "  /* user_project_wrapper mentioned here too */\n"
         "endmodule\n")
    got = p3._resolve_asic_top_structural(tmp_path, "caravel_user_project", None)
    assert got == "the_real_top", got
