"""TAPEOUT-SIGNOFF (multi-corner ECO) — _build_eco_repair_tcl must read every
process corner the PDK provides as an OpenROAD timing corner so
`repair_timing -setup` optimizes the WORST (ss) process corner, not just tt.

Background (proven live on ibex, sky130A, 55k cells, 20 ns clock):
  * The routed run MET timing at the typical (tt) corner (+1.80 ns) but the
    multi-corner OCV sign-off STA surfaced a huge ss setup violation (−35.78 ns
    placement-RC). This is the "single-corner-closure confounder": tt passes,
    ss blows up because slews explode at the slow process corner.
  * The v1.2.85 DRV constraints (set_max_transition/set_max_capacitance) let
    repair_design fix the slew explosion — but a SINGLE-CORNER (tt) ECO then runs
    repair_timing -setup against tt (already MET) and never touches the ss setup
    violation. Driving the ECO MULTI-CORNER recovered 20.3 ns of ss slack
    (−35.78 → −15.49) that a tt-only ECO cannot reach.

§4.05: the multi-corner ECO RECOVERS what is recoverable; a genuine ss floor
still shows VIOLATED afterwards (ibex@20 ns remains a real floor — this feature
does not fabricate closure). This test pins the EMISSION contract only.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


def _mc(corner_libs):
    return R._build_eco_repair_tcl(
        top="chip_top",
        tech_lef_c="/pdk/tech.lef",
        cell_lef_c="/pdk/cells.lef",
        liberty_c="/pdk/tt.lib",
        pnr_dir_c="/proj/pnr",
        eco_dir_c="/proj/eco",
        metal_prefix="met",
        corner_libs=corner_libs,
    )


def test_multicorner_defines_all_process_corners():
    tcl = _mc({"SS": "/pdk/ss.lib", "TT": "/pdk/tt.lib", "FF": "/pdk/ff.lib"})
    # define_corners lists ss FIRST (worst-setup), deterministic ss->tt->ff.
    assert "define_corners ss tt ff" in tcl
    assert "read_liberty -corner ss /pdk/ss.lib" in tcl
    assert "read_liberty -corner tt /pdk/tt.lib" in tcl
    assert "read_liberty -corner ff /pdk/ff.lib" in tcl
    # The single-corner bare `read_liberty <path>` must NOT be emitted in MC mode.
    assert "read_liberty /pdk/tt.lib\n" not in tcl


def test_multicorner_repair_timing_setup_targets_worst_corner():
    # repair_timing -setup must still be present; with ss defined it targets ss.
    tcl = _mc({"SS": "/pdk/ss.lib", "FF": "/pdk/ff.lib"})
    assert "define_corners ss ff" in tcl
    assert "repair_timing -setup" in tcl
    # DRV-slew fix (repair_design) still runs in pass 1 before repair_timing.
    assert tcl.index("repair_design") < tcl.index("repair_timing -setup")


def test_multicorner_retains_all_four_561_workarounds():
    tcl = _mc({"SS": "/pdk/ss.lib", "TT": "/pdk/tt.lib", "FF": "/pdk/ff.lib"})
    assert "post_hold.def" in tcl          # (a) RSZ-0074
    assert "setup-only" in tcl             # (b) Signal-11
    assert "PG_CLEANUP" in tcl             # (c) DRT-0305
    # (d) DPL-0033 — still non-aborting, but the count is now REPORTED
    # rather than caught and printed as a warning nothing reads.
    assert "check_placement -no_abort" in tcl


def test_single_corner_is_byte_identical_regression():
    # None / empty / single-corner must degrade to the pre-multi-corner
    # single `read_liberty <liberty_c>` emission (byte-identical).
    base = _mc(None)
    assert base == _mc({})
    assert base == _mc({"TT": "/pdk/tt.lib"})  # a single corner is NOT multi
    assert "read_liberty /pdk/tt.lib\n" in base
    assert "define_corners" not in base


def test_two_corners_is_enough_to_trigger_multicorner():
    # ss + tt (no ff) is a valid 2-corner setup sign-off matrix.
    tcl = _mc({"SS": "/pdk/ss.lib", "TT": "/pdk/tt.lib"})
    assert "define_corners ss tt" in tcl
    assert "read_liberty -corner ss /pdk/ss.lib" in tcl


def test_noncanonical_extra_corner_appended_sorted():
    # An extra non-SS/TT/FF label is appended AFTER the canonical order, sorted.
    tcl = _mc({"SS": "/pdk/ss.lib", "TT": "/pdk/tt.lib", "SF": "/pdk/sf.lib"})
    line = next(l for l in tcl.splitlines() if l.startswith("define_corners"))
    assert line == "define_corners ss tt sf"


def test_primary_read_def_no_link_design_command():
    # The ECO reads post_hold.def as the PRIMARY source (netlist+placement+rows+
    # tracks) — no read_verilog/link_design command (they leave the block with no
    # floorplan → ODB-0251, then DPL-0027/GRT-0701 on reroute). read_def must NOT
    # be -incremental (that does not carry rows/tracks).
    tcl = _mc({"SS": "/pdk/ss.lib", "TT": "/pdk/tt.lib"})
    cmds = [ln.strip() for ln in tcl.splitlines()
            if ln and not ln.lstrip().startswith("#")]
    assert not any(c.startswith("link_design") for c in cmds)
    assert not any(c.startswith("read_verilog") for c in cmds)
    assert any(c.startswith("read_def ") and c.endswith("post_hold.def")
               for c in cmds)
    assert "read_def -incremental" not in tcl


def test_write_sdf_corner_flag_multicorner_only():
    # write_sdf needs -corner under multi-scene analysis (STA-0103) — emit at the
    # nominal (tt) corner when multi-corner; single-corner stays byte-identical.
    mc = _mc({"SS": "/pdk/ss.lib", "TT": "/pdk/tt.lib", "FF": "/pdk/ff.lib"})
    assert "write_sdf -corner tt " in mc
    mc_no_tt = _mc({"SS": "/pdk/ss.lib", "FF": "/pdk/ff.lib"})
    assert "write_sdf -corner ss " in mc_no_tt  # first corner when no tt
    sc = _mc(None)
    assert "write_sdf -corner" not in sc  # single-corner: no flag
    assert "write_sdf /proj/eco/chip_top_eco.sdf" in sc


def test_emitted_tcl_is_brace_balanced_all_modes():
    # Structural pin (tclsh-independent): every emission must have balanced
    # braces (the write_sdf -corner split must not leak a stray brace).
    def _balanced(s):
        depth = 0
        for ch in s:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth < 0:
                    return False
        return depth == 0
    for cl in (None, {"TT": "/t.lib"}, {"SS": "/s.lib", "TT": "/t.lib"},
               {"SS": "/s.lib", "TT": "/t.lib", "FF": "/f.lib"}):
        assert _balanced(_mc(cl)), f"unbalanced braces for corner_libs={cl}"
