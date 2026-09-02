#!/usr/bin/env python3
"""corpus_guard.py — a corpus test that SKIPPED must be able to say so
loudly in a shape that was supposed to exercise it (G15).

Corpus guards in this tree all open the same way::

    root = _PROGRAMS.parents[3] / "benchmark-data" / "ic"
    if not root.is_dir():
        pytest.skip("corpus not present")

Since #2019 (`bb861e2e19`, "the repo root carries the repo, not campaign
output") `benchmark-data/` is UNTRACKED at the tip, so that branch is taken
on every clean checkout and every guard in this class reports PASS-by-skip.
That is how #1974's completion contract could relabel four published cells
FAIL and stay invisible for two campaigns: the control that existed to catch
it could not be distinguished from a control that ran and agreed.

The silence is correct as a DEFAULT — an ordinary clean checkout genuinely
has no corpus and must not go red for it. What is wrong is that the silence
is also the answer in a shape that DECLARED a corpus. This module makes that
second case loud:

  * `VIBE_IC_BENCHMARK_DATA` set  — the run pointed at a corpus, so a guard
    that then found none measured nothing it was asked to measure;
  * `VIBEIC_REQUIRE_CORPUS` truthy — the run asserted outright that corpus
    guards must execute (the shape a landing check or a census should use).

In either shape `require_corpus()` FAILS instead of skipping, and the message
names which declaration armed it. Chip-AGNOSTIC: no design, PDK or vendor
literal appears here.
"""
#: MOVED HERE FROM `programs/` (G16). This module raises `pytest.skip` and
#: `pytest.fail`, so it can only ever run inside a pytest process — it has no
#: CLI, no `main()` and no exit code, and nothing outside `programs/tests/`
#: imports it. In `programs/` its `_guard` suffix put it in
#: `gate_is_wired_check`'s population (`_(check|lint|audit|guard|gate)$`), where
#: it was measured as "consulted by no automatic verdict" — correctly, because
#: `programs/tests/` is deliberately NOT a wiring source and a test importing a
#: gate is not the flow consulting it. It is a test helper and it now sits with
#: the other twenty-seven under `programs/tests/`, underscore-named like them.
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pytest

# Read the pointer name off the program that defines it rather than retyping
# it; `benchmark_evidence_structure_check` is where the corpus pointer's
# precedence contract lives.
try:  # pragma: no cover - import shape differs between callers
    from benchmark_evidence_structure_check import CORPUS_ENV
except ImportError:  # pragma: no cover
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from benchmark_evidence_structure_check import CORPUS_ENV

REQUIRE_ENV = "VIBEIC_REQUIRE_CORPUS"

_FALSE = {"", "0", "false", "no", "off"}


def _truthy(value: Optional[str]) -> bool:
    return value is not None and value.strip().lower() not in _FALSE


def armed(env: Optional[dict] = None) -> Optional[str]:
    """Return the declaration that makes a corpus skip a failure, or None.

    Two declarations arm the guard. `REQUIRE_ENV` is the explicit one. The
    corpus POINTER arms it too: a run that set `$VIBE_IC_BENCHMARK_DATA` has
    said a corpus exists, so a guard finding none is measuring nothing.
    """
    env = os.environ if env is None else env
    if _truthy(env.get(REQUIRE_ENV)):
        return REQUIRE_ENV
    if _truthy(env.get(CORPUS_ENV)):
        return CORPUS_ENV
    return None


def corpus_root(programs_dir: Path, env: Optional[dict] = None) -> Path:
    """The corpus root this run should read.

    The pointer wins over the in-tree path, matching
    `benchmark_evidence_structure_check`'s documented precedence.
    """
    env = os.environ if env is None else env
    pointed = env.get(CORPUS_ENV)
    if _truthy(pointed):
        return Path(pointed)
    return Path(programs_dir).resolve().parents[3] / "benchmark-data" / "ic"


def require_corpus(root: Path, what: str, env: Optional[dict] = None) -> Path:
    """Return `root`, or skip — unless a declaration says it must be there.

    `what` names the thing the caller wanted to measure, so the failure says
    what went unmeasured rather than only that a path was absent.
    """
    root = Path(root)
    if root.is_dir():
        return root
    why = armed(env)
    if why is None:
        pytest.skip(f"corpus not present: {what} ({root})")
    pytest.fail(
        f"CORPUS_GUARD_SKIPPED (G15): ${why} declares a corpus, but "
        f"{root} does not exist, so '{what}' measured nothing. A guard that "
        f"cannot be told apart from a guard that ran and agreed is not a "
        f"control — unset ${why} to run without the corpus, or materialise "
        f"the corpus at that path.")
    raise AssertionError("unreachable")  # pragma: no cover
