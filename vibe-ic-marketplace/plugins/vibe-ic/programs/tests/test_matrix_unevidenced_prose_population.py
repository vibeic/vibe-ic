"""The unevidenced population is declared twice; the copies must agree.

vibe-ic #923 closed the same defect shape for stage membership: one fact
written down in two places, the copies drifting, and the number a reader
quotes coming from whichever copy they happened to read. This is that shape
again, one module over.

``test_matrix_d3_outputs_produced`` declares its unevidenced population TWICE:

  * as DATA, in ``UNEVIDENCED_CELLS`` -- re-derived live and pinned by
    ``test_d3_unevidenced_cells_are_named_cell_by_cell``; and
  * as PROSE, in the module docstring and in that test's own docstring, which
    state the size of the population, how many of it are RED, and which
    ordinal a newcomer would take.

Only the DATA copy had a check. The prose copy drifted the moment the register
shrank, and it drifted into the exact currency this campaign is about: counts
a reader will quote.

WHAT THIS TEST IS NOT. It cannot close a single red cell and does not try to.
Every cell in the register stays RED and stays pinned -- asserted below by
``test_the_pinned_population_is_unchanged_and_still_red``, which is this fix's
paired guard: it must pass identically before and after, so the prose fix
cannot be bought by making a cell green or by emptying the register.

HISTORICAL SENTENCES ARE LEFT ALONE. Claims written in the past tense ("before
the fix all twelve were green") record what was measured on a day that has
passed; re-stamping them with today's number would destroy the record. Only
present-tense claims about THIS checkout are checked here.

NAMING, and it is not cosmetic. This file deliberately does NOT match
``test_matrix_d[1-8]_*.py``. That glob is how ``test_matrix_63x8_coverage``
and ``test_matrix_mutation_ledger`` discover the eight dimension modules, and
EVERY file it matches is imported and required to expose a module-level
``DIM``. A companion named ``test_matrix_d3_...`` is therefore picked up as a
ninth dimension module and takes the whole 504-cell census down with an error
that names neither file. Measured on this branch before this file was named.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(PROGRAMS / "tests"))

import test_matrix_d3_outputs_produced as D3  # noqa: E402

#: Only as far as any count in this file can plausibly reach.
_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven",
          "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
          "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty")
_ORDINALS = ("zeroth", "first", "second", "third", "fourth", "fifth", "sixth",
             "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth",
             "thirteenth", "fourteenth", "fifteenth", "sixteenth",
             "seventeenth", "eighteenth", "nineteenth", "twentieth")


def _word(n: int) -> str:
    assert 0 <= n < len(_WORDS), f"no word for {n}; extend _WORDS"
    return _WORDS[n]


def _ordinal(n: int) -> str:
    assert 0 <= n < len(_ORDINALS), f"no ordinal for {n}; extend _ORDINALS"
    return _ORDINALS[n]


# ── the measurement, taken from the module rather than recomputed ──────────

def _measured():
    """Ask the module. Never re-derive the rule here.

    ``waiver_for`` is the module's own function and ``UNEVIDENCED_CELLS`` its
    own register; a local reimplementation of "which cells are waived" would
    agree with itself no matter what the module did, which is the way a test
    stops testing anything.
    """
    pinned = tuple(D3.UNEVIDENCED_CELLS)
    waived = tuple(s for s in pinned if D3.waiver_for(s) is not None)
    red = tuple(s for s in pinned if D3.waiver_for(s) is None)
    return pinned, red, waived


def _module_prose() -> str:
    doc = D3.__doc__ or ""
    named = D3.test_d3_unevidenced_cells_are_named_cell_by_cell.__doc__ or ""
    assert doc.strip(), "the d3 module lost its docstring"
    assert named.strip(), "the naming test lost its docstring"
    # Collapse wrapping. These sentences are reflowed by hand every time the
    # docstring is edited, so a pattern anchored to line breaks would go
    # vacuous on the next rewrap -- a check that stops looking without saying
    # so, which is the failure this whole campaign is removing.
    return re.sub(r"\s+", " ", doc + "\n" + named)


def _claims(pattern: str) -> list:
    """Every number-word this prose uses in *pattern*, as written."""
    return re.findall(pattern, _module_prose(), flags=re.IGNORECASE)


# ── the three present-tense claims ────────────────────────────────────────

def test_the_red_count_claimed_in_prose_is_the_number_actually_red():
    """"N cells are red for this reason" must be N.

    Measured 2026-08-11 on the v1.10.30 landing batch: the register had been
    reduced from twelve entries to ten and this sentence still said twelve --
    and twelve was never right even for the old register, because the waived
    member xfails rather than failing.
    """
    _, red, _ = _measured()
    claims = _claims(r"([A-Za-z]+) cells are red for this reason")
    assert claims, (
        "the module no longer states how many cells are red for this reason. "
        "That sentence is the one a reader quotes; if it is being removed, "
        "remove this assertion in the same change and say why.")
    for claimed in claims:
        assert claimed.lower() == _word(len(red)), (
            f"the module's prose says {claimed!r} cells are red for this "
            f"reason; the live register holds {len(red)} unwaived cells "
            f"{sorted(red)!r}. The population is declared twice and the "
            f"copies "
            f"disagree -- the same defect vibe-ic#923 closed for stage "
            f"membership. Correct the SENTENCE; the register is the "
            f"measurement and is pinned by "
            f"test_d3_unevidenced_cells_are_named_cell_by_cell.")


def test_the_population_size_claimed_in_prose_is_the_register_size():
    """"granting N of them [waivers]" must be the size of the register."""
    pinned, _, _ = _measured()
    claims = _claims(r"against granting ([A-Za-z]+) of them")
    assert claims, (
        "the waiver-refusal sentence no longer states a count; it is the "
        "argument for why these cells are red rather than waived and the "
        "number is load-bearing")
    for claimed in claims:
        assert claimed.lower() == _word(len(pinned)), (
            f"the prose refuses {claimed!r} waivers; the register pins "
            f"{len(pinned)} cells {sorted(pinned)!r}")


def test_the_next_newcomer_ordinal_matches_the_register_size():
    """"a Nth cell joining" must be the ordinal AFTER the current population.

    This one is the reason the drift matters rather than being cosmetic: the
    sentence tells the next reader which ordinal signals a NEW loss of
    evidence. Left stale it names an ordinal the register has already passed,
    so a genuine newcomer reads as already accounted for.
    """
    pinned, _, _ = _measured()
    claims = _claims(r"a[n]? ([A-Za-z]+) cell joining")
    assert claims, "the anti-growth sentence lost its ordinal"
    for claimed in claims:
        assert claimed.lower() == _ordinal(len(pinned) + 1), (
            f"the prose calls the next newcomer the {claimed!r} cell; the "
            f"register holds {len(pinned)}, so the next one is the "
            f"{_ordinal(len(pinned) + 1)}. A stale ordinal makes a real new "
            f"loss of evidence read as one already counted.")


# ── the paired guard: this must pass IDENTICALLY before and after ─────────

def test_the_pinned_population_is_unchanged_and_still_red():
    """THE GUARD. Nothing here may go green, and the register may not shrink.

    Run this against the unfixed module and against the fixed one and it gives
    the same answer both times. That is its whole job: it makes the three
    assertions above unsatisfiable by deleting a cell from the register, by
    waiving one, or by making one pass -- every route to green that would turn
    a prose correction into a waiver.

    The predicate consulted is ``audit_step``, which is the function the
    parametrized cell test itself calls. Asking anything else would be this
    file forming a second opinion about cells it does not own.
    """
    pinned, red, waived = _measured()

    assert len(pinned) >= 10, (
        f"the unevidenced register shrank to {len(pinned)} "
        f"{sorted(pinned)!r}. "
        f"A prose count is corrected by editing the sentence, never by "
        f"emptying the register it describes.")
    assert len(waived) == 1, (
        f"the unevidenced register now holds {len(waived)} waived cell(s) "
        f"{sorted(waived)!r}; exactly one pre-existing waiver is expected and "
        f"a new one here would be the standing excuse this module refuses")

    still_red = []
    for sid in red:
        missing, _detail = D3.audit_step(sid)
        if missing:
            still_red.append(sid)
    assert sorted(still_red) == sorted(red), (
        f"cells {sorted(set(red) - set(still_red))!r} are pinned as "
        f"unevidenced "
        f"and their predicate now PASSES. If a run tree was published that "
        f"closes them, delete them from UNEVIDENCED_CELLS and name the tree; "
        f"if not, something made the predicate stop looking.")
