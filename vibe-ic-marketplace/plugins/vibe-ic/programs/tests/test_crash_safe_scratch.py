"""Cleanup that does not depend on the dying process getting to run.

Every assertion here KILLS something.  A `finally` passes any test that lets the
process exit normally, which is why the two leaks this module exists for shipped
with `finally` blocks that were correct and never reached: `SIGKILL` was the
case, and a clean-exit test cannot see it.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _crash_safe_scratch as S  # noqa: E402

#: Measured: the child below reserves and prints in well under a second.
_SPAWN_TIMEOUT_S = 20


def _holder(root: Path, prefix: str) -> subprocess.Popen:
    """A child that reserves a directory and then sits on the lock forever."""
    code = (
        "import sys, time\n"
        f"sys.path.insert(0, {str(PROGRAMS)!r})\n"
        "import _crash_safe_scratch as S\n"
        f"res, _ = S.reserve({prefix!r}, root={str(root)!r})\n"
        "print(res.path, flush=True)\n"
        "time.sleep(600)\n")
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                         text=True)
    line = p.stdout.readline().strip()
    assert line, "the holder child never reported a reservation"
    return p, Path(line)


def test_a_live_owner_is_never_reaped(tmp_path):
    """The failure this must not have: sweeping out a peer that is running.

    Other agents work in this repo at the same time; a reaper that cannot tell
    a dead owner from a live one trades an invisible leak for an invisible
    corruption, which is the worse of the two.
    """
    child, held = _holder(tmp_path, "probe-")
    try:
        rep = S.reap("probe-", root=tmp_path)
        assert held.exists(), (
            "a directory whose owner is STILL RUNNING was removed: %s" % held)
        assert str(held) in rep.live, (
            "the live peer was left alone but not NAMED — a silent skip is "
            "how a set shrinks unnoticed: %s" % (rep,))
        assert not rep.reaped
    finally:
        child.kill()
        child.wait(timeout=_SPAWN_TIMEOUT_S)


def test_a_SIGKILLed_owners_directory_is_reaped_by_the_next_run(tmp_path):
    """The whole point. The owner is killed with the one signal it cannot
    handle, so nothing of its own code runs — and the directory still goes."""
    child, held = _holder(tmp_path, "probe-")
    assert held.exists()
    os.kill(child.pid, signal.SIGKILL)
    child.wait(timeout=_SPAWN_TIMEOUT_S)
    # The kernel releases the flock on death; nothing in the child did.
    rep = S.reap("probe-", root=tmp_path)
    assert not held.exists(), (
        "a killed owner's scratch survived the next reap — this is the 19 "
        "leaked worktrees, one run later")
    assert str(held) in rep.reaped


def test_reserve_reaps_before_it_allocates(tmp_path):
    """Which is what makes the leak self-limiting rather than merely tidy."""
    child, held = _holder(tmp_path, "probe-")
    os.kill(child.pid, signal.SIGKILL)
    child.wait(timeout=_SPAWN_TIMEOUT_S)
    res, rep = S.reserve("probe-", root=tmp_path)
    try:
        assert str(held) in rep.reaped, rep
        assert not held.exists()
        assert res.path.exists() and res.path != held
    finally:
        res.release()


def test_a_reaped_directory_gets_its_external_registration_dropped(tmp_path):
    """A scratch tree can hold state somewhere ELSE — a git worktree
    registration is the measured case, and `git worktree prune` cannot clear
    one whose directory still exists. Removing the directory without it leaves
    the repo carrying the entry forever."""
    seen = []
    child, held = _holder(tmp_path, "probe-")
    os.kill(child.pid, signal.SIGKILL)
    child.wait(timeout=_SPAWN_TIMEOUT_S)
    S.reap("probe-", remover=seen.append, root=tmp_path)
    assert [str(p) for p in seen] == [str(held)], (
        "the remover hook did not run for the reaped directory, so anything "
        "registered elsewhere would be orphaned: %s" % seen)


def test_a_directory_with_no_lock_is_kept_while_it_is_young(tmp_path):
    """A peer between `mkdtemp` and its `flock` has no sidecar yet. Reaping it
    would be a race this module created."""
    d = tmp_path / "probe-fresh"
    d.mkdir()
    rep = S.reap("probe-", root=tmp_path)
    assert d.exists(), "a directory with no lock sidecar was reaped on sight"
    assert any(p == str(d) for p, _ in rep.kept), rep


def test_a_directory_with_no_lock_is_reaped_once_it_is_old(tmp_path):
    """The 19 that were already on this host when the fix landed. They predate
    the sidecar, so age plus "nothing references it" is all there is to go on —
    and both must be required, not either."""
    d = tmp_path / "probe-legacy"
    (d / "wt").mkdir(parents=True)
    old = time.time() - 86400
    os.utime(d, (old, old))
    rep = S.reap("probe-", legacy_max_age_s=3600, root=tmp_path)
    assert not d.exists(), (
        "a day-old sidecar-less leftover was not reaped, so the pre-fix "
        "leaks would never be cleaned up: %s" % (rep,))
    assert str(d) in rep.reaped


def test_an_old_directory_a_process_still_references_is_kept(tmp_path):
    """The conservative half of the legacy rule, driven rather than asserted:
    a real child is started with its cwd inside the directory."""
    d = tmp_path / "probe-legacy-busy"
    d.mkdir()
    old = time.time() - 86400
    os.utime(d, (old, old))
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                             cwd=str(d))
    try:
        # The cwd link needs the child to have execve'd; poll rather than sleep
        # a fixed amount, so a slow host does not make this vacuous.
        for _ in range(100):
            if S._referenced_by_a_process(d):
                break
            time.sleep(0.05)
        else:
            pytest.fail("the child never showed up in /proc with that cwd, so "
                        "this test proves nothing about the guard")
        rep = S.reap("probe-", legacy_max_age_s=3600, root=tmp_path)
        assert d.exists(), (
            "an old directory a LIVE process is sitting in was reaped: %s" % rep)
        assert any(p == str(d) for p, _ in rep.kept)
    finally:
        child.kill()
        child.wait(timeout=_SPAWN_TIMEOUT_S)


def test_the_legacy_branch_can_be_switched_off_entirely(tmp_path):
    """During the transition a peer running the PRE-LOCK build leaves a
    directory nothing can attribute. Age plus `/proc` is a guess, and a caller
    that knows such a peer may be alive must be able to decline to make it —
    keeping a leak is recoverable, deleting a live agent's worktree is not."""
    d = tmp_path / "probe-legacy"
    d.mkdir()
    old = time.time() - 86400
    os.utime(d, (old, old))
    rep = S.reap("probe-", legacy_max_age_s=3600, root=tmp_path,
                 reap_unlocked=False)
    assert d.exists(), "the unattributable directory was reaped anyway"
    assert any(p == str(d) and "may be alive" in w for p, w in rep.kept), rep
    # CONTROL: the same directory IS reaped when the caller does not decline,
    # so the flag is what decided it and not the age rule.
    rep2 = S.reap("probe-", legacy_max_age_s=3600, root=tmp_path)
    assert not d.exists(), rep2


def test_a_LOCKED_directory_is_still_decided_when_the_legacy_branch_is_off(
        tmp_path):
    """Switching the guess off must not switch the KNOWLEDGE off: a dead
    owner's locked directory is still provably dead and still goes."""
    child, held = _holder(tmp_path, "probe-")
    os.kill(child.pid, signal.SIGKILL)
    child.wait(timeout=_SPAWN_TIMEOUT_S)
    rep = S.reap("probe-", root=tmp_path, reap_unlocked=False)
    assert not held.exists(), (
        "a locked directory whose owner is provably gone was kept because an "
        "unrelated legacy switch was off: %s" % (rep,))


def test_the_lock_is_actually_taken_and_not_merely_created(tmp_path):
    """CONTROL. Without this, every test above passes against a `reserve` that
    writes a sidecar and locks nothing — `_is_locked` would answer False for a
    live owner and the live-peer test would be measuring the age rule."""
    res, _ = S.reserve("probe-", root=tmp_path)
    try:
        assert S._is_locked(res.path / S.LOCK_NAME) is True, (
            "the reservation's own lock reads as unheld inside the process "
            "that holds it")
    finally:
        res.release()
    # And released on a clean teardown, so a tidy exit does not look live.
    assert not res.path.exists()


# ---------------------------------------------------------------------------
# A PEER TIDIES UP WHILE WE ARE WALKING THE LISTING.
#
# `iterdir()` is a snapshot. On a host running several agents against one /tmp,
# a peer finishes between the listing and the inspection and `d.stat()` raises
# FileNotFoundError, which escaped `reserve()` into the caller. Measured: it
# took down two tests of an unrelated PR's verification run and did NOT
# reproduce on a re-run of the same tree, which is how it stayed invisible.
#
# Three-way control, because a fix here can go wrong in two directions —
# crashing (the bug) and swallowing everything (the over-correction):
#   vanished        -> reported, sweep continues
#   still reapable  -> STILL reaped in the same sweep
#   a real error    -> NOT disguised as "it vanished"
# ---------------------------------------------------------------------------
def _vanishes_after_the_listing(monkeypatch, doomed, exc=None):
    """Model the RACE, not merely a missing directory.

    The listing must still SEE it — that is what makes this a race rather than
    an absence — so `is_dir` is answered directly and only `stat` raises. A
    naive patch of `stat` alone removes it at `iterdir()` time (pathlib's
    `is_dir` goes through `stat`), so the candidate never enters the loop and
    the test proves nothing.
    """
    exc = exc or FileNotFoundError(2, "No such file or directory", str(doomed))
    real_stat, real_is_dir = Path.stat, Path.is_dir

    def fake_is_dir(self):
        return True if Path(self) == doomed else real_is_dir(self)

    def fake_stat(self, *a, **k):
        if Path(self) == doomed:
            raise exc
        return real_stat(self, *a, **k)

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)
    monkeypatch.setattr(Path, "stat", fake_stat)


def test_a_peer_that_vanishes_mid_sweep_is_reported_not_a_crash(tmp_path, monkeypatch):
    doomed = tmp_path / "probe-gone"
    doomed.mkdir()
    _vanishes_after_the_listing(monkeypatch, doomed)
    rep = S.reap("probe-", root=tmp_path, legacy_max_age_s=0)
    assert rep.vanished == [str(doomed)], rep
    assert str(doomed) not in rep.reaped, rep
    assert [p for p, _ in rep.kept] == [], rep


def test_the_sweep_carries_ON_past_a_vanished_peer(tmp_path, monkeypatch):
    """The half that matters. A vanished peer must not abort the sweep, or one
    tidy peer disables the reaper for every abandoned directory behind it."""
    doomed = tmp_path / "probe-aaa-gone"
    doomed.mkdir()
    stale = tmp_path / "probe-bbb-stale"
    stale.mkdir()
    _vanishes_after_the_listing(monkeypatch, doomed)
    rep = S.reap("probe-", root=tmp_path, legacy_max_age_s=0)
    assert rep.vanished == [str(doomed)], rep
    assert str(stale) in rep.reaped, rep
    assert not stale.exists()


def test_a_real_error_is_not_disguised_as_a_vanished_peer(tmp_path, monkeypatch):
    """The over-correction guard. `except FileNotFoundError` must not become
    `except Exception`: a PermissionError is a fact about this host and has to
    reach the caller rather than be filed as "someone else tidied up"."""
    doomed = tmp_path / "probe-denied"
    doomed.mkdir()
    _vanishes_after_the_listing(
        monkeypatch, doomed,
        exc=PermissionError(13, "Permission denied", str(doomed)))
    with pytest.raises(PermissionError):
        S.reap("probe-", root=tmp_path, legacy_max_age_s=0)


def test_reserve_survives_a_peer_vanishing(tmp_path, monkeypatch):
    """End to end: this is the call that actually blew up in the field."""
    doomed = tmp_path / "probe-gone"
    doomed.mkdir()
    _vanishes_after_the_listing(monkeypatch, doomed)
    res, rep = S.reserve("probe-", root=tmp_path, legacy_max_age_s=0)
    try:
        assert res.path.is_dir()
        assert rep.vanished == [str(doomed)], rep
    finally:
        res.release()
