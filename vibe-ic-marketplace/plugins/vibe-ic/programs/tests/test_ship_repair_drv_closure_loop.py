"""ORGANIC (post-v1.5.60 interaction) — #527's SHIPPED post-route real-SPEF
repair (`_ship_signoff_spef_repair_tcl`) called `repair_design` /
`repair_timing -setup` exactly ONCE before the v1.5.60 clear+reroute. OpenROAD's
own log shows `repair_design` is a GREEDY SINGLE-PASS resizer: it reports what
it FOUND at entry, not what remains when it returns, and one call is not
guaranteed to reach 0.

MEASURED (caravel_user_project x sky130A, v1.5.60): `signoff_spef_repair.log`
recorded `[INFO RSZ-0034] Found 111 slew violations.` /
`[INFO RSZ-0036] Found 30 capacitance violations.` / `Resized 89 instances.`
from the single call — leaving a residual that the promotion gate's own
non-negative-setup + DRC-clean checks (which do not evaluate max_cap/max_slew
at all) happily promoted as sign-off. Step 23 Post-route STA
(`sta_corner_record_completeness_check` on the real max-RC SPEF sign-off
corner) then reported 2 max_slew + 2 max_capacitance VIOLATED entries on the
SHIPPED route.

Fix: repair_design/repair_timing -setup + detailed_placement are safe to call
repeatedly (unlike repair_antennas, which is one-shot per call) — each call
re-measures the CURRENT design and fixes what's left. A bounded (5-iteration)
repeat, mirroring the antenna-repair loop already established in this same
file, converges the residual instead of shipping it.

This test proves the emitted Tcl (a) is syntactically valid (a real tclsh
parse/eval, per the #581 doctrine that content-only string assertions are
insufficient) and (b) actually contains a BOUNDED loop wrapping
repair_design/repair_timing/detailed_placement — not just one more hand-added
single call, which would not have converged the measured residual.
"""
import shutil
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")

_STUB = 'proc unknown {args} { return "" }\n'


def _run_tclsh(script_path: Path):
    return _pr.run([tclsh, str(script_path)],
                          capture_output=True, text=True)


def _emit(tmp_path: Path) -> str:
    return R._ship_signoff_spef_repair_tcl(
        top="chip_top",
        tech_lef_c=str(tmp_path / "tech.lef"),
        cell_lef_c=str(tmp_path / "cells.lef"),
        ss_liberty_c=str(tmp_path / "ss.lib"),
        pnr_dir_c=str(tmp_path / "pnr"),
        max_captable_c=str(tmp_path / "rules.magic"),
        metal_prefix="met",
        thread_count=4,
    )


# --------------------------------------------------------- structural -----

def test_repair_design_call_is_wrapped_in_a_bounded_loop():
    """A single extra `repair_design` call bolted on would not fix a design
    whose first pass leaves an arbitrary-sized residual — the fix must be a
    LOOP, bounded so it still terminates."""
    tcl = _emit(Path("/tmp"))
    assert "for {set _drv_i 0}" in tcl
    assert "$_drv_i < " in tcl
    # the loop body must contain the actual repair calls, not just the
    # loop scaffold with the repair left outside it
    loop_start = tcl.index("for {set _drv_i 0}")
    loop_end = tcl.index("\n}\n", loop_start)
    body = tcl[loop_start:loop_end]
    assert "repair_design" in body
    assert "repair_timing -setup" in body
    assert "detailed_placement" in body


def test_loop_runs_before_the_routing_clear_and_reroute():
    """The repair must converge BEFORE the guide-clearing reroute (v1.5.60),
    not after — reordering would ship an unrepaired route again."""
    tcl = _emit(Path("/tmp"))
    loop_pos = tcl.index("for {set _drv_i 0}")
    clear_pos = tcl.index("SHIP_ROUTING_CLEARED")
    reroute_pos = tcl.index("global_route} e]} { puts \"SHIP_GR_NONFATAL")
    assert loop_pos < clear_pos < reroute_pos


def test_loop_still_measures_wns_before_and_after():
    """The existing WNS-before/after markers `_parse_ship_repair_log` and the
    promotion gate depend on must survive the refactor untouched."""
    tcl = _emit(Path("/tmp"))
    assert "SHIP_WNS_BEFORE" in tcl
    assert "SHIP_WNS_AFTER_REPAIR" in tcl
    assert tcl.index("SHIP_WNS_BEFORE") < tcl.index("for {set _drv_i 0}")
    assert tcl.index("for {set _drv_i 0}") < tcl.index("SHIP_WNS_AFTER_REPAIR")


# ----------------------------------------------------------- tclsh -----

@needs_tclsh
def test_full_ship_repair_tcl_parses_and_evaluates_in_tclsh(tmp_path):
    """The named defect end-state check: OpenROAD (a Tcl interpreter) must
    reach the END of the emitted script. tclsh with every tool command
    stubbed exercises the identical parser."""
    tcl = _emit(tmp_path)
    script = tmp_path / "ship_repair.tcl"
    script.write_text(_STUB + tcl + "\nputs SHIP_REPAIR_TCL_END\n")
    result = _run_tclsh(script)
    assert result.returncode == 0, result.stderr
    assert "missing close-bracket" not in result.stderr
    assert "SHIP_REPAIR_TCL_END" in result.stdout


@needs_tclsh
def test_loop_body_actually_executes_bounded_iterations(tmp_path):
    """Instrument `repair_design` to count invocations — the loop must call
    it more than once (proving the fix is a real repeat, not scaffolding
    that never executes) and stop at the bound (5)."""
    tcl = _emit(tmp_path)
    counting_stub = (
        _STUB +
        "set ::repair_design_calls 0\n"
        "proc repair_design {args} { incr ::repair_design_calls }\n"
        "proc detailed_placement {args} {}\n"
        "proc repair_timing {args} {}\n"
    )
    script = tmp_path / "ship_repair.tcl"
    script.write_text(
        counting_stub + tcl +
        "\nputs \"REPAIR_DESIGN_CALLS: $::repair_design_calls\"\n")
    result = _run_tclsh(script)
    assert result.returncode == 0, result.stderr
    line = [ln for ln in result.stdout.splitlines()
            if ln.startswith("REPAIR_DESIGN_CALLS:")][0]
    calls = int(line.split(":")[1].strip())
    assert calls == 5, f"expected the bounded loop cap (5), got {calls}"
