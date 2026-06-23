"""ORGANIC #614 [HIGH] — ASIC source selector mis-classified real RTL leaves
as FPGA-board wrappers when they top-of-file `include` a sibling macro/HEADER
(.sv with include-guard + `define only, NO module decl, e.g. prim_assert.sv).

_is_fpga_board_wrapper Signal 1 treated ANY sibling-include as a wrapper
signal → _select_asic_rtl_sources dropped the leaf → slang/yosys aborted with
"unknown module '<core>'".

POSITIVE: a leaf that includes a pure macro/header sibling is NOT a wrapper
(kept in the synth source list).

NEGATIVE no-leak: a real wrapper that includes a sibling MODULE is STILL
flagged as a wrapper (the fix only spares header-shaped includes).

chip-AGNOSTIC: keys on "does the included sibling declare a module", pure
structural; no chip/vendor names.
"""
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs"))
import design_one_shot_runner as P  # noqa: E402

_MACRO_HEADER = (
    "`ifndef PRIM_ASSERT_SV\n"
    "`define PRIM_ASSERT_SV\n"
    "`define ASSERT(name, prop) // no-op\n"
    "`endif\n"
)
_LEAF_INCLUDING_HEADER = (
    '`include "prim_assert.sv"\n'
    "module ibex_core(input clk, input rst_n, output q);\n"
    "  assign q = 1'b0;\n"
    "endmodule\n"
)
_SIBLING_MODULE = "module core_mod(input a, output b); assign b = a; endmodule\n"
_WRAPPER_INCLUDING_MODULE = (
    '`include "core_mod.sv"\n'
    "module board_top(input clk, output led);\n"
    "  core_mod u(.a(clk), .b(led));\n"
    "endmodule\n"
)


def _make_rtl(tmp_path):
    rtl = tmp_path / "rtl"
    rtl.mkdir()
    (rtl / "prim_assert.sv").write_text(_MACRO_HEADER)
    (rtl / "ibex_core.sv").write_text(_LEAF_INCLUDING_HEADER)
    (rtl / "core_mod.sv").write_text(_SIBLING_MODULE)
    (rtl / "board_top.sv").write_text(_WRAPPER_INCLUDING_MODULE)
    return rtl


def test_sibling_declares_module_helper(tmp_path):
    rtl = _make_rtl(tmp_path)
    assert P._sibling_declares_module(rtl / "prim_assert.sv") is False
    assert P._sibling_declares_module(rtl / "core_mod.sv") is True
    assert P._sibling_declares_module(rtl / "does_not_exist.sv") is False  # fail-open


def test_leaf_including_macro_header_not_wrapper(tmp_path):
    rtl = _make_rtl(tmp_path)
    siblings = {p.name for p in rtl.glob("*.sv")}
    # POSITIVE: ibex_core includes prim_assert.sv (a macro header) → NOT a wrapper
    assert P._is_fpga_board_wrapper(rtl / "ibex_core.sv", siblings) is False


def test_wrapper_including_module_sibling_still_flagged(tmp_path):
    rtl = _make_rtl(tmp_path)
    siblings = {p.name for p in rtl.glob("*.sv")}
    # NO-LEAK: board_top includes core_mod.sv (declares a module) → STILL a wrapper
    assert P._is_fpga_board_wrapper(rtl / "board_top.sv", siblings) is True


def test_select_asic_sources_keeps_leaf(tmp_path):
    rtl = _make_rtl(tmp_path)
    result = P._select_asic_rtl_sources(rtl)
    # flatten whatever shape the selector returns (tuple of lists / list)
    flat = []
    for x in (result if isinstance(result, (list, tuple)) else [result]):
        flat.extend(x if isinstance(x, (list, tuple)) else [x])
    names = {Path(p).name for p in flat}
    assert "ibex_core.sv" in names, (
        f"the RTL leaf must stay in the synth source list, got {sorted(names)}")
    assert "board_top.sv" not in names, "the real wrapper must still be excluded"
