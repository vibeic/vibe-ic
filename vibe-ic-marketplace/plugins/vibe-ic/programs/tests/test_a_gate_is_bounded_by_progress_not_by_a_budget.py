#!/usr/bin/env python3
"""test_a_gate_is_bounded_by_progress_not_by_a_budget.py

`flow_compliance_check` drove every gate program under
`subprocess.run(..., timeout=gate_budget)`. The file's own #525 comment records
what that cost, and it is the whole argument in one sentence:

    the old fixed 300s killed honest slow gates on large SoCs
    (reset_dependency_check ~6 min on a 7.5MB post-PnR netlist; provenance
    sha256 over multi-GB GDS) and reported the kill as a plain gate FAIL

The response at the time was to raise the number to 900. That is the same defect
restated, and so is raising it again: a gate hashing a multi-GB GDS is WORKING,
and killing it destroys the answer whatever the message beside the kill then
says. Relabelling it NOT_MEASURED would not have given the answer back either.

FIVE bounded calls are replaced here — the gate runner, both yosys sub-gates,
the structural-P0 worker, and the `--help` capability probe — with
`_watchdog.run_host_supervised`, which bounds NO PROGRESS: CPU and I/O read from
`/proc` across the whole process tree, plus captured-output growth.

WHY THIS IS A SMALL CHANGE TO A LOAD-BEARING FILE. The verdict tier does not
move. A wedged gate returns False and FAILs the audit, exactly as a timed-out
one did; only the moment of the kill and the sentence explaining it change. That
is deliberate: the VACUOUS_PASS / PASS_WITH_WAIVERS tiers in this file have a
MEASURED regression history (v1.10.14 -> v1.10.16 turned PASS=36 FAIL=0 into
PASS=25 VOIDED=8 FAIL over byte-identical artefacts), and nothing here touches
them. It is also why a bare rc 2 was never an option: the runner now requires a
typed design/capability/external reason before rc 2 can enter VACUOUS_PASS; an
untyped undetermined result is INCOMPLETE.

THE GRACE CAN ONLY KILL LESS. `gate_budget` seconds of no-progress stops a
strict subset of what `gate_budget` seconds of runtime stopped: both stop a gate
idle for N, only the budget stopped a gate still working at N. No gate that
passes today can start failing.

No design, PDK, vendor or IP-model identifier appears anywhere in this file.

Run: python3 -m pytest programs/tests/test_a_gate_is_bounded_by_progress_not_by_a_budget.py -q
"""
from __future__ import annotations

import ast
import sys
import time
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as F                # noqa: E402
import _watchdog as W                            # noqa: E402


def _gate(tmp_path: Path, body: str) -> str:
    """A gate program with `body`, addressed the way the runner addresses one."""
    prog = tmp_path / "a_gate.py"
    prog.write_text(body, encoding="utf-8")
    return str(prog)


# ── direction 1: a slow-but-working gate is no longer killed ───────────────

def test_a_gate_that_is_working_is_never_stopped(tmp_path, monkeypatch):
    """THE FIX, and the half the old budget could not deliver at any constant.

    The gate runs far past the grace it is given while burning CPU and printing
    — a stand-in for the ~6 min netlist read and the multi-GB sha256 named in
    the #525 comment. It must reach its own exit code.
    """
    monkeypatch.setattr(F._pl, "gate_timeout_s", lambda: 1)
    prog = _gate(tmp_path, (
        "import sys, time\n"
        "end = time.monotonic() + 3.0\n"
        "x = 0\n"
        "while time.monotonic() < end:\n"
        "    x += 1\n"
        "    if x % 200000 == 0:\n"
        "        print('hashing', flush=True)\n"
        "sys.exit(0)\n"))
    monkeypatch.setattr(F, "_resolve_program_cmd",
                        lambda cmd, cwd=None: [sys.executable, prog])
    started = time.monotonic()
    ok, out = F._check_program_exit_zero(tmp_path, "a_gate")
    took = time.monotonic() - started
    assert ok is True, out
    # NON-VACUITY: it really did outlive the grace, so this is not passing
    # because the subject happened to be fast.
    assert took > 2.0, (
        f"the gate finished in {took:.1f}s against a 1s grace — it never "
        f"outlived the bound, so this proves nothing")


# ── direction 2: a wedged gate is still caught, and still BLOCKS ───────────

def test_a_wedged_gate_is_stopped(tmp_path, monkeypatch):
    """THE HALF THAT MUST NOT MOVE. Idle and silent across the grace, process
    alive: stopped."""
    monkeypatch.setattr(F._pl, "gate_timeout_s", lambda: 1)
    prog = _gate(tmp_path, "import time\ntime.sleep(600)\n")
    monkeypatch.setattr(F, "_resolve_program_cmd",
                        lambda cmd, cwd=None: [sys.executable, prog])
    started = time.monotonic()
    ok, out = F._check_program_exit_zero(tmp_path, "a_gate")
    took = time.monotonic() - started
    assert ok is False, "a wedged gate PASSED — the guard was deleted"
    assert took < 60, (
        f"the wedged gate took {took:.0f}s to notice — the watchdog is not "
        f"sampling inside its own grace")
    assert "STALLED" in out, out
    assert "It was not slow; it was doing nothing." in out, out
    assert "TIMED OUT" not in out, (
        "the clock sentence is still being published as the reason")


def test_a_wedged_gate_still_FAILS_the_audit_and_is_not_a_pass_tier(
        tmp_path, monkeypatch):
    """THE BLOCKING PROOF. `ok is False` is what makes the step FAIL, and the
    ledger must not classify the stall into any tier that reads as a pass —
    rc 2 in this runner is VACUOUS_PASS, which is exactly the trap."""
    monkeypatch.setattr(F._pl, "gate_timeout_s", lambda: 1)
    prog = _gate(tmp_path, "import time\ntime.sleep(600)\n")
    monkeypatch.setattr(F, "_resolve_program_cmd",
                        lambda cmd, cwd=None: [sys.executable, prog])
    F._GATE_LEDGER.clear()
    ok, out = F._check_program_exit_zero(tmp_path, "a_gate")
    assert ok is False
    assert not out.startswith(F._VACUOUS_HINT_PREFIX), (
        "a wedged gate is being promoted into the VACUOUS_PASS tier")
    assert not out.startswith(F._WAIVER_HINT_PREFIX)
    rows = [r for r in F._GATE_LEDGER]
    assert rows, "the stall was not recorded in the gate execution ledger"
    assert rows[-1]["verdict"] == "STALLED", rows[-1]
    assert rows[-1]["rc"] is None, (
        "a stall was given a return code, which a reader can compare against "
        "the pass codes")


def test_a_gate_that_really_fails_still_fails(tmp_path, monkeypatch):
    """NON-VACUITY. The ordinary failing path must still work — a fix that made
    everything pass would satisfy direction 1 and be a deletion."""
    monkeypatch.setattr(F._pl, "gate_timeout_s", lambda: 30)
    prog = _gate(tmp_path, "import sys\nprint('nope')\nsys.exit(1)\n")
    monkeypatch.setattr(F, "_resolve_program_cmd",
                        lambda cmd, cwd=None: [sys.executable, prog])
    ok, out = F._check_program_exit_zero(tmp_path, "a_gate")
    assert ok is False, out
    assert "STALLED" not in out, (
        "an ordinary gate failure is being excused as a stall")


def test_a_gate_that_passes_still_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(F._pl, "gate_timeout_s", lambda: 30)
    prog = _gate(tmp_path, "import sys\nprint('fine')\nsys.exit(0)\n")
    monkeypatch.setattr(F, "_resolve_program_cmd",
                        lambda cmd, cwd=None: [sys.executable, prog])
    ok, _out = F._check_program_exit_zero(tmp_path, "a_gate")
    assert ok is True


def test_untyped_rc_two_is_incomplete(tmp_path, monkeypatch):
    """A bare rc 2 cannot launder an undetermined execution into a pass tier."""
    monkeypatch.setattr(F._pl, "gate_timeout_s", lambda: 30)
    prog = _gate(tmp_path, "import sys\nprint('verdict: SKIP')\nsys.exit(2)\n")
    monkeypatch.setattr(F, "_resolve_program_cmd",
                        lambda cmd, cwd=None: [sys.executable, prog])
    F._GATE_LEDGER.clear()
    ok, out = F._check_program_exit_zero(tmp_path, "a_gate")
    assert ok is True and out.startswith("INCOMPLETE:"), out
    assert F._GATE_LEDGER[-1]["reason_class"] == "EXECUTION_ERROR"


# ── the shape of the change ────────────────────────────────────────────────

def test_no_gate_dispatch_is_bounded_by_runtime_any_more():
    """THE CONTROL THAT A BEHAVIOURAL TEST CANNOT BE.

    A version of this fix that kept every kill and merely reworded it would pass
    every test above except direction 1. This reads the CALLS out of the tree —
    not the text, because a comment quoting the call it replaced is not a call.
    """
    src = Path(F.__file__).read_text(encoding="utf-8")
    bounded = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name in ("run", "check_output", "call", "Popen") and \
                any(k.arg == "timeout" for k in node.keywords):
            bounded.append(node.lineno)
    assert bounded == [], (
        f"flow_compliance_check still bounds a subprocess by RUNTIME at "
        f"line(s) {bounded} — a gate that is working is still being killed "
        f"there, whatever the handler beside it reports")
    assert src.count("run_host_supervised") >= 5, (
        "one of the five dispatch sites lost its bound without gaining a "
        "watchdog — a gate that wedges there now hangs for ever")


def test_the_grace_reuses_the_budget_so_it_can_only_kill_less():
    """The safety argument, stated as a test rather than left in prose."""
    assert F._GATE_STALL_GRACE_S == 60, (
        "the sub-gate grace moved away from the runtime bound it replaced; "
        "re-check that it is still >= that bound or the argument fails")
