#!/usr/bin/env python3
"""_ratchet_baseline.py — a ratchet that FAILS when it tightens is broken.

WHY THIS MODULE EXISTS
======================
A shrink-only baseline is a debt register: the recorded set may lose members
(the debt was paid) and may never gain them (that is a regression). Three
hygiene gates in this tree carry one, and all three reacted to a SHRINK the
same wrong way — they printed

    [NOTE] baseline shrank — now wired: <name>. Re-run with --write-baseline.

and, in `flow_gate_enforcement_audit`, they FAILED on it outright.

Two defects, one shape:

  1. A GATE THAT FAILS WHEN DEBT IS PAID punishes every improvement, so the
     cheapest way to keep it green is to never fix anything. A ratchet whose
     tightening direction costs the operator something is not a ratchet.
  2. THE REMEDY IT NAMES IS THE ONE THAT LAUNDERS. `--write-baseline` records
     whatever this run measured — the departures AND the arrivals. At the
     moment of decision nobody can tell a paid debt from a fresh regression,
     so a blanket rewrite erases both. Training the operator to reach for it
     on every shrink is training them to erase regressions on the days a
     shrink and a regression land together.

MEASURED, on the tree this module was written against, defect 2 was not
hypothetical: `prose_polarity_consulted_check` reported `polarity-blind 213
(baseline 213)` while ONE entry had left the set and ONE had joined it. Both of
that gate's older siblings guarded `--write-baseline` with

    if prev and len(now) > len(prev): refuse

which is a COUNT and not a membership test, so that swap wrote cleanly: the
paid debt would have been removed and a brand-new offender recorded as
accepted debt, at constant size, with no diff a reader could question.
`flow_gate_enforcement_audit` had already removed exactly this hole from
itself under vibe-ic#900 ("RATCHET ON MEMBERSHIP, NOT ON COUNT"); the other
two still carried it.

THE ASYMMETRY IS IN THE CODE, NOT IN OPERATOR DISCIPLINE
========================================================
    recorded set GREW       -> FAIL. Unchanged. That is the whole point.
    recorded set SHRANK     -> PASS, and the shrink is REPORTED: which entries
                               left, and by how much.
    recorded set UNCHANGED  -> PASS.

`shrunk()` is the recording, and it is add-proof by construction rather than
by a guard that has to be remembered: the set it returns is
`previous & current`, which is a SUBSET of `previous` for every possible input.
An entry this run measured for the first time is by definition absent from
`previous`, so no argument to this function can put it in the result. There is
no flag, no threshold and no reason string that changes that.

`write_shrunk()` re-establishes the same property at the point of writing, on
the finished document rather than on the list: every register it is given must
be a subset of what that register previously recorded, or nothing is written.
A caller that builds its document from something other than `shrunk()` is
refused there, so the invariant does not depend on each call site getting it
right.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
=========================================
It does not write during a verdict run, and no caller may make it. MEASURED:
`tools/ci/repo_hygiene_gates.sh` runs INSIDE the whole-repo
`suite_write_guard.py` bracket opened at `tools/gatekeeper-land.sh:690`
(`full:write-guard-baseline`), and that guard BLOCKS (rc 1) on any tracked
write. A gate that rewrote its own tracked register while producing a verdict
would refuse the very landing that carried the fix — and it would be the
"a hygiene stage rewrote the tree it was auditing" family the guard was built
for (#1029). So the tightening is reported on the verdict path and recorded on
a separate, explicit, add-proof path.

chip-AGNOSTIC: pure set algebra over opaque strings and a JSON write. No chip,
PDK, vendor, node or field literal appears here or can.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Union

import _atomic_artefact as _atomic

__all__ = [
    "ShrinkRefused",
    "departed",
    "shrunk",
    "write_shrunk",
    "report_line",
    "RECORD_FLAG",
]

#: The flag every caller exposes for the recording path. One spelling, so the
#: sentence a gate prints and the argument the operator types cannot drift.
RECORD_FLAG = "--record-shrink"


class ShrinkRefused(Exception):
    """A write was asked to ADD an entry to a shrink-only register.

    Raised rather than returned. A caller that ignores a return value has
    written the file anyway, and the whole property this module exists to hold
    is that no code path — including a careless one — can add.
    """


def _norm(values: Iterable[Any]) -> List[str]:
    return sorted({str(v) for v in values})


def departed(previous: Iterable[Any], current: Iterable[Any]) -> List[str]:
    """Entries the register records that this run did NOT measure as offending.

    These are the paid debts, and they are what a gate names when it reports a
    tightening. Sorted, deduplicated, and stringified so a register written
    with a stray duplicate does not report the same payment twice.
    """
    return sorted(set(_norm(previous)) - set(_norm(current)))


def shrunk(previous: Iterable[Any], current: Iterable[Any]) -> List[str]:
    """The register AFTER the tightening: `previous` minus what left it.

    THE ADD-PROOF STEP. The value is `previous & current`, so it is a subset of
    `previous` for every possible pair of arguments — an entry that appears
    only in `current` is one this run measured for the first time, which is a
    REGRESSION, and a regression is failed by the reading path rather than
    recorded by this one.

    Note what this is NOT: it is not `current`. Writing `current` is
    `--write-baseline`, and the difference between the two expressions is the
    entire difference between recording a payment and granting an amnesty.
    """
    return sorted(set(_norm(previous)) & set(_norm(current)))


def write_shrunk(path: Union[str, Path],
                 doc: Mapping[str, Any],
                 *,
                 previous_by_register: Mapping[str, Iterable[Any]],
                 ensure_ascii: bool = True) -> List[str]:
    """Write `doc` atomically, refusing if any register in it GREW.

    `previous_by_register` maps each shrink-only register name in `doc` to the
    set that register held BEFORE this run. Every one of them must be present
    in `doc`, must be a list, and must be a subset of its previous value.

    The check is on the DOCUMENT, deliberately, and not on the list a caller
    passed to `shrunk()`. A gate builds its own register document — it has
    comments, sizes and a second register to carry — and a gate that built one
    register with `shrunk()` and the other with `current` would satisfy every
    check made one level up. Here there is nothing left to get wrong: what is
    about to reach the disk is what is measured.

    Returns the sorted register names that were written, so a caller can say
    what it recorded. Raises `ShrinkRefused` — and writes NOTHING, not even
    the registers that were clean — if any register gained an entry.
    """
    grew: Dict[str, List[str]] = {}
    for name, prev in previous_by_register.items():
        if name not in doc:
            raise ShrinkRefused(
                f"register {name!r} is named as shrink-only but is absent from "
                f"the document about to be written. A register that vanishes "
                f"is not a register that shrank: every recorded entry would "
                f"read as paid on the next run.")
        value = doc[name]
        if not isinstance(value, (list, tuple)):
            raise ShrinkRefused(
                f"register {name!r} must be a list, not "
                f"{type(value).__name__}.")
        added = sorted(set(_norm(value)) - set(_norm(prev)))
        if added:
            grew[name] = added
    if grew:
        detail = "; ".join(
            f"{name} gained {len(v)}: " + ", ".join(v[:8])
            + (" ..." if len(v) > 8 else "")
            for name, v in sorted(grew.items()))
        raise ShrinkRefused(
            f"refusing to write: the recorded set GREW. This is a shrink-only recording and the "
            f"document ADDS entries — {detail}. An entry may leave a debt "
            f"register when this run measured that it no longer offends; it "
            f"may never join one here. A new offender is a finding, and the "
            f"reading path fails it.")
    _atomic.write_text(
        Path(path),
        json.dumps(dict(doc), indent=2, ensure_ascii=ensure_ascii) + "\n")
    return sorted(previous_by_register)


def report_line(label: str, left: Sequence[str],
                before: int, after: int, *, limit: int = 6) -> str:
    """The sentence a gate prints when it measures a tightening.

    It names the entries and the size change, because "the baseline shrank" on
    its own is the disclosure a reader cannot check. It names no flag whose
    other effect is to erase a regression.
    """
    shown = ", ".join(left[:limit]) + (" ..." if len(left) > limit else "")
    return (f"  [TIGHTENED] {label}: {len(left)} entr"
            f"{'y' if len(left) == 1 else 'ies'} left the recorded set "
            f"({before} -> {after}) — {shown}")
