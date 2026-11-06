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



# ---------------------------------------------------------------- 4. ORIGIN

















# ------------------------------------------------- 3. macro GDS substitution



# --------------------------------------------- 1./2. placement legality





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
    import inspect
    src = inspect.getsource(mod.main)
    i_pre = src.index("_publish_in_progress_steps(project, plan)")
    i_sum = src.index("fs_ok = _pl.emit_final_summary(")
    i_full = src.index('"steps": [asdict(s) for s in plan],')
    assert i_pre < i_sum < i_full, (
        "the steps record must be on disk before emit_final_summary reads it, "
        "and the full record still overwrites it at the end")




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
    import inspect
    seg = inspect.getsource(a1s.step_for_block)
    assert "analog_hardmacro_pinname_consistency_check.py" in seg
    assert "[A8 advisory] interface consistency" in seg
    # advisory: the subprocess result never becomes the step's verdict
    j = seg.index("analog_hardmacro_pinname_consistency_check.py")
    next_section = seg.find("# A8 is also the moment", j)
    assert next_section > j
    assert "returncode" not in seg[j:next_section]
