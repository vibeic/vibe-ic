#!/usr/bin/env python3
"""gen_program_inventory.py — single source of truth for every stated count of
this plugin's `programs/` population.

WHY IT EXISTS
=============
The MCP tool count has a generator (`mcp-eda/tools/gen_mcp_tool_inventory.py`)
whose artefact says "Do NOT hand-edit; the website tool count must read `total`
from here", and a CI drift test behind it. The number is still correct: **56**.

The PROGRAM count had neither, and every stated program count in the repo was
hand-typed. Measured at 2026-08-19 on `2c15de257`:

    stated "917" in README.md x4 and plugins/vibe-ic/README.md x5
        -> correct when written at 73d1efb20 (2026-07-20); the tree had drifted
           by 261 files since, and nothing anywhere noticed.
    stated "888 catalogued"  x2   -> INDEX.md had long since said 1111.
    stated "3,737 programs"  x1   -> the recursive count was 3817.
    stated "1608 test files" x3   -> the tracked test corpus was 2609.
    stated "2,545 test files" x2  -> same population, a THIRD different number.

Two of those numbers described the SAME population and disagreed with each
other, which is the tell: nothing in the repo said what any of them counted.

THE AMBIGUITY IS THE ROOT CAUSE, NOT THE ARITHMETIC
===================================================
Several different true numbers can be quoted for "how many programs":

    1179  every `programs/*.py`, top level, helpers and shims included
    1112  the INDEX.md catalogue (helper and shim files excluded)
          NOTE the phrase this line does NOT spell out: `_is_helper`
          below classifies a file by a case-folded SUBSTRING search of
          its first 2000 chars, so a file that merely DESCRIBES that
          class of file removes itself from the catalogue. This file
          tripped exactly that on its first run — 1179 top level but
          1111 catalogued, one short. Do not reintroduce the literal
          phrase above this point in the file.
    3819  every `*.py` at any depth under `programs/`, tests included
    2610  the `programs/tests/**/test_*.py` corpus
     577  gate-shaped programs `*_{check,audit,lint}.py`
     544  gate-shaped programs `*_check.py` only

Every one of those is true. A bare "917" names none of them, so a reader cannot
tell a stale number from a different measurement, and neither can a reviewer.
That is exactly how the drift survived 261 files. Each population below
therefore carries an explicit `definition` string, and every stated count in
the bound documents is tied to a population KEY in `_CLAIMS` and verified by
`check_documents()` — a number in those files that is bound to no key is a
FAIL, not a shrug.

WHY THE ARTEFACT CARRIES DIGESTS AND NOT A LIST OF FILENAMES
============================================================
The first version of this file shipped `members`: the 1179 sorted filenames of
programs_top_level, so a drift message could name what changed. Measured
against the suite, that put the tree's unwired-disclosure test into the red —
the test that holds a program carrying a `NOT WIRED YET` docstring section to
really being called by nothing. Its message read: this program is now
referenced by `programs/PROGRAM_INVENTORY.json`, so it is wired, delete the
disclosure.

Nothing had been wired. A program that runs nowhere had merely had its NAME
written into a data file, and a detector that measures wiring by searching for
the name read that as a call — the exact defect `gate_is_wired_check.py` was
built around ("A NAME IS NOT A CALL"), arriving from a new direction. `INDEX.md`
already pays this cost and is special-cased by name in that test.

The fix is not a second special case. A shipped list of every program name
makes EVERY name-searching wiring detector read as satisfied — the ones in the
tree today, which cannot all be enumerated, and the ones written next year,
which certainly cannot. So the list is not shipped at all: `count` is the
contract and `sha256_of_sorted_paths` detects any add, removal or rename
exactly. What is lost is one line of convenience in a failure message; what is
kept is that this artefact cannot make an unwired gate look wired.

This docstring does not spell the affected program's name for the same reason:
writing it here would re-create the defect in prose. The test that guards this
asserts over EVERY top-level program stem, not the one that happened to go red.

READ THE NUMBER FROM THE ARTEFACT, DO NOT HAND-TYPE IT
======================================================
`PROGRAM_INVENTORY.json` is the artefact. Any README, website page, slide or
report that states a program count must read `populations.<key>.count` from it.
A hand-typed count is a defect this gate exists to fail on, whether or not it
happens to be right on the day it is typed.

THE DEFAULT RUN CLOSES THE ROUND TRIP (vibe-ic v1.13.3 follow-up)
=================================================================
It did not, and that is what made this gate recur. The default run wrote the
artefact; `--check` bound the artefact AND the prose that quotes it; so there
was NO invocation of this program that could satisfy the check it ships with,
and the only way to clear a drift was to hand-edit six README lines — the
practice three paragraphs above call the defect.

The tell that this was structural and not an oversight: TWO places in the tree
had already measured it and routed around it rather than closing it. `main()`
carried "which a regeneration cannot fix", and
`generated_artifact_conflict_resolve.REGISTRY` carried "Measured: with the JSON
freshly regenerated, --check was still red on five README lines". It was five
then and six on 6c798ce4be. An open round trip does not hold still: every claim
the tree grows past adds a site.

So the default run now writes BOTH, driven by the SAME `_CLAIMS` table that
checks them — see `apply_documents`. `--artifact-only` opts out for the one
caller whose contract is a single registered path.

Usage:
  python3 programs/gen_program_inventory.py            # regenerate artefact
                                                       # AND rewrite the stated
                                                       # counts that quote it
  python3 programs/gen_program_inventory.py --artifact-only
                                                       # the artefact alone
  python3 programs/gen_program_inventory.py --check    # verify committed == tree
                                                       # AND stated docs == tree

exit 0 = PASS         committed inventory matches the tree, and every stated
                      count in the bound documents matches its population
exit 1 = FAIL         the committed inventory is stale, a stated count drifted,
                      a bound claim site has vanished, or a document states an
                      unregistered count
exit 2 = NOT CHECKED  the programs directory or a bound document is unreadable
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent
PLUGIN = PROGRAMS.parent                       # plugins/vibe-ic/
MARKETPLACE = PLUGIN.parent.parent             # vibe-ic-marketplace/
OUT = PROGRAMS / "PROGRAM_INVENTORY.json"
INDEX_MD = PROGRAMS / "INDEX.md"

SCHEMA_VERSION = 1


# ─── the helper / shim predicate ────────────────────────────────────
# Kept byte-identical in EFFECT to tools/gen_programs_index.py::_is_helper.
# That generator is repo-root-only and is NOT shipped in the flattened plugin
# cache, so it cannot be imported from here; the two are held together instead
# by `programs_catalogued` being cross-checked against INDEX.md's own stated
# total on every run. A divergence fails rather than going quiet.
def _is_helper(path: Path) -> bool:
    name = path.name
    if name.startswith("_"):
        return True
    if name.startswith("DEPRECATED_") or name.endswith("_shim.py"):
        return True
    try:
        head = path.read_text(errors="replace")[:2000]
    except OSError:
        return False
    return "DEPRECATION SHIM" in head.upper()


def _tracked_under_plugin() -> list[str] | None:
    """Plugin-relative posix paths of every TRACKED file, or None if git cannot
    answer (no repo, no git binary, timeout).

    WHY TRACKED AND NOT THE WORKING TREE (measured 2026-08-19)
    ---------------------------------------------------------
    The first version globbed the working tree, matching
    `tools/gen_programs_index.py`. Run inside the plugin's own pytest session it
    then read 1180 top-level programs where the tree ships 1179: another test
    writes a probe module into the REAL `programs/` directory and deletes it a
    moment later, and this gate happened to look while it was there. Two runs
    forty seconds apart disagreed, with nothing committed in between.

    A gate that flaps does not report "unknown" — it reports a confident wrong
    number, and here it would have demanded a regeneration that itself could not
    be reproduced. The tracked set is also the RIGHT population on the merits: a
    README states what the repo SHIPS, and a scratch file a test wrote sixty
    milliseconds ago is not that.
    """
    try:
        r = subprocess.run(["git", "-C", str(PLUGIN), "ls-files", "-z", "--", "."],
                           capture_output=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    return [x.decode("utf-8", "replace") for x in r.stdout.split(b"\0") if x]


def _digest(rels: list[str]) -> str:
    return hashlib.sha256("\n".join(rels).encode()).hexdigest()


def _rel(paths) -> list[str]:
    return sorted(p.relative_to(PLUGIN).as_posix() for p in paths)


# ─── populations ────────────────────────────────────────────────────
def discover() -> dict:
    """Enumerate every population a document is allowed to state a count for.

    Enumeration is from the TRACKED set (`git ls-files`) — see
    `_tracked_under_plugin` for the measurement that forced it. When git cannot
    answer, the working tree is used instead and `enumerated_from` says so; a
    --check whose committed artefact was built from the OTHER source refuses to
    render a drift verdict rather than comparing two different populations.
    """
    tracked = _tracked_under_plugin()
    if tracked is not None:
        source = "git-tracked"
        rels = [r for r in tracked if r.endswith(".py")]
        top = [PLUGIN / r for r in rels
               if r.startswith("programs/") and r.count("/") == 1]
        tree_all = [PLUGIN / r for r in rels if r.startswith("programs/")]
        tests = [PLUGIN / r for r in rels
                 if r.startswith("programs/tests/")
                 and r.rsplit("/", 1)[1].startswith("test_")]
        mcp_tests = [PLUGIN / r for r in rels
                     if r.startswith("mcp-eda/test/") and r.count("/") == 2
                     and r.rsplit("/", 1)[1].startswith("test_")]
        skill_tests = [PLUGIN / r for r in rels
                       if r.startswith("skills/") and r.count("/") == 3
                       and r.split("/")[2] == "tests"
                       and r.rsplit("/", 1)[1].startswith("test_")]
    else:
        source = "working-tree"
        top = list(PROGRAMS.glob("*.py"))
        tree_all = list(PROGRAMS.rglob("*.py"))
        tests = list((PROGRAMS / "tests").rglob("test_*.py"))
        mcp_tests = list((PLUGIN / "mcp-eda" / "test").glob("test_*.py"))
        skill_tests = list((PLUGIN / "skills").glob("*/tests/test_*.py"))

    catalogued = [p for p in top if not _is_helper(p)]
    check_only = [p for p in top if p.name.endswith("_check.py")]
    gates = [p for p in top
             if p.name.endswith(("_check.py", "_audit.py", "_lint.py"))]

    def pop(key: str, definition: str, paths) -> dict:
        rels = _rel(paths)
        return {"definition": definition,
                "count": len(rels),
                "sha256_of_sorted_paths": _digest(rels)}

    populations = {
        "programs_top_level": pop(
            "programs_top_level",
            "Every *.py directly in plugins/vibe-ic/programs/ (top level, NOT "
            "recursive). Helpers (_*.py), DEPRECATED_* and *_shim.py ARE "
            "included. This is the population the shell glob `programs/*.py` "
            "expands to. NOTE: the git pathspec `programs/*.py` is NOT the "
            "same thing — git's `*` crosses `/`, so `git ls-files "
            "'programs/*.py'` returns the RECURSIVE population instead.",
            top),
        "programs_catalogued": pop(
            "programs_catalogued",
            "programs_top_level minus helpers and deprecation shims (_*.py, "
            "DEPRECATED_*, *_shim.py, and any file whose first 2000 chars "
            "contain 'DEPRECATION SHIM'). This is the population catalogued in "
            "programs/INDEX.md by tools/gen_programs_index.py.",
            catalogued),
        "programs_tree_all_py": pop(
            "programs_tree_all_py",
            "Every *.py at ANY depth under plugins/vibe-ic/programs/, "
            "including programs/tests/ and the sub-packages. Roughly "
            "programs_top_level + test_files + sub-package modules.",
            tree_all),
        "test_files": pop(
            "test_files",
            "Every test_*.py at any depth under plugins/vibe-ic/programs/tests/.",
            tests),
        "mcp_eda_test_files": pop(
            "mcp_eda_test_files",
            "Every test_*.py directly under plugins/vibe-ic/mcp-eda/test/.",
            mcp_tests),
        "programs_helpers_and_shims": pop(
            "programs_helpers_and_shims",
            "programs_top_level minus programs_catalogued: the helper modules "
            "and deprecation shims that INDEX.md deliberately omits. Stated in "
            "the plugin README so the gap between the two program counts is "
            "accounted for rather than left as an unexplained discrepancy.",
            [p for p in top if _is_helper(p)]),
        "skill_compliance_test_files": pop(
            "skill_compliance_test_files",
            "Every test_*.py under plugins/vibe-ic/skills/*/tests/ — the "
            "per-skill compliance regressions. A DIFFERENT corpus from "
            "test_files, which is programs/tests/ only.",
            skill_tests),
        "gate_programs_check_suffix": pop(
            "gate_programs_check_suffix",
            "Top-level programs whose filename ends in _check.py. A SUBSET of "
            "gate_programs_check_audit_lint — quoting one where the other is "
            "meant is a different measurement, not a correction.",
            check_only),
        "gate_programs_check_audit_lint": pop(
            "gate_programs_check_audit_lint",
            "Top-level programs whose filename ends in _check.py, _audit.py or "
            "_lint.py.",
            gates),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "enumerated_from": source,
        "_comment": "AUTHORITATIVE inventory of this plugin's programs/ "
                    "populations — generated from the tree by "
                    "programs/gen_program_inventory.py. Do NOT hand-edit; any "
                    "stated program count (README, website, slides, reports) "
                    "must read populations.<key>.count from here rather than "
                    "being typed by hand. Every key carries a `definition` "
                    "because several of these counts are simultaneously true "
                    "and measure different things.",
        "populations": populations,
    }


# ─── stated counts in the documents ─────────────────────────────────
#: (document, population key, regex). The regex MUST have exactly one capture
#: group, holding the stated number. Each entry is REQUIRED to match at least
#: once: a claim site that has been reworded away is reported as a FAIL, never
#: as a silent pass, because a claim nothing can find reads exactly like a
#: claim that is correct.
_CLAIMS: tuple[tuple[str, str, str], ...] = (
    ("README.md", "programs_top_level",
     r"\| Deterministic programs \| \*\*([\d,]+)\*\*"),
    ("README.md", "programs_top_level",
     r"runners → ([\d,]+) top-level programs"),
    ("README.md", "programs_top_level",
     r"the ([\d,]+) top-level programs, and all"),
    ("README.md", "programs_top_level",
     r"## Deterministic programs \(([\d,]+) top level\)"),
    ("README.md", "programs_catalogued",
     r"of which \*\*([\d,]+)\*\* are catalogued in"),
    ("README.md", "test_files",
     r"\| Test files \| \*\*([\d,]+)\*\*"),
    ("README.md", "mcp_eda_test_files",
     r"\+ \*\*([\d,]+)\*\* under `plugins/vibe-ic/mcp-eda/test/`"),
    ("README.md", "programs_tree_all_py",
     r"← ([\d,]+) \*\.py at any depth"),
    # SAME LINE as the claim above, second number. It was unbound and drifted
    # 1260 -> 1298 over six days: no population word falls inside `_sweep`'s
    # 34-char window either side of it ("top level)" ahead, "*.py at any depth ("
    # behind), so neither _CLAIMS nor the unregistered-claim sweep could see it.
    ("README.md", "programs_top_level",
     r"\*\.py at any depth \(([\d,]+) top level\)"),
    ("README.md", "test_files",
     r"← ([\d,]+) test files"),
    ("plugins/vibe-ic/README.md", "programs_top_level",
     r"It is \*\*([\d,]+) top-level Python\nprograms\*\*"),
    ("plugins/vibe-ic/README.md", "programs_catalogued",
     r"\(([\d,]+) of them catalogued in"),
    ("plugins/vibe-ic/README.md", "test_files",
     r"\*\*([\d,]+) test files\*\*\. Programs decide"),
    ("plugins/vibe-ic/README.md", "programs_top_level",
     r"\*\*([\d,]+) top-level deterministic programs\*\* verify"),
    ("plugins/vibe-ic/README.md", "programs_top_level",
     r"At ([\d,]+) top-level programs, a hand-maintained"),
    ("plugins/vibe-ic/README.md", "programs_top_level",
     r"— ([\d,]+) top-level \*\.py"),
    ("plugins/vibe-ic/README.md", "programs_catalogued",
     r"top-level \*\.py \(([\d,]+) catalogued\)"),
    ("plugins/vibe-ic/README.md", "test_files",
     r"— ([\d,]+) test files"),
    ("plugins/vibe-ic/README.md", "test_files",
     r"\*\*([\d,]+) test files\*\* under `programs/tests/`"),
    ("plugins/vibe-ic/README.md", "programs_helpers_and_shims",
     r"the other\n([\d,]+) are helper modules and shims"),
    ("plugins/vibe-ic/README.md", "skill_compliance_test_files",
     r"plus \*\*([\d,]+)\*\* per-skill compliance regressions"),
    ("plugins/vibe-ic/README.md", "skill_compliance_test_files",
     r"— ([\d,]+) per-skill compliance regression files"),
    ("plugins/vibe-ic/README.md", "programs_top_level",
     r"moved from 41 at v0\.40 to ([\d,]+) top-level programs today"),
)

#: Numbers in the bound documents that sit next to a population word but are
#: NOT counts of a programs/ population. Each entry is a literal snippet that
#: must STILL BE PRESENT: if the surrounding text is reworded the entry stops
#: matching and the gate fails, so this list cannot rot into a blanket waiver.
#: It is deliberately not an "ignore these numbers" list — it is an assertion
#: about six specific sentences.
_NOT_A_POPULATION_COUNT: tuple[tuple[str, str, str], ...] = (
    ("README.md",
     "**60 of the 63 flow steps are gated by a program",
     "63 counts FLOW STEPS, not programs. The flow step count is owned by "
     "flow/phase1_phase2_phase3.yaml and flow_compliance_check.py."),
    ("plugins/vibe-ic/README.md",
     "**60 skills** that back the programs up",
     "60 counts SKILLS, not programs, so this gate does not own it — but it "
     "is STALE: skills/*/SKILL.md measured 63 on 2026-08-19. Left "
     "unchanged here deliberately rather than silently corrected, "
     "because a skills inventory is a separate population that needs "
     "its own generator; recorded so it is not mistaken for verified."),
    ("plugins/vibe-ic/README.md",
     "**9 agents**, and",
     "9 counts AGENTS, not programs. Out of this gate's scope."),
    ("plugins/vibe-ic/README.md",
     "pytest -q --maxfail=10",
     "10 is a pytest flag value, not a count of anything."),
    ("README.md",
     "and all 56 EDA/device tools",
     "56 counts MCP-EDA TOOLS, not programs. That count already has its own "
     "generator and drift gate (mcp-eda/tools/gen_mcp_tool_inventory.py + "
     "mcp-eda/test/test_mcp_tool_inventory_no_drift.py) and is measured "
     "correct; it is not this gate's population."),
    ("plugins/vibe-ic/README.md",
     "moved from 41 at v0.40 to",
     "41 is a HISTORICAL program count at v0.40, deliberately frozen: it is "
     "the start of a growth sentence, not a claim about the tree today. The "
     "endpoint of that same sentence IS bound, to programs_top_level."),
)

#: A number token adjacent to one of these words is a candidate count claim.
#: MEASURED: the first version of this list held only `programs?|test files?`,
#: and a stale "62 per-skill compliance regression files" in a tree diagram sat
#: three characters outside it — the sweep read the document as fully covered.
#: A population word this gate does not know is a claim it silently exempts, so
#: the list is deliberately wider than the claims currently bound to it.
_POPULATION_WORD = (r"(?:programs?|test files?|regression files?|"
                    r"compliance regressions|\.py files?)")
#: Plain integer or thousands-grouped integer. `{1,2,3,4}` brace expansions in
#: paths like `stage{1,2,3,4}_compliance.py` are rejected by the trailing
#: lookahead, which forbids a comma that is not a thousands separator.
_NUMBER = r"(?<![\w.,])(\d+(?:,\d{3})*)(?![\d.,])"
_WINDOW = 34


def _sweep(text: str) -> list[tuple[int, int, str]]:
    """(start, end, number) for every number adjacent to a population word.

    Adjacency is checked in BOTH directions — `917 programs` and
    `## Deterministic programs (917)` are both claims, and looking only
    forward silently misses every heading-shaped one.
    """
    hits = []
    for m in re.finditer(_NUMBER, text):
        ahead = text[m.end():m.end() + _WINDOW]
        behind = text[max(0, m.start() - _WINDOW):m.start()]
        if "|" in ahead:
            ahead = ahead.split("|")[0]
        if "|" in behind:
            behind = behind.rsplit("|", 1)[1]
        if (re.search(r"\b" + _POPULATION_WORD + r"\b", ahead, re.I)
                or re.search(r"\b" + _POPULATION_WORD + r"\b", behind, re.I)):
            hits.append((m.start(), m.end(), m.group(1)))
    return hits


def _read_doc(rel: str) -> str:
    p = MARKETPLACE / rel
    return p.read_text()


def check_documents(inv: dict) -> list[str]:
    """Return a list of failure lines; empty means every stated count agrees."""
    fails: list[str] = []
    pops = inv["populations"]
    docs = sorted({rel for rel, _, _ in _CLAIMS}
                  | {rel for rel, _, _ in _NOT_A_POPULATION_COUNT})
    texts = {rel: _read_doc(rel) for rel in docs}

    covered: dict[str, list[tuple[int, int]]] = {rel: [] for rel in docs}

    for rel, key, pattern in _CLAIMS:
        if key not in pops:
            fails.append(f"{rel}: claim bound to unknown population {key!r}")
            continue
        want = pops[key]["count"]
        found = list(re.finditer(pattern, texts[rel]))
        if not found:
            fails.append(
                f"{rel}: claim site for {key} has VANISHED — no match for "
                f"/{pattern}/. A reworded claim is unchecked, not correct; "
                f"restore the wording or update _CLAIMS.")
            continue
        for m in found:
            covered[rel].append((m.start(1), m.end(1)))
            got = int(m.group(1).replace(",", ""))
            if got != want:
                line = texts[rel][:m.start(1)].count("\n") + 1
                fails.append(
                    f"{rel}:{line}: states {m.group(1)} for {key}, tree has "
                    f"{want} (counts: {pops[key]['definition'][:72]}...). "
                    f"Run `python3 programs/gen_program_inventory.py`: it "
                    f"rewrites this number from populations.{key}.count. Do "
                    f"not hand-type it.")

    for rel, snippet, _reason in _NOT_A_POPULATION_COUNT:
        idx = texts[rel].find(snippet)
        if idx < 0:
            fails.append(
                f"{rel}: declared not-a-count sentence {snippet!r} is no longer "
                f"present. Re-check whether the number it held is now a real "
                f"claim, then update _NOT_A_POPULATION_COUNT.")
            continue
        covered[rel].append((idx, idx + len(snippet)))

    for rel in docs:
        for start, end, num in _sweep(texts[rel]):
            if any(s <= start and end <= e for s, e in covered[rel]):
                continue
            line = texts[rel][:start].count("\n") + 1
            fails.append(
                f"{rel}:{line}: UNREGISTERED count claim {num!r} next to a "
                f"population word. Every stated programs/ count must be bound "
                f"to a population key in _CLAIMS (or declared in "
                f"_NOT_A_POPULATION_COUNT with a reason). "
                f"Populations: {', '.join(sorted(pops))}.")
    return fails


def _format_like(sample: str, value: int) -> str:
    """`value` spelled the way `sample` was: grouped iff `sample` was grouped.

    The two READMEs mix `2925` and `2,545` for numbers of the same size, and
    both are correct today because `check_documents` strips the separator
    before comparing. A writer that imposed one style would rewrite lines it
    did not need to touch, so the diff of a count change would no longer be the
    count change.
    """
    return f"{value:,}" if "," in sample else str(value)


def apply_documents(inv: dict) -> tuple[list[str], list[str]]:
    """Rewrite every bound stated count in the bound documents IN PLACE.

    Returns ``(edits, unfixable)``. ``edits`` is one line per number actually
    changed; ``unfixable`` is every failure `check_documents` reports that
    substituting a number cannot close -- a claim site reworded away, a claim
    bound to an unknown population, or a new count claim bound to nothing.

    WHY THIS EXISTS: THE ROUND TRIP WAS OPEN
    ========================================
    Until this function, the generator wrote PROGRAM_INVENTORY.json and nothing
    else, while `--check` bound BOTH that artefact and the prose counts in the
    two READMEs. So `--check` asked a question that no run of this program
    could answer yes to, and the drift it reported could only be cleared by
    hand-editing prose -- which is the very thing the module docstring calls a
    defect ("READ THE NUMBER FROM THE ARTEFACT, DO NOT HAND-TYPE IT").

    MEASURED on 6c798ce4be (v1.13.3), on a clean clone: the tree had grown by
    three test files and three `*.py`, `--check` was red on SIX prose sites in
    two READMEs, and a full regeneration moved NONE of them. Two places in this
    repository had already written the gap down and worked around it rather
    than closing it -- `main()` below ("which a regeneration cannot fix") and
    `generated_artifact_conflict_resolve.REGISTRY` ("Measured: with the JSON
    freshly regenerated, --check was still red on five README lines"). FIVE
    when that was written, SIX now: an open round trip does not stay the same
    size, it accumulates one site per claim the tree grows past.

    The substitution is driven by `_CLAIMS` -- the SAME table `check_documents`
    reads -- so the writer cannot drift from the checker: a site the checker
    binds is a site the writer fixes, and a site bound to nothing is fixed by
    neither. That is the point. A second, independent list of "where the
    numbers live" would be one more place to state the same fact, which is the
    defect this whole file was written about.
    """
    pops = inv["populations"]
    edits: list[str] = []
    unfixable: list[str] = []
    docs = sorted({rel for rel, _, _ in _CLAIMS})

    for rel in docs:
        path = MARKETPLACE / rel
        text = path.read_text()
        # (start, end, replacement) for every site whose number is wrong.
        # Collected first and applied from the END backwards, so an earlier
        # span's offsets are still valid after a later span is resized.
        spans: list[tuple[int, int, str, str, str]] = []
        for claim_rel, key, pattern in _CLAIMS:
            if claim_rel != rel:
                continue
            if key not in pops:
                unfixable.append(f"{rel}: claim bound to unknown population "
                                 f"{key!r} — no number can be written for a "
                                 f"population that does not exist.")
                continue
            want = pops[key]["count"]
            found = list(re.finditer(pattern, text))
            if not found:
                unfixable.append(
                    f"{rel}: claim site for {key} has VANISHED — no match for "
                    f"/{pattern}/. A reworded claim is unchecked, not correct, "
                    f"and no substitution can restore a sentence that is gone: "
                    f"restore the wording or update _CLAIMS.")
                continue
            for m in found:
                got = m.group(1)
                if int(got.replace(",", "")) == want:
                    continue
                spans.append((m.start(1), m.end(1),
                              _format_like(got, want), got, key))

        if not spans:
            continue
        for start, end, new, old, key in sorted(spans, reverse=True):
            line = text[:start].count("\n") + 1
            text = text[:start] + new + text[end:]
            edits.append(f"{rel}:{line}: {key} {old} -> {new}")
        # Written through the same atomic helper the rest of this tree uses, so
        # a writer interrupted mid-README cannot leave a half-written document
        # behind claiming a count nobody measured.
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text)
        os.replace(tmp, path)

    # An UNREGISTERED claim is a number this file has never been told the
    # meaning of. Writing one would be inventing a population; it is reported
    # so the default run cannot look like it closed a gap it did not touch.
    for line in check_documents(inv):
        if "UNREGISTERED count claim" in line:
            unfixable.append(line)
    return sorted(edits), unfixable


def compare_committed(inv: dict, committed: dict) -> tuple[str, list[str]]:
    """Compare a committed artefact against a freshly measured one.

    Returns ("NOT_CHECKED", [reason]) when the two were enumerated from
    different populations — no drift verdict is possible across that gap and
    inventing one would be wrong in both directions — otherwise
    ("MEASURED", [failure lines]), empty when they agree.

    Pure: takes both dicts, touches no file. That is deliberate — the earlier
    version of this check could only be exercised by overwriting the real
    artefact on disk, which the suite's write guard refuses, and rightly:
    nothing that READS this tree may write to it.
    """
    committed_src = committed.get("enumerated_from")
    if committed_src != inv["enumerated_from"]:
        return "NOT_CHECKED", [
            f"the committed inventory was enumerated from {committed_src!r} "
            f"and this run enumerated from {inv['enumerated_from']!r}. Those "
            f"are different populations; no drift verdict is possible. Re-run "
            f"the generator where git can answer, or regenerate."]
    fails: list[str] = []
    for key, want in inv["populations"].items():
        have = committed.get("populations", {}).get(key)
        if have is None:
            fails.append(f"{OUT.name}: population {key!r} missing")
        elif have.get("sha256_of_sorted_paths") != want["sha256_of_sorted_paths"]:
            fails.append(
                f"{OUT.name}: {key} is stale — committed {have.get('count')}, "
                f"tree {want['count']}. Re-run "
                f"`python3 programs/gen_program_inventory.py`.")
    for key in committed.get("populations", {}):
        if key not in inv["populations"]:
            fails.append(f"{OUT.name}: population {key!r} no longer exists")
    return "MEASURED", fails


def check_index_cross(inv: dict) -> list[str]:
    """programs_catalogued must equal the total INDEX.md states for itself."""
    if not INDEX_MD.exists():
        return [f"{INDEX_MD.name} missing — cannot cross-check "
                f"programs_catalogued against the shipped catalogue."]
    m = re.search(r"\*\*Total programs \(excluding helpers / shims\):\*\* "
                  r"(\d+)", INDEX_MD.read_text())
    if not m:
        return ["INDEX.md states no total — cannot cross-check "
                "programs_catalogued. Re-run tools/gen_programs_index.py."]
    stated = int(m.group(1))
    got = inv["populations"]["programs_catalogued"]["count"]
    if stated != got:
        return [f"INDEX.md states {stated} catalogued programs, this "
                f"inventory measures {got}. The two helper predicates have "
                f"diverged, or one artefact is stale — regenerate BOTH "
                f"(tools/gen_programs_index.py and this file)."]
    return []


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed inventory is stale or any "
                         "stated count in a bound document has drifted")
    ap.add_argument("--check-artifact", action="store_true",
                    dest="check_artifact",
                    help="exit 1 only if the committed PROGRAM_INVENTORY.json "
                         "differs from the tree; ignore prose in bound "
                         "documents. For callers that regenerate the artefact "
                         "and need to know whether THOSE BYTES are now correct")
    ap.add_argument("--artifact-only", action="store_true",
                    dest="artifact_only",
                    help="regenerate PROGRAM_INVENTORY.json and NOTHING else. "
                         "For a caller whose contract is that one path: "
                         "`generated_artifact_conflict_resolve` registers this "
                         "artefact, regenerates it after a merge and stages "
                         "exactly what it regenerated, so a run that also "
                         "corrected prose would leave a correct edit unstaged "
                         "and outside its verdict")
    a = ap.parse_args()

    try:
        inv = discover()
    except OSError as exc:
        print(f"NOT CHECKED: cannot enumerate {PROGRAMS}: {exc}")
        sys.exit(2)

    if a.check or a.check_artifact:
        fails: list[str] = []
        if not OUT.exists():
            print(f"FAIL: {OUT.name} missing — run without --check to generate")
            sys.exit(1)
        try:
            committed = json.loads(OUT.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            # A truncated or unreadable artefact states no measurement. Reading
            # it as an empty inventory would report every population as newly
            # drifted; reading it as agreement would report a clean sweep over
            # a comparison that never happened. Neither is earned.
            print(f"NOT CHECKED: {OUT.name} is present but states no "
                  f"measurement ({exc}). Regenerate it.")
            sys.exit(2)
        status, msgs = compare_committed(inv, committed)
        if status == "NOT_CHECKED":
            print("NOT CHECKED: " + msgs[0])
            sys.exit(2)
        fails += msgs
        # --check-artifact STOPS HERE, and the reason is a real caller.
        # `generated_artifact_conflict_resolve.py` regenerates a derived file
        # after a merge and then asks "are the committed bytes now the derived
        # bytes?" about ONE registered path. Full --check also binds PROSE
        # counts in the READMEs, so it answers "no" for a reason that has
        # nothing to do with that path -- and the resolver's own degradation
        # table turns a still-red --check into rc 2, UNMEASURABLE. That would
        # report an unmeasurable tree where the artefact is provably correct.
        #
        # The comment that stood here said the prose was something "a
        # regeneration cannot fix". That was true when it was written and it is
        # why the round trip stayed open: a default run wrote the artefact, a
        # default --check demanded the prose too, and no invocation of this
        # program could satisfy the check it shipped with. `apply_documents`
        # closes it, and the resolver now asks for `--artifact-only` so its
        # narrow question keeps its narrow answer.
        if not a.check_artifact:
            try:
                fails += check_index_cross(inv)
                fails += check_documents(inv)
            except OSError as exc:
                print(f"NOT CHECKED: cannot read a bound document: {exc}")
                sys.exit(2)

        if fails:
            print(f"FAIL: {len(fails)} stated-count problem(s)")
            for f in fails:
                print(f"  - {f}")
            sys.exit(1)
        if a.check_artifact:
            print("OK: committed PROGRAM_INVENTORY.json matches the tree "
                  "(artefact only; prose counts NOT examined).")
        else:
            print("OK: committed inventory matches the tree, and every stated "
                  "count in the bound documents matches its population.")
        for key, p in sorted(inv["populations"].items()):
            print(f"  {key:32s} = {p['count']}")
        sys.exit(0)

    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(inv, indent=2) + "\n")
    os.replace(tmp, OUT)
    print(f"wrote {OUT}")
    for key, p in sorted(inv["populations"].items()):
        print(f"  {key:32s} = {p['count']}")

    # THE ROUND TRIP. The default run writes the artefact AND the prose that
    # quotes it, so `--check` after a plain regeneration is a question this
    # program can answer yes to. --artifact-only opts out for the one caller
    # whose contract is a single path.
    if not a.artifact_only:
        try:
            edits, unfixable = apply_documents(inv)
        except OSError as exc:
            print(f"\nNOT WRITTEN: cannot read or write a bound document: "
                  f"{exc}. The artefact above is correct; the prose that "
                  f"quotes it was NOT examined.", file=sys.stderr)
            sys.exit(2)
        if edits:
            print(f"\nrewrote {len(edits)} stated count(s) from the artefact:")
            for line in edits:
                print(f"  {line}")
        else:
            print("\nevery stated count in the bound documents already "
                  "matched; nothing to rewrite.")
        # Printed on the same run that wrote, and never swallowed: a
        # substitution cannot restore a sentence somebody reworded away, and a
        # run that stayed quiet about that would read as "the documents are
        # now correct" when they are not. --check is still the gate.
        if unfixable:
            print(f"\nSTILL RED — {len(unfixable)} problem(s) no substitution "
                  f"can fix:", file=sys.stderr)
            for line in unfixable:
                print(f"  - {line}", file=sys.stderr)

    print("\nEvery one of these is true and they measure different things — "
          "quote the KEY, never a bare number.")


if __name__ == "__main__":
    main()
