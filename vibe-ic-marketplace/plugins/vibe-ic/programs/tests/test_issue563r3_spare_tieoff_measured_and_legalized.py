"""ORGANIC #563 round-3 — the tie-off never connected anything, and the
legalization that would have saved the run was unreachable.

Measured on spm x {sky130A, ihp-sg13g2, gf180mcuD}, plugin v1.8.37/v1.8.38.
`_build_spare_protection_tcl` marks every spare `dont_touch`; odb then REFUSES
to connect an iterm of a dont_touch instance:

    [ERROR ODB-0369] Attempt to connect iterm of dont_touch instance
                     spare_inverter_0

That RAISES, so on every run: (a) the tie-off connected zero sinks -- the DEF
carried `- spare_tielo ( spare_tielo_drv ZN ) + USE SIGNAL ;`, driver only --
and (b) the throw unwound past the `detailed_placement` that sat AFTER the
connect loop but INSIDE the same catch.

(b) is what made it expensive. `spare_tielo_drv` is placed at the first spare's
PRE-SNAP coordinates, so with no legalization it kept a raw integer-micron
location. On spm x gf180mcuD it landed at (13.00, 9.08) um against a 0.56 um
site and a 3.92 um row pitch with ROW_0 at y=11.76: off-grid in X (5.214 sites)
and BELOW row 0, i.e. outside the core. All six real spares WERE snapped by the
`detailed_placement` between the two fragments; exactly one instance was
illegal, and OpenROAD reported exactly one:

    [WARNING DPL-0006] Site aligned check failed (1).
    [ERROR DPL-0033] detailed placement checks failed during check placement.
    [ERROR DPL-0701] NegotiationLegalizer did not fully converge. (x9)
    [ERROR DRT-0073] No access point for <inst>/I  (x46)
    [INFO  RCX-0134] Can't execute write_spef command. There's no extraction
                     data.

Zero SPEF -> post-route STA silently fell back to netlist-only -> SS setup
reported -8.81 ns / TNS -106.34 and the campaign recorded a TIMING failure six
steps downstream of a placement defect. Controls at the same corner, clock and
netlist: v1.5.65 +1.73 ns and v1.5.79 +1.77 ns, both WITH SPEF.

Two things are pinned here, and the second matters more than the first:

1. `tied_off` is MEASURED from OpenROAD's log, not claimed before it runs. The
   pre-fix value was `bool(tie_cell_discovered and instances)` -- the mere
   EXISTENCE of a tie cell in the PDK liberty -- and `spare_cell_coverage_check`
   gates on it, so the gate read an intention while zero sinks were connected.
   Note that #563 round-2's own docstring already claimed it had made this flag
   "an honest claim (was constant True with no backing TCL)". It had written the
   TCL; the TCL threw. A flag is not honest because a fix intended it to be.

2. The legalization does not share a catch with the connect. THE GENERAL LESSON:
   a recovery step placed downstream of a fragile step inside ONE catch is a
   recovery that does not run precisely when it is needed. `test_legalization_*`
   below fails against the pre-fix ordering, which is what makes it a control
   rather than a description.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


_PLAN = {
    "count": 2,
    "instances": [
        {"name": "spare_inverter_0", "cell": "sky130_fd_sc_hd__inv_1",
         "type": "inverter", "llx": 13, "lly": 13},
        {"name": "spare_dff_0", "cell": "sky130_fd_sc_hd__dfrtp_4",
         "type": "dff", "llx": 14, "lly": 62},
    ],
}




# --------------------------------------------------------------------------
# 1. The structural fix: legalization must be OUTSIDE the tie-off catch.
# --------------------------------------------------------------------------











# --------------------------------------------------------------------------
# 2. The measurement: fail-closed in both directions.
# --------------------------------------------------------------------------



















# --------------------------------------------------------------------------
# 3. Regression control against the REAL failing log.
# --------------------------------------------------------------------------

_REAL_GF180_LOG = """\
[INFO DPL-0001] Placement Analysis
[ERROR ODB-0369] Attempt to connect iterm of dont_touch instance spare_inverter_0
SPARE_TIEOFF_NONFATAL: ODB-0369
SPARE_FIRM_LOCKED: 6 instances
[WARNING DPL-0006] Site aligned check failed (1).
[ERROR DPL-0033] detailed placement checks failed during check placement.
SPARE_CHECK_PLACEMENT_WARN: DPL-0033
[ERROR DPL-0701] NegotiationLegalizer did not fully converge. Violations remain: 1
[ERROR DRT-0073] No access point for clkload1/I (gf180mcu_fd_sc_mcu7t5v0__clkinv_1).
[INFO RCX-0435] Reading extraction model file rules.openrcx.nom.magic ...
[INFO RCX-0134] Can't execute write_spef command. There's no extraction data.
"""








# --------------------------------------------------------------------------
# 4. Unchanged behaviour when the PDK exposes no tie cell.
# --------------------------------------------------------------------------



# --------------------------------------------------------------------------
# 5. The SPEF stance stops blaming the PDK for our own upstream failure.
#
# The same run that produced the log above wrote
# `multi_corner_spef_stance.json` saying "this PDK did not ship the min/max
# OpenRCX captables, so setup and hold share the nominal-RC SPEF. HONEST
# limitation, not a claim of corner coverage." Both halves are false: the run's
# own log NAMES the captables it read, a sibling version extracted max+min+nom
# from that same PDK, and ZERO SPEF files existed so nothing "shared" a
# nominal-RC SPEF. The `else` fired on any corner_count < 2 -- including 0 --
# and asserted a CAUSE the code never checked. A disclosure phrased as candour
# is read as MORE trustworthy, which is exactly why it must not attribute our
# own failure to the environment.
# --------------------------------------------------------------------------

def test_spef_stance_reports_observation_and_names_no_cause():
    src = Path(R.__file__).read_text()
    i = src.index('"signoff_dimension": "multi_corner_spef"')
    # Scope to the EMITTED expression: the history comment above it quotes the
    # old PDK-blaming sentence on purpose, and a test that forbade the literal
    # anywhere in the file would forbid documenting the fix.
    emitted = src[src.index('"disclosure": (', i):][:2500]
    assert "did not ship the min/max" not in emitted, (
        "the disclosure still blames the PDK for a cause it never checked")
    assert "NOT attributed to the PDK" in emitted
    assert "NO SPEF EXTRACTED" in emitted, (
        "corner_count == 0 needs its own branch — the old text claimed setup "
        "and hold 'share the nominal-RC SPEF' when no SPEF existed at all")
