#!/usr/bin/env python3
"""`_tree_exclusive_tests` — the split that decides what may share a working tree.

WHY THIS FILE EXISTS
====================
`plugin_full_audit` caught the module shipping untested:

    D1 program-test-coverage: FAIL — untested non-synth programs: ['_tree_exclusive_tests']

which is the SECOND time in one day I shipped a shared resolver with no test (see
`test_corpus_location.py`, same finding, same audit). The rule is right and the
omission was mine both times.

WHAT IS ACTUALLY AT RISK
========================
This module decides which test files may run CONCURRENTLY in one checkout. A defect
in either direction is silent and expensive:

  * a file wrongly called parallel-safe collides with its neighbours and produces
    FALSE REDS -- 34 of them, measured, before this list existed;
  * a file wrongly called exclusive is merely slow, but the list is also the
    round's floor, so a list that grows by accident silently gives back the 6.5x.

So every case below asserts BOTH directions. A test that only proved "the listed
ones are exclusive" would pass against a module that called EVERYTHING exclusive.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
MOD = PROGRAMS / "_tree_exclusive_tests.py"


def _load():
    spec = importlib.util.spec_from_file_location("_tx_under_test", MOD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


T = _load()


# ---------------------------------------------------------------------------
# is_tree_exclusive: BOTH directions, and the path shapes the selector really emits
# ---------------------------------------------------------------------------
def test_a_listed_file_is_exclusive_however_its_path_is_spelled():
    """The selector emits repo-relative paths; a caller may hold plugin-relative or
    absolute ones. The answer must not depend on which."""
    for p in ("programs/tests/test_gate_skip_routing_check.py",
              "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
              "test_gate_skip_routing_check.py",
              "/abs/anywhere/test_gate_skip_routing_check.py",
              "test_gate_skip_routing_check"):
        assert T.is_tree_exclusive(p), p


def test_an_unlisted_file_is_parallel_safe():
    """The paired half. Without it, a module that returned True for everything
    would satisfy the test above and hand back the entire speedup."""
    for p in ("programs/tests/test_api_health.py",
              "programs/tests/test_all_steps_covers_flow.py"):
        assert not T.is_tree_exclusive(p), p


def test_a_near_miss_name_is_not_exclusive():
    """Substring matching would drag in files nobody measured. The list is keyed on
    the whole stem."""
    assert not T.is_tree_exclusive("programs/tests/test_gate_skip_routing_check_v2.py")
    assert not T.is_tree_exclusive("programs/tests/xtest_gate_skip_routing_check.py")


# ---------------------------------------------------------------------------
# split: the two halves must partition the selection exactly — no file lost, none
# counted twice, order preserved, and the indices 1-based because every record the
# driver keeps is keyed on the selection index.
# ---------------------------------------------------------------------------
def test_split_partitions_exactly_and_keeps_order():
    sel = ["programs/tests/test_api_health.py",                    # 1 safe
           "programs/tests/test_gate_skip_routing_check.py",       # 2 exclusive
           "programs/tests/test_all_steps_covers_flow.py",         # 3 safe
           "programs/tests/test_programs_index_freshness.py"]      # 4 exclusive
    par, exc = T.split(sel)
    assert par == [1, 3], par
    assert exc == [2, 4], exc
    assert sorted(par + exc) == [1, 2, 3, 4], (
        "the two halves do not partition the selection — a file is lost or "
        "double-counted, and the driver keys its records on these indices")


def test_split_is_one_based_because_the_driver_indexes_from_one():
    """Off by one here means every record is attributed to the wrong file, which
    reads as a coherent set of failures in files that were never run."""
    par, exc = T.split(["programs/tests/test_api_health.py"])
    assert par == [1] and exc == []


def test_an_empty_selection_yields_two_empty_halves_not_an_error():
    assert T.split([]) == ([], [])


def test_a_selection_of_only_exclusives_leaves_the_parallel_half_empty():
    """The driver must cope: with nothing to parallelise there is still work to do,
    and an empty wave must not be mistaken for 'nothing was selected'."""
    par, exc = T.split(["programs/tests/test_programs_index_freshness.py",
                        "programs/tests/test_gate_discloses_denominator.py"])
    assert par == [] and exc == [1, 2]


# ---------------------------------------------------------------------------
# The list itself
# ---------------------------------------------------------------------------
def test_the_list_is_not_empty_and_not_everything():
    """Both degenerate ends are real failure modes: empty gives back the false reds,
    and a list that swallowed the corpus gives back the speedup."""
    assert T.TREE_EXCLUSIVE, "the exclusive list is empty — the 34 collisions return"
    assert len(T.TREE_EXCLUSIVE) < 60, (
        f"{len(T.TREE_EXCLUSIVE)} exclusive files is no longer a measured exception "
        "list; the round's floor is these files run in sequence")


def test_every_listed_file_exists():
    """A stale entry is a silent cost: it serialises nothing and hides that the real
    collider was renamed."""
    missing = [n for n in sorted(T.TREE_EXCLUSIVE)
               if not (PROGRAMS / "tests" / f"{n}.py").is_file()]
    assert not missing, (
        f"listed but absent (renamed or deleted?): {missing}. A name that matches "
        "nothing serialises nothing.")


def test_no_entry_carries_a_py_suffix():
    """The list is keyed on stems; an entry with `.py` would match nothing and be a
    silently dead line."""
    bad = [n for n in T.TREE_EXCLUSIVE if n.endswith(".py")]
    assert not bad, bad
