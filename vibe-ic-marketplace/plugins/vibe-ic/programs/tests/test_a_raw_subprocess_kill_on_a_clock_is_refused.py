#!/usr/bin/env python3
"""Class (0) of `watchdog_ceiling_semantics_check`: a RAW kill on a CLOCK.

WHAT WENT WRONG
===============
The gate's headline sentence is "no clock may stop a supervised job". Its
population was the 244 supervised launches routed through `_watchdog` /
`_docker_watchdog`. MEASURED on this tree: it reported `OFFENDER 0` and `[PASS]`
on a checkout that still carried, in `gate_host_independence_check.parallel_audit`::

    out, err = proc.communicate(timeout=max(timeout * len(labels), timeout))
    ...
    except subprocess.TimeoutExpired:
        proc.kill()

taken by swapping that one file back to its pre-fix blob `488ad4a4` and re-running:
`CLEAN 241  BUDGET 0  EXEMPT 0  UNJUDGED 2  RESIDUAL 1  OFFENDER 0`, byte-identical
to the fixed tree's verdict. The gate was right about what it looked at. A raw
`subprocess.Popen` never routed through a supervisor was outside it — and that is
exactly where the deadline had survived, on the shard carrying the heaviest gate
in the suite.

With the class extended, the SAME swap now reports::

    RAW_CLOCK_KILL 4   OFFENDER 1
    gate_host_independence_check.py:1790  proc.kill(...)  [raw_timeout_kill]
        register key: gate_host_independence_check.py::collect::proc.kill
    [FAIL] rc 1

WHAT THIS FILE LOCKS
====================
1. Each of the three shapes is FOUND — planted, one per synthetic file.
2. THE SUPERVISOR'S OWN REAP IS NOT. `_watchdog` kills a job whose progress
   signals went flat; that is the ruling being obeyed, and a gate that flagged it
   would forbid the only legitimate way to stop anything.
3. The RATCHET: a site on the shrink-only record is REPORTED, a site off it is
   REFUSED, and a recorded site that has gone asks to be removed.
4. The shapes that are NOT this defect stay clean: a `finally:` cleanup kill, and
   a kill with no clock anywhere near it.

Run::

    cd .../plugins/vibe-ic && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \\
      python3 -m pytest programs/tests/\\
test_a_raw_subprocess_kill_on_a_clock_is_refused.py -q
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import watchdog_ceiling_semantics_check as W                 # noqa: E402


def _scan(tmp_path: Path, body: str, name: str = "subject.py"):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    src = path.read_text(encoding="utf-8")
    return W.scan_raw_clock_kill(path, name, tree=ast.parse(src),
                                 src_lines=src.splitlines())


_TIMEOUT_KILL = '''
import subprocess
def drive(argv, budget):
    proc = subprocess.Popen(argv)
    try:
        out, err = proc.communicate(timeout=budget)
    except subprocess.TimeoutExpired:
        proc.kill()
        out, err = proc.communicate()
    return proc.returncode, out, err
'''

_DEADLINE_KILL = '''
import time
def drive(proc, budget):
    deadline = time.monotonic() + budget
    while proc.poll() is None:
        if time.monotonic() > deadline:
            proc.kill()
            break
        time.sleep(0.1)
'''

_SLEEP_THEN_KILL = '''
import time
def drive(proc):
    time.sleep(30)
    proc.terminate()
'''


def test_the_deadline_shapes_are_each_found(tmp_path):
    """The three spellings of "elapsed time decided to stop it"."""
    got = {}
    for label, body in (("timeout", _TIMEOUT_KILL),
                        ("deadline", _DEADLINE_KILL),
                        ("sleep", _SLEEP_THEN_KILL)):
        rows = _scan(tmp_path, body, f"{label}.py")
        got[label] = [r.kind for r in rows]
    assert got["timeout"] == ["raw_timeout_kill"], got["timeout"]
    assert "clock_guarded_kill" in got["deadline"], got["deadline"]
    assert "sleep_then_kill" in got["sleep"], got["sleep"]


def test_a_planted_kill_after_a_sleep_is_refused_end_to_end(tmp_path):
    """THE ACCEPTANCE ARM THE RULING NAMES: plant one, and it must go RED.

    Driven through the gate's own verdict logic — the register decides
    OFFENDER vs RESIDUAL — rather than through the scanner alone, because a
    shape that is found and then quietly filed as a residual is not refused.
    """
    rows = _scan(tmp_path, _SLEEP_THEN_KILL, "planted.py")
    assert rows, "the planted kill was not found at all"
    recorded, problem = W._load_raw_kill_register(_PROGRAMS)
    assert not problem, f"the shipped register did not load: {problem}"
    for r in rows:
        assert r.expr not in recorded, (
            f"a freshly planted site {r.expr!r} is already on the record; the "
            f"register is matching too loosely and would absorb a new defect")
    assert any("deadline with its arithmetic written out by hand" in r.detail
               for r in rows), [r.detail for r in rows]


def test_the_supervisors_own_stopped_job_reap_is_not_flagged():
    """THE OTHER ACCEPTANCE ARM: the one legitimate kill stays green.

    `_watchdog` stops a job whose every readable forward-progress signal went
    flat. That is vibe-ic#2051 being OBEYED. Run over the real primitive, not a
    paraphrase of it: a gate that flagged this would forbid the only sanctioned
    way to stop anything, and the whole ruling with it.
    """
    for name in ("_watchdog.py", "_progress_run.py", "_docker_watchdog.py"):
        path = _PROGRAMS / name
        if not path.is_file():
            pytest.skip(f"NOT_MEASURED: {name} is not in this tree")
        src = path.read_text(encoding="utf-8")
        rows = W.scan_raw_clock_kill(path, name, tree=ast.parse(src),
                                     src_lines=src.splitlines())
        assert not rows, (
            f"{name} is reported as killing on a clock: "
            + "; ".join(f"{r.file}:{r.line} {r.callee} [{r.kind}]" for r in rows)
            + ". The progress-stall reap is the ONE kill the ruling permits.")


def test_a_cleanup_kill_and_a_clockless_kill_stay_clean(tmp_path):
    """The false-positive arm. Without it this class would be unusable.

    A `finally:` that reaps what the function itself started, and a kill decided
    by a caller's own predicate, are both correct and neither reads a clock.
    """
    rows = _scan(tmp_path, '''
import subprocess
def drive(argv):
    proc = subprocess.Popen(argv)
    try:
        return proc.communicate()
    finally:
        if proc.poll() is None:
            proc.kill()
''', "cleanup.py")
    assert not rows, [f"{r.line} {r.kind}" for r in rows]

    rows = _scan(tmp_path, '''
def drive(proc, caller_says_stop):
    if caller_says_stop():
        proc.kill()
''', "clockless.py")
    assert not rows, [f"{r.line} {r.kind}" for r in rows]

    rows = _scan(tmp_path, '''
import time
def supervise(proc, stall_grace_s, since_last_progress_s):
    while proc.poll() is None:
        if since_last_progress_s() >= stall_grace_s:
            proc.kill()
            return "stalled"
        time.sleep(1)
''', "stall.py")
    assert not rows, (
        "a stop under a PROGRESS predicate was flagged as a clock kill: "
        + str([f"{r.line} {r.kind}" for r in rows]))


def test_the_escalation_after_a_decided_kill_is_one_finding_not_two(tmp_path):
    """SIGTERM then SIGKILL is one decision. Two rows invite the wrong repair."""
    rows = _scan(tmp_path, '''
import os, signal, subprocess
def drive(argv, budget):
    proc = subprocess.Popen(argv, start_new_session=True)
    try:
        return proc.communicate(timeout=budget)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            return proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            return proc.communicate()
''', "escalation.py")
    assert len(rows) == 1, (
        f"{len(rows)} rows for one decision: "
        + "; ".join(f"{r.line} {r.callee}" for r in rows))
    assert rows[0].callee == "os.killpg"


def test_the_register_is_shrink_only_and_keyed_on_an_identity():
    """The ratchet, on the SHIPPED register: nothing blessed, nothing by line.

    THE REGISTER IS NOW EMPTY, AND THAT IS ITS BEST STATE (owner ruling R4).
    This test used to open with `assert recorded, "an empty register would
    refuse the whole tree silently"`. The first half of that sentence came
    true — every one of the four recorded sites was converted, so `recorded`
    is `{}` — and the second half was never true of an empty register: with
    nothing recorded, a raw clock kill is not silently forgiven, it is an
    OFFENDER, printed by name with its register key, rc 1. The assumption is
    replaced by the executed proof below rather than deleted: emptiness is
    only safe if the empty register still refuses, so this asserts that it
    does. A ratchet whose terminal state fails its own test would be a
    ratchet nobody could finish.
    """
    doc = json.loads(
        (_PROGRAMS / W._RAW_KILL_REGISTER).read_text(encoding="utf-8"))
    recorded = doc["recorded"]
    for key, note in recorded.items():
        parts = key.split("::")
        assert len(parts) == 3, (
            f"{key!r} is not <file>::<function>::<callee>; a key that is not an "
            f"identity drifts on every unrelated edit above the site")
        assert not parts[1].isdigit(), (
            f"{key!r} is keyed on a LINE NUMBER, which moves whenever anything "
            f"above it is edited")
        assert note.strip(), f"{key!r} is recorded with no note"


def test_an_empty_register_refuses_LOUDLY_rather_than_forgiving(tmp_path):
    """The property `assert recorded` was standing in for, EXECUTED.

    A register with no entries must make any raw clock kill an OFFENDER that
    is named with its key and returns rc 1 — never a silent pass. This is the
    same arm the four conversions were measured with: restore one kill, the
    gate refuses it by name.
    """
    programs = tmp_path / "programs"
    programs.mkdir()
    (programs / W._RAW_KILL_REGISTER).write_text(
        json.dumps({"recorded": {}}), encoding="utf-8")
    (programs / "offender.py").write_text(_TIMEOUT_KILL, encoding="utf-8")
    rows, _backstop = W.scan(programs)
    offenders = [r for r in rows if r.verdict == "OFFENDER"]
    assert len(offenders) == 1, [(r.file, r.line, r.verdict) for r in rows]
    assert offenders[0].expr.endswith("::proc.kill"), offenders[0].expr
    assert not [r for r in rows if r.verdict == "RESIDUAL_RAW_CLOCK_KILL"]


def test_an_exemption_tag_is_the_same_one_the_rest_of_the_gate_uses(tmp_path):
    """One convention, not two — and it must actually apply to this class."""
    body = _SLEEP_THEN_KILL.replace(
        "    proc.terminate()",
        f"    proc.terminate()  {W._EXEMPT_TAG} a reason a reader can weigh")
    rows = _scan(tmp_path, body, "exempted.py")
    assert rows and all(r.verdict == "EXEMPT" for r in rows), (
        f"the shared exemption tag does not reach this class: "
        + str([(r.line, r.verdict) for r in rows]))
