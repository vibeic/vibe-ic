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

import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

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













# ───────────────────── 1. the antenna repair loop ─────────────────────

import shutil          # noqa: E402

_tclsh = shutil.which("tclsh")

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






















# ───────── SPM-12: one report, two stamped corners (lane spmspice) ─────────
#
# MEASURED by lane spmspice over the LANDED v1.17.52 code: a report stamping
# BOTH `ss_125C_4v50` and `ff_n40C_5v50` was accepted, and `parse_sta_corner_basis`
# silently answered with whichever of them the first matching regex found first
# — cone 5.3238 ns / SPICE 4.1188 ns = -22.63 % against 20.03 %, MISMATCH. The
# SAME design whose report stamps `ss` alone measures 7.4884 ns. A 1.8x swing in
# the number that gets the verdict, decided by regex order.

_ONE_CORNER = ("STA_BASIS_LIBERTY: /pdk/lib/x__ss_125C_4v50.lib\n"
               "OCV_DERATE_APPLIED early=0.95 late=1.05\n")
_TWO_CORNERS = (_ONE_CORNER +
                "# corner_liberty: ff=/pdk/lib/x__ff_n40C_5v50.lib\n")


def test_two_stamped_corners_is_not_a_corner():
    got = scc.parse_sta_corner_basis(_TWO_CORNERS)
    assert got["liberty"] == ""                       # no answer is given
    assert got["declared_liberties"] == [             # MEMBERSHIP, both named
        "/pdk/lib/x__ff_n40C_5v50.lib", "/pdk/lib/x__ss_125C_4v50.lib"]
    assert got["ocv_late_derate"] == 1.05             # the rest still parses


def test_one_corner_stamped_twice_is_still_one_corner():
    """THE FALSE-REFUSAL CONTROL. A writer that repeats its own stamp has not
    declared two corners, and must not be refused."""
    got = scc.parse_sta_corner_basis(_ONE_CORNER + _ONE_CORNER)
    assert got["liberty"] == "/pdk/lib/x__ss_125C_4v50.lib"
    assert got["declared_liberties"] == ["/pdk/lib/x__ss_125C_4v50.lib"]


def test_one_corner_still_answers_and_none_still_refuses():
    assert scc.parse_sta_corner_basis(_ONE_CORNER)["liberty"] == \
        "/pdk/lib/x__ss_125C_4v50.lib"
    none = scc.parse_sta_corner_basis("no header here\n")
    assert none["liberty"] == "" and none["declared_liberties"] == []


_STA_BODY = """\
Startpoint: test (input port clocked by clk)
Endpoint: ep (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

  Slew    Load    Delay    Time   Description
------------------------------------------------------------
                   0.00    0.00   clock clk (rise edge)
                   4.80    4.80 v input external delay
   0.08    0.00    0.00    4.80 v test (in)
   0.04    0.33    0.55    5.35 v u1/Z (BUF)
           0.33    0.00    5.35 ^ ep/D (DFF)
                           5.35   data arrival time
"""


def _spm12_project(tmp_path, corner_header):
    p = tmp_path / "proj"
    (p / "phase3" / "stage3" / "pnr").mkdir(parents=True)
    (p / "phase3" / "stage3" / "extracted").mkdir(parents=True)
    (p / "phase3" / "stage3" / "sta").mkdir(parents=True)
    (p / "phase3" / "stage3" / "pnr" / "x_pnr.v").write_text(
        "module x(); BUF u1 (.A(test), .Z(n1)); DFF ep (.D(n1)); endmodule\n")
    (p / "phase3" / "stage3" / "extracted" / "x.spef").write_text(
        '*SPEF "ieee 1481-1999"\n*C_UNIT 1 PF\n*NAME_MAP\n*1 n1\n'
        '*D_NET *1 0.001\n*END\n')
    rpt = p / "phase3" / "stage3" / "sta" / "sta_mcorner_ocv.rpt"
    rpt.write_text(corner_header + _STA_BODY)
    return p, rpt


def test_the_driver_refuses_a_report_that_stamps_two_corners(tmp_path,
                                                             monkeypatch):
    """The refusal is WIRED, not merely present: the driver returns ERROR and
    NAMES both corners rather than correlating against one of them."""
    p, rpt = _spm12_project(tmp_path, _TWO_CORNERS)
    monkeypatch.setattr(scc, "_resolve_ngspice", lambda c: "/usr/bin/true")
    monkeypatch.setattr(scc, "_read_container_text",
                        lambda c, path: "library(x) { }\n")
    monkeypatch.setattr(scc, "discover_installed_pdk_sources",
                        lambda c, lib, cells: {"subckt_names": {"BUF", "DFF"},
                                               "cell_text": "", "cell_spice": "",
                                               "model_file": "/m", "model_section": "ss",
                                               "model_preludes": []})
    # R-0915-166 — the picker now also takes the this-run freshness anchor;
    # this stub is about WHICH report is returned, not about selection.
    monkeypatch.setattr(scc, "_pick_sta_report",
                        lambda proj, names, not_before=None: rpt)
    got = scc.run_installed_pdk_path_correlation(p, "/pdk/lib/x__tt.lib",
                                                 container="none")
    assert got["status"] == "ERROR", got
    assert "2 DIFFERENT corner libraries" in got["reason"], got["reason"]
    assert "x__ss_125C_4v50.lib" in got["reason"]
    assert "x__ff_n40C_5v50.lib" in got["reason"]


def test_the_driver_still_proceeds_past_a_single_declared_corner(tmp_path,
                                                                monkeypatch):
    """THE OTHER DIRECTION. One stamped corner must NOT be refused by the new
    predicate — it must get past it and fail (or pass) further down on its own
    merits, never on the corner count."""
    p, rpt = _spm12_project(tmp_path, _ONE_CORNER)
    monkeypatch.setattr(scc, "_resolve_ngspice", lambda c: "/usr/bin/true")
    monkeypatch.setattr(scc, "_read_container_text",
                        lambda c, path: "library(x) { }\n")
    monkeypatch.setattr(scc, "discover_installed_pdk_sources",
                        lambda c, lib, cells: {"subckt_names": {"BUF", "DFF"},
                                               "cell_text": "", "cell_spice": "",
                                               "model_file": "/m", "model_section": "ss",
                                               "model_preludes": []})
    # R-0915-166 — the picker now also takes the this-run freshness anchor;
    # this stub is about WHICH report is returned, not about selection.
    monkeypatch.setattr(scc, "_pick_sta_report",
                        lambda proj, names, not_before=None: rpt)
    got = scc.run_installed_pdk_path_correlation(p, "/pdk/lib/x__tt.lib",
                                                 container="none")
    assert "DIFFERENT corner libraries" not in (got.get("reason") or ""), got


#: spm's OWN canonical multi-corner report, in miniature: a SETUP/ss section
#: carrying the path, and a HOLD/ff section after it. MEASURED on the real
#: `sta_mcorner_ocv.rpt`: 2 sections, `ss_125C_4v50` at line 4 and
#: `ff_n40C_5v50` at line 136, and `parse_sta_path` takes the first path block —
#: which is in the SETUP section. A file-wide refusal would refuse EVERY run of
#: this design, for the report's shape rather than for anything wrong with it.
_SECTIONED = (
    "=== SETUP corner: process=SS liberty=/pdk/x__ss_125C_4v50.lib, SPEF=a ===\n"
    "OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV\n"
    "STA_BASIS_LIBERTY: /pdk/x__ss_125C_4v50.lib\n"
    + _STA_BODY +
    "=== HOLD corner: process=FF liberty=/pdk/x__ff_n40C_5v50.lib, SPEF=b ===\n"
    "OCV_DERATE_APPLIED early=0.95 late=1.10 flat-OCV\n"
    "STA_BASIS_LIBERTY: /pdk/x__ff_n40C_5v50.lib\n"
    + _STA_BODY)


def test_a_sectioned_report_is_answered_by_the_paths_own_section():
    got = scc.parse_sta_corner_basis(_SECTIONED)
    assert got["sections"] == 2
    assert got["liberty"] == "/pdk/x__ss_125C_4v50.lib"
    assert got["declared_liberties"] == ["/pdk/x__ss_125C_4v50.lib"]
    # …and the OTHER corner is still DISCLOSED. The refusal is scoped; the
    # disclosure is not.
    assert got["declared_liberties_in_file"] == [
        "/pdk/x__ff_n40C_5v50.lib", "/pdk/x__ss_125C_4v50.lib"]
    # the derate comes from the same section, not from the other one
    assert got["ocv_late_derate"] == 1.05


def test_the_hold_section_first_does_not_hand_the_deck_the_fast_corner():
    """THE ORDERING HAZARD SPM-12 MEASURED. The old rule took the first match
    of the first regex that hit, so a report whose FF stamp came first built
    the deck at FF and charged a 1.8x delay swing to the design."""
    hold_first = (
        "=== HOLD corner: process=FF liberty=/pdk/x__ff_n40C_5v50.lib ===\n"
        "STA_BASIS_LIBERTY: /pdk/x__ff_n40C_5v50.lib\n"
        "=== SETUP corner: process=SS liberty=/pdk/x__ss_125C_4v50.lib ===\n"
        "STA_BASIS_LIBERTY: /pdk/x__ss_125C_4v50.lib\n" + _STA_BODY)
    got = scc.parse_sta_corner_basis(hold_first)
    assert got["liberty"] == "/pdk/x__ss_125C_4v50.lib"   # the PATH's corner


def test_two_corners_inside_the_paths_own_section_is_still_refused():
    """The scope narrows WHERE the ambiguity is looked for; it does not
    forgive one."""
    ambiguous = (
        "=== SETUP corner: process=SS liberty=/pdk/x__ss_125C_4v50.lib ===\n"
        "STA_BASIS_LIBERTY: /pdk/x__ss_125C_4v50.lib\n"
        "# corner_liberty: ff=/pdk/x__ff_n40C_5v50.lib\n" + _STA_BODY)
    got = scc.parse_sta_corner_basis(ambiguous)
    assert got["liberty"] == ""
    assert len(got["declared_liberties"]) == 2


# ── the SPEF is not on the design side when the STA states a load ──────────
#
# MEASURED (spm x gf180mcuD, image 0.3.46): scaling EVERY `*D_NET` total
# capacitance in the design's own SPEF by 10 — 673 records — moved this gate by
# NOTHING. `pct_error` -15.936758 both arms, `spice_path_delay_ns` 9.901463
# both arms, every per-cell PDK ratio byte-identical. Lane spmspice measured
# +153.6 % CRITICAL_MISMATCH for the same injection on ITS OWN replay, so the
# sensitivity is real for a report shape that does NOT state a load — and
# absent for one that does. That difference was invisible; it is now published
# per stage.

def test_the_load_source_is_named_per_stage():
    sta_stated = {"sta_load_pf": 0.04, "wire_cap_pf": 0.0361}
    assert scc.stagewise_stage_load_pf(sta_stated, False, 0.0) == (0.04, "sta_report")
    # …the SPEF only when the STA states nothing
    spef_only = {"sta_load_pf": None, "wire_cap_pf": 0.0361}
    assert scc.stagewise_stage_load_pf(spef_only, False, 0.0) == (0.0361, "spef")
    # …and the endpoint receiver on the last stage when it is the larger
    load, src = scc.stagewise_stage_load_pf(spef_only, True, 0.12)
    assert (round(load, 6), src) == (0.12, "endpoint_receiver")
    # NOTHING is not zero: a stage with neither still gets a floor, and says so
    load, src = scc.stagewise_stage_load_pf({}, False, 0.0)
    assert src == "none" and load == 1e-4


def test_the_deck_and_the_report_read_the_load_from_one_function():
    """A load spelled in two places is two places to get wrong. The deck the
    simulator runs and the number the report publishes must come from the SAME
    call."""
    import inspect
    body = inspect.getsource(scc.build_installed_stagewise_deck)
    assert "stagewise_stage_load_pf(" in body
    driver = inspect.getsource(scc.run_installed_pdk_path_correlation)
    assert "per_stage_load_source" in driver
    assert "stagewise_stage_load_pf(" in driver
