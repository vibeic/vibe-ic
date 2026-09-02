#!/usr/bin/env python3
"""Build the BASE-owned, exact test-selection denominator for a landing.

The selector implementation comes from the already raw-attested runtime state,
never from an unreviewed subject checkout.  It is applied to both the BASE and
candidate trees and the result is unioned: a candidate may add coverage, but it
cannot narrow coverage by deleting, renaming, or editing its own selector.  The
record carries explicit present/absent Git-object identities for every selected
logical path so a deletion cannot disappear from the denominator.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import os
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Sequence


_TRANSITION_SPEC = importlib.util.spec_from_file_location(
    "_vibeic_protected_landing_transition",
    Path(__file__).resolve().with_name("protected_landing_transition.py"),
)
if _TRANSITION_SPEC is None or _TRANSITION_SPEC.loader is None:
    raise ImportError("protected landing transition authority is unavailable")
transition = importlib.util.module_from_spec(_TRANSITION_SPEC)
sys.modules[_TRANSITION_SPEC.name] = transition
_TRANSITION_SPEC.loader.exec_module(transition)

_ATTESTER_SPEC = importlib.util.spec_from_file_location(
    "_vibeic_trusted_selection_attester",
    Path(__file__).resolve().with_name("trusted_worktree_attest.py"),
)
if _ATTESTER_SPEC is None or _ATTESTER_SPEC.loader is None:
    raise ImportError("trusted snapshot attester is unavailable")
attester = importlib.util.module_from_spec(_ATTESTER_SPEC)
sys.modules[_ATTESTER_SPEC.name] = attester
_ATTESTER_SPEC.loader.exec_module(attester)


SCHEMA = 1
KIND = "vibeic.trusted-test-selection"
PROGRESS_PLAN_SCHEMA = 1
PLUGIN_REL = "vibe-ic-marketplace/plugins/vibe-ic"
SELECTOR_REL = f"{PLUGIN_REL}/programs/ci_targeted_test_select.py"
CONTROL_TESTS = (
    "programs/tests/test_ci_harness_timeout_ceiling_check.py",
    "programs/tests/test_gate_process_attestation.py",
    "programs/tests/test_landing_merge_verdict.py",
    "programs/tests/test_pytest_per_file_junit.py",
)

# Selected files normally contribute one outer checkpoint only after every item
# in the file has a validated ``test_finish``.  The four matrix meta-gates below
# deliberately contain nested, finite populations.  A file-level checkpoint is
# therefore too coarse: under normal host contention these files can keep
# completing real work for longer than the outer semantic-stall window.
#
# This BASE-owned table is the complete nested-producer inventory.  ``items`` is
# the exact collection denominator of the protected file.  Each domain row is
# ``(one-based item ordinal, exact nodeid, exact scope, finite total)``.  The
# outer schedule interleaves every validated item completion with these domain
# transitions, so neither a long file nor a long nested population is judged by
# elapsed time, stdout, or CPU activity.
HERMETIC_CENSUS_FILE = "programs/tests/test_flow_matrix_census_freshness.py"
HERMETIC_MATRIX_FILE = "programs/tests/test_flow_matrix_coverage.py"
HERMETIC_ARTEFACT_FILE = "programs/tests/test_matrix_artefact_mutation_channel.py"
HERMETIC_MUTATION_FILE = "programs/tests/test_matrix_mutation_ledger.py"
# EVERY DOMAIN TOTAL BELOW WAS MEASURED ON 2026-08-25, and three of the nine
# were wrong. They are the face of this table that NOTHING READS:
# `test_nested_progress_schedule_matches_live_pytest_collection` takes `items`
# and the nodeid at `ordinal` and DISCARDS the rest of the row (`_scope`,
# `_total`); `validate_nested_progress_inventory` checks shape and profiles.
# The total is spent by `progress_plan()` at LANDING time, where a short count
# reads as a stalled arm and never as a failing assertion -- so a wrong one can
# sit here indefinitely, and `matrix-mutation-replays` did, for five days.
#
# Measured by attaching the production `_pytest_progress_plugin` to each pinned
# nodeid and tallying the `domain_progress` records it really emits:
#
#   census   test_the_census_block_is_fresh         collection-runs    1   ok
#   census   test_the_census_block_is_fresh         outcome-modules    8 -> 9
#   cover    ..._outlives_old_fixed_bound...        outcome-modules    4   ok
#   cover    ..._cannot_outlive_the_pytest_harness  outcome-modules    8 -> 9
#   cover    ..._waits_at_each_wave_boundary        outcome-modules    8   ok
#   cover    ..._has_a_live_outcome_and_..._starved outcome-modules    8 -> 9
#   cover    ..._downgrades_a_red_cell...           outcome-modules    1   ok
#   artefact ..._reproduces_the_recorded_verdict    artefact-replays   8   ok
#   mutation ..._reddens_its_witness[D1-BLIND...]   mutation-replays  24 -> 25
#
# Six of nine matched their pin EXACTLY, which is what says the instrument
# discriminates rather than reporting drift everywhere it looks.
#
# THE THREE THAT MOVED ARE ONE CAUSE: those tests iterate the FULL dimension
# population, `dimension_module_paths()` = sorted(glob("test_matrix_d[1-9]_*.py")),
# and a NINTH dimension module (`test_matrix_d9_verdict_consumed.py`) joined it.
# The rows pinned 4, 8 and 1 are deliberately reduced populations and are NOT
# the dimension count; that is why they did not move with the others.
HERMETIC_TEST_PROGRESS = {
    HERMETIC_CENSUS_FILE: {
        "items": 6,
        # EVERY PRODUCER ITEM MUST APPEAR IN EXACTLY ONE OF TWO LISTS, and
        # this is the second. It is NOT a claim that these items are short:
        # it is the MEASURED set of producer items carrying no schedule at
        # 1ec22dabc, written down so that an ELEVENTH cannot appear in
        # silence. `test_the_published_total_equals_the_live_census` reached
        # the landing gate exactly that way — discovered by the AST, scheduled
        # by nobody, killed at 300 s with rc 199 — and a file-level inventory
        # check could not see it. Adding a producer call to a new item now
        # forces a decision here or a measured row above.
        "producer_items_without_schedule": (),
        "producer_profiles": (("enforcement_census",),),
        # ORDINAL 4 ADDED, and it is the item the AST itself finds calling the
        # producer: `test_the_published_total_equals_the_live_census` is the
        # ONLY function in this file whose source names one of
        # `_NESTED_PRODUCER_CALLS`, while both ordinal-2 rows belong to an item
        # that reaches its producer INDIRECTLY through the generator. The
        # file-level inventory check was satisfied by the file being registered
        # at all, so the one item that provably needed a schedule had none.
        #
        # MEASURED on origin/main 1ec22dabc in the pinned image, this file
        # ALONE on an idle host at the production 300 s window: `.F.` — three
        # items done — then `WATCHDOG_STALLED … killed as hung, not slow`,
        # `AGGREGATE_NORECORD  STALLED after 300 s`, `aggregate INCOMPLETE
        # rc=199 cases=0 red=0`, the same rc the official 2026-08-31 tier
        # reported. Item 4 is what was killed.
        #
        # TOTALS MEASURED THE WAY THE BLOCK ABOVE RECORDS: the production
        # `_pytest_progress_plugin` attached to this nodeid alone emits
        # `matrix-collection-runs` (total 1) and `matrix-outcome-modules`
        # (total 9) — the same two scopes and the same two totals as ordinal 2,
        # because it iterates the same nine dimension modules.
        # `validate_nested_progress_inventory` now refuses a registered file
        # with an unscheduled producer item, so this row cannot go missing
        # again.
        "domains": (
            (2, HERMETIC_CENSUS_FILE + "::test_the_census_block_is_fresh",
             "matrix-collection-runs", 1),
            (2, HERMETIC_CENSUS_FILE + "::test_the_census_block_is_fresh",
             "matrix-outcome-modules", 9),
            (4, HERMETIC_CENSUS_FILE
             + "::test_the_published_total_equals_the_live_census",
             "matrix-collection-runs", 1),
            (4, HERMETIC_CENSUS_FILE
             + "::test_the_published_total_equals_the_live_census",
             "matrix-outcome-modules", 9),
        ),
    },
    HERMETIC_MATRIX_FILE: {
        # items 32 -> 33 AND ordinal 31 -> 32, v1.12.40. RE-DERIVED, never
        # adjusted to make the assertion pass: 95ad23e8c ("timeout-as-verdict:
        # thirteen elapsed-asserts, moved off the stopwatch") added exactly one
        # function to the protected file --
        # `test_a_single_measured_red_still_fails_beside_any_number_of_not_measured_cells`
        # -- and `git diff e91229941..HEAD` over that file shows one `+def test_`
        # and no `-def test_`. MEASURED with the same command
        # `test_nested_progress_schedule_matches_live_pytest_collection` runs --
        # `pytest --collect-only -q` from the plugin root, autoload off:
        #
        #   collected                                                        33
        #   ...::test_a_single_measured_red_still_fails_beside_...           #30
        #   ...::test_the_second_axis_downgrades_a_red_cell_...              #32
        #
        # BOTH NUMBERS MOVE OR NEITHER DOES, for the reason the mutation-ledger
        # block below already records: the ordinal is a position in the same
        # list `items` counts. The new function lands at 30, so the four domain
        # ordinals BEFORE it -- 21, 25, 26, 28 -- are unmoved and were each
        # re-checked against the live collection rather than assumed; only 31
        # is after it and shifts by exactly one. The domain TOTALS are unmoved
        # too: they count `test_matrix_d[1-9]_*.py`, still 9 modules.
        "items": 33,
        # EVERY PRODUCER ITEM MUST APPEAR IN EXACTLY ONE OF TWO LISTS, and
        # this is the second. It is NOT a claim that these items are short:
        # it is the MEASURED set of producer items carrying no schedule at
        # 1ec22dabc, written down so that an ELEVENTH cannot appear in
        # silence. `test_the_published_total_equals_the_live_census` reached
        # the landing gate exactly that way — discovered by the AST, scheduled
        # by nobody, killed at 300 s with rc 199 — and a file-level inventory
        # check could not see it. Adding a producer call to a new item now
        # forces a decision here or a measured row above.
        "producer_items_without_schedule": (
            "test_a_not_measured_cell_is_never_counted_as_enforced",
            "test_live_collection_chatty_import_without_events_fails_closed",
            "test_live_collection_refuses_missing_complete_manifest",
            "test_live_collection_relays_finite_semantic_progress_past_old_bound",
            "test_nested_outcome_run_is_killed_when_no_item_can_renew_the_window",
            "test_no_cell_is_counted_enforced_while_its_predicate_is_red",
            "test_the_enforcement_census_is_reported_for_humans",
        ),
        "producer_profiles": (
            ("_run_outcome_reports", "enforcement_census"),
            ("_collect_items_from_paths", "_run_outcome_reports",
             "enforcement_census"),
        ),
        "domains": (
            (21, HERMETIC_MATRIX_FILE
             + "::test_nested_outcome_run_outlives_old_fixed_bound_with_semantic_progress",
             "matrix-outcome-modules", 4),
            (25, HERMETIC_MATRIX_FILE
             + "::test_the_outcome_loop_cannot_outlive_the_pytest_harness",
             "matrix-outcome-modules", 9),
            (26, HERMETIC_MATRIX_FILE
             + "::test_the_outcome_pool_waits_at_each_wave_boundary",
             "matrix-outcome-modules", 8),
            (28, HERMETIC_MATRIX_FILE
             + "::test_every_cell_has_a_live_outcome_and_the_outcome_run_is_not_starved",
             "matrix-outcome-modules", 9),
            (32, HERMETIC_MATRIX_FILE
             + "::test_the_second_axis_downgrades_a_red_cell_that_the_state_axis_counts",
             "matrix-outcome-modules", 1),
        ),
    },
    HERMETIC_ARTEFACT_FILE: {
        "items": 36,
        # EVERY PRODUCER ITEM MUST APPEAR IN EXACTLY ONE OF TWO LISTS, and
        # this is the second. It is NOT a claim that these items are short:
        # it is the MEASURED set of producer items carrying no schedule at
        # 1ec22dabc, written down so that an ELEVENTH cannot appear in
        # silence. `test_the_published_total_equals_the_live_census` reached
        # the landing gate exactly that way — discovered by the AST, scheduled
        # by nobody, killed at 300 s with rc 199 — and a file-level inventory
        # check could not see it. Adding a producer call to a new item now
        # forces a decision here or a measured row above.
        "producer_items_without_schedule": (),
        "producer_profiles": (("replay_many",),),
        "domains": (
            (19, HERMETIC_ARTEFACT_FILE
             + "::test_lock2_the_replay_reproduces_the_recorded_verdict[ART-DRC-ROUTER-SUMMARY]",
             "matrix-artefact-replays", 8),
        ),
    },
    # 126 -> 125 AND ORDINAL 92 -> 91, 2026-08-24. RE-DERIVED, never adjusted to
    # make the assertion pass: vibe-ic#1779 folded step `1.6x` into step `2`, so
    # the ledger lost the one parametrised cell that step owned. MEASURED with
    # the same command `test_nested_progress_schedule_matches_live_pytest_collection`
    # runs -- `pytest --collect-only -q` from the plugin root, autoload off:
    #
    #   collected                                            125
    #   ...::test_lock2_..._reddens_its_witness[D1-BLIND-GATE-PROGRAMS]   #91
    #
    # BOTH NUMBERS MOVE OR NEITHER DOES. The ordinal is a position in the same
    # list `items` counts, so a cell removed BEFORE the witness shifts it by
    # exactly one; correcting the count and leaving the ordinal would leave the
    # schedule pointing at `[D1-UNREACHABLE-CLAUSE]`, which is what position 92
    # now holds, and the domain assertion would then be checking the wrong test.
    HERMETIC_MUTATION_FILE: {
        # items 125 -> 126 and ordinal 91 -> 92: v1.11.80 added
        # `test_0_5ic_d3_live_replay_closes_the_exact_coverage_delta`, which
        # sorts before the parametrised `test_lock2_...` family.
        "items": 126,
        # EVERY PRODUCER ITEM MUST APPEAR IN EXACTLY ONE OF TWO LISTS, and
        # this is the second. It is NOT a claim that these items are short:
        # it is the MEASURED set of producer items carrying no schedule at
        # 1ec22dabc, written down so that an ELEVENTH cannot appear in
        # silence. `test_the_published_total_equals_the_live_census` reached
        # the landing gate exactly that way — discovered by the AST, scheduled
        # by nobody, killed at 300 s with rc 199 — and a file-level inventory
        # check could not see it. Adding a producer call to a new item now
        # forces a decision here or a measured row above.
        "producer_items_without_schedule": (
            "test_a_cut_off_replay_omits_unstarted_pairs_and_never_a_verdict",
            "test_replay_many_callback_failure_refuses_the_population",
            "test_replay_many_reports_only_finite_completed_units_in_result_order",
        ),
        "producer_profiles": (("replay_many",),),
        "domains": (
            (92, HERMETIC_MUTATION_FILE
             + "::test_lock2_the_mutation_really_reddens_its_witness[D1-BLIND-GATE-PROGRAMS]",
             "matrix-mutation-replays", 25),
        ),
    },
}

# These are the only call shapes allowed to create the nested populations above
# in the protected selection.  ``progress_plan`` scans BASE-owned source and
# refuses a newly reachable producer whose owner has no exact schedule.
_NESTED_PRODUCER_CALLS = {
    "_collect_items_from_paths",
    "_run_outcome_reports",
    "enforcement_census",
    "replay_many",
}

HERMETIC_TEST_RUNTIME_OVERLAYS = tuple(sorted({
    "tools/ci/hermetic_test_arm_entry.sh",
    f"{PLUGIN_REL}/programs/matrix_mutation_ledger.py",
    *(f"{PLUGIN_REL}/{path}" for path in HERMETIC_TEST_PROGRESS),
}))


class Refusal(RuntimeError):
    pass


def _safe_rel(value: str, what: str) -> str:
    if (not isinstance(value, str) or not value or "\n" in value
            or "\r" in value or "\x00" in value):
        raise Refusal(f"{what} is not a safe relative path")
    path = PurePosixPath(value)
    if (path.is_absolute() or path.as_posix() != value
            or any(part in {"", ".", ".."} for part in path.parts)):
        raise Refusal(f"{what} is not canonical: {value!r}")
    return value


def _nested_call_name(node: ast.Call) -> str:
    value: ast.expr = node.func
    while isinstance(value, ast.Attribute):
        name = value.attr
        value = value.value
        if name in _NESTED_PRODUCER_CALLS:
            return name
    if isinstance(value, ast.Name) and value.id in _NESTED_PRODUCER_CALLS:
        return value.id
    return ""


def nested_progress_producer_items(
        test_file: str, *, plugin_root: Path | None = None,
        ) -> dict[str, tuple[str, ...]]:
    """Which ITEMS of ``test_file`` invoke a nested matrix producer.

    THE FILE IS NOT THE UNIT THE SUPERVISOR KILLS. `nested_progress_producers`
    below answers "does this FILE call a producer", and that is the granularity
    `validate_nested_progress_inventory` checked: a file that calls one anywhere
    is registered, and registration is satisfied by a domain row for ANY item in
    it. The outer stall lease is not spent per file; it is spent between two
    consecutive validated events, and an item that runs longer than the lease
    while emitting none is killed whichever of its neighbours carries the rows.

    MEASURED on origin/main 1ec22dabc, pinned image sha256:66c33ff2, ONE file,
    an otherwise idle host, the production 300 s window::

        .F.
        WATCHDOG_STALLED: configured forward-progress signals did not advance
                          for > 300s — killed as hung, not slow.
        AGGREGATE_NORECORD  STALLED after 300 s with no validated pytest
                            lifecycle progress
        aggregate  INCOMPLETE rc=199 cases=0 red=0

    Three items completed, the fourth was killed, and the whole file's record
    was lost — `_watchdog.RC_STALLED`, our own kill, reaching the operator as
    `FAIL targeted aggregate session produced no complete record`, a row that
    reads exactly like a red suite. On the official 2026-08-31 tier the same
    line carried the same `rc=199`.

    The fourth item is `test_the_published_total_equals_the_live_census`, and it
    is the ONLY function in that file whose source calls a name in
    `_NESTED_PRODUCER_CALLS`. The file's two registered rows both belong to item
    2, which reaches its producer INDIRECTLY through the generator. So the
    registry named the file, the file-level check was satisfied, and the item
    the AST itself finds calling the producer had no schedule at all.

    ONE-DIRECTIONAL BY CONSTRUCTION, and the direction is the fail-closed one:
    an AST-discovered item MUST carry a row; a row for an item the AST does not
    discover is legitimate and is left alone. Item 2 is exactly that case — an
    indirect reach the AST cannot see and a schedule that is nonetheless right —
    so requiring the converse would delete a correct declaration in order to
    enforce a rule about a different item.

    Returns ``{function name: (producer call names, sorted)}`` for module-level
    test functions only; a file that is absent or unparseable raises `Refusal`,
    never an empty answer, because "I could not look" must not read as "nothing
    calls one".
    """
    root = plugin_root or (
        Path(__file__).resolve().parents[2] / PurePosixPath(PLUGIN_REL))
    rel = _safe_rel(test_file, "nested-progress owner")
    path = root.joinpath(*PurePosixPath(rel).parts)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise Refusal(
            f"cannot inspect BASE nested-progress owner {rel}: {exc}") from exc
    items: dict[str, tuple[str, ...]] = {}
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        calls = tuple(sorted({
            name for inner in ast.walk(node) if isinstance(inner, ast.Call)
            for name in [_nested_call_name(inner)] if name
        }))
        if calls:
            items[node.name] = calls
    return items


def nested_progress_producers(
        selection: Sequence[str], *, plugin_root: Path | None = None,
        ) -> dict[str, tuple[str, ...]]:
    """Return BASE-owned selected files that invoke a nested matrix producer.

    Candidate-only paths are intentionally absent from the BASE runtime and get
    no trusted liveness allowance.  They retain the ordinary file checkpoint
    and fail NORECORD if they introduce a long opaque operation.  Existing
    BASE-owned producers, however, must be in the exact registry above.
    """
    root = plugin_root or (
        Path(__file__).resolve().parents[2] / PurePosixPath(PLUGIN_REL))
    owners: dict[str, tuple[str, ...]] = {}
    for raw in selection:
        rel = _safe_rel(raw, "nested-progress selection")
        path = root.joinpath(*PurePosixPath(rel).parts)
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise Refusal(
                f"cannot inspect BASE nested-progress owner {rel}: {exc}") from exc
        calls = tuple(sorted({
            name for node in ast.walk(tree) if isinstance(node, ast.Call)
            for name in [_nested_call_name(node)] if name
        }))
        if calls:
            owners[rel] = calls
    return owners


def validate_nested_progress_inventory(
        selection: Sequence[str], *, plugin_root: Path | None = None,
        ) -> None:
    discovered = nested_progress_producers(selection, plugin_root=plugin_root)
    registered = {
        path for path in selection if path in HERMETIC_TEST_PROGRESS
    }
    if set(discovered) != registered:
        raise Refusal(
            "nested progress producer inventory differs from the BASE-owned "
            f"schedule: discovered={sorted(discovered)}, "
            f"registered={sorted(registered)}")
    for test_file in sorted(registered):
        spec = HERMETIC_TEST_PROGRESS[test_file]
        if (not isinstance(spec, dict)
                or set(spec) != {"items", "producer_profiles", "domains",
                                 "producer_items_without_schedule"}):
            raise Refusal(f"nested progress spec for {test_file} is malformed")
        total_items = spec["items"]
        profiles = spec["producer_profiles"]
        domains = spec["domains"]
        unscheduled = spec["producer_items_without_schedule"]
        if (not isinstance(unscheduled, tuple)
                or unscheduled != tuple(sorted(set(unscheduled)))
                or any(not isinstance(name, str) or not name.startswith("test_")
                       for name in unscheduled)):
            raise Refusal(
                f"'producer_items_without_schedule' for {test_file} is invalid")
        if (type(total_items) is not int or total_items < 1
                or not isinstance(profiles, tuple)
                or not profiles
                or profiles != tuple(dict.fromkeys(profiles))
                or any(not isinstance(profile, tuple)
                       or profile != tuple(sorted(set(profile)))
                       or not profile
                       or any(name not in _NESTED_PRODUCER_CALLS
                              for name in profile)
                       for profile in profiles)
                or discovered[test_file] not in profiles
                or not isinstance(domains, tuple)):
            raise Refusal(f"nested progress denominator for {test_file} is invalid")
        seen: set[tuple[str, str]] = set()
        previous_ordinal = 0
        scheduled_nodeids: set[str] = set()
        for row in domains:
            if not isinstance(row, tuple) or len(row) != 4:
                raise Refusal(f"nested progress row for {test_file} is malformed")
            ordinal, nodeid, scope, total = row
            domain_progress_unit(test_file, nodeid, scope, 1, total)
            if (type(ordinal) is not int or not 1 <= ordinal <= total_items
                    or ordinal < previous_ordinal
                    or (nodeid, scope) in seen):
                raise Refusal(
                    f"nested progress order for {test_file} is ambiguous")
            previous_ordinal = ordinal
            seen.add((nodeid, scope))
            scheduled_nodeids.add(nodeid)
        # ITEM GRANULARITY, because the stall lease is spent between two
        # consecutive events and not per file. See
        # `nested_progress_producer_items` for the measured kill this closes:
        # a registered file whose rows all belong to one item, while a
        # DIFFERENT item calls the producer, satisfies every check above and is
        # killed at 300 s with rc 199. One-directional and fail-closed — an
        # AST-discovered item must be scheduled; a scheduled item the AST does
        # not discover (an indirect reach) is left exactly as declared.
        for name in sorted(nested_progress_producer_items(
                test_file, plugin_root=plugin_root)):
            if (f"{test_file}::{name}" not in scheduled_nodeids
                    and name not in unscheduled):
                raise Refusal(
                    f"nested progress schedule for {test_file} declares no "
                    f"domain for {name}, which calls a nested producer, and "
                    f"does not list it in 'producer_items_without_schedule': "
                    f"an item with no checkpoint is judged by elapsed time and "
                    f"is killed as hung once it outruns the stall window")
        for name in sorted(unscheduled):
            if name not in nested_progress_producer_items(
                    test_file, plugin_root=plugin_root):
                raise Refusal(
                    f"{test_file} lists {name} in "
                    f"'producer_items_without_schedule' and it calls no nested "
                    f"producer: a stale exemption hides the next real one")


def _atomic_write(path: Path, raw: bytes) -> None:
    parent = path.parent.resolve(strict=True)
    if path.parent.resolve() != parent:
        raise Refusal("output parent changed")
    tmp = parent / f".{path.name}.tmp.{os.getpid()}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(tmp, flags, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("short write")
            view = view[written:]
        os.fsync(fd)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    finally:
        os.close(fd)
    os.replace(tmp, path)
    observed = path.lstat()
    if (not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1
            or stat.S_IMODE(observed.st_mode) != 0o600):
        raise Refusal(f"published output is not a private regular file: {path}")


def _read_bound_file(path: Path, expected: dict[str, Any], what: str) -> bytes:
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or path.is_symlink()
                or before.st_nlink != 1):
            raise Refusal(f"{what} is not a single-link regular file")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            chunks = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            held = os.fstat(fd)
        finally:
            os.close(fd)
        after = path.lstat()
    except OSError as exc:
        raise Refusal(f"cannot read {what}: {exc}") from exc
    identity = lambda row: (row.st_dev, row.st_ino, row.st_mode, row.st_nlink,
                            row.st_size, row.st_mtime_ns, row.st_ctime_ns)
    if identity(before) != identity(held) or identity(before) != identity(after):
        raise Refusal(f"{what} changed while read")
    raw = b"".join(chunks)
    mode = "100755" if stat.S_IMODE(before.st_mode) & 0o111 else "100644"
    if (mode != expected["mode"] or len(raw) != expected["size"]
            or hashlib.sha256(raw).hexdigest() != expected["sha256"]):
        raise Refusal(f"{what} bytes do not match the selected Git object")
    return raw


def _changes(repo: Path, base: str, candidate: str) -> list[dict[str, Any]]:
    raw = transition._git(  # type: ignore[attr-defined]
        repo,
        ["diff", "--name-status", "-z", "--find-renames", base, candidate],
        binary=True,
    )
    assert isinstance(raw, bytes)
    fields = raw.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    rows = []
    index = 0
    while index < len(fields):
        try:
            status = fields[index].decode("ascii", errors="strict")
        except UnicodeDecodeError as exc:
            raise Refusal("git diff status is not ASCII") from exc
        index += 1
        if (not status or status[0] not in "ACDMRTUXB"
                or not status[1:].isdigit() and len(status) > 1):
            raise Refusal(f"unknown git diff status {status!r}")
        count = 2 if status[0] in {"R", "C"} else 1
        if index + count > len(fields):
            raise Refusal("truncated git diff name-status record")
        paths = []
        for raw_path in fields[index:index + count]:
            try:
                path = raw_path.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise Refusal("changed path is not strict UTF-8") from exc
            paths.append(_safe_rel(path, "changed path"))
        index += count
        rows.append({"status": status, "paths": paths})
    rows.sort(key=lambda row: (row["paths"], row["status"]))
    if len({(row["status"], tuple(row["paths"])) for row in rows}) != len(rows):
        raise Refusal("duplicate changed-path record")
    return rows


def _state(repo: Path, tree: dict[str, tuple[str, str]], full_path: str,
           algorithm: str, oid_len: int) -> dict[str, Any]:
    if full_path not in tree:
        return {"present": False}
    mode, _oid = tree[full_path]
    if mode not in {"100644", "100755"}:
        raise Refusal(f"selected test is not a regular tracked file: {full_path}")
    row = transition._observe_file(  # type: ignore[attr-defined]
        repo, full_path, tree[full_path], algorithm, oid_len)
    return {"present": True, **{key: row[key]
            for key in ("mode", "blob_oid", "sha256", "size")}}


def _load_selector(path: Path, expected: dict[str, Any]):
    _read_bound_file(path, expected, "trusted selector")
    name = "_vibeic_trusted_target_selector"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Refusal("trusted selector has no import loader")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise Refusal(f"trusted selector cannot be loaded: {exc}") from exc
    finally:
        sys.dont_write_bytecode = old
    if not callable(getattr(module, "select_tests", None)):
        raise Refusal("trusted selector has no select_tests API")
    return module


def build(*, object_repo: Path, base: str, candidate: str,
          selector_commit: str, selector_path: Path,
          base_snapshot: Path, candidate_snapshot: Path) -> dict[str, Any]:
    repo = object_repo.resolve(strict=True)
    algorithm, oid_len = transition._object_format(repo)  # type: ignore[attr-defined]
    base_commit, base_tree_oid = transition._commit_and_tree(  # type: ignore[attr-defined]
        repo, base, oid_len, "selection base")
    candidate_commit, candidate_tree_oid = transition._commit_and_tree(  # type: ignore[attr-defined]
        repo, candidate, oid_len, "selection candidate")
    selector_commit_id, selector_tree_oid = transition._commit_and_tree(  # type: ignore[attr-defined]
        repo, selector_commit, oid_len, "selection authority")
    base_tree = transition._tree(repo, base_commit, oid_len)  # type: ignore[attr-defined]
    candidate_tree = transition._tree(  # type: ignore[attr-defined]
        repo, candidate_commit, oid_len)
    selector_tree = transition._tree(  # type: ignore[attr-defined]
        repo, selector_commit_id, oid_len)
    if SELECTOR_REL not in selector_tree:
        raise Refusal("selected runtime has no trusted selector")
    selector_record = transition._observe_file(  # type: ignore[attr-defined]
        repo, SELECTOR_REL, selector_tree[SELECTOR_REL], algorithm, oid_len)
    selector = _load_selector(selector_path, selector_record)

    base_root = base_snapshot.resolve(strict=True)
    candidate_root = candidate_snapshot.resolve(strict=True)
    try:
        for root, commit in ((base_root, base_commit),
                             (candidate_root, candidate_commit)):
            linked = (root / ".git").exists()
            attester._attest(
                root, attester._tree(repo, commit),
                allow_git_control_file=linked,
                object_repo=repo if linked else None,
                expected_sha=commit if linked else None)
    except (OSError, attester.Refusal) as exc:
        raise Refusal(f"selection snapshot is not object-exact: {exc}") from exc
    base_plugin = base_root / PLUGIN_REL
    candidate_plugin = candidate_root / PLUGIN_REL
    if not base_plugin.is_dir() or not candidate_plugin.is_dir():
        raise Refusal("selection roots must be directories")
    changes = _changes(repo, base_commit, candidate_commit)
    changed_paths = sorted({path for row in changes for path in row["paths"]})
    try:
        base_selected = set(selector.select_tests(
            changed_paths, base_plugin, PLUGIN_REL,
            mode=selector.MODE_IMPORT_EDGE))
        candidate_selected = set(selector.select_tests(
            changed_paths, candidate_plugin, PLUGIN_REL,
            mode=selector.MODE_IMPORT_EDGE))
    except Exception as exc:
        raise Refusal(f"trusted selector could not measure both trees: {exc}") from exc

    directly_changed_tests = {
        path[len(PLUGIN_REL) + 1:]
        for path in changed_paths
        if path.startswith(f"{PLUGIN_REL}/programs/tests/test_")
        and path.endswith(".py")
    }
    selected = base_selected | candidate_selected | directly_changed_tests
    for control in CONTROL_TESTS:
        full = f"{PLUGIN_REL}/{control}"
        if full not in base_tree or full not in candidate_tree:
            raise Refusal(f"mandatory negative control is absent: {control}")
        selected.add(control)
    if not selected:
        raise Refusal("trusted selection denominator is empty")

    rows = []
    base_run = []
    candidate_run = []
    for rel in sorted(selected):
        _safe_rel(rel, "selected test")
        if not rel.startswith("programs/tests/test_") or not rel.endswith(".py"):
            raise Refusal(f"selector emitted a non-test path: {rel}")
        full = f"{PLUGIN_REL}/{rel}"
        base_state = _state(repo, base_tree, full, algorithm, oid_len)
        candidate_state = _state(
            repo, candidate_tree, full, algorithm, oid_len)
        if not base_state["present"] and not candidate_state["present"]:
            raise Refusal(f"selected path is absent from both commits: {rel}")
        reasons = []
        if rel in base_selected:
            reasons.append("base-selector")
        if rel in candidate_selected:
            reasons.append("candidate-tree-through-base-selector")
        if rel in directly_changed_tests:
            reasons.append("changed-test")
        if rel in CONTROL_TESTS:
            reasons.append("mandatory-negative-control")
        reasons = sorted(reasons)
        if base_state["present"]:
            base_run.append(rel)
        if candidate_state["present"]:
            candidate_run.append(rel)
        rows.append({"path": rel, "reasons": reasons,
                     "base": base_state, "candidate": candidate_state})

    payload = {
        "base_commit": base_commit,
        "base_tree": base_tree_oid,
        "candidate_commit": candidate_commit,
        "candidate_tree": candidate_tree_oid,
        "selector_commit": selector_commit_id,
        "selector_tree": selector_tree_oid,
        "selector": selector_record,
        "plugin_rel": PLUGIN_REL,
        "mode": "import-edge",
        "changes": changes,
        "tests": rows,
        "base_selection": base_run,
        "candidate_selection": candidate_run,
    }
    return {
        "schema": SCHEMA,
        "kind": KIND,
        "complete": True,
        "payload": payload,
        "payload_sha256": hashlib.sha256(
            transition.canonical_bytes(payload)).hexdigest(),
    }


def _write_list(path: Path, values: Iterable[str]) -> None:
    _atomic_write(path, "".join(f"{value}\n" for value in values).encode("utf-8"))


def progress_plan(selection: Sequence[str], *, scope: str,
                  stall_grace_seconds: int) -> dict[str, Any]:
    if (not isinstance(scope, str) or not scope or len(scope) > 240
            or "\0" in scope or "\n" in scope or "\r" in scope):
        raise Refusal("pytest progress scope is not one bounded string")
    if (type(stall_grace_seconds) is not int
            or not 1 <= stall_grace_seconds <= 86400):
        raise Refusal("pytest progress grace is outside 1..86400")
    parsed = [_safe_rel(value, "pytest progress selection")
              for value in selection]
    if not parsed or parsed != sorted(set(parsed)):
        raise Refusal("pytest progress selection is not finite/sorted/unique")
    validate_nested_progress_inventory(parsed)
    # Collection is a finite parent-owned phase.  Without this checkpoint a
    # wide but healthy aggregate can finish collection and execute tests while
    # the outer runner still sees zero progress until the first scheduled file
    # completes.  The inner strict lifecycle parser supplies the exact declared
    # item count; ordinary output cannot produce this transition.
    units: list[str] = ["pytest:collection-complete"]
    for value in parsed:
        spec = HERMETIC_TEST_PROGRESS.get(value)
        if spec is not None:
            by_ordinal: dict[int, list[tuple[str, str, int]]] = {}
            for ordinal, nodeid, domain_scope, total in spec["domains"]:
                by_ordinal.setdefault(ordinal, []).append(
                    (nodeid, domain_scope, total))
            for ordinal in range(1, spec["items"] + 1):
                for nodeid, domain_scope, total in by_ordinal.get(
                        ordinal, ()):
                    for completed in range(1, total + 1):
                        units.append(domain_progress_unit(
                            value, nodeid, domain_scope, completed, total))
                units.append(test_progress_unit(
                    value, ordinal, spec["items"]))
        units.append(f"pytest:{value}")
    units.append("pytest:record-published")
    return {
        "schema": PROGRESS_PLAN_SCHEMA,
        "scope": scope,
        "stall_grace_seconds": stall_grace_seconds,
        "units": units,
    }


def test_progress_unit(test_file: str, completed: int, total: int) -> str:
    """Canonical unit for one BASE-authorised pytest item completion."""
    _safe_rel(test_file, "test-progress test file")
    if (type(total) is not int or not 1 <= total <= 10_000
            or type(completed) is not int or not 1 <= completed <= total):
        raise Refusal("test-progress denominator is not finite")
    return f"pytest-item:{test_file}|{completed}/{total}"


def domain_progress_unit(test_file: str, nodeid: str, scope: str,
                         completed: int, total: int) -> str:
    """Canonical unit for one BASE-authorised nested semantic transition."""
    _safe_rel(test_file, "domain-progress test file")
    if (not isinstance(nodeid, str)
            or not nodeid.startswith(test_file + "::")
            or any(char in nodeid for char in "\0\n\r|")):
        raise Refusal("domain-progress nodeid is not canonical")
    if (not isinstance(scope, str) or not scope
            or len(scope) > 160 or any(char in scope for char in "\0\n\r|")):
        raise Refusal("domain-progress scope is not canonical")
    if (type(total) is not int or not 1 <= total <= 10_000
            or type(completed) is not int or not 1 <= completed <= total):
        raise Refusal("domain-progress denominator is not finite")
    return (f"pytest-domain:{nodeid}|{scope}|{completed}/{total}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--object-repo", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--selector-commit", required=True)
    parser.add_argument("--selector-path", type=Path, required=True)
    parser.add_argument("--base-snapshot", type=Path, required=True)
    parser.add_argument("--candidate-snapshot", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--base-selection", type=Path, required=True)
    parser.add_argument("--candidate-selection", type=Path, required=True)
    parser.add_argument("--base-progress-plan", type=Path, required=True)
    parser.add_argument("--candidate-progress-plan", type=Path, required=True)
    parser.add_argument("--stall-grace-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    try:
        record = build(
            object_repo=args.object_repo, base=args.base,
            candidate=args.candidate, selector_commit=args.selector_commit,
            selector_path=args.selector_path,
            base_snapshot=args.base_snapshot,
            candidate_snapshot=args.candidate_snapshot,
        )
        _atomic_write(args.manifest, transition.canonical_bytes(record))
        _write_list(args.base_selection, record["payload"]["base_selection"])
        _write_list(
            args.candidate_selection,
            record["payload"]["candidate_selection"])
        _atomic_write(
            args.base_progress_plan,
            transition.canonical_bytes(progress_plan(
                record["payload"]["base_selection"], scope="pytest:A1",
                stall_grace_seconds=args.stall_grace_seconds)))
        _atomic_write(
            args.candidate_progress_plan,
            transition.canonical_bytes(progress_plan(
                record["payload"]["candidate_selection"], scope="pytest:B1",
                stall_grace_seconds=args.stall_grace_seconds)))
    except (OSError, Refusal, transition.Refusal) as exc:
        for path in (args.manifest, args.base_selection,
                     args.candidate_selection, args.base_progress_plan,
                     args.candidate_progress_plan):
            try:
                path.unlink()
            except OSError:
                pass
        print(f"[NORECORD] trusted test selection: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
