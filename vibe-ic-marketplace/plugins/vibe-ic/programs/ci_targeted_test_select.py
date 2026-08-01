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
     ``programs/tests/matrix_63x8/waivers.py`` or
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
itself a test — ``matrix_63x8/{waivers,cells,flowref}.py``, ``_hostpaths.py``,
``_plugin_tree.py``, ``_source_pin.py``, ``_gdsii.py``, ``matrix_d4_probe.py``,
``matrix_d7_artifact_graph.py``. Measured on this tree BEFORE rule 4, with the
real CLI (``--base HEAD``, one-line edit to ``matrix_63x8/waivers.py``): the
selector saw the changed path (``1 changed path(s)``) and emitted 15 files —
exactly the smoke floor, 0 of the 11 test files that import it.

That was not an ordinary coverage gap. ``matrix_63x8/waivers.py`` is the CENTRAL
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
    ``programs/tests/`` (``matrix_63x8/waivers.py`` -> ``matrix_63x8.waivers``,
    ``matrix_63x8/__init__.py`` -> ``matrix_63x8``), plus its bare basename when
    that name is unambiguous — this tree really does bare-import a nested helper
    after an inline ``sys.path.insert`` (``from synthetic_protocol_blobs import
    …``), so path-dotted names alone would miss it;
  * importing ``a.b`` imports ``a``, so ancestor packages count as imported.
    This is what couples the whole ``matrix_63x8`` package: a test that reads
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
    matrix_63x8/waivers.py                 11                             ~1 s
    matrix_63x8/cells.py                   11
    matrix_63x8/flowref.py                 11
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
    # test that guards it. ~4 s for 15 tests — cheap enough for the floor.
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
)

# Directories under the plugin root that hold top-level SOURCE modules whose
# unit tests live in programs/tests/. (Test files themselves live only in
# programs/tests/.)
_SOURCE_DIRS: tuple[str, ...] = ("programs", "benchmark")
_TESTS_REL = "programs/tests"


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
# Rule 4 — shared TEST-HELPER modules (vibe-ic#534). Everything below is built
# LAZILY: nothing here runs unless a changed path is a helper module, so the
# common case (a source or test file changed) pays exactly nothing.
# ---------------------------------------------------------------------------


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
      on ``sys.path``): ``matrix_63x8/waivers.py`` -> ``matrix_63x8.waivers``,
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

    ``own_package`` is the dotted package the file lives in (``matrix_63x8`` for
    ``matrix_63x8/cells.py``, ``None`` at the tests-dir top level) and resolves
    relative imports: inside ``matrix_63x8``, ``from . import flowref`` and
    ``from .flowref import StepId`` both yield ``matrix_63x8.flowref``.

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
                      (``from matrix_63x8 import cells`` when ``waivers.py``
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


def _smoke_set(plugin_root: Path) -> set[str]:
    """The curated smoke set, filtered to basenames that actually exist."""
    out: set[str] = set()
    tests_dir = plugin_root / _TESTS_REL
    for base in SMOKE_BASENAMES:
        if (tests_dir / base).is_file():
            out.add(f"{_TESTS_REL}/{base}")
    return out


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

    for raw in changed_paths:
        rel = _to_plugin_rel(raw, plugin_prefix)
        if not rel.endswith(".py"):
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

    # (4) Built LAZILY — only when a shared test-helper module actually changed,
    # so the common case never reads the tree.
    if changed_helpers:
        selected |= _helper_consumers(plugin_root, changed_helpers, source_stems)

    # Only emit tests that exist on disk (robust against a stale index entry).
    return sorted(t for t in selected if (plugin_root / t).is_file())


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
    ap.add_argument("--mode", choices=MODES, default=MODE_OWNERSHIP,
                    help="selection rule (default: %(default)s — the shipped "
                         "behaviour). 'reference'/'reference-capped' are OPT-IN "
                         "and cost more; see the module docstring for the "
                         "measured coverage/cost frontier.")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
