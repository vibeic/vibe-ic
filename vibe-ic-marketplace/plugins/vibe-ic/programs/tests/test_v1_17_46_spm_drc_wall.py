#!/usr/bin/env python3
"""`spm` on gf180mcuD halted at `drc` with 70 violations. 60 of them were ours.

MEASURED (host 8HD-6, image `ghcr.io/vibeic/vibeic-eda@sha256:06537f7e…`, own
label 0.3.46; plugin base `ad38a76d` = v1.17.45; two PnR arms whose only
difference is the fix under test):

  arm A (base)  76 sign-off violations: DF.13_MV 41 · DF.14_MV 19 ·
                ANT.16_ii_ANT.3 6 · ANT.16_ii_ANT.5 3 · PL.8 1 ·
                M1.4/M2.4/M3.4/M4.4/M5.4/MT.3 1 each
  arm B (fix)   16: DF.13_MV 0 · DF.14_MV 0, everything else BYTE-FOR-BYTE
                the same set. Zero new violations.

  (The six metal-density rows are present in BOTH arms because the sandbox
  streams the DEF straight to GDS without the flow's metal fill; the flow's
  own run closes them. arm A's remaining 70 is exactly the run's 70.)

WHAT WAS WRONG. `_build_tapcell_prune_tcl` decides tap coverage at
`placed.def` time. CTS, the resizer repair passes and `repair_antennas` all
create DEVICE-BEARING cells AFTER that, and `tapcell` cannot be re-run once
cells are placed. Measured on the shipped `spm.def`: 14 of 651 logic/buffer
instances and 4 of 64 antenna diodes had NO well-tie within the PDK max tap
distance — worst 98.7 um — and the sign-off deck put 60 of the run's 70
violations on them. Two of them (`wire70`, `wire79`, row y=709.52 um) were
7.84 um from a tie one row below and STILL violated: gf180mcu's DF.13_MV
grows the tap INSIDE nwell, and a neighbouring row's nwell is a separate
island. So the repair is PER ROW, not by euclidean distance.

Also covered here, both found while reading the same run:
  * RB-12 flow ordering — `signoff_metrics_aggregate` ran BEFORE the three
    sign-off gates that write the reports it reads.
  * RB-13 schema — the same record's LVS reader knew one of the two spellings
    its own producers use for the verdict.
  * RB-15 — the SPICE correlation gate built its deck at the ACTIVE liberty's
    PVT and compared it against a path taken from a report produced at a
    DIFFERENT corner, then charged the difference to the design.
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import phase3_one_shot_runner as r  # noqa: E402
import signoff_metrics_aggregate as sma  # noqa: E402
import spice_correlation_check as scc  # noqa: E402


def _pdk(**kw):
    base = dict(name="x", liberty="l", tech_lef="t", cell_lef="c",
                cell_gds="g", site="s", drc_deck="d",
                tapcell_master="gf180mcu_fd_sc_mcu7t5v0__filltie",
                tapcell_distance_um=14.0)
    base.update(kw)
    return r.PdkConfig(**base)


# ── the repair block itself ──────────────────────────────────────────────────
def test_welltie_repair_block_is_emitted_for_a_pdk_with_a_tap_master():
    tcl = r._build_welltie_coverage_repair_tcl(_pdk())
    assert "WELLTIE_COVERAGE_REPAIR" in tcl
    assert "gf180mcu_fd_sc_mcu7t5v0__filltie" in tcl


def test_welltie_repair_budget_is_the_pdk_max_tap_distance_not_a_literal():
    """The budget must TRACK the PDK. A PDK declaring 20 um gets 20 um."""
    assert "int(14.0 * $_wtdbu)" in r._build_welltie_coverage_repair_tcl(_pdk())
    assert "int(20.0 * $_wtdbu)" in r._build_welltie_coverage_repair_tcl(
        _pdk(tapcell_distance_um=20.0))


def test_welltie_repair_is_per_row_not_per_euclidean_distance():
    """`wire70` was 7.84 um from a tie in the row below and still violated."""
    tcl = r._build_welltie_coverage_repair_tcl(_pdk())
    # the anchor and the tie it is compared against are keyed by the SAME row
    assert "set _wtties $_wttie($_wty)" in tcl
    assert "abs($_wtt - $_wtcx) <= $_wtd" in tcl
    # and the tie is created at that row's own y
    assert "$_wtni setLocation $_wtx $_wty" in tcl


def test_welltie_repair_uses_the_row_orientation():
    """A tie placed N in an FS row mismatches its neighbours' implants."""
    tcl = r._build_welltie_coverage_repair_tcl(_pdk())
    assert "$_wtni setOrient $_wtro($_wty)" in tcl


def test_welltie_repair_refreshes_the_placement_cache_before_the_fill():
    """MEASURED: without this, `filler_placement` tiled a spacer over all 43
    new ties -- 474 NEW implant/well violations replacing 60 tap ones."""
    tcl = r._build_welltie_coverage_repair_tcl(_pdk())
    assert "catch {check_placement} _wtcp" in tcl
    assert tcl.index("catch {check_placement} _wtcp") > tcl.index(
        "odb::dbInst_create")


def test_welltie_repair_reports_an_anchor_it_could_not_place():
    """2 of 45 had no free site in their own row. That is a REPORT, never a
    silent drop."""
    tcl = r._build_welltie_coverage_repair_tcl(_pdk())
    assert "WELLTIE_COVERAGE_REPAIR_UNPLACEABLE" in tcl
    assert "unplaceable=$_wtfail" in tcl


def test_welltie_repair_excludes_the_tap_master_from_its_own_anchor_set():
    """A tie is not a device that needs a tie."""
    tcl = r._build_welltie_coverage_repair_tcl(_pdk())
    i = tcl.index('if {[$_wtmm getName] eq "gf180mcu_fd_sc_mcu7t5v0__filltie"}')
    assert "continue" in tcl[i:i + 200]


def test_welltie_repair_degrades_to_a_named_skip_without_a_tap_master():
    tcl = r._build_welltie_coverage_repair_tcl(_pdk(tapcell_master=None))
    assert "WELLTIE_COVERAGE_REPAIR_SKIPPED" in tcl
    assert "odb::dbInst_create" not in tcl


def test_welltie_repair_names_no_chip_or_design_literal():
    tcl = r._build_welltie_coverage_repair_tcl(_pdk())
    for lit in ("spm", "caravel", "sky130", "wire70", "wire79"):
        assert lit not in tcl.lower().replace(
            "gf180mcu_fd_sc_mcu7t5v0__filltie", "")


def test_welltie_repair_is_wired_before_the_row_fill_in_the_pnr_stage():
    """It has to run while the row sites are still free."""
    src = (PROGS / "phase3_one_shot_runner.py").read_text()
    assert "_build_welltie_coverage_repair_tcl(\n        pdk) + " \
           "_build_sparse_die_aware_filler_tcl(" in src


# ── RB-12: the sign-off gates write what the metrics record reads ────────────
def _stmt_order(func_src: str, needles: list) -> list:
    """Index of each needle's first appearance, as statement order."""
    return [func_src.index(n) for n in needles]


def test_declared_signoff_gates_run_before_the_metrics_record():
    """MEASURED: `signoff_metrics_aggregate` was produced over reports that did
    not exist yet -- 7 of 18 keys NOT_MEASURED, its own `--check` green because
    both sides were empty, and rc=1 FAIL in the SAME run's gate ledger."""
    src = (PROGS / "phase3_one_shot_runner.py").read_text()
    gates = src.index("plan.extend(step_declared_signoff_gates(project))")
    record = src.index("plan.append(step_signoff_metrics_aggregate(project))")
    assert gates < record, (
        "the gates that write post_route_signoff_corner.json, "
        "sta_corner_record_completeness.json and tapeout_precheck.json must "
        "be planned BEFORE the record that reads them")


def test_metrics_record_still_precedes_the_release_documents():
    """37.5ic blocks_on 37.4; the reorder must not have moved that."""
    src = (PROGS / "phase3_one_shot_runner.py").read_text()
    record = src.index("plan.append(step_signoff_metrics_aggregate(project))")
    docs = src.index("plan.append(step_tapeout_docs_gen(project))")
    assert record < docs


# ── RB-13: the LVS verdict has two spellings and both are the flow's own ─────
def _write_lvs(tmp_path: Path, payload: dict) -> Path:
    p = tmp_path / "reports" / "phase3"
    p.mkdir(parents=True, exist_ok=True)
    (p / "lvs.json").write_text(json.dumps(payload))
    return tmp_path


LVS_KEYS = ("design__lvs_error__count", "design__lvs_unmatched_device__count",
            "design__lvs_unmatched_net__count",
            "design__lvs_unmatched_pin__count")


def test_lvs_reads_the_netgen_parser_top_level_verdict(tmp_path):
    """The shape `spm` actually shipped: verdict at the TOP level."""
    proj = _write_lvs(tmp_path, {
        "verdict": "match", "verdict_reason": "circuits match uniquely",
        "summary": {"devices": {"ckt1": 661, "ckt2": 661},
                    "unmatched_devices": {"ckt1": 0, "ckt2": 0}}})
    for key in LVS_KEYS:
        cell = sma._lvs(proj, key)
        assert cell.value == 0, key
        assert "verdict=MATCH" in cell.basis


def test_lvs_still_reads_the_audit_spelling(tmp_path):
    """`eda_report_audit:lvs` puts it under summary. Unchanged."""
    proj = _write_lvs(tmp_path, {"summary": {"terminal_verdict": "MATCH"}})
    cell = sma._lvs(proj, LVS_KEYS[0])
    assert cell.value == 0
    assert "summary.terminal_verdict=MATCH" in cell.basis


def test_lvs_a_non_match_is_still_not_a_count(tmp_path):
    """The §4.05 no-leak arm: reading a second spelling must not turn a
    MISMATCH into a zero."""
    proj = _write_lvs(tmp_path, {"verdict": "mismatch",
                                 "summary": {"unmatched_devices":
                                             {"ckt1": 3, "ckt2": 3}}})
    cell = sma._lvs(proj, LVS_KEYS[1])
    assert cell.value == "NOT_MEASURED"
    assert "'MISMATCH'" in cell.reason and "not MATCH" in cell.reason


def test_lvs_no_verdict_at_all_names_both_spellings(tmp_path):
    proj = _write_lvs(tmp_path, {"summary": {"devices": {"ckt1": 1}}})
    cell = sma._lvs(proj, LVS_KEYS[0])
    assert cell.value == "NOT_MEASURED"
    assert "summary.terminal_verdict" in cell.reason
    assert "verdict" in cell.reason


# ── RB-15: the correlation must not cross corners ────────────────────────────
_OCV_REPORT = """\
=== SETUP corner: process=SS liberty=/pdk/lib/cell__ss_125C_4v50.lib, SPEF=x ===
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
STA_BASIS_LIBERTY: /pdk/lib/cell__ss_125C_4v50.lib
"""

_MULTICORNER_REPORT = """\
# Multi-corner SPEF STA (TAPEOUT-SIGNOFF P1)
# corner_liberty: max=/pdk/lib/cell__tt_025C_5v00.lib
"""


def test_sta_corner_basis_reads_the_report_declared_liberty():
    b = scc.parse_sta_corner_basis(_OCV_REPORT)
    assert b["liberty"] == "/pdk/lib/cell__ss_125C_4v50.lib"
    assert b["ocv_late_derate"] == 1.05


def test_sta_corner_basis_reads_the_multicorner_spelling():
    b = scc.parse_sta_corner_basis(_MULTICORNER_REPORT)
    assert b["liberty"] == "/pdk/lib/cell__tt_025C_5v00.lib"
    assert b["ocv_late_derate"] is None


def test_sta_corner_basis_is_empty_when_the_report_declares_nothing():
    """An undeclared corner must reach the caller as ABSENT, so it can decline
    rather than fall back on the active corner."""
    b = scc.parse_sta_corner_basis("Startpoint: a\nEndpoint: b\n")
    assert b["liberty"] == ""


def test_driver_declines_rather_than_correlating_across_corners():
    src = (PROGS / "spice_correlation_check.py").read_text()
    assert "refusing a cross-corner correlation" in src
    assert "refusing to correlate it against another corner" in src


def test_driver_divides_out_the_ocv_derate_the_spice_side_does_not_carry():
    src = (PROGS / "spice_correlation_check.py").read_text()
    assert "expected_ns = derated_ns / ocv_late if ocv_late else derated_ns" \
           in src


def test_stagewise_deck_visits_the_sta_operating_points():
    """The tolerance is derived per stage at the STA (slew, load) points, so
    the measurement has to be taken there. MEASURED on `spm`: the free-running
    chain gave -47.6 %, the same stages at those points -22.4 %."""
    stages = [
        {"cell": "buf", "toggle_pin": "I", "out_pin": "Z",
         "transition": "fall", "sta_load_pf": 0.04, "wire_cap_pf": 0.01,
         "sta_delay_ns": 0.55},
        {"cell": "buf", "toggle_pin": "I", "out_pin": "Z",
         "transition": "rise", "sta_load_pf": 0.39, "wire_cap_pf": 0.14,
         "sta_delay_ns": 1.39},
    ]
    deck = scc.build_installed_stagewise_deck(
        "/m.spice", "ss", [], "/c.spice", stages,
        {"buf": (["I", "Z", "VDD", "VNW", "VPW", "VSS"], "")},
        4.5, 125.0, 2.25, 0.05, [0.5, 2.0])
    # the STA load, not the SPEF wire cap
    assert "c0r so0r 0 40f" in deck and "c1r so1r 0 390f" in deck
    # both drive polarities for both stages
    for n in ("vsi0r", "vsi0f", "vsi1r", "vsi1f"):
        assert n in deck
    # measured to the transition the STA row declares
    assert "TARG v(so0r) VAL='2.25' FALL=1" in deck
    assert "TARG v(so1r) VAL='2.25' RISE=1" in deck


def test_stagewise_parse_takes_the_one_arc_that_can_exist():
    """Exactly one drive polarity can produce the declared output edge."""
    transcript = (
        "d0f                 =  3.94501e-10 targ=  1.03950e-08\n"
        "mx0f                =  4.50000e+00 at=  1.1e-08\n"
        "mn0f                =  0.00000e+00 at=  1.0e-08\n"
        "Error: measure  d0r  trig(TARG) : out of interval\n")
    vals, why = scc.parse_stagewise_meas(transcript, 1, 4.5)
    assert why == ""
    assert vals == pytest.approx([0.394501], rel=1e-6)


def test_stagewise_parse_refuses_when_no_polarity_survives():
    vals, why = scc.parse_stagewise_meas(
        "Error: measure  d0r  trig(TARG) : out of interval\n"
        "Error: measure  d0f  trig(TARG) : out of interval\n", 1, 4.5)
    assert vals is None
    assert "0 of 2 drive polarities" in why


def test_stagewise_parse_refuses_a_stage_that_did_not_swing():
    """A number taken off a node that never reached the rail is not a delay."""
    transcript = ("d0f = 3.9e-10 targ= 1e-08\n"
                  "mx0f = 1.00000e+00 at= 1.1e-08\n"
                  "mn0f = 0.00000e+00 at= 1.0e-08\n")
    vals, why = scc.parse_stagewise_meas(transcript, 1, 4.5)
    assert vals is None and "full swing" in why


def test_stagewise_parse_refuses_when_both_polarities_survive():
    """Two live arcs is an unresolved sensitisation, not a choice to make."""
    transcript = "".join(
        f"d0{v} = 3.9e-10 targ= 1e-08\nmx0{v} = 4.5e+00 at= 1e-08\n"
        f"mn0{v} = 0.0e+00 at= 1e-08\n" for v in ("r", "f"))
    vals, why = scc.parse_stagewise_meas(transcript, 1, 4.5)
    assert vals is None and "2 of 2 drive polarities" in why


def test_path_deck_window_clears_the_delay_it_is_measuring():
    """At tt the path is 3.87 ns inside an 8 ns half-period and nothing showed;
    at the report's own corner it is 7.15 ns, 89 % of that window."""
    src = (PROGS / "spice_correlation_check.py").read_text()
    assert "pw = max(8.0, 24.0 * tr_ns, 3.0 * float(expected_ns or 0.0))" in src


# ── the modules still parse and the new names are real ───────────────────────
@pytest.mark.parametrize("mod", ["phase3_one_shot_runner.py",
                                 "signoff_metrics_aggregate.py",
                                 "spice_correlation_check.py"])
def test_touched_modules_parse(mod):
    ast.parse((PROGS / mod).read_text())
