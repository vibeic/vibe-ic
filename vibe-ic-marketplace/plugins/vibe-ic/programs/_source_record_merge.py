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

chip-AGNOSTIC: pure container algebra. No PDK, vendor, process or design
literal appears here or can affect the result.
"""
from __future__ import annotations

import json
from typing import (Any, Callable, Dict, Hashable, Iterable, List, Mapping,
                    Optional, Sequence, Sized, Tuple)

__all__ = ["merge_source_records", "stable_repr"]

_POLICIES = ("richer", "sparser")


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


def merge_source_records(
    per_source: Iterable[Optional[Mapping[Hashable, Any]]],
    *,
    content: Optional[Callable[[Any], Any]] = None,
    on_conflict: str = "richer",
) -> Tuple[Dict[Hashable, Any], List[Dict[str, Any]]]:
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

    Returns
    -------
    ``(merged, conflicts)``. Each conflict is
    ``{"key", "kept_size", "other_sizes", "policy"}``, sorted by ``str(key)``
    so the report itself is order-independent too.
    """
    if on_conflict not in _POLICIES:
        raise ValueError(
            f"on_conflict must be one of {_POLICIES}, not {on_conflict!r}")
    payload_of: Callable[[Any], Any] = content if content is not None else (lambda r: r)

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

    for key, records in by_key.items():
        speaking = [r for r in records if _substantive(payload_of(r))]

        if not speaking:
            # Every source is silent about this key. There is nothing to
            # preserve, but the answer must still not depend on order: keep the
            # first when they all agree, otherwise the lexicographically
            # smallest. (In practice they are all `{}` and this is the first.)
            first = records[0]
            merged[key] = (
                first if all(stable_repr(r) == stable_repr(first) for r in records)
                else min(records, key=stable_repr))
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
            merged[key] = distinct[0]
            continue

        ordered = sorted(distinct, key=lambda r: (_size(payload_of(r)), stable_repr(r)))
        kept = ordered[-1] if on_conflict == "richer" else ordered[0]
        merged[key] = kept
        conflicts.append({
            "key": key,
            "kept_size": _size(payload_of(kept)),
            "other_sizes": sorted(_size(payload_of(r))
                                  for r in distinct if r is not kept),
            "policy": on_conflict,
        })

    conflicts.sort(key=lambda c: str(c["key"]))
    return merged, conflicts
