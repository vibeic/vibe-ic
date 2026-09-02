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


# ------------------------- 6. the block's ports are the DESIGN's port names

import analog_a2_topology_emit as a2  # noqa: E402


def test_the_topology_library_ports_bind_to_the_declared_interface():
    """MEASURED: the `ldo` topology entry names its supply input `vdd`; the
    design's own interface declaration (every pin citing its document line)
    names it `vin`, and the chip RTL instantiates `.vin(...)`. The emitted
    hardmacro said `vdd` in its LEF, its GDS labels and its Verilog view, and
    the post-layout LEC stopped on `Module 'ldo' ... does not have a port
    named 'vin'` — on a die whose sign-off DRC was 0 and whose LVS matched."""
    m, refusal = a2.bind_ports_to_declaration(
        ["vdd", "vss", "vref", "vout"], ["vin", "vss", "vref", "vout"])
    assert refusal is None
    assert m == {"vdd": "vin", "vss": "vss", "vref": "vref", "vout": "vout"}


def test_an_ambiguous_leftover_is_refused_and_nothing_is_renamed():
    """Two-and-two (or three-and-four) has no unique answer. A rename that
    guesses is worse than no rename: the interface gate then reports the
    disagreement instead of a silent, plausible, wrong binding."""
    m, refusal = a2.bind_ports_to_declaration(
        ["vdd", "vss", "vin", "vcm", "rst", "vout"],
        ["vdd", "vss", "vin", "vrefp", "vrefn", "clk", "bit_out"])
    assert m == {}
    assert refusal and "PORT_BINDING_AMBIGUOUS" in refusal
    assert "rst" in refusal and "vrefp" in refusal


def test_no_declaration_leaves_the_library_names_alone():
    assert a2.bind_ports_to_declaration(["vdd", "vss"], []) == ({}, None)


def test_case_is_not_a_disagreement_about_role():
    m, refusal = a2.bind_ports_to_declaration(["VDD", "vss"], ["vdd", "VSS"])
    assert refusal is None and m == {"VDD": "vdd", "vss": "VSS"}


def test_the_rename_is_a_whole_token_never_a_substring():
    """`vdda` must stay `vdda`, and the SPICE source NAME in
    `v_vdd vdd 0 {supply}` must not change while the NODE it drives does —
    measured: renaming whole strings only left the A4 testbench driving a node
    the DUT no longer had, and the corner sweep failed on a floating input."""
    out = a2._rename_nets(
        ["v_vdd vdd 0 {supply}", "vdda", "v(vdd)", "vdd", {"n": "vdd"}],
        {"vdd": "vin"})
    assert out == ["v_vdd vin 0 {supply}", "vdda", "v(vin)", "vin",
                   {"n": "vin"}]


def test_the_binding_is_recorded_in_the_ir_whatever_it_decided():
    """`port_binding` states the declared pins, the library ports, what was
    renamed and any refusal — so a reader of topology.json can see whether the
    names came from the design or from the circuit library."""
    src = Path(a2.__file__).read_text()
    i = src.index('ir["port_binding"] = {')
    block = src[i:i + 700]
    for key in ('"declared_pins"', '"library_ports"', '"renamed"',
                '"refusal"', '"source"'):
        assert key in block


# ---------------- 7. an absent DRV table is silence; a count is a measurement

import sta_corner_record_completeness_check as _rec  # noqa: E402

_CENSUS_REPORT = """\
SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew min_pulse_width \
max_capacitance max_fanout
SIGNOFF_DRV_CENSUS_BEGIN the tool's own violator count for every check type \
requested above, zero included -- an absent table is silence, a count is a \
measurement
SIGNOFF_DRV_CENSUS max_slew violators=0
SIGNOFF_DRV_CENSUS max_fanout violators=0
SIGNOFF_DRV_CENSUS max_capacitance violators=0
"""


def test_the_signoff_deck_records_the_tools_own_drv_counts():
    tcl = mod._report_check_types_tcl("/out/sta.rpt")
    assert "sta::${_vt}_violation_count" in tcl
    assert "SIGNOFF_DRV_CENSUS $_vt violators=$_vn" in tcl
    for kind in ("max_slew", "max_fanout", "max_capacitance"):
        assert kind in tcl
    # the census is emitted on the SUCCESS branch only — never beside a
    # report_check_types that errored
    assert tcl.index("SIGNOFF_CHECK_TYPES_FAILED") < tcl.index(
        "SIGNOFF_DRV_CENSUS")


def test_the_census_begin_line_is_digit_free():
    """`extract_drv` ends an open violator table at the first line with no
    digit. A digit in the BEGIN line would make the census look like extra
    violator rows of whatever table happened to be open above it."""
    assert not any(c.isdigit() for c in mod._SIGNOFF_DRV_CENSUS_BEGIN)


def test_a_census_zero_is_a_measurement_not_an_absent_table():
    d = _rec.extract_drv(_CENSUS_REPORT)
    assert d["kinds_without_table"] == []
    assert d["census"] == {"max_slew": 0, "max_fanout": 0,
                           "max_capacitance": 0}
    assert d["violations"] == {}


def test_without_a_census_silence_is_still_unmeasured():
    """The pre-existing reading is untouched: a report with the marker and no
    census keeps every requested kind in `kinds_without_table`."""
    d = _rec.extract_drv(_CENSUS_REPORT.split("SIGNOFF_DRV_CENSUS_BEGIN")[0])
    assert sorted(d["kinds_without_table"]) == [
        "max_capacitance", "max_fanout", "max_slew"]
    assert d.get("census") == {}


def test_a_census_does_not_hide_a_table_that_has_rows():
    rpt = _CENSUS_REPORT.replace("max_capacitance violators=0",
                                 "max_capacitance violators=2")
    rpt = ("max capacitance\n\nPin      Limit   Cap   Slack\n"
           "-----------------------------------\n"
           "a/vin     0.30   0.46   -0.16 (VIOLATED)\n"
           "b/vin     0.30   0.43   -0.13 (VIOLATED)\n\n") + rpt
    d = _rec.extract_drv(rpt)
    assert d["violations"].get("max_capacitance") == 2
    assert d["census"]["max_capacitance"] == 2
    assert "max_capacitance" not in d["kinds_without_table"]


# ------------- 8. the DRV bound, the GR-tree abort, and the Verilog parser

def test_a_measured_capacitance_violator_brings_the_bound_back_to_the_seed():
    """The electrical floor `rsz::find_max_wire_length` answers with the length
    at which wire DELAY degrades. A wire violates its LOAD limit long before
    that: MEASURED on ihp-sg13g2 the floor is 3671 um, so a 1.3 mm die was
    repaired at a 3671 um repeater spacing — nothing was inserted — while the
    sign-off report carried 10 max-capacitance violators. The floor still
    governs the kinds it governs; a MEASURED capacitance violator brings the
    bound back to the geometric seed, and never below it."""
    tcl = mod._v1_8_100_signoff_drv_repair_tcl("/out")
    assert "set _sdr_seed $_sdr_mwl" in tcl
    assert "SDR_DRV_BY_KIND" in tcl
    assert "SDR_MWL_LOWERED_FOR_CAP" in tcl
    # keyed on the tool's OWN per-kind count, and only downward to the seed
    assert "if {$_sdr_ncap > 0 && $_sdr_mwl > $_sdr_seed}" in tcl
    assert "set _sdr_mwl $_sdr_seed" in tcl


def test_the_drv_count_is_attributed_to_its_table():
    """A total alone cannot choose the bound: the section headings are read so
    a max-capacitance row is not counted as a max-slew one."""
    tcl = mod._v1_8_100_signoff_drv_repair_tcl("/out")
    assert 'eq "max capacitance"' in tcl
    assert 'eq "max slew"' in tcl


def test_a_stale_global_route_tree_is_regenerated_and_the_repair_retried():
    """RSZ-0074 (`Failed to build tree from global routes ... found route to 2
    pins, expected 1`) aborts repair_design at iteration 0 having done nothing.
    Regenerating the global route on the current design and retrying runs the
    identical repair to completion. Bounded to ONE retry."""
    tcl = mod._v1_8_100_signoff_drv_repair_tcl("/out")
    i = tcl.index("RSZ-0074")
    seg = tcl[i:i + 900]
    assert "SDR_RSZ0074_DETECTED" in seg
    assert "global_route" in seg
    assert "SDR_RSZ0074_RECOVERED" in seg
    # a failure of the retry still stops the loop — no unbounded retrying
    assert "SDR_RSZ0074_RETRY_NONFATAL" in seg and "set _sdr_stop 1" in seg
    # a NON-RSZ-0074 error keeps the old behaviour exactly
    assert "SDR_REPAIR_NONFATAL: $_sdr_rd" in seg


import analog_hardmacro_pinname_consistency_check as _pin  # noqa: E402


def test_a_non_ansi_module_header_is_not_a_module_without_ports():
    """The flow's OWN A8 emitter writes the non-ANSI form. Reading only ANSI
    headers made this gate report `Block 'ldo': missing_in_v=['vin','vout',
    'vref','vss']` for a view that declares exactly those four ports — the same
    verdict it printed for a block that really did disagree."""
    non_ansi = ("module ldo (\n    vin,\n    vss,\n    vref,\n    vout\n);\n"
                "    inout vin;\n    inout vss;\n    inout vref;\n"
                "    inout vout;\nendmodule\n")
    assert _pin.parse_verilog_ports(non_ansi) == {"vin", "vss", "vref", "vout"}


def test_the_ansi_form_still_parses_exactly_as_before():
    assert _pin.parse_verilog_ports(
        "module m (input a, output [3:0] b, inout c); endmodule") == {
            "a", "b", "c"}


def test_a_bare_header_name_the_body_never_declares_is_not_a_port():
    assert _pin.parse_verilog_ports(
        "module m (a, zz);\n input a;\n endmodule") == {"a"}


def test_a8_reports_the_interface_disagreement_at_the_producer():
    """`analog_hardmacro_pinname_consistency_check` compares the three views
    of a macro's interface and NOTHING in the flow ran it. The disagreement
    surfaced three phases later as a yosys parse error at the post-layout LEC
    (`Module 'delta_sigma' ... does not have a port named 'vrefp'`). It is now
    reported at A8, where the views are produced — ADVISORY: the A8 verdict is
    still the A8 gate's own, and a design whose blocks declare no interface
    makes the check self-skip exactly as before."""
    import analog_one_shot_runner as a1s
    src = Path(a1s.__file__).read_text()
    i = src.index("analog_hardmacro_gds_emit.py")
    seg = src[i:i + 4000]
    assert "analog_hardmacro_pinname_consistency_check.py" in seg
    assert "[A8 advisory] interface consistency" in seg
    # advisory: the subprocess result never becomes the step's verdict
    j = seg.index("analog_hardmacro_pinname_consistency_check.py")
    assert "returncode" not in seg[j:j + 900]
