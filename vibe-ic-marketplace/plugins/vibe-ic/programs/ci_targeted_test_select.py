#!/usr/bin/env python3
"""ci_targeted_test_select.py — pick a FAST targeted pytest subset for the
patch-cadence gatekeeper CI gate.

WHY
===
The full plugin suite (~17k tests across two trees) is a MILESTONE-only gate:
on a hosted 2-core runner it takes 90+ minutes, which is unusable as the
per-PR required check. On every PR we instead want to run, in *minutes*, the
smallest subset that still covers what the PR actually changed — plus a fixed
curated "doctrine smoke" set so a docs-only or version-only PR never runs zero
tests. The full both-tree suite still runs on the `x.y.0` milestone job.

SELECTION RULES
===============
Given the PR's changed files (``git diff --name-only <base>..HEAD``, repo- or
plugin-relative), the selected subset is the UNION of:

  1. For each changed SOURCE module — a top-level ``programs/<stem>.py`` or
     ``benchmark/<stem>.py`` that is NOT a test file — every
     ``programs/tests/test_*.py`` whose filename is OWNED by ``<stem>``.
     A test ``test_X.py`` (X = basename without the ``test_`` prefix / ``.py``
     suffix) is owned by the source-module stem ``S`` such that ``X == S`` or
     ``X`` starts with ``S + "_"``, AND ``S`` is the LONGEST such source-module
     stem. The longest-prefix rule prevents over-selection: e.g.
     ``test_analog_corner_sweep_check.py`` is owned by
     ``analog_corner_sweep_check``, never by a shorter ``analog_corner_sweep``.

  2. Each changed TEST file (``programs/tests/test_*.py``) — included directly.

  3. ALWAYS the curated doctrine SMOKE set (governance + core gates).

  4. For each changed SHARED TEST-HELPER module — any ``*.py`` under
     ``programs/tests/`` that is NOT a ``test_*.py`` file, e.g.
     ``programs/tests/matrix/waivers.py`` or
     ``programs/tests/_hostpaths.py`` — every test file that IMPORTS it,
     derived from the tests' own ``import`` statements rather than from a
     hand-written list. See ``_helper_consumers`` for the exact edges.

Output: plugin-root-relative test paths, one per line, deduped and sorted, to
stdout. The list is NEVER empty — the smoke set is the floor. If git is
unavailable (no history / not a repo), only the smoke set is emitted.

This is deliberately a PROGRAM, not workflow YAML: the mapping is testable and
lives next to the tests it selects. See
``programs/tests/test_ci_targeted_test_select.py``.

SHARED TEST-HELPER MODULES  (vibe-ic#534, measured 2026-07-28)
==============================================================
Rules 1 and 2 between them see only ``programs/<stem>.py`` / ``benchmark/
<stem>.py`` and ``programs/tests/test_*.py``. A third population exists and was
invisible to both: SHARED code that lives under ``programs/tests/`` but is not
itself a test — ``matrix/{waivers,cells,flowref}.py``, ``_hostpaths.py``,
``_plugin_tree.py``, ``_source_pin.py``, ``_gdsii.py``, ``matrix_d4_probe.py``,
``matrix_d7_artifact_graph.py``. Measured on this tree BEFORE rule 4, with the
real CLI (``--base HEAD``, one-line edit to ``matrix/waivers.py``): the
selector saw the changed path (``1 changed path(s)``) and emitted 15 files —
exactly the smoke floor, 0 of the 11 test files that import it.

That was not an ordinary coverage gap. ``matrix/waivers.py`` is the CENTRAL
waiver registry that vibe-ic#527 (v1.7.86) and #530 (v1.7.88) deliberately
consolidated, moving waiver text out of per-dimension mirrors so one accepted
gap has exactly one text. Consolidation is what makes the hole expensive: a
single edit there can flip the verdict of a cell in any of the eight dimensions,
and a targeted CI that runs none of them is green for no reason. Both #527's and
#530's authors were told BY HAND to run all the matrix files, which is the
workaround rule 4 removes.

Rule 4 is DERIVED, not listed. A hand-list of the consumer filenames would be a
second registry beside the first, free to drift from it — the exact defect #527
and #530 spent two versions removing, and it would have been wrong on arrival:
the report that opened #534 said ten consumers; the tree has ELEVEN, the
eleventh being ``test_matrix_waiver_single_source.py``, which #530 itself added.
So the edges come from the tests' own ``import`` statements, parsed with ``ast``:

  * a helper's importable name is derived from its path relative to
    ``programs/tests/`` (``matrix/waivers.py`` -> ``matrix.waivers``,
    ``matrix/__init__.py`` -> ``matrix``), plus its bare basename when
    that name is unambiguous — this tree really does bare-import a nested helper
    after an inline ``sys.path.insert`` (``from synthetic_protocol_blobs import
    …``), so path-dotted names alone would miss it;
  * importing ``a.b`` imports ``a``, so ancestor packages count as imported.
    This is what couples the whole ``matrix`` package: a test that reads
    only ``cells`` is still selected when ``waivers`` changes, because both
    resolve through the package whose contents moved. For this tree the
    package-ancestor edge changes nothing (all 11 consumers import ``waivers``
    directly); it is the margin that keeps rule 4 correct for the NEXT dimension
    module, which is the failure mode a hand-list has;
  * helper -> helper edges are followed transitively, so a change to
    ``flowref.py`` reaches the tests that import ``matrix_d4_probe``.

Cost is paid only when a helper actually changes: the index is built lazily, and
the ``ast`` parse runs only on test files whose text contains a target's
top-level name (a sound superset filter — no import form of ``a.b`` can omit the
literal ``a``). Measured on this tree, 1986 test files:

    changed helper                      tests selected (excl. 15 smoke)   wall
    matrix/waivers.py                 11                             ~1 s
    matrix/cells.py                   11
    matrix/flowref.py                 11
    matrix_d4_probe.py                      1
    matrix_d7_artifact_graph.py             1
    _hostpaths.py                         116
    _plugin_tree.py                        24
    _source_pin.py                          8
    _gdsii.py                               7

KNOWN RESIDUALS, measured 2026-07-28 while closing #534, deliberately NOT fixed
here. Recorded so the next reader inherits the numbers instead of re-deriving
them:

  * ``conftest.py`` — pytest injects it; no test file names it in an import, so
    the derived rule correctly finds zero consumers, while a change to it really
    does affect all 1986. Selecting the whole tree is the same non-answer as
    selecting none of it, so it stays out until someone measures a budget for it.
  * NON-``.py`` fixtures — 33 files under ``programs/tests/fixtures/`` (23) and
    ``phase1_fixtures/`` (11), named by 15 test files. Consumed by PATH literal,
    not by import, and the selector skips non-``.py`` changed paths before any
    rule runs, so a fixture edit selects the smoke floor. Reaching them needs a
    path-literal scan — a different rule from this one, keyed on strings rather
    than on the import graph.
  * SHARED HELPERS THAT LIVE IN ``programs/``, not under ``programs/tests/``.
    ``_waiver_entries.py`` and ``_evidence_independence.py`` are the two named
    in #534's follow-up question; both are genuinely unreachable today, but by
    the #452 orphan mechanism below, NOT by the rule-4 hole: rule 1 does see
    them as source modules and finds no ``test__waiver_entries*.py`` to own.
    Measured over the 38 leading-underscore modules under ``programs/`` /
    ``benchmark/`` — the repo's convention for "shared helper, no standalone
    gate", hence no eponymous test — 144 importer edges are unreachable today,
    worst single module ``_path_layout`` at 43, mean 3.8. That is far cheaper
    than ``--mode reference`` (which keys on any identifier MENTION: 198 files
    for ``phase3_one_shot_runner``), so an import-derived rule 1b is tractable.
    It is left out because it changes the DEFAULT per-landing cost for many
    unrelated diffs, and this module already exposes that trade-off as an
    owner-facing ``--mode`` frontier with its own measured table. Widening the
    default is that owner's call, not a side effect of #534.

WHAT THE OWNERSHIP RULE CANNOT REACH  (vibe-ic#452, measured 2026-07-27)
=======================================================================
Rule 1 keys on the test FILENAME. This repo names a large share of its tests
after the ISSUE or the VERSION that motivated them (``test_organic409_…``,
``test_v1_0_67_issue708_…``), which is orthogonal to the module they exercise.
Measured over the shipped tree (1870 test files, 1023 source stems):

    ownership-reachable test files      851 / 1870  (45.5%)
    orphaned (rule 1 can NEVER pick)   1019 / 1870  (54.5%)

Three tests that went red on real landings were each missed 0/3 by rule 1,
because the owning stem of all three is ``None``. They stayed red for 41, 26 and
23 landings respectively.

``--mode`` exposes the two alternatives that were MEASURED against that gap.
They are OPT-IN and nothing in CI passes ``--mode``; ``ownership`` is the
default and is byte-identical to the behaviour that shipped before this flag
existed. The cost is real and the choice is the owner's:

  mode                reachable      catch on the 3    files/landing     worst
                                     known regressions  (mean of 40)
  ownership (default)  851 (45.5%)   0 / 3              16.8             20
  reference-capped    1652 (88.3%)   2 / 3              19.8             48
  import-edge          --            see below         110-158          176
  reference           1849 (98.9%)   3 / 3              48.5            213

vibe-ic#565 — THE IMPORT-EDGE ROW, measured 2026-08-01 because the decision it
feeds was being asked without it. The mechanism shipped with #534 and the
DEFAULT was left at `ownership` pending a cost that nobody had taken.

On the exact regression #565 is about — `phase3_one_shot_runner.py` changes and
`test_spm_ihp_openrcx_captable_layout.py` is the file that pins the behaviour a
734-line edit silently reverted for three releases:

    mode                selects    catches that test
    ownership              16         no
    reference-capped       16         no
    import-edge           176         YES
    reference             258         YES

Selection size on three real landings of this repo (v1.9.19/20/21):

    ownership          21    26    27
    reference-capped   35    47    48
    import-edge       110   157   158

Wall-clock with the real CI command on the largest of those (v1.9.18's diff):

    ownership     27 files     484 tests     49s
    import-edge  158 files    3276 tests    409s      (8.4x)

So import-edge buys the catch that `reference-capped` does not, at ~2/3 of
`reference`'s file count — and costs roughly eight ownership lanes per landing.
Whether that trade is worth making the DEFAULT is still the owner's call; what
changed is that the call now has its number.

Wall-clock, measured with the real CI command (``pytest -q --maxfail=10
--timeout=180``):

    ownership,  17 files    315 tests     58s
    ownership,  18 files    324 tests     31s
    reference,  48 files    850 tests    183s
    reference,  67 files    859 tests     81s
    reference, 213 files   2756 tests    345s / 349s  (two runs, WORST case)

Two things fall out of that table. First, the worst case is ~6-11x the
ownership lane depending on which landing you compare against — it is not
unbounded; both runs of the 213-file set finished, agreeing to 1.4%. Second,
NEITHER file count NOR test count predicts cost: 67 files/859 tests ran in less
than half the time of 48 files/850 tests, and two ~equal ownership selections
differ by 1.9x. So a budget expressed in files (or in tests) is NOT a time
budget; a real one would need persisted per-file timings, which nothing in this
repo records.

Measured on a 32-thread workstation, single-process; the lane they would run in
is a 2-core hosted runner. Treat them as ratios, not as CI wall-clock.

``reference-capped`` is order-free on purpose. An ordered "take the N most
focused first" budget was also measured and REJECTED: over the 1984 (orphaned
test, named stem) pairs it scored 86.5% against 85.8% for an arbitrary
alphabetical order — a 0.7pp edge, i.e. the ordering heuristic was noise, and
its apparent 3/3 on the three known regressions was a 3-sample artifact.

Note what NONE of these modes can do. The cost is not prose noise that a
smarter matcher could strip: of the 198 test files that name
``phase3_one_shot_runner``, 95 name that module and NOTHING else, and 186 of the
198 bind to it by a real import or path literal. Any rule that reliably catches
a regression in that module's tests pays ~95 files.

So no mode here delivers bounded STALENESS — "every test file is seen within K
landings" — because a changed-file selector only ever looks at what changed.
That is a rotation / full-suite property. For scale, a 1/20 rotation shard of
this tree (94 files + the smoke floor) measured 1317 tests in 146s, i.e. ~2.5x
the ownership baseline for a FIXED, predictable cost and a hard <=20-landing
bound. The three known regressions stayed red for 41, 26 and 23 landings, so a
bound of that size would have caught all three — including the one that survived
an x.y.0 MILESTONE, whose full-suite job lives in a workflow that fires only on
`pull_request` / `merge_group` and is currently `disabled_manually`.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import re
import subprocess
import sys
from pathlib import Path

#: `spec_from_file_location("<stem>", <path>)` — an EXPLICIT loader edge.
#: Matched on the module NAME argument, which is the stem the test binds,
#: rather than on the path, because the path is often built from `Path`
#: arithmetic that a regex cannot follow.
_LOADER_NAME_RE = re.compile(
    r"spec_from_file_location\(\s*[\"\']([A-Za-z_]\w*)[\"\']")

#: A `.py` FILENAME carried as a quoted literal ANYWHERE in a test — the THIRD
#: route a real dependency travels, and the one an import graph is structurally
#: blind to.
#:
#: MEASURED on 4232a7301e, the commit that put a hygiene-record handover on
#: `gatekeeper_review`'s argv. Its sibling guard imports two modules and WAS
#: selected; the guard that owns the property — "the CLI offers no way to skip
#: the hygiene set" — reaches its subject like this:
#:
#:     subprocess.run([sys.executable,
#:                     str(_PROGRAMS / "gatekeeper_review.py"), "--help"])
#:
#: A path assembled from a constant and handed to a subprocess. No import, no
#: `spec_from_file_location`, so no edge — and the ONLY guard on that program's
#: CLI surface went unselected while that program was being changed.
#:
#: Deliberately keyed on the BASENAME WITH ITS EXTENSION rather than on the bare
#: stem `_build_reference_index` uses. The stem occurs in prose, in comments and
#: in unrelated identifiers; `"gatekeeper_review.py"` occurs where something
#: RUNS it. Measured over the same change set: 12 test files name a changed
#: program this way, 10 were already selected, so the rule adds TWO — 122 -> 124
#: files, against 138 for promoting `--mode reference` to the default.
_DRIVER_PY_LITERAL_RE = re.compile(r"[\"\']([A-Za-z_][\w.\-/]*\.py)[\"\']")

#: The SAME call, read for the file it actually loads rather than for the alias
#: it binds it under (vibe-ic#1176). `_LOADER_NAME_RE` keys the edge on argument
#: one, so a test that renames the module on the way in carries an edge under a
#: name no source stem matches, and the edge is dropped:
#:
#:     spec_from_file_location("fcc_i492_conv", PROGRAMS / "flow_compliance_check.py")
#:
#: MEASURED on `75776dbbb`: `test_issue492_gate_argv_conversions.py` and
#: `test_issue492_umbrella_gate_invocation.py` both load
#: `flow_compliance_check.py` under a private alias, and neither appears in
#: `_build_import_edge_index`'s entry for that stem — the two tests state the
#: strongest dependency the tree has on that module and were invisible to it.
#:
#: The call's argument list is captured whole (one level of nested parens, which
#: covers the `Path(...) / "x.py"` and `parents[1] / "x.py"` forms this tree
#: uses) and every `.py` string literal inside it contributes its stem. The path
#: arithmetic still cannot be followed — but the FINAL segment is a literal in
#: every occurrence in this tree, and the stem is all this index needs.
_LOADER_CALL_RE = re.compile(
    r"spec_from_file_location\((?P<args>[^()]*(?:\([^()]*\)[^()]*)*)\)", re.S)
#: A `.py` string literal inside such an argument list.
_LOADER_PY_LITERAL_RE = re.compile(r"[\"\']([^\"\']+\.py)[\"\']")

# Selection modes. `ownership` is the DEFAULT and the shipped behaviour; the
# other two are opt-in and measured in the module docstring (vibe-ic#452).
MODE_OWNERSHIP = "ownership"
MODE_REFERENCE = "reference"
MODE_REFERENCE_CAPPED = "reference-capped"
#: vibe-ic#565 — select by the DEPENDENCY a test states, not by its filename and
#: not by a lexical mention.
#:
#: `2a632bcfe` changed 734 lines of `phase3_one_shot_runner.py` and removed all
#: 11 lines of the IHP OpenRCX captable discovery landed hours earlier. The four
#: tests that pin it are in `test_spm_ihp_openrcx_captable_layout.py`, which
#: `import phase3_one_shot_runner` directly. `ownership` keys on the test
#: FILENAME, so it selected none of them; the revert survived three releases.
#:
#: MEASURED on that exact commit, driving the real selector:
#:
#:     ownership          16 files    misses the IHP test
#:     reference-capped   16 files    misses it too — the cap ZEROES a stem
#:                                    named by more than `ref_max_tests`, and
#:                                    `phase3_one_shot_runner` is named by 198,
#:                                    so the cheap middle option gives no
#:                                    protection for the largest module in the
#:                                    tree, which is where the risk is
#:     reference         251 files    catches it, on a LEXICAL mention
#:     import-edge       155 files    catches it, on a STATED dependency
#:
#: Cheaper than `reference` AND more precise: every file it selects has an
#: import or an explicit loader pointing at the changed module, rather than a
#: name that happens to appear in it.
MODE_IMPORT_EDGE = "import-edge"
MODES = (MODE_OWNERSHIP, MODE_REFERENCE, MODE_REFERENCE_CAPPED,
         MODE_IMPORT_EDGE)

# `reference-capped` default: a source stem NAMED BY more than this many test
# files contributes nothing through the reference rule (its own owned tests
# still apply). 50 was the measured knee — see the module docstring.
DEFAULT_REF_MAX_TESTS = 50


# ---------------------------------------------------------------------------
# Curated doctrine SMOKE set — fixed, high-value, fast governance/core gates.
# These run on EVERY PR regardless of what changed, so the required gate always
# exercises the doctrine invariants (chip-AGNOSTIC source, NDA in commit msgs,
# version sync + monotonic bump, check-in scope, the flow/spec/rtl gates, and
# the D1/D2 plugin audit). Basenames only — resolved against programs/tests/ at
# runtime; a name that does not exist is skipped (never a hard failure).
# ---------------------------------------------------------------------------
SMOKE_BASENAMES: tuple[str, ...] = (
    "test_source_chip_agnostic_check.py",
    "test_commit_msg_nda_check.py",
    "test_marketplace_version_sync_check.py",
    "test_version_bump_monotonic_check.py",
    "test_agent_checkin_scope_guard.py",
    "test_plugin_full_audit.py",
    "test_flow_compliance_check.py",
    # vibe-ic#220 — the self-disabling-condition guard. Belongs in the SMOKE
    # floor rather than in change-targeted selection: it asserts a global
    # invariant over the shipped flow definition, so the PR that reintroduces
    # the defect is precisely the PR whose changed-file set might not select it.
    "test_flow_condition_reachability_check.py",
    "test_spec_conformance_check.py",
    "test_rtl_hygiene_lint.py",
    # vibe-ic#381 aftermath — the SKILL-set schema invariants (every SKILL.md
    # carries a Compliance gate; every compliance.yaml has a SKILL.md). Same
    # argument as the reachability guard above, and it was not hypothetical:
    # `flow-change-acceptance` shipped WITHOUT its Compliance-gate section and
    # `test_every_skill_md_has_compliance_gate` sat RED on main unnoticed,
    # because a change to `skills/*/SKILL.md` does not select a test file
    # under `programs/tests/`. The PR that breaks a global invariant over the
    # shipped skills is exactly the PR whose changed-file set cannot reach the
    # test that guards it. ~5 s for 19 tests — cheap enough for the floor.
    "test_tools_and_integration.py",
    # The promised survey (see the commit that added the line above): every
    # test that asserts a property of the WHOLE shipped tree has the same
    # reachability problem, because the selector maps a changed SOURCE file
    # to the test NAMED after it. MEASURED with the selector itself — for a
    # diff adding `programs/<new>.py`, for one touching `skills/*/SKILL.md`,
    # and for one touching the flow YAML, NONE of the four below were
    # selected, though each is exactly what those diffs can break:
    #   INDEX.md must list every program        (a NEW program breaks it)
    #   SKILL.md files must stay chip-AGNOSTIC  (a SKILL edit breaks it)
    #   ALL_STEPS must cover the flow           (a flow edit breaks it)
    #   the retired core must not reappear      (any diff can reintroduce it)
    # ~8 s for the four together.
    "test_programs_index_freshness.py",
    "test_wave76_skill_md_chip_agnostic.py",
    "test_all_steps_covers_flow.py",
    "test_no_vibe_ic_core_reappears.py",
    # vibe-ic#1025 — the same reachability argument, arriving through a SHELL
    # file. Part of what this guard pins is a property of
    # `tools/ci/repo_hygiene_gates.sh`: that the empty-corpus sweep is
    # dispatched by a wrapper which BLOCKS on rc 2 rather than one that records
    # NOT_CHECKED and exits 0. That file is outside `_SOURCE_DIRS` and no test
    # is NAMED after it, so MEASURED with the selector itself on exactly the
    # one-token diff that breaks the wiring: 16 tests selected, this guard NOT
    # among them. The PR that neuters the gate is precisely the PR whose
    # changed-file set cannot reach the test that guards it. ~2 s for 7 tests.
    "test_issue1025_empty_corpus_sweep_blocks.py",
    # vibe-ic#1025 — same reachability argument, arriving through a JSON
    # file. What this guard pins is partly a property of
    # `tools/ci/gate_red_since.json`: that no acknowledgement has an
    # unreachable deadline. That path is outside `_SOURCE_DIRS` and no test
    # is NAMED after it, so MEASURED with the selector on exactly the
    # one-file diff that switches the mechanism off (`max_commits:
    # 9999999`): 16 tests selected, this guard NOT among them. ~3 s.
    "test_gate_red_since_check.py",
    # vibe-ic#1734 — same reachability argument, MEASURED twice on this tree
    # with the real selector, at 7c376e348, one throwaway commit each:
    #
    #   adding `pytestmark = pytest.mark.timeout(2700)` to ONE test file
    #     -> 18 files selected, this guard NOT among them
    #   raising `DEFAULT_STALL_AFTER` in `programs/pytest_per_file_junit.py`
    #     -> 43 files selected, this guard NOT among them
    #
    # The first is the defect itself: `ci_harness_timeout_ceiling_check.py`
    # exists to stop a test declaring a bound it can outlive, and the PR that
    # reintroduces an exemption is a one-line edit to a test file, which
    # selects the test named after that file and not this one. The second is
    # the ceiling's own input — the stall window is resolved from the driver,
    # so a diff that raises it moves this gate's verdict without selecting it.
    #
    # For completeness, because the negative matters as much: a diff touching
    # `tools/gatekeeper-land.sh` DOES select it (72 files), via
    # `_REPO_TOOL_DIRS` below. That lane was already covered; these two were
    # not. The program additionally self-checks before every scan, so the two
    # layers are independent — this roster entry covers the case where the
    # program's own test is what must run, and the self-check covers the case
    # where the program runs at all.
    "test_ci_harness_timeout_ceiling_check.py",
)

# Directories under the plugin root that hold top-level SOURCE modules whose
# unit tests live in programs/tests/. (Test files themselves live only in
# programs/tests/.)
_SOURCE_DIRS: tuple[str, ...] = ("programs", "benchmark")
_TESTS_REL = "programs/tests"

# Rule 6 (vibe-ic#1057) — REPO-ROOT directories that sit OUTSIDE the plugin and
# whose files the plugin's tests drive by PATH rather than by import.
#
# Measured hole this closes: `tools/gatekeeper-land.sh` is named by 40 test
# files, and a change to it selected 15 — the smoke floor, and nothing else.
# Two independent reasons, either one alone sufficient:
#
#   * `select_tests` drops every changed path that is not `.py`, so a shell
#     script never reaches a rule at all; and
#   * even `tools/foo.py` fails `rp.parent.as_posix() in _SOURCE_DIRS`, because
#     these paths are repo-relative and `_SOURCE_DIRS` is plugin-relative.
#
# So the selection was the same 15 files whether the change was a one-character
# comment or a rewrite of the landing script — a green that says nothing about
# the file that moved. The repo has no `.github/workflows/` (only
# `workflows-disabled/`), so this selection IS the gate; there is no broader
# job behind it that would have caught the miss.
#
# This is a DIRECTORY, read from the tree — never a list of filenames, which
# would rot the first time a script is added or renamed.
_REPO_TOOL_DIRS: tuple[str, ...] = ("tools",)

# vibe-ic#1058 — the directory list above turned out to be the wrong shape, and
# the audit that produced this constant's replacement is why.
#
# `tools/` was not special; it was the one we happened to notice. Probing EVERY
# top-level directory with a trivial change, and counting only selections BEYOND
# the smoke floor (a floor hit is not a targeted selection):
#
#   flow/phase1_phase2_phase3.yaml   114 covering tests    0 selected beyond floor
#   skills/rtl-review/SKILL.md        67                   0
#   .claude-plugin/plugin.json        35                   0
#   .claude-plugin/marketplace.json   17                   0
#   agents/ic-expert-agent.md         15                   0
#   pytest.ini / conftest.py / hooks.json / run_tests.sh / SKILL_INVENTORY.json
#                                     1-4 each             0
#
# Every path outside `programs/` and `benchmark/` selected exactly the 15-file
# floor. `flow/phase1_phase2_phase3.yaml` is the canonical 44-step flow — the
# repo's single source of truth — and a change to it selected nothing that reads
# it. Enumerating directories would have to keep pace with every new one; the
# generalisation below needs no list at all, so there is nothing to keep in step.
#
# RULE 7 supersedes rule 6: ANY changed path that no other rule mapped is keyed
# by the most specific suffix of its own path that is UNIQUE in the tree, and
# selects the tests that name that key. `tools/` now flows through this rule;
# `_REPO_TOOL_DIRS` is retained only because rule 6's tests pin it as the
# narrower case that must keep working.
#
# vibe-ic#1176 — rule 7 resolves its key in THREE hops, not one. The key names a
# file; what has to be found is the tests that can break when that file changes,
# and the tree binds them three different ways:
#
#   hop 1  a TEST names the key            glob `test_*.py`          (#1068)
#   hop 2  a tests/ HELPER names it        glob `programs/tests/**`  (#1178)
#   hop 3  a PROGRAM opens it              glob `programs|benchmark/*.py`
#
# Each hop was measured against the flow yaml, and each was the whole gap for
# the tests below it. After hop 2, a flow-yaml change selected 160 files and
# still missed all seven tests that reach the flow through
# `flow_compliance_check.py` / `flow_dashboard_data.py` — programs, so neither
# earlier hop can see them. Hop 3 resolves the naming source module through the
# SAME rules a direct edit of that module takes, so it can never select more
# than editing the module itself would.
#
# Hop 3 alone is LEXICAL and that is not affordable: 66 source modules mention
# the flow yaml (537 dependent tests) but only 23 can open it (159). Programs
# are prose-heavy where helpers are not, so hop 3 keys on a LIVE string literal
# — `ast`, docstrings excluded — and the three giant runners that merely cite
# the yaml drop out. See `_names_key_as_live_literal`.
#
# Uniqueness is what makes the rule safe to apply to everything. `README.md`
# exists 41 times and `SKILL.md` 64 times: their basenames identify no file, so
# they key on a longer suffix that tests do not spell, and select NOTHING rather
# than dragging in every test that mentions a readme. Under-selecting an
# ambiguous name is recoverable; over-selecting teaches people to ignore the
# selection. Measured: 1158 of 6529 distinct basenames in this repo are
# ambiguous, so this is the common case, not a corner.


def _plugin_root_default() -> Path:
    """The plugin root is this file's grandparent (…/vibe-ic/programs/<me>)."""
    return Path(__file__).resolve().parent.parent


def _norm(path: str) -> str:
    return path.replace("\\", "/").strip()


def _to_plugin_rel(path: str, plugin_prefix: str) -> str:
    """Normalise a changed-file path to be relative to the plugin root.

    Accepts a repo-relative path (``<plugin_prefix>/programs/foo.py``) OR a path
    that is already plugin-relative (``programs/foo.py``) — the latter keeps
    synthetic test inputs simple. Anything outside the plugin returns as-is
    (it will simply not classify as a source/test file).
    """
    p = _norm(path)
    if plugin_prefix and p.startswith(plugin_prefix + "/"):
        return p[len(plugin_prefix) + 1:]
    return p


def _source_stems(plugin_root: Path) -> set[str]:
    """Stems of every top-level source module under the source dirs.

    Top-level only (non-recursive): tests reference top-level program modules;
    subdir fixtures/samples are not importable module targets. Test files
    (``test_*.py``) and dunder/helper files are excluded.
    """
    stems: set[str] = set()
    for d in _SOURCE_DIRS:
        src_dir = plugin_root / d
        if not src_dir.is_dir():
            continue
        for py in src_dir.glob("*.py"):
            name = py.name
            if name.startswith("test_") or name.startswith("__"):
                continue
            stems.add(py.stem)
    return stems


def _owning_stem(test_x: str, source_stems: set[str]) -> str | None:
    """Return the LONGEST source stem that owns test basename ``test_x``.

    ``test_x`` is the test filename with the ``test_`` prefix and ``.py`` suffix
    already stripped. Ownership: ``test_x == S`` or ``test_x.startswith(S + '_')``.
    The longest match wins so a more-specific module claims its own tests.
    """
    best: str | None = None
    for s in source_stems:
        if test_x == s or test_x.startswith(s + "_"):
            if best is None or len(s) > len(best):
                best = s
    return best


def _build_test_index(plugin_root: Path, source_stems: set[str]) -> dict[str, set[str]]:
    """Map each source stem -> set of plugin-rel test paths it owns."""
    index: dict[str, set[str]] = {}
    tests_dir = plugin_root / _TESTS_REL
    if not tests_dir.is_dir():
        return index
    for tf in tests_dir.glob("test_*.py"):
        test_x = tf.name[len("test_"):-len(".py")]
        owner = _owning_stem(test_x, source_stems)
        if owner is not None:
            index.setdefault(owner, set()).add(f"{_TESTS_REL}/{tf.name}")
    return index


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _build_import_edge_index(
    plugin_root: Path, source_stems: set[str],
) -> dict[str, set[str]]:
    """Map each source stem -> plugin-rel test paths that DEPEND ON it.

    vibe-ic#565. Two edge kinds, because this tree uses both and either alone
    is a hole:

      import       `import phase3_one_shot_runner`, `from x import y` — parsed
                   with `ast` via the same `_imported_module_names` rule 4 uses,
                   so the two selectors cannot drift.
      explicit     `spec_from_file_location("<stem>", ...)`. MEASURED over 2081
      loader       test files: 1866 import edges, 86 loader edges, and 77 test
                   files carry a loader edge with NO import of the same name.
                   An `ast`-only scan misses those 77 entirely — which is the
                   shape this mode exists to stop, one level down.

    Fail-open, matching rule 4: a file that cannot be read or parsed contributes
    no edges rather than aborting the selection. A selector that dies on one bad
    file selects nothing, and selecting nothing is the defect.
    """
    tests_dir = plugin_root / _TESTS_REL
    if not tests_dir.is_dir():
        return {}

    idx: dict[str, set[str]] = {}
    for tp in sorted(tests_dir.rglob("test_*.py")):
        try:
            text = tp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = tp.relative_to(plugin_root).as_posix()

        names: set[str] = set()
        imported = _imported_module_names(text, _own_package(rel))
        if imported:
            names |= {n for n in imported if n in source_stems}
        for m in _LOADER_NAME_RE.finditer(text):
            if m.group(1) in source_stems:
                names.add(m.group(1))
        # …and the same call read for the file it LOADS, so an alias cannot hide
        # the edge (vibe-ic#1176). Additive: a call whose alias already matched
        # contributes the same stem twice and the set absorbs it.
        for m in _LOADER_CALL_RE.finditer(text):
            for lit in _LOADER_PY_LITERAL_RE.finditer(m.group("args")):
                stem = Path(_norm(lit.group(1))).stem
                if stem in source_stems:
                    names.add(stem)
        # …and the THIRD edge kind: a test that DRIVES the program as a
        # subprocess, naming its file instead of importing it. Same standing as
        # the two above — a STATED dependency, not a mention — because a `.py`
        # basename in a quoted literal is what running a program looks like.
        for m in _DRIVER_PY_LITERAL_RE.finditer(text):
            stem = Path(_norm(m.group(1))).stem
            if stem in source_stems:
                names.add(stem)

        for n in names:
            idx.setdefault(n, set()).add(rel)
    return idx


def _build_reference_index(
    plugin_root: Path, source_stems: set[str],
) -> dict[str, set[str]]:
    """Map each source stem -> set of plugin-rel test paths that NAME it.

    A test file references stem ``S`` if ``S`` occurs in its text as a whole
    identifier. This is the rule that reaches the 54.5% of test files the
    filename-ownership rule cannot (see the module docstring); it is only built
    when a non-default ``--mode`` asks for it, so the default path pays nothing.

    Whole-identifier, not substring: ``_path_layout`` must not be matched by a
    mention of ``_path_layout_helper``. Unreadable files are skipped rather than
    failing the selection — a selector that cannot read one file must still
    emit a list.
    """
    index: dict[str, set[str]] = {}
    tests_dir = plugin_root / _TESTS_REL
    if not tests_dir.is_dir():
        return index
    for tf in tests_dir.glob("test_*.py"):
        try:
            text = tf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = f"{_TESTS_REL}/{tf.name}"
        for name in set(_IDENT.findall(text)) & source_stems:
            index.setdefault(name, set()).add(rel)
    return index


# ---------------------------------------------------------------------------
# Rule 6 — repo-root TOOL scripts (vibe-ic#1057). Built LAZILY, like rule 4:
# nothing here reads the tree unless a changed path is under a repo-root tool
# directory, so every other lane pays exactly nothing.
# ---------------------------------------------------------------------------


def _is_repo_tool(repo_rel: str) -> bool:
    """Is ``repo_rel`` (REPO-relative) a file under a repo-root tool dir?

    Repo-relative on purpose: these paths are the ones `_to_plugin_rel` hands
    back untouched precisely because they are outside the plugin.
    """
    p = _norm(repo_rel)
    return any(p.startswith(d + "/") for d in _REPO_TOOL_DIRS)


def _tool_ref_pattern(basename: str) -> re.Pattern[str]:
    """Match ``basename`` as a whole path token, not as a substring.

    The boundary class includes ``.`` and ``-`` because these names carry them
    (``gatekeeper-land.sh``); a plain ``\\b`` would let ``land.sh`` match inside
    ``pre-land.sh``. Anchoring on both sides is what keeps a new script named
    with an existing one as its suffix from silently inheriting its tests.
    """
    b = r"[A-Za-z0-9_.\-]"
    return re.compile(rf"(?<!{b}){re.escape(basename)}(?!{b})")


def _repo_files(repo_root: Path) -> list[str] | None:
    """Every tracked repo-relative path, or None if the tree cannot be listed.

    None is a real answer, not a failure: a synthetic tree (a unit-test fixture)
    is not a git repo, and the caller degrades to basename keying there. What it
    must never do is raise — a selector that cannot list the tree still has to
    emit a list.
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files"],
            capture_output=True, text=True, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def _distinctive_key(changed: str, repo_files: list[str] | None) -> str | None:
    """The shortest suffix of ``changed`` that identifies exactly ONE repo file.

    Walks the path from the basename upward — ``marketplace.json``, then
    ``.claude-plugin/marketplace.json``, and so on — and returns the first
    suffix that no OTHER tracked file also ends with. That suffix is the most
    specific thing a test could write and still mean this file, so it is the
    right key to search test text for.

    Returns None when NO suffix distinguishes the file. That is not a defect and
    not a rare one: a path can be a proper suffix of a longer path, so it can
    never be spelled unambiguously. `.claude-plugin/marketplace.json` (repo
    root) is exactly this — `vibe-ic-marketplace/.claude-plugin/marketplace.json`
    ends with it, so every reference to the short form is also a reference to the
    long one. Selecting on it would attribute the plugin manifest's tests to the
    repo manifest. None says "this cannot be mapped", and the caller discloses it
    rather than guessing (vibe-ic#1058).
    """
    parts = _norm(changed).split("/")
    if not parts or not parts[-1]:
        return None
    if repo_files is None:
        return parts[-1]          # synthetic tree: basename is all we have
    for i in range(len(parts) - 1, -1, -1):
        suffix = "/".join(parts[i:])
        owners = [f for f in repo_files
                  if f == suffix or f.endswith("/" + suffix)]
        if len(owners) == 1:
            return suffix
    return None


def _build_tool_reference_index(
    plugin_root: Path, tool_basenames: set[str],
) -> dict[str, set[str]]:
    """Map tool BASENAME -> set of plugin-rel test paths that NAME it.

    Keyed on the basename WITH its extension (``gatekeeper-land.sh``), which is
    how a path-driven consumer actually names the file, and never on the bare
    stem: a stem collides across trees (``tools/spec_validator.py`` vs the
    plugin's own ``spec_validator``) and would hand one file's edit the other
    file's tests — a selection that looks richer while pointing at the wrong
    code.

    Unreadable files are skipped rather than failing the run: a selector that
    cannot read one test file must still emit a list.
    """
    index: dict[str, set[str]] = {}
    if not tool_basenames:
        return index
    tests_dir = plugin_root / _TESTS_REL
    if not tests_dir.is_dir():
        return index
    pats = {b: _tool_ref_pattern(b) for b in tool_basenames}
    for tf in sorted(tests_dir.glob("test_*.py")):
        try:
            text = tf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = f"{_TESTS_REL}/{tf.name}"
        for base, pat in pats.items():
            if pat.search(text):
                index.setdefault(base, set()).add(rel)
    return index


# ---------------------------------------------------------------------------
# Rule 4 — shared TEST-HELPER modules (vibe-ic#534). Everything below is built
# LAZILY: nothing here runs unless a changed path is a helper module, so the
# common case (a source or test file changed) pays exactly nothing.
# ---------------------------------------------------------------------------


def _build_key_helper_index(
    plugin_root: Path, keys: set[str],
) -> dict[str, set[str]]:
    """Map key -> set of plugin-rel HELPER modules that NAME it.

    THE SECOND HOP, and rule 7 is incomplete without it. #1068 made an
    unmapped path reach `_build_tool_reference_index`, which globs
    ``test_*.py`` — so a data file is found only when a TEST names it
    literally. MEASURED on `a38902d1`: a change to
    ``flow/phase1_phase2_phase3.yaml`` selects 128 files and
    ``test_matrix_d4_criteria_match.py`` is NOT among them, because that test
    names the yaml zero times. It reaches the flow through
    ``from matrix import flowref``, and the path lives in
    ``programs/tests/matrix/flowref.py`` (3 occurrences).

    d4 recomputes itself from that yaml on every run, so the dimension that
    measures flow-yaml correctness was the one a flow-yaml change did not run.

    This index finds the HELPERS; the caller hands them to `_helper_consumers`
    (rule 4), which already owns helper -> importing-test resolution. Composing
    rather than re-deriving means this hop cannot drift from rule 4.

    Same whole-token matching as `_build_tool_reference_index`, so
    ``flow.yaml`` cannot match inside ``subflow.yaml``. Built LAZILY by its
    only caller, which runs solely when an unmapped path is in the diff.
    """
    index: dict[str, set[str]] = {}
    if not keys:
        return index
    tests_dir = plugin_root / _TESTS_REL
    if not tests_dir.is_dir():
        return index
    pats = {k: _tool_ref_pattern(k) for k in keys}
    for pyf in sorted(tests_dir.rglob("*.py")):
        if pyf.name.startswith("test_"):
            continue          # tests are rule 7's first hop, already covered
        try:
            text = pyf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = f"{_TESTS_REL}/{pyf.relative_to(tests_dir).as_posix()}"
        if not _is_test_helper(rel):
            continue
        for k, pat in pats.items():
            if pat.search(text):
                index.setdefault(k, set()).add(rel)
    return index


def _names_key_as_live_literal(text: str, pat: re.Pattern[str]) -> bool:
    """Does ``text`` hold the key in a string literal that is not a docstring?

    THE DISCRIMINATOR that makes the third hop affordable, and the reason it is
    `ast` rather than another `pat.search(text)`. A source module is prose-heavy
    in a way a test helper is not: this tree's runners cite the flow yaml in
    their module docstrings while never opening it, and a lexical scan cannot
    tell that citation from a path constant.

    MEASURED on `75776dbbb` for key ``phase1_phase2_phase3.yaml``:

        source modules that MENTION it            66   -> 537 dependent tests
        source modules holding it as a LIVE literal 23 ->  159 dependent tests

    The 43 that drop out are docstring and comment citations — `phase3_one_shot_
    runner` (214 dependents, 3 mentions, all prose), `design_one_shot_runner`
    (106), `_path_layout` (51) and this module itself, which names the yaml in
    its own rule-7 docstring. None of them can read the file, so none of their
    dependents can break when it changes; keeping them would have tripled the
    selection for a change none of them can see.

    A comment needs no handling: comments are not in the AST at all.

    Fail-CLOSED on a syntax error, unlike the read paths around it: an
    unparseable source module contributes no key edge rather than falling back
    to the lexical scan this function exists to replace. The fallback would
    re-admit exactly the prose citations, and it would do so silently.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return False
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstrings.add(id(body[0].value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docstrings and pat.search(node.value)):
            return True
    return False


def _build_key_source_index(
    plugin_root: Path, keys: set[str], source_stems: set[str],
) -> dict[str, set[str]]:
    """Map key -> set of SOURCE STEMS that hold it as a live string literal.

    THE THIRD HOP (vibe-ic#1176). Hop one globs ``test_*.py`` and hop two
    (#1178) globs the helpers under ``programs/tests/``. Neither looks at
    ``programs/*.py``, so a data file that only a PROGRAM opens reaches no test
    at all — and the tests that exercise that program through it are the ones a
    change to the data file is most likely to break.

    MEASURED on `75776dbbb`, a one-line edit to ``flow/phase1_phase2_phase3.
    yaml`` after #1178: 160 files selected, and all seven of the residual
    flow-readers #1176 stayed open for are absent. Every one of them reaches the
    flow through ``flow_compliance_check.py`` or ``flow_dashboard_data.py`` —
    programs, not helpers — either by importing the module or by loading it with
    ``spec_from_file_location``:

        test_flow_dashboard_data.py                     D._load_flow()
        test_issue492_gate_argv_conversions.py          local _load_flow()
        test_issue492_umbrella_gate_invocation.py       local _load_flow()
        test_issue559_not_a_project_gate.py             local _load_flow()
        test_issue559_polluter_conversion.py            local _load_flow()
        test_issue559_semantic_argv_gates.py            local _load_flow()
        test_si_mcf_not_run_is_not_a_design_failure.py  F.DEFAULT_FLOW_DEF

    This index finds the STEMS; the caller resolves them through the very rules
    a changed source module already goes through, so the third hop cannot select
    anything a direct edit of that module would not have selected, and cannot
    drift from the mode the caller was asked for.

    Built LAZILY by its only caller, which runs solely when an unmapped path is
    in the diff.
    """
    index: dict[str, set[str]] = {}
    if not keys:
        return index
    pats = {k: _tool_ref_pattern(k) for k in keys}
    for src_dir in _SOURCE_DIRS:
        d = plugin_root / src_dir
        if not d.is_dir():
            continue
        for pyf in sorted(d.glob("*.py")):
            if pyf.stem not in source_stems:
                continue
            try:
                text = pyf.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for k, pat in pats.items():
                if not pat.search(text):
                    continue          # cheap lexical reject before the parse
                if _names_key_as_live_literal(text, pat):
                    index.setdefault(k, set()).add(pyf.stem)
    return index


def _is_test_helper(rel: str) -> bool:
    """Is ``rel`` (plugin-relative) a shared helper module under the tests dir?

    A ``*.py`` file under ``programs/tests/`` — at any depth — whose basename is
    not ``test_*.py``. That is exactly the population rules 1 and 2 cannot see:
    rule 1 only looks at top-level ``programs/`` and ``benchmark/``, rule 2 only
    at ``test_*.py``.
    """
    if not rel.endswith(".py") or not rel.startswith(_TESTS_REL + "/"):
        return False
    return not Path(rel).name.startswith("test_")


def _with_ancestors(dotted: str) -> set[str]:
    """``a.b.c`` -> ``{a, a.b, a.b.c}``.

    Importing ``a.b.c`` executes ``a`` and ``a.b`` too, so a consumer of any of
    them is coupled to the package the changed module lives in.
    """
    parts = dotted.split(".")
    return {".".join(parts[: i + 1]) for i in range(len(parts))}


def _helper_module_names(plugin_root: Path, source_stems: set[str]) -> dict[str, set[str]]:
    """Map plugin-rel helper path -> every name it can be imported by.

    Two naming schemes are emitted because the tree really uses both:

    * the path-dotted name relative to ``programs/tests/`` (which conftest puts
      on ``sys.path``): ``matrix/waivers.py`` -> ``matrix.waivers``,
      and ``<pkg>/__init__.py`` -> ``<pkg>``;
    * the bare basename, for nested helpers imported by bare name after an
      inline ``sys.path.insert`` (``from synthetic_protocol_blobs import …``).
      Emitted ONLY when unambiguous: dropped if two helpers share the basename,
      or if it collides with a top-level source stem (``import waivers_schema_
      check`` must stay a rule-1 source module, never a tests-dir helper).
    """
    tests_dir = plugin_root / _TESTS_REL
    if not tests_dir.is_dir():
        return {}

    paths: list[Path] = []
    for py in tests_dir.rglob("*.py"):
        if py.name.startswith("test_") or not py.is_file():
            continue
        paths.append(py)

    # Count basenames first so an ambiguous bare alias can be withheld.
    base_counts: dict[str, int] = {}
    for py in paths:
        stem = py.parent.name if py.name == "__init__.py" else py.stem
        base_counts[stem] = base_counts.get(stem, 0) + 1

    out: dict[str, set[str]] = {}
    for py in paths:
        rel_in_tests = py.relative_to(tests_dir)
        parts = list(rel_in_tests.parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
            if not parts:          # programs/tests/__init__.py — not a package
                continue
        else:
            parts[-1] = rel_in_tests.stem
        dotted = ".".join(parts)
        names = {dotted}
        bare = parts[-1]
        if base_counts.get(bare, 0) == 1 and bare not in source_stems:
            names.add(bare)
        out[f"{_TESTS_REL}/{py.relative_to(tests_dir).as_posix()}"] = names
    return out


def _imported_module_names(text: str, own_package: str | None) -> set[str] | None:
    """Every module name imported by ``text``, ancestors included.

    ``own_package`` is the dotted package the file lives in (``matrix`` for
    ``matrix/cells.py``, ``None`` at the tests-dir top level) and resolves
    relative imports: inside ``matrix``, ``from . import flowref`` and
    ``from .flowref import StepId`` both yield ``matrix.flowref``.

    Returns ``None`` when the file cannot be parsed — a selector must not go
    quiet because one file is unreadable or syntactically broken; the caller
    treats ``None`` as "unknown", not as "imports nothing".
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found |= _with_ancestors(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # Relative: climb `level - 1` packages up from own_package.
                if own_package is None:
                    continue
                base_parts = own_package.split(".")
                up = node.level - 1
                base_parts = base_parts[: len(base_parts) - up] if up else base_parts
                if not base_parts:
                    continue
                base = ".".join(base_parts)
                mod = f"{base}.{node.module}" if node.module else base
            else:
                if not node.module:
                    continue
                mod = node.module
            found |= _with_ancestors(mod)
            # `from a.b import c` also binds `a.b.c` when c is a submodule.
            for alias in node.names:
                if alias.name != "*":
                    found.add(f"{mod}.{alias.name}")
    return found


def _own_package(rel: str) -> str | None:
    """Dotted package of a plugin-rel tests file, or None at the tests root."""
    parts = Path(rel[len(_TESTS_REL) + 1:]).parts[:-1]
    return ".".join(parts) if parts else None


def _helper_consumers(plugin_root: Path, changed_helpers: list[str],
                      source_stems: set[str]) -> set[str]:
    """Plugin-rel test files that import any of ``changed_helpers``.

    Three edge kinds, all derived from ``import`` statements — never listed:

      1. direct     — a test imports the changed module by either of its names;
      2. package    — a test imports an ANCESTOR package of the changed module
                      (``from matrix import cells`` when ``waivers.py``
                      changed), because both resolve through the package whose
                      contents moved;
      3. transitive — helper -> helper -> test (a change to ``flowref.py``
                      reaches the tests that import ``matrix_d4_probe``).
    """
    tests_dir = plugin_root / _TESTS_REL
    if not tests_dir.is_dir():
        return set()
    helpers = _helper_module_names(plugin_root, source_stems)

    targets: set[str] = set()
    for rel in changed_helpers:
        for name in helpers.get(rel, set()):
            targets |= _with_ancestors(name)
    if not targets:
        return set()

    # (3) Close over helper -> helper imports until nothing new is reached.
    helper_imports: dict[str, set[str]] = {}
    for rel in helpers:
        try:
            txt = (plugin_root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        got = _imported_module_names(txt, _own_package(rel))
        helper_imports[rel] = set() if got is None else got
    for _ in range(len(helpers) + 1):
        grew = False
        for rel, imported in helper_imports.items():
            names = helpers.get(rel, set())
            if names <= targets or not (imported & targets):
                continue
            targets |= {a for n in names for a in _with_ancestors(n)}
            grew = True
        if not grew:
            break

    # Sound superset pre-filter: no import form of `a.b` can omit the literal
    # `a`, so a file without any target's top-level name cannot import one.
    tops = {t.split(".")[0] for t in targets}
    selected: set[str] = set()
    for tf in tests_dir.glob("test_*.py"):
        try:
            txt = tf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not any(top in txt for top in tops):
            continue
        rel = f"{_TESTS_REL}/{tf.name}"
        imported = _imported_module_names(txt, None)
        if imported is None or imported & targets:
            selected.add(rel)
    return selected


# Rule 8 — DIRECTORY CONSUMERS (vibe-ic#1387). Built LAZILY, like rules 4/6/7.
#
# A test (or a shared helper) that reads a source directory by GLOB depends on
# every file in it, and says so nowhere a name-based rule can see. The measured
# case: `matrix_d7_artifact_graph.py:524` does
#
#     for path in sorted(F.PROGRAMS_DIR.glob("*.py")):
#
# and parses the AST of every program. A change to `programs/eda_report_audit.py`
# therefore reddens `test_matrix_d7_outputs_list_complete.py` — while `grep -c
# eda_report_audit` over BOTH files returns 0, so rule 3 has no name to match and
# rule 5 has no import to follow. #1265 was verified NEW 0 by the documented
# method and the delegate test, run by hand, was 11 red against main's 10.
#
# This is vibe-ic#534 one level out. #534: helpers are consumed by `import`, and
# nothing modelled it -> rule 4. Here: source DIRECTORIES are consumed by `glob`,
# and nothing modelled it.
#
# DERIVED, not listed, for the reason rule 4's docstring already gives: a
# hand-list is a second registry free to drift, and it would have been wrong on
# arrival — the tree has 19 `*.py` glob sites across 23 files today, and the
# number moves whenever anyone writes a corpus-walking test. So the PATTERN is
# read out of the AST and matched against the changed path with `fnmatch`.
#
# `iterdir()`/`walk()` are deliberately NOT edges: they carry no pattern, so the
# only sound reading is "every file in some unknown directory", which would
# select all 273 directory-reading files for any change. A pattern is what makes
# the edge specific enough to be worth having.
_DIR_GLOB_CALLS = ("glob", "rglob")

# A pattern that matches EVERYTHING names no shape, and in this tree it almost
# never means "read the source tree": measured, 38 of the 56 files that would
# match `programs/eda_report_audit.py` matched ONLY via `"*"`, and they are
# `tmp_path.glob("*")` fixtures asserting what a run wrote into a temp dir. That
# is the same objection already made against `iterdir()` above — an edge with no
# shape is an edge to everything — so the universal patterns are excluded on the
# same ground rather than a different one. Dropping them takes the #1265 case
# from +53 files to +18, and `matrix_d7_artifact_graph.py` (`"*.py"`) is
# untouched by the exclusion.
_UNSHAPED_PATTERNS = frozenset({"*", "**", "**/*", "*/*"})


def _glob_patterns_in(text: str) -> set[str]:
    """Literal patterns this file passes to `.glob()` / `.rglob()`.

    Fail-open like rule 4: an unparseable file contributes nothing rather than
    raising. A non-literal pattern (an f-string, a variable) is skipped for the
    same reason `iterdir` is — it names no shape that can be matched.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()
    out: set[str] = set()
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        fn = n.func
        if not isinstance(fn, ast.Attribute) or fn.attr not in _DIR_GLOB_CALLS:
            continue
        if n.args and isinstance(n.args[0], ast.Constant) \
                and isinstance(n.args[0].value, str):
            pat = n.args[0].value
            if pat not in _UNSHAPED_PATTERNS:
                out.add(pat)
    return out


def _build_dir_consumer_index(plugin_root: Path) -> dict[str, set[str]]:
    """`plugin-rel test-tree file` -> the glob patterns it reads.

    Cost is paid only when rule 8 actually fires. The `"glob("` text filter is a
    sound superset — no call to `.glob(...)` can omit the literal `glob(` — and
    it keeps the `ast` parse off the ~90% of the test tree that never globs.
    """
    tests_dir = plugin_root / _TESTS_REL
    if not tests_dir.is_dir():
        return {}
    out: dict[str, set[str]] = {}
    for path in sorted(tests_dir.rglob("*.py")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "glob(" not in text:
            continue
        pats = _glob_patterns_in(text)
        if pats:
            out[path.relative_to(plugin_root).as_posix()] = pats
    return out


def _dir_consumers(plugin_root: Path, changed_sources: list[str],
                   source_stems: set[str]) -> set[str]:
    """Rule 8: test-tree files whose glob pattern matches a changed source path.

    A matching TEST file is selected directly. A matching HELPER is routed back
    through rule 4, so the tests that import it come too — which is the whole
    path from `programs/eda_report_audit.py` to
    `test_matrix_d7_outputs_list_complete.py`: the glob edge reaches
    `matrix_d7_artifact_graph.py`, and rule 4 carries it to the test.
    """
    if not changed_sources:
        return set()
    index = _build_dir_consumer_index(plugin_root)
    if not index:
        return set()
    hit_tests: set[str] = set()
    hit_helpers: list[str] = []
    for rel, pats in index.items():
        name = Path(rel).name
        for src in changed_sources:
            base = Path(src).name
            if any(fnmatch.fnmatch(base, p) or fnmatch.fnmatch(src, p)
                   for p in pats):
                if name.startswith("test_"):
                    if (plugin_root / rel).is_file():
                        hit_tests.add(rel)
                elif _is_test_helper(rel):
                    hit_helpers.append(rel)
                break
    if hit_helpers:
        hit_tests |= _helper_consumers(plugin_root, hit_helpers, source_stems)
        hit_tests |= {h for h in hit_helpers if Path(h).name.startswith("test_")}
    return hit_tests


def _smoke_set(plugin_root: Path) -> set[str]:
    """The curated smoke set, filtered to basenames that actually exist."""
    out: set[str] = set()
    tests_dir = plugin_root / _TESTS_REL
    for base in SMOKE_BASENAMES:
        if (tests_dir / base).is_file():
            out.add(f"{_TESTS_REL}/{base}")
    return out


def import_edge_gap(
    changed_paths: list[str], selected: list[str] | set[str],
    plugin_root: Path,
) -> tuple[list[tuple[str, int, int, int]], int]:
    """(rows, total_missed) — what the selection LEFT OUT, by import edge.

    Each row is ``(source_stem, imported_by, selected, not_selected)``. PURE and
    separate from `main` so it can be driven against a constructed tree; the
    inline version could only be exercised through the CLI, which resolves
    `plugin_root` from the SCRIPT's own location and therefore always audits the
    real plugin — a fixture handed to it was never read, and the test that
    thought it was passed for the wrong reason.

    vibe-ic#565. The default `ownership` mode maps a changed module to tests by
    FILENAME, so 2035 of 2850 import edges (71%) are unseeable by name. Whether
    to WIDEN the default is a cost decision and stays the owner's; this reports
    the shortfall so a landing is not stamped on a count that reads as coverage.
    Changed TEST files are excluded — rule 2 already selects them, and their
    stems are not source modules.
    """
    stems = {Path(c).stem for c in changed_paths
             if c.endswith(".py") and f"/{_TESTS_REL.split('/')[-1]}/" not in c}
    if not stems:
        return [], 0
    idx = _build_import_edge_index(plugin_root, stems)
    sel = set(selected)
    rows: list[tuple[str, int, int, int]] = []
    total = 0
    for stem in sorted(idx):
        importers = idx[stem]
        if not importers:
            continue
        missed = len(importers - sel)
        total += missed
        rows.append((stem, len(importers), len(importers) - missed, missed))
    return rows, total


def select_tests(
    changed_paths: list[str],
    plugin_root: Path,
    plugin_prefix: str = "",
    mode: str = MODE_OWNERSHIP,
    ref_max_tests: int = DEFAULT_REF_MAX_TESTS,
) -> list[str]:
    """Pure selector: changed files -> sorted plugin-rel test paths.

    Always includes the smoke set (the floor); adds owned tests for changed
    source modules, directly-changed test files, and — for a changed SHARED
    TEST-HELPER module under ``programs/tests/`` — the tests that import it
    (rule 4, vibe-ic#534). Never returns an empty list (smoke floor), assuming
    at least one smoke basename exists on disk.

    Rule 4 applies in EVERY mode: it is not a coverage/cost trade-off like the
    ``--mode`` frontier below but a population the other rules never see at all,
    and it costs nothing unless a helper is in the diff.

    ``mode`` is OPT-IN and defaults to the shipped behaviour:

      * ``ownership``       — rules 1-3 only. The default; nothing in CI passes
                              anything else, and this path never builds the
                              reference index.
      * ``reference``       — additionally, every test file that NAMES a changed
                              source stem.
      * ``reference-capped``— the same, except a stem named by more than
                              ``ref_max_tests`` test files contributes nothing
                              through the reference rule (its owned tests still
                              apply). Bounds the cost the giant modules impose.

    See the module docstring for the measured coverage/cost of each.
    """
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {MODES}")

    source_stems = _source_stems(plugin_root)
    index = _build_test_index(plugin_root, source_stems)
    ref_index: dict[str, set[str]] = {}
    if mode in (MODE_REFERENCE, MODE_REFERENCE_CAPPED):
        ref_index = _build_reference_index(plugin_root, source_stems)
    # vibe-ic#565 — built ONLY for import-edge mode, and only when something was
    # actually changed, so the default lane pays nothing for it.
    edge_index: dict[str, set[str]] = {}
    if mode == MODE_IMPORT_EDGE:
        edge_index = _build_import_edge_index(plugin_root, source_stems)

    selected: set[str] = set(_smoke_set(plugin_root))
    changed_helpers: list[str] = []
    changed_tools: set[str] = set()
    unmapped: list[str] = []
    changed_sources: list[str] = []          # rule 8 (vibe-ic#1387)

    for raw in changed_paths:
        rel = _to_plugin_rel(raw, plugin_prefix)
        # (6) a changed repo-root TOOL script -> the tests that NAME it.
        # Checked BEFORE the `.py` guard below, which is one of the two reasons
        # this population was invisible: a `.sh` never survived to reach a rule.
        if _is_repo_tool(rel):
            changed_tools.add(Path(rel).name)
            continue
        if not rel.endswith(".py"):
            # (7) anything else the rules below cannot classify. Formerly a
            # silent `continue`, which is precisely how a change to the canonical
            # flow YAML came to select the smoke floor and nothing else.
            unmapped.append(raw)
            continue
        rp = Path(rel)
        # (2) a changed test file -> include directly (if it still exists).
        if rel.startswith(_TESTS_REL + "/") and rp.name.startswith("test_"):
            if (plugin_root / rel).is_file():
                selected.add(rel)
            continue
        # (4) a changed shared test-helper module -> the tests that import it.
        if _is_test_helper(rel):
            changed_helpers.append(rel)
            continue
        # (1) a changed top-level source module -> its owned tests.
        if rp.parent.as_posix() in _SOURCE_DIRS and not rp.name.startswith("test_"):
            selected |= index.get(rp.stem, set())
            # (8) a source file is also read by every test that GLOBS its
            # directory. Collected here, resolved lazily below.
            changed_sources.append(rel)
            # (4, opt-in) every test file that NAMES the changed module.
            if mode in (MODE_REFERENCE, MODE_REFERENCE_CAPPED):
                refs = ref_index.get(rp.stem, set())
                if mode == MODE_REFERENCE or len(refs) <= ref_max_tests:
                    selected |= refs
            # (5, opt-in) every test file that DEPENDS ON the changed module —
            # an import, or an explicit `spec_from_file_location` loader.
            #
            # vibe-ic#565. NOT capped, deliberately: the cap is what makes
            # `reference-capped` useless for this defect, because it zeroes
            # exactly the large, frequently-changed modules where a silent
            # revert is most likely (`phase3_one_shot_runner` is named by 198
            # test files, well over the 50 default). A STATED dependency is not
            # noise that needs bounding — every file selected here carries an
            # edge pointing at the module that changed.
            elif mode == MODE_IMPORT_EDGE:
                selected |= edge_index.get(rp.stem, set())
        else:
            # (7) a `.py` inside the plugin but NOT under a source dir — the
            # second half of the same hole. `conftest.py` and `pytest.ini` sit
            # here, as does anything under `mcp-eda/`.
            unmapped.append(raw)

    # (4) Built LAZILY — only when a shared test-helper module actually changed,
    # so the common case never reads the tree.
    if changed_helpers:
        selected |= _helper_consumers(plugin_root, changed_helpers, source_stems)

    # (8) Built LAZILY, same as rules 4 and 6 and for the same reason: the
    # index is read only when a source file is actually in the diff.
    #
    # Applies in EVERY mode and is NOT capped, on rule 4's argument: `--mode`
    # trades coverage against cost over a population the other rules DO see,
    # whereas a glob consumer is seen by no rule at all. Capping it would
    # restore the hole for exactly the corpus-walking matrix tests where a
    # silent miss is most expensive — that is the #1265 failure, verbatim.
    if changed_sources:
        selected |= _dir_consumers(plugin_root, changed_sources, source_stems)

    # (6) Built LAZILY, same as rule 4 and for the same reason.
    #
    # Applies in EVERY mode, and is NOT capped. Both deliberate, and the same
    # argument rule 4 already makes: `--mode` trades coverage against cost over
    # a population the other rules DO see, whereas these files were seen by no
    # rule at all — a cap here would restore the original hole for exactly the
    # heavily-referenced scripts (`gatekeeper-land.sh` at 40 tests) where a
    # silent break is most expensive. A test that names the script by path is
    # a STATED dependency, not noise that needs bounding.
    if changed_tools:
        tool_index = _build_tool_reference_index(plugin_root, changed_tools)
        for base in changed_tools:
            selected |= tool_index.get(base, set())

    # (7) Everything no other rule claimed. LAZY like rules 4 and 6: the tree is
    # listed only when such a path is actually in the diff, so the common case
    # (a change under `programs/`) still reads nothing extra.
    #
    # `unmappable` is collected, not discarded — `select_unmappable` re-derives
    # it for the CLI, which discloses these paths instead of letting them pass
    # as a silent floor-only selection.
    if unmapped:
        repo_files = _repo_files(_repo_root_of(plugin_root, plugin_prefix))
        keys = {k for k in (_distinctive_key(u, repo_files) for u in unmapped)
                if k}
        if keys:
            key_index = _build_tool_reference_index(plugin_root, keys)
            for k in keys:
                selected |= key_index.get(k, set())
            # SECOND HOP. The index above globs `test_*.py`, so a data file that
            # only a HELPER names is found by nothing — which is why a flow-yaml
            # change still missed `test_matrix_d4_criteria_match.py` (0 mentions;
            # it reads the flow via `matrix/flowref.py`). Resolve those
            # helpers through rule 4, which already owns helper -> test.
            helper_index = _build_key_helper_index(plugin_root, keys)
            named_helpers = sorted({h for k in keys
                                    for h in helper_index.get(k, set())})
            if named_helpers:
                selected |= _helper_consumers(
                    plugin_root, named_helpers, source_stems)
            # THIRD HOP (vibe-ic#1176). Hops one and two between them see only
            # `test_*.py` and the helpers under `programs/tests/`, so a data
            # file that only a PROGRAM opens still reaches nothing. Resolve the
            # naming source modules through the SAME rules a direct edit of
            # those modules would take — rule 1's ownership always, plus
            # whatever the requested `--mode` adds — so this hop can never
            # select more than editing the module itself would, and never
            # diverges from the mode it was asked for.
            source_index = _build_key_source_index(
                plugin_root, keys, source_stems)
            for k in keys:
                for stem in source_index.get(k, set()):
                    selected |= index.get(stem, set())
                    if mode in (MODE_REFERENCE, MODE_REFERENCE_CAPPED):
                        refs = ref_index.get(stem, set())
                        if mode == MODE_REFERENCE or len(refs) <= ref_max_tests:
                            selected |= refs
                    elif mode == MODE_IMPORT_EDGE:
                        selected |= edge_index.get(stem, set())

    # Only emit tests that exist on disk (robust against a stale index entry).
    return sorted(t for t in selected if (plugin_root / t).is_file())


def _repo_root_of(plugin_root: Path, plugin_prefix: str) -> Path:
    """The repo root implied by ``plugin_root`` and ``plugin_prefix``.

    Derived by stripping the prefix's segments, NOT by asking git — the caller
    may be operating on a synthetic tree, and this must stay a pure function of
    its arguments so the same call is reproducible off a real checkout.
    """
    if not plugin_prefix:
        return plugin_root
    root = plugin_root
    for _ in [p for p in _norm(plugin_prefix).split("/") if p]:
        root = root.parent
    return root


def select_unmappable(changed_paths: list[str], plugin_root: Path,
                      plugin_prefix: str = "") -> list[str]:
    """Changed paths that map to NO test set — the honest gap in a selection.

    Separate from `select_tests` so the selection itself stays a pure list and
    every caller keeps working unchanged. See the `--strict-unmapped` flag: this
    is the input to the loud-missing-answer path (vibe-ic#1058).
    """
    repo_files = _repo_files(_repo_root_of(plugin_root, plugin_prefix))
    index_cache: dict[str, set[str]] | None = None
    out: list[str] = []
    for raw in changed_paths:
        rel = _to_plugin_rel(raw, plugin_prefix)
        rp = Path(rel)
        mapped_by_other_rule = (
            (rel.startswith(_TESTS_REL + "/") and rp.name.startswith("test_"))
            or _is_test_helper(rel)
            or (rel.endswith(".py")
                and rp.parent.as_posix() in _SOURCE_DIRS
                and not rp.name.startswith("test_"))
        )
        if mapped_by_other_rule:
            continue
        key = (Path(rel).name if _is_repo_tool(rel)
               else _distinctive_key(raw, repo_files))
        if not key:
            out.append(raw)          # no suffix identifies it — unmappable
            continue
        if index_cache is None:
            index_cache = {}
        hits = index_cache.get(key)
        if hits is None:
            hits = _build_tool_reference_index(plugin_root, {key}).get(key, set())
            index_cache[key] = hits
        if not hits:
            out.append(raw)          # identifiable, but no test names it
    return sorted(set(out))


def _git_changed_files(base: str, repo_root: Path) -> list[str] | None:
    """Every path that differs from ``base`` RIGHT NOW — committed or not.

    The union of two questions, because either alone has a blind spot:

    * ``<base>..HEAD`` — what the commits say. Blind to the index and the
      working tree.
    * ``<base>`` (base vs working tree) — what is actually on disk, staged and
      unstaged. This is what a gatekeeper standing on a squash-merged-but-not-
      yet-committed tree has.

    In CI the tree is clean and HEAD is the PR tip, so the two agree and the
    union changes nothing. The union matters LOCALLY, and it is the defect this
    replaces: the merge queue stages a squash (so ``HEAD == base``, diff empty)
    and then asks which tests the change needs. The old answer was the smoke
    floor — indistinguishable from "your change needs nothing else". Two
    landings were gated on that answer before it was caught.

    Returns repo-relative paths, or None if git/history is unavailable (caller
    then falls back to the smoke set only).
    """
    seen: list[str] = []
    ok = False
    for args in ([f"{base}..HEAD"], [base]):
        try:
            r = subprocess.run(
                ["git", "-C", str(repo_root), "diff", "--name-only", *args],
                capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode != 0:
            continue
        ok = True
        for ln in r.stdout.splitlines():
            if ln.strip() and ln not in seen:
                seen.append(ln)
    return seen if ok else None


def _repo_root(plugin_root: Path) -> Path | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(plugin_root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    top = r.stdout.strip()
    return Path(top) if top else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Select a fast targeted pytest subset from the PR diff "
                    "(plus a fixed doctrine smoke set) for the gatekeeper "
                    "patch-cadence CI gate.",
    )
    ap.add_argument("--base", required=True,
                    help="base SHA/ref; diff is <base>..HEAD")
    ap.add_argument("--plugin-root", default=None,
                    help="plugin root (default: this file's grandparent)")
    ap.add_argument("--no-gap-report", action="store_true",
                    help="skip the import-edge gap disclosure (vibe-ic#565). "
                         "It costs ~3 s over the tests tree and does not change "
                         "what is selected; opting out means the landing is "
                         "stamped without knowing what the selection dropped.")
    ap.add_argument("--mode", choices=MODES, default=MODE_IMPORT_EDGE,
                    help="selection rule (default: %(default)s). OWNER DECISION "
                         "(vibe-ic#565): the default follows the IMPORT EDGES a "
                         "test declares, not the test's FILENAME. A test named "
                         "after the chip or the feature rather than after the "
                         "module it pins was never selected, and a 734-line edit "
                         "silently reverted a landed fix for three releases "
                         "because of it. 'ownership' remains available and is "
                         "now the opt-IN narrowing; see the module docstring for "
                         "the measured coverage/cost frontier.")
    ap.add_argument("--strict-unmapped", action="store_true",
                    help="EXIT 3 if any changed path maps to no test set, and "
                         "name those paths on stderr (vibe-ic#1058). Off by "
                         "default: prose and generated corpora legitimately map "
                         "to nothing, so ON by default would fail most diffs and "
                         "be switched off within a week. The DISCLOSURE below is "
                         "unconditional — this flag only decides whether an "
                         "unmapped path is fatal.")
    ap.add_argument("--ref-max-tests", type=int, default=DEFAULT_REF_MAX_TESTS,
                    help="reference-capped only: a stem named by more than this "
                         "many test files contributes nothing through the "
                         "reference rule (default: %(default)s)")
    args = ap.parse_args(argv)

    plugin_root = Path(args.plugin_root).resolve() if args.plugin_root \
        else _plugin_root_default()

    repo_root = _repo_root(plugin_root)
    plugin_prefix = ""
    changed: list[str] | None = None
    if repo_root is not None:
        try:
            plugin_prefix = plugin_root.resolve().relative_to(repo_root).as_posix()
        except ValueError:
            plugin_prefix = ""
        changed = _git_changed_files(args.base, repo_root)

    if changed is None:
        # git unavailable -> honest smoke-only floor (never zero coverage).
        print(f"[ci_targeted_test_select] git diff unavailable for base={args.base!r}; "
              f"emitting smoke set only", file=sys.stderr)
        changed = []
    elif not changed:
        # LOUD, because this output is otherwise identical to a real selection
        # and reads as "your change needs no further tests".
        print(f"[ci_targeted_test_select] NO CHANGES vs base={args.base!r} "
              f"(neither committed nor in the working tree). What follows is the "
              f"smoke FLOOR, not a targeted selection — if you expected your edit "
              f"to be seen here, it is not in this repository at this base.",
              file=sys.stderr)

    selected = select_tests(changed, plugin_root, plugin_prefix,
                            mode=args.mode, ref_max_tests=args.ref_max_tests)
    for t in selected:
        print(t)
    print(f"[ci_targeted_test_select] selected {len(selected)} test file(s) "
          f"from {len(changed)} changed path(s) (base={args.base}, "
          f"mode={args.mode})", file=sys.stderr)

    # vibe-ic#565 — SAY WHAT WAS LEFT OUT. The default `ownership` mode maps a
    # changed module to tests by FILENAME, so a test named after the chip or the
    # feature is invisible however directly it imports the module: 2035 of 2850
    # import edges (71%) are unseeable by name. Whether to WIDEN the default is
    # a cost decision and stays the owner's — but a bounded selection that does
    # not say what it dropped reads as full coverage, and that is what a landing
    # gets stamped on. Measured: the landing that changed
    # `phase3_one_shot_runner` selected 17 files while 162 test files import it.
    #
    # The index costs 2.98 s over the whole tests tree — affordable beside a
    # landing that already runs for minutes, and it is the only way this number
    # exists at all. `--no-gap-report` opts out for a caller that cannot pay it.
    if not args.no_gap_report:
        try:
            rows, miss_total = import_edge_gap(changed, selected, plugin_root)
            if rows:
                print("[ci_targeted_test_select] IMPORT-EDGE GAP — test files "
                      "that IMPORT a changed module and were NOT selected (the "
                      "default maps by filename, not by import):",
                      file=sys.stderr)
                for stem, n_imp, n_sel, n_missed in rows:
                    print(f"    {stem:<34} imported by {n_imp:>4}, selected "
                          f"{n_sel:>4}, NOT selected {n_missed:>4}",
                          file=sys.stderr)
                print(f"    TOTAL not selected: {miss_total} — rerun with "
                      f"`--mode import-edge` to include them (vibe-ic#565)",
                      file=sys.stderr)
        except Exception as _gap_exc:            # noqa: BLE001
            # The report is a disclosure, not a dependency: a selection that
            # dies computing its own footnote selects nothing, and selecting
            # nothing is the defect this file exists against.
            print(f"[ci_targeted_test_select] import-edge gap report "
                  f"unavailable ({_gap_exc}) — the selection above stands, but "
                  f"what it left out is UNKNOWN, not zero", file=sys.stderr)

    # vibe-ic#1058 — UNMAPPED disclosure. Unconditional, because the failure this
    # closes is not "the selection was wrong" but "the selection was silently
    # generic and read as coverage". Naming the paths converts that into a fact
    # a reviewer can act on. `--strict-unmapped` decides only whether it is fatal.
    try:
        unmapped = select_unmappable(changed, plugin_root, plugin_prefix)
    except Exception as _un_exc:                     # noqa: BLE001
        print(f"[ci_targeted_test_select] unmapped-path report unavailable "
              f"({_un_exc}) — the selection above stands, but whether every "
              f"changed path reached a test set is UNKNOWN, not yes",
              file=sys.stderr)
        return 0
    if unmapped:
        print(f"[ci_targeted_test_select] UNMAPPED — {len(unmapped)} changed "
              f"path(s) map to NO test set. The selection above covers the rest; "
              f"for these it is the smoke floor, which is not evidence about "
              f"them:", file=sys.stderr)
        for u in unmapped:
            print(f"    {u}", file=sys.stderr)
        if args.strict_unmapped:
            print("    --strict-unmapped: failing rather than reporting a green "
                  "over paths nothing verified (vibe-ic#1058)", file=sys.stderr)
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
