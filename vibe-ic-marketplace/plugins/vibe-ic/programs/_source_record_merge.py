#!/usr/bin/env python3
"""Merge per-source parsed records so that SILENCE cannot overwrite SPEECH.

THE SHAPE THIS EXISTS FOR
-------------------------
A program reads N sources, parses each into ``{key: record}``, and folds them
together::

    merged = {}
    for src in sources:
        merged.update(parse(src))          # <-- last wins

``dict.update`` is last-wins, and the source list is almost always built by
``sorted()`` or a glob. So when two sources describe the same key and one of
them describes it EMPTILY, the winner is decided by **filename order**.

That is not a style complaint. "This source does not describe key K" and "key K
has nothing in it" are different facts, and last-wins collapses the first onto
the second. Every consumer downstream then reads an absence as a measurement.

MEASURED, on a real post-route project: six LEF files declared the same macro,
five carrying 61-65 obstruction rectangles and one carrying zero. ``sorted()``
put the empty one last, it won, the macro's obstructions vanished, and a
BLOCKING gate reported PASS on a layout with 28 real crossings. Reversing the
file order reversed the verdict. Nothing about the design had changed.

The direction of the error is the part that matters: a silent record makes the
merged evidence SMALLER, so the gate that consumes it finds LESS. On a blocking
gate that is a false PASS -- the failure mode you do not see.

THE RULE
--------
A source that says nothing about a key cannot displace a source that said
something about it.

ABSENCE IS NOT DENIAL, AND "CANNOT TELL" IS NEITHER
---------------------------------------------------
An empty record is not one fact. A source can produce one for three different
reasons, and collapsing them is the same mistake as last-wins, one level up:

  SILENT         the source named the key and contributed NOTHING about the
                 aspect being merged. A liberty ``cell`` whose pins carry no
                 ``direction`` -- a ``pg_pin``-only block -- is silent about
                 directions; the parser documents that it cannot express them.
                 Absence wearing the shape of a measurement.
  DENIES         the source named the key and MEASURED it empty. A LEF that
                 carries an ``OBS`` section declaring no routing-layer rect has
                 said "this macro obstructs nothing", which is a fact about the
                 macro, not a gap in the file.
  INDETERMINATE  an empty record whose reason CANNOT BE DECIDED from the input.
                 An L-doc that lists a byte with no bit rows may be declaring it
                 has none, or may be naming a byte whose rows live in the peer
                 document. Nothing in the JSON separates those.

The third one is the point. It is not a tidier name for silence and it is not a
weak denial: it is the state of not knowing which, and it gets its OWN state and
its OWN report line rather than being folded into either. Folding it into
"silent" claims the source said nothing when it may have measured a zero;
folding it into "denies" fabricates a measurement out of a blank.

Which one an empty record is cannot be inferred from the record -- only the
parser that produced it knows -- so the caller declares it with ``stance=``. The
DEFAULT is INDETERMINATE, deliberately: a caller who has not thought about it
gets the state that says "unclassified", never a silent promotion to either
side.

THE PROPERTY
------------
Stated so a test can hold it, and so a different correct implementation passes
the same test:

  P1  If ANY source supplies a substantive record for key K, the merged record
      for K is substantive.
  P2  The result is invariant under permutation of ``per_source``.
  P3  When two sources supply DIFFERENT substantive records for K, that is a
      real disagreement this function cannot resolve from its inputs. It is
      resolved by a STATED policy -- itself permutation-invariant -- and
      reported in the returned conflict list. Reporting an ambiguity is not the
      same as resolving it; the record says a choice existed and which way it
      was taken.
  P4  SILENT is UNCONDITIONAL: silence cannot displace content under ANY
      policy, because silence is not evidence and no policy should be able to
      turn it into some. DENIES is POLICY-GOVERNED: a measured empty against
      measured content is two sources disagreeing, so it goes through
      ``on_conflict`` like any other disagreement and is REPORTED as one.
      This is the whole cash value of the distinction -- P1 above is stated for
      SUBSTANTIVE records, and a denial is substantive even though it is empty.
  P5  INDETERMINATE takes the conservative branch -- it cannot displace content
      either, because an unproven denial is not a denial -- and every key where
      it did so is named in ``absences``. The outcome matches silence; the
      REPORT does not, because "I did not erase, and I do not know whether a
      real measurement was overridden" is a different thing to have to say.

WHAT COUNTS AS "SAYING NOTHING" IS THE CALLER'S TO DECLARE
----------------------------------------------------------
The default is the record's own truthiness, which is right when the record IS
the payload (``{cell: {pin: dir}}`` -- an empty pin map is silence).

It is WRONG when the record is a struct whose payload is one field::

    {"blocked": {}, "size": (12.0, 8.4), "overlap_area": 0.0}

That record is truthy and says nothing about obstructions. Only the caller
knows which field carries the meaning, so the caller passes ``content=``. This
is deliberately not guessed: a helper that inferred it would be wrong silently,
which is the failure this module exists to end.

WHICH WAY TO BREAK A TIE IS ALSO THE CALLER'S, AND IT IS NOT UNIVERSAL
---------------------------------------------------------------------
``on_conflict="richer"`` keeps the record with more content. That is the right
default here because it continues the same monotone direction as the rule
itself -- prefer evidence over its absence -- and because the consumers in this
repo are measurement programs whose error budget is dominated by under-reading.

``on_conflict="sparser"`` exists because on a BLOCKING geometry gate the two
errors are not symmetric in that direction. Under-reporting leaves a violation
unfound (a gap); over-reporting accuses metal of crossing an obstruction the
loaded variant never declared (a FABRICATED finding that stops a clean design).
A gate that blocks should pick the floor. See ``macro_obs_geometry_intersect_
check.merge_macro_obs``, which states that argument for its own domain.

So the direction is domain-dependent and this module refuses to have an opinion
about which domain you are in. It only guarantees that whichever you pick, the
answer does not change when the files are renamed.

The policy governs DENIALS too, and only denials -- never silence (P4). Which
is what makes the direction load-bearing rather than decorative: at the phase3
PDN planner, ``richer`` is the difference between honouring a declared blockage
and strapping supply metal across it, and ``on_conflict`` is one word. The
call-site test that pins that direction is part of the fix, not an extra.

chip-AGNOSTIC: pure container algebra. No PDK, vendor, process or design
literal appears here or can affect the result.
"""
from __future__ import annotations

import json
from typing import (Any, Callable, Dict, Hashable, Iterable, List, Mapping,
                    NamedTuple, Optional, Sized)

# The three reasons an empty record can be empty, plus the one that is not
# empty at all. Exported as constants, not spelled as bare strings at the call
# sites: a stance mistyped as a literal would be a policy nobody declared, and
# `stance=` rejects an unknown one for the same reason `on_conflict=` does.
SPEAKS = "speaks"
SILENT = "silent"
DENIES = "denies"
INDETERMINATE = "indeterminate"

__all__ = ["merge_source_records", "stable_repr", "MergeOutcome",
           "SPEAKS", "SILENT", "DENIES", "INDETERMINATE"]

_POLICIES = ("richer", "sparser")
_STANCES = (SILENT, DENIES, INDETERMINATE)


class MergeOutcome(NamedTuple):
    """What the merge produced, and everything it had to decide to produce it.

    Three fields rather than two because the third question is a different
    question: ``conflicts`` is "two sources disagreed and the policy picked",
    ``absences`` is "a source was empty and here is which KIND of empty it was".
    A caller that only wants the answer reads ``.merged``; one that has to
    report honestly reads the other two. Neither can be dropped into the other
    without losing the distinction this module exists to draw.
    """
    merged: Dict[Hashable, Any]
    conflicts: List[Dict[str, Any]]
    absences: List[Dict[str, Any]]


def stable_repr(obj: Any) -> str:
    """A representation that does not depend on dict insertion order.

    Used only to compare and to break ties deterministically -- never shown to
    a user as the value itself. ``sort_keys`` is what makes two dicts built in
    different orders compare equal, which is exactly the confusion this module
    is about.
    """
    try:
        return json.dumps(obj, sort_keys=True, default=repr)
    except Exception:
        return repr(obj)


def _substantive(value: Any) -> bool:
    try:
        return bool(value)
    except Exception:          # an object with a hostile __bool__
        return value is not None


def _size(value: Any) -> int:
    """How much a record says. Ties in this measure fall through to
    ``stable_repr``, so the ordering is total either way."""
    if isinstance(value, Sized):
        try:
            return len(value)
        except Exception:
            pass
    return 1 if _substantive(value) else 0


def _pick_stable(records: List[Any]) -> Any:
    """One of ``records``, chosen without reference to their order.

    The first when they all say the same thing (the ordinary case -- they are
    all ``{}``), otherwise the lexicographically smallest rendering. Never a
    blend: the answer must be a record some source actually supplied.
    """
    first = records[0]
    if all(stable_repr(r) == stable_repr(first) for r in records):
        return first
    return min(records, key=stable_repr)


def merge_source_records(
    per_source: Iterable[Optional[Mapping[Hashable, Any]]],
    *,
    content: Optional[Callable[[Any], Any]] = None,
    on_conflict: str = "richer",
    stance: Optional[Callable[[Any], str]] = None,
) -> MergeOutcome:
    """Fold ``per_source`` into one mapping under the rule above.

    Parameters
    ----------
    per_source :
        One parsed ``{key: record}`` mapping per source, in whatever order the
        caller discovered them. ``None`` entries are skipped, so a caller that
        could not read a source does not have to special-case it -- and, note,
        an unreadable source is silence too, and silence cannot erase.
    content :
        ``record -> payload``. Returns the part of the record that carries the
        meaning; the record is "substantive" when that part is truthy. Defaults
        to the record itself.
    on_conflict :
        ``"richer"`` (default) keeps the larger payload, ``"sparser"`` the
        smaller, when two sources disagree substantively. Both are
        permutation-invariant. Any other value is a programming error and
        raises -- silently accepting an unknown policy would put the order
        dependence straight back.
    stance :
        ``record -> SILENT | DENIES | INDETERMINATE``, consulted ONLY for a
        record whose payload is not substantive. Content is decided by the
        payload and is not the caller's to override: a record that says
        something SPEAKS, and returning ``SPEAKS`` for an empty payload raises
        rather than letting a caller declare a blank to be a measurement.
        Defaults to INDETERMINATE for every empty record -- the state that
        says "unclassified", which is the truth when nobody has classified it.

    Returns
    -------
    ``MergeOutcome(merged, conflicts, absences)``.

    Each conflict is ``{"key", "kind", "kept_size", "other_sizes", "policy"}``
    with ``kind`` in ``{"content-vs-content", "content-vs-denial"}``; each
    absence is ``{"key", "kind", "counts"}``. Both are sorted by
    ``(str(key), kind)``, so the reports are order-independent too -- a report
    that reordered when the files did would reintroduce the defect in the one
    place a reader goes to check for it.
    """
    if on_conflict not in _POLICIES:
        raise ValueError(
            f"on_conflict must be one of {_POLICIES}, not {on_conflict!r}")
    payload_of: Callable[[Any], Any] = content if content is not None else (lambda r: r)
    stance_of: Callable[[Any], str] = stance if stance is not None else (
        lambda _r: INDETERMINATE)

    def _stance(record: Any) -> str:
        got = stance_of(record)
        if got not in _STANCES:
            raise ValueError(
                f"stance must be one of {_STANCES}, not {got!r} -- an empty "
                f"record cannot be {SPEAKS!r}, and an unrecognised stance "
                f"would be a policy nobody declared")
        return got

    # Group first, reduce second. Folding in arrival order is what made the
    # answer depend on arrival order; grouping removes the possibility rather
    # than handling it.
    by_key: Dict[Hashable, List[Any]] = {}
    for one in per_source:
        if not one:
            continue
        for key, record in one.items():
            by_key.setdefault(key, []).append(record)

    merged: Dict[Hashable, Any] = {}
    conflicts: List[Dict[str, Any]] = []
    absences: List[Dict[str, Any]] = []

    for key, records in by_key.items():
        speaking = [r for r in records if _substantive(payload_of(r))]
        empties = [(r, _stance(r)) for r in records
                   if not _substantive(payload_of(r))]
        denying = [r for r, s in empties if s == DENIES]
        silent = [r for r, s in empties if s == SILENT]
        unsure = [r for r, s in empties if s == INDETERMINATE]
        counts = {SPEAKS: len(speaking), SILENT: len(silent),
                  DENIES: len(denying), INDETERMINATE: len(unsure)}

        def _note(kind: str) -> None:
            absences.append({"key": key, "kind": kind, "counts": dict(counts)})

        if not speaking:
            # Nobody described this key. The key still SURVIVES and stays empty
            # -- "every source calls this empty" is a real, reportable fact and
            # dropping the key would trade a silent under-check for a silent
            # no-check. What differs now is what we can SAY about it.
            if denying:
                # At least one source measured it empty, so the emptiness is
                # attested rather than merely unfilled. A measurement outranks
                # a blank for the purpose of WHICH record survives -- they are
                # all empty, so this changes nothing about the answer and
                # everything about whether the answer is evidence.
                merged[key] = _pick_stable(denying)
                _note("denied-everywhere")
            else:
                merged[key] = _pick_stable(records)
            if unsure:
                _note("indeterminate-empty")
            elif silent and not denying:
                _note("silent-everywhere")
            continue

        distinct: List[Any] = []
        seen: set = set()
        for r in speaking:
            sig = stable_repr(r)
            if sig not in seen:
                seen.add(sig)
                distinct.append(r)

        if len(distinct) == 1:
            # The ordinary case, and the one the defect broke: exactly one
            # source (or several agreeing sources) described this key, and it
            # now wins no matter where in the list it sat.
            kept = distinct[0]
        else:
            ordered = sorted(distinct,
                             key=lambda r: (_size(payload_of(r)), stable_repr(r)))
            kept = ordered[-1] if on_conflict == "richer" else ordered[0]
            conflicts.append({
                "key": key,
                "kind": "content-vs-content",
                "kept_size": _size(payload_of(kept)),
                "other_sizes": sorted(_size(payload_of(r))
                                      for r in distinct if r is not kept),
                "policy": on_conflict,
            })

        if denying:
            # P4. A DENIAL is a measurement, so denial-against-content is two
            # sources disagreeing -- not silence, and not this function's to
            # settle. It goes through the caller's STATED policy exactly like
            # any other disagreement, and it is REPORTED either way.
            #
            # `richer` keeps the content: a planner would rather refuse once
            # too often than strap metal across a blockage. `sparser` takes the
            # denial: a BLOCKING gate would rather miss a finding than
            # fabricate one against a variant that measured nothing there.
            # Under last-wins, neither of those choices existed -- the denial
            # was indistinguishable from a blank and the file order decided.
            floor = _pick_stable(denying)
            conflicts.append({
                "key": key,
                "kind": "content-vs-denial",
                "kept_size": _size(payload_of(kept if on_conflict == "richer"
                                              else floor)),
                "other_sizes": [_size(payload_of(floor if on_conflict == "richer"
                                                 else kept))],
                "policy": on_conflict,
            })
            if on_conflict == "sparser":
                kept = floor

        merged[key] = kept

        # P5. Silence and "cannot tell" both failed to displace the content --
        # same outcome, DIFFERENT things to have to report. The first is the
        # rule working as designed. The second is the rule working on an empty
        # nobody has classified, so it carries a residual: if that source was
        # in fact denying, a real measurement was just overridden and no policy
        # got to weigh in. Naming it is the only honest option available.
        if silent:
            _note("silence-could-not-erase")
        if unsure:
            _note("indeterminate-could-not-erase")

    conflicts.sort(key=lambda c: (str(c["key"]), c["kind"]))
    absences.sort(key=lambda a: (str(a["key"]), a["kind"]))
    return MergeOutcome(merged, conflicts, absences)
