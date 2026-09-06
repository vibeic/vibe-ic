#!/usr/bin/env python3
"""spm's last three walls on gf180mcuD: the antenna loop, the undeclared
database unit, and a correlation gate that was measuring the PDK.

MEASURED (host 8HD-6, image `ghcr.io/vibeic/vibeic-eda@sha256:06537f7e…`, own
label 0.3.46, OpenROAD 26Q3-2061-ga7aee7bc76; plugin base `2074e709` =
v1.17.58, i.e. carrying czspmdrc's v1.17.52).

1. THE ANTENNA LOOP ENDED ON ITS LAST ITERATION, NOT ITS BEST.
   The run's own `openroad.log` (two antenna windows, both at the 6-iteration
   cap):

       window 1   22 -> 7 -> 6 -> 5 -> 4 -> 2 -> 2     never reached 0
       window 2    2 ->  2 ->  2 ->  2 -> 3 -> 2 -> 3  ended on 3

   Window 2 SAW 2 five times and shipped 3. It printed `ANTENNA_POSTROUTE_DONE`
   and nothing else: no sequence, no "best", no statement that a count which
   repeats without a trend is not a fixed point. `_emit_antenna_report` then
   read `nets[-1]` — the LAST pair in the log — so the report said 3 and the
   reader had no way to learn that the loop had held 2 and let go of it.

   AND THE RESTORE IS NOT AVAILABLE ON THIS TOOL. Both directions, same image,
   same routed DEF, one line different:
       with    `odb::dbChip_destroy` + `read_db <snapshot>`:
               check_antennas 3 (correct), then `report_worst_slack -max`
               dies `[CRITICAL ORD-2008] unknown master term type`
       without the restore (the control): `report_worst_slack -max` -> 12.26,
               `write_def` OK, session finishes.
   So a mid-session rollback silently destroys the STA network the rest of the
   PnR session runs on. The loop therefore STOPS at its best by MEMBERSHIP
   instead of walking past it, and says NOT_CONVERGED with the sequence.

2. `database_unit_um` WAS NEVER DECLARED BY ANYBODY, so `General.DatabaseUnit`
   reported NOT_DETERMINED and `tapeout_precheck` was the one sign-off gate of
   six that could never pass. And the obvious authority is the WRONG one:
       tech LEF  `DATABASE MICRONS 2000 ;`        -> 0.0005 um
       routed DEF`UNITS DISTANCE MICRONS 2000 ;`  -> 0.0005 um
       PDK cell GDS UNITS                         -> 0.001  um
       our streamed GDS UNITS                     -> 0.001  um
   Publishing the LEF's number would have turned a rung that never passed into
   one that always failed, on a stream that is exactly right.

3. THE SPICE CORRELATION GATE WAS MEASURING THE PDK. After czspmdrc took it
   from -71.1 % to -22.4 % the residual was proved corner-INDEPENDENT (ss
   1.873 / tt 1.845): it is this open PDK's liberty-NLDM vs ngspice-model
   characterisation gap. The tolerance is derived from local NLDM grid
   half-ranges — it models INTERPOLATION error and nothing else — so the gate
   could not pass on gf180mcuD however correct the design. The two error
   sources are now separated in the instrument and both printed.

4. `parse_spef_caps` COULD NOT READ HALF ITS OWN SPEF. 337 of the 673 `*D_NET`
   records in `spm.spef` carry an IEEE-1481 backslash escape in their
   `*NAME_MAP` name; the reader kept the backslash, so no caller holding the
   netlist's spelling could find them, and `resolve_path_stages` supplied
   `0.0` for 4 of the 12 critical-path stages.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import phase3_one_shot_runner as r  # noqa: E402
import spice_correlation_check as scc  # noqa: E402


# ─────────────────────────── 4. the SPEF reader ───────────────────────────

#: The exact shape `spm.spef` carries: a name-map whose names are escaped, and
#: `*D_NET` records that reference them by index.
_SPEF = """*SPEF "ieee 1481-1999"
*DESIGN "spm"
*C_UNIT 1 PF

*NAME_MAP
*44 net13
*422 __uuf__\\._178_
*177 __BoundaryScanRegister_input__0__\\.dout

*D_NET *44 0.00365001
*CONN
*END

*D_NET *422 0.0191052
*CONN
*END

*D_NET *177 0.0151856
*CONN
*END
"""


def test_spef_escaped_names_are_readable_by_their_netlist_spelling():
    caps = scc.parse_spef_caps(_SPEF)
    # The netlist spells these WITHOUT the SPEF escape. Every one must resolve.
    assert caps.get("net13") == pytest.approx(0.00365001)
    assert caps.get("__uuf__._178_") == pytest.approx(0.0191052)
    assert caps.get("__BoundaryScanRegister_input__0__.dout") == \
        pytest.approx(0.0151856)
    # …and the SPEF's own spelling still resolves, so a caller that already
    # held the escaped name is not broken by the fix.
    assert caps.get("__uuf__\\._178_") == pytest.approx(0.0191052)


def test_spef_unescape_is_only_about_the_backslash():
    assert scc.spef_unescape("__uuf__\\._178_") == "__uuf__._178_"
    assert scc.spef_unescape("plain_net") == "plain_net"
    assert scc.spef_unescape("bus\\[3\\]") == "bus[3]"


def test_a_net_the_spef_never_named_is_reported_not_defaulted():
    """`0.0` for an absent net and `0.0` for a net the SPEF says is 0 are
    different facts, and the deck cannot tell them apart once a default has
    been supplied."""
    sta_path = {
        "startpoint": "in_port", "endpoint": "ep", "endpoint_transition": "fall",
        "path_delay_ns": 1.0,
        "rows": [{"inst": "u1", "cell": "BUF", "pin": "u1/Y", "incr": 0.5,
                  "tr": "v", "slew_ns": 0.1, "cap_pf": 0.01}],
    }
    inst_map = {"u1": {"cell": "BUF", "conns": {"A": "in_port", "Y": "n_out"}}}
    got = scc.resolve_path_stages(sta_path, inst_map, {}, {"BUF"}, "", 12)
    assert got["stages"][0]["wire_cap_source"] == "ABSENT_FROM_SPEF"
    assert got["nets_absent_from_spef"] == ["n_out"]
    # …and with the cap present it is sourced, not guessed.
    got2 = scc.resolve_path_stages(sta_path, inst_map, {"n_out": 0.0},
                                   {"BUF"}, "", 12)
    assert got2["stages"][0]["wire_cap_source"] == "spef"
    assert got2["nets_absent_from_spef"] == []


# ──────────────── 3. the two error sources, separated ────────────────

_TABLE = {"index_1": [0.1, 0.5, 1.0],
          "index_2": [0.01, 0.05],
          "values": [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]}


def test_the_reference_point_is_a_characterised_grid_point():
    """Not an interpolation. At a grid point the NLDM carries a MEASURED
    number, so the comparison there has zero interpolation error and what is
    left is the characterisation gap alone."""
    got = scc.nldm_grid_point(_TABLE, 0.4, 0.04)
    assert (got["slew"], got["load"]) == (0.5, 0.05)
    assert got["value"] == 4.0
    assert got["value"] == _TABLE["values"][got["i"]][got["j"]]


def test_the_design_reference_carries_the_measured_pdk_ratio():
    stages = [{"cell": "A", "sta_delay_ns": 1.0},
              {"cell": "B", "sta_delay_ns": 2.0}]
    assert scc.characterised_reference_ns(stages, {"A": 0.9, "B": 0.8}) == \
        pytest.approx(1.0 * 0.9 + 2.0 * 0.8)


def test_a_partial_pdk_reference_is_refused_rather_than_half_applied():
    """A correction applied to some stages and not others is a number nobody
    can attribute. The caller must degrade to the uncorrected comparison and
    say so, which is what `None` forces."""
    stages = [{"cell": "A", "sta_delay_ns": 1.0},
              {"cell": "B", "sta_delay_ns": 2.0}]
    assert scc.characterised_reference_ns(stages, {"A": 0.9}) is None


def test_the_pdk_gap_cannot_absorb_a_design_defect():
    """THE ANTI-LAUNDERING CONTROL. The reference ratios are a property of the
    PDK; a design defect moves the SPICE sum and NOT the ratios, so it moves
    the judged number by exactly what it moved before.

    Numbers are spm's own: liberty cone 12.752 ns, SPICE 9.901 ns, tolerance
    17.263 %, and a measured PDK ratio of 0.9 (a -10 % characterisation gap).
    """
    expected_ns, tol = 12.752380952, 17.263443
    stages = [{"cell": "C", "sta_delay_ns": expected_ns}]
    ratios = {"C": 0.9}
    ref = scc.characterised_reference_ns(stages, ratios)

    # (i) the healthy design: the PDK gap is taken out and it correlates.
    healthy = (9.901463 - ref) / ref * 100.0
    assert scc.path_correlation_verdict(healthy, tol) == "CORRELATED"

    # (ii) fold the PDK gap back in — the ONE mutation this change must not
    # survive — and the same measurement is red again.
    folded = (9.901463 - expected_ns) / expected_ns * 100.0
    assert folded == pytest.approx(-22.355966, abs=1e-5)
    assert scc.path_correlation_verdict(folded, tol) != "CORRELATED"

    # (iii) a REAL design miss — the SPICE side 40 % slow, e.g. a wire load the
    # STA modelled and the deck did not — is still refused AFTER the change.
    miss = (9.901463 * 1.4 - ref) / ref * 100.0
    assert scc.path_correlation_verdict(miss, tol) != "CORRELATED"
    # …and so is a missing stage, which makes the SPICE side too fast.
    short = (9.901463 * 0.6 - ref) / ref * 100.0
    assert scc.path_correlation_verdict(short, tol) != "CORRELATED"


def test_the_tolerance_itself_did_not_move():
    """This is not a widening. `derive_liberty_path_tolerance` is untouched and
    `path_correlation_verdict` still classifies against exactly it."""
    assert scc.path_correlation_verdict(17.263442, 17.263443) == "CORRELATED"
    assert scc.path_correlation_verdict(17.263444, 17.263443) == "MISMATCH"
    assert scc.path_correlation_verdict(34.526887, 17.263443) == \
        "CRITICAL_MISMATCH"


# ─────────────────── 2. the database unit nobody declared ───────────────────

def test_the_three_units_are_read_from_the_files_that_state_them():
    assert r.lef_database_units_per_um(
        "UNITS\n    DATABASE MICRONS 2000  ;\n    CAPACITANCE PICOFARADS 1 ;\n"
    ) == 2000.0
    assert r.def_database_units_per_um("UNITS DISTANCE MICRONS 2000 ;") == 2000.0
    assert r.lef_manufacturing_grid_um("MANUFACTURINGGRID 0.0050 ;") == 0.005
    # NOT READ is None, never a default.
    assert r.lef_database_units_per_um("") is None
    assert r.def_database_units_per_um("UNITS DISTANCE MICRONS ;") is None


def test_the_stream_grid_is_the_authority_and_the_lef_is_not():
    """gf180mcuD's own readings. The LEF/DEF database (0.0005 um) and the GDS
    database (0.001 um) are two different databases on purpose."""
    got = r.database_unit_verdict(2000.0, 2000.0, 0.001, 0.005)
    assert got["verdict"] == "PASS"
    assert got["database_unit_um"] == 0.001
    assert got["lef_database_unit_um"] == 0.0005
    # Both numbers are in the record, so neither can be quoted alone.
    assert "0.0005" in got["reason"] and "0.001" in got["reason"]


def test_a_def_that_disagrees_with_its_lef_is_refused_naming_both():
    got = r.database_unit_verdict(2000.0, 1000.0, 0.001, 0.005)
    assert got["verdict"] == "FAIL"
    assert got["database_unit_um"] is None
    assert "2000" in got["reason"] and "1000" in got["reason"]


def test_a_database_that_cannot_spell_the_manufacturing_grid_is_refused():
    got = r.database_unit_verdict(2000.0, 2000.0, 0.003, 0.005)
    assert got["verdict"] == "FAIL"
    assert got["database_unit_um"] is None
    assert "0.005" in got["reason"] and "0.003" in got["reason"]


@pytest.mark.parametrize("lef,dfe,stream,missing", [
    (None, 2000.0, 0.001, "tech LEF DATABASE MICRONS"),
    (2000.0, None, 0.001, "DEF UNITS DISTANCE MICRONS"),
    (2000.0, 2000.0, None, "PDK cell GDS UNITS"),
])
def test_an_unread_input_publishes_nothing_and_names_itself(lef, dfe, stream,
                                                            missing):
    """"Could not read it" is not "read it and it was empty". The declaration
    keeps NOT_DETERMINED and the rung keeps reporting a non-pass."""
    got = r.database_unit_verdict(lef, dfe, stream, 0.005)
    assert got["verdict"] == "NOT_MEASURED"
    assert got["database_unit_um"] is None
    assert missing in got["not_read"]


def test_the_grid_check_is_skipped_not_faked_when_no_grid_is_declared():
    got = r.database_unit_verdict(2000.0, 2000.0, 0.001, None)
    assert got["verdict"] == "PASS"
    assert "declares no MANUFACTURINGGRID" in got["reason"]


# ───────────────────── 1. the antenna repair loop ─────────────────────

import shutil          # noqa: E402
import subprocess      # noqa: E402
import tempfile        # noqa: E402

_tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(_tclsh is None, reason="tclsh not installed")

#: Stubs standing in for the tool. `VIC_SEQ` scripts the VIOLATING-NET SET the
#: loop sees on each measurement — not a count, because the whole point is that
#: a count cannot tell two different sets apart.
_HARNESS = r"""
set ::SEQ $::env(VIC_SEQ)
set ::STEP 0
proc check_antennas {args} {
  set rf ""
  for {set i 0} {$i < [llength $args]} {incr i} {
    if {[lindex $args $i] eq "-report_file"} { set rf [lindex $args [expr {$i+1}]] }
  }
  set idx $::STEP
  if {$idx >= [llength $::SEQ]} { set idx [expr {[llength $::SEQ]-1}] }
  set nets [lindex $::SEQ $idx]
  if {$rf ne "" && $::env(VIC_NAME_NETS) eq "1"} {
    set fh [open $rf w]
    foreach n $nets { puts $fh "Net: $n" ; puts $fh "  Pin: x/I" }
    close $fh
  }
  return [llength $nets]
}
proc repair_antennas {args} { incr ::STEP ; return 0 }
proc detailed_route {args} { incr ::STEP ; return 0 }
namespace eval ord {
  proc get_db_block {} { return ::BLK }
  proc get_db {} { return ::DB }
}
proc ::BLK {sub args} {
  switch -- $sub {
    findNet - findInst { return "NULL" }
    getInsts - getRows { return {} }
    getDefUnits { return 2000 }
    default { return {} }
  }
}
set _spare_tie_nets {}
set _vic_drc_opt {}
"""


def _pdk_with_diode():
    return r.PdkConfig(
        name="fixture_pdk", liberty="/pdk/lib.lib", tech_lef="/pdk/tech.lef",
        cell_lef="/pdk/cells.lef", cell_gds=None, site="unithd",
        drc_deck=None, metal_prefix="met",
        antenna_diode_cell="fixture_diode_2")


def _drive(seq: str, name_nets: bool = True) -> str:
    """Run the EMITTED antenna Tcl under stubs and return its stdout."""
    with tempfile.TemporaryDirectory() as td:
        script = Path(td) / "ant.tcl"
        script.write_text(_HARNESS + r._antenna_repair_tcl(
            _pdk_with_diode(), td))
        env = dict(**{k: v for k, v in __import__("os").environ.items()})
        env["VIC_SEQ"] = seq
        env["VIC_NAME_NETS"] = "1" if name_nets else "0"
        res = subprocess.run([_tclsh, str(script)], capture_output=True,
                             text=True, env=env, timeout=120)
        assert res.returncode == 0, res.stderr
        return res.stdout


@needs_tclsh
def test_a_converging_loop_is_unchanged_and_says_so():
    out = _drive("{a b c} {a b} {a} {}")
    assert "ANTENNA_LOOP_CONVERGED: iter=3" in out
    assert "ANTENNA_LOOP_SEQUENCE: 3 2 1 0" in out
    assert "ANTENNA_LOOP_NOT_CONVERGED" not in out
    # the escalation is untouched on the turns that DO repair
    assert "margin=0" in out and "margin=10" in out and "margin=20" in out


@needs_tclsh
def test_progress_is_a_smaller_count_even_when_the_set_is_not_nested():
    """spm window 1, MEASURED: 22 -> 7 with `x[10]` and `x[17]` NEWLY
    violating. That turn repaired fifteen nets; a rule that demanded the new
    set be a SUBSET would have called it non-progress and stopped there. The
    loop must run the whole cap and reach 2, exactly as it did before."""
    out = _drive("{a b c d e f g h i j k l m n o p q r s t u v} "
                 "{x1 x2 x3 x4 x5 x6 x7} {y1 y2 y3 y4 y5 y6} "
                 "{z1 z2 z3 z4 z5} {p1 p2 p3 p4} {q1 q2} {q1 q2}")
    assert "ANTENNA_LOOP_SEQUENCE: 22 7 6 5 4 2 2" in out
    assert "stop=CAP" in out
    assert out.count("REPAIR_ANTENNA_DONE") == 6
    assert "ANTENNA_LOOP_BEST: iter=5 nets=2" in out


@needs_tclsh
def test_a_fixed_point_is_non_convergence_and_the_loop_stops_there():
    """spm window 2: it held 2 for four turns and shipped 3. The same set
    twice is a fixed point of the repair, not a fixed point being reached."""
    out = _drive("{a b} {a b} {a b} {a b} {a b c} {a b} {a b c}")
    assert "ANTENNA_LOOP_SEQUENCE: 2 2" in out
    assert "stop=FIXED_POINT" in out
    assert "ANTENNA_LOOP_NOT_CONVERGED" in out
    # ONE wasted repair, and it leaves 2 — the old loop ran the whole cap and
    # left 3.
    assert out.count("REPAIR_ANTENNA_DONE") == 1
    assert "best=2@iter0 last=2" in out


@needs_tclsh
def test_the_same_count_with_different_nets_is_caught():
    """THE CASE A COUNT CANNOT SEE. Both turns report 2; they are not the same
    2, and the old stop rule had no way to notice."""
    out = _drive("{a b} {a c} {a b} {a c}")
    assert "violating={a b}" in out and "violating={a c}" in out
    assert "stop=OSCILLATING" in out          # not FIXED_POINT: the nets moved


@needs_tclsh
def test_walking_past_the_best_is_reported_not_silent():
    """spm window 2: it reached 2 and left 3. The old loop printed neither
    number."""
    out = _drive("{a b c} {a b} {a b d} {a b} {a b d}")
    assert "ANTENNA_LOOP_BEST: iter=1 nets=2" in out
    assert "ANTENNA_LOOP_SEQUENCE: 3 2 3" in out
    assert "stop=REGRESSED" in out
    assert "ANTENNA_LOOP_BEST_NOT_RESTORED" in out
    assert "ORD-2008" in out          # WHY it cannot be restored, in the log


@needs_tclsh
def test_without_membership_the_old_count_rule_is_kept_byte_for_byte():
    """"the set did not shrink" and "nobody could tell me what the set was"
    are different facts. A tool that does not name the violating nets gets the
    loop it always had — the escalation to the cap — and the log SAYS the stop
    rule degraded."""
    out = _drive("{a b c d e f g h i} {a b c d e f g h i} {a b c d e f g h i} "
                 "{a b c d e f g h i} {a b c d e f g h i} "
                 "{a b c d e f g h i} {a b c d e f g h i}",
                 name_nets=False)
    assert "ANTENNA_LOOP_MEMBERSHIP_UNAVAILABLE" in out
    assert "margin=0" in out and "margin=20" in out and "margin=40" in out
    assert "membership=0" in out
    assert "stop=CAP" in out
    assert out.count("REPAIR_ANTENNA_DONE") == 6      # the whole cap, as before


def test_the_report_carries_what_the_loop_did_not_just_where_it_stopped():
    trace = r.antenna_loop_trace(
        "ANTENNA_LOOP_SEQUENCE: 3 2 3\n"
        "ANTENNA_LOOP_BEST: iter=1 nets=2\n"
        "ANTENNA_LOOP_NOT_CONVERGED: stop=REGRESSED membership=1 "
        "sequence={3 2 3} best=2@iter1 last=3 remaining={a b d}\n"
        "ANTENNA_PIN_FEEDER_OUTSIDE_ROWS: net=x[16] pin_y=3161.74 um "
        "rows_y=384.16..2399.04 um gap=762.70 um -- because\n")
    assert trace["sequence"] == [3, 2, 3]
    assert trace["best_net_violations"] == 2
    assert trace["last_net_violations"] == 3
    assert trace["converged"] is False
    assert trace["best_not_restored"] is True
    assert trace["membership_available"] is True
    assert trace["stop_reason"] == "REGRESSED"
    assert trace["pins_outside_cell_rows"] == [
        {"net": "x[16]", "pin_y_um": 3161.74,
         "rows_y_um": [384.16, 2399.04], "gap_um": 762.70}]


def test_a_log_with_no_loop_trace_reports_none_not_a_default():
    """A design that was already antenna-clean skipped the loop, and an OLD log
    has no markers at all. Neither is "it did not converge"."""
    trace = r.antenna_loop_trace(
        "ANTENNA_ALREADY_CLEAN: 0 net violations, skipping repair+reroute\n"
        "[INFO ANT-0002] Found 0 net violations.\n")
    assert trace["converged"] is None
    assert trace["sequence"] == []
    assert trace["best_net_violations"] is None
    assert trace["best_not_restored"] is False
    assert trace["membership_available"] is None
