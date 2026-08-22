#!/usr/bin/env python3
"""A base arm that never OPENED the corpus cannot sanction its expansion.

WHAT THIS PINS, AND WHY IT WAS NOT PINNED
=========================================
`hygiene_finding_delta._corpus_transition` is documented as *"the sole permitted
EMPTY-to-expanded declaration addition"*. It requires of the BASE arm *"the exact
structural EMPTY shape (`items=0`, `gates=1`, `expansion=EXPANDED`)"*.

`expansion` is the field that separates the two zeroes (vibe-ic#1764):

    EXPANDED   the corpus was opened, its index read, and it holds none
    NO_CORPUS  no corpus was resolved, so nothing was opened at all

Both carry `items: 0`. MEASURED, with `repo_hygiene_gates.sh --list
--summary-json` on a clean `a4caccefe` worktree:

    VIBE_IC_BENCHMARK_DATA at a clone   -> {"items": 0, "gates": 1, "expansion": "EXPANDED"}
    no pointer, no corpus in the tree   -> {"items": 0, "gates": 1, "expansion": "NO_CORPUS"}

`test_a_corpus_nothing_opened_is_not_reported_as_one_that_was_read` pins that
`delta` PARTITIONS those two into `empty_corpora` and `absent_corpora`. Nothing
pinned the consequence one layer up: that the TRANSITION refuses a base in the
second state. The behaviour is correct today and was reached by reading the
source, so this is the assertion that keeps it correct.

WHY IT MATTERS RATHER THAN BEING TIDINESS
=========================================
Sanctioning a transition off a `NO_CORPUS` base would certify an expansion
against an arm that never opened the corpus it is being compared to — "the base
had none" asserted from a run that could not look. That is precisely the
substitution #1764 removed from the producer, reappearing where it would license
a declaration change rather than merely mis-word a row.

It also has an operational edge, which is why the wording is worth keeping exact:
whether the base arm reaches `EXPANDED` depends on the corpus pointer being bound
for THAT arm. `gatekeeper_review._published_corpus_binding` supplies it by
default today. On a host with neither the variable nor its fallback checkout, the
base arm is `NO_CORPUS` and no cell, however correctly published, could ever
transition the corpus. That is a real precondition of the restoration and it is
stated nowhere else.

chip-AGNOSTIC: pure record plumbing. No IC, vendor, SKU or process node.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))
sys.path.insert(0, str(_HERE))

import hygiene_finding_delta as H          # noqa: E402
from test_hygiene_finding_delta import _transition_pair   # noqa: E402


def _base_expansion(base, value):
    """Set the routed-DEF corpus row's expansion on the BASE arm only."""
    hit = 0
    for row in base["corpora"]:
        if row["name"] == H.ROUTED_DEF_CORPUS:
            row["expansion"] = value
            hit += 1
    assert hit == 1, f"expected exactly one routed-DEF corpus row, saw {hit}"
    return base


def test_the_pair_this_rests_on_is_sanctioned_when_the_base_was_opened():
    """POSITIVE CONTROL, first, because a refusal test that would pass over a
    broken fixture proves nothing. The unmodified pair must be accepted."""
    base, candidate, evidence = _transition_pair()
    assert _base_expansion(base, "EXPANDED") is base
    H.delta(base, candidate, evidence)          # must not raise


def test_transition_refuses_a_base_that_never_opened_the_corpus():
    """The assertion. `NO_CORPUS` on the base is not the structural EMPTY shape.

    Only the `expansion` field is changed — `items` stays 0 and `gates` stays 1
    — so the refusal cannot come from the count. That is the whole point: the
    two states are indistinguishable by the integer, and the field is what tells
    them apart.
    """
    base, candidate, evidence = _transition_pair()
    _base_expansion(base, H.NO_CORPUS_EXPANSION)
    with pytest.raises(H.Refusal) as e:
        H.delta(base, candidate, evidence)
    assert "structural EMPTY" in str(e.value), str(e.value)


def test_the_refusal_is_not_reachable_through_the_item_count():
    """`items` is 0 in BOTH states, so a consumer keying off it alone cannot
    tell them apart. Asserted here so a future 'simplification' that replaces
    the expansion check with an items check fails instead of passing quietly."""
    base, _, _ = _transition_pair()
    _base_expansion(base, H.NO_CORPUS_EXPANSION)
    row = next(r for r in base["corpora"] if r["name"] == H.ROUTED_DEF_CORPUS)
    assert row["items"] == 0 and row["gates"] == 1, row
    assert row["expansion"] == H.NO_CORPUS_EXPANSION, row


def test_the_two_expansion_spellings_are_the_ones_the_dispatcher_emits():
    """The literals this file reasons about must be the module's own.

    A test that hand-spells `"NO_CORPUS"` keeps passing after the constant is
    renamed, while the property it claims to guard has quietly stopped being
    guarded.
    """
    assert H.NO_CORPUS_EXPANSION == "NO_CORPUS"
    assert H.ROUTED_DEF_CORPUS == "published cells carrying a routed DEF"
