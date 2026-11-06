#!/usr/bin/env python3
"""TAPEOUT-SIGNOFF — the single-corner-closure confounder fix (ibex-surfaced,
recurring across aes/subservient/sha256 as STA-rigor FAIL).

Two chip-AGNOSTIC gaps, both closed program-first:

  1. DRV constraints in the auto-SDC. The Phase-3 auto-SDC carried NO design-rule
     constraints (no set_max_transition / set_max_capacitance), so on a large
     design slews explode (ibex: 9.97 ns vs the tt-liberty's own 1.5 ns
     default_max_transition) yet the design still PASSES the typical-corner STA —
     the violation is HIDDEN until the ss corner turns it into a huge setup
     violation. `_build_auto_silicon_sdc` now emits set_max_transition /
     set_max_capacitance DERIVED FROM THE PDK LIBERTY (`_liberty_drv_limits`),
     never a fabricated literal (§4.05).

  2. Multi-corner OCV sign-off STA. The prior multi-corner report varied only the
     RC (SPEF) corner, keeping the nominal liberty — it never signed off the ss/ff
     PROCESS corners, so the ss setup blow-up was never surfaced. `_emit_mcorner_ocv_sta`
     signs off SETUP @ ss liberty + HOLD @ ff liberty with the flat-OCV derate +
     recovery/removal/MPW the rigor gate demands, and the rigor gate now PREFERS
     that multi-corner report. §4.05: the REAL per-corner slack is reported (a
     genuine ss violation appears VIOLATED, never hidden); single-process-corner
     PDKs get an honest single-corner disclosure (no fabricated ss/ff).
"""
from __future__ import annotations

import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import sta_signoff_rigor_check as G  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════════
# 1. DRV limits derived from the PDK liberty
# ═══════════════════════════════════════════════════════════════════════════

_LIB_TT = (
    "library (sky130_fd_sc_hd__tt) {\n"
    "  default_fanout_load : 1.0;\n"
    "  default_max_transition : 1.5000000000;\n"
    "  cell (buf) { pin (X) { max_capacitance : 5.0000000000; } }\n"
    "  cell (inv) { pin (Y) { max_capacitance : 0.0210670000; } }\n"
    "}\n"
)










# ═══════════════════════════════════════════════════════════════════════════
# 2. auto-SDC carries the DRV constraints
# ═══════════════════════════════════════════════════════════════════════════













# ═══════════════════════════════════════════════════════════════════════════
# 3. multi-corner OCV STA — TCL source-pin + rigor-gate consumption
# ═══════════════════════════════════════════════════════════════════════════







_MCORNER_FULL_RIGOR = """\
=== SETUP corner: process=SS liberty, SPEF=chip_top.spef ===
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
Startpoint: reg_a
Endpoint: reg_b
  -52.69   slack (VIOLATED)
worst slack max -52.69
tns -1234.5
Recovery/Removal checks:
   reg_rst recovery 0.31 slack (MET)
   reg_rst removal 0.12 slack (MET)
Min Pulse Width checks:
   clk min_pulse_width 1.80 slack (MET)
=== HOLD corner: process=FF liberty, SPEF=chip_top.spef ===
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
   0.20 slack (MET)
worst slack min 0.20
recovery removal min_pulse_width
"""

_SINGLE_FULL_RIGOR = """\
   0.42 slack (MET)
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
recovery removal min_pulse_width
"""


def test_rigor_gate_prefers_mcorner_ocv_report(tmp_path):
    """When both a single-corner and a multi-corner OCV report exist, the rigor
    gate evaluates the MULTI-CORNER one (the run is judged on multi-corner
    sign-off, not the single nom corner)."""
    d = tmp_path / "phase3" / "stage3" / "sta"
    d.mkdir(parents=True)
    (d / "post_route_timing.rpt").write_text(_SINGLE_FULL_RIGOR)
    (d / "sta_mcorner_ocv.rpt").write_text(_MCORNER_FULL_RIGOR)
    rpt = G._find_report(tmp_path)
    assert rpt.name == "sta_mcorner_ocv.rpt"


def test_rigor_gate_passes_on_full_rigor_even_when_ss_violated(tmp_path):
    """§4.05 — rigor != closure: a multi-corner report with a VIOLATED ss setup
    slack still PASSES the RIGOR gate (it carries the full derate + check types).
    The violation is SURFACED in the report body, not hidden; timing closure is a
    separate dimension."""
    rpt = tmp_path / "sta_mcorner_ocv.rpt"
    rpt.write_text(_MCORNER_FULL_RIGOR)
    res = G.evaluate(_MCORNER_FULL_RIGOR)
    assert res["verdict"] == "PASS"
    assert res["ocv_derate_applied"] and res["recovery_checked"]
    assert res["removal_checked"] and res["min_pulse_width_checked"]
    # the VIOLATED ss slack IS present in the report (surfaced, not masked).
    assert "VIOLATED" in _MCORNER_FULL_RIGOR
    assert "-52.69" in _MCORNER_FULL_RIGOR






# ── OpenSTA-3.1.0 check-type marker (the report_check_types output has no
#    literal recovery/removal/min_pulse_width words) ───────────────────────────

# A REAL OpenSTA 3.1.0 report shape: report_check_types prints "Group Slack" +
# "Required Width" tables (NO literal recovery/removal/min_pulse_width words), so
# the emitter's authoritative marker is what carries the check-type evidence.
_OPENSTA_310_WITH_MARKER = """\
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
worst slack max 0.42
Group                                  Slack
--------------------------------------------
asynchronous                            1.09
max slew
Pin                                    Limit    Slew   Slack
_x/A                                    1.50    0.90    0.60 (MET)
                                     Required  Actual
Pin                                    Width   Width   Slack
_clk (high)                             1.30    9.85    8.55 (MET)
SIGNOFF_WORST_PATHS_REPORTED path_delay=max group_path_count=3
SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew min_pulse_width max_capacitance
"""

# ORGANIC #540 — why the fixture above gained a line. It was captured from a
# REAL OpenSTA 3.1.0 sign-off report, and it carries no startpoint, no endpoint
# and no arrival breakdown, because the emitter's `report_checks` was erroring
# into a silent `catch` on every invocation. Nobody noticed: the test that owns
# this fixture was checking the DRV marker, which did appear. The fixture was a
# faithful record of a BROKEN report asserted to PASS the sign-off rigor gate —
# which is exactly the blindness #540 reports. The line added above is the one
# the FIXED emitter now writes. The unfixed shape is kept below, and is now
# required to FAIL.
_OPENSTA_310_NO_WORST_PATH = _OPENSTA_310_WITH_MARKER.replace(
    "SIGNOFF_WORST_PATHS_REPORTED path_delay=max group_path_count=3\n", "")

_OPENSTA_310_NO_MARKER = """\
OCV_DERATE_APPLIED early=0.95 late=1.05 flat-OCV
worst slack max 0.42
Group                                  Slack
--------------------------------------------
asynchronous                            1.09
max slew
Pin                                    Limit    Slew   Slack
_x/A                                    1.50    0.90    0.60 (MET)
"""




def test_rigor_gate_passes_on_opensta310_output_via_marker():
    """§ the fix: an OpenSTA-3.1.0 report whose report_check_types output has NO
    literal check-type words STILL PASSES because the emitter marker attests the
    recovery/removal/MPW checks were performed."""
    res = G.evaluate(_OPENSTA_310_WITH_MARKER)
    assert res["verdict"] == "PASS", res
    assert res["recovery_checked"] and res["removal_checked"]
    assert res["min_pulse_width_checked"]


def test_rigor_gate_fails_a_report_whose_slack_has_no_path_behind_it():
    """ORGANIC #540 — a sign-off report that records a slack with NO worst-path
    evidence must FAIL, and the finding must name that as the gap.

    This is the exact corpus shape: full derate, full check-types marker, a
    `worst slack` number — and nothing saying what produced it, because
    `report_checks` errored inside a `catch`. The gate used to PASS it, so the
    defect was invisible to the one gate positioned to see it."""
    res = G.evaluate(_OPENSTA_310_NO_WORST_PATH)
    assert res["verdict"] == "FAIL", res
    assert res["worst_path_evidence"] is False, res
    assert res["worst_path_evidence_source"] is None, res
    assert any("worst-path evidence" in m for m in res["missing"]), res
    # the dimensions that already worked must be unaffected — this FAILs for
    # the path gap ALONE, not by collateral damage to the check-type detection.
    assert res["ocv_derate_applied"] and res["recovery_checked"]
    assert res["removal_checked"] and res["min_pulse_width_checked"]
    assert len(res["missing"]) == 1, res


def test_rigor_gate_reads_a_failed_path_query_as_negative_evidence():
    """A report whose path query FAILED and SAID so must FAIL — and the reason
    the tool gave must survive into the finding.

    §4.05: the loud failure marker exists so the report states why it has no
    path. A gate that treated the marker's mere presence as "the emitter did
    its job" would convert an explicit error into a pass."""
    body = _OPENSTA_310_NO_WORST_PATH + (
        "SIGNOFF_WORST_PATHS_FAILED path_delay=max reason=Error 514: "
        "t.tcl line 1, '-max' is not a known keyword or flag.\n")
    res = G.evaluate(body)
    assert res["verdict"] == "FAIL", res
    assert res["worst_path_evidence"] is False, res
    assert res["worst_path_query_failures"], res
    assert "Error 514" in res["worst_path_query_failures"][0], res
    assert any("FAILED" in m for m in res["missing"]), res


def test_a_failed_pass_outranks_a_sibling_pass_that_succeeded():
    """A two-pass report (setup + hold) where ONE pass lost its path is NOT
    evidenced. The surviving pass cannot account for the other's slack, and a
    gate that let a good setup section cover a dead hold section would restore
    exactly the partial-evidence hole #540 is about."""
    body = (_OPENSTA_310_WITH_MARKER
            + "=== HOLD corner ===\nworst slack min 0.20\n"
              "SIGNOFF_WORST_PATHS_FAILED path_delay=min reason=Error 514: "
              "'-min' is not a known keyword or flag.\n")
    res = G.evaluate(body)
    assert res["worst_path_evidence"] is False, res
    assert res["verdict"] == "FAIL", res
    assert "path_delay=min" in res["worst_path_query_failures"][0], res


def test_a_real_path_dump_counts_without_any_marker():
    """A report from a pre-marker emitter (or another tool) still counts when it
    carries a genuine path dump.

    `_emit_spef_sta` calls a bare `report_checks` with no flag — it never had
    the bug and never carries the marker, and it must not be failed for that."""
    body = _OPENSTA_310_NO_WORST_PATH + (
        "Startpoint: reg_a (rising edge-triggered flip-flop clocked by clk)\n"
        "Endpoint: reg_b (rising edge-triggered flip-flop clocked by clk)\n"
        "                           1.42   data arrival time\n")
    res = G.evaluate(body)
    assert res["worst_path_evidence"] is True, res
    assert res["worst_path_evidence_source"] == "path-dump", res
    assert res["verdict"] == "PASS", res


def test_rigor_gate_fails_opensta310_without_marker_no_false_pass():
    """§4.05 no false-PASS: the same OpenSTA-3.1.0 tables WITHOUT the marker (the
    checks were not actually run/attested) FAIL — the plain 'Group Slack' /
    'max slew' tables do not contain the check-type words, so the gate is not
    fooled into passing."""
    res = G.evaluate(_OPENSTA_310_NO_MARKER)
    assert res["verdict"] == "FAIL", res
    assert res["recovery_checked"] is False
    assert res["removal_checked"] is False
    assert res["min_pulse_width_checked"] is False




# ── v1.2.x regression: the multi_process disclosure %-format must not crash ──
def test_mcorner_ocv_disclosure_escaped_percent_no_typeerror():
    """v1.2.85 regression (caught live on the sha256 sky130A re-run):
    step_canonicalize_artefacts built the multi-corner-OCV `disclosure` string with
    a bare `±5%` inside a `% (setup_lbl, hold_lbl)`-formatted literal, so Python read
    `% +` (from "5% + recovery") as a THIRD conversion spec → TypeError: not enough
    arguments for format string — on the multi_process=True branch that EVERY sky130A
    ss+ff run takes, crashing the runner AFTER all EDA work. The percent must be
    escaped (`±5%%`). This pins the exact expression + a source guard."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]
           / "phase3_one_shot_runner.py").read_text()
    # source guard: the %-FORMATTED disclosure literal must carry the ESCAPED
    # percent. (A separate f-string note keeps a bare `±5%` — that is SAFE, an
    # f-string does no %-substitution — so we assert the escaped form exists, not
    # a blanket ban on the bare form.)
    assert "flat-OCV ±5%% + recovery/" in src
    # behavioural: the exact multi_process=True expression renders without raising.
    setup_lbl, hold_lbl = "ss_100C_1v40", "ff_n40C_1v95"
    rendered = ("Multi-corner OCV sign-off: SETUP @ %s process (slow) + max-RC, "
                "HOLD @ %s process (fast) + min-RC, flat-OCV ±5%% + recovery/"
                "removal/MPW. Per-corner slack is REAL — a violation is SURFACED, "
                "not masked; close it with the DRV constraints + a timing ECO."
                % (setup_lbl, hold_lbl))
    assert "±5% + recovery" in rendered          # literal percent survives
    assert setup_lbl in rendered and hold_lbl in rendered
