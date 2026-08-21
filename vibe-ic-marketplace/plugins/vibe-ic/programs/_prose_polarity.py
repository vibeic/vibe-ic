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

So the vocabulary lives here, once. What must not differ is the list of words
that mean "no".

SCOPE LIVES HERE TOO, AND FOR THE SAME REASON (vibe-ic#790). The original note
here said a caller keeps its own scope rule. `sentence_scope` was written to be
that shared rule and then left half-written — it clamped the reach BACKWARD at a
sentence break and let the FORWARD reach run to a flat character count that
stopped at nothing. The reach is one rule now, symmetric, with `extra_breaks`
for the one thing that really is per-caller: what ends a RECORD in input that is
not prose.

`sentence_scope` NOW HAS TWO CALLERS: `drc_vacuous_pass_check._record_span` and
`l_doc_consumer_contract.framed_hits` (vibe-ic#1021 — the framing window there
was a flat character count that crossed full stops, so a hit in one sentence
borrowed its framing from the next; it now takes the reach from here rather
than growing a private copy of "where does a sentence end"). It was written and
corrected while the first caller was still an unlanded branch, and the sentence
here used to say the function had no caller at all — true then, and the reason
the correction moved no shipped verdict: the defect was latent, in the strong
sense that no code path reached it. That sentence is retired rather than
quietly left standing, because a claim a reader has to take on faith is the
shape #712 exists to remove, and a test enforces the match.

The caller is the reason `extra_breaks` exists, and the sequence is worth
keeping: that branch first clamped its own forward reach IN ITS OWN FILE — the
same divergence-by-private-copy this module exists to end. The reach was fixed
here instead, the caller deleted its copy, and it now passes `("\\n", ". ",
"; ")` as `extra_breaks` and nothing else. It was MEASURED identical over every
span its corpus drives before the copy was removed.

The other modules that import this one take `NEGATION_RE`, `DENIAL_CORE_RE`,
`blank_bracketed` and `is_denied`, none of which the reach change touched —
and, since #1021, `l_doc_consumer_contract` takes the reach itself.

Note which way that half-written rule failed. Publishing a denied value (#706,
#711) is loud once someone looks. Retracting a value nothing denied is SILENT:
the extractor reports less than it read and no gate goes red.

chip-AGNOSTIC: pure structural negation vocabulary in English and Chinese. No
chip, PDK, vendor, foundry or part number appears here or ever should.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional, Tuple

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
    text = text or ""
    # Every alternative in `BRACKETED_RE` needs an OPENING bracket, so a text
    # holding none of them cannot match and `sub` would return it unchanged.
    # Sound fast reject, not a policy — it changes speed only, and it matters
    # because `sentence_scope` calls this once per match on a hot path.
    #
    # MEASURE THE RIGHT QUANTITY. `sentence_scope` got materially more expensive
    # here, and how much depends entirely on the harness:
    #   * THE FUNCTION IN ISOLATION, called on every match with nothing
    #     amortising it — +186% bracket-free, +1126% bracket-dense, +305% on
    #     realistic prose (4,000 calls each; ~1.1us -> 3.0/13.4/4.4us). This
    #     reject is what keeps the bracket-free case from joining the third.
    #   * THROUGH A CALLER that gates the consult behind a whole-text pre-scan
    #     and spreads it over a real report — +8.6% end to end (1.115 -> 1.211 s
    #     on a 120,000-record, 1.79 MB report).
    # Neither number refutes the other; they answer different questions. Quote
    # the harness with the figure or the next reader will measure one and think
    # the other was wrong.
    if not ("(" in text or "[" in text or "{" in text):
        return text
    return BRACKETED_RE.sub(lambda m: " " * len(m.group(0)), text)


def is_denied(span: str, *, ignore_bracketed: bool = True) -> Optional[str]:
    """The denial word in `span`, or None.

    Returns the WORD rather than a bool so a caller can say which one it found —
    a refusal that names its evidence is checkable; a bare False is not."""
    hay = blank_bracketed(span) if ignore_bracketed else (span or "")
    m = NEGATION_RE.search(hay)
    return m.group(0) if m else None


#: What ENDS A SENTENCE — the one break set, applied IDENTICALLY in both
#: directions. Every member is a sentence terminator followed by a boundary, or
#: a structural break that ends a prose block. Two entries that a reader will
#: look for are deliberately absent:
#:
#:   ";"  a semicolon JOINS two independent clauses into ONE sentence. "The old
#:        floorplan is removed; the die area 1200 x 900 um." is a single
#:        statement whose denial governs its number, and treating "; " as an end
#:        loses it — MEASURED, see `test_issue712_prose_polarity`. It was in the
#:        original backward set, which is why that loss was live.
#:   "\n" a bare newline is a SOFT WRAP in a prose document, not a sentence end.
#:        In a machine-generated report it IS a record boundary — but that is a
#:        property of the caller's input, not of English, so the caller declares
#:        it through `extra_breaks` rather than every prose reader paying for it.
SENTENCE_BREAKS: Tuple[str, ...] = (". ", "! ", "? ", "\n\n", "\n- ")


def sentence_scope(text: str, start: int, end: int,
                   *, before: int = 240, after: int = 240,
                   extra_breaks: Iterable[str] = ()) -> Tuple[int, int]:
    """A window around [start, end) bounded by sentence punctuation ON BOTH SIDES.

    THE WINDOW IS THE SENTENCE THE MATCH SITS IN. A denial retracts the value it
    genuinely denies and nothing else, so the reach must be the same rule in both
    directions: everything up to the last break before the match, everything up
    to the first break after it.

    THIS USED TO CLAMP BACKWARD ONLY (vibe-ic#790). `hi` was a flat character
    count that stopped at nothing, so a denial in a LATER, UNRELATED statement
    retracted this one's number — `cells: 87` suppressed by a `no drc errors
    found` printed two records away. That direction is the quiet one: nothing
    goes red, the caller simply publishes less than it read. The window this
    returns moves on 67.3% of 200,000 random inputs (and the polarity answer
    with it on 11.8%), so a future caller would have inherited that — which is
    the whole reason to fix a function nothing calls yet.

    `extra_breaks` are additional breaks the CALLER declares, applied with the
    same both-direction rule. It exists for input that is not prose: consecutive
    lines of a machine-generated report are unrelated RECORDS, so such a caller
    passes ``extra_breaks=("\\n",)`` and gets record scoping from the one place
    that owns scoping. They ADD to `SENTENCE_BREAKS` and cannot remove from it —
    a caller must not be able to opt out of sentence bounding by accident.

    BREAKS ARE LOCATED ON BRACKET-BLANKED TEXT, because "not applicable
    (superseded by rev 2. see note) for die area 1200 x 900 um" ends no sentence
    at that ". " — it is a qualifier, and cutting there loses the "not" that
    governs the number. `blank_bracketed` is length-preserving, so the returned
    offsets index the ORIGINAL `text`; the caller still slices its own text and
    decides for itself whether to blank before calling `is_denied`. Only the
    window [lo, hi) is blanked, so a bracket that opens before the budget cannot
    be paired — that span simply keeps the pre-#790 behaviour.

    `before`/`after` are a BUDGET, not the rule: a bound on how much text is
    examined at all. They are equal because an unequal budget silently truncates
    one half of a long sentence and reintroduces, as a character count, exactly
    the asymmetry the break rule just removed.
    """
    text = text or ""
    lo0 = max(0, start - before)
    hi0 = min(len(text), end + after)
    if lo0 >= hi0:
        return lo0, hi0
    # Blanked ONCE for both scans; `seg` is indexed relative to `lo0`.
    seg = blank_bracketed(text[lo0:hi0])
    lo, hi = lo0, hi0
    for p in tuple(SENTENCE_BREAKS) + tuple(extra_breaks):
        if not p:                       # an empty break would collapse the scope
            continue
        i = seg.rfind(p, 0, start - lo0)
        if i != -1:
            # Every index is measured from the FIXED base `lo0`. Accumulating
            # them onto an already-advanced `lo` overshot the real break by the
            # width of every earlier clamp and cut into the sentence itself.
            lo = max(lo, lo0 + i + len(p))
        j = seg.find(p, end - lo0, hi0 - lo0)
        if j != -1:
            hi = min(hi, lo0 + j)
    return lo, hi
