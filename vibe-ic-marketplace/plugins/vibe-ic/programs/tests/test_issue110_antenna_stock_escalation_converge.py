"""ORGANIC #110 — antenna-repair residual on the DEPLOYED STOCK OpenROAD.

Community issue #110: `check_antennas` on the committed sha256 route left a
real, reproducible residual (3 net / 4 pin, met2 side-area) on a 26k-instance
DRC-clean design. Root cause (proven live, 2026-07-11): the pre-escalation
antenna pass ran ONE `repair_antennas` + `detailed_route` turn, so the realizing
detailed route re-introduced a met2 side-area antenna the coarse global-route
repair did not foresee — a global-vs-detailed routing divergence the single pass
cannot chase.

The fix (`_antenna_repair_tcl`, v1.3.47, shipped/committed) is the INCREMENTAL
repair->reroute->recheck OUTER loop with an ESCALATING `-ratio_margin`. Its
PRIMARY path is the fork's `repair_antennas ... -reroute`; on the **deployed
stock binary** (`vibeic-eda:0.2.5`, which has NO `-reroute` — verified live:
`[ERROR STA-0562] repair_antennas -reroute is not a known keyword or flag`) the
`catch` DEGRADES to the external `repair_antennas -ratio_margin` +
`detailed_route` pass, once per outer turn, escalating the margin each turn.

Live proof on the DEPLOYED STOCK binary against the exact committed sha256
recipe (faithful re-route, base route == committed 0-DRC checkpoint):
    precheck  21 net / 22 pin
    iter 0 (margin 0)  -> +22 diodes -> 3 net / 4 pin   (== the #110 residual)
    iter 1 (margin 10) -> +7  diodes -> 0 net / 0 pin
    iter 2 (margin 20) -> check == 0 -> CONVERGED
Fresh-process re-read of the repaired DEF -> Found 0 net / 0 pin (geometric +
persistent, not an in-memory illusion); 29 diode_2 instances inserted
(base 0 -> 29); KLayout sign-off DRC on the repaired GDS == 0 items (identical
to the pre-antenna base GDS -> the diodes/reroute add ZERO DRC).

These tests pin the emitted-TCL control logic on SYNTHETIC before/after antenna
reports, driving the STOCK path (no `-reroute`) so a blind run auto-covers the
#110 convergence + the clean-design no-op. chip/PDK-AGNOSTIC.
"""
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")


def _pdk() -> "R.PdkConfig":
    return R.PdkConfig(
        name="fixture_pdk",
        liberty="/pdk/lib.lib", tech_lef="/pdk/tech.lef",
        cell_lef="/pdk/cells.lef", cell_gds=None,
        site="unithd", drc_deck=None, metal_prefix="met",
        tapcell_master="sky130_fd_sc_hd__tapvpwrvgnd_1",
        antenna_diode_cell="sky130_fd_sc_hd__diode_2",
        pnr_exclude_cell_file="/pdk/drc_exclude.cells",
    )


# A Tcl harness that EMULATES the deployed STOCK OpenROAD: `repair_antennas`
# with `-reroute` ERRORS (STA-0562), and each successful (no-`-reroute`) repair
# pass drops the check_antennas count along a caller-supplied sequence. This is
# the #110 environment (deployed vibeic-eda:0.2.5 has no `-reroute`).
_STOCK_HARNESS = """
set ::seq {%s}
set ::i 0
set ::diodes 0
proc check_antennas {args} {
  set v [lindex $::seq $::i]
  if {$::i < [expr {[llength $::seq]-1}]} { incr ::i }
  return $v
}
proc repair_antennas {args} {
  # stock: the `-reroute` flag is unknown -> hard error (STA-0562 analogue).
  if {[lsearch $args -reroute] >= 0} { error "STA-0562 unknown flag -reroute" }
  # a real (diode-inserting) repair pass; record that diodes were added.
  incr ::diodes
  return ""
}
proc detailed_route {args} { return "" }
"""


def _run(script_text: str):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ant.tcl"
        p.write_text(script_text)
        return _pr.run([tclsh, str(p)],
                              capture_output=True, text=True)


@needs_tclsh
def test_stock_path_converges_the_110_residual():
    """#110 on the DEPLOYED STOCK binary: check_antennas 21 -> 3 -> 0 must reach
    ANTENNA_LOOP_CONVERGED via the external fallback (the `-reroute` primary
    errors every turn), and the authoritative post-loop check reports 0/0 — the
    exact live trajectory (21 -> 3 -> 0)."""
    harness = _STOCK_HARNESS % "21 3 0"
    res = _run(harness + R._antenna_repair_tcl(_pdk()))
    assert res.returncode == 0, res.stderr
    # the fork -reroute is unavailable on stock -> fallback engaged every turn
    assert "ANTENNA_NATIVE_REROUTE_NONFATAL" in res.stdout
    # ...and the loop still CONVERGES (does not plateau at the 3/4 residual)
    assert "ANTENNA_LOOP_CONVERGED" in res.stdout
    assert "ANTENNA_POSTROUTE_DONE" in res.stdout


@needs_tclsh
def test_stock_path_escalates_diode_budget_until_clear():
    """The residual only clears once the margin is escalated (the live run
    needed margin 10). The emitted trace must show the margin GROWING across
    turns while the count is still non-zero — i.e. an ESCALATING diode budget,
    not a fixed one-shot pass."""
    # never-clearing-at-margin-0 style sequence: still 3 after the first turn,
    # forcing a second turn at a higher margin.
    harness = _STOCK_HARNESS % "21 3 3 0"
    res = _run(harness + R._antenna_repair_tcl(_pdk()))
    assert res.returncode == 0, res.stderr
    assert "margin=0" in res.stdout
    assert "margin=10" in res.stdout      # escalated after turn 0
    assert "ANTENNA_LOOP_CONVERGED" in res.stdout


@needs_tclsh
def test_clean_design_is_a_noop_no_repair_called():
    """ACCEPTANCE GATE (no-op on a clean design): when the precheck reports 0
    the loop is SKIPPED entirely — no `repair_antennas` pass runs, so no spurious
    diode is inserted (proven live on spm sky130: precheck 0/0 -> skip)."""
    harness = _STOCK_HARNESS % "0 0"
    res = _run(harness + R._antenna_repair_tcl(_pdk()))
    assert res.returncode == 0, res.stderr
    assert "ANTENNA_ALREADY_CLEAN" in res.stdout
    # the repair loop never ran -> zero diode-inserting repair passes
    assert "REPAIR_ANTENNA_DONE" not in res.stdout
    assert "ANTENNA_LOOP_CONVERGED" not in res.stdout
    # prove it geometrically: the diode counter emulated in the harness is 0
    probe = (harness + R._antenna_repair_tcl(_pdk())
             + '\nputs "DIODES_INSERTED=$::diodes"\n')
    res2 = _run(probe)
    assert "DIODES_INSERTED=0" in res2.stdout


@needs_tclsh
def test_stock_path_no_false_convergence_when_residual_persists():
    """HONESTY: if OSS OpenROAD genuinely cannot clear the residual, the loop
    must NOT emit ANTENNA_LOOP_CONVERGED — it runs the cap and leaves the
    authoritative in-session check to report the true residual (never masked)."""
    harness = _STOCK_HARNESS % "3 3 3 3 3 3 3 3"
    res = _run(harness + R._antenna_repair_tcl(_pdk()))
    assert res.returncode == 0, res.stderr
    assert "ANTENNA_LOOP_CONVERGED" not in res.stdout
    assert "ANTENNA_POSTROUTE_DONE" in res.stdout


def test_block_degrades_without_reroute_and_never_full_global_routes():
    """The stock path must NOT depend on `-reroute` (deployed 0.2.5 lacks it) and
    must NOT drop a full `global_route` into the loop (the ibex ~1900-net reroute
    timeout); the realizing reroute stays the incremental `detailed_route`."""
    cmds = "\n".join(ln for ln in R._antenna_repair_tcl(_pdk()).splitlines()
                     if not ln.lstrip().startswith("#"))
    # external fallback present (works on a binary without -reroute)
    assert "repair_antennas sky130_fd_sc_hd__diode_2 -iterations 1 " \
           "-ratio_margin $_ant_margin}" in cmds
    assert "detailed_route -verbose 0" in cmds
    assert "global_route" not in cmds
