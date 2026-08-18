#!/usr/bin/env python3
"""A private, throwaway copy of the shipped tree — so a test can PLANT.

WHY THIS EXISTS
===============
Several tests in this suite have to show a shipped scanner reacting to a file
that is not in the commit: an unrouted gate, an unindexed program, a contract
violation. The direct way to do that is to write the file into the live
``programs/`` directory, run the scanner, and unlink it in a ``finally``.

That is correct exactly once — when nothing else is looking. The landing gate's
per-file recovery path runs one pytest session per file, many at a time, over
ONE shared checkout (``pytest_per_file_junit.py``). For the whole body of such
a test every concurrent session sees a ``programs/`` tree that is not the
commit's: an extra module, a missing one, or a rewritten ``INDEX.md``. Any
neighbour that ENUMERATES the tree — the index-freshness gate, the
every-program-has-a-test audit, the gate inventories, the ratchets that compare
a measured count against a recorded one — then reports the difference as a
finding about the branch.

The failure is worse than a flake because of the ``finally``: the plant is gone
before anyone looks, ``git status --porcelain`` is empty, and the red has no
evidence attached. It is the same defect class the scanners themselves exist to
catch — a number that could not be determined (is this tree the commit's?)
collapsed into one that is then reported as a measurement.

WHAT THIS GIVES INSTEAD
=======================
A directory that looks like a plugin root to the scanners, built by HARDLINKING
every shipped program rather than copying it. A hardlink is the same inode:
byte-identical content, ``is_file()`` true, not a symlink — so a scanner reading
source, hashing it, or refusing symlinks behaves exactly as it does on the real
tree. Planting into the farm creates a NEW inode and cannot touch the original.

It is not a git work tree. A test that needs ``git`` in the tree it plants into
needs something else; this helper is for the scanners that read the filesystem.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Optional

_HERE = Path(__file__).resolve().parent
PLUGIN = _HERE.parent.parent
PROGRAMS = PLUGIN / "programs"


def private_plugin(dest: Path, *, link_dirs: Iterable[str] = ("flow",),
                   programs_glob: str = "*.py",
                   include_tests: bool = False,
                   extra_programs: Optional[Iterable[str]] = None) -> Path:
    """Build a plugin-shaped tree under *dest* and return its root.

    ``programs/`` holds a hardlink per shipped ``programs/<glob>``; every name
    in *link_dirs* is symlinked to the real directory of that name, because the
    scanners only READ those (flow yaml, skills) and a symlinked directory
    keeps the farm cheap.
    """
    root = dest / "plugin"
    progs = root / "programs"
    progs.mkdir(parents=True, exist_ok=True)
    for src in sorted(PROGRAMS.glob(programs_glob)):
        if src.is_file():
            os.link(src, progs / src.name)
    for name in extra_programs or ():
        src = PROGRAMS / name
        if src.is_file() and not (progs / name).exists():
            os.link(src, progs / name)
    if include_tests:
        tests = progs / "tests"
        tests.mkdir(exist_ok=True)
        for src in sorted((PROGRAMS / "tests").glob("*.py")):
            if src.is_file():
                os.link(src, tests / src.name)
    for name in link_dirs:
        real = PLUGIN / name
        if real.is_dir() and not (root / name).exists():
            (root / name).symlink_to(real, target_is_directory=True)
    return root


def assert_live_tree_unplanted(pattern: str) -> None:
    """No file matching *pattern* may be left in the live programs dir.

    Called by the tests that used to plant there, so a re-introduction is a
    failure of the test that caused it rather than of whichever neighbour
    happened to be scanning at the time.
    """
    strays = sorted(p.name for p in PROGRAMS.glob(pattern))
    assert not strays, (
        f"{strays} were planted into the live programs dir. A concurrent "
        f"pytest session enumerating programs/ counts them as this branch's, "
        f"and the cleanup that removes them also removes the evidence.")
