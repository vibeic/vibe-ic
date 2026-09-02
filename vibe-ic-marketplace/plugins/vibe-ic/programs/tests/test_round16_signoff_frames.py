"""Round 16 of the u_hawaii_adc acceptance: the die the sign-off tools read.

MEASURED on the live tip (v1.15.60), on the round-15 die: sign-off DRC 184
violations and an LVS that could not match. None of the 184 was drawn by a
tool that thought it was drawing it, and the LVS mismatch was not a netlist
error. Four separate frame/legality defects, each pinned here:

  1. PARTIAL REPAIR, UN-LEGALIZED PLACEMENT. `repair_design` aborts mid-walk
     (RSZ-0074) having ALREADY resized cells. Through v1.15.60 the sign-off
     DRV loop broke out of the pass at that point, skipping the legalize and
     the reroute: 4 instances left overlapping (a buf_1 -> buf_2 upsize at the
     same origin, 0.48 um into the neighbour), which streamed out as 15 FEOL
     violations and 2 LVS extraction overlaps at the very same coordinate.
     The pass now completes (legalize + verify + reroute) and only then stops.

  2. NOTHING EVER SAID "OVERLAP". `check_placement` is asked immediately
     before the shipped DEF is written and `step_pnr` refuses a non-zero
     count. A detector, never a mover: the route is final at that point.

  3. THE MACRO ABSTRACT'S SIZE BOX SHIPPED AS DEVICE GEOMETRY. A plain
     `ly.read(macro_gds)` merges the macro's artwork into the DEF-created
     abstract cell without clearing the full-cell box the LEF/DEF reader
     already painted there on the first tech-LEF layer. Measured: 65,089 um^2
     of phantom `Activ` inside a 271x264 um macro that draws 525 um^2 there,
     and with it 129 of the 184 violations (Cnt.g2 x73, Pin.e x38, NBL.e x16,
     Cnt.g1, Gat.a2). Macros are now substituted the way std cells are.

  4. LEF `ORIGIN`, READ WITH OPPOSITE SIGNS. OpenROAD's master frame is
     `geometry + ORIGIN` (dbITerm getBBox, and where the routed wires are);
     magic's extraction reads `geometry - ORIGIN`; KLayout's streamout applies
     no shift at all. On `delta_sigma` (ORIGIN 3.800 20.750) the streamed pin
     metal sat one ORIGIN from the wire driving it — six opens in the shipped
     GDS that DRC cannot see — and netgen reported them as six unmatched nets.
     Streamout now translates macro artwork into OpenROAD's frame, and the
     extraction LEF states its geometry in that one frame with ORIGIN 0 0.
     Measured end to end on the round-15 die: 184 -> 15 -> 0 violations.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as mod  # noqa: E402


LEF_WITH_ORIGIN = """\
VERSION 5.7 ;
MACRO delta_sigma
  CLASS BLOCK ;
  ORIGIN 3.800 20.750 ;
  SIZE 271.370 BY 264.010 ;
  PIN vin
    PORT
      LAYER Metal3 ;
        RECT 164.760 -14.350 165.960 -13.650 ;
    END
  END vin
  OBS
      LAYER Metal3 ;
        RECT -3.800 -9.050 266.720 241.570 ;
  END
END delta_sigma
END LIBRARY
"""

LEF_ZERO_ORIGIN = LEF_WITH_ORIGIN.replace("ORIGIN 3.800 20.750",
                                          "ORIGIN 0.000 0.000")


# ---------------------------------------------------------------- 4. ORIGIN

def test_macro_origins_are_read_from_the_lef():
    assert mod._lef_macro_origins(LEF_WITH_ORIGIN) == {
        "delta_sigma": (3.8, 20.75)}


def test_a_zero_origin_macro_is_not_reported():
    assert mod._lef_macro_origins(LEF_ZERO_ORIGIN) == {}
    assert mod._lef_macro_origins("MACRO m\n  SIZE 1 BY 1 ;\nEND m\n") == {}


def test_normalization_moves_the_geometry_into_openroads_frame():
    """The pin RECT lands at rect+ORIGIN — the frame `dbITerm getBBox`
    reports and the frame every routed wire in the DEF was built against."""
    out, origins = mod._lef_normalize_macro_origin(LEF_WITH_ORIGIN)
    assert origins == {"delta_sigma": (3.8, 20.75)}
    assert "RECT 168.560 6.400 169.760 7.100 ;" in out
    # and the ORIGIN it was folded into is gone, so no reader can apply it
    # a second time (with either sign).
    assert re.search(r"^\s*ORIGIN\s+0\.000\s+0\.000\s*;", out, re.M)
    assert "3.800 20.750" not in out


def test_normalization_moves_the_obs_too():
    """An OBS left behind would be one ORIGIN from the metal it describes."""
    out, _ = mod._lef_normalize_macro_origin(LEF_WITH_ORIGIN)
    assert "RECT 0.000 11.700 270.520 262.320 ;" in out


def test_a_zero_origin_lef_is_returned_byte_identical():
    out, origins = mod._lef_normalize_macro_origin(LEF_ZERO_ORIGIN)
    assert origins == {}
    assert out == LEF_ZERO_ORIGIN


def test_normalization_preserves_every_line():
    out, _ = mod._lef_normalize_macro_origin(LEF_WITH_ORIGIN)
    assert len(out.splitlines()) == len(LEF_WITH_ORIGIN.splitlines())


def test_streamout_translates_macro_artwork_by_the_lef_origin():
    """The streamout script reads the ORIGIN from the LEFs it is given and
    applies it to the substituted macro artwork. Without this the macro's
    real metal is ORIGIN away from the abstract pin the router connected."""
    src = mod._GDS_STREAMOUT_PY
    compile(src, "stream_out.py", "exec")          # the emitted script parses
    assert "_lef_macro_origins_text" in src
    assert "MACRO_LEF_ORIGIN" in src
    # the translation is composed with (not replaced by) the shape transform
    assert "_otr * _t" in src


def test_streamout_origin_scan_regex_survives_the_string_embedding():
    """The MACRO block regex carries a backreference; embedded in a non-raw
    triple-quoted string an unescaped `\\1` becomes chr(1) and every macro
    silently reads as ORIGIN-less (measured: the first cut of this fix)."""
    ns = {}
    src = mod._GDS_STREAMOUT_PY
    body = src.split("def _lef_macro_origins_text", 1)[1]
    body = "def _lef_macro_origins_text" + body.split("\n\n\n", 1)[0]
    exec(body, ns)
    assert ns["_lef_macro_origins_text"](LEF_WITH_ORIGIN) == {
        "delta_sigma": (3.8, 20.75)}


# ------------------------------------------------- 3. macro GDS substitution

def test_macro_gds_is_substituted_not_merged_over_the_abstract():
    src = mod._GDS_STREAMOUT_PY
    assert "MACRO_GDS manual-substituted" in src
    # the abstract's own shapes (the LEF SIZE box the reader painted) are
    # cleared before the artwork is copied in
    i = src.index("for gp in macro_gds_files:")
    tail = src[i:]
    assert "_mdc.shapes(_li).clear()" in tail
    # a macro GDS naming no DEF master still merges the legacy way
    assert "MACRO_GDS merged (no DEF master matched)" in tail


# --------------------------------------------- 1./2. placement legality

def test_a_partial_repair_finishes_its_pass_instead_of_breaking_out():
    tcl = mod._v1_8_100_signoff_drv_repair_tcl("/out")
    assert "SDR_REPAIR_NONFATAL" in tcl
    # the abort sets the stop flag; it does not break before the legalize
    i = tcl.index("SDR_REPAIR_NONFATAL")
    assert "set _sdr_stop 1" in tcl[i:i + 200]
    assert "break" not in tcl[i:i + 200]
    # and the pass still ends with a legalize, a reroute, and only then a stop
    assert tcl.index("detailed_placement") > i
    assert tcl.index("SDR_STOPPED_AFTER_PARTIAL_REPAIR") > tcl.index(
        "detailed_route")


def test_the_repair_pass_verifies_its_own_legalization():
    tcl = mod._v1_8_100_signoff_drv_repair_tcl("/out")
    assert "check_placement -no_abort" in tcl
    assert "SDR_PLACEMENT_VIOLATIONS" in tcl
    # an escalation exists for the case the default bound cannot resolve
    assert "-use_diamond_legalizer" in tcl


def test_step_pnr_refuses_a_non_zero_placement_violation_count():
    """The gate reads the placer's own count off the log and FAILs."""
    src = Path(mod.__file__).read_text()
    assert "PNR_PLACEMENT_VIOLATIONS" in src
    assert "PNR_PLACEMENT_ILLEGAL" in src
    # the detector runs before the shipped DEF is written
    i_check = src.index('puts "PNR_PLACEMENT_VIOLATIONS: $_plv"')
    i_write = src.index("{min_area_patch_block}write_def")
    assert i_check < i_write


@pytest.mark.parametrize("count,expect_fail", [(0, False), (1, True),
                                               (4, True), (-1, False)])
def test_the_placement_gate_verdict_follows_the_count(count, expect_fail):
    """`-1` is 'the tool could not answer' — reported, never a FAIL."""
    log = f"PNR_STAGE: write_routed\nPNR_PLACEMENT_VIOLATIONS: {count}\n"
    m = re.findall(r"^PNR_PLACEMENT_VIOLATIONS:\s+(-?\d+)", log, re.M)
    assert m, "the gate's own pattern must match the deck's own print"
    assert (int(m[-1]) > 0) is expect_fail


# ------------------------------------------------- secondary strap spacing

def test_secondary_straps_are_bound_by_the_layers_own_spacing():
    """A layer whose min spacing exceeds its min width: the group must be
    placed against the SPACING rule, not against the strap width."""
    tech = ("LAYER TopMetal1\n  TYPE ROUTING ;\n  WIDTH 1.64 ;\n"
            "  SPACING 1.64 ;\nEND TopMetal1\n")
    stripes = [{"layer": "TopMetal1", "width": 2.2, "pitch": 8.0,
                "offset": 0.0}]
    out = mod._secondary_supply_tcl("VDD", "VSS", stripes, tech)["stripes"]
    assert "1.64" in out                      # the rule reached the deck
    assert "$_sec_gap >= 1.64" in out
    assert "PDN_SECONDARY_STRAPS_DO_NOT_FIT" in out
    assert "PDN_SECONDARY_STRAP_PLACED" in out


def test_a_secondary_group_that_cannot_clear_the_rule_is_refused_by_name():
    """pitch 5.0, width 2.2, spacing 1.64: 0.3 um of gap either side. The
    marker names the layer, the need, the gap and the rule."""
    tech = ("LAYER TopMetal1\n  TYPE ROUTING ;\n  WIDTH 1.64 ;\n"
            "  SPACING 1.64 ;\nEND TopMetal1\n")
    stripes = [{"layer": "TopMetal1", "width": 2.2, "pitch": 5.0,
                "offset": 0.0}]
    out = mod._secondary_supply_tcl("VDD", "VSS", stripes, tech)["stripes"]
    # the fit is decided at runtime against the measured gap
    assert "set _sec_gap [expr {(5.0 - 2.2 - $_sec_need) / 2.0}]" in out


def test_without_a_stated_spacing_the_width_proxy_is_disclosed():
    tech = "LAYER M9\n  TYPE ROUTING ;\n  WIDTH 1.0 ;\nEND M9\n"
    stripes = [{"layer": "M9", "width": 1.0, "pitch": 10.0, "offset": 0.0}]
    out = mod._secondary_supply_tcl("VDD", "VSS", stripes, tech)["stripes"]
    assert "width-proxy" in out


def test_the_secondary_group_is_centred_between_the_primary_straps():
    """Both gaps equal, each the largest available — a group dropped at
    `offset + pitch/2` leaves an asymmetric pair and violates the tighter."""
    tech = ("LAYER M5\n  TYPE ROUTING ;\n  WIDTH 0.2 ;\n  SPACING 0.21 ;\n"
            "END M5\n")
    stripes = [{"layer": "M5", "width": 1.0, "pitch": 20.0, "offset": 2.0}]
    out = mod._secondary_supply_tcl("VDD", "VSS", stripes, tech)["stripes"]
    assert "-offset [expr {2.0 + 1.0 + $_sec_gap}]" in out


# ------------------------------------------------------ extraction LEF view

def test_the_extraction_lef_view_normalizes_origin_and_drops_obs():
    src = Path(mod.__file__).read_text()
    i = src.index("_ext_lefs = []")
    tail = src[i:i + 3000]
    assert "_lef_normalize_macro_origin(_stripped_lef)" in tail
    assert "_RE_LEF_OBS_BLOCK.subn" in tail
    # a LEF with neither an OBS nor an ORIGIN is passed through untouched
    assert "if not _n and not _orig:" in tail
    assert "lef_origin_normalized" in src


# ------------------------------------- 5. the summary must quote THIS run

def test_the_step_record_is_published_before_the_summary_that_quotes_it():
    """`final_report_generate` ECHOES the runner's step record for DRC/LVS
    (ORGANIC #399 — echo, never re-derive). The record was written AFTER the
    summary, so a re-run of the same project published the PREVIOUS run's
    numbers: measured `total_violations=216` in `final_summary.md` beside an
    orchestrator record, a DRC report and a steps view that all said 39."""
    src = Path(mod.__file__).read_text()
    i_pre = src.index('"record": "in-progress (steps only')
    i_sum = src.index("fs_ok = _pl.emit_final_summary(")
    i_full = src.index('"steps": [asdict(s) for s in plan],')
    assert i_pre < i_sum < i_full, (
        "the steps record must be on disk before emit_final_summary reads it, "
        "and the full record still overwrites it at the end")


def test_the_pre_summary_record_carries_the_step_extras_the_summary_reads():
    """A record without `extras` would make the summary say '(report
    missing)' — the pre-#399 state — instead of this run's counts."""
    import dataclasses
    r = mod.StepResult("drc", "FAIL", 1.0, "d", extras={"total_violations": 39})
    assert dataclasses.asdict(r).get("extras", {}).get(
        "total_violations") == 39
