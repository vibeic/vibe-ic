#!/usr/bin/env python3
"""_ppa_corpus.py — the corpus walk the five PPA record gates share.

WHY THIS MODULE EXISTS
======================
`ppa_head_to_head_check` takes `--corpus DIR` and resolves it through
`_corpus_location`, so it follows `$VIBE_IC_BENCHMARK_DATA` to a cloned corpus
and judges every record it finds. Its five siblings —

    ppa_contract_check          --contract       CONTRACT.json
    ppa_measurement_check       --coverage       BUNDLE.json
    ppa_feasibility_check       --candidates     CANDIDATES.json
    ppa_pareto_check            --candidates     CANDIDATES.json
    ppa_problem_integrity_check --baseline/--candidate  A.json B.json

— took an EXACT path and nothing else, so a record filed anywhere the caller
did not name was not judged at all. That asymmetry was nobody's decision; the
five and the sixth answer the same kind of question about the same kind of
artefact. This module is the corpus half of the sixth gate, factored out so the
five get it through the SAME seam rather than through five new ones — the same
argument `_corpus_location` itself makes about the location question.

WHAT IS COPIED FROM `ppa_head_to_head_check`, EXACTLY
====================================================
    the location seam      `_corpus_location.resolve()` / `.refuse()`, so all
                           six follow one pointer and print one vocabulary
    the severity order     REFUSED > UNDETERMINED > OK. rc 2 is the LARGER
                           integer and the WEAKER verdict, so aggregating a
                           corpus with `max()` promotes a refusal to a pass;
                           :func:`worst_rc` is that gate's aggregator verbatim
    the vacuous arm        an empty corpus is rc 2 with the root NAMED, never
                           rc 0. Those five gates exist to refuse a vacuous
                           100% coverage, a frontier nobody recomputed and an
                           "every candidate feasible" over an empty list; a
                           corpus mode that turns "found nothing" into a pass
                           has destroyed the gate it was added to

WHAT IS DELIBERATELY NOT COPIED: THE RECORD GLOB
================================================
`ppa_head_to_head_check` finds its records with `**/*head_to_head*.json` — a
FILENAME test. The complaint that produced this module is precisely that a
record filed under another name is not judged, and a filename glob answers that
complaint with a smaller version of itself. So the walk here enumerates every
`*.json` under the corpus and selects on the DOCUMENT: its declared
`"schema"` key where the shape has one (PPA_INTERFACES §5 requires it as the
first key of every instance document), or its structure where it does not. A
record is judged because of what it IS, not because of what it was called.

The cost is disclosed rather than hidden: every corpus run prints the number of
JSON files it opened beside the number of records it selected, so "0 records"
can never be read as "0 files" or as "all clean".

A FILE THAT COULD NOT BE READ IS NOT A FILE THAT HELD NO RECORD
===============================================================
A `*.json` that does not parse is not thereby "not a PPA record" — nobody
looked. Those are counted, NAMED, and raise the corpus verdict to UNDETERMINED.
This is the same rule `_corpus_location` applies one level up to a pointer that
is set and wrong, and it is the rule that keeps "I could not look" from
arriving as "there are none".

TWO RECORDS FOR ONE IDENTITY IS A CONFLICT, NEVER A PICK
========================================================
The single most dangerous thing a corpus walk can do is take `records[0]`. A
gate that needs "the contract" and finds two of them has NOT found the
contract; it has found a disagreement, and choosing one buries it exactly the
way `_ppa/contract.py` refuses to bury a conflicting declared fact (PPA-C-003:
"this contract does not choose between them because choosing would bury the
disagreement inside a digest"). :func:`identity_conflicts` is that rule at
corpus scale: one identity claimed by two documents whose CONTENT differs is a
refusal that NAMES both paths and both digests. Two documents that are
byte-identical under that identity are a copy, not a disagreement — disclosed
as a note, never silently deduplicated, because a set whose size depends on how
many times somebody ran `cp` is its own defect.

chip-AGNOSTIC: path plumbing, JSON, and digests. No design, PDK, vendor, node
or SKU literal, and none is reachable from here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _corpus_location as _corpus  # noqa: E402  the one seam for all corpora
from _ppa import canonical_json as cj  # noqa: E402

#: PPA_INTERFACES.md §1. Repeated here rather than imported from any one gate so
#: that this module does not make five gates depend on a sixth.
RC_OK = 0
RC_REFUSED = 1
RC_UNDETERMINED = 2
RC_BAD_INVOCATION = 3

#: `ppa_head_to_head_check._SEVERITY`, verbatim and for its stated reason:
#: `flow_compliance_check.__check_program_exit_zero` maps rc 2 -> VACUOUS_PASS
#: and rc 1 -> FAIL, so 2 is the larger integer and the weaker verdict. Adding a
#: record to a corpus must never be able to SUBTRACT a refusal from it.
_SEVERITY = {RC_REFUSED: 2, RC_UNDETERMINED: 1, RC_OK: 0}


def worst_rc(rcs: Iterable[int]) -> int:
    """The corpus verdict: the single most severe record decides it."""
    worst = RC_OK
    for rc in rcs:
        if _SEVERITY.get(rc, _SEVERITY[RC_REFUSED]) > _SEVERITY[worst]:
            worst = rc if rc in _SEVERITY else RC_REFUSED
    return worst


class Scan:
    """What one corpus walk found, with its denominator attached.

    `files` is what was opened, `records` is what was selected and `unreadable`
    is what could not be decided either way. A caller that prints `len(records)`
    without `files` beside it has published a zero over a population nobody can
    size.
    """

    def __init__(self, root: Path, origin: str) -> None:
        self.root = root
        self.origin = origin
        self.files = 0
        self.records: List[Tuple[Path, Any]] = []
        self.unreadable: List[Tuple[Path, str]] = []

    def denominator(self, scanned: str) -> str:
        line = (f"{self.files} JSON file(s) opened under {self.root}, "
                f"{len(self.records)} {scanned} selected")
        if self.unreadable:
            line += f", {len(self.unreadable)} unreadable"
        return line


def open_corpus(named: Path, gate: str, scanned: str,
                may_be_absent: bool = False) -> Tuple[Optional[Path], int]:
    """``(corpus, 0)`` when the corpus can be walked, ``(None, rc)`` when not.

    A CORPUS THAT IS NOT THERE IS NOT AN EMPTY CORPUS. `Path.glob` yields
    nothing for a missing directory, so without this branch both print "0
    records" and both exit 2 — a denominator asserted over a population nobody
    searched. The decision is delegated to `_corpus_location.refuse`, which
    keeps a pointer that is SET AND WRONG (UNDETERMINED, never excused) apart
    from "the corpus lives in another repository" (a stated NO_CORPUS).
    """
    corpus, origin = _corpus.resolve(named, gate=gate, announce=True)
    if not corpus.is_dir():
        return None, _corpus.refuse(gate, named, corpus, origin, may_be_absent,
                                    scanned)
    return corpus, RC_OK


#: Every JSON document under the corpus. NOT a filename test — see the module
#: docstring. The selection happens on the parsed document.
RECORD_GLOB = "**/*.json"


def collect(corpus: Path, select: Callable[[Any], bool],
            origin: str = _corpus.NAMED) -> Scan:
    """Every document under `corpus` that `select` accepts, plus the denominator.

    `select` is handed the PARSED document. It must answer "is this one of the
    records this gate judges?" from the document's own declared schema or
    shape, never from its path.
    """
    scan = Scan(corpus, origin)
    for path in sorted(p for p in corpus.glob(RECORD_GLOB) if p.is_file()):
        scan.files += 1
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:      # noqa: PERF203
            scan.unreadable.append((path, f"could not be read: {exc}"))
            continue
        except json.JSONDecodeError as exc:
            scan.unreadable.append((path, f"is not JSON: {exc}"))
            continue
        try:
            wanted = bool(select(doc))
        except Exception as exc:                          # noqa: BLE001
            # A selector that raised has not answered "no"; it has failed to
            # answer, and the two must not reach the verdict as the same word.
            scan.unreadable.append(
                (path, f"could not be classified: {exc.__class__.__name__}: {exc}"))
            continue
        if wanted:
            scan.records.append((path, doc))
    return scan


def report_unreadable(gate: str, scan: Scan) -> int:
    """Print every file that could not be decided, and the rc it forces.

    RC_UNDETERMINED, never RC_OK: a file nobody could parse is not a file that
    held no record.
    """
    if not scan.unreadable:
        return RC_OK
    for path, why in scan.unreadable:
        print(f"[{gate}] CANNOT CHECK: {path} {why}. This file was NOT "
              f"established to hold no record — nobody could look at it.",
              file=sys.stderr)
    return RC_UNDETERMINED


def vacuous(gate: str, corpus: Path, scanned: str, scan: Optional[Scan] = None
            ) -> int:
    """The empty-corpus arm: rc 2, with the corpus root NAMED. Never rc 0.

    The five gates this serves exist to refuse a vacuous 100% coverage, a
    frontier nobody recomputed, and "every candidate is feasible" over an empty
    list. A corpus mode that answers "found nothing" with a pass has removed
    the only property those gates had.
    """
    denom = f" ({scan.denominator(scanned)})" if scan is not None else ""
    print(f"[{gate}] VACUOUS: the corpus at {corpus} carries no {scanned}, so "
          f"NOTHING WAS VALIDATED{denom}. This is NOT a pass: a gate that has "
          f"never met an artefact cannot have cleared one. rc=2.",
          file=sys.stderr)
    return RC_UNDETERMINED


def both_given(gate: str, exact: str, corpus: str) -> int:
    """rc 3 for an exact path AND a corpus in one invocation.

    Silently letting one win is how a caller who NAMED a document gets a
    verdict about a different one. `ppa_head_to_head_check` accepts both today
    and lets `--corpus` win without saying so; that is recorded as a request to
    the lander rather than copied here, because the point of a corpus mode is
    to widen what gets judged, not to quietly narrow it.

    rc 3, not 1 and not 2: PPA_INTERFACES §1 — a bad invocation is never a
    finding about a design, and never "not checked" either.
    """
    print(f"[{gate}] REFUSE (bad invocation): {exact} and {corpus} were both "
          f"given. One names a single document and the other names a "
          f"population; running either one silently would report a verdict "
          f"about something the caller did not ask about. Give exactly one. "
          f"rc=3.", file=sys.stderr)
    return RC_BAD_INVOCATION


def identity_conflicts(rows: Sequence[Tuple[Path, str, Any]], gate: str,
                       identity_name: str) -> Tuple[List[Dict[str, Any]],
                                                    List[Dict[str, Any]]]:
    """``(conflicts, copies)`` over ``(path, identity, content)`` rows.

    A CONFLICT is one identity claimed by two documents whose content digests
    differ: both cannot describe the same thing, and picking either buries the
    disagreement. A COPY is one identity claimed twice with identical content —
    a filesystem fact, disclosed and never silently folded away.

    Neither is decided here; this returns the rows and the caller attaches the
    verdict, for the same reason `_ppa.contract` names a conflict instead of
    resolving it.
    """
    by_identity: Dict[str, List[Tuple[Path, str]]] = {}
    for path, identity, content in rows:
        by_identity.setdefault(identity, []).append((path, cj.digest_of(content)))
    conflicts: List[Dict[str, Any]] = []
    copies: List[Dict[str, Any]] = []
    for identity in sorted(by_identity):
        seen = by_identity[identity]
        if len(seen) < 2:
            continue
        digests = {d for _, d in seen}
        row = {
            "identity_kind": identity_name,
            "identity": identity,
            "claimed_by": [{"path": str(p), "content_digest": d}
                           for p, d in sorted(seen, key=lambda x: str(x[0]))],
        }
        (conflicts if len(digests) > 1 else copies).append(row)
    return conflicts, copies


def print_conflicts(gate: str, conflicts: Sequence[Dict[str, Any]],
                    copies: Sequence[Dict[str, Any]]) -> int:
    """Print both lists and return the rc the conflicts force (1, else 0)."""
    for row in copies:
        where = ", ".join(c["path"] for c in row["claimed_by"])
        print(f"[{gate}] NOTE: {row['identity_kind']} {row['identity']} is "
              f"carried by {len(row['claimed_by'])} byte-identical "
              f"document(s): {where}. Reported rather than deduplicated — a "
              f"record set whose size depends on how many copies exist is its "
              f"own defect.", file=sys.stderr)
    for row in conflicts:
        where = "; ".join(f"{c['path']}={c['content_digest']}"
                          for c in row["claimed_by"])
        print(f"[{gate}] REFUSE: {row['identity_kind']} {row['identity']} is "
              f"claimed by {len(row['claimed_by'])} documents that DISAGREE: "
              f"{where}. This corpus does not choose between them: taking the "
              f"first match would bury the disagreement where nothing "
              f"downstream can see it. rc=1.", file=sys.stderr)
    return RC_REFUSED if conflicts else RC_OK
