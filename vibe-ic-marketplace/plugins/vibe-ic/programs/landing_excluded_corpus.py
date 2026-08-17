#!/usr/bin/env python3
"""landing_excluded_corpus.py — what the LANDING GATE deliberately does not run,
declared one test node at a time, with the reason and the owning artefact named.

rc: 0 = the declaration is current / 1 = an --audit finding / 2 = REFUSED (the
declaration could not be read, or it is empty). rc=2 is never a pass: "there was
nothing to exclude" and "I could not look" must not reach a reader as the same
sentence.

THE TWO QUESTIONS, AND WHY THEY MUST NOT SHARE A TIER
=====================================================
Owner directive, 2026-08-17:

  * THE 63x9 FLOW GATES fire when the flow runs. A Phase 1/2/3 run executes each
    step and that step's own gate. They already have an execution path and they
    are not this program's business.
  * THE LANDING GATE is REGRESSION for changes entering main. Its only job is to
    answer "does this change break something that used to work".

A third thing had grown inside the landing gate and is neither: a MATRIX
SELF-AUDIT — "is the published headline figure in `matrix_63x8/README.md` still
consistent with what the live suite counts". That audits a PUBLISHED ARTEFACT. A
stale published figure breaks nothing; it makes one number out of date, which
blocks the campaign, not the push. `tools/ci/repo_hygiene_gates.sh` already made
that separation for its own `63x8 census fresh` line (owner decision 2026-08-16,
the comment block at that file's ~line 1270). This program makes it for the two
PYTEST arms, which is where the rest of the material was.

WHY A NODE REGISTRY AND NOT A GLOB
==================================
Every file named below is MIXED. Not one of them is wholly a self-audit, and
three of them carry the cheapest genuine regressions in the repo — a
`--check` that can still go red, a cascade that is driven rather than declared,
a waiver registry whose citations must still resolve. Dropping a FILE would take
those with it, and the rule this repo pays for repeatedly is that a check which
cannot fail is worse than no check.

So the unit of exclusion is the pytest NODE, the mechanism is one marker, and
the marker is not the record — this file is. A marker alone answers "is this
deselected"; it cannot answer "why, and who runs it now". `--audit` holds the
two in step IN BOTH DIRECTIONS:

  * every node declared here must exist and must carry the marker  (no stale
    declaration quietly excluding nothing);
  * every node in the tree carrying the marker must be declared here  (no
    silent addition — a marker typed onto a regression test would otherwise
    remove it from every landing and say nothing).

The second direction is the one that matters. A silent glob exclusion is how a
gate goes missing for months, and this repo has paid for that shape more than
once.

WHAT THIS IS NOT
================
It is NOT a deletion. Every node below still exists, still collects, and still
runs — under `tools/run_campaign_tier.sh`, which selects exactly the marker this
file declares. NOTHING SCHEDULES THAT ENTRY POINT YET. That is stated here
rather than implied, because the enforcement question for the published census
is an OPEN OWNER DECISION (see `tools/run_campaign_tier.sh`), and a program that
quietly implied an answer would be the third time this figure went stale with
nothing noticing.

WHAT IS DELIBERATELY *NOT* HERE
===============================
`test_matrix_d1..d8` (the eight dimension modules), `tools/test_d9_content_census.py`
and `tools/test_d9_corpus_baseline.py` are NOT declared out, and the omission is
a decision rather than an oversight:

  * d1/d2/d5 were examined and cleared as landing regressions — d1 reddens when a
    gate names a program that no longer resolves, d2 when a gate loses its
    reachable non-zero-exit branch, d5 when a `blocks_on` edge breaks.
  * d3/d4/d6/d7/d8 were classified as OWNER DECISION, not as "not a regression".
    Moving them on that basis would be inventing the answer this task was told
    not to invent. They are listed in `tools/run_campaign_tier.sh`'s header as
    the open set.
  * the two `tools/test_d9_*` instrument tests are real unit regressions over
    instruments that live in THIS repo, and they cost 1.1 s and 20 s. Their
    subject is campaign equipment, which is a layering argument, not a
    regression argument.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic_artefact import write_text as atomic_write_text  # noqa: E402

#: THE ONE MARKER. Spelled once; the shell arms ask for it with `--marker-expr`
#: and `--select-expr` rather than repeating the string, so a rename cannot
#: leave one arm deselecting nothing while still printing PASS.
MARKER = "campaign_tier"

#: pytest's own default collection patterns, spelled once. A second definition
#: of "is a test file" drifts, and it drifts towards a file nobody runs.
_TEST_BASENAME = re.compile(r"^(test_.*\.py|.*_test\.py)$")

_ENTRY_POINT = "tools/run_campaign_tier.sh"

#: The trees whose landing arm actually passes `-m`. `run_unselectable_pytest`
#: does not, so a marker under `skills/`, `mcp-eda/` or `_shared/` would be
#: inert; `audit()` refuses a declaration there rather than letting one sit
#: looking effective.
_MARKER_HONOURED = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/",
    "tools/",
)


@dataclass(frozen=True)
class ExcludedNode:
    """One pytest node the landing gate deliberately does not run.

    `node` is `test_name` for a module-level function or `Class::test_name` for
    a method — the same spelling pytest uses, minus the file, which `path`
    already carries.

    `subject` is the ARTEFACT the node audits. It is the field that makes this a
    layering record rather than a speed record: if the subject is a published
    page or a corpus, the node answers a campaign question; if the subject is
    this repository's source, it does not belong here at all.
    """

    path: str        # repo-relative test file
    node: str        # "test_x" or "Class::test_x"
    category: str    # the classification this exclusion rests on
    subject: str     # the published artefact it audits
    owner: str       # what runs it now
    why: str


_CENSUS_README = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/matrix_63x8/README.md")
_D9_REALITY = "benchmark-data/evaluation/d9_flow_gate_reality/d9_reality.json"

_MATRIX = "matrix-self-audit"

_CENSUS_FRESHNESS = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
    "test_matrix_63x8_census_freshness.py")
_FIGURE_COVERAGE = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
    "test_matrix_63x8_figure_coverage.py")
_COVERAGE = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
    "test_matrix_63x8_coverage.py")
_D9_REALITY_TESTS = "tools/test_d9_flow_gate_reality.py"


#: THE REGISTRY. Ordered by file, then by the order the nodes appear in it.
_EXCLUDED: Tuple[ExcludedNode, ...] = (
    # ── the published census block in matrix_63x8/README.md ──────────────
    #
    # The file's own docstring names its subject: "The published 63x8 census
    # must reproduce". Its sixth test — `test_the_generator_cli_can_go_red_and_green`
    # — is NOT here: it drives the real CLI over a SYNTHETIC census injected
    # through sys.modules and proves `--check` can still return 1. That is a
    # can-it-still-fail control on `tools/gen_matrix_63x8_census.py` and it
    # stays in the landing gate, where it costs 1.9 s.
    ExcludedNode(
        path=_CENSUS_FRESHNESS,
        node="test_the_census_block_is_present_and_marked_generated",
        category=_MATRIX,
        subject=_CENSUS_README,
        owner=_ENTRY_POINT,
        why="asserts the published README carries the generated-census markers "
            "and the DO NOT EDIT BY HAND notice. A published document losing "
            "its markers is a campaign defect; it breaks no code a landing "
            "changes.",
    ),
    ExcludedNode(
        path=_CENSUS_FRESHNESS,
        node="test_the_census_block_is_fresh",
        category=_MATRIX,
        subject=_CENSUS_README,
        owner=_ENTRY_POINT,
        why="re-derives the published block by running all 504 cells through "
            "the eight dimension modules. THE single most expensive item that "
            "was in the landing path (measured 129.3 s standalone, 170.9 s "
            "inside a four-file session). Its question is 'is the published "
            "figure still true', which is the campaign's question.",
    ),
    ExcludedNode(
        path=_CENSUS_FRESHNESS,
        node="test_the_published_total_equals_the_live_census",
        category=_MATRIX,
        subject=_CENSUS_README,
        owner=_ENTRY_POINT,
        why="recomputes the six published columns independently of the "
            "generator and demands they partition to 504. RED at origin/main "
            "f6b0e77dd ('the published columns account for 451 cells but the "
            "matrix has 504'): a real finding ABOUT THE PUBLISHED PAGE that no "
            "PR caused and no PR can clear.",
    ),
    ExcludedNode(
        path=_CENSUS_FRESHNESS,
        node="test_no_substituted_cell_is_inside_a_figure_presented_as_enforcement",
        category=_MATRIX,
        subject=_CENSUS_README,
        owner=_ENTRY_POINT,
        why="grades how the published table PRESENTS its columns — that "
            "own+substituted may not appear as one bold figure. A presentation "
            "rule over a document, not a property of the code.",
    ),
    ExcludedNode(
        path=_CENSUS_FRESHNESS,
        node="test_every_substitution_disclosure_says_what_was_substituted",
        category=_MATRIX,
        subject=_CENSUS_README,
        owner=_ENTRY_POINT,
        why="grades each published disclosure STRING in the README. Same "
            "subject, same tier as the four above.",
    ),

    # ── the anchored figures in the 63x8 prose corpus ─────────────────────
    #
    # Nine of this file's twelve tests build a one-document corpus in tmp_path
    # and drive the real generator CLI in both directions plus its refusals.
    # Those are fixture-driven generator regressions and they STAY. The three
    # below are the ones whose population is the COMMITTED corpus.
    ExcludedNode(
        path=_FIGURE_COVERAGE,
        node="test_every_anchored_figure_in_the_committed_corpus_is_fresh",
        category=_MATRIX,
        subject=_CENSUS_README + " (and the 33-file 63x8 prose corpus)",
        owner=_ENTRY_POINT,
        why="re-derives all 57 anchored figures in the real committed corpus. "
            "A stale anchored figure is a stale published number.",
    ),
    ExcludedNode(
        path=_FIGURE_COVERAGE,
        node="test_the_five_figures_the_issue_named_are_anchored_and_live",
        category=_MATRIX,
        subject=_CENSUS_README + " (and the 33-file 63x8 prose corpus)",
        owner=_ENTRY_POINT,
        why="asserts five named bindings are still ANCHORED somewhere in the "
            "published prose. It is a property of the prose, not of the tree.",
    ),
    ExcludedNode(
        path=_FIGURE_COVERAGE,
        node="test_the_generated_census_block_is_guarded_exactly_as_before",
        category=_MATRIX,
        subject=_CENSUS_README,
        owner=_ENTRY_POINT,
        why="opens the published README and asserts the two generators do not "
            "fight over the same bytes. A contract between two publishers of "
            "one page.",
    ),

    # ── the campaign's own coverage claim ─────────────────────────────────
    #
    # Roughly fifteen of this file's twenty-six tests are the harness's own
    # machinery under test (worker caps, wave boundaries, fail-closed on a
    # chatty import, a red non-cell helper, three synthetic dimension-99 cells)
    # plus structural regressions (eight modules own eight dimensions, every
    # cell collected exactly once by pytest in a subprocess, cell ids not
    # silently renamed). Those STAY. The four below are the campaign audit.
    #
    # NOTE the classification trap, recorded so nobody re-litigates it: this is
    # NOT category (i). The eight dimension modules audit the flow's gate
    # DECLARATIONS statically — d1 imports `flow_compliance_check._evaluate_gate`
    # and asks what the real executor WOULD dispatch. Running Phase 1/2/3
    # executes `cdc_crossing_check`; it does not execute d1/step3. "The flow
    # runs them" is true of the flow gates and is NOT true of this material.
    ExcludedNode(
        path=_COVERAGE,
        node="test_the_census_is_reported_for_humans",
        category=_MATRIX,
        subject=_CENSUS_README + " (the state-axis census it publishes)",
        owner=_ENTRY_POINT,
        why="emits the state-axis census via record_property so a reader gets "
            "the campaign's headline without reading the code. Reporting a "
            "published figure is the campaign's job.",
    ),
    ExcludedNode(
        path=_COVERAGE,
        node="test_every_cell_has_a_live_outcome_and_the_outcome_run_is_not_starved",
        category=_MATRIX,
        subject=_CENSUS_README + " (the 504-cell coverage claim)",
        owner=_ENTRY_POINT,
        why="RUNS all 504 cells of test_matrix_d1..d8 in nested pytest "
            "sessions (measured 126.9-128.2 s). Its subject is whether the "
            "campaign's coverage claim is starved — the campaign's own "
            "bookkeeping.",
    ),
    ExcludedNode(
        path=_COVERAGE,
        node="test_no_cell_is_counted_enforced_while_its_predicate_is_red",
        category=_MATRIX,
        subject=_CENSUS_README + " (the 504-cell coverage claim)",
        owner=_ENTRY_POINT,
        why="joins the 504-cell outcome run against the state census. RED at "
            "origin/main for a reason no PR caused: 53 cells skip on a host "
            "without the campaign run trees that left with benchmark-data, and "
            "the assertion's own text says 'a missing dependency or a "
            "collection error is a HOST problem, not a repo defect'. A landing "
            "gate must not carry a check that says that about itself.",
    ),
    ExcludedNode(
        path=_COVERAGE,
        node="test_the_enforcement_census_is_reported_for_humans",
        category=_MATRIX,
        subject=_CENSUS_README + " (the two-axis census it publishes)",
        owner=_ENTRY_POINT,
        why="emits the two-axis census via record_property. Same subject as "
            "its state-axis sibling, and it drives the same 504-cell run.",
    ),

    # ── the D9 flow-gate PAGE BLOCK, whose corpus has left this repo ──────
    #
    # Six of this file's fifteen tests are pure unit tests of
    # `d9.verdict_moved()` over synthetic (bucket, rc) pairs, plus
    # `test_the_certification_sentence_is_verbatim`, which reads one module
    # constant. Those STAY and they pass. The seven functions below (nine
    # collected tests) all open `benchmark-data/evaluation/d9_flow_gate_reality/
    # d9_reality.json` and grade the RENDERED PAGE BLOCK against it.
    #
    # THIS IS THE LIVE DEFECT, not a theoretical one. That corpus left the repo
    # in c5d7f2d00 ("chore: move published benchmark results to
    # vibeic/benchmark-data") and this file has not been touched since 111c74dde
    # (#1009). MEASURED on a clean detached origin/main worktree: 9 failed / 6
    # passed, every failure FileNotFoundError on that JSON — and ROUTE 2
    # discovers this file by an UNCONDITIONAL `find tools/`, so the whole arm is
    # rc=1 and `gatekeeper-land.sh` writes no stamp on any checkout that does
    # not happen to carry a leftover untracked benchmark-data/.
    ExcludedNode(
        path=_D9_REALITY_TESTS,
        node="TestZeroDenominatorRefusesRatherThanPasses::"
             "test_zero_denominator_steps_are_dark_with_that_cause",
        category=_MATRIX,
        subject=_D9_REALITY + " (now in vibeic/benchmark-data)",
        owner=_ENTRY_POINT,
        why="reads the published sweep report and asserts every "
            "zero-denominator row is drawn dark with that cause. The report is "
            "not in this repository.",
    ),
    ExcludedNode(
        path=_D9_REALITY_TESTS,
        node="TestZeroDenominatorRefusesRatherThanPasses::"
             "test_no_cell_claims_to_have_moved_on_more_runs_than_it_probed",
        category=_MATRIX,
        subject=_D9_REALITY + " (now in vibeic/benchmark-data)",
        owner=_ENTRY_POINT,
        why="an internal-consistency assertion over the published sweep "
            "report's rows. Same absent subject.",
    ),
    ExcludedNode(
        path=_D9_REALITY_TESTS,
        node="TestThePageMayNotSoftenTheSentence::"
             "test_the_rendered_block_carries_it_and_both_belief_lists",
        category=_MATRIX,
        subject=_D9_REALITY + " + the rendered flow-gate page block",
        owner=_ENTRY_POINT,
        why="renders the published page block from the published report. The "
            "page itself (`--page flow-gate.html`) is not in this repository "
            "either.",
    ),
    ExcludedNode(
        path=_D9_REALITY_TESTS,
        node="TestThePageMayNotSoftenTheSentence::"
             "test_every_dark_cell_is_rendered_as_dark_with_a_named_cause",
        category=_MATRIX,
        subject=_D9_REALITY + " + the rendered flow-gate page block",
        owner=_ENTRY_POINT,
        why="counts how many rows the published block draws dark and compares "
            "it with the published report. Grading a page.",
    ),
    ExcludedNode(
        path=_D9_REALITY_TESTS,
        node="TestThePageMayNotSoftenTheSentence::"
             "test_the_block_does_not_claim_d9_is_shipped",
        category=_MATRIX,
        subject=_D9_REALITY + " + the rendered flow-gate page block",
        owner=_ENTRY_POINT,
        why="asserts the published block still carries its PLANNED caveat. A "
            "property of published prose.",
    ),
    ExcludedNode(
        path=_D9_REALITY_TESTS,
        node="TestNoMeasuredNumberInTheBlockIsHandTyped::"
             "test_moving_the_measurement_moves_every_copy_in_the_block",
        category=_MATRIX,
        subject=_D9_REALITY + " + the rendered flow-gate page block",
        owner=_ENTRY_POINT,
        why="parametrized over three published fields; proves no measured "
            "number in the published block is hand-typed. Its input is the "
            "absent report.",
    ),
    ExcludedNode(
        path=_D9_REALITY_TESTS,
        node="TestDriftIsDetected::"
             "test_check_fails_when_the_page_block_no_longer_matches",
        category=_MATRIX,
        subject=_D9_REALITY + " + the rendered flow-gate page block",
        owner=_ENTRY_POINT,
        why="edits the published page to flatter the headline from 31 to 63 "
            "and requires `--check` to redden. A drift check on a published "
            "page, seeded from the absent report.",
    ),
)


def entries() -> Tuple[ExcludedNode, ...]:
    return _EXCLUDED


def paths() -> Tuple[str, ...]:
    seen: List[str] = []
    for e in _EXCLUDED:
        if e.path not in seen:
            seen.append(e.path)
    return tuple(seen)


def repo_root(start: Optional[Path] = None) -> Optional[Path]:
    """The enclosing git repository, or None (which callers turn into rc=2)."""
    here = (start or Path(__file__)).resolve()
    for anc in (here, *here.parents):
        if (anc / ".git").exists():
            return anc
    return None


# ── AST: does the node exist, and does it carry the marker ─────────────────
#
# Static, not a pytest collection. Collection of these files imports the matrix
# substrate and would make this gate cost seconds instead of milliseconds; more
# to the point, a gate that has to RUN the suite to say what the suite excludes
# is a gate the suite can influence.


def _is_marker(dec: ast.AST) -> bool:
    """`@pytest.mark.<MARKER>` — bare, never called."""
    return (isinstance(dec, ast.Attribute)
            and dec.attr == MARKER
            and isinstance(dec.value, ast.Attribute)
            and dec.value.attr == "mark")


def _parametrize_arity(dec: ast.AST) -> Optional[int]:
    """The number of cases `@pytest.mark.parametrize(...)` expands to, or None.

    Returns None when the argument list is not a literal this can count — an
    unknown arity is REPORTED by the caller as unknown rather than guessed at 1,
    because a guessed arity would make the ROUTE-2 deselect assertion lie.
    """
    if not isinstance(dec, ast.Call):
        return None
    fn = dec.func
    if not (isinstance(fn, ast.Attribute) and fn.attr == "parametrize"):
        return None
    if len(dec.args) < 2:
        return None
    try:
        values = ast.literal_eval(dec.args[1])
    except (ValueError, SyntaxError):
        return None
    try:
        return len(values)
    except TypeError:
        return None


@dataclass(frozen=True)
class Found:
    marked: bool
    #: How many pytest items this function expands to, or None if undecidable.
    items: Optional[int]


def _scan(text: str) -> Dict[str, Found]:
    """`{"test_x": Found, "Class::test_x": Found}` for one test module."""
    out: Dict[str, Found] = {}

    def visit(fn, prefix: str, class_decorators: Sequence[ast.AST]) -> None:
        marked = any(_is_marker(d) for d in fn.decorator_list) or any(
            _is_marker(d) for d in class_decorators)
        arity: Optional[int] = 1
        for d in list(fn.decorator_list) + list(class_decorators):
            n = _parametrize_arity(d)
            if n is None and isinstance(d, ast.Call) and isinstance(
                    d.func, ast.Attribute) and d.func.attr == "parametrize":
                arity = None
                break
            if n is not None and arity is not None:
                arity *= n
        out[prefix + fn.name] = Found(marked=marked, items=arity)

    tree = ast.parse(text)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                visit(node, "", ())
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        and sub.name.startswith("test"):
                    visit(sub, node.name + "::", node.decorator_list)
    return out


def tracked_test_files(repo: Path) -> Optional[List[str]]:
    """Every TRACKED file pytest would collect by name, repo-relative, sorted.

    Tracked rather than walked: an untracked scratch file in somebody's worktree
    must not be able to change what this program says a landing excludes.
    """
    try:
        out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"],
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    files = [p for p in out.stdout.split("\0") if p]
    if not files:
        return None
    return sorted(p for p in files if _TEST_BASENAME.match(os.path.basename(p)))


def audit(repo: Path) -> List[str]:
    """Findings that make this declaration untrustworthy. Empty == clean.

    BOTH DIRECTIONS, and the second is the load-bearing one:
      1. every DECLARED node exists and carries the marker;
      2. every MARKED node in the tracked tree is declared here.
    """
    findings: List[str] = []

    by_path: Dict[str, List[ExcludedNode]] = {}
    for e in _EXCLUDED:
        by_path.setdefault(e.path, []).append(e)
        # ONLY THE TWO ARMS THAT HONOUR THE MARKER MAY CARRY A DECLARATION.
        # `run_pytest` (the targeted arm) and `run_repo_tools_pytest` pass
        # `-m`; `run_unselectable_pytest` does not. A marker placed in a tree
        # nothing filters would be a declaration that reads as an exclusion and
        # excludes nothing — the exact shape the registry exists to refuse.
        if not any(e.path.startswith(p) for p in _MARKER_HONOURED):
            findings.append(
                f"{e.path}::{e.node} is declared under a tree no landing arm "
                f"filters with -m ({', '.join(_MARKER_HONOURED)}) — the marker "
                f"would be inert there and the exclusion would be a fiction.")
        for field, name in ((e.category, "category"), (e.subject, "subject"),
                            (e.owner, "owner"), (e.why, "why")):
            if not field.strip():
                findings.append(
                    f"{e.path}::{e.node} states no {name} — an exclusion whose "
                    f"reason is blank is a silent exclusion with extra steps.")

    scanned: Dict[str, Dict[str, Found]] = {}
    for rel, group in sorted(by_path.items()):
        p = repo / rel
        if not p.is_file():
            findings.append(
                f"declared exclusion names {rel!r}, which does not exist — a "
                f"declaration that excludes nothing is a stale roster.")
            continue
        try:
            found = _scan(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError as exc:
            findings.append(f"{rel} does not parse ({exc}); the declaration "
                            f"below it cannot be checked.")
            continue
        scanned[rel] = found
        for e in group:
            hit = found.get(e.node)
            if hit is None:
                findings.append(
                    f"{rel}::{e.node} is declared excluded but no such test "
                    f"node exists — it was renamed or deleted, and this "
                    f"declaration has been excluding nothing since.")
            elif not hit.marked:
                findings.append(
                    f"{rel}::{e.node} is declared excluded but carries no "
                    f"@pytest.mark.{MARKER} — the landing gate is RUNNING it "
                    f"while this file says it does not.")

    tracked = tracked_test_files(repo)
    if tracked is None:
        findings.append(
            "`git ls-files` did not answer, so the reverse direction — is any "
            "MARKED node undeclared — was not checked. That is the direction "
            "that hides a regression test somebody quietly took out.")
        return findings

    declared = {(e.path, e.node) for e in _EXCLUDED}
    for rel in tracked:
        p = repo / rel
        if not p.is_file():
            continue
        found = scanned.get(rel)
        if found is None:
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if f"mark.{MARKER}" not in text:      # cheap pre-filter
                continue
            try:
                found = _scan(text)
            except SyntaxError:
                continue
        for node, hit in sorted(found.items()):
            if hit.marked and (rel, node) not in declared:
                findings.append(
                    f"{rel}::{node} carries @pytest.mark.{MARKER} but is NOT "
                    f"declared here — a test removed from every landing with "
                    f"no reason, no subject and no owner on the record.")
    return findings


def expected_items(repo: Path, prefix: str) -> Tuple[Optional[int], List[str]]:
    """How many pytest ITEMS the declared exclusions under `prefix` expand to.

    Derived from the tree (parametrize arity is read, never typed), so the
    shell can assert that a run REALLY deselected them. `None` means at least
    one arity was undecidable, and the caller must then not assert a number —
    an assertion built on a guess is the shape this whole file exists against.

    A declared path that is ABSENT from `repo` is SKIPPED rather than refused,
    and the distinction matters. This is asked by a shell function that is
    generic over its root — `tools/ci/test_repo_tools_tests_gate.py` drives it
    against a throwaway repository holding one planted test, and a refusal
    there would break the control that proves the gate can still go red.
    Absence of a declared file in THE REPOSITORY is a real fault and it is
    caught by `audit()`, which is asked about the repository and nothing else.
    """
    total = 0
    notes: List[str] = []
    for rel in paths():
        if not rel.startswith(prefix):
            continue
        p = repo / rel
        if not p.is_file():
            notes.append(f"{rel} is not present in this tree -> 0")
            continue
        found = _scan(p.read_text(encoding="utf-8", errors="replace"))
        for e in _EXCLUDED:
            if e.path != rel:
                continue
            hit = found.get(e.node)
            if hit is None or hit.items is None:
                return None, [f"{rel}::{e.node} arity is undecidable"]
            total += hit.items
            notes.append(f"{rel}::{e.node} -> {hit.items}")
    return total, notes


def _list_lines() -> List[str]:
    lines = [
        "WHAT THE LANDING GATE DELIBERATELY DOES NOT RUN",
        f"marker: @pytest.mark.{MARKER}   (deselected with -m 'not {MARKER}')",
        f"runs instead under: {_ENTRY_POINT}   "
        f"(NOTHING SCHEDULES IT YET — owner decision, see that file)",
        "",
    ]
    for rel in paths():
        group = [e for e in _EXCLUDED if e.path == rel]
        lines.append(f"{rel}   [{len(group)} node(s)]")
        for e in group:
            lines.append(f"    {e.node}")
            lines.append(f"        category : {e.category}")
            lines.append(f"        subject  : {e.subject}")
            lines.append(f"        owner    : {e.owner}")
            lines.append(f"        why      : {e.why}")
        lines.append("")
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=None,
                    help="repository root (default: the one enclosing this file)")
    ap.add_argument("--list", action="store_true",
                    help="print every exclusion with its reason and owner (default)")
    ap.add_argument("--audit", action="store_true",
                    help="rc=1 on a stale declaration or an undeclared marker")
    ap.add_argument("--marker-expr", action="store_true",
                    help="print the -m expression a LANDING arm must pass")
    ap.add_argument("--select-expr", action="store_true",
                    help="print the -m expression the CAMPAIGN tier must pass")
    ap.add_argument("--paths", metavar="PREFIX", nargs="?", const="",
                    help="print the declared files under PREFIX, one per line")
    ap.add_argument("--brief", metavar="PREFIX", nargs="?", const="",
                    help="one line per excluded node under PREFIX, for a gate log")
    ap.add_argument("--expected-items", metavar="PREFIX",
                    help="print how many pytest items the declarations under "
                         "PREFIX expand to (rc=2 if undecidable)")
    ap.add_argument("--json", metavar="OUT", help="write the registry as JSON")
    args = ap.parse_args(list(argv) if argv is not None else None)

    # ZERO DENOMINATOR REFUSES. An empty registry is not "nothing is excluded";
    # it is a file somebody emptied, and every caller below would then print a
    # confident PASS over no items at all.
    if not _EXCLUDED:
        print("REFUSED: the exclusion registry is EMPTY. That is not 'the "
              "landing gate excludes nothing' — it is a registry that can no "
              "longer be checked in either direction.", file=sys.stderr)
        return 2

    if args.marker_expr:
        print(f"not {MARKER}")
        return 0
    if args.select_expr:
        print(MARKER)
        return 0

    repo = Path(args.repo).resolve() if args.repo else repo_root()
    if repo is None or not (repo / ".git").exists():
        print("REFUSED: no enclosing git repository, so neither direction of "
              "the declaration could be checked.", file=sys.stderr)
        return 2

    if args.paths is not None:
        for rel in paths():
            if rel.startswith(args.paths):
                print(rel)
        return 0

    if args.brief is not None:
        # One line per node, for a gate log. The full reason stays one command
        # away (`--list`) rather than being summarised into something a reader
        # could mistake for the whole record.
        shown = 0
        for e in _EXCLUDED:
            if not e.path.startswith(args.brief):
                continue
            shown += 1
            print(f"NOT RUN BY THE LANDING GATE  {e.path}::{e.node}")
            print(f"    [{e.category}] audits {e.subject}")
            print(f"    runs under {e.owner}")
        if not shown:
            print(f"REFUSED: no declared exclusion under {args.brief!r}; an "
                  f"empty list here would read as 'nothing is excluded'.",
                  file=sys.stderr)
            return 2
        print(f"({shown} node(s); `landing_excluded_corpus.py --list` states "
              f"the reason for each)")
        return 0

    if args.expected_items:
        total, notes = expected_items(repo, args.expected_items)
        if total is None:
            print("REFUSED: " + "; ".join(notes), file=sys.stderr)
            return 2
        print(total)
        return 0

    if args.json:
        atomic_write_text(
            Path(args.json),
            json.dumps({"marker": MARKER, "entry_point": _ENTRY_POINT,
                        "excluded": [vars(e) for e in _EXCLUDED]},
                       indent=2, sort_keys=True) + "\n",
            encoding="utf-8")

    findings = audit(repo)
    if args.audit:
        print(f"[landing_excluded_corpus] {len(_EXCLUDED)} declared exclusion(s) "
              f"across {len(paths())} file(s); reverse scan over "
              f"{len(tracked_test_files(repo) or [])} tracked test file(s).")
        for f in findings:
            print(f"  FINDING  {f}")
        if findings:
            print(f"[FAIL] the landing gate's declared exclusions and the tree "
                  f"disagree in {len(findings)} place(s).")
            return 1
        print("[PASS] every declared exclusion is marked and every marked node "
              "is declared.")
        return 0

    for line in _list_lines():
        print(line)
    for f in findings:
        print(f"  FINDING  {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
