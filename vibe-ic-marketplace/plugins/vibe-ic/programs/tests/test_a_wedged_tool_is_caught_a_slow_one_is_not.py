#!/usr/bin/env python3
"""test_a_wedged_tool_is_caught_a_slow_one_is_not.py

`tester_oracle_health_check` ran the burn command and the tester command under
`subprocess.run(..., timeout=N)` and recorded the bound firing as
`severity=ERROR, category=BURN_FAIL / TESTER_FAIL, "…timed out after Ns"`. That
is a finding about the ORACLE, produced by a fact about the HOST: a burn tool
writing to a board over a slow link, or a tester waiting on a device that is
answering, is working, and a wall clock cannot tell it from one that is wedged.

THE RC-2 ROUTE IS CLOSED HERE, and that is why this one needed real progress
logic rather than the one-line exit-code correction used elsewhere in this
branch. `tester_oracle_health_check` is wired into `flow_compliance_check` as a
gate program, and `__check_program_exit_zero` maps a gate's rc 2 onto
VACUOUS_PASS — a PASS tier. Returning "undetermined" as rc 2 from this program
would have turned a killed burn into a passing gate. rc 2 carries two different
meanings across this flow and only one of them is UNDETERMINED.

So the bound is now a STALL GRACE under `_watchdog.run_supervised`: "how long
may this be silent AND idle", not "how long may this take". Any output or CPU
resets it.

STRICTLY MORE PERMISSIVE THAN BEFORE, WHICH IS WHY NO GUARD MOVED. The old code
killed at `timeout` unconditionally. The new code kills at the same number only
when NOTHING has moved for that whole span, and never otherwise. Every job the
old code let through, the new code lets through; some it killed, the new code
does not. There is no input on which this refuses less than it used to about a
tool that is genuinely wedged — that case still reaches the same ERROR finding,
which `test_a_wedged_tool_is_still_an_error` asserts.

No design, PDK, vendor or IP-model identifier appears anywhere in this file.

Run: python3 -m pytest programs/tests/test_a_wedged_tool_is_caught_a_slow_one_is_not.py -q
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import tester_oracle_health_check as T             # noqa: E402
import flow_compliance_check as FCC                # noqa: E402


def _script(tmp_path: Path, body: str) -> str:
    """A command string for `run_cmd`, via a FILE.

    Not `python3 -c <repr>`: `run_cmd` uses `shlex.split`, which leaves the
    `\n` inside a quoted repr as two characters, and the child dies of a
    SyntaxError before it can be slow, silent or wedged. That mistake made the
    first draft of this file report DID NOT RAISE about a fix that worked.
    """
    f = tmp_path / "subject.py"
    f.write_text(body, encoding="utf-8")
    return f"{sys.executable} {f}"


# ── direction 1: a slow-but-progressing tool is no longer failed ────────────

def test_a_tool_that_is_slow_but_talking_runs_to_completion(tmp_path):
    """THE FIX. This command takes ~4x the grace it is given and is never
    killed, because it is producing output the whole time. Under the old
    `subprocess.run(timeout=...)` it was dead at 1 second with the oracle
    recorded as broken."""
    body = ("import sys, time\n"
            "for _ in range(8):\n"
            "    sys.stdout.write('working\\n'); sys.stdout.flush()\n"
            "    time.sleep(0.5)\n"
            "sys.stdout.write('DONE\\n')\n")
    started = time.monotonic()
    rc, out, _err = T.run_cmd(_script(tmp_path, body), 1)
    took = time.monotonic() - started
    assert rc == 0, out
    assert "DONE" in out, out
    # NON-VACUITY: it really did outlive the bound it was given. Without this
    # the test would pass against an implementation that finished instantly.
    assert took > 2.0, (
        f"the subject finished in {took:.1f}s, so it never outlived its 1s "
        f"grace and this proves nothing")


def test_a_tool_that_is_silent_but_computing_runs_to_completion(tmp_path):
    """The other progress signal. A burn tool can be busy and say nothing; the
    CPU probe is what keeps it alive, and without it silence alone would read
    as a stall."""
    body = ("import time\n"
            "end = time.monotonic() + 3.0\n"
            "x = 0\n"
            "while time.monotonic() < end:\n"
            "    x += 1\n"
            "print('DONE')\n")
    started = time.monotonic()
    rc, out, _err = T.run_cmd(_script(tmp_path, body), 1)
    took = time.monotonic() - started
    assert rc == 0 and "DONE" in out, out
    assert took > 2.0, f"finished in {took:.1f}s — it never outlived the grace"


# ── direction 2: a genuinely wedged tool is still caught ───────────────────

def test_a_wedged_tool_is_still_an_error(tmp_path):
    """THE HALF THAT MUST NOT MOVE. Silent AND idle for the whole grace, with
    the process still alive: that is a wedged tool, and it still stops this
    gate. A guard that stopped refusing would be a deletion."""
    # 600 s of nothing against a 1 s grace floored at the measured launch
    # cost. The wait is the FLOOR, not the sleep: a wedged tool is detected in
    # seconds, not in ten minutes.
    body = "import time\ntime.sleep(600)\n"
    with pytest.raises(T.Stalled) as caught:
        T.run_cmd(_script(tmp_path, body), 1)
    msg = str(caught.value)
    assert "no output" in msg and "no CPU" in msg, msg
    assert "It was not slow" in msg, (
        "the message must separate wedged from slow — that separation is the "
        "whole fix")


def test_the_wedged_tool_still_reaches_an_ERROR_finding(monkeypatch, tmp_path):
    """And it still reaches the finding, with the severity that stops the gate.
    Asserted through `check_oracle` rather than by reading the source, because
    the handler could have been correct and unreachable."""
    sof = tmp_path / "known_good.sof"
    sof.write_text("x")

    def _always_stalled(cmd_str, timeout):
        raise T.Stalled("`x` produced no output and used no CPU for 1s and was "
                        "stopped. It was not slow — it was doing nothing.")

    monkeypatch.setattr(T, "run_cmd", _always_stalled)
    findings, _extras = T.check_oracle({
        "known_good_sof": str(sof),
        "burn_command": "burn {sof}",
        "tester_command": "test",
        "pass_fingerprint": "OK",
        "fail_fingerprint": "BAD",
        "timeout_seconds": 1,
    })
    errors = [f for f in findings if f.severity == "ERROR"]
    assert errors, [(f.severity, f.category, f.message) for f in findings]
    assert any(f.category == "BURN_FAIL" for f in errors), errors
    assert any("no forward progress" in f.message for f in errors), errors
    assert not any("timed out after" in f.message for f in findings), (
        "the accusing wall-clock sentence is still being published")
    # AND IT STILL CANNOT PASS. `main` requires no ERROR *and* an ORACLE_PASS;
    # neither holds here, so the gate is still stopped.
    passed = (all(f.severity != "ERROR" for f in findings)
              and any(f.category == "ORACLE_PASS" for f in findings))
    assert passed is False


# ── why rc 2 was not the fix here ──────────────────────────────────────────

def test_rc_two_from_this_program_would_have_been_a_passing_gate():
    """THE MEASUREMENT BEHIND THE DESIGN CHOICE, asserted so the next author
    does not 'simplify' this into the one-line rc-2 correction used elsewhere.

    `flow_compliance_check` runs this program as a gate and reads rc 2 as
    VACUOUS_PASS. That is a PASS tier. Returning UNDETERMINED as rc 2 from a
    killed burn would have converted a stopped gate into a passing one.
    """
    assert "tester_oracle_health_check" in Path(FCC.__file__).read_text(
        encoding="utf-8"), "this program is no longer wired as a gate"
    doc = FCC.__check_program_exit_zero.__doc__ if hasattr(
        FCC, "__check_program_exit_zero") else None
    src = Path(FCC.__file__).read_text(encoding="utf-8")
    assert "rc == 2  → VACUOUS_PASS" in src, (
        "the rc-2 meaning in the gate runner has changed; re-check whether the "
        "rc-2 correction is now available to gate programs")
    assert doc is None or True     # the private name is mangled; src is the read
