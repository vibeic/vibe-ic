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

import phase3_one_shot_runner as R  # noqa: E402
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


def test_liberty_drv_limits_parses_slew_and_cap_ceiling(tmp_path):
    """max_transition comes from the library default; with no library-level
    default_max_capacitance the ceiling is the MAX characterised pin cap (5.0),
    disclosed as a PDK-derived ceiling — both are REAL liberty values."""
    lib = tmp_path / "sky130_fd_sc_hd__tt_025C_1v80.lib"
    lib.write_text(_LIB_TT)
    res = R._liberty_drv_limits(str(lib))
    assert res["max_transition_ns"] == 1.5
    assert res["max_capacitance_pf"] == 5.0
    assert "default_max_transition" in res["slew_source"]
    assert "ceiling" in res["cap_source"]
    assert "DRV limits derived from the PDK liberty" in res["note"]


def test_liberty_drv_limits_prefers_library_default_cap(tmp_path):
    """A library-level default_max_capacitance is preferred over the pin-cap
    ceiling."""
    lib = tmp_path / "x.lib"
    lib.write_text(
        "library (x) {\n"
        "  default_max_transition : 2.0;\n"
        "  default_max_capacitance : 0.3;\n"
        "  cell (buf) { pin (X) { max_capacitance : 5.0; } }\n"
        "}\n")
    res = R._liberty_drv_limits(str(lib))
    assert res["max_transition_ns"] == 2.0
    assert res["max_capacitance_pf"] == 0.3
    assert "default_max_capacitance" in res["cap_source"]


def test_liberty_drv_limits_no_tokens_returns_none_no_fabrication(tmp_path):
    """§4.05: a liberty declaring neither token yields None for both — NEVER a
    fabricated limit — and an honest note."""
    lib = tmp_path / "bare.lib"
    lib.write_text("library (x) { cell (inv) { area : 1.0; } }\n")
    res = R._liberty_drv_limits(str(lib))
    assert res["max_transition_ns"] is None
    assert res["max_capacitance_pf"] is None
    assert "no fabricated limit" in res["note"]


def test_liberty_drv_limits_missing_path_no_fabrication():
    """A missing/empty liberty path yields all-None + a disclosure (never a
    fabricated DRV)."""
    res = R._liberty_drv_limits("")
    assert res["max_transition_ns"] is None
    assert res["max_capacitance_pf"] is None
    assert "NO DRV limit" in res["note"]


# ═══════════════════════════════════════════════════════════════════════════
# 2. auto-SDC carries the DRV constraints
# ═══════════════════════════════════════════════════════════════════════════

def test_auto_sdc_emits_drv_constraints_when_derived(tmp_path):
    sdc = R._build_auto_silicon_sdc(
        tmp_path, top="chip_top", drv_slew_ns=1.5, drv_cap_pf=5.0,
        drv_note="DRV limits derived from the PDK liberty: max_transition=1.5 ns")
    assert "set_max_transition 1.5 [current_design]" in sdc
    assert "set_max_capacitance 5.0 [current_design]" in sdc
    assert "TAPEOUT-SIGNOFF (DRV)" in sdc
    # the clock + IO delays are still present (DRV is additive).
    assert "create_clock" in sdc


def test_auto_sdc_backward_compatible_without_drv_args(tmp_path):
    """§ regression: called with no DRV args the SDC is byte-identical to the
    pre-DRV behaviour (no DRV block, no set_max_* line)."""
    sdc = R._build_auto_silicon_sdc(tmp_path, top="chip_top")
    assert "set_max_transition" not in sdc
    assert "set_max_capacitance" not in sdc
    assert "TAPEOUT-SIGNOFF (DRV)" not in sdc


def test_auto_sdc_honest_disclosure_when_no_limits(tmp_path):
    """§4.05: when the resolver found no limits but passes a note, the SDC carries
    the honest disclosure and NO fabricated constraint."""
    sdc = R._build_auto_silicon_sdc(
        tmp_path, top="chip_top",
        drv_note="PDK liberty declares neither default_max_transition nor "
                 "max_capacitance; NO DRV limit emitted (§4.05 — no fabricated "
                 "limit)")
    assert "set_max_transition" not in sdc
    assert "set_max_capacitance" not in sdc
    assert "no fabricated limit" in sdc


def test_drv_block_only_slew_when_cap_absent():
    """A slew-only liberty emits set_max_transition alone (no fabricated cap)."""
    block = R._drv_constraints_sdc_block(1.5, None, "slew only")
    assert "set_max_transition 1.5 [current_design]" in block
    assert "set_max_capacitance" not in block


# ═══════════════════════════════════════════════════════════════════════════
# 3. multi-corner OCV STA — TCL source-pin + rigor-gate consumption
# ═══════════════════════════════════════════════════════════════════════════

def test_emit_mcorner_ocv_sta_source_carries_full_rigor():
    """The multi-corner OCV STA TCL emits the flat-OCV derate, the OCV marker,
    the recovery/removal + min-pulse-width + max-slew check types, and reports
    the worst-path slews (so the slew explosion is visible)."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    i = src.index("def _emit_mcorner_ocv_sta")
    # Window covers the function prologue + the two _pass() passes; sized with
    # headroom for the optional netlist_override arg (ECO post-ECO re-measure).
    win = src[i:i + 5600]
    assert "_flat_ocv_derate_tcl" in win        # two-command derate helper
    assert "OCV_DERATE_APPLIED" in win
    assert "_report_check_types_tcl" in win     # guarded + marked check types
    assert "slew capacitance" in win            # -fields {slew capacitance}
    assert "SETUP" in win and "HOLD" in win      # setup@ss, hold@ff split
    assert "process=" in win                    # process-corner labelling
    # the shared check-types helper carries the command + authoritative marker.
    j = src.index("def _report_check_types_tcl")
    helper = src[j:j + 1200]
    assert "report_check_types -recovery -removal -max_slew" in helper
    assert "min_pulse_width" in helper


def test_emit_mcorner_ocv_sta_skips_without_netlist(tmp_path):
    """§4.05: no routed netlist / SDC → honest False (no vacuous report)."""
    notes = []
    ok = R._emit_mcorner_ocv_sta(
        tmp_path, "chip_top", _PdkStub(), "", {"SS": "/c/ss.lib",
                                               "FF": "/c/ff.lib"},
        {}, None, tmp_path / "out.rpt", notes)
    assert ok is False
    assert any("skipped" in n for n in notes)


class _PdkStub:
    liberty = "/foss/pdks/x/tt.lib"
    macro_libs: list = []


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


def test_flat_ocv_derate_uses_two_commands_not_combined():
    """LIVE-VALIDATED root cause: OpenSTA 3.1.0 rejects the combined
    `set_timing_derate -early X -late Y` ('only one of -early and -late can be
    specified'), aborting the STA script before the rigor report is written.
    The helper must emit TWO separate commands, and every emitter must use it."""
    tcl = R._flat_ocv_derate_tcl()
    assert "set_timing_derate -early 0.95" in tcl
    assert "set_timing_derate -late 1.05" in tcl
    # the combined single-command form must NOT appear.
    assert "-early 0.95 -late" not in tcl
    assert tcl.count("set_timing_derate") == 2
    # indent variant (used inside the AOCV catch block).
    ind = R._flat_ocv_derate_tcl(indent="  ")
    assert ind.startswith("  set_timing_derate -early")


def test_spef_sta_and_mcorner_emitters_avoid_combined_derate():
    """§ regression: neither _emit_spef_sta nor _emit_mcorner_ocv_sta emits the
    combined `-early .. -late ..` form (which errors on this OpenSTA build)."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    for fn in ("def _emit_spef_sta", "def _emit_mcorner_ocv_sta"):
        i = src.index(fn)
        win = src[i:i + 6000]
        assert "set_timing_derate -early" not in win or "_flat_ocv_derate_tcl" in win
        # the load-bearing check: the combined form is gone from the emitter body.
        assert f"-early {R._FLAT_OCV_DERATE_EARLY} -late" not in win
        assert "-early 0.95 -late" not in win


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
SIGNOFF_CHECK_TYPES_REPORTED recovery removal max_slew min_pulse_width max_capacitance
"""

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


def test_report_check_types_tcl_emits_guarded_marker():
    """The check-types TCL runs report_check_types under a catch and appends the
    authoritative marker ONLY on success (else records the failure reason)."""
    tcl = R._report_check_types_tcl("/x/out.rpt")
    assert "report_check_types -recovery -removal -max_slew -min_pulse_width" in tcl
    assert "SIGNOFF_CHECK_TYPES_REPORTED recovery removal" in tcl
    assert "catch {report_check_types" in tcl
    assert "SIGNOFF_CHECK_TYPES_FAILED" in tcl  # failure path recorded


def test_rigor_gate_passes_on_opensta310_output_via_marker():
    """§ the fix: an OpenSTA-3.1.0 report whose report_check_types output has NO
    literal check-type words STILL PASSES because the emitter marker attests the
    recovery/removal/MPW checks were performed."""
    res = G.evaluate(_OPENSTA_310_WITH_MARKER)
    assert res["verdict"] == "PASS", res
    assert res["recovery_checked"] and res["removal_checked"]
    assert res["min_pulse_width_checked"]


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


def test_resolve_signoff_corner_libs_from_staged_input(tmp_path):
    """Staged input/pdk/liberty ss/tt/ff libs are classified into SS/TT/FF."""
    libd = tmp_path / "input" / "pdk" / "liberty"
    libd.mkdir(parents=True)
    for nm in ("sky130_fd_sc_hd__ss_100C_1v40.lib",
               "sky130_fd_sc_hd__tt_025C_1v80.lib",
               "sky130_fd_sc_hd__ff_n40C_1v95.lib"):
        (libd / nm).write_text("library(x){}\n")
    got = R._resolve_signoff_corner_libs(tmp_path, _PdkStub(), "")
    assert set(got) == {"SS", "TT", "FF"}
    assert got["SS"].endswith("ss_100C_1v40.lib")
    assert got["FF"].endswith("ff_n40C_1v95.lib")


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
