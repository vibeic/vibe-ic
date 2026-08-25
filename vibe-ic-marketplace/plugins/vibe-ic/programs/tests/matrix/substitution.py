"""matrix.substitution — the question ``ENFORCED`` does not answer.

``ENFORCED`` says a live predicate RAN and PASSED. It does not say WHAT it ran
against, and for at least one dimension the honest answer is "not the mechanism
the cell is named after".

WHY THIS MODULE EXISTS
======================
Dimension 8 asks "when a declared output is MISSING, does the CATCHER catch
it?". To make that question answerable at all it holds the step's gate at a
known tier by substituting a minimal stand-in
(``{"files_exist": ["_d8_gate/gate_ok.flag"]}``) for the step's own gate. The
substitution is deliberate, argued at length in that module's docstring, and
disclosed in its KNOWN GAP #2.

And then it was erased. The census that module feeds reported those cells as
plain ``ENFORCED``; the README totalled them into one number; the number is what
a reader quotes. Measured 2026-08-09 on ``origin/main`` at ``dee025059``::

    16 of dimension 8's 61 ENFORCED cells exercise the step's own gate;
    45 run against the substituted stand-in.

A disclosure that does not travel with the number is not a disclosure — it is a
footnote nobody reaches. This whole campaign exists because measuring something
ADJACENT to the question and reporting it as the answer is the disease; a
caveat written honestly in one file and dropped in another is the same disease
one layer up.

THE CONTRACT
============
A dimension module MAY expose, beside ``matrix_cell_state`` and
``matrix_na_precondition``::

    def matrix_cell_substitution(step_id) -> Optional[str]: ...

``None``  the cell's predicate ran against the step's OWN mechanism.
a string  it ran against a STAND-IN, and the string says which stand-in and
          why — the same evidence bar a waiver reason carries.

A module that does not expose the hook is **UNDECLARED**, and that is the third
value of this vocabulary rather than a synonym for ``None``.

WHY UNDECLARED IS A STATE AND NOT A DEFAULT
===========================================
This is the load-bearing decision in this file, so it is stated rather than
implied.

Reading "no hook" as "no substitution" would republish the exact defect it was
written to remove: a clean-looking figure asserting something nobody measured.
The question is genuinely open for seven of the eight dimensions, and it is not
answerable by inspection from outside — dimension 1's own docstring says "every
leaf program here is stubbed to `exit 0`; only the DISPATCH is measured", which
may or may not be a substitution in this sense depending on whether the stubbed
leaf can change dimension 1's answer. That call belongs to the module that
built the predicate and mutation-proved it, not to the census, and not to this
file. So the census reports the seven as UNDECLARED, by name, in the published
table, and the generated headline refuses to fold them into either column.

The consequence is deliberate: "genuinely enforcing" is published as a FLOOR
with a named unknown beside it, not as a point estimate. A floor a reader can
check beats a total nobody can reproduce, which is the finding this contract
closes.

WHAT A DISCLOSURE MUST SAY
==========================
The same thing a waiver reason must say, for the same reason: an unfalsifiable
one-liner passes a length check and tells a reader nothing. So the floor is a
length floor plus the placeholder blacklist ``waivers`` already uses — "TODO",
"unknown", "not implemented" are not disclosures. This module deliberately does
NOT grade whether the sentence is TRUE; that is the owning module's
mutation-proof burden, and pretending otherwise here would be this file
measuring something adjacent to its own question.
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple, Union

from . import waivers as _waivers


class _Undeclared:
    """The dimension has not answered "was this measured against a stand-in?".

    A singleton with an explicit repr so it can never be mistaken for ``None``
    in a traceback, a census dict or a rendered table.
    """

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "UNDECLARED"

    def __bool__(self) -> bool:
        # Truthy on purpose. `if substitution:` must not quietly read
        # UNDECLARED as "nothing to report" — that is the erasure this whole
        # module exists to refuse.
        return True


#: The third value of the vocabulary. See "WHY UNDECLARED IS A STATE".
UNDECLARED = _Undeclared()

#: The attribute a dimension module exposes to declare. Named here so the
#: coverage meta-test and the census generator cannot drift on the spelling.
HOOK = "matrix_cell_substitution"

#: The census states a substitution disclosure can legally decorate. Kept in
#: step with ``test_matrix_coverage.VALID_STATES``; a disclosure on
#: anything else is refused by :func:`disclosure_for`.
SUBSTITUTABLE_STATES: Tuple[str, ...] = ("ENFORCED",)

#: A disclosure shorter than this cannot name both the stand-in and the reason.
#: Measured against the real one this campaign has: dimension 8's is 300+ chars,
#: and the shortest sentence that names a substituted mechanism AND why it was
#: substituted lands around 80. Set at 60 so the floor rejects a label without
#: rejecting a terse but complete sentence.
MIN_DISCLOSURE_LEN = 60

#: Reused from the waiver registry rather than re-listed: the phrases that are
#: not reasons there are not reasons here either, and two copies of one
#: blacklist drift apart.
FORBIDDEN_SUBSTRINGS: Tuple[str, ...] = _waivers.FORBIDDEN_REASON_SUBSTRINGS

_FORBIDDEN_RE = tuple(
    (phrase, re.compile(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", re.IGNORECASE))
    for phrase in FORBIDDEN_SUBSTRINGS
)

#: What :func:`disclosure_for` can return.
Verdict = Union[None, str, _Undeclared]


def validate(text: object) -> Tuple[str, ...]:
    """Problems with one disclosure string; empty tuple means admissible.

    Grades SHAPE only — see the module docstring on why truth is the owning
    module's burden and not this file's.
    """
    problems: List[str] = []
    if not isinstance(text, str):
        return (f"disclosure is {type(text).__name__}, expected str or None",)
    stripped = text.strip()
    if not stripped:
        problems.append("disclosure is empty or whitespace")
    elif len(stripped) < MIN_DISCLOSURE_LEN:
        problems.append(
            f"disclosure is {len(stripped)} chars, under the "
            f"{MIN_DISCLOSURE_LEN}-char floor — name the stand-in that was "
            f"substituted AND why the real mechanism could not be used"
        )
    for bad, rx in _FORBIDDEN_RE:
        if rx.search(stripped):
            problems.append(f"disclosure contains the non-reason phrase {bad!r}")
    return tuple(problems)


def hook_of(mod: object):
    """The module's ``matrix_cell_substitution``, or ``None`` if it has none."""
    fn = getattr(mod, HOOK, None)
    return fn if callable(fn) else None


def declares(mod: object) -> bool:
    """Has this dimension answered the question at all?"""
    return hook_of(mod) is not None


def disclosure_for(mod: object, step_id, state: str) -> Verdict:
    """Ask *mod* whether this cell's enforcement was measured against a stand-in.

    Returns ``None`` (own mechanism), a disclosure string (substituted), or
    :data:`UNDECLARED` (the dimension has not answered). Raises
    ``AssertionError`` — never silently downgrades — when the answer is
    malformed or when a non-ENFORCED cell claims a substitution, because
    ``WAIVED`` and ``NA`` already say the cell is not enforcing and counting one
    as substituted-enforcing would double-count it.
    """
    fn = hook_of(mod)
    if fn is None:
        return UNDECLARED
    value = fn(step_id)
    if value is None:
        return None
    if value is UNDECLARED:
        return UNDECLARED
    problems = validate(value)
    assert not problems, (
        f"{getattr(mod, '__name__', mod)!r} step {step_id!r}: substitution "
        f"disclosure is not admissible: {list(problems)}"
    )
    assert state in SUBSTITUTABLE_STATES, (
        f"step {step_id!r} is {state}, not one of {SUBSTITUTABLE_STATES}, yet "
        f"its module returned a substitution disclosure. {state} already says "
        f"the cell is not enforcing; counting it as substituted-enforcing "
        f"would double-count it"
    )
    return value.strip()


#: The census bucket names, in the order the generated table prints them.
OWN_MECHANISM = "OWN"
SUBSTITUTED = "SUBSTITUTED"
UNDECLARED_BUCKET = "UNDECLARED"
BUCKETS: Tuple[str, ...] = (OWN_MECHANISM, SUBSTITUTED, UNDECLARED_BUCKET)


def bucket(verdict: Verdict) -> str:
    """Which published column a :func:`disclosure_for` verdict belongs in."""
    if verdict is UNDECLARED:
        return UNDECLARED_BUCKET
    if verdict is None:
        return OWN_MECHANISM
    return SUBSTITUTED


__all__ = [
    "HOOK",
    "UNDECLARED",
    "SUBSTITUTABLE_STATES",
    "MIN_DISCLOSURE_LEN",
    "FORBIDDEN_SUBSTRINGS",
    "OWN_MECHANISM",
    "SUBSTITUTED",
    "UNDECLARED_BUCKET",
    "BUCKETS",
    "validate",
    "hook_of",
    "declares",
    "disclosure_for",
    "bucket",
]
