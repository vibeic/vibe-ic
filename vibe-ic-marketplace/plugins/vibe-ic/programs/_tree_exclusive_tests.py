#!/usr/bin/env python3
"""The test files that may not share a working tree with another test file.

WHAT THIS IS
============
The per-file parallel path runs N test files at once IN THE SAME CHECKOUT. Most
files do not care. These do: each of them either WRITES into the tree, or ASSERTS
SOMETHING ABOUT THE WHOLE TREE -- "the shipped tree is clean", "the real CI gate
set is currently clean", "the default run never touches the ...". Run two of those
at once and each observes the other's temporary artefacts.

That is not a flaw in parallelism and not a flaw in the tests. It is a shared
resource with no lock, and the fix is to stop sharing it: these files run one at a
time, after the parallel waves.

MEASURED, 2026-08-18, on a 374-file selection, one host, same tree, same selection,
the only variable being serial-vs-parallel dispatch:

    serial    2067 s   8 red
    parallel   317 s  42 red      (6.5x faster)
    serial-only failures:  0      <- parallel misses NOTHING serial catches
    parallel-only failures: 34    <- across the 21 files listed below

`serial-only == 0` is the load-bearing half of that: the parallel path does not
check less. The 34 extra are collisions, and every one of them is in a file that
audits or mutates the tree.

WHY A NAMED LIST AND NOT A HEURISTIC
====================================
A heuristic ("does the file import Path", "does it write anywhere") would be a
guess about which files collide, and a guess that is wrong in the permissive
direction reintroduces exactly the false reds this list removes. This list is the
MEASURED set: it is what actually differed between the two arms. When a new file
starts colliding, the differential between the arms will name it, and it belongs
here -- not in a broader pattern that also drags in files that were never a problem.

THE LIST IS A COST, NOT A VICTORY. Every entry is a file that cannot be
parallelised, so the round's floor is however long these 21 take in sequence.
Shrinking it means giving the offending tests their own tree, not relaxing the
comparison that found them.
"""
from __future__ import annotations

from typing import FrozenSet

#: MEASURED as parallel-only failures on a 374-file two-arm run. Basenames without
#: the `.py`, matched against the stem of each selected path, so the same list
#: works whether the selector emits repo-relative or plugin-relative paths.
TREE_EXCLUSIVE: FrozenSet[str] = frozenset({
    "test_ci_harness_timeout_ceiling_check",
    "test_gate_cli_entry_survives_weakening",
    "test_gate_discloses_denominator",
    "test_gate_skip_routing_check",
    "test_issue1035_five_gates_declare_where_they_are_enforced",
    "test_issue1130_wiring_population_parity",
    "test_issue1235_coverage_gate_declares_where_it_is_enforced",
    "test_issue1241_vendored_attribution_wired",
    "test_issue306_register_paydown",
    "test_issue313_flow_change_acceptance",
    "test_issue509_phase2_scaffold_gen_is_oracle_only",
    "test_issue511_empty_project_pass_disclosure",
    "test_issue559_not_a_project_gate",
    "test_issue833_analog_l5_vacuous_reaches_umbrella",
    "test_macro_obs_gate_enforcement_declared",
    "test_matrix_63x8_census_freshness",
    "test_organic381_artefact_defect_close_requires_the_artefact",
    "test_organic_chip_agnostic_reports_its_denominator",
    "test_programs_index_freshness",
    "test_pytest_per_file_junit",
    "test_three_orphan_checkers_have_a_machine_runner",
})


def is_tree_exclusive(path: str) -> bool:
    """True when this selected path must not share the tree with another file."""
    stem = path.rsplit("/", 1)[-1]
    if stem.endswith(".py"):
        stem = stem[:-3]
    return stem in TREE_EXCLUSIVE


def split(selection):
    """(parallel_safe_indices, exclusive_indices), both 1-based, order preserved.

    Returns INDICES rather than paths because the driver keys every record on the
    selection index; returning paths would make the caller re-derive an index and
    a re-derivation is where the two halves could drift apart.
    """
    par, exc = [], []
    for i, p in enumerate(selection, start=1):
        (exc if is_tree_exclusive(p) else par).append(i)
    return par, exc
