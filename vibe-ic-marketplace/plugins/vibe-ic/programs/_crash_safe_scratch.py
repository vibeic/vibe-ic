#!/usr/bin/env python3
"""Scratch space whose cleanup does not depend on the process getting to run.

WHY (measured 2026-08-04, one parallel-agent session)
=====================================================
Two programs here allocate scratch space and clean it up in a ``finally``.  A
``finally`` runs on a clean exit and on an exception.  It runs on NEITHER of the
two ways a long agent session actually ends a subprocess — ``SIGKILL``, and a
harness tearing down a process group — and both happened:

    gate_cli_mutation_probe        left ``<gate>.py.probe-orig`` beside a gate
                                   whose entry point had been rewritten to
                                   return zero unconditionally.  Zero is what
                                   the flow reads as PASS, so every later reader
                                   of that checkout was measuring a gate that
                                   could no longer fail.  (The sentinel comment
                                   the probe injects is deliberately NOT spelled
                                   out here: `neutered_gate_tree_check` scans
                                   every shipped module for it, and a docstring
                                   that quotes it would be a permanent finding.)
    gate_host_independence_check   left 19 ``/tmp/hostindep-*/wt`` trees, each
                                   still REGISTERED as a git worktree of the
                                   shared repo.

The first is the dangerous one: a lie that reads green.  The second is only
litter until it is 19 registrations deep in a repo several agents share.

WHAT ACTUALLY SURVIVES A KILL
=============================
Nothing the dying process would have run.  What does survive is the KERNEL's
bookkeeping, and ``flock(2)`` is the piece of it that answers the question this
module needs: an advisory lock held on an open descriptor is released by the
kernel when the holder dies, *whatever* killed it.  So a scratch directory that
carries an flock'd sidecar can be asked "is your owner still alive?" by any
later process, and the answer is correct under SIGKILL — which is exactly the
case a ``finally`` cannot cover.

That turns cleanup from an obligation the dying process owes into a fact the
NEXT run can establish:

    reserve(prefix)   mkdtemp + take an exclusive flock on ``.owner.lock``
                      inside it, and hold it for the lifetime of the process.
    reap(prefix)      every sibling whose lock can be TAKEN had its owner die —
                      remove it.  Every sibling whose lock is HELD is left alone
                      and NAMED, because a cleanup that races a live peer is the
                      same class of damage one level over.

CONSERVATIVE BY CONSTRUCTION.  Three separate reasons to leave a directory
standing, and only one to remove it:

  * the lock is held            -> a live owner.  Never touched.
  * no lock file at all         -> written by a build that predates this module.
                                   Removed only when it is older than
                                   ``legacy_max_age_s`` AND no process on this
                                   host has a cwd or an argv pointing into it.
  * anything unexpected         -> left, and reported.

chip-AGNOSTIC: it reasons about processes and directories, nothing else.
"""
from __future__ import annotations

import errno
import fcntl
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional, Tuple

#: Name of the sidecar inside a reserved directory.  Chosen to sort first and to
#: be obviously not a payload file.
LOCK_NAME = ".owner.lock"

#: Name of the sidecar that serialises REAPERS against each other, one per
#: (root, prefix).  It is a FILE, so it is never a reap candidate.
REAP_LOCK_SUFFIX = ".reap.lock"

#: (root, prefix) pairs this PROCESS is already reaping.  `remover` is caller
#: code and may reach `reap` again; without this the second call would block on
#: a lock this same process holds, forever.
_REAPING: set = set()


def _reap_lock(base: "Path", prefix: str):
    """Hold the reaper lock for ``(base, prefix)`` for the duration of a walk.

    WHY A REAPER MUST NOT RACE ANOTHER REAPER, measured on this fleet with six
    concurrent probes against one ``/tmp``:

        3 of 6 runs ended with their OWN scratch still standing, and `reap`
        reported it as "no lock sidecar and only 0s old -- it may be a peer
        between mkdtemp and lock".

    That sentence was FALSE about what had happened. The directory had a lock
    sidecar; a PEER REAPER was part-way through `shutil.rmtree` on it, so the
    sidecar had already been unlinked when this walk stat'ed it, and the
    unlocked branch then read a half-removed directory as a peer that is just
    starting up. `rmtree(..., ignore_errors=True)` from two processes over one
    tree can also leave the directory itself standing. The caller is left
    unable to tell "kept because someone may be starting" from "gone because
    someone else removed it" -- and a test that asks "is my scratch gone?"
    fails for a reason that belongs to a peer.

    Serialised, the same six runs are 6 of 6 removed. The walk is short; the
    lock is held only around it, and `flock` is released by the kernel if a
    reaper dies, so a crashed reaper cannot wedge the next one.

    IF THE LOCK CANNOT BE TAKEN AT ALL -- a read-only root, an exotic
    filesystem -- the walk proceeds UNSERIALISED, which is exactly what shipped
    before this. Refusing to reap would trade a rare race for a certain leak.
    """
    import contextlib

    @contextlib.contextmanager
    def _held():
        key = (str(base), prefix)
        if key in _REAPING:            # re-entered through `remover`
            yield False
            return
        fd = None
        try:
            fd = os.open(str(base / (prefix + REAP_LOCK_SUFFIX)),
                         os.O_RDWR | os.O_CREAT, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError:
            if fd is not None:
                os.close(fd)
            yield False
            return
        _REAPING.add(key)
        try:
            yield True
        finally:
            _REAPING.discard(key)
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    return _held()


#: A directory with NO lock sidecar predates this module (or was made by hand).
#: It is reaped only once it is this old, so a peer that is mid-``mkdtemp`` —
#: created but not yet locked — cannot be swept out from under itself.  One hour
#: is far above the seconds-to-minutes any of these scratch trees live.
LEGACY_MAX_AGE_S = 3600


class Reservation(NamedTuple):
    """A scratch directory and the descriptor whose lock proves it is live."""
    path: Path
    fd: int

    def release(self) -> None:
        """Best-effort teardown for the CLEAN path.  Correctness does not
        depend on it — that is the whole point of this module."""
        try:
            os.close(self.fd)
        except OSError:
            pass
        shutil.rmtree(self.path, ignore_errors=True)


class ReapReport(NamedTuple):
    reaped: List[str]
    live: List[str]      # a peer is holding the lock: left alone, on purpose
    kept: List[Tuple[str, str]]   # (path, why it was not touched)
    #: A candidate that DISAPPEARED between the listing and the inspection —
    #: a peer finished and cleaned up in the window. Reported rather than
    #: swallowed: on a shared host it is the difference between "quiet" and
    #: "several other runs are alive right now", and a reaper that hides it
    #: cannot be told apart from one that is not running at all.
    vanished: List[str] = []


def _tmp_root() -> Path:
    return Path(tempfile.gettempdir())


def _is_locked(lock: Path) -> Optional[bool]:
    """True = a live owner holds it.  False = nobody does.  None = cannot tell.

    Opened O_RDWR because ``LOCK_EX`` on a read-only descriptor is refused on
    some kernels — which would report every directory as live and turn this
    module into a no-op that reads like a policy.
    """
    try:
        fd = os.open(str(lock), os.O_RDWR)
    except OSError:
        return None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK):
                return True
            return None
        # We took it, so no live owner had it.  Drop it again immediately: the
        # caller may decide NOT to reap, and holding a lock we are not using
        # would make the next run misread this directory as live.
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def _referenced_by_a_process(path: Path) -> bool:
    """Does any process on this host have a cwd or an argv pointing in here?

    The fallback for a directory with no lock sidecar.  Best-effort by nature —
    ``/proc`` entries for other users are unreadable — so it is used only to
    make the legacy sweep MORE conservative, never to justify a removal.
    """
    token = str(path)
    proc = Path("/proc")
    if not proc.is_dir():
        return True          # cannot look -> assume held
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if token in os.readlink(str(entry / "cwd")):
                return True
        except OSError:
            pass
        try:
            if token in (entry / "cmdline").read_bytes().decode(
                    "utf-8", "replace"):
                return True
        except OSError:
            pass
    return False


def reap(prefix: str, remover: Optional[Callable[[Path], None]] = None,
         legacy_max_age_s: int = LEGACY_MAX_AGE_S,
         root: Optional[Path] = None,
         exclude: Optional[Path] = None,
         reap_unlocked: bool = True) -> ReapReport:
    """Remove every ``<tmp>/<prefix>*`` whose owner is provably gone.

    ``remover`` runs before the tree is deleted, for scratch that also holds a
    registration somewhere else — a ``git worktree``, say, which must be
    unregistered or the repo keeps the entry forever.

    ``reap_unlocked=False`` turns the sidecar-less branch off entirely.  A
    directory with no lock cannot be attributed to a process, so age plus a
    ``/proc`` scan is all there is to go on — and a caller that KNOWS a peer
    running the pre-lock build may be alive can say so, and keep every
    unlockable directory instead of guessing.  Locked directories are decided
    exactly as before; only the guess is suppressed.
    """
    # `Path(root)` and not `root`: a caller that passes a string is the normal
    # case across a subprocess boundary, and the first test written against
    # this module found exactly that shape raising AttributeError in the reap.
    base = Path(root) if root else _tmp_root()
    with _reap_lock(base, prefix):
        return _walk(base, prefix, remover, legacy_max_age_s, exclude,
                     reap_unlocked)


def _walk(base: Path, prefix: str, remover, legacy_max_age_s: int,
          exclude: Optional[Path], reap_unlocked: bool) -> ReapReport:
    """The candidate walk itself. Called with the reaper lock held."""
    reaped: List[str] = []
    live: List[str] = []
    kept: List[Tuple[str, str]] = []
    vanished: List[str] = []
    try:
        candidates = sorted(p for p in base.iterdir()
                            if p.is_dir() and p.name.startswith(prefix))
    except OSError:
        return ReapReport([], [], [], [])
    for d in candidates:
      # THE LISTING IS A SNAPSHOT, AND PEERS ARE REMOVING THEIR OWN SCRATCH
      # WHILE WE WALK IT. `d.stat()` below raised FileNotFoundError the moment
      # a peer finished in that window, and the exception escaped `reserve()`
      # into the caller — a reaper that crashes because someone else tidied up.
      # Measured on this fleet (31 agents, one /tmp): it took down two tests of
      # an unrelated PR's verification run, and did not reproduce on a re-run,
      # which is exactly how it stayed invisible.
      #
      # A directory that is already gone needs no reaping. It is NOT `reaped`
      # (we did not remove it), NOT `kept` (it is not there to keep), so it is
      # reported as its own outcome.
      try:
          if exclude is not None and d.resolve() == exclude.resolve():
              continue
          lock = d / LOCK_NAME
          if lock.is_file():
              held = _is_locked(lock)
              if held is None:
                  kept.append((str(d), "its lock sidecar could not be opened"))
                  continue
              if held:
                  live.append(str(d))
                  continue
          else:
              if not reap_unlocked:
                  kept.append((str(d), "no lock sidecar, and the caller reports "
                                       "a peer that predates the lock may be "
                                       "alive — unattributable, so kept"))
                  continue
              age = time.time() - d.stat().st_mtime
              if age < legacy_max_age_s:
                  kept.append((str(d), "no lock sidecar and only %ds old — it may "
                                       "be a peer between mkdtemp and lock"
                                       % int(age)))
                  continue
              if _referenced_by_a_process(d):
                  kept.append((str(d), "no lock sidecar, but a live process "
                                       "references the path"))
                  continue
          if remover is not None:
              try:
                  remover(d)
              except Exception as exc:                       # noqa: BLE001
                  kept.append((str(d), "remover raised %s: %s"
                               % (type(exc).__name__, exc)))
                  continue
          shutil.rmtree(d, ignore_errors=True)
          if d.exists():
              kept.append((str(d), "rmtree left it standing"))
          else:
              reaped.append(str(d))
      except FileNotFoundError:
          vanished.append(str(d))
          continue
    return ReapReport(reaped, live, kept, vanished)


def reserve(prefix: str, remover: Optional[Callable[[Path], None]] = None,
            legacy_max_age_s: int = LEGACY_MAX_AGE_S,
            root: Optional[Path] = None) -> Tuple[Reservation, ReapReport]:
    """Reap abandoned peers, then take a fresh locked directory.

    Reaping FIRST is what makes the leak self-limiting: a killed run cannot
    clean up after itself, so the next one does it — the tree can hold at most
    the scratch of the runs that are still alive.
    """
    report = reap(prefix, remover, legacy_max_age_s, root)
    d = Path(tempfile.mkdtemp(prefix=prefix, dir=str(root) if root else None))
    lock = d / LOCK_NAME
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        shutil.rmtree(d, ignore_errors=True)
        raise
    os.write(fd, ("%d\n" % os.getpid()).encode())
    return Reservation(d, fd), report
