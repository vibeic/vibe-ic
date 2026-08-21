"""gf180mcuD chip-path campaign, 2026-08-20 — the post-route repair block
repaired and measured SETUP ONLY.

MEASURED, on a real chip: `subservient` on the wafer.space gf180mcuD `1x1`
slot routed with a hold violation of −67.9 ps at `max_ff_n40C_5v50` on four
pad-to-flop paths, and the flow's own `Checker.HoldViolations` refused the
run. Every manufacturability check (Magic DRC, KLayout DRC, LVS, antenna,
density, XOR) was clean; only hold failed.

The cause is a flow-shape gap, not a design bug, and it is chip-AGNOSTIC:

    _PNR_STAGE_ORDER = (..., "cts", "hold_repair",       <- hold, on ESTIMATED RC
                        "global_route", "detailed_route",
                        ..., "postroute_setup_repair_estimate")   <- setup only

Hold was settled BEFORE routing, on estimated wire delay, and the one block
that runs with REAL parasitics — `_postroute_repair_estimate_tcl` — asked only
`repair_timing -setup` and reported only `sta::worst_slack -max`. A post-route
hold violation was therefore neither repaired nor reported.

Any design with a pad-to-flop path has this exposure. A design that drives
every bidirectional pad as an output has none — which is exactly why the
control template and `spm` passed and would have hidden the defect.

These tests pin the HOLD half of the recipe. They do not weaken any check: the
block still runs after every shipped artifact and after the authoritative
sta.rpt, so it edits only the in-memory netlist.
"""
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402


def _tcl():
    # fork_repair_capable=True — the block is probe-gated and emits "" otherwise.
    return R._postroute_repair_estimate_tcl("/out", True)


def test_control_setup_repair_is_still_emitted():
    """CONTROL arm: the pre-existing setup half must be untouched, so a failure
    below is about hold and nothing else."""
    tcl = _tcl()
    assert "repair_timing -setup" in tcl
    assert "sta::worst_slack -max" in tcl
    assert "SPEF_REPAIR_WNS_BEFORE" in tcl
    assert "SPEF_REPAIR_WNS_AFTER" in tcl


def test_postroute_block_repairs_hold():
    """THE DEFECT: nothing after routing ever asked OpenROAD to fix hold."""
    tcl = _tcl()
    assert "repair_timing -hold" in tcl, (
        "the post-route repair block never runs `repair_timing -hold`, so a hold "
        "violation that only appears with real routing parasitics is never "
        "repaired — measured on a real gf180mcuD chip at -67.9 ps"
    )


def test_postroute_block_measures_hold_slack_both_sides():
    """A repair whose effect is not measured is not auditable. `-max` is setup;
    hold needs `-min`, before AND after."""
    tcl = _tcl()
    assert "sta::worst_slack -min" in tcl, (
        "hold slack (`sta::worst_slack -min`) is never reported by the "
        "post-route block, so a post-route hold violation is invisible here — "
        "UNMEASURED IS NOT ZERO"
    )
    assert "SPEF_REPAIR_HOLD_WNS_BEFORE" in tcl
    assert "SPEF_REPAIR_HOLD_WNS_AFTER" in tcl


def test_hold_repair_is_est0104_guarded_like_its_siblings():
    """The two existing repairs each carry the EST-0104 reseed recovery; a hold
    repair without it would be silently refused on exactly the runs that need
    it (the estimator arrives with a dirty parasitics set after the min-area
    patch and the PG reroute)."""
    tcl = _tcl()
    assert "SPEF_REPAIR_HOLD_EST0104_DETECTED" in tcl
    assert "_spef_repair_hold_est_rec" in tcl


def test_refusal_accounting_counts_three_repairs_not_two():
    """`_prr_refused >= 2` meant "both refused" when there were two repairs.
    With three, that threshold would call a round NOT_APPLIED in which the hold
    repair actually ran — an honest-reporting bug, not cosmetics."""
    tcl = _tcl()
    assert "$_prr_refused >= 3" in tcl
    assert "of 3 repairs refused" in tcl
    assert "$_prr_refused/3" in tcl
    assert "/2)" not in tcl, "the two-repair denominator survived somewhere"


def test_hold_addition_introduced_no_new_repair_design_call():
    """`repair_design` segfaults on a buffered gate config and `catch` cannot
    contain a segfault, so the hold addition must not add one.

    The block legitimately mentions `repair_design}` TWICE at the base
    revision — the guarded call plus its EST-0104 retry — so the assertion is
    that the count is UNCHANGED, not that it is one. Measured at the base
    revision before writing this number down:
        BASE repair_design} count = 2
    """
    tcl = _tcl()
    assert tcl.count("repair_design}") == 2, (
        "the hold addition changed the number of `repair_design` calls; it must "
        "add `repair_timing -hold` only"
    )
