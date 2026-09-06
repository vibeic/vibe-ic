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
