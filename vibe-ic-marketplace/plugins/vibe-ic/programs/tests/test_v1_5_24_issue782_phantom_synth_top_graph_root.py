"""ORGANIC #782 — the #683 phantom-synth-top fallback only fires for the
LITERAL auto-wrapper name 'chip_top'.

現象: a REUSED-IP / catalog-glue project is driven with an explicit
``--top-name <ic_name>`` (the campaign harness passes the IC name, e.g.
``--top-name ibex``). That name is PHANTOM — no staged file declares it. The
authored integration wrapper is staged under its own name (``chip_top``), and
Phase-1 doc-extraction lifted a prose top into ``L9.top_module`` ('ibex_top')
which is ALSO phantom, with ``L9.synth_top`` null.

The synth-top precedence (waiver -> L9.synth_top -> <top>_asic.sv -> caller
top_name) therefore resolves ``synth_top='ibex'``, and yosys is invoked
``read_slang ... --top ibex`` -> ``error: 'ibex' is not a valid top-level
module`` -> Phase-2 FAIL.

ORGANIC #683 added exactly the right repair for this — consult the structural
instantiation-graph resolver (`_v661_resolve_dut_module`, the same one the TB
path trusts) and adopt a real graph root. But its guard was written as
``if synth_top == top_name == "chip_top"``, keying on the literal runner
auto-wrapper name rather than on the condition that name was standing in for:
"the resolved top is not a module that exists in staged rtl/". So the identical
failure with any OTHER phantom name fell straight through.

Fix: guard on ``synth_top == top_name`` (precedence fell through, so no
waiver / L9.synth_top / <top>_asic.sv override is in play) AND
``synth_top not in staged_modules`` (yosys is GUARANTEED to reject it). That
can only ever convert a certain FAIL into a structurally-resolved top; it can
never redirect a top that would have worked.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as P2  # noqa: E402


def _stage(rtl: Path, files: dict) -> None:
    rtl.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (rtl / name).write_text(text)


# A catalog-glue shape: authored `chip_top` wrapper + vendor leaves. NOTHING
# declares the caller-supplied top name.
_GLUE = {
    "chip_top.sv": (
        "module chip_top (input clk, input rst_n, output q);\n"
        "  core_alu u_alu (.clk(clk), .rst_n(rst_n), .q(q));\n"
        "endmodule\n"),
    "core_alu.sv": (
        "module core_alu (input clk, input rst_n, output q);\n"
        "  leaf_reg u_r (.clk(clk), .d(rst_n), .q(q));\n"
        "endmodule\n"),
    "leaf_reg.sv": (
        "module leaf_reg (input clk, input d, output q);\n"
        "  assign q = d;\nendmodule\n"),
}






def test_resolver_finds_the_graph_root_directly(tmp_path):
    """The structural resolver itself returns the authored wrapper."""
    proj = tmp_path / "proj"
    _stage(proj / "phase2" / "stage1" / "rtl", _GLUE)

    mods = set(P2._v661_rtl_module_names(proj))
    assert "ibex" not in mods and "chip_top" in mods
    assert P2._v661_resolve_dut_module(proj, "ibex", None) == "chip_top"
