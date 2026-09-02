#!/usr/bin/env python3
"""A registered FILE is not a scheduled ITEM.

THE DEFECT, measured on origin/main 1ec22dabc in the pinned image
sha256:66c33ff2, `programs/tests/test_flow_matrix_census_freshness.py` ALONE on
an idle host at the production 300 s window::

    .F.
    WATCHDOG_STALLED: configured forward-progress signals did not advance for
                      > 300s — killed as hung, not slow.
    AGGREGATE_NORECORD  STALLED after 300 s with no validated pytest lifecycle
                        progress
    aggregate  INCOMPLETE rc=199 cases=0 red=0

Three items completed; the fourth was killed by our own watchdog and the whole
file's record died with it. `rc=199` is `_watchdog.RC_STALLED`. The operator saw
`FAIL targeted aggregate session produced no complete record` — a row that reads
exactly like a red suite. The official 2026-08-31 landing tier carried the same
`rc=199` on the same row.

`validate_nested_progress_inventory` checked the inventory at FILE granularity:
a file that calls a nested producer anywhere must be registered, and any domain
row in it satisfied that. But the stall lease is spent between two consecutive
validated events, so the unit that gets killed is the ITEM. The census file's
two rows both belonged to item 2, which reaches its producer indirectly through
the generator; item 4,
`test_the_published_total_equals_the_live_census`, is the ONLY function in that
file whose source names one of `_NESTED_PRODUCER_CALLS` — and it had no schedule
at all.

The rule is one-directional and fail-closed: an AST-discovered item must be
scheduled OR explicitly listed as unscheduled. The converse is deliberately not
required — item 2's row is a correct declaration for an indirect reach the AST
cannot see, and demanding symmetry would delete it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CI = Path(__file__).resolve().parent
if str(_CI) not in sys.path:
    sys.path.insert(0, str(_CI))

import trusted_test_selection as T  # noqa: E402

CENSUS_ITEM = "test_the_published_total_equals_the_live_census"


def _selection():
    return sorted(T.HERMETIC_TEST_PROGRESS)


# ══════════════════════════════════════════════════════════════════════════
# The control that is RED pre-fix, on REAL in-repo data.
# ══════════════════════════════════════════════════════════════════════════

def test_the_item_the_ast_finds_is_the_item_that_carries_a_schedule():
    """The killed item, discovered and scheduled — from the shipped registry."""
    discovered = T.nested_progress_producer_items(T.HERMETIC_CENSUS_FILE)
    assert CENSUS_ITEM in discovered, discovered
    scheduled = {row[1] for row in
                 T.HERMETIC_TEST_PROGRESS[T.HERMETIC_CENSUS_FILE]["domains"]}
    assert f"{T.HERMETIC_CENSUS_FILE}::{CENSUS_ITEM}" in scheduled, scheduled


def test_the_live_registry_validates_at_item_granularity():
    T.validate_nested_progress_inventory(_selection())


def test_an_unscheduled_producer_item_is_refused():
    """Remove the row this fix added and the inventory must refuse by name."""
    spec = dict(T.HERMETIC_TEST_PROGRESS[T.HERMETIC_CENSUS_FILE])
    spec["domains"] = tuple(
        row for row in spec["domains"] if CENSUS_ITEM not in row[1])
    saved = T.HERMETIC_TEST_PROGRESS[T.HERMETIC_CENSUS_FILE]
    T.HERMETIC_TEST_PROGRESS[T.HERMETIC_CENSUS_FILE] = spec
    try:
        with pytest.raises(T.Refusal) as excinfo:
            T.validate_nested_progress_inventory(_selection())
    finally:
        T.HERMETIC_TEST_PROGRESS[T.HERMETIC_CENSUS_FILE] = saved
    assert CENSUS_ITEM in str(excinfo.value), str(excinfo.value)


# ══════════════════════════════════════════════════════════════════════════
# Load-bearing negatives — true in BOTH directions.
# ══════════════════════════════════════════════════════════════════════════

def test_an_exemption_that_names_no_producer_item_is_refused():
    """A stale exemption hides the next real gap, so it is not tolerated."""
    spec = dict(T.HERMETIC_TEST_PROGRESS[T.HERMETIC_CENSUS_FILE])
    spec["producer_items_without_schedule"] = ("test_not_a_producer_item",)
    saved = T.HERMETIC_TEST_PROGRESS[T.HERMETIC_CENSUS_FILE]
    T.HERMETIC_TEST_PROGRESS[T.HERMETIC_CENSUS_FILE] = spec
    try:
        with pytest.raises(T.Refusal) as excinfo:
            T.validate_nested_progress_inventory(_selection())
    finally:
        T.HERMETIC_TEST_PROGRESS[T.HERMETIC_CENSUS_FILE] = saved
    assert "test_not_a_producer_item" in str(excinfo.value)


def test_a_scheduled_item_the_ast_cannot_see_is_left_alone():
    """One-directional. Item 2 reaches its producer indirectly and keeps its
    rows; a symmetric rule would delete a correct declaration."""
    discovered = T.nested_progress_producer_items(T.HERMETIC_CENSUS_FILE)
    assert "test_the_census_block_is_fresh" not in discovered
    T.validate_nested_progress_inventory(_selection())


def test_discovery_is_a_refusal_not_an_empty_answer():
    """"I could not look" must never read as "nothing calls a producer"."""
    with pytest.raises(T.Refusal):
        T.nested_progress_producer_items("programs/tests/does_not_exist.py")


def test_only_module_level_test_functions_are_items():
    disc = T.nested_progress_producer_items(T.HERMETIC_MATRIX_FILE)
    assert disc and all(name.startswith("test_") for name in disc), disc
