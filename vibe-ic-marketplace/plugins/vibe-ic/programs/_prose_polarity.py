"""The ONE negation vocabulary for prose extraction. vibe-ic#712.

WHY THIS FILE EXISTS
--------------------
A prose extractor that reads a value out of a sentence without regard for the
POLARITY of that sentence publishes a denied value as a declaration. It happened
twice in one day, in two fields, found by the same activity — retargeting a
design from one process to another:

    #706  pdk_target           "This block is NOT targeted at <PDK>."
                               -> pdk_target = <PDK>, outranking the design's own
                                  labelled declaration three lines below.
    #711  die_area_budget_um   a document saying the old fixed die "has NO
                               meaning here and is REMOVED, not translated"
                               re-declared that exact rectangle as a mandate.

Neither is cosmetic: `die_area_budget_um` sits above `auto` in the phase-3
runner's documented precedence, so the design is hard-sized onto a die belonging
to a different chip — citing the design's own document as the authority.

AND EACH FIX BUILT ITS OWN COPY OF THE VOCABULARY. `_FOUNDRY_NEGATION_RE` in
`phase1_doc_one_shot_runner` and `_DIE_NEGATION_RE` in `floorplan_contract`.
#711's own comment records the reason it had to be written a second time: the
polarity blindness "survived in the neighbouring field of the same document".
Two copies drift, and the second one is written only after the field it guards
has already published a wrong value. This repo has already named that failure
once, in `eda_report_audit`: *"three private copies of it is how the divergence
happened."*

So the vocabulary lives here, once. A caller keeps its own SCOPE rule — how far
around the match to look, and what to blank first — because that genuinely
differs per field: a die statement carries harmless parenthetical qualifiers and
its denial usually sits in a neighbouring sentence, while a foundry-context
match is judged inside a bounded span. What must not differ is the list of words
that mean "no".

chip-AGNOSTIC: pure structural negation vocabulary in English and Chinese. No
chip, PDK, vendor, foundry or part number appears here or ever should.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

#: Words that DENY. Split into two tiers because they are not interchangeable:
#: a bare "no"/"not" negates the clause it sits in, while "removed"/"superseded"
#: retires a value that the document still prints in full.
_DENIAL_CORE = (
    r"\bnot\b|\bno\b|\bnone\b|\bwithout\b|\bexcluding\b|\bexclud\w*\b|"
    r"\bnever\b|\bnon-?\b|非|无|無|不|否"
)
_DENIAL_RETIRED = (
    r"\bremoved\b|\bobsolete\b|\bsupersed\w*\b|\bn/a\b|\binapplicable\b|"
    r"\bdeprecated\b|\bno longer\b|\bdoes not apply\b"
)

#: The two tiers, and both together. `NEGATION_RE` is what a caller wants unless
#: it has a measured reason to want one tier.
DENIAL_CORE_RE = re.compile(f"(?:{_DENIAL_CORE})", re.IGNORECASE)
DENIAL_RETIRED_RE = re.compile(f"(?:{_DENIAL_RETIRED})", re.IGNORECASE)
NEGATION_RE = re.compile(f"(?:{_DENIAL_CORE}|{_DENIAL_RETIRED})", re.IGNORECASE)

#: Bracketed text, which carries qualifiers rather than the statement's polarity
#: ("die area (not including seal ring)"). A caller that blanks these before
#: looking for a denial is following #711's measurement, not a style preference.
BRACKETED_RE = re.compile(r"\([^()]*\)|\[[^\[\]]*\]|\{[^{}]*\}")


def blank_bracketed(text: str) -> str:
    """`text` with bracketed spans replaced by spaces of the same length.

    Length-preserving on purpose, so a caller's offsets stay valid."""
    return BRACKETED_RE.sub(lambda m: " " * len(m.group(0)), text or "")


def is_denied(span: str, *, ignore_bracketed: bool = True) -> Optional[str]:
    """The denial word in `span`, or None.

    Returns the WORD rather than a bool so a caller can say which one it found —
    a refusal that names its evidence is checkable; a bare False is not."""
    hay = blank_bracketed(span) if ignore_bracketed else (span or "")
    m = NEGATION_RE.search(hay)
    return m.group(0) if m else None


def sentence_scope(text: str, start: int, end: int,
                   *, before: int = 240, after: int = 120) -> Tuple[int, int]:
    """A window around [start, end) bounded by sentence punctuation.

    The default reaches FURTHER BACK than forward because a denial is written
    before the value it retires far more often than after it — measured in #711,
    where the denial did not live in the same sentence as the number.
    """
    lo = max(0, start - before)
    hi = min(len(text or ""), end + after)
    seg = (text or "")[lo:start]
    for p in (". ", "\n\n", "\n- ", "; "):
        i = seg.rfind(p)
        if i != -1:
            lo = max(lo, lo + i + len(p))
    return lo, hi
