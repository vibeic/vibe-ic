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
import fnmatch
import importlib
import re

R = importlib.import_module("phase3_one_shot_runner")


def _fallback():
    return R._dont_use_family_fallback_tcl()


def _patterns():
    """The patterns the emitted block actually feeds `get_lib_cells`."""
    line = next(l for l in _fallback().splitlines() if "foreach _du_pat" in l)
    return re.search(r"\{(.*?)\}", line).group(1).split()


def _mode():
    """The matching mode the emitted block ASKS FOR, read from the flags it
    passes to `get_lib_cells` on the `$_du_pat` lookup — not from the buffer
    counter's own unrelated `get_lib_cells *`."""
    m = re.search(r"get_lib_cells((?: -\w+)*) \$_du_pat", _fallback())
    flags = m.group(1) if m else ""
    regexp = "-regexp" in flags
    return regexp, ("-nocase" in flags and regexp)


def _matches(cell):
    """True when the emitted block would exclude ``cell``.

    Mirrors what OpenSTA does with what was ACTUALLY emitted, so this is the
    SAME decision the tool makes -- not a re-statement of the pattern literals,
    and not an assumption about which mode the block asked for. Two measured
    facts drive the mirror (OpenSTA inside OpenROAD, in-container):
      * ``-nocase`` is IGNORED without ``-regexp`` -- the tool prints
        ``[WARNING STA-0358] -nocase ignored without -regexp`` and matches
        case-SENSITIVELY (``-nocase -quiet *dly*`` -> 0 cells, ``*DLY*`` -> 4).
        So a block that passes GLOBS is evaluated as globs, case-sensitively,
        however it spelled its flags.
      * a ``-regexp`` pattern is anchored to the WHOLE cell name
        (``dly`` -> 0 cells, ``.*dly.*`` -> 4), hence ``fullmatch``.

    2026-08-05: this used to `re.fullmatch` unconditionally. Measured against
    e3aa9b126 -- the tree before the fix these tests exist for -- that made 3 of
    this file's 5 pre-fix failures come out as `re.error: nothing to repeat`,
    because that tree emits globs and a glob is not a regex. The tests did
    discriminate the landing, but by crashing in Python's regex parser instead of
    saying which delay cell the emitted set fails to reach. A pattern that is
    invalid under its own declared mode now reaches NOTHING, which is the
    truthful answer and the one that makes the assertion readable.
    """
    regexp, nocase = _mode()

    def hit(pat):
        if regexp:
            try:
                return bool(re.fullmatch(pat, cell,
                                         re.IGNORECASE if nocase else 0))
            except re.error:
                return False        # OpenSTA would reject it too
        return fnmatch.fnmatchcase(cell, pat)

    return any(hit(p) for p in _patterns())


# Cell names below are FAMILY examples, not any one PDK's catalogue: the
# double-underscore spelling is the open-PDK `<lib>__<fn>` convention, the bare
# spelling is the convention every commercial library the flow has met uses.
_MUST_EXCLUDE = [
    "sky130_fd_sc_hd__dlygate4sd3_1",     # open-PDK spelling, signal delay
    "gf180mcu_fd_sc_mcu7t5v0__dlyd_1",    # open-PDK spelling, signal delay
    "sky130_fd_sc_hd__clkdlybuf4s15_1",   # open-PDK spelling, clock delay
    "sky130_fd_sc_hd__lpflow_bleeder_1",  # open-PDK spelling, lpflow
    "sky130_fd_sc_hd__probe_p_8",         # open-PDK spelling, characterization
    "DLY1D1", "DLY4D1", "dly2d1",         # BARE spelling, signal delay
    "DELAY2X",                            # BARE spelling, spelled out
    "CLKDLYBUFX4",                        # BARE spelling, clock delay
]
_MUST_KEEP = [
    "sky130_fd_sc_hd__buf_1", "sky130_fd_sc_hd__clkbuf_16",
    "BUFD1", "BUFD20", "CLKBUFD1", "CLKBUFD20", "CDMBUFD4",
    "INVD1", "NAND2D1", "DFCNQD1",
]


def test_signal_delay_family_is_excluded():
    # The CONTRACT is which cells get excluded, not which literal glob is
    # printed. Asserting the literal is what let the block ship a pattern set
    # that matched ZERO cells on a commercial library while printing success.
    for cell in _MUST_EXCLUDE:
        assert _matches(cell), f"delay/characterization cell not excluded: {cell}"


def test_delay_exclusion_is_naming_convention_agnostic():
    # The defect-present test: with the older patterns (all anchored on the
    # open-PDK `<lib>__<fn>` double underscore) every BARE-named delay cell
    # below matched nothing, so the family stayed in the resizer's pool while
    # the run printed DONT_USE_FALLBACK_APPLIED: 0.
    for cell in ("DLY1D1", "DLY2D1", "DLY3D1", "DLY4D1", "DELAY1X",
                 "CLKDLYBUFX2"):
        assert _matches(cell), (
            f"{cell} is a delay cell spelled the way a commercial library "
            "spells it; a pattern set anchored on '__' misses it entirely")


def test_delay_exclusion_is_liberty_scoped_and_nonfatal():
    tcl = _fallback()
    # applied over whatever liberty was actually read (empty-match PDKs skip),
    # via set_dont_use, guarded -- never a hard failure on a PDK without them.
    # -regexp is MANDATORY, not stylistic: without it OpenSTA ignores -nocase
    # (`[WARNING STA-0358]`) and the guard excludes nothing while still
    # printing DONT_USE_FALLBACK_APPLIED. Measured, not assumed.
    assert "get_lib_cells -regexp -nocase -quiet $_du_pat" in tcl
    assert "set_dont_use" in tcl
    assert "DONT_USE_FALLBACK_NONFATAL" in tcl


def test_normal_buffers_are_NOT_excluded():
    # negative control: the fix must not disable the resizer's real buffers.
    # Widening the patterns to reach bare names must not start swallowing the
    # ordinary buffer / clock-buffer / logic families.
    for cell in _MUST_KEEP:
        assert not _matches(cell), f"ordinary cell wrongly excluded: {cell}"


def test_exclusion_never_empties_the_buffer_pool():
    # Second guard: even a correct pattern set can, on some library, match
    # every buffer there is. The block counts the cells OpenSTA ITSELF calls
    # buffers before and after, and reverts rather than leave the resizer and
    # CTS with nothing to insert -- out loud, never silently.
    tcl = _fallback()
    assert "get_property $_c is_buffer" in tcl
    assert "unset_dont_use" in tcl
    assert "DONT_USE_FALLBACK_REVERTED" in tcl
    assert tcl.index("_du_before") < tcl.index("unset_dont_use")


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
    marker = "foreach _du_pat"
    assert marker in tcl
    assert "buffer_ports -inputs" in tcl
    assert tcl.index(marker) < tcl.index("buffer_ports -inputs")


def test_delay_exclusion_carries_no_chip_literal():
    # chip-AGNOSTIC: the exclusion keys on the std-cell FUNCTION family, never on
    # a PDK / vendor / SKU / design literal.
    tcl = _fallback().lower()
    for banned in ("gf180", "sky130", "spm", "mcu7t5v0", "dlyd_1"):
        assert banned not in tcl
