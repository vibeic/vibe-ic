"""matrix_63x8.waivers — the accepted-gap registry.

A waiver is a public, dated admission that one cell of the 504 is NOT enforced
and WHY. It is not a way to make a red test green; it is a way to make an
unenforced cell *visible and machine-checkable* instead of silently absent.

====================================================================
HOW A WAIVER IS CONSUMED
====================================================================
A waived cell's test is marked::

    @pytest.mark.xfail(strict=True, reason=waiver.reason)

``strict=True`` is REQUIRED and is the entire anti-rot mechanism: the moment
the underlying gap is fixed and the predicate starts passing, the suite goes
**red** on XPASS and forces the waiver's removal. A non-strict xfail rots
silently forever, which is the same silent-absence disease in a different
costume.

====================================================================
WHAT COUNTS AS A REASON
====================================================================
``reason`` must say what a program *cannot decide* and why, in terms someone
who has never seen the cell can check. ``evidence`` must be independently
verifiable: a ``path:line``, a measured value with the command that produced
it, or a decision reference.

    GOOD  reason:   "The gate dispatches through __import__(f'{name}_protocol_synth');
                     the set of reachable names is data-dependent on L3_CMD_PROTOCOL
                     at runtime, so no static predicate can enumerate the call sites."
          evidence: "programs/rtl_dispatch.py:214 — __import__(f'{proto}_protocol_synth')"

    GOOD  reason:   "Deciding this needs a real converged project tree; the
                     required artefact is produced only by a tool absent from CI."
          evidence: "`which verilator` -> rc=1 on 192.168.1.120; measured 2026-07-25"

    BAD   "not implemented yet"          - says nothing checkable
    BAD   "too hard"                     - says nothing checkable
    BAD   "flaky"                        - names a symptom, not a cause
    BAD   "covered elsewhere"            - then point at it in `evidence`, or
                                           it is not covered

====================================================================
THIS TUPLE STARTS EMPTY AND IS APPLIED CENTRALLY
====================================================================
The eight dimension modules share this worktree. A sibling that needs a waiver
**reports it to the orchestrator in its return value** and does NOT edit this
file — concurrent edits to a shared registry lose entries. The orchestrator
applies them in one pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Union

from . import flowref
from .flowref import StepId


@dataclass(frozen=True)
class Waiver:
    """One accepted, evidence-backed gap in the 504-cell matrix."""

    step_id: Union[str, int]
    dim: int
    reason: str
    evidence: str

    @property
    def key(self) -> Tuple[str, int]:
        return (flowref.normalize_id(self.step_id), self.dim)

    @property
    def label(self) -> str:
        return f"{flowref.normalize_id(self.step_id)}/d{self.dim}"

    @property
    def xfail_reason(self) -> str:
        """The string to hand ``pytest.mark.xfail(strict=True, reason=...)``."""
        return f"WAIVED {self.label}: {self.reason} [evidence: {self.evidence}]"


#: Phrases that are NOT reasons. Matched with WORD BOUNDARIES, not as bare
#: substrings — a naive ``"later" in reason`` also fires on "related" and
#: "translated", which is the same false-positive-by-adjacent-measurement error
#: this whole package exists to avoid. Checked by the meta-test so a
#: placeholder can never be smuggled in as an accepted gap.
FORBIDDEN_REASON_SUBSTRINGS: Tuple[str, ...] = (
    "not implemented",
    "todo",
    "tbd",
    "fixme",
    "too hard",
    "will fix later",
    "unknown",
)

_FORBIDDEN_RE = tuple(
    (phrase, re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", re.IGNORECASE))
    for phrase in FORBIDDEN_REASON_SUBSTRINGS
)

#: Minimum lengths. A one-word reason cannot be evidence-backed.
MIN_REASON_LEN = 40
MIN_EVIDENCE_LEN = 8


WAIVERS: Tuple[Waiver, ...] = ()


_BY_KEY: Dict[Tuple[str, int], Waiver] = {w.key: w for w in WAIVERS}


def waiver_for(step_id: StepId, dim: int) -> Optional[Waiver]:
    """The waiver at ``(step_id, dim)``, or ``None``. Accepts int or str ids."""
    return _BY_KEY.get((flowref.normalize_id(step_id), int(dim)))


def waivers_for_dim(dim: int) -> Tuple[Waiver, ...]:
    """Every waiver of one dimension, in registry order."""
    return tuple(w for w in WAIVERS if w.dim == int(dim))


def is_waived(step_id: StepId, dim: int) -> bool:
    return waiver_for(step_id, dim) is not None


def validate(waiver: Waiver) -> Tuple[str, ...]:
    """Return the list of problems with *waiver*; empty tuple means valid.

    Used by the meta-test. Kept as a function (not an ``__post_init__``) so a
    bad waiver produces a readable aggregate failure instead of an import-time
    explosion that hides every other problem.
    """
    problems = []
    if waiver.dim not in range(1, 9):
        problems.append(f"dim {waiver.dim!r} is not in 1..8")
    if not flowref.has_step(waiver.step_id):
        problems.append(f"step {waiver.step_id!r} is not declared in the flow yaml")
    reason = (waiver.reason or "").strip()
    evidence = (waiver.evidence or "").strip()
    if not reason:
        problems.append("reason is empty")
    elif len(reason) < MIN_REASON_LEN:
        problems.append(
            f"reason is {len(reason)} chars, under the {MIN_REASON_LEN}-char "
            f"floor — say what a program cannot decide and why"
        )
    for bad, rx in _FORBIDDEN_RE:
        if rx.search(reason):
            problems.append(f"reason contains the non-reason phrase {bad!r}")
    if not evidence:
        problems.append("evidence is empty")
    elif len(evidence) < MIN_EVIDENCE_LEN:
        problems.append(
            f"evidence is {len(evidence)} chars — needs a path:line, a measured "
            f"value, or a decision reference"
        )
    return tuple(problems)


def xfail_mark(step_id: StepId, dim: int):
    """The pytest mark for ``(step_id, dim)``, or ``None`` when not waived.

    Exists so that ``strict=True`` is decided HERE, once, instead of eight
    times by eight agents. A non-strict ``xfail`` rots silently forever: the
    gap gets fixed, the test starts passing, and nobody is told the waiver is
    now a lie. With ``strict=True`` an XPASS turns the suite red and forces the
    waiver's removal — that is the entire anti-rot mechanism, and it is not a
    per-module style choice.

    Usage::

        mark = waivers.xfail_mark(sid, 4)
        if mark:
            request.applymarker(mark)

    or at collection time::

        pytest.param(sid, marks=[m] if (m := waivers.xfail_mark(sid, 4)) else [])
    """
    import pytest  # local import: the substrate stays importable without pytest

    w = waiver_for(step_id, dim)
    if w is None:
        return None
    return pytest.mark.xfail(strict=True, reason=w.xfail_reason)


__all__ = [
    "Waiver",
    "WAIVERS",
    "xfail_mark",
    "waiver_for",
    "waivers_for_dim",
    "is_waived",
    "validate",
    "FORBIDDEN_REASON_SUBSTRINGS",
    "MIN_REASON_LEN",
    "MIN_EVIDENCE_LEN",
]
