"""The two causes that made a landing lane answer NORECORD, pinned both ways.

NORECORD is a THIRD STATE: not red, not clean — UNKNOWN. Two files on main sat
in it, and neither was a driver defect. Each is pinned here with its negative
control in the same file, because a test that cannot fail against the pre-fix
shape proves nothing about the fix.

  1. `test_commit_msg_nda_check.py` built every leak string from
     `FICTIONAL_NDA_TOKENS` while `conftest.py` published that set with
     `os.environ.setdefault`. On a host that already exports
     `VIBEIC_NDA_TOKENS` — which the landing tier is — setdefault loses, the
     guard hunts different tokens, 10 negatives fail, `--maxfail=10` truncates
     the session at item 26 of 90, and a truncated session is not a record:

         session finished before every selected item completed (26/90)

  2. `test_issue1181_probe_budget_and_summary.py` killed a session with
     `subprocess.run(timeout=...)`, which reaps the direct child and not its
     grandchild. The fixture's `sleep 30` was orphaned to init and outlived the
     session, so the driver — which owns the complete descendant tree — refused
     the file's result even though all four of its tests had PASSED:

         pytest exited with unfinished live descendants

Neither fix makes the tier stop asking, and neither weakens an assertion: the
NDA file still proves both directions of the guard on the same corpus, and the
killed-session file still proves that a killed session loses its earned record.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_NDA_SUITE = _TESTS / "test_commit_msg_nda_check.py"

#: An ambient store of the right SHAPE and the wrong VALUES — what a configured
#: host looks like to this suite. No real token is used or needed: the defect is
#: that the ambient set and the fixture set DIFFER, not what either one says.
_AMBIENT = json.dumps({
    "sku_full": "zzqq11223344", "sku_prefix": "zzqq11",
    "foundry_product": "wwppmm", "foundry_brand1": "vvnnkkllzz",
    "foundry_brand2": "ttrrooeexx", "foundry_brand3": "yybbnnmmqq",
    "ip_vendor": "ssmmaaddff", "ip_part": "qqllzzxxcc",
})


def _pytest(args, env_extra, timeout=600):
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
        capture_output=True, text=True, timeout=timeout, env=env,
        cwd=str(_TESTS.parents[1]))


# ===========================================================================
# CAUSE 1 — the ambient token store
# ===========================================================================
def test_the_nda_suite_is_immune_to_an_ambient_token_store():
    """THE FIX. With a foreign `VIBEIC_NDA_TOKENS` exported, the NDA suite must
    still run to completion and pass — it measures its own corpus against the
    store it publishes for itself, not against whatever the host exports."""
    p = _pytest([str(_NDA_SUITE)], {"VIBEIC_NDA_TOKENS": _AMBIENT})
    assert p.returncode == 0, (
        "the NDA suite is red under an ambient token store, which is exactly "
        "the state that truncated the session at 26/90 and produced NORECORD:\n"
        + p.stdout[-4000:] + p.stderr[-2000:])
    assert " failed" not in p.stdout, p.stdout[-3000:]


def test_the_ambient_store_is_genuinely_hostile():
    """THE NEGATIVE CONTROL for the test above, and it is not optional: if
    `_AMBIENT` were somehow equivalent to the fixture set, the test above would
    pass for no reason at all.

    A module that DEFERS to the ambient store the way `conftest.py` does — via
    `setdefault` — must still be broken by it. This reproduces the pre-fix shape
    of the NDA suite in miniature: build the leak string from the fixture set,
    let the guard resolve its own tokens from the environment, and watch them
    disagree."""
    mod = _TESTS.parent / "_probe_ambient_store_test.py"
    mod.write_text(textwrap.dedent(f"""
        import json, os, subprocess, sys
        from pathlib import Path
        _P = Path(__file__).resolve().parent
        sys.path.insert(0, str(_P)); sys.path.insert(0, str(_P / "tests"))
        from _nda_fixture_tokens import FICTIONAL_NDA_TOKENS

        def test_deferring_to_the_ambient_store_misses_the_fixture_leak():
            # `setdefault` — the pre-fix behaviour. On a configured host it is
            # a no-op, so the guard below never learns the fixture tokens.
            os.environ.setdefault("VIBEIC_NDA_TOKENS",
                                  json.dumps(FICTIONAL_NDA_TOKENS))
            msg = _P / "m.txt"
            msg.write_text("fix: port the flow to " + FICTIONAL_NDA_TOKENS["sku_full"])
            rc = subprocess.run(
                [sys.executable, str(_P / "commit_msg_nda_check.py"),
                 "--message-file", str(msg)],
                capture_output=True, text=True).returncode
            msg.unlink()
            assert rc == 1, "LEAK NOT CAUGHT"
    """), encoding="utf-8")
    try:
        p = _pytest([str(mod)], {"VIBEIC_NDA_TOKENS": _AMBIENT}, timeout=300)
        assert p.returncode != 0, (
            "the ambient store did not break a module that defers to it, so "
            "the immunity test above proves nothing:\n" + p.stdout[-3000:])
        assert "LEAK NOT CAUGHT" in p.stdout, p.stdout[-3000:]
    finally:
        mod.unlink(missing_ok=True)


# ===========================================================================
# CAUSE 2 — the orphaned grandchild
# ===========================================================================
_INNER = textwrap.dedent("""\
    import subprocess
    def test_a():
        assert True
    def test_slow():
        subprocess.run(["sh", "-c", "echo $$ > {pid}; exec sleep 30"])
""")


def _alive(pid: int) -> bool:
    """Is this pid a process that is still RUNNING?

    `os.kill(pid, 0)` alone is the wrong probe, and it is wrong in the exact
    direction that matters here: it SUCCEEDS for a zombie. MEASURED in the run
    image (`ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2`), at the moment the
    assertion below used to fail:

        BEFORE KILL  alive=True  /proc/<gc>/stat[3]=S
        AFTER killpg _alive=True /proc/<gc>/stat[3]=Z   PPid=1
        ps -o pid,ppid,stat,comm -p 1 -> "1  0  Ss  python3"
        /proc/1/cmdline               -> the test process itself

    The killed grandchild is reparented to PID 1, and PID 1 in this image is
    whatever the run was started as — the pytest entry, not a reaping init. It
    never calls `wait()`, so the grandchild stays a zombie forever and
    `os.kill(pid, 0)` keeps returning success. Both failing tests end in
    `assert not _alive(gc)`, which is why ONE fact explains both, and why the
    two NDA tests in this file are green.

    A zombie is dead: it holds no resources, runs no code, and the driver's
    "unfinished live descendants" refusal is about processes that are still
    RUNNING. So the state is read, not inferred from a signal.

    THE DISCRIMINATION THIS MUST NOT LOSE:
    `test_the_bare_timeout_idiom_still_orphans_the_grandchild` asserts a
    genuinely running orphan reads True. That orphan is a `sleep 30` in state
    S — measured above — so reading `Z` as dead still tells the two apart. Any
    widening that also reported a running `sleep` as dead would turn both
    tests green while proving nothing, and `test_a_zombie_is_dead_and_a_
    sleeping_orphan_is_not` below is the guard against exactly that.
    """
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return _proc_state(pid) not in ("Z", "X", "x")


def _proc_state(pid: int) -> str:
    """`/proc/<pid>/stat` field 3, or "" where /proc does not answer.

    Field 3 is read from AFTER the last ')' because the comm field can itself
    contain spaces and parentheses."""
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return ""
    try:
        return raw[raw.rindex(")") + 2:].split()[0]
    except (ValueError, IndexError):
        return ""


def _spawn_inner(tmp_path):
    """A pytest whose slow test spawns a GRANDCHILD that records its own pid."""
    pidf = tmp_path / "grandchild.pid"
    t = tmp_path / "test_inner.py"
    t.write_text(_INNER.format(pid=pidf), encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(t)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={"PATH": "/usr/bin:/bin", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
        start_new_session=True)
    return proc, pidf


def _grandchild_pid(pidf: Path, deadline: float) -> int:
    while time.time() < deadline:
        if pidf.is_file():
            txt = pidf.read_text().strip()
            if txt.isdigit():
                return int(txt)
        time.sleep(0.1)
    pytest.fail("the inner fixture never spawned its grandchild")


def test_a_killed_session_leaves_no_live_descendant(tmp_path):
    """THE FIX, as an idiom: kill the process GROUP and the grandchild dies with
    the session. This is the shape `test_issue1181_probe_budget_and_summary.py`
    now uses."""
    proc, pidf = _spawn_inner(tmp_path)
    gc = _grandchild_pid(pidf, time.time() + 30)
    try:
        proc.communicate(timeout=3)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)   # the whole tree
        proc.communicate()
    deadline = time.time() + 10
    while _alive(gc) and time.time() < deadline:
        time.sleep(0.1)
    assert not _alive(gc), (
        f"grandchild {gc} outlived the killed session — the driver will call "
        "this file's result UNKNOWN however green its tests are")


def test_the_bare_timeout_idiom_still_orphans_the_grandchild(tmp_path):
    """THE NEGATIVE CONTROL. `subprocess.run(timeout=...)` reaps the direct
    child only, so the grandchild survives — which is the defect, measured, and
    the reason the test above is not a tautology.

    This test CLEANS UP THE ORPHAN IT CREATES. Leaving it running would make
    THIS file the next NORECORD, which would be a fine joke and a bad test."""
    proc, pidf = _spawn_inner(tmp_path)
    gc = _grandchild_pid(pidf, time.time() + 30)
    try:
        try:
            proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()            # the pre-fix idiom: the DIRECT child only
            proc.communicate()
        time.sleep(0.5)
        assert _alive(gc), (
            "the bare-timeout idiom did not orphan the grandchild, so the fix "
            "above is indistinguishable from doing nothing")
    finally:
        try:
            os.killpg(os.getpgid(gc), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(gc, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        deadline = time.time() + 10
        while _alive(gc) and time.time() < deadline:
            time.sleep(0.1)
        assert not _alive(gc), f"failed to clean up orphan {gc}"


def test_the_repaired_files_carry_the_idioms_that_repair_them():
    """Anchored to the operation, not to a count: the killed-session test must
    own its process group, and the NDA suite must publish its own store."""
    killed = (_TESTS / "test_issue1181_probe_budget_and_summary.py").read_text(
        encoding="utf-8")
    assert "start_new_session=True" in killed and "killpg" in killed, (
        "the killed-session test no longer owns the tree it spawns")
    nda = _NDA_SUITE.read_text(encoding="utf-8")
    assert "monkeypatch.setenv(\"VIBEIC_NDA_TOKENS\"" in nda, (
        "the NDA suite no longer publishes the token store it measures against")


def test_a_zombie_is_dead_and_a_sleeping_orphan_is_not(tmp_path):
    """The guard on `_alive` itself, both directions in one test.

    Reading the process state instead of signalling it is only correct while
    the two cases stay distinguishable. A widening that reported a RUNNING
    orphan as dead would turn both tests in this file green and prove nothing
    — "time to stop" is not a reason to stop asking. So: a real zombie must
    read dead, and a real sleeping process must read alive, measured on
    processes this test creates.
    """
    sleeper = subprocess.Popen(["sleep", "30"])
    try:
        assert _proc_state(sleeper.pid) in ("S", "R", "D"), (
            f"a running `sleep` is in state {_proc_state(sleeper.pid)!r}")
        assert _alive(sleeper.pid), "a running process must read alive"

        # a child that has exited and has NOT been waited for is a zombie
        zombie = subprocess.Popen([sys.executable, "-c", "raise SystemExit(0)"])
        deadline = time.time() + 10
        while time.time() < deadline and _proc_state(zombie.pid) != "Z":
            time.sleep(0.05)
        assert _proc_state(zombie.pid) == "Z", (
            f"could not create a zombie to test against; state is "
            f"{_proc_state(zombie.pid)!r}")
        assert os.kill(zombie.pid, 0) is None, (
            "os.kill(pid, 0) must still SUCCEED for a zombie — that is the "
            "whole reason this probe was wrong")
        assert not _alive(zombie.pid), "a zombie must read dead"
        zombie.wait()
    finally:
        sleeper.kill()
        sleeper.wait()


def test_alive_falls_back_to_the_signal_where_proc_does_not_answer():
    """`/proc` is not universal. Where it cannot be read the probe degrades to
    what it did before rather than declaring everything dead."""
    assert _proc_state(2 ** 22 + 7) == ""      # no such pid, no /proc entry
    assert not _alive(2 ** 22 + 7)             # and the signal agrees
    assert _alive(os.getpid()), "this very process must read alive"
