"""SLOW-corner (SS) setup closure — the resizer/buffer_ports must NEVER insert a
SIGNAL DELAY macro (``__dly*`` / ``__delay*``) as a plain signal/port buffer.

Root cause (spm × gf180mcuD, STOCK image, base PnR route — MEASURED live):
  * ``buffer_ports -inputs`` picks a cell OpenROAD reports ``is_buffer=true`` for.
    In gf180mcu the delay macros ``dlya/dlyb/dlyc/dlyd_*`` carry that flag, and
    ``buffer_ports`` inserted 33 ``__dlyd_1`` delay cells — one on every input bit
    ``x[0..32]`` — each adding ~2.4 ns (typ) / ~4.9 ns (SS 125C/4v50) to the
    input→FF datapath.
  * The TYP corner still MET (+3.85 ns) but the SS SIGN-OFF setup corner went
    VIOLATED (-0.56 ns, TNS -0.98): the single-corner-closure confounder — a
    typ-only "MET" masking a slow-corner blow-up.
  * Excluding the delay family (like ``__clkdlybuf`` already is) makes
    ``buffer_ports`` insert the normal ``buf_1``; the SS setup path then closes IN
    THE BASE ROUTE, 0-DRC, no ECO. MEASURED end-to-end on the stock :0.2.28 image:
    SS setup -0.56 -> +2.25 ns MET, detailed_route Number of violations = 0.

These pin the EMISSION contract (chip-AGNOSTIC, no OpenROAD needed):
  the delay family is excluded, via liberty-scoped get_lib_cells, BEFORE
  buffer_ports, and normal buffers are preserved. Delay macros are legitimate
  ONLY for deliberate hold padding, never as signal/port buffers, in ANY PDK.
"""
import importlib

R = importlib.import_module("phase3_one_shot_runner")


def _fallback():
    return R._dont_use_family_fallback_tcl()


def test_signal_delay_family_is_excluded():
    tcl = _fallback()
    # both the abbreviated (dlya/dlyb/dlyc/dlyd, dlygate, dlymetal, dlybuf, …)
    # and spelled-out delay-macro name families are excluded.
    assert "*__dly*" in tcl
    assert "*__delay*" in tcl


def test_delay_exclusion_is_liberty_scoped_and_nonfatal():
    tcl = _fallback()
    # applied over whatever liberty was actually read (empty-match PDKs skip),
    # via set_dont_use, guarded — never a hard failure on a PDK without them.
    assert "get_lib_cells -quiet $_du_pat" in tcl
    assert "set_dont_use" in tcl
    assert "DONT_USE_FALLBACK_NONFATAL" in tcl


def test_normal_buffers_are_NOT_excluded():
    # negative control: the fix must not disable the resizer's real buffers.
    # A plain buffer / clock buffer exclusion pattern must never be emitted —
    # only the delay-CLOCK master (__clkdlybuf) and signal delay macros are.
    tcl = _fallback()
    du_line = next(l for l in tcl.splitlines() if "foreach _du_pat" in l)
    assert "*__buf_*" not in du_line          # normal signal buffers kept
    assert "*__clkbuf_*" not in du_line        # CTS clock buffers kept
    assert "*__clkbuf*" not in du_line
    # the pre-existing families remain excluded (no regression of the v1.2.86 fix)
    assert "*__probe_*" in du_line
    assert "*__lpflow_*" in du_line
    assert "*__clkdlybuf*" in du_line          # clock DELAY buffer still excluded


def test_delay_exclusion_precedes_buffer_ports_in_pnr_tcl():
    # the exclusion must be emitted BEFORE `buffer_ports -inputs`, or the port
    # buffering would already have picked a delay cell before it is forbidden.
    tcl = R._build_pnr_tcl_text(
        tech_lef_c="/x/tech.lef", cell_lef_c="/x/cell.lef",
        macro_lefs_tcl="", liberty_c="/x/c.lib", macro_libs_tcl="",
        netlist_c="/x/d.v", top="d", sdc_c="/x/d.sdc",
        dont_use_block=_fallback(),
        metal_prefix="met", die_w=100, die_h=100, core_pad=10,
        core_w=90, core_h=90, site="unit", out_dir_c="/out",
        tapcell_block="", pdn_block="", util=0.3,
        spare_protection_tcl="", spare_postfix_tcl="",
        clk_buf="BUF", clk_buf_root="BUF", routing_constraint_tcl="",
        pg_cleanup_block="", spef_repair_block="",
        antenna_repair_block="", filler_block="")
    assert "*__dly*" in tcl
    assert "buffer_ports -inputs" in tcl
    assert tcl.index("*__dly*") < tcl.index("buffer_ports -inputs")


def test_delay_exclusion_carries_no_chip_literal():
    # chip-AGNOSTIC: the exclusion keys on the std-cell FUNCTION family, never on
    # a PDK / vendor / SKU / design literal.
    tcl = _fallback().lower()
    for banned in ("gf180", "sky130", "spm", "mcu7t5v0", "dlyd_1"):
        assert banned not in tcl
