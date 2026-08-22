"""#569 — both end-of-flow repairs were refused and the log said APPLIED.

From a real run:

    SPEF_REPAIR_WNS_BEFORE: 14.41737614545876
    [ERROR EST-0104] inconsistent parasitics state
    SPEF_REPAIR_DESIGN_NONFATAL: EST-0104
    [ERROR EST-0104] inconsistent parasitics state
    SPEF_REPAIR_SETUP_NONFATAL: EST-0104
    SPEF_REPAIR_APPLIED_ON_ESTIMATE          <- printed anyway

`repair_design` and `repair_timing` both decline with EST-0104 because this
block runs after min-area patching and PG reroute, which edit the odb and leave
the estimator with a non-empty invalidation set. Nothing is repaired, so
`WNS_AFTER` prints the same number as `WNS_BEFORE` to the digit — which reads as
"the repair ran and there was nothing to gain".

The two `catch`es were right not to abort the deck. What was missing is that a
swallowed refusal reached the verdict as a success: the APPLIED line was
unconditional. Same family as the identical-WNS pair, and the same family as
the metal-fill engine that could not observe its own fill (v1.9.6): an absence
rendering as a pass.

WHAT THIS COMMIT DOES AND DOES NOT DO
    does      makes the refusal VISIBLE and stops the false APPLIED claim
    does NOT  fix the EST-0104 refusal itself

The recovery — re-annotating and re-issuing `estimate_parasitics
-detailed_routing` after a `-placement` reseed — is the rest of #569 and needs
the flow re-run as its acceptance evidence (`WNS_AFTER` must differ from
`WNS_BEFORE`). Landing the honesty half first is deliberate: until the log
stops claiming APPLIED, the flow re-run that proves the recovery cannot be read.

EXERCISED BY RUNNING THE TCL, not by reading it. `tclsh` sources the emitted
block with `repair_design` / `repair_timing` stubbed to raise or not, and the
branch taken is read off stdout — a test that grepped the emitter's source
would pass on a block that never parses.
"""
from __future__ import annotations

import importlib.util
import pathlib
import shutil
import subprocess
import sys
import textwrap

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import phase3_one_shot_runner as R  # noqa: E402

_TCLSH = shutil.which("tclsh")

#: Stubs for everything the block calls, so the only variable is whether the two
#: repairs raise. `file exists` is forced true to reach the repair branch.
_HARNESS = """\
set MODE {mode}
proc read_spef {{a}} {{}}
proc estimate_parasitics {{args}} {{}}
namespace eval sta {{ proc worst_slack {{args}} {{ return 14.417 }} }}
proc report_checks {{args}} {{}}
proc repair_design {{}} {{
  global MODE
  if {{$MODE ne "none"}} {{ error "[ERROR EST-0104] inconsistent parasitics state" }}
}}
proc repair_timing {{args}} {{
  global MODE
  if {{$MODE eq "both"}} {{ error "[ERROR EST-0104] inconsistent parasitics state" }}
}}
proc file {{sub args}} {{ if {{$sub eq "exists"}} {{ return 1 }} ; return 0 }}
source {block}
"""


def _emit(tmp_path) -> pathlib.Path:
    p = tmp_path / "block.tcl"
    p.write_text(R._postroute_repair_estimate_tcl("/out", fork_repair_capable=True),
                 encoding="utf-8")
    return p


def _run_tcl(tmp_path, mode: str) -> str:
    block = _emit(tmp_path)
    h = tmp_path / "harness.tcl"
    h.write_text(_HARNESS.format(mode=mode, block=block), encoding="utf-8")
    proc = subprocess.run([_TCLSH, str(h)], capture_output=True, text=True,
                          timeout=45)
    return proc.stdout


tclsh_only = pytest.mark.skipif(_TCLSH is None, reason="no tclsh on this host")


# ── the defect ───────────────────────────────────────────────────────────────
@tclsh_only
def test_both_refused_does_not_claim_applied(tmp_path):
    """The measured case: two EST-0104 refusals, nothing repaired."""
    out = _run_tcl(tmp_path, "both")
    assert "SPEF_REPAIR_NOT_APPLIED" in out, out
    assert "SPEF_REPAIR_APPLIED_ON_ESTIMATE" not in out, out


@tclsh_only
def test_the_refusal_line_says_why_the_wns_pair_is_uninformative(tmp_path):
    """A reader who sees two identical WNS numbers has to be told what they
    mean. Without this the operator draws the opposite conclusion — that the
    design had converged."""
    out = _run_tcl(tmp_path, "both")
    assert "2/2" in out, out
    assert "SAME" in out, out


# ── the accept cases ─────────────────────────────────────────────────────────
@tclsh_only
def test_no_refusal_still_reports_applied(tmp_path):
    """Load-bearing: without it, a block that never claimed APPLIED would
    satisfy the tests above and the flow would lose a true signal."""
    out = _run_tcl(tmp_path, "none")
    assert "SPEF_REPAIR_APPLIED_ON_ESTIMATE" in out, out
    assert "SPEF_REPAIR_NOT_APPLIED" not in out, out
    assert "SPEF_REPAIR_PARTIAL" not in out, out


@tclsh_only
def test_one_refusal_is_partial_and_still_applied(tmp_path):
    """One repair ran, so work WAS done — reporting NOT_APPLIED here would be
    the same dishonesty pointing the other way."""
    out = _run_tcl(tmp_path, "one")
    assert "SPEF_REPAIR_PARTIAL: 1 of 2" in out, out
    assert "SPEF_REPAIR_APPLIED_ON_ESTIMATE" in out, out
    assert "SPEF_REPAIR_NOT_APPLIED" not in out, out


# ── the deck must still parse and must not abort ─────────────────────────────
@tclsh_only
def test_the_emitted_block_is_syntactically_complete(tmp_path):
    """vibe-ic#581 — a Tcl syntax error here takes down the WHOLE deck, and the
    failure surfaces far from its cause."""
    block = _emit(tmp_path)
    chk = tmp_path / "chk.tcl"
    chk.write_text(textwrap.dedent("""\
        set f [open [lindex $argv 0] r]; set body [read $f]; close $f
        puts [expr {[info complete $body] ? "COMPLETE" : "INCOMPLETE"}]
    """), encoding="utf-8")
    proc = subprocess.run([_TCLSH, str(chk), str(block)],
                          capture_output=True, text=True, timeout=45)
    assert "COMPLETE" in proc.stdout, proc.stdout + proc.stderr


@tclsh_only
def test_a_refusal_does_not_abort_the_deck(tmp_path):
    """The `catch`es were correct and must stay. An EST-0104 that killed the
    deck would lose write_def / write_verilog — worse than the false claim this
    commit removes."""
    out = _run_tcl(tmp_path, "both")
    assert "SPEF_REPAIR_WNS_AFTER" in out, out
    assert "SPEF_REPAIR_DESIGN_NONFATAL" in out, out
    assert "SPEF_REPAIR_SETUP_NONFATAL" in out, out


def test_the_counter_is_in_the_emitted_text(tmp_path):
    """Runs without tclsh, so a host with no Tcl still catches the emitter
    losing the counter entirely."""
    tcl = R._postroute_repair_estimate_tcl("/out", fork_repair_capable=True)
    assert "set _prr_refused 0" in tcl
    assert tcl.count("incr _prr_refused") == 2, (
        "both repairs must count toward the refusal total")


def test_stock_openroad_still_emits_nothing():
    """Probe-gated: stock upstream OpenROAD never reaches this block, so it
    cannot segfault there. That guard predates this change and must survive it."""
    assert R._postroute_repair_estimate_tcl("/o", fork_repair_capable=False) == ""
