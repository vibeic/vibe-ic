"""`LINE_END_BREAKS` must be OPT-IN, and must bound a scope at a line end.

Seven readers repaired for vibe-ic#712 each needed the same fact -- a sentence
may end at a line end -- and each had written it out privately, under two
different names already. This is that fact, in the module that owns scoping.

The tests below hold the two halves that make it safe: it does what it says, and
its existence changes nothing for a consumer that does not ask for it.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS_DIR))

import _prose_polarity as P  # noqa: E402


SPEC = ("The path from 8-bit to 16-bit is no longer supported.\n"
        "Data is packed from 8-bit to 32-bit words.")


def test_it_is_not_in_SENTENCE_BREAKS():
    """Adding it there would change the scope EVERY consumer computes, silently,
    and they did not ask. 213 extractors read through this module."""
    for brk in P.LINE_END_BREAKS:
        assert brk not in P.SENTENCE_BREAKS, (
            f"{brk!r} has been added to the shared break set, which changes "
            f"scoping for every consumer of `sentence_scope`")


def test_without_it_the_scope_reaches_over_the_full_stop():
    """The behaviour that made seven readers need it -- and the behaviour every
    existing consumer still gets, unchanged."""
    at = SPEC.index("from 8-bit to 32-bit")
    lo, hi = P.sentence_scope(SPEC, at, at + 20)
    assert P.is_denied(SPEC[lo:hi]), (
        "without the line-end breaks this scope no longer reaches the denial "
        "above, so the constant is solving a problem that has gone")


def test_with_it_the_scope_stops_at_the_line_end():
    at = SPEC.index("from 8-bit to 32-bit")
    lo, hi = P.sentence_scope(SPEC, at, at + 20,
                              extra_breaks=P.LINE_END_BREAKS)
    assert not P.is_denied(SPEC[lo:hi]), (
        "the live sentence is still being read as denied:\n" + repr(SPEC[lo:hi]))


def test_a_denial_wrapped_mid_sentence_is_still_reached():
    """Why it is not `("\\n",)`. Breaking on every newline bounds a scope
    mid-sentence, and a denial written across two lines would be missed -- the
    under-reach that publishes a denied value."""
    wrapped = "The path from 8-bit to 16-bit is no\nlonger supported."
    at = wrapped.index("from 8-bit to 16-bit")
    lo, hi = P.sentence_scope(wrapped, at, at + 20,
                              extra_breaks=P.LINE_END_BREAKS)
    assert P.is_denied(wrapped[lo:hi]), (
        "a denial wrapped across two lines is no longer reached:\n"
        + repr(wrapped[lo:hi]))
