"""v1.3.47 — antenna-repair ESCALATION: tool-native `repair_antennas -reroute`
+ escalating `-ratio_margin`, pinned here (chip/PDK-AGNOSTIC).

Motivation (ORGANIC #110): on a large, dense routed design (sha256, 26268-cell,
DRC-clean) the pre-v1.3.47 antenna loop (`repair_antennas -iterations 1` ->
`detailed_route`, no margin) leaves a small residual (3 net / 4 pin, met1
side-area) — the diode/jumper fix is computed on the global-route estimate and
the realizing reroute re-introduces a met1 side-area antenna the repair did not
foresee. The fix drives each outer turn through the fork's tool-native
`repair_antennas -reroute` (ONE repair pass + an incremental detailed_route of
ONLY the diode-dirty nets, via hasInitialRouting — a single-pass repair WITHOUT a
reroute silently deletes the diode-dirty net's wire so check_antennas reads a
false 0) with an ESCALATING `-ratio_margin` (0->40) that over-fixes to give
head-room against the reroute re-introduction, until check_antennas == 0 or the
cap. On a build without `-reroute` the catch falls back to the external
repair -> detailed_route pass (byte-compatible with the pre-fix loop).

These tests pin the emitted-TCL control logic + verdict on SYNTHETIC before/after
antenna reports (FAIL->PASS), so a blind run auto-covers the escalation.
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


def _cmd_lines(block: str) -> str:
    return "\n".join(
        ln for ln in block.splitlines() if not ln.lstrip().startswith("#"))


def _run_tclsh(script_text: str):
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "ant.tcl"
        p.write_text(script_text)
        return _pr.run([tclsh, str(p)],
                              capture_output=True, text=True)


# ── emitted-shape assertions ─────────────────────────────────────────────────

def test_block_uses_tool_native_reroute():
    """Each repair turn must PREFER `repair_antennas ... -reroute` (the fork's
    proven repair+incremental-reroute-in-one-call path)."""
    cmds = _cmd_lines(R._antenna_repair_tcl(_pdk()))
    assert "-reroute" in cmds
    assert "repair_antennas sky130_fd_sc_hd__diode_2 -iterations 1" in cmds


def test_block_prefers_route_jumpers_over_new_timing_loads():
    """A repair must not add a diode load to an IO pin whose Liberty limit is
    one; layer jumpers repair antenna ratio without reopening max-fanout."""
    cmds = _cmd_lines(R._antenna_repair_tcl(_pdk()))
    repair_lines = [line for line in cmds.splitlines()
                    if "repair_antennas " in line]
    assert len(repair_lines) == 2
    assert all("-jumper_only" in line for line in repair_lines)
    assert all("-diode_only" not in line for line in repair_lines)


def test_block_escalates_ratio_margin():
    """The margin must start at 0 and ESCALATE (over-fix head-room against the
    reroute re-introducing a residual)."""
    cmds = _cmd_lines(R._antenna_repair_tcl(_pdk()))
    assert "-ratio_margin" in cmds
    assert "_ant_margin" in cmds
    # escalation step present (grows the margin each turn)
    assert "$_ant_margin + 10" in cmds or "incr _ant_margin" in cmds


def test_block_keeps_incremental_outer_loop_and_no_global_route():
    """Still the bounded incremental OUTER loop; still NO full global_route
    (the ibex full-reroute timeout); external reroute kept as the fallback."""
    cmds = _cmd_lines(R._antenna_repair_tcl(_pdk()))
    assert "set _ant_cap" in cmds
    assert "for {set _i 0} {$_i < $_ant_cap} {incr _i}" in cmds
    assert "global_route" not in cmds
    assert "detailed_route -verbose 0" in cmds        # external fallback reroute
    assert "-iterations 5" not in cmds


def test_block_has_external_fallback_when_reroute_unsupported():
    """A build without `-reroute` must degrade to external repair -> reroute,
    not abort."""
    cmds = _cmd_lines(R._antenna_repair_tcl(_pdk()))
    assert "ANTENNA_NATIVE_REROUTE_NONFATAL" in cmds
    # the fallback external repair (no -reroute) + detailed_route both present
    assert "REPAIR_ANTENNA_NONFATAL" in cmds


def test_block_skips_when_pdk_has_no_diode():
    pdk = _pdk()
    pdk.antenna_diode_cell = None
    block = R._antenna_repair_tcl(pdk)
    assert "ANTENNA_REPAIR_SKIPPED" in block
    assert "repair_antennas" not in block


# ── control-logic proofs on SYNTHETIC before/after antenna reports ───────────

_SIM_HARNESS = """
set ::seq {%s}
set ::i 0
proc check_antennas {args} {
  set v [lindex $::seq $::i]
  if {$::i < [expr {[llength $::seq]-1}]} { incr ::i }
  return $v
}
proc repair_antennas {args} { %s }
proc detailed_route {args} { return "" }
"""


@needs_tclsh
def test_parse_eval_reaches_postroute_done():
    """Real Tcl parse/eval with every tool command stubbed reaches the terminal
    marker with returncode 0 (OpenROAD is a Tcl interpreter)."""
    script = 'proc unknown {args} { return "" }\n' + R._antenna_repair_tcl(_pdk())
    res = _run_tclsh(script)
    assert res.returncode == 0, res.stderr
    assert "missing close-bracket" not in res.stderr
    assert "ANTENNA_POSTROUTE_DONE" in res.stdout


@needs_tclsh
def test_native_reroute_path_converges_fail_to_pass():
    """FAIL->PASS via the tool-native `-reroute` path: check_antennas 21 -> 3
    -> 0 must emit ANTENNA_LOOP_CONVERGED (repair_antennas -reroute SUCCEEDS, so
    the external detailed_route is never needed)."""
    harness = _SIM_HARNESS % ("21 3 0", 'return ""')
    res = _run_tclsh(harness + R._antenna_repair_tcl(_pdk()))
    assert res.returncode == 0, res.stderr
    assert "ANTENNA_LOOP_CONVERGED" in res.stdout
    assert "ANTENNA_POSTROUTE_DONE" in res.stdout


@needs_tclsh
def test_fallback_path_converges_when_reroute_unsupported():
    """FAIL->PASS on a build WITHOUT `-reroute`: repair_antennas errors when it
    sees `-reroute`, so the external repair->detailed_route fallback fires and
    the loop still converges 21 -> 3 -> 0."""
    repair_body = ('if {[lsearch $args -reroute] >= 0} '
                   '{ error "unknown option -reroute" }\n  return ""')
    harness = _SIM_HARNESS % ("21 3 0", repair_body)
    res = _run_tclsh(harness + R._antenna_repair_tcl(_pdk()))
    assert res.returncode == 0, res.stderr
    assert "ANTENNA_NATIVE_REROUTE_NONFATAL" in res.stdout   # fallback engaged
    assert "ANTENNA_LOOP_CONVERGED" in res.stdout            # still converges
    assert "ANTENNA_POSTROUTE_DONE" in res.stdout


@needs_tclsh
def test_no_false_convergence_when_residual_never_clears():
    """HONESTY: if the antenna count NEVER reaches 0, the loop must NOT emit
    ANTENNA_LOOP_CONVERGED — it runs the cap and leaves the authoritative check
    to report the residual (no masking)."""
    harness = _SIM_HARNESS % ("7 7 7 7 7 7 7 7", 'return ""')
    res = _run_tclsh(harness + R._antenna_repair_tcl(_pdk()))
    assert res.returncode == 0, res.stderr
    assert "ANTENNA_LOOP_CONVERGED" not in res.stdout
    assert "ANTENNA_POSTROUTE_DONE" in res.stdout


@needs_tclsh
def test_margin_escalates_across_turns():
    """The emitted REPAIR_ANTENNA_DONE trace must show the margin GROWING across
    turns (0,10,20,...) when the residual persists."""
    harness = _SIM_HARNESS % ("9 9 9 9 9 9 9 9", 'return ""')
    res = _run_tclsh(harness + R._antenna_repair_tcl(_pdk()))
    assert "margin=0" in res.stdout
    assert "margin=10" in res.stdout
    assert "margin=20" in res.stdout
