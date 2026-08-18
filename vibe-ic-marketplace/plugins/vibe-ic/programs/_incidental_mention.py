#!/usr/bin/env python3
"""Incidental-mention guard for protocol / identity term matching.

Phase-1 decides a design's IDENTITY (``ic_name``) by testing whether
canonical protocol terms appear in the concatenated L1+L2 content blob.
Those tests were bare ``in`` substring tests, which have no left word
boundary, so a term matches when it is merely an INFIX of an unrelated
longer word:

    "DDR" in "The ADDRESS bus is 16 bits"        -> True   (ADDRESS)
    "DDR" in "LPDDR4 / GDDR6 comparison"         -> True   (LPDDR4)
    "CLE" in "NAND gate delay per CYCLE is 3ns"  -> True   (CYCLE)
    "ALE" in "full-SCALE input range"            -> True   (SCALE)
    "MR0" in "timer register TIMR0"              -> True   (TIMR0)

Consequence: a part that merely has an address bus, cites JEDEC (which
every ESD / packaging / PDK guide does), and mentions a memory
generation once in a comparison sentence has its ``ic_name`` overwritten
with that memory generation's canonical name — a confident
misclassification stamped into 14 L docs, steering every downstream step
that keys on ``ic_name`` or the derived IC class.

Two rules live here.

1. LEFT word-boundary anchoring (:class:`AnchoredBlob`). Deliberately
   NOT a full ``\\b...\\b``:

     * every observed false positive is a LEFT-boundary violation — the
       term sits inside a longer word (A|DDR, LP|DDR4, CY|CLE, TIM|MR0);
       requiring a non-word char to the left rejects all of them.
     * generation tokens are legitimately PREFIXES of longer real tokens
       ("DDR" is a true signal inside "DDR3"/"DDR4"), so a right-hand
       ``\\b`` would break genuine detection. Right-side continuation
       stays allowed.

   This also turns several hand-maintained sibling-mutex denylists
   (ONFI / LPDDR5 / HBM3 guards, each added reactively after an observed
   false positive) into structural correctness: "DDR" no longer matches
   "LPDDR5" at all.

2. Subject corroboration (:func:`subject_term`). Anchoring alone still
   lets a single incidental CITATION decide identity ("Unlike DDR3
   parts, this device ..."). A generation name must appear often enough
   to be the document's SUBJECT, not a passing reference.

Both rules are chip-AGNOSTIC: pure string/frequency rules keyed on word
shape. They encode no part, vendor, protocol or benchmark literal.
"""
from __future__ import annotations

import re

__all__ = ["AnchoredBlob", "subject_term", "IDENTITY_CORROBORATION_MIN"]


# Minimum left-anchored occurrences before a protocol GENERATION name is
# treated as the document's subject rather than a passing citation.
#
# Mirrors the threshold and the reasoning already established for the
# ic_name tier cascade ("a 3+ count signals 'this doc is about this part
# number'; <STANDARD> mentioned once is just a side reference"), and the
# same >=5 dominant-subject density the DDR4/DDR5 sibling mutex already
# uses. A real DDR3 / LPDDR5 / UFS spec names its own generation on
# nearly every page; an unrelated part cites it once, in one comparison
# sentence or one reference-list row.
IDENTITY_CORROBORATION_MIN = 3


def _anchored_finditer(text: str, term: str):
    return re.finditer(r"(?<!\w)" + re.escape(term), text)


class AnchoredBlob(str):
    """A ``str`` whose ``in`` test requires a LEFT word boundary.

    Behaves as a normal ``str`` everywhere else. ``.lower()`` /
    ``.upper()`` return an ``AnchoredBlob`` too, so case-folded phrase
    tests stay anchored.
    """

    __slots__ = ()

    def __contains__(self, term: object) -> bool:  # type: ignore[override]
        if not isinstance(term, str) or not term:
            return False
        return next(_anchored_finditer(str(self), term), None) is not None

    def lower(self) -> "AnchoredBlob":  # type: ignore[override]
        return AnchoredBlob(str(self).lower())

    def upper(self) -> "AnchoredBlob":  # type: ignore[override]
        return AnchoredBlob(str(self).upper())

    def count_anchored(self, term: str) -> int:
        """Left-anchored occurrence count of ``term``."""
        if not isinstance(term, str) or not term:
            return 0
        return sum(1 for _ in _anchored_finditer(str(self), term))


def anchored_count(blob: str, term: str) -> int:
    """Left-anchored occurrence count of ``term`` in ``blob``."""
    if not blob or not isinstance(term, str) or not term:
        return 0
    return sum(1 for _ in _anchored_finditer(str(blob), term))


def subject_term(blob: str, term: str,
                 minimum: int = IDENTITY_CORROBORATION_MIN) -> bool:
    """True iff ``term`` appears often enough to be the blob's SUBJECT.

    Guards identity-setting clauses whose only positive evidence is a
    generation name plus a standards-body citation — the shape that lets
    an incidental mention overwrite a design's ``ic_name``.
    """
    return anchored_count(blob, term) >= minimum
