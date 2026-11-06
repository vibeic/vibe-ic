#!/usr/bin/env python3
"""E2E finding F-2: `--backend` drives no backend, including the ones that exist.

WHAT IS THERE
=============
`_ppa/backends/` ships five modules -- opensta, openroad, yosys, librelane,
orfs -- and `PPA_INTERFACES.md` §4 says each "parses one tool's output into
canonical records and does nothing else". `ppa_metric_extract.py` takes a
`--backend TOOL` flag. Nothing connects the two:

    if args.backend is not None:
        try:
            __import__(f"_ppa.backends.{args.backend}")
        except ImportError:
            ... rc=2, no such module
        ... "backend exists but ppa_metric_extract does not drive backends
             yet; the domain lane that owns it does"  -> rc=2

WHY THE REFUSAL IS RIGHT AND THE FLAG IS STILL BROKEN
=====================================================
Measured on `e36d81c0a` (v1.11.33): all six of `opensta openroad yosys
librelane orfs nosuchtool` return rc=2 with `[CANNOT CHECK]`. That is the
HONEST behaviour and the module comment says why -- emitting an empty bundle
for a tool nobody taught the system to read is the exact defect the contract
removes.

So this is not a lying gate. It is a declared seam that no test crosses, and
the consequence is what F-2 names: the flag was never exercised, so nothing
notices that a REAL backend and a MISSPELLED one produce the same answer. A
caller cannot tell `--backend opensta` (implemented, ready, not wired) from
`--backend openstaa` (a typo) by exit code, and both are 2.

WHAT THIS FILE ASSERTS
======================
Three things, and only the third is pinned:

  1. the seam is honest RIGHT NOW: a real backend and an unknown one both
     refuse, never silently produce an empty bundle. This is green and must
     STAY green -- it is the property that stops the fix from being "return 0
     and write nothing".

  2. a real backend and an unknown one are DISTINGUISHABLE, by message if not
     yet by code. Green today.

  3. `--backend <a module that exists>` actually extracts a record from that
     tool's artefact. RED today, by design, and pinned -- this is F-2 itself.

The backend list is DISCOVERED from `_ppa/backends/`, so a sixth backend added
tomorrow is covered without editing this file. Its emptiness is asserted
first, because a glob that finds nothing would make every arm below green over
a population of zero -- this file's own subject matter.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_TESTS = pathlib.Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_BACKENDS_DIR = _PROGRAMS / "_ppa" / "backends"

BACKENDS = sorted(p.stem for p in _BACKENDS_DIR.glob("*.py")
                  if not p.stem.startswith("_"))


def _run(args, timeout=120):
    return _pr.run([sys.executable, *args], capture_output=True,
                          text=True, cwd=str(_PROGRAMS))


def test_the_backend_package_is_populated():
    """The denominator. PPA_INTERFACES §4 names five backend modules; an empty
    glob would make every parametrized arm below vacuously green."""
    assert set(BACKENDS) >= {"opensta", "openroad", "yosys", "librelane",
                             "orfs"}, BACKENDS


def test_every_backend_module_imports_on_its_own():
    """Cheap, and it catches the thing that makes a seam impossible to wire.

    A backend that only imports when reached through a package `__init__`
    cannot be driven by `__import__(f"_ppa.backends.{name}")`, which is
    exactly how the seam reaches for it.
    """
    broken = []
    for b in BACKENDS:
        r = _run(["-c", f"import sys; sys.path.insert(0, '.'); "
                        f"__import__('_ppa.backends.{b}')"])
        if r.returncode != 0:
            broken.append((b, r.stderr.strip().splitlines()[-1:]))
    assert not broken, f"backend module(s) not importable by the seam: {broken}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
