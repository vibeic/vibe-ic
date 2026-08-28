"""#603 — POST-REROUTE real-SPEF convergence for the SHIPPED signoff repair.

ROOT CAUSE (measured, sha256 x sky130A, ss_100C_1v60 max-RC SPEF): the shipped
`_ship_signoff_spef_repair_tcl` measured `SHIP_WNS_AFTER_REPAIR` on the
`set_wire_rc` wire-load estimate BEFORE the mandatory reroute — so a design the
estimate called +0.05 ns closed actually shipped -6.66 ns once the reroute
landed the inserted buffers/resized cells on the REAL routed parasitics the
sign-off judges (worst slew 1.5 ns estimate -> 7.7 ns real). Nothing
re-extracted + re-repaired against the post-reroute parasitics, and the
promotion gate trusted the optimistic pre-reroute number.

FIX: after the reroute, iterate extract(real max-RC SPEF)->repair->reroute
(bounded + plateau break, each reroute UNBOUNDED/DRC-converging like the base
route) and emit the HONEST post-reroute real-SPEF worst slack SHIP_WNS_POSTROUTE
the promotion gate keys on. MEASURED recovery on sha256 x sky130A: SS setup
-6.66 ns -> -2.32 ns (one pass), TNS -210 -> -24.6 ns, reroute DRC-clean; the
~-2.4 ns residual is a genuine slow-corner logic-depth floor (documented, NOT
fabricated closure). §4.05: the loop RECOVERS what is recoverable and the honest
residual still surfaces VIOLATED — it never masks the floor.

chip/PDK-AGNOSTIC: standard OpenROAD APIs + the active PDK's max captable.
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

def test_convergence_loop_present_and_after_the_reroute():
    """The re-extract+re-repair loop must run AFTER the base clear+reroute, so it
    operates on the REAL rerouted parasitics — not before, which would repeat the
    optimistic pre-reroute estimate."""
    tcl = _emit(Path("/tmp"))
    assert "for {set _cvg 0}" in tcl
    # base reroute (SHIP_ROUTING_CLEARED + global_route/detailed_route) first,
    # THEN the convergence loop, THEN the honest post-route measurement.
    assert tcl.index("SHIP_ROUTING_CLEARED") < tcl.index("for {set _cvg 0}")
    assert tcl.index("for {set _cvg 0}") < tcl.index('puts "SHIP_WNS_POSTROUTE:')


def test_loop_reextracts_real_spef_and_reroutes_each_pass():
    """Each pass must re-EXTRACT the real max-RC parasitics (not reuse the stale
    pre-reroute SPEF) and reroute to realize the repair — otherwise the real
    slews the sign-off judges never get fixed."""
    tcl = _emit(Path("/tmp"))
    start = tcl.index("for {set _cvg 0}")
    end = tcl.index('puts "SHIP_WNS_POSTROUTE:')
    body = tcl[start:end]
    assert "extract_parasitics -ext_model_file" in body
    assert "repair_design" in body
    assert "repair_timing -setup" in body
    assert "global_route" in body
    assert "detailed_route" in body
    # bounded + terminating: closure break AND plateau break
    assert "SHIP_CVG_CLOSED" in body
    assert "SHIP_CVG_PLATEAU" in body


def test_postroute_marker_is_the_final_real_spef_measure():
    """SHIP_WNS_POSTROUTE must be emitted AFTER a final real-SPEF read, so it
    reflects the shipped route's real parasitics — the number the sign-off
    independently re-derives."""
    tcl = _emit(Path("/tmp"))
    pr = tcl.index('puts "SHIP_WNS_POSTROUTE:')
    # a read_spef of the extracted max-RC SPEF precedes the final measurement
    assert tcl.rindex("read_spef", 0, pr) > tcl.index("for {set _cvg 0}")


# ---------------------------------------------------------- parse/gate -----

def test_parse_extracts_wns_postroute():
    log = ("SHIP_WNS_BEFORE: -19.85\nSHIP_WNS_AFTER_REPAIR: 0.045\n"
           "SHIP_WNS_CVG_PASS0: -6.66\nSHIP_WNS_CVG_PASS1: -2.32\n"
           "SHIP_WNS_POSTROUTE: -2.42\nNumber of violations = 0\n"
           "Found 436 slew violations.\nFound 126 slew violations.\n"
           "SHIP_SIGNOFF_REPAIR_DONE\n")
    p = R._parse_ship_repair_log(log)
    assert p["wns_postroute"] == -2.42
    assert p["wns_before"] == -19.85


def test_gate_promotes_honest_improvement_over_base():
    """An honest post-reroute -2.42 ns that is a huge improvement over the base
    -19.85 ns, DRC-clean + DRV-non-regressing, still PROMOTES (never ship the
    worse un-repaired base)."""
    p = R._parse_ship_repair_log(
        "SHIP_WNS_BEFORE: -19.85\nSHIP_WNS_AFTER_REPAIR: 0.045\n"
        "SHIP_WNS_POSTROUTE: -2.42\nNumber of violations = 0\n"
        "Found 436 slew violations.\nFound 126 slew violations.\n")
    assert R._ship_repair_should_promote(p, True, True) is True


def test_gate_refuses_real_timing_regression_vs_base():
    """The new no-regression guard: even with an optimistic +0.05 pre-reroute
    estimate + DRC-clean, a post-reroute real slack WORSE than the base route is
    NOT promoted (keeps the base — never ship a real regression)."""
    p = R._parse_ship_repair_log(
        "SHIP_WNS_BEFORE: -3.0\nSHIP_WNS_AFTER_REPAIR: 0.05\n"
        "SHIP_WNS_POSTROUTE: -9.0\nNumber of violations = 0\n")
    assert R._ship_repair_should_promote(p, True, True) is False


def test_gate_backward_compatible_when_no_postroute_marker():
    """Older/stubbed logs without SHIP_WNS_POSTROUTE keep the pre-reroute
    closure gate exactly (the new guard is skipped when the marker is absent)."""
    p = {"wns_after_repair": 2.0, "route_violations": 0}
    assert R._ship_repair_should_promote(p, True, True) is True
    p_fail = {"wns_after_repair": -1.0, "route_violations": 0}
    assert R._ship_repair_should_promote(p_fail, True, True) is False


# ------------------------------------------------------------- tclsh -----

@needs_tclsh
def test_convergence_loop_parses_and_bounds_iterations(tmp_path):
    """The emitted convergence loop must be valid Tcl AND terminate: with a
    NON-numeric worst_slack (tool hiccup / stub) it must break, never crash the
    `expr` in the plateau check (the exact bug this test would have caught)."""
    tcl = _emit(tmp_path)
    script = tmp_path / "s.tcl"
    script.write_text(_STUB + tcl + "\nputs SHIP_END\n")
    r = _pr.run([tclsh, str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "SHIP_END" in r.stdout
    assert "can't use empty string as operand" not in r.stderr


@needs_tclsh
def test_convergence_loop_iterates_when_slack_stays_negative(tmp_path):
    """With worst_slack stubbed to a fixed negative value the loop must repair
    more than once (real repeat) and stop at the bound — proving it is a bounded
    convergence loop, not scaffolding that never executes."""
    tcl = _emit(tmp_path)
    # `unknown` returns "" for every command not stubbed here (incl. the empty
    # net list, so the routing-clear foreach is a no-op). Only repair_design
    # (counted) and sta::worst_slack (a fixed negative) need real behaviour.
    stub = (
        _STUB +
        "set ::rd 0\n"
        "proc repair_design {args} { incr ::rd }\n"
        "namespace eval sta { proc worst_slack {args} { return -5.0 } }\n"
        # v1.8.43 — the reroute is now guarded by a design-signature no-op check
        # (a repair that changes NOTHING must not destroy and re-route 300+ nets
        # to ship an identical netlist; measured: doing so introduced 13 x m3.6
        # min-met3-area islands the base route did not have). Under the bare
        # `unknown`-returns-"" stub the design trivially never changes, so the
        # guard would correctly skip the loop and this test would be asserting
        # nothing. Give the stub a design that DOES change, which is the case
        # this test is about.
        "set ::ncall 0\n"
        "namespace eval ord {}\n"
        "proc ord::get_db_block {} { return ::BLK }\n"
        "proc ::BLK {m args} {\n"
        "  if {$m eq \"getInsts\"} {\n"
        "    incr ::ncall\n"
        "    if {$::ncall == 1} { return {::I1} } else { return {::I1 ::I2} }\n"
        "  }\n"
        "  return {}\n"
        "}\n"
        "proc ::I1 {m} { if {$m eq \"getName\"} { return a } else { return ::MA } }\n"
        "proc ::I2 {m} { if {$m eq \"getName\"} { return b } else { return ::MB } }\n"
        "proc ::MA {m} { return ma }\n"
        "proc ::MB {m} { return mb }\n"
    )
    script = tmp_path / "s2.tcl"
    script.write_text(stub + tcl + "\nputs \"RD_CALLS: $::rd\"\n")
    r = _pr.run([tclsh, str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("RD_CALLS:")][0]
    # >5: the pre-reroute loop (5) plus at least one convergence pass (5 more).
    assert int(line.split(":")[1]) > 5, r.stdout
    assert "SHIP_REPAIR_NOOP" not in r.stdout, (
        "the design signature changed, so the no-op guard must NOT fire")


@needs_tclsh
def test_noop_guard_skips_the_reroute_when_the_repair_changed_nothing(tmp_path):
    """v1.8.43 — a repair that resizes/inserts NOTHING must keep the base route.

    MEASURED (spm x sky130A): re-routing a logically identical netlist came back
    with 13 x `m3.6` min-met3-area islands the base route did not have, every one
    a met2->via2->met3->via3->met4 stack transition landing (0.1905 um^2 against
    the PDK's 0.24), and TritonRoute reported `Number of violations = 0` on that
    same route. A route is not free to re-roll."""
    tcl = _emit(tmp_path)
    stub = (
        _STUB +
        "set ::rd 0\n"
        "proc repair_design {args} { incr ::rd }\n"
        "namespace eval sta { proc worst_slack {args} { return -5.0 } }\n"
    )
    script = tmp_path / "s3.tcl"
    script.write_text(stub + tcl + "\nputs \"RD_CALLS: $::rd\"\n")
    r = _pr.run([tclsh, str(script)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "SHIP_REPAIR_NOOP: 1" in r.stdout, r.stdout
    line = [ln for ln in r.stdout.splitlines() if ln.startswith("RD_CALLS:")][0]
    assert int(line.split(":")[1]) == 5, (
        "only the pre-reroute repair loop may run; the convergence loop must be "
        "skipped entirely when the design did not change")
