"""R9 — the post-antenna DRV repair must RECOVER from EST-0104, not surrender.

WHAT THIS DEFENDS
-----------------
OpenROAD refuses `repair_design` / `repair_timing` with
`[ERROR EST-0104] inconsistent parasitics state` whenever the estimator's
`parasitics_invalid_` set is non-empty at the moment the incremental-parasitics
guard opens (src/est/src/EstimateParasitics.cpp, IncrementalParasiticsGuard
ctor). That set is filled by NETLIST edits (src/est/src/OdbCallBack.cpp:
inDbInstCreate / inDbNetCreate / inDbNetDestroy / inDbITermPostConnect /
inDbITermPostDisconnect / inDbInstSwapMasterAfter) and is cleared in exactly two
places: `updateParasitics()` (incremental mode only) and
`estimateWireParasitics()` — i.e. `estimate_parasitics -placement`.

Antenna repair inserts diodes ("[INFO GRT-0015] Inserted 28 diodes"), so every
repair the flow attempts AFTER antenna repair is refused. Measured on
caravel_user_project x sky130A: the post-antenna loop saw
`SDR_DRV_PASS1_BEFORE: 4` and then `SDR_REPAIR_NONFATAL: EST-0104` — it could
see the violations and was not permitted to fix them.

Measured, RUN not asserted, on the real design with REAL global routes present
so every flag was a legal call:
    no recovery                          -> EST-0104
    estimate_parasitics -global_routing  -> EST-0104   (command SUCCEEDS)
    estimate_parasitics -detailed_routing-> EST-0104   (command SUCCEEDS)
    estimate_parasitics -placement       -> repair OK
and, because the reseed calls `sta_->deleteParasitics()`, the sign-off SPEF
annotation must be restored BEFORE the retry: counting the tool's own
`(VIOLATED)` lines on the same design gave 3 (on SPEF) -> 0 (after reseed) ->
3 (after re-reading the SPEF). Repairing in the middle of that would optimise
the ~10x-optimistic tech-LEF model.

The tests below execute the emitted recovery under `tclsh` with the OpenROAD
commands stubbed, so what is checked is the fragment's BEHAVIOUR (which branch
runs, in which order, and what the caller is told), not its source text.
"""
import os
import shutil
import subprocess  # nosec - fixed argv, no shell
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import phase3_one_shot_runner as p3  # noqa: E402


def _emit(spef="/OUT/sdr_pass.spef", tag="SDR"):
    return p3._est0104_recovery_tcl(spef, "_sdr_rd", "MY_REPAIR", tag)


def _run_tcl(script: str) -> str:
    """Execute a Tcl script, return stdout. Skips if no tclsh on the box."""
    tclsh = shutil.which("tclsh") or shutil.which("tclsh8.6")
    if not tclsh:
        pytest.skip("no tclsh available to execute the emitted recovery")
    with tempfile.NamedTemporaryFile("w", suffix=".tcl", delete=False) as fh:
        fh.write(script)
        path = fh.name
    try:
        out = subprocess.run([tclsh, path], capture_output=True,  # nosec
                             text=True, timeout=60)
        return out.stdout + out.stderr
    finally:
        os.unlink(path)


_STUB_HEAD = """
# --- stubs standing in for the OpenROAD commands the recovery drives ---
set CALLS {}
proc estimate_parasitics {args} {
  global CALLS EP_FAILS
  lappend CALLS "estimate_parasitics $args"
  if {$EP_FAILS} { error "EST-0999 reseed refused" }
}
proc read_spef {f} {
  global CALLS RS_FAILS
  lappend CALLS "read_spef $f"
  if {$RS_FAILS} { error "SPEF-0001 unreadable" }
}
proc MY_REPAIR {args} {
  global CALLS RETRY_FAILS
  lappend CALLS "MY_REPAIR"
  if {$RETRY_FAILS} { error "EST-0104 still" }
}
"""


def _harness(err_text, *, ep_fails=0, rs_fails=0, retry_fails=0,
             spef_present=True):
    spef = "/tmp/r9_test_spef_present.spef" if spef_present \
        else "/tmp/r9_test_spef_absent_should_not_exist.spef"
    if spef_present:
        with open(spef, "w") as fh:
            fh.write("*SPEF\n")
    elif os.path.exists(spef):
        os.unlink(spef)
    body = p3._est0104_recovery_tcl(spef, "_sdr_rd", "MY_REPAIR", "SDR")
    return (
        _STUB_HEAD
        + f"set EP_FAILS {ep_fails}\nset RS_FAILS {rs_fails}\n"
        + f"set RETRY_FAILS {retry_fails}\n"
        + f"set _sdr_rd {{{err_text}}}\n"
        + body
        + '\nputs "RECOVERED=$_sdr_est_rec"\n'
          'puts "CALLS=[join $CALLS |]"\n'
    )


# --------------------------------------------------------------------------
# BEHAVIOUR: the happy path
# --------------------------------------------------------------------------

def test_est0104_is_recovered_and_the_caller_is_told_so():
    out = _run_tcl(_harness("EST-0104 inconsistent parasitics state"))
    assert "SDR_EST0104_DETECTED" in out, out
    assert "SDR_EST0104_RECOVERED" in out, out
    assert "RECOVERED=1" in out, out


def test_recovery_reseeds_with_placement_reannotates_then_retries_in_that_order():
    """The three steps and their ORDER are the property.

    -placement because it is the only estimate_parasitics flag that clears the
    estimator's invalid set (the other two were measured still failing); the
    re-read because the reseed destroys the SPEF annotation; the retry last.
    """
    out = _run_tcl(_harness("EST-0104 inconsistent parasitics state"))
    calls = [c for c in out.split("CALLS=")[1].strip().split("|")]
    assert len(calls) == 3, calls
    assert calls[0].startswith("estimate_parasitics "), calls
    assert "-placement" in calls[0], calls
    assert "-global_routing" not in calls[0], calls
    assert "-detailed_routing" not in calls[0], calls
    assert calls[1].startswith("read_spef "), calls
    assert calls[2] == "MY_REPAIR", calls


# --------------------------------------------------------------------------
# BEHAVIOUR: it must not fire on anything else, and must not hide failures
# --------------------------------------------------------------------------

def test_a_different_error_is_left_alone_for_the_caller_to_handle():
    out = _run_tcl(_harness("RSZ-0042 something else entirely"))
    assert "SDR_EST0104_DETECTED" not in out, out
    assert "RECOVERED=0" in out, out
    assert "CALLS=" in out and out.split("CALLS=")[1].strip() == "", out


@pytest.mark.parametrize("kw,marker", [
    (dict(ep_fails=1), "SDR_EST0104_RESEED_NONFATAL"),
    (dict(rs_fails=1), "SDR_EST0104_SPEFR_NONFATAL"),
    (dict(retry_fails=1), "SDR_EST0104_RETRY_NONFATAL"),
    (dict(spef_present=False), "SDR_EST0104_NOSPEF"),
])
def test_every_way_the_recovery_can_fail_reports_not_recovered(kw, marker):
    """If any step of the recovery fails the caller must fall back to exactly
    its previous behaviour — never a silent 'recovered'."""
    out = _run_tcl(_harness("EST-0104 inconsistent parasitics state", **kw))
    assert marker in out, out
    assert "SDR_EST0104_RECOVERED" not in out, out
    assert "RECOVERED=0" in out, out


def test_the_repair_is_never_retried_without_a_reannotated_spef():
    """The reseed wipes the SPEF (measured 3 -> 0 -> 3 violated pins). If the
    SPEF cannot be restored the retry must NOT happen, or the repair would
    optimise the optimistic tech-LEF model instead of the sign-off deck."""
    for kw in (dict(rs_fails=1), dict(spef_present=False)):
        out = _run_tcl(_harness("EST-0104 inconsistent parasitics state", **kw))
        calls = out.split("CALLS=")[1].strip()
        assert "MY_REPAIR" not in calls, (kw, calls)


# --------------------------------------------------------------------------
# WIRED IN: the shipped repair loop must actually carry it
# --------------------------------------------------------------------------

def test_signoff_drv_repair_loop_recovers_instead_of_breaking_out():
    """The loop's repair_design failure branch must try the recovery before it
    gives up, and must still give up when the recovery did not take."""
    tcl = p3._v1_8_100_signoff_drv_repair_tcl("/OUT")
    i_repair = tcl.index("repair_design -max_wire_length")
    i_detect = tcl.index("SDR_EST0104_DETECTED")
    i_giveup = tcl.index('SDR_REPAIR_NONFATAL: $_sdr_rd"; break')
    assert i_repair < i_detect < i_giveup, (i_repair, i_detect, i_giveup)
    # the give-up is now conditional on the recovery having failed
    assert "if {!$_sdr_est_rec} { puts \"SDR_REPAIR_NONFATAL" in tcl
    # and the retry re-issues the SAME command, margins included
    head = tcl[i_detect:i_giveup]
    assert "repair_design -max_wire_length $_sdr_mwl" in head
    assert "-slew_margin" in head and "-cap_margin" in head


# --------------------------------------------------------------------------
# The loop that carries the recovery must itself be probe-gated
# --------------------------------------------------------------------------

def _cmd_lines(tcl):
    return "\n".join(ln for ln in tcl.splitlines()
                     if not ln.lstrip().startswith("#"))


def test_postroute_drv_repair_is_only_emitted_on_the_fork_openroad():
    """The loop drives repair_design / repair_timing on a post-detailed-route
    SPEF-annotated design. On STOCK OpenROAD the RSZ repair-move family
    segfaults there (#581 r3) and a Tcl `catch` cannot contain a Signal 11 —
    the process dies and no GDS is written. So it must be emitted only when the
    fork-capability probe says yes, exactly like the end-of-flow estimate
    block it shares a hazard with."""
    stock = _cmd_lines(p3._post_route_spef_repair_tcl("/out", "/t.lef", "/c.lef"))
    for banned in ("repair_design", "repair_timing",
                   "detailed_route", "global_route"):
        assert banned not in stock, banned
    # …and the extraction it wraps is still there, so a stock user keeps the
    # sign-off SPEF the multi-corner STA reads.
    assert "extract_parasitics" in stock and "write_spef" in stock
    assert "SPEF_MEASURE_COMPLETE" in stock

    fork = _cmd_lines(p3._post_route_spef_repair_tcl(
        "/out", "/t.lef", "/c.lef", fork_repair_capable=True))
    assert "repair_design" in fork
    assert "SDR_EST0104_DETECTED" in fork


def test_the_probe_negative_path_says_why_it_skipped():
    """An empty block and a skipped block are different claims; the log must
    carry the second one."""
    stock = p3._post_route_spef_repair_tcl("/out", "/t.lef", "/c.lef")
    assert "SDR_SKIP_STOCK_OPENROAD" in stock


def test_end_of_flow_estimate_block_also_recovers():
    """The #147 end-of-flow estimate ran AFTER the min-area patch and the PG
    reroute — both netlist/odb edits — so BOTH of its repairs were refused
    EST-0104 on every run, and the estimate it exists to produce was never
    made: WNS_BEFORE and WNS_AFTER were identical to the digit
    (14.41737614545876 -> 14.41737614545876, measured). Measure-only block, so
    the recovery can never touch a shipped artifact."""
    tcl = p3._postroute_repair_estimate_tcl("/OUT", True)
    for tag in ("SPEF_REPAIR_DESIGN", "SPEF_REPAIR_SETUP"):
        assert f"{tag}_EST0104_DETECTED" in tcl, tag
        assert f"{tag}_EST0104_RECOVERED" in tcl, tag
    # the fork's proven marking is re-issued after the re-annotation, because
    # the -placement reseed necessarily overwrote it
    assert ("estimate_parasitics -detailed_routing; repair_design") in tcl
    assert ("estimate_parasitics -detailed_routing; repair_timing -setup") in tcl
    # give-up is still reachable and still says the original error
    assert 'if {!$_spef_repair_design_est_rec} { puts "SPEF_REPAIR_DESIGN_NONFATAL' in tcl
    assert 'if {!$_spef_repair_setup_est_rec} { puts "SPEF_REPAIR_SETUP_NONFATAL' in tcl
    # stock OpenROAD still gets nothing at all (it would segfault)
    assert p3._postroute_repair_estimate_tcl("/OUT", False) == ""


def test_after_spef_command_runs_between_reannotation_and_retry():
    """Order again, executed rather than asserted: reseed, re-annotate, then
    the caller's own marking, then the retry."""
    spef = "/tmp/r9_test_spef_present.spef"
    with open(spef, "w") as fh:
        fh.write("*SPEF\n")
    body = p3._est0104_recovery_tcl(spef, "_sdr_rd", "MY_REPAIR", "SDR",
                                    after_spef="MARK_SRC")
    script = (_STUB_HEAD
              + "proc MARK_SRC {args} { global CALLS; lappend CALLS MARK_SRC }\n"
              + "set EP_FAILS 0\nset RS_FAILS 0\nset RETRY_FAILS 0\n"
              + "set _sdr_rd {EST-0104 inconsistent parasitics state}\n"
              + body + '\nputs "CALLS=[join $CALLS |]"\n')
    out = _run_tcl(script)
    calls = out.split("CALLS=")[1].strip().split("|")
    assert "-placement" in calls[0], calls
    assert calls[1].startswith("read_spef "), calls
    assert calls[2] == "MARK_SRC", calls
    assert calls[3] == "MY_REPAIR", calls


def test_recovery_emitter_is_pure():
    a = _emit()
    b = _emit()
    assert a == b


def test_tag_scopes_the_flag_variable_so_two_call_sites_cannot_collide():
    one = p3._est0104_recovery_tcl("/a.spef", "_x", "CMD_A", "SDR")
    two = p3._est0104_recovery_tcl("/b.spef", "_y", "CMD_B", "SPEF_REPAIR")
    assert "_sdr_est_rec" in one and "_spef_repair_est_rec" in two
    assert "_sdr_est_rec" not in two
