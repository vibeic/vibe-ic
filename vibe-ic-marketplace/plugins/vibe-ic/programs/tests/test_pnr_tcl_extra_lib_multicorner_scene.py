"""Regression: pnr.tcl must NOT emit a bare `read_liberty <lib>` for an
extra / hard-macro liberty under a multi-scene (multi-corner) `define_corners`
stanza — OpenSTA/OpenROAD 26Q3+ abort such a bare read with
`[ERROR STA-0103] -scene keyword required with multi-scene analysis`, killing
pnr.tcl before floorplan. The extra lib (single timing view) must be read into
EVERY defined corner instead. Single-corner PnR must stay byte-identical.

Chip/PDK-AGNOSTIC by construction: every fixture here is a SYNTHETIC neutral
name (GENERIC_HARDMACRO, generic corners, /work/... paths). No vendor / SKU /
design literal appears in this test.
"""
import importlib

m = importlib.import_module("phase3_one_shot_runner")
qualify = m._corner_qualify_extra_libs


_MULTI = (
    "define_corners ss tt ff\n"
    "read_liberty -corner ss /work/stdcell_ss.lib\n"
    "read_liberty -corner tt /work/stdcell_tt.lib\n"
    "read_liberty -corner ff /work/stdcell_ff.lib"
)
_MACRO_BARE = "read_liberty /work/GENERIC_HARDMACRO_tt.lib"


def test_multicorner_expands_extra_lib_to_every_corner():
    out = qualify(_MACRO_BARE, _MULTI)
    lines = out.splitlines()
    assert "read_liberty -corner ss /work/GENERIC_HARDMACRO_tt.lib" in lines
    assert "read_liberty -corner tt /work/GENERIC_HARDMACRO_tt.lib" in lines
    assert "read_liberty -corner ff /work/GENERIC_HARDMACRO_tt.lib" in lines
    # THE BUG GUARD: no bare read for the macro survives under multi-scene.
    assert _MACRO_BARE not in lines
    assert not any(
        ln.strip() == _MACRO_BARE for ln in lines), "bare read_liberty leaked"


def test_multiple_extra_libs_each_expand():
    two = ("read_liberty /work/GENERIC_HARDMACRO_A_tt.lib\n"
           "read_liberty /work/GENERIC_HARDMACRO_B_tt.lib")
    out = qualify(two, _MULTI)
    # 2 libs x 3 corners = 6 corner-qualified reads, 0 bare.
    corner_reads = [ln for ln in out.splitlines()
                    if ln.startswith("read_liberty -corner ")]
    assert len(corner_reads) == 6
    assert not any(
        m2.startswith("read_liberty /work/GENERIC_HARDMACRO")
        for m2 in out.splitlines())


def test_single_corner_is_byte_identical_noop():
    # No corner stanza -> single-corner PnR -> unchanged (byte-identical).
    assert qualify(_MACRO_BARE, None) == _MACRO_BARE
    assert qualify(_MACRO_BARE, "") == _MACRO_BARE


def test_fewer_than_two_corners_is_noop():
    one = "define_corners tt\nread_liberty -corner tt /work/stdcell_tt.lib"
    assert qualify(_MACRO_BARE, one) == _MACRO_BARE


def test_empty_macro_libs_noop():
    assert qualify("", _MULTI) == ""
    assert qualify("   ", _MULTI) == "   "


def test_already_qualified_lines_untouched():
    already = ("read_liberty -corner ss /work/GENERIC_HARDMACRO_tt.lib\n"
               "read_liberty -corner tt /work/GENERIC_HARDMACRO_tt.lib")
    # lines already carrying -corner must pass through verbatim, not re-expand.
    assert qualify(already, _MULTI) == already


def test_build_pnr_tcl_text_end_to_end_no_bare_macro_read():
    """Integration: the assembled pnr.tcl carries per-corner macro reads and
    no bare macro read when a multi-corner corner_liberty_block is supplied."""
    macro_bare = "read_liberty /work/GENERIC_HARDMACRO_tt.lib"
    kw = dict(
        tech_lef_c="/work/tech.lef", cell_lef_c="/work/cells.lef",
        macro_lefs_tcl="read_lef /work/GENERIC_HARDMACRO.lef",
        liberty_c="/work/stdcell_tt.lib", macro_libs_tcl=macro_bare,
        netlist_c="/work/netlist.v", top="generic_top",
        sdc_c="/work/c.sdc", dont_use_block="", metal_prefix="M",
        die_w=100, die_h=100, core_pad=5, core_w=90, core_h=90,
        site="unit", out_dir_c="/work/out", tapcell_block="",
        pdn_block="", util=0.5, spare_protection_tcl="",
        spare_postfix_tcl="", clk_buf="BUF", clk_buf_root="BUF",
        routing_constraint_tcl="", pg_cleanup_block="",
        spef_repair_block="", antenna_repair_block="", filler_block="",
        corner_liberty_block=_MULTI,
    )
    tcl = m._build_pnr_tcl_text(**kw)
    assert "read_liberty -corner ss /work/GENERIC_HARDMACRO_tt.lib" in tcl
    assert "read_liberty -corner tt /work/GENERIC_HARDMACRO_tt.lib" in tcl
    assert "read_liberty -corner ff /work/GENERIC_HARDMACRO_tt.lib" in tcl
    assert not any(
        ln.strip() == macro_bare for ln in tcl.splitlines()
    ), "bare macro read_liberty leaked into multi-corner pnr.tcl"

    # single-corner: bare macro read is preserved (byte-identical behavior)
    kw_single = dict(kw)
    kw_single["corner_liberty_block"] = None
    tcl1 = m._build_pnr_tcl_text(**kw_single)
    assert any(ln.strip() == macro_bare for ln in tcl1.splitlines())
