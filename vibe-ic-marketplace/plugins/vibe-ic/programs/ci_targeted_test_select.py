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

Output: plugin-root-relative test paths, one per line, deduped and sorted, to
stdout. The list is NEVER empty — the smoke set is the floor. If git is
unavailable (no history / not a repo), only the smoke set is emitted.

This is deliberately a PROGRAM, not workflow YAML: the mapping is testable and
lives next to the tests it selects. See
``programs/tests/test_ci_targeted_test_select.py``.

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
  reference           1849 (98.9%)   3 / 3              48.5            213

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
import re
import subprocess
import sys
from pathlib import Path

# Selection modes. `ownership` is the DEFAULT and the shipped behaviour; the
# other two are opt-in and measured in the module docstring (vibe-ic#452).
MODE_OWNERSHIP = "ownership"
MODE_REFERENCE = "reference"
MODE_REFERENCE_CAPPED = "reference-capped"
MODES = (MODE_OWNERSHIP, MODE_REFERENCE, MODE_REFERENCE_CAPPED)

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
    source modules and directly-changed test files. Never returns an empty list
    (smoke floor), assuming at least one smoke basename exists on disk.

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
    if mode != MODE_OWNERSHIP:
        ref_index = _build_reference_index(plugin_root, source_stems)

    selected: set[str] = set(_smoke_set(plugin_root))

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
        # (1) a changed top-level source module -> its owned tests.
        if rp.parent.as_posix() in _SOURCE_DIRS and not rp.name.startswith("test_"):
            selected |= index.get(rp.stem, set())
            # (4, opt-in) every test file that NAMES the changed module.
            if mode != MODE_OWNERSHIP:
                refs = ref_index.get(rp.stem, set())
                if mode == MODE_REFERENCE or len(refs) <= ref_max_tests:
                    selected |= refs

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
