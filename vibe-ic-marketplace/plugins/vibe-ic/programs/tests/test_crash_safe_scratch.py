"""Cleanup that does not depend on the dying process getting to run.

Every assertion here KILLS something.  A `finally` passes any test that lets the
process exit normally, which is why the two leaks this module exists for shipped
with `finally` blocks that were correct and never reached: `SIGKILL` was the
case, and a clean-exit test cannot see it.
"""
from __future__ import annotations

import os
import shutil
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
# #1263 — A CONCURRENT PEER IS THE OPERATING CONDITION, NOT AN ERROR.
#
# Every agent on this host reaps the same shared prefix, so a candidate this
# loop listed can be gone by the time the loop reaches it. Until #1263 that
# interleaving raised an uncaught FileNotFoundError out of `reap` — and so out
# of `reserve` and out of every caller — which is how a test about cleanup
# after a SIGKILL came to fail on host load rather than on anything the code
# under test did.
#
# Driven through the PUBLIC `remover` seam, which runs between the listing and
# the look at the NEXT candidate: that is precisely the peer's interleaving,
# and unlike a sleep-and-hope racer it lands every single time.
# ---------------------------------------------------------------------------

def _two_old_candidates(tmp_path):
    """Two sidecar-less candidates old enough to be reaped, sorted a < b."""
    a, b = tmp_path / "probe-a", tmp_path / "probe-b"
    old = time.time() - 86400
    for d in (a, b):
        d.mkdir()
        os.utime(d, (old, old))
    return a, b


def test_a_peer_removing_a_candidate_mid_sweep_does_not_crash_the_sweep(
        tmp_path):
    """The #1263 crash itself. `reap` must not die because it got the help it
    is designed to get."""
    a, b = _two_old_candidates(tmp_path)

    def peer_removes_b(d):
        if d == a:
            shutil.rmtree(b)

    rep = S.reap("probe-", remover=peer_removes_b, legacy_max_age_s=3600,
                 root=tmp_path)
    assert str(a) in rep.reaped, rep


def test_a_peers_removal_is_reported_as_the_PEERS_and_never_as_ours(tmp_path):
    """Surviving is half of it. `reaped` is this run's claim to have done the
    removal, and the only thing anyone reads it for is whether THIS reaper
    works — so a directory somebody else removed must never be counted there,
    and must not vanish from the report altogether either."""
    a, b = _two_old_candidates(tmp_path)

    def peer_removes_b(d):
        if d == a:
            shutil.rmtree(b)

    rep = S.reap("probe-", remover=peer_removes_b, legacy_max_age_s=3600,
                 root=tmp_path)
    assert str(b) in rep.vanished, (
        "a peer's removal was not reported at all, so a sweep that touched "
        "nothing and a sweep whose work was done for it read alike: %s"
        % (rep,))
    assert str(b) not in rep.reaped, (
        "this run took credit for a removal a peer did: %s" % (rep,))
    assert not any(p == str(b) for p, _ in rep.kept), (
        "a directory that is GONE was reported as one left standing: %s"
        % (rep,))


def test_a_YOUNG_candidate_a_peer_removed_is_not_called_a_legacy_leftover(
        tmp_path):
    """A vanished directory must not be judged by the sidecar-less rules at
    all. It has no sidecar because it has no anything — reasoning about its age
    or about pre-lock builds describes a directory that is not there."""
    a = tmp_path / "probe-a"
    a.mkdir()
    os.utime(a, (time.time() - 86400,) * 2)
    b = tmp_path / "probe-b"          # young, and NOT old enough to reap
    b.mkdir()

    def peer_removes_b(d):
        if d == a:
            shutil.rmtree(b)

    rep = S.reap("probe-", remover=peer_removes_b, legacy_max_age_s=3600,
                 root=tmp_path)
    assert str(b) in rep.vanished, rep
    assert not any(p == str(b) and "may be a peer between" in w
                   for p, w in rep.kept), (
        "a directory a peer had already removed was filed under the "
        "mkdtemp-race rule, which is about a directory that EXISTS: %s"
        % (rep,))


def test_the_peer_rule_does_not_swallow_a_sidecar_that_really_cannot_be_read(
        tmp_path):
    """THE OTHER DIRECTION, and the one that makes the fix worth having rather
    than a blanket `except`. "It is not there" is a peer doing its job; "it is
    there and I could not read it" is a fault, and the #1263 repair must keep
    saying so. Without this test the same green comes from catching every
    OSError and calling the directory vanished."""
    if os.geteuid() == 0:
        pytest.skip("root can open a 0-mode file, so the fault cannot be "
                    "staged and this control would be vacuous")
    d = tmp_path / "probe-unreadable"
    d.mkdir()
    lock = d / S.LOCK_NAME
    lock.write_text("")
    os.chmod(str(lock), 0)
    try:
        assert S._is_locked(lock) is None, (
            "the 0-mode sidecar was readable after all, so this control is "
            "not staging the fault it claims to")
        rep = S.reap("probe-", root=tmp_path)
        assert d.exists(), rep
        assert any(p == str(d) and "could not be opened" in w
                   for p, w in rep.kept), (
            "a REAL sidecar fault on a directory that is standing was filed "
            "as a peer's removal, which is the blanket-catch the #1263 fix "
            "exists to avoid: %s" % (rep,))
        assert str(d) not in rep.vanished, rep
    finally:
        os.chmod(str(lock), 0o600)


def test_a_directory_that_went_while_its_lock_was_being_opened_says_so(
        tmp_path):
    """The residual window: the sidecar was a file when we looked and the whole
    directory was gone by the `os.open`. It cannot be scheduled from outside
    the process, so `_is_locked`'s "cannot tell" answer is injected directly —
    what is under test is the CLASSIFICATION that follows it, which is the only
    part that was wrong."""
    d = tmp_path / "probe-racing"
    d.mkdir()
    (d / S.LOCK_NAME).write_text("")
    real_is_locked = S._is_locked

    def cannot_tell_because_it_went(lock):
        shutil.rmtree(d, ignore_errors=True)
        return real_is_locked(lock)

    S._is_locked = cannot_tell_because_it_went
    try:
        rep = S.reap("probe-", root=tmp_path)
    finally:
        S._is_locked = real_is_locked
    assert str(d) in rep.vanished, rep
    assert not any(p == str(d) and "could not be opened" in w
                   for p, w in rep.kept), (
        "a directory a peer had removed was reported as a sidecar that could "
        "not be opened, sending the next reader after a permissions fault "
        "that is not there: %s" % (rep,))
