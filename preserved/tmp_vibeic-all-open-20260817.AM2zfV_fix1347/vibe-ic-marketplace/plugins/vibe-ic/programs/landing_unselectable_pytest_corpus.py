#!/usr/bin/env python3
"""landing_unselectable_pytest_corpus.py — the tracked pytest files NO landing
stage can reach, enumerated so a stage can run them.

rc: 0 = census produced / 1 = an --audit finding / 2 = NOT DETERMINED. rc=2 is
never a pass and never an empty list: "I could not look" must not reach a
reader as "I looked and there was nothing".

WHY THIS EXISTS (vibe-ic#1424)
==============================
The landing gate's pytest run is SELECTOR-DRIVEN, and the selector is rooted at
one tree::

    tools/gatekeeper-land.sh:268   python3 programs/ci_targeted_test_select.py …
    tools/gatekeeper-land.sh:299   xargs -a "$sel" python3 -m pytest …

It runs the selector's explicit list — not bare `pytest` (so `testpaths` does
not govern it) and not `run_tests.sh` (so tier discovery does not either). And
the selector cannot emit anything outside one directory::

    programs/ci_targeted_test_select.py:357   _TESTS_REL = "programs/tests"
    programs/ci_targeted_test_select.py:698   if not rel.startswith(_TESTS_REL + "/"): return False

`run_repo_tools_pytest` (vibe-ic#1312, `gatekeeper-land.sh:334`) closed the same
hole for the REPO-ROOT `tools/` tree, by discovery and unconditionally. It did
not close it for the rest. MEASURED on 3d13e2c59, tracked files only, and the
selector run on a real base emitted 29 files of which 0 lay outside
`programs/tests/`:

    programs/tests/            2477 files   <- the only tree the selector emits
    tools/                       29         <- run_repo_tools_pytest, since #1312
    ----------------------------------      the rest reaches NO landing stage:
    skills/*/tests/              67 files    222 tests
    mcp-eda/                     31          201
    tools/phase1_engine/tests/    8          121
    _shared/                      3          283
                                ---         ----
                                109 files    827 tests

827 pytest nodes across 109 files that no landing could ever be blocked by.
`benchmark-data/`'s 121 `test_*.py` are NOT in that number: they are CVDP corpus
artefacts — the scored harness's own files, not this repo's tests — and they are
DECLARED below rather than left implied by a constant, which is the specific
thing #1424 asks for.

WHY A COMPLEMENT AND NOT A ROSTER
=================================
The set is computed as "every tracked test file MINUS what a landing stage
already runs MINUS what is declared out", so a tree added tomorrow is in it the
day it is added, with nothing to keep in step. A roster is the recorded-register
defect this repo has removed repeatedly (census / tranche baseline / skip
ratchet): it goes stale silently and in the SAFE-LOOKING direction, because
fewer files still reports PASS.

The two subtrahends are DECLARED WITH A PROBE, not assumed. `_COVERED` names,
for each stage, a string that must appear in `tools/gatekeeper-land.sh`; the
test suite asserts every probe still matches. So deleting `run_repo_tools_pytest`
does not silently drop `tools/` out of the complement — it turns a test red.

WHY NOT GENERALISE THE SELECTOR INSTEAD
=======================================
#1424 declined to propose that, and the reason survives inspection:
`_TESTS_REL` roots every index `ci_targeted_test_select.py` builds (:478 :485
:513 :554 :562 :667 :676 :727), so widening it changes what the gate runs for
every PR. The selector is a TARGETING mechanism — it answers "which tests does
this diff put at risk". These trees are not un-targeted; they are unreachable.
An unconditional discovery run is the smaller and more honest instrument, and it
is the one #1312 already proved in this same file.

THE COST, MEASURED
==================
109 files / 827 collected, from the repo root, as the gate runs pytest
(`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 --timeout=180 --timeout-method=thread`):
761 passed, 58 skipped, 5 xfailed, 3 xpassed, 0 failed in 21.3 s. Zero
INHERITED reds — which is not the same as zero cost: the point of adopting a
tree is that its FUTURE failures block a landing.

CWD IS PART OF THE MEASUREMENT, AND IS NOT A FREE CHOICE
========================================================
The stage runs from the REPO ROOT, like `run_repo_tools_pytest`. That is not
where the green came from — it is where this code says it lives:
`tools/phase1_engine/gap_detect.py:43` resolves `DEFAULT_DEFAULTS_DIR` as the
bare relative `vibe-ic-marketplace/plugins/vibe-ic/agents/defaults`, which only
exists when cwd IS the repo root. From the PLUGIN root the same two tests fail
(`test_typical_scaffolds_retired.py`, `assert 'apb-peripheral' in {}`) — that is
vibe-ic#1390, still open, and nothing here silences it: it is a defect in the
resolution, not in the tree this stage runs.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
sys.path.insert(0, str(Path(__file__).resolve().parent))  # so the sibling import below resolves however this is invoked
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)

# pytest's own default collection patterns, spelled once. Anything else here
# would be a SECOND definition of "is a test file" that can drift from the one
# pytest uses — and the direction it drifts in is a file nobody runs.
_TEST_BASENAME = re.compile(r"^(test_.*\.py|.*_test\.py)$")

# The plugin, repo-relative. This program lives inside it, so it is derived
# from __file__ rather than stated, and the derivation is asserted by the tests.
_PLUGIN_REL = "vibe-ic-marketplace/plugins/vibe-ic"


@dataclass(frozen=True)
class Covered:
    """A tree some landing stage already runs, and how to check it still does.

    `probe` is a literal that must appear in `tools/gatekeeper-land.sh`. It is
    the wiring guard: a stage that is deleted or renamed must not be able to
    quietly remove its tree from this program's subtrahend, because that would
    move files OUT of the complement — the safe-looking direction again.
    """

    prefix: str          # repo-relative, always ends in "/"
    stage: str           # the shell function in tools/gatekeeper-land.sh
    probe: str           # literal that must be present in that file
    why: str


@dataclass(frozen=True)
class Excluded:
    """A tree deliberately NOT run by a landing, with the reason STATED.

    #1424: "the exclusion should be *stated* rather than implied by a constant".
    A prefix that matches nothing is an --audit finding, not a silent no-op.
    """

    prefix: str
    why: str


def _covered(plugin_rel: str = _PLUGIN_REL) -> Tuple[Covered, ...]:
    return (
        Covered(
            prefix=f"{plugin_rel}/programs/tests/",
            stage="run_pytest",
            probe="programs/ci_targeted_test_select.py",
            why="the targeted selector's one tree — the only paths "
                "ci_targeted_test_select.py is able to emit (_TESTS_REL).",
        ),
        Covered(
            prefix="tools/",
            stage="run_repo_tools_pytest",
            probe="run_repo_tools_pytest",
            why="vibe-ic#1312 — discovered and run unconditionally from the "
                "repo root, because the plugin-scoped selector cannot address "
                "repo-root paths at all.",
        ),
    )


_EXCLUDED: Tuple[Excluded, ...] = (
    Excluded(
        prefix="benchmark-data/",
        why="CVDP corpus artefacts — the scored harness's OWN files (cocotb "
            "`test_runner.py` and the per-problem testbenches it drives), "
            "published as evidence of a run. They are inputs to a benchmark, "
            "not tests of this repo, and running them would need the EDA "
            "toolchain the benchmark supplies. Counting them would inflate "
            "the denominator this issue is measured against.",
    ),
)


def repo_root(start: Optional[Path] = None) -> Optional[Path]:
    """The enclosing git repository, or None.

    None is a REFUSAL that the caller must turn into rc=2. It is never turned
    into an empty corpus, which would read as "nothing to run".
    """
    here = (start or Path(__file__)).resolve()
    for anc in (here, *here.parents):
        if (anc / ".git").exists():
            return anc
    return None


def plugin_rel(repo: Path) -> str:
    """This plugin's path relative to `repo`, derived from THIS file.

    Derived, not stated: a hand-written constant is a second copy of a layout
    that this file cannot see change.
    """
    plugin = Path(__file__).resolve().parent.parent
    try:
        return plugin.relative_to(repo).as_posix()
    except ValueError:
        return _PLUGIN_REL


def tracked_test_files(repo: Path) -> Optional[List[str]]:
    """Every TRACKED file pytest would collect by name, repo-relative, sorted.

    None on any git failure — the rc=2 path. `git ls-files` is used rather than
    a walk so that an untracked scratch file in somebody's worktree cannot
    change what a landing runs.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "-z"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    files = [p for p in out.stdout.split("\0") if p]
    if not files:
        # A repository with zero tracked files is not a repository we can
        # measure. Refuse rather than report an empty corpus.
        return None
    return sorted(p for p in files if _TEST_BASENAME.match(os.path.basename(p)))


def partition(files: Sequence[str], plugin: str = _PLUGIN_REL) -> Dict[str, object]:
    """Split the corpus into covered / excluded / unselectable.

    `unselectable` is the COMPLEMENT, so it needs no maintenance: a new tree
    lands in it the moment its first test file is tracked.
    """
    covered = _covered(plugin)
    by_stage: Dict[str, List[str]] = {c.prefix: [] for c in covered}
    by_exclusion: Dict[str, List[str]] = {e.prefix: [] for e in _EXCLUDED}
    unselectable: List[str] = []
    for rel in files:
        for c in covered:
            if rel.startswith(c.prefix):
                by_stage[c.prefix].append(rel)
                break
        else:
            for e in _EXCLUDED:
                if rel.startswith(e.prefix):
                    by_exclusion[e.prefix].append(rel)
                    break
            else:
                unselectable.append(rel)
    return {
        "total": len(files),
        "covered": by_stage,
        "excluded": by_exclusion,
        "unselectable": unselectable,
    }


def audit(repo: Path, part: Dict[str, object], plugin: str) -> List[str]:
    """Findings that make the census itself untrustworthy. Empty == clean."""
    findings: List[str] = []
    land = repo / "tools" / "gatekeeper-land.sh"
    text = land.read_text(encoding="utf-8", errors="replace") if land.is_file() else None
    if text is None:
        findings.append(
            f"{land} is absent — the stages this program subtracts cannot be "
            f"confirmed to exist, so the complement below is not a measurement.")
    covered: Dict[str, List[str]] = part["covered"]      # type: ignore[assignment]
    for c in _covered(plugin):
        if text is not None and c.probe not in text:
            findings.append(
                f"stage {c.stage!r} no longer appears in tools/gatekeeper-land.sh "
                f"(probe {c.probe!r} not found) — {c.prefix} would be subtracted "
                f"from the complement while nothing runs it.")
        if not covered.get(c.prefix):
            findings.append(
                f"declared covered tree {c.prefix!r} matches NO tracked test "
                f"file — a subtrahend that removes nothing is a stale roster.")
    excluded: Dict[str, List[str]] = part["excluded"]    # type: ignore[assignment]
    for e in _EXCLUDED:
        if not excluded.get(e.prefix):
            findings.append(
                f"declared exclusion {e.prefix!r} matches NO tracked test file "
                f"— the reason it states no longer describes this tree.")
        if not e.why.strip():
            findings.append(f"exclusion {e.prefix!r} states no reason.")
    return findings


def _census_lines(part: Dict[str, object], plugin: str) -> List[str]:
    lines = [f"tracked test files: {part['total']}"]
    covered: Dict[str, List[str]] = part["covered"]      # type: ignore[assignment]
    for c in _covered(plugin):
        lines.append(f"  covered   {len(covered[c.prefix]):5d}  {c.prefix}"
                     f"   [{c.stage}]")
    excluded: Dict[str, List[str]] = part["excluded"]    # type: ignore[assignment]
    for e in _EXCLUDED:
        lines.append(f"  excluded  {len(excluded[e.prefix]):5d}  {e.prefix}")
    uns: List[str] = part["unselectable"]                # type: ignore[assignment]
    lines.append(f"  UNSELECTABLE {len(uns):5d}  <- run by "
                 f"run_unselectable_pytest")
    return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=None,
                    help="repository root (default: the one enclosing this file)")
    ap.add_argument("--list", action="store_true",
                    help="print the unselectable files, one per line (default)")
    ap.add_argument("--census", action="store_true",
                    help="print the per-tree census instead of the file list")
    ap.add_argument("--audit", action="store_true",
                    help="rc=1 on a stale subtrahend / exclusion / missing stage")
    ap.add_argument("--json", metavar="OUT", help="write the full report as JSON")
    args = ap.parse_args(list(argv) if argv is not None else None)

    repo = Path(args.repo).resolve() if args.repo else repo_root()
    if repo is None or not (repo / ".git").exists():
        print("NOT DETERMINED: no enclosing git repository — this is not an "
              "empty corpus, it is a refusal to measure.", file=sys.stderr)
        return 2
    plugin = plugin_rel(repo)
    files = tracked_test_files(repo)
    if files is None:
        print("NOT DETERMINED: `git ls-files` did not answer — this is not an "
              "empty corpus, it is a refusal to measure.", file=sys.stderr)
        return 2
    part = partition(files, plugin)
    findings = audit(repo, part, plugin)

    if args.json:
        atomic_write_text(Path(args.json), 
            json.dumps({"plugin": plugin, "findings": findings, **part},
                       indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.audit:
        for line in _census_lines(part, plugin):
            print(line)
        for f in findings:
            print(f"  FINDING  {f}")
        return 1 if findings else 0
    if args.census:
        for line in _census_lines(part, plugin):
            print(line)
        return 0
    for rel in part["unselectable"]:                     # type: ignore[union-attr]
        print(rel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
