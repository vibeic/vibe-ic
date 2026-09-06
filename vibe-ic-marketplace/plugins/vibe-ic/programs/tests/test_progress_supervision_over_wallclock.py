#!/usr/bin/env python3
"""A declared STEP BUDGET must not be handed to the watchdog's hard ceiling.

THE OWNER'S RULE, AND WHAT THE PRODUCT STILL DID
------------------------------------------------
"dont use timeout (we have phase-out this time-out mechanism) to stop".
`_watchdog.py` is the mechanism that replaces it, and its own docstring is
explicit about the one number it does NOT want used as a control::

    `hard_ceiling_s` (default 24h) is a pathological-infinite-loop backstop
    ONLY (a CPU-burning loop that never goes idle), NOT the primary control.

`loop_watchdog_compliance_check` already FORCES every long tool through that
supervisor. It checks the SHAPE of the call -- `marker=` present, or a
`run_supervised` callee -- and nothing checks the SEMANTICS. So a call site can
satisfy the gate in full and then pin `hard_ceiling_s` to its step budget,
which reinstates exactly the wall-clock kill the primitive exists to remove.
That is not a hypothetical: `lec_run._docker` passed
``hard_ceiling_s=float(timeout)`` where `timeout` is the LEC step budget
(7200 s by default), and `run_docker_supervised` also wraps the container-side
command in a GNU ``timeout`` at that same ceiling -- so a Yosys equivalence
proof that is emitting output and burning a full core is SIGKILLed at 7195 s
with no verdict, and the flow records a design that was never compared.

MEASURED, 2026-09-06, while this was being written: a post-layout LEC on an
open benchmark IC had been running as ONE Yosys process for 5360 s of a 7195 s
step budget, 1374 points proved, 0 failed, 99.9 % CPU, still advancing.

THE FIX, AND WHY IT IS NOT "A BIGGER NUMBER"
---------------------------------------------
The step budget survives, with its original job: it decides whether the NEXT
attempt is LAUNCHED (`StepBudget.next_attempt_budget()` -> 0 = do not launch).
That is the anti-re-arm property the budget was written for on 2026-08-27, and
it is a decision made BETWEEN attempts, so it kills nothing. What it no longer
does is bound a RUNNING attempt. A progressing attempt now runs to completion;
one that stops moving is still stopped, and is recorded as STALLED with the
evidence -- what was watched, and how long it had shown nothing.

Three states, not two: `natural` / `stalled` / `ceiling`, and lec_run keeps
`_STALL_MARKER` distinct from `_TIMEOUT_MARKER` so a report can say which.

WHY THE SUBPROCESSES HERE ARE SYNTHETIC
----------------------------------------
Every job below is a `python3 -c` loop or a `sleep`. The property under test is
"does the supervisor kill a job that is still moving", which is a property of
the supervisor; using a real EDA tool would measure the tool and the host as
well and would take hours to do it.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import _docker_watchdog as _dw          # noqa: E402
import _watchdog as _wd                 # noqa: E402
import lec_run                          # noqa: E402


# A job that PROGRESSES for `secs` seconds: it prints, and it burns CPU.
def _progressing(secs: float, tick: float = 0.05) -> str:
    return (f"{sys.executable} -c "
            f"'import sys,time;t=time.time()\n"
            f"while time.time()-t<{secs}:\n"
            f"    sys.stdout.write(\"tick\\n\");sys.stdout.flush()\n"
            f"    time.sleep({tick})\n"
            f"print(\"DONE\")'")


def _progressing_argv(secs: float, tick: float = 0.05):
    return [sys.executable, "-c",
            "import sys,time\n"
            f"t=time.time()\n"
            f"while time.time()-t<{secs}:\n"
            "    sys.stdout.write('tick\\n'); sys.stdout.flush()\n"
            f"    time.sleep({tick})\n"
            "print('DONE')\n"]


# ---------------------------------------------------------------------------
# 1. THE HEADLINE. A job that is still progressing outlives the step budget.
# ---------------------------------------------------------------------------
def test_a_progressing_job_outlives_the_declared_lec_step_budget(tmp_path):
    """RED before the fix: `hard_ceiling_s=float(timeout)` put a GNU `timeout`
    of 1 s around a 4 s job that was printing every 50 ms, so it was killed and
    `DONE` never arrived. GREEN after: the budget no longer reaches the ceiling
    and the job runs to its own end.

    Runs in HOST mode (`container=""`), which `run_docker_supervised` supports
    by construction, so the test needs no container and no EDA image.
    """
    script = tmp_path / "job.py"
    script.write_text(
        "import sys,time\n"
        "t=time.time()\n"
        "while time.time()-t < 4.0:\n"
        "    sys.stdout.write('tick\\n'); sys.stdout.flush()\n"
        "    time.sleep(0.05)\n"
        "print('DONE')\n")
    marker = str(script)
    started = time.monotonic()
    r = lec_run._docker("", f"{sys.executable} {marker}",
                        timeout=1, marker=marker)
    elapsed = time.monotonic() - started

    assert r.returncode == 0, (
        f"a still-progressing job was stopped: rc={r.returncode} "
        f"after {elapsed:.1f}s\nstdout={r.stdout[-400:]!r}\n"
        f"stderr={r.stderr[-400:]!r}")
    assert "DONE" in r.stdout, (
        "the job did not reach its own end — the declared step budget is "
        "still bounding a RUNNING attempt")
    assert elapsed > 3.0, (
        "the job did not actually outlive the 1 s budget, so this test did "
        "not exercise what it claims")


def test_lec_docker_does_not_hand_the_step_budget_to_the_hard_ceiling(
        monkeypatch):
    """The structural half of the same finding, so a regression is named at the
    call site instead of only as a slow behavioural surprise.

    The declared budget must not arrive as `hard_ceiling_s`. Asserting only
    "!= 73" would pass on any other bounded number, so the assertion is on the
    PROPERTY: whatever ceiling is used must be at least the primitive's own
    pathological backstop.
    """
    seen = {}

    def fake_supervised(container, cmd, marker, **kw):
        seen.update(kw)
        seen["marker"] = marker
        return 0, "Yosys 0.68\n", ""

    monkeypatch.setattr(_dw, "run_docker_supervised", fake_supervised)
    lec_run._docker("vibeic-eda", "yosys -s /work/equiv.ys", timeout=73,
                    marker="/work/equiv.ys")

    ceiling = seen.get("hard_ceiling_s", _wd.DEFAULT_HARD_CEILING_S)
    assert ceiling >= _wd.DEFAULT_HARD_CEILING_S, (
        f"the LEC step budget (73 s) reached the watchdog's pathological "
        f"backstop as {ceiling} — a wall-clock deadline wearing the "
        f"watchdog's clothes")
    assert seen["marker"] == "/work/equiv.ys", (
        "the CPU/progress marker must still be the exact yosys script")


# ---------------------------------------------------------------------------
# 2. THE OTHER DIRECTION. A genuinely stalled job IS stopped — as STALLED.
# ---------------------------------------------------------------------------
def test_a_stalled_job_is_stopped_and_recorded_as_stalled_not_as_a_timeout():
    """Removing the ceiling must not remove the ability to stop a hang.

    `sleep` emits nothing and burns no CPU, so every configured progress signal
    is flat and the grace trips. The outcome must be the watchdog's OWN stall
    code — never GNU `timeout`'s 124, which is what a wall-clock kill returns
    and what a reader would (correctly) read as "the clock ran out".
    """
    rc, out, err = _dw.run_docker_supervised(
        "", "sleep 30", marker="sleep 30",
        docker_exec_raw=lec_run._docker_exec_raw,
        stall_grace_s=1.5, poll_s=0.4)

    assert rc == _wd.RC_STALLED, (
        f"a job with every signal flat returned rc={rc}; RC_STALLED "
        f"({_wd.RC_STALLED}) is the only outcome that says 'it stopped "
        f"moving' rather than 'the clock ran out'")
    assert rc not in (124, 137), "a stall must never be reported as a timeout"


def test_a_stall_carries_the_evidence_a_reader_needs_to_check_it():
    """"Killed as hung" is an assertion until it says what was watched and when
    the job was last seen moving. Both must be on the record."""
    res = _wd.run_supervised(["sleep", "20"], stall_grace_s=1.0, poll_s=0.3)
    assert res.outcome == "stalled"
    assert res.rc == _wd.RC_STALLED
    assert "WATCHDOG_STALLED" in res.err
    assert res.supervision.get("watched"), (
        "the record does not name the progress signals that were wired")
    assert "output" in res.supervision["watched"], (
        f"captured output is always wired by run_supervised; "
        f"watched={res.supervision['watched']!r}")
    assert res.supervision.get("since_last_progress_s") is not None, (
        "the record cannot say WHEN the job was last seen moving")
    assert res.supervision["since_last_progress_s"] >= 1.0
    # and the same two facts must be legible in the text a human reads
    assert "watched=" in res.err and "since_last_progress_s=" in res.err


# ---------------------------------------------------------------------------
# 3. THE CONTROL. A fast job behaves identically — this changes the ordinary
#    path not at all.
# ---------------------------------------------------------------------------
def test_the_fast_path_is_byte_identical():
    """A sub-second job returns the same rc and the same bytes whatever the
    ceiling is. If this ever differs, the change was not confined to the long
    tail it was written for."""
    cmd = "printf 'hello\\n'"
    a = _dw.run_docker_supervised(
        "", cmd, marker=cmd, docker_exec_raw=lec_run._docker_exec_raw,
        hard_ceiling_s=30)
    b = _dw.run_docker_supervised(
        "", cmd, marker=cmd, docker_exec_raw=lec_run._docker_exec_raw,
        hard_ceiling_s=_wd.DEFAULT_HARD_CEILING_S)
    assert a[0] == b[0] == 0
    assert a[1] == b[1] == "hello\n"


def test_a_fast_job_through_lec_docker_is_unchanged():
    r = lec_run._docker("", "printf 'ok\\n'", timeout=1, marker="printf")
    assert r.returncode == 0
    assert r.stdout == "ok\n"


# ---------------------------------------------------------------------------
# 2b. THE THIRD KILL, END TO END. The DRC change rests on it: a job that IS
#     progressing and is going NOWHERE. `test_watchdog` proves `abort_probe`
#     with fake processes and a source-text assertion; nothing drove it over a
#     REAL subprocess, which is the only way to see that a chatty, CPU-burning
#     child — the exact shape no generic signal can stop — is actually stopped.
# ---------------------------------------------------------------------------
def test_a_progressing_job_going_nowhere_is_aborted_with_its_reason():
    """The child prints continuously, so output AND CPU advance every poll and
    the stall grace can NEVER fire. Only the caller's domain predicate can end
    it, and the outcome must be its own third state — not a stall, not a
    ceiling, and never a natural exit that a reader would take as a result."""
    looks = {"n": 0}

    def going_nowhere():
        looks["n"] += 1
        if looks["n"] < 4:
            return None
        return "the convergence metric has not moved"

    res = _wd.run_supervised(
        ["bash", "-c", "while :; do echo tick; sleep 0.05; done"],
        stall_grace_s=3600, poll_s=0.2, abort_probe=going_nowhere)

    assert res.outcome == "aborted", (
        f"a chatty CPU-burning child ended as {res.outcome!r}; every generic "
        f"signal reads it as healthy, so only the domain predicate can stop it")
    assert res.rc == _wd.RC_ABORTED
    assert res.rc not in (0, 124, _wd.RC_STALLED), (
        "a deliberate abort must not be confusable with a natural exit, a "
        "wall-clock kill, or a hang")
    assert res.abort_reason == "the convergence metric has not moved"
    assert "WATCHDOG_ABORTED: the convergence metric has not moved" in res.err
    assert "tick" in res.out, (
        "the child was not actually progressing, so this test did not "
        "exercise the case it claims")


def test_a_progressing_job_with_a_satisfied_predicate_is_never_aborted():
    """The other direction, and the one that makes the DRC change safe: while
    the caller's predicate keeps answering None, the same chatty child runs to
    its own end however long it takes."""
    res = _wd.run_supervised(
        ["bash", "-c", "for i in $(seq 1 40); do echo tick; sleep 0.05; done"],
        stall_grace_s=3600, poll_s=0.2, abort_probe=lambda: None)
    assert res.outcome == "natural", res.err[-300:]
    assert res.rc == 0
    assert res.out.count("tick") == 40


# ---------------------------------------------------------------------------
# 3b. THE OUTER WALL. Removing the inner ceiling is worth nothing if the RUNNER
#     still wraps the producer in a host deadline five minutes further out.
# ---------------------------------------------------------------------------
def test_the_runner_imposes_no_outer_deadline_on_the_lec_producer():
    """The declared budget is RECORDED, not ENFORCED.

    THE ASSERTION HERE IS THE ONE THE OLD INVARIANT COULD NOT MAKE. Its
    siblings in `test_lec_run` require `outer == inner + 300` — satisfied by
    any number big enough, and satisfied at every one of the three values this
    wall has held (1200, 3x the inner budget, inner+300). Each was defended in
    a comment as the right one; each still killed a proof that was computing.
    This asserts there is no wall.

    Read with `ast`, and keyed on the BUDGET NAME rather than on the dispatch's
    argv. THE FIRST DRAFT OF THIS TEST WAS VACUOUS and was caught by its own
    mutation: it filtered on `"lec_run" in ast.unparse(call)`, but the argv is
    built into a local `cmd`, so that string is not in the call at all. Swapping
    the pre-fix file back in left it GREEN. What the defect actually touches is
    `_LEC_PRODUCER_TIMEOUT_S` reaching a `timeout=`, so that is what is read.
    """
    import ast
    src = (PROGRAMS / "design_one_shot_runner.py").read_text(
        encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    assert "_LEC_PRODUCER_TIMEOUT_S" in src, (
        "the declared budget is gone entirely — this test can no longer "
        "distinguish 'not enforced' from 'not measured'")
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for k in node.keywords:
            if k.arg in ("timeout", "hard_ceiling_s") and \
                    "_LEC_PRODUCER_TIMEOUT_S" in ast.unparse(k.value):
                bad.append(f"design_one_shot_runner.py:{node.lineno}")
    assert bad == [], (
        "the LEC producer is dispatched under a host wall-clock deadline "
        "again — a progressing proof dies at it with no verdict: "
        + ", ".join(bad))


def test_the_declared_lec_budget_is_still_read_from_the_producer():
    """Removing the ENFORCEMENT must not remove the DISCLOSURE. The number is
    still derived from `lec_run`'s own constant, and it still reaches the step
    record — so "this run went long" stays answerable."""
    import design_one_shot_runner as R
    import lec_run as L
    assert R.lec_producer_yosys_timeout_s() == L.DEFAULT_YOSYS_TIMEOUT_S
    assert R.lec_producer_outer_timeout_s() == \
        R.lec_producer_yosys_timeout_s() + 300
    src = (PROGRAMS / "design_one_shot_runner.py").read_text(
        encoding="utf-8", errors="replace")
    assert "_LEC_PRODUCER_TIMEOUT_S}s — RECORDED" in src, (
        "the declared budget no longer reaches the step record; a run that "
        "went long is now invisible instead of merely uncut")


# ---------------------------------------------------------------------------
# 3c. THE SECOND-ORDER CONSEQUENCES OF REMOVING A DEADLINE. Both were made
#     REACHABLE by this lane's own change, so both are this lane's to close.
# ---------------------------------------------------------------------------
def _spent_budget(total_s, elapsed_s):
    """A StepBudget with one recorded attempt and `elapsed_s` on its clock."""
    now = [0.0]
    b = lec_run.StepBudget(total_s, clock=lambda: now[0])
    b.record("verilog", "", total_s, elapsed_s, True, False)
    now[0] = elapsed_s
    return b


def test_a_spent_admission_budget_does_not_contradict_a_verdict():
    """A proof may now legitimately run PAST the budget and still decide.

    While the budget was a deadline this was unreachable — a run past it had
    been killed, so it had no verdict — and `annotate_step_budget` appended
    "the designs are neither proven equivalent nor proven different"
    unconditionally. Appending that to a PASS is not a disclosure, it is a
    contradiction inside one report, and this lane's own change is what made
    it reachable.
    """
    b = _spent_budget(7200, 10800.0)
    assert b.exhausted(), "the fixture did not actually spend the budget"
    rep = lec_run.annotate_step_budget(
        {"verdict": "PASS", "equivalent": True,
         "verdict_explanation": "all 1374/1374 $equiv cells proven"}, b)
    ex = rep["verdict_explanation"]
    assert "neither proven equivalent nor proven different" not in ex, (
        "a PASS report also says the designs were never compared:\n" + ex)
    assert "bounds attempts, not runtime" in ex
    # the machine-readable fields stay true and unchanged
    assert rep["step_budget_exhausted"] is True
    assert rep["exhausted_resource"] == "wall_clock_seconds"


def test_a_spent_budget_with_no_verdict_still_says_nothing_was_decided():
    """The other direction. The disclosure that mattered must survive: when no
    attempt reached a verdict, the report must still say so in those words."""
    b = _spent_budget(7200, 10800.0)
    rep = lec_run.annotate_step_budget(
        {"verdict": "INCONCLUSIVE", "equivalent": False,
         "verdict_explanation": "stopped before any completed equiv_status"}, b)
    ex = rep["verdict_explanation"]
    assert "neither proven equivalent nor proven different" in ex
    assert "no attempt reached a verdict" in ex


def test_an_unspent_budget_appends_nothing_at_all():
    """The control: the ordinary path is untouched."""
    now = [0.0]
    b = lec_run.StepBudget(7200, clock=lambda: now[0])
    before = "all 1374/1374 $equiv cells proven"
    rep = lec_run.annotate_step_budget(
        {"verdict": "PASS", "verdict_explanation": before}, b)
    assert rep["verdict_explanation"] == before
    assert rep["step_budget_exhausted"] is False


def test_the_kill_record_does_not_name_a_duration_it_never_measured():
    """rc 137 is GNU `timeout`'s SIGKILL escalation AND a container OOM-kill —
    `_CONTAINER_TIMEOUT_RCS`' own comment says so. Stamping "after {budget}s"
    on it asserted a wall the run may never have reached, and with the ceiling
    back at the pathological backstop that number would now read 86400.
    """
    class _R:
        returncode = 137
        stdout = "Yosys 0.68\n9.2. Executing EQUIV_SIMPLE pass.\n"
        stderr = ""

    seen = {}

    def fake_docker(container, cmd, timeout=120, marker=None, **kw):
        seen["timeout"] = timeout
        return _R()

    import types
    orig = lec_run._docker
    lec_run._docker = fake_docker
    try:
        launched, out = lec_run.run_yosys_equiv(
            "vibeic-eda", "/work/equiv.ys", timeout=7200)
    finally:
        lec_run._docker = orig

    assert launched
    assert lec_run._TIMEOUT_MARKER in out, (
        "the budget-kill marker must survive — consumers key on it")
    assert "after 7200s" not in out, (
        "the record still names a duration nothing measured:\n" + out)
    assert "rc=137" in out
    assert "ATTEMPT ADMISSION" in out


# ---------------------------------------------------------------------------
# 3d. A WALL CLOCK PRODUCING A CAPABILITY VERDICT. The analog A6 physical-
#     verification producer rolled its own `docker exec` helper: a bare
#     `subprocess.run(timeout=600)` under `except Exception`, so a klayout DRC
#     that merely ran LONG came back as rc 127 -- the POSIX "command not
#     found" code -- with empty stdout. That file's own comment records what
#     A6 then reports for `rc=127, no report`: "no parseable DRC result".
#     A slow run and an ABSENT ENGINE were byte-identical to every reader.
#
#     This is vibe-ic#581's shape ("A TIMEOUT IS A BUDGET OUTCOME, NOT A
#     CAPABILITY GAP") reappearing one track over, and `loop_watchdog_
#     compliance_check` cannot see it: the tool name comes from a runtime
#     `_tool_on_path` lookup, so the argv carries no static long-tool literal.
# ---------------------------------------------------------------------------
def test_a_slow_analog_pv_tool_is_not_reported_as_a_missing_one():
    """RED before: rc 127. The distinction is the whole difference between
    "could not measure" and "the engine is not installed"."""
    import subprocess as _sp
    import analog_a6_native_pv as A6

    real = A6.subprocess.run

    def _always_times_out(*a, **k):
        raise _sp.TimeoutExpired(cmd=a[0] if a else "x", timeout=k.get("timeout"))

    A6.subprocess.run = _always_times_out
    try:
        rc, out, err = A6._docker_exec("vibeic-eda", "klayout -b -r drc.lydrc")
    finally:
        A6.subprocess.run = real

    assert rc != 127, (
        "a tool that ran LONG is reported with the 'command not found' code; "
        "A6 books that as 'no parseable DRC result', i.e. a capability gap")
    assert rc in (124, _wd.RC_STALLED), rc
    assert "not found" not in (err or "").lower()


def test_a_supervised_analog_pv_launch_error_is_contained_not_raised():
    """Removing `except Exception: return 127` must not turn an unexpected
    launch error into a traceback out of a physical-verification step.

    The old helper swallowed EVERYTHING into 127 — which is what made a slow
    tool indistinguishable from a missing one. The fix keeps 127 for the case
    it genuinely describes (the tool could not be RUN) and takes the timeout
    out of that bucket. This pins the half that must not regress.
    """
    import analog_a6_native_pv as A6

    def _explode(*a, **k):
        raise OSError(24, "Too many open files")

    import _docker_watchdog as _dw
    orig = _dw.run_docker_supervised
    _dw.run_docker_supervised = _explode
    try:
        rc, out, err = A6._docker_exec("vibeic-eda", "klayout -b -r d.lydrc",
                                       marker="d.lydrc")
    finally:
        _dw.run_docker_supervised = orig

    assert rc == 127, rc
    assert "Too many open files" in err
    assert out == ""


def test_the_analog_pv_long_tools_are_supervised_not_wall_clocked():
    """Every LONG call in that producer must carry a progress marker; the SHORT
    probes (`test -e`, `command -v`) must keep the bounded raw path, because a
    probe that does not answer in 30 s IS broken and decides nothing about a
    design. Read with `ast` so a call cannot hide behind formatting.
    """
    import ast
    src = (PROGRAMS / "analog_a6_native_pv.py").read_text(
        encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    unsupervised = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_docker_exec"):
            continue
        if any(k.arg == "marker" for k in node.keywords):
            continue
        flat = ast.unparse(node)
        # the two SHORT probes are named by the command they run
        if "test -e" in flat or "command -v" in flat:
            continue
        unsupervised.append(f"analog_a6_native_pv.py:{node.lineno}")
    assert unsupervised == [], (
        "these physical-verification runs are bounded by a wall clock with no "
        "progress supervision: " + ", ".join(unsupervised))


# ---------------------------------------------------------------------------
# 4. THE MIGRATION LEFTOVER. `_progress_run.run` has no `timeout=` parameter,
#    deliberately — "convert a call site by deleting the argument". One call
#    site kept the argument, and the TypeError it raises is not a
#    SubprocessError, so the `except` beside it does not catch it.
# ---------------------------------------------------------------------------
def test_progress_run_rejects_a_timeout_argument_loudly():
    """The primitive's own contract, pinned: it must not silently accept and
    ignore a bound. This is the shape that makes the next test's finding a
    CRASH rather than a no-op."""
    import _progress_run as _pr
    with pytest.raises(TypeError):
        _pr.run(["true"], capture_output=True, text=True, timeout=30)


def test_no_program_hands_a_timeout_to_the_progress_run_primitive():
    """MEASURED on main at ad38a76d: 108 `_progress_run` call sites across
    `programs/`, of which exactly ONE still passed `timeout=` --
    `analog_one_shot_runner`'s A6 DRC-attribution advisory. Its `except
    (OSError, subprocess.SubprocessError)` cannot catch a TypeError, so the
    advisory did not degrade -- it took the whole A6 step down with it.

    Read with `ast`, so a mention in a comment or a docstring cannot trip it
    and a call cannot hide behind formatting.
    """
    import ast
    offenders = []
    for path in sorted(PROGRAMS.glob("*.py")):
        src = path.read_text(encoding="utf-8", errors="replace")
        if "_progress_run" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        aliases = {a.asname or a.name
                   for n in ast.walk(tree) if isinstance(n, ast.Import)
                   for a in n.names if a.name == "_progress_run"}
        if not aliases:
            continue
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id in aliases
                    and n.func.attr in ("run", "run_or_undetermined",
                                        "run_best_effort")
                    and any(k.arg == "timeout" for k in n.keywords)):
                offenders.append(f"{path.name}:{n.lineno}")
    assert offenders == [], (
        "these call sites pass `timeout=` to a primitive that has no such "
        "parameter — each one is an uncaught TypeError at runtime: "
        + ", ".join(offenders))
