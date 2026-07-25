"""ORGANIC (post-v1.5.61 residual) — caravel_user_project x sky130A's Step 23
sign-off STA still showed SEVERE (multi-ns) max_slew/max_capacitance VIOLATED
entries after v1.5.61's bounded repair_design/repair_timing/detailed_placement
loop plateaued at 36 slew + 30 capacitance violations, unchanged across 4
further calls in the SAME session (`Resized: 0, Buffers: 0` every time after
the first).

TWO independent defects, both fixed here:

1. REPORT HONESTY (`report_check_types` without `-violators`): OpenSTA prints
   only the SINGLE WORST offending pin per check type, so a design with 271
   real violating pins produced a sign-off report showing exactly 4
   "VIOLATED" lines — reading as a couple of marginal misses when the true
   population is two orders of magnitude larger. `-violators` (bounded by
   `-max_count`) prints the complete list. The pass/fail verdict was never
   wrong (the sign-off gate keys on the mere presence of the word VIOLATED),
   but the report structurally could not show the true scope.

2. DRV CLOSURE (root cause, traced on the real netlist): the plateaued
   population is WIRE-LENGTH dominated, not fanout dominated — e.g. wire152
   (already the LARGEST clkbuf/buf cell in sky130_fd_sc_hd) drives a net whose
   ONLY load sits ~2mm away on a harness-fixed, 0.2%-utilization die
   (`FP_SIZING = absolute`, Caravel-mandated; the die cannot be shrunk).
   `repair_design` invoked with NO `-max_wire_length` (the pre-existing
   invocation) never attempts mid-wire repeater insertion for this
   population — its OWN transcript logs `Buffers: 0` on every call. Passing
   `-max_wire_length` (the standard, documented OpenROAD mechanism for
   exactly this case) is measured to close a large fraction of the residual.
   Because this mechanism is NOT uniformly safe (a naive application can
   regress the REAL post-reroute violator count even when the in-session
   estimate looks fine — measured on this same design), it ships as a
   SEPARATE, independently re-measured, fail-safe-gated step: promote ONLY
   when a freshly measured (real, post-reroute) violator count is STRICTLY
   LOWER than before, never on the in-session estimate alone.

This test proves (a) the report-honesty flag is present on every
`report_check_types` call site, (b) the escalation Tcl is syntactically valid
(a real tclsh parse/eval) and contains the bounded round loop wrapping
`repair_design -max_wire_length`, and (c) the pure-Python parse/promote gates
correctly reject a session whose measured violator count went UP or whose
setup/DRC did not hold, matching the §4.05 "never fabricate a PASS" doctrine.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

tclsh = shutil.which("tclsh")
needs_tclsh = pytest.mark.skipif(tclsh is None, reason="tclsh not installed")

_STUB = 'proc unknown {args} { return "" }\n'

# Full OpenROAD/ODB/STA stub set for the escalation Tcl: the real script
# queries die geometry (ord::get_db_tech / ord::get_db_block / dbBlock /
# dbTech / dbRect accessors) before it ever reaches repair_design, so a
# tclsh-only smoke test needs these bound to something concrete (a
# 2920x3520 um die, matching caravel_user_project's harness-fixed floorplan,
# DBU=1000/um) — NOT just the catch-all `unknown` stub, which only fires for
# undefined COMMANDS, not for calling a method on an undefined object.
_OPENROAD_STUB = (
    _STUB +
    "proc detailed_placement {args} {}\n"
    "proc repair_timing {args} {}\n"
    "proc global_route {args} {}\n"
    "proc detailed_route {args} {}\n"
    "proc extract_parasitics {args} {}\n"
    "proc write_spef {args} {}\n"
    "proc read_spef {args} {}\n"
    "proc estimate_parasitics {args} {}\n"
    "proc write_def {args} {}\n"
    "proc write_verilog {args} {}\n"
    "proc set_timing_derate {args} {}\n"
    "proc define_process_corner {args} {}\n"
    "proc remove_fillers {args} {}\n"
    "proc set_wire_rc {args} {}\n"
    "proc report_check_types {args} {}\n"
    "namespace eval sta { proc worst_slack {args} { return 1.0 } }\n"
    "namespace eval odb { proc dbWire_destroy {args} {} }\n"
    "namespace eval ord {\n"
    "  proc get_db_tech {} { return _tech }\n"
    "  proc get_db_block {} { return _block }\n"
    "}\n"
    "proc _tech {cmd} { return 1000 }\n"
    "proc _block {cmd args} {\n"
    "  if {$cmd eq \"getDieArea\"} { return _die }\n"
    "  if {$cmd eq \"getNets\"} { return {} }\n"
    "  return {}\n"
    "}\n"
    "proc _die {cmd} {\n"
    "  switch $cmd { xMax {return 2920000} xMin {return 0} "
    "yMax {return 3520000} yMin {return 0} }\n"
    "}\n"
)


def _run_tclsh(script_path: Path):
    return subprocess.run([tclsh, str(script_path)],
                          capture_output=True, text=True, timeout=60)


def _emit_escalation(tmp_path: Path) -> str:
    return R._ship_wire_length_escalation_tcl(
        top="chip_top",
        tech_lef_c=str(tmp_path / "tech.lef"),
        cell_lef_c=str(tmp_path / "cells.lef"),
        ss_liberty_c=str(tmp_path / "ss.lib"),
        pnr_dir_c=str(tmp_path / "pnr"),
        max_captable_c=str(tmp_path / "rules.magic"),
        metal_prefix="met",
        thread_count=4,
    )


# ----------------------------------------------- report honesty (FIX 1) ---

def test_report_check_types_requests_violators_not_just_the_worst():
    """MEASURED regression this closes: without `-violators`, OpenSTA prints
    ONE pin per check type — caravel_user_project x sky130A showed 4
    "VIOLATED" lines in a report whose true population was 271 pins."""
    tcl = R._report_check_types_tcl("/tmp/rpt.txt")
    assert "-violators" in tcl
    assert "-max_count" in tcl
    # still requests every check type the rigor gate demands
    for flag in ("-recovery", "-removal", "-max_slew", "-min_pulse_width",
                 "-max_capacitance"):
        assert flag in tcl


def test_check_types_violators_count_is_bounded():
    """A pathological design must not blow the report file up unboundedly —
    `-max_count` caps it (chosen high enough to never truncate a real
    design's population; caravel_user_project's is <300)."""
    assert R._CHECK_TYPES_VIOLATORS_MAX_COUNT >= 300


# ------------------------------------------- DRV non-regression (FIX 2) ---

def test_parse_ship_repair_log_extracts_first_and_last_drv_counts():
    log = (
        "SHIP_WNS_BEFORE: 1.0\n"
        "[INFO RSZ-0034] Found 63 slew violations.\n"
        "[INFO RSZ-0036] Found 39 capacitance violations.\n"
        "[INFO RSZ-0034] Found 36 slew violations.\n"
        "[INFO RSZ-0036] Found 30 capacitance violations.\n"
        "SHIP_WNS_AFTER_REPAIR: 2.0\n"
        "[INFO DRT-0199]   Number of violations = 0.\n"
        "SHIP_SIGNOFF_REPAIR_DONE\n"
    )
    parsed = R._parse_ship_repair_log(log)
    assert parsed["drv_slew_before"] == 63
    assert parsed["drv_slew_after"] == 36
    assert parsed["drv_cap_before"] == 39
    assert parsed["drv_cap_after"] == 30


def test_promotion_gate_refuses_a_drv_regression():
    """MEASURED failure mode this closes: a session can look fine on setup
    WNS + DRC (the ONLY two things the pre-fix gate checked) while the real
    slew/capacitance violator population got WORSE. One measured escalation
    variant went from 63 slew/39 cap to 71 slew/13 cap: better on cap, worse
    on slew — the pre-fix gate would have promoted this."""
    parsed = {
        "wns_after_repair": 2.0, "route_violations": 0,
        "drv_slew_before": 63, "drv_slew_after": 71,
        "drv_cap_before": 39, "drv_cap_after": 13,
    }
    assert R._ship_repair_should_promote(parsed, True, True) is False


def test_promotion_gate_still_allows_a_genuine_drv_improvement():
    parsed = {
        "wns_after_repair": 2.0, "route_violations": 0,
        "drv_slew_before": 63, "drv_slew_after": 10,
        "drv_cap_before": 39, "drv_cap_after": 5,
    }
    assert R._ship_repair_should_promote(parsed, True, True) is True


def test_promotion_gate_unchanged_when_drv_counts_are_unavailable():
    """Backward-compatible: designs/log shapes that predate the DRV markers
    (or a run where `Found N ... violations.` never printed) fall back to the
    pre-fix setup+DRC-only gate rather than refusing every promotion."""
    parsed = {"wns_after_repair": 2.0, "route_violations": 0}
    assert R._ship_repair_should_promote(parsed, True, True) is True


def test_promotion_gate_still_requires_drc_clean_and_nonneg_setup():
    bad_drc = {"wns_after_repair": 2.0, "route_violations": 3}
    assert R._ship_repair_should_promote(bad_drc, True, True) is False
    bad_setup = {"wns_after_repair": -0.5, "route_violations": 0}
    assert R._ship_repair_should_promote(bad_setup, True, True) is False


# --------------------------------------- escalation structure (FIX 3) -----

def test_escalation_wraps_repair_design_max_wire_length_in_a_bounded_loop():
    tcl = _emit_escalation(Path("/tmp"))
    assert "-max_wire_length" in tcl
    occurrences = len(re.findall(r"repair_design -max_wire_length",
                                 tcl))
    assert occurrences == R._DRV_ESCALATION_ROUNDS >= 2


def test_escalation_max_wire_length_is_derived_from_die_geometry_not_a_literal():
    """chip/PDK-AGNOSTIC: the repeater threshold must come from the design's
    OWN die geometry (queried via ord::get_db_block / getDbUnitsPerMicron),
    never a hardcoded per-chip micron literal."""
    tcl = _emit_escalation(Path("/tmp"))
    assert "getDieArea" in tcl
    assert "getDbUnitsPerMicron" in tcl
    assert "_esc_mwl" in tcl
    # the clamp bounds are present (sane floor/ceiling), not a single magic
    # constant substituted directly into the repair_design call
    assert "200" in tcl and "2000" in tcl


def test_escalation_measures_real_violators_before_and_after_not_just_estimate():
    """The gate must never trust the in-session estimate alone (measured:
    it can look fine while the real post-reroute state is worse) — it has to
    re-run a real check_types -violators pass both before the rounds start
    and after they finish."""
    tcl = _emit_escalation(Path("/tmp"))
    before_pos = tcl.index("SHIP_ESC_BEFORE_COUNT")
    rounds_start = tcl.index("repair_design -max_wire_length")
    after_pos = tcl.index("SHIP_ESC_AFTER_COUNT")
    assert before_pos < rounds_start < after_pos


def test_escalation_reroutes_for_real_every_round_not_just_once():
    """Each round must clear+reroute+re-extract BEFORE the next repair_design
    call — otherwise later rounds optimize against stale parasitics (the
    exact estimate-vs-real mismatch this whole mechanism exists to close)."""
    tcl = _emit_escalation(Path("/tmp"))
    assert tcl.count("SHIP_ESC_ROUTING_CLEARED") == R._DRV_ESCALATION_ROUNDS
    assert tcl.count("global_route") >= R._DRV_ESCALATION_ROUNDS
    assert tcl.count("detailed_route") >= R._DRV_ESCALATION_ROUNDS


def test_parse_ship_escalation_log_roundtrip():
    log = (
        "SHIP_ESC_MAX_WIRE_LENGTH: 973.33\n"
        "SHIP_ESC_BEFORE_COUNT: 271\n"
        "SHIP_ESC_WNS_BEFORE: 6.07\n"
        "[INFO DRT-0199]   Number of violations = 78.\n"
        "[INFO DRT-0199]   Number of violations = 0.\n"
        "SHIP_ESC_AFTER_COUNT: 59\n"
        "SHIP_ESC_WNS_AFTER: 9.5\n"
        "SHIP_ESC_DONE\n"
    )
    parsed = R._parse_ship_escalation_log(log)
    assert parsed == {
        "before_count": 271, "after_count": 59,
        "wns_before": 6.07, "wns_after": 9.5,
        "route_violations": 0, "max_wire_length": 973.33,
        "done": True,
    }


def test_escalation_promotion_gate_requires_strictly_fewer_real_violators():
    better = {"route_violations": 0, "wns_after": 9.5,
              "before_count": 271, "after_count": 59}
    assert R._ship_escalation_should_promote(better, True, True) is True

    worse = {"route_violations": 0, "wns_after": 9.5,
             "before_count": 271, "after_count": 967}
    assert R._ship_escalation_should_promote(worse, True, True) is False

    same = {"route_violations": 0, "wns_after": 9.5,
            "before_count": 271, "after_count": 271}
    assert R._ship_escalation_should_promote(same, True, True) is False


def test_escalation_promotion_gate_skips_on_missing_measurement():
    """§4.05: never guess. A count that failed to parse must refuse
    promotion, not default to "probably fine"."""
    parsed = {"route_violations": 0, "wns_after": 9.5,
              "before_count": None, "after_count": 59}
    assert R._ship_escalation_should_promote(parsed, True, True) is False


def test_escalation_promotion_gate_still_requires_drc_clean_and_setup():
    bad_drc = {"route_violations": 5, "wns_after": 9.5,
               "before_count": 271, "after_count": 59}
    assert R._ship_escalation_should_promote(bad_drc, True, True) is False
    bad_setup = {"route_violations": 0, "wns_after": -1.0,
                 "before_count": 271, "after_count": 59}
    assert R._ship_escalation_should_promote(bad_setup, True, True) is False


# ------------------------------------------------------------ tclsh -----

@needs_tclsh
def test_full_escalation_tcl_parses_and_evaluates_in_tclsh(tmp_path):
    tcl = _emit_escalation(tmp_path)
    script = tmp_path / "escalation.tcl"
    script.write_text(_OPENROAD_STUB + tcl + "\nputs SHIP_ESC_TCL_END\n")
    result = _run_tclsh(script)
    assert result.returncode == 0, result.stderr
    assert "missing close-bracket" not in result.stderr
    assert "SHIP_ESC_TCL_END" in result.stdout


@needs_tclsh
def test_escalation_loop_body_actually_executes_bounded_rounds(tmp_path):
    """Instrument `repair_design` to count invocations — the escalation must
    call it exactly `_DRV_ESCALATION_ROUNDS` times (a real bounded repeat,
    not scaffolding that never executes)."""
    tcl = _emit_escalation(tmp_path)
    counting_stub = (
        _OPENROAD_STUB +
        "set ::repair_design_calls 0\n"
        "proc repair_design {args} { incr ::repair_design_calls }\n"
    )
    script = tmp_path / "escalation.tcl"
    script.write_text(
        counting_stub + tcl +
        "\nputs \"REPAIR_DESIGN_CALLS: $::repair_design_calls\"\n")
    result = _run_tclsh(script)
    assert result.returncode == 0, result.stderr
    line = [ln for ln in result.stdout.splitlines()
            if ln.startswith("REPAIR_DESIGN_CALLS:")][0]
    calls = int(line.split(":")[1].strip())
    assert calls == R._DRV_ESCALATION_ROUNDS


# --------------- v1.5.65 post-mortem: spare-net-safe routing clear ----------
#
# NEGATIVE CONTROL: each test in this section MUST FAIL on the pre-fix code
# (where the routing clear loop destroyed ALL non-PG nets including spares)
# and PASS only after the spare-net-safe filter is applied. This is the
# load-bearing distinction between "a test that always passes" and "a test
# that proves the fix".

def test_spare_safe_routing_clear_tcl_contains_spare_filter():
    """The shared helper ``_spare_safe_routing_clear_tcl`` must emit a TCL
    fragment that SKIPS nets whose name contains ``spare`` (the tie-off nets
    created by ``_build_spare_postfix_tcl``) and nets touching a dont_touch
    instance. On the pre-fix code (no such helper), this test fails outright
    because the function does not exist."""
    tcl = R._spare_safe_routing_clear_tcl("TEST")
    assert "*spare*" in tcl, "spare-name glob missing"
    assert "isDoNotTouch" in tcl, "dont_touch instance check missing"
    assert "TEST_ROUTING_CLEARED" in tcl
    assert "spare_preserved" in tcl


def test_escalation_routing_clear_uses_spare_safe_helper():
    """The escalation TCL's reroute loop must contain the spare-net filter.
    On the pre-fix code, the reroute loop cleared ALL non-PG nets (no spare
    check) → this test would fail because ``*spare*`` never appears in the
    routing-clear section."""
    tcl = _emit_escalation(Path("/tmp"))
    # The routing-clear section must contain the spare filter markers
    assert "*spare*" in tcl, "escalation routing clear missing spare filter"
    assert "isDoNotTouch" in tcl, "escalation routing clear missing dnt check"
    assert "SHIP_ESC_ROUTING_CLEARED" in tcl
    assert "spare_preserved" in tcl


def test_postroute_convergence_tcl_uses_spare_safe_clear():
    """The convergence loop (raw-string template ``_SHIP_POSTROUTE_CVG_TCL``)
    must contain the spare-net filter. On the pre-fix code the convergence
    loop destroyed all non-PG wires unconditionally → this test would fail."""
    # The convergence template is a module-level constant assembled from
    # multiple string fragments; we access the emitted TCL through the
    # function that builds the full convergence script.
    import inspect
    src = inspect.getsource(R)
    # The convergence loop is a raw string template assigned to (or containing)
    # "SHIP_CVG_ROUTING_CLEARED". On the fix, it also contains the spare filter.
    assert "SHIP_CVG_ROUTING_CLEARED" in src
    assert "spare_preserved=$_skip" in src


def test_signoff_spef_repair_tcl_uses_spare_safe_clear():
    """``_ship_signoff_spef_repair_tcl`` must use ``_spare_safe_routing_clear_
    tcl`` (or inline an equivalent filter). On the pre-fix code, the function
    cleared all non-PG wires with no spare check → this test would fail."""
    import inspect
    src = inspect.getsource(R._ship_signoff_spef_repair_tcl)
    assert "_spare_safe_routing_clear_tcl" in src, \
        "signoff SPEF repair TCL does not call the spare-safe helper"


@needs_tclsh
def test_spare_safe_clear_parses_in_tclsh(tmp_path):
    """Syntax smoke test: the spare-safe routing clear TCL must parse
    without error in a real tclsh."""
    tcl = R._spare_safe_routing_clear_tcl("SMOKE")
    script = tmp_path / "spare_safe.tcl"
    script.write_text(_OPENROAD_STUB + tcl + "\nputs SPARE_SAFE_OK\n")
    result = _run_tclsh(script)
    assert result.returncode == 0, result.stderr
    assert "SPARE_SAFE_OK" in result.stdout


@needs_tclsh
def test_spare_safe_clear_skips_spare_nets_in_tclsh(tmp_path):
    """Functional test with a simulated ODB: create 3 net types (regular,
    spare-named, dont_touch-connected), run the spare-safe clear, verify
    that only the regular net's wire is destroyed."""
    tcl = R._spare_safe_routing_clear_tcl("FUNC")
    # Write the TCL simulation script directly to avoid Python→TCL escaping
    # issues with nested proc generation.
    script = tmp_path / "spare_func.tcl"
    script.write_text(
        # Wire-destroy tracker
        "namespace eval odb { proc dbWire_destroy {w} {"
        " lappend ::destroyed $w } }\n"
        "set ::destroyed {}\n"
        # ODB stubs
        "proc set_thread_count {args} {}\n"
        "proc read_lef {args} {}\n"
        "proc read_liberty {args} {}\n"
        "proc read_def {args} {}\n"
        "proc read_sdc {args} {}\n"
        # ord namespace
        "namespace eval ord {\n"
        "  proc get_db_tech {} { return _tech }\n"
        "  proc get_db_block {} { return _block }\n"
        "}\n"
        "proc _tech {cmd} { return 1000 }\n"
        # --- 3 mock nets: regular (clk), spare (spare_tielo), dont_touch (data) ---
        # Each net is a command that responds to getSigType/getName/getWire/getITerms
        "proc _net_clk {cmd args} {\n"
        "  switch $cmd {\n"
        "    getSigType { return SIGNAL }\n"
        "    getName { return clk }\n"
        "    getWire { return wire_clk }\n"
        "    getITerms { return {} }\n"
        "  }\n"
        "}\n"
        "proc _net_spare_tielo {cmd args} {\n"
        "  switch $cmd {\n"
        "    getSigType { return SIGNAL }\n"
        "    getName { return spare_tielo }\n"
        "    getWire { return wire_spare }\n"
        "    getITerms { return {} }\n"
        "  }\n"
        "}\n"
        # dont_touch net: iterm → inst → isDoNotTouch returns 1
        "proc _iterm_data {cmd args} {\n"
        "  switch $cmd { getInst { return _inst_data } }\n"
        "}\n"
        "proc _inst_data {cmd args} { return 1 }\n"
        "proc _net_data {cmd args} {\n"
        "  switch $cmd {\n"
        "    getSigType { return SIGNAL }\n"
        "    getName { return data }\n"
        "    getWire { return wire_data }\n"
        "    getITerms { return [list _iterm_data] }\n"
        "  }\n"
        "}\n"
        # _block returns our 3 nets
        "proc _block {cmd args} {\n"
        "  if {$cmd eq \"getDieArea\"} { return _die }\n"
        "  if {$cmd eq \"getNets\"} { return [list _net_clk _net_spare_tielo _net_data] }\n"
        "  return {}\n"
        "}\n"
        "proc _die {cmd} {\n"
        "  switch $cmd { xMax {return 2920000} xMin {return 0}"
        " yMax {return 3520000} yMin {return 0} }\n"
        "}\n"
        # Now run the spare-safe routing clear
        + tcl +
        "\nputs \"DESTROYED: $::destroyed\"\nputs FUNC_OK\n"
    )
    result = _run_tclsh(script)
    assert result.returncode == 0, f"tclsh failed: {result.stderr}"
    assert "FUNC_OK" in result.stdout
    # Only the regular net (clk) should have its wire destroyed
    destroyed_line = [ln for ln in result.stdout.splitlines()
                      if ln.startswith("DESTROYED:")][0]
    assert "wire_clk" in destroyed_line, \
        f"regular net wire not destroyed: {destroyed_line}"
    assert "wire_spare" not in destroyed_line, \
        f"spare net wire was destroyed: {destroyed_line}"
    assert "wire_data" not in destroyed_line, \
        f"dont_touch net wire was destroyed: {destroyed_line}"


# --------------- v1.5.65 post-mortem v2: escalation is re-enabled -----------

def test_escalation_step_is_not_disabled():
    """On the pre-fix code (v1.5.65), ``step_signoff_drv_wire_length_repair``
    starts with ``return None`` immediately after the docstring — this test
    MUST FAIL on that version and PASS only after the ``return None`` is
    removed. The function legitimately has ``return None`` in conditional
    branches (e.g. ``if not routed.is_file(): return None``); only a BARE
    ``return None`` as the FIRST executable statement is the disable pattern."""
    import ast
    import inspect
    src = inspect.getsource(R.step_signoff_drv_wire_length_repair)
    tree = ast.parse(src)
    func = tree.body[0]
    assert isinstance(func, ast.FunctionDef)
    # Skip the docstring (an ast.Expr(value=Constant) at position 0)
    body = func.body
    first_stmt_idx = 0
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)):
        first_stmt_idx = 1
    if first_stmt_idx < len(body):
        first_stmt = body[first_stmt_idx]
        if (isinstance(first_stmt, ast.Return)
                and isinstance(first_stmt.value, ast.Constant)
                and first_stmt.value.value is None):
            pytest.fail("step_signoff_drv_wire_length_repair is DISABLED "
                        "(starts with `return None` — the v1.5.65 pattern)")
