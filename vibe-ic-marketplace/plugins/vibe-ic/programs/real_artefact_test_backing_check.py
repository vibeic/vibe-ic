#!/usr/bin/env python3
"""real_artefact_test_backing_check.py — how many of a change's tests are
driven by a REAL checked-in artefact, and how many by a fixture the author
typed alongside the change.

ADVISORY. This program exits 0 on any classification. It REPORTS a split so a
reviewer can see `0 of 20 real-artefact-backed` BEFORE merging instead of
after a third round of adversarial review. It is not promoted to blocking
until a sweep over merged PRs shows zero false positives — a misclassification
here should cost one line of reading, never a blocked change.

WHY (vibe-ic#400)
-----------------
A change whose tests are ALL synthetic fixtures authored alongside it cannot
distinguish itself from its own absence. Measured on a real (withdrawn)
branch: mutate the guard to `if False and ...` and 10 of 31 tests die — which
reads like coverage. All 10 were hand-typed fixtures from the same commits.
The 4 tests that read a checked-in artefact ALL still passed on the mutant.
No document in the repo could tell that guard from its absence.

Measured over this repo: ~1 % of test modules read an in-repo artefact
through `programs/tests/_hostpaths`. The helper has existed, with a written
rationale, the whole time.

WHAT IT DOES NOT CLAIM
----------------------
A real-artefact test is not automatically a non-vacuous one. #400 measured a
corpus test asserting `new ⇒ old` that still passed when the predicate was
replaced by `return False` — an implication with a false antecedent is
vacuously true. What proves a test bites is a MUTATION RUN: disable the
change, re-run its own tests, and check a real-artefact test is among the
dead. This split report is what makes a reviewer ask for that run; it is a
floor, not a proof, and saying otherwise here would be the same
false-certificate shape the report is about.

chip-AGNOSTIC: pure AST over test sources. No design, PDK or vendor literal.

USAGE
-----
    real_artefact_test_backing_check.py [FILE ...]
    real_artefact_test_backing_check.py --base <ref> --head <ref> [--repo DIR]
    ... [--json OUT]

EXIT CODES
----------
    0 = always (ADVISORY)      2 = nothing to classify
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set

# The in-repo artefact accessors. `require_corpus` / `corpus_path` are
# deliberately NOT here: they reach an EXTERNAL corpus and SKIP when it is
# absent, so a test using them proves nothing on a bare checkout.
_REAL_ACCESSORS = frozenset((
    "require_repo", "repo_path", "repo_path_opt",
))

# The SECOND shape, found by running this program against its own author's
# tests: a corpus sweep that reaches the checked-in data by hand
# (`Path(__file__).parents[3] / "benchmark-data"`) instead of through the
# helper. Classifying those as SYNTHETIC would report `0 of 24` for a change
# whose tests really do walk the committed corpus — a report that misleads a
# reviewer in exactly the direction it exists to prevent.
#
# These are REPO DATA-ROOT names, not design literals: no chip, PDK or vendor
# token participates, and `source_chip_agnostic_check` passes on this file.
_REPO_DATA_ROOTS = frozenset((
    "benchmark-data", "benchmark_external", "community",
))
_FS_READS = frozenset((
    "read_text", "read_bytes", "glob", "rglob", "iterdir", "is_file",
    "is_dir", "open", "load", "walk", "listdir",
))


# The THIRD shape, owed since PR #411 and reported there as a known gap: a
# test can reach the real repository through GIT rather than through the
# filesystem. `test_f10_gitignore_formal_transcript_shippable.py` drives the
# actual `.gitignore` by asking `git rev-parse --show-toplevel` and then
# `git check-ignore` / `git ls-files` — which is not merely "real", it is the
# ONLY faithful way to test an ignore rule, because the rule's meaning IS
# what git computes. This program reported that change `0 of 40` backed.
#
# The discriminator against a SYNTHETIC git test is `init`: a test that
# builds a throwaway repo in `tmp_path` is a fixture no matter how much git
# it runs. Excluding those under-claims when a test does BOTH, which is the
# conservative direction — over-claiming "real" is what makes a
# fixture-only change look backed, and that is the failure this program
# exists to prevent.
_GIT_REPO_READS = frozenset((
    "rev-parse", "--show-toplevel", "check-ignore", "ls-files", "ls-tree",
    "cat-file", "check-attr", "merge-base",
))
_GIT_SCRATCH = frozenset(("init", "init-db", "clone"))


def _calls_in(node: ast.AST) -> Set[str]:
    """Every callable NAME referenced under `node` (bare or attribute tail)."""
    out: Set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.Name):
            out.add(n.id)
    return out



def _sweeps_repo_data(node: ast.AST, funcs: Dict[str, ast.AST]) -> bool:
    """True when the test names a repo DATA ROOT and performs a filesystem
    read — the hand-rolled equivalent of `require_repo`."""
    def _scan(n):
        names, strs = _calls_in(n), set()
        for x in ast.walk(n):
            if isinstance(x, ast.Constant) and isinstance(x.value, str):
                strs.add(x.value)
        return names, strs
    names, strs = _scan(node)
    for c in list(names):
        if c in funcs:
            n2, s2 = _scan(funcs[c])
            names |= n2
            strs |= s2
    return bool(strs & _REPO_DATA_ROOTS) and bool(names & _FS_READS)


def _reads_repo_via_git(node: ast.AST, funcs: Dict[str, ast.AST]) -> bool:
    """True when the test interrogates the REAL repository through git.

    Requires `git` itself, a repo-state read subcommand, and the ABSENCE of
    any scratch-repo construction — see `_GIT_REPO_READS` above for why the
    absence is what keeps this honest.
    """
    def _strs(n):
        return {x.value for x in ast.walk(n)
                if isinstance(x, ast.Constant) and isinstance(x.value, str)}
    strs = _strs(node)
    for c in _calls_in(node):
        if c in funcs:
            strs |= _strs(funcs[c])
    return ("git" in strs
            and bool(strs & _GIT_REPO_READS)
            and not (strs & _GIT_SCRATCH))


def classify_module(path: Path) -> dict:
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except (OSError, SyntaxError) as exc:
        return {"file": str(path), "error": f"{type(exc).__name__}: {exc}",
                "tests": [], "real": [], "synthetic": []}

    funcs: Dict[str, ast.AST] = {}
    fixtures: Set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = node
            for dec in node.decorator_list:
                # `@pytest.fixture` / `@fixture` / `@pytest.fixture(...)`
                d = dec.func if isinstance(dec, ast.Call) else dec
                name = (d.attr if isinstance(d, ast.Attribute)
                        else getattr(d, "id", ""))
                if name == "fixture":
                    fixtures.add(node.name)

    # Module-level statements count too: a test can be backed by a constant
    # resolved once at import (`_CORPUS = require_repo("benchmark-data")`).
    module_level = set()
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
            module_level |= _calls_in(node)
    module_backed = bool(module_level & _REAL_ACCESSORS)

    def reaches(name: str, seen: Set[str]) -> bool:
        if name in seen or name not in funcs:
            return False
        seen.add(name)
        called = _calls_in(funcs[name])
        if called & _REAL_ACCESSORS:
            return True
        return any(reaches(c, seen) for c in called if c in funcs)

    tests, real, synthetic = [], [], []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        tests.append(node.name)
        backed = module_backed or reaches(node.name, set())
        kind = "helper" if backed else ""
        if not backed and _sweeps_repo_data(node, funcs):
            backed, kind = True, "ad-hoc path"
        if not backed and _reads_repo_via_git(node, funcs):
            backed, kind = True, "git repo"
        if not backed:
            # A pytest FIXTURE the test requests by parameter name is part of
            # what drives it. Missing this would misreport every test whose
            # real artefact arrives through a fixture — the idiomatic shape.
            params = [a.arg for a in node.args.args]
            backed = any(p in fixtures and reaches(p, set()) for p in params)
            if backed:
                kind = "fixture"
        (real if backed else synthetic).append(
            f"{node.name} [{kind}]" if backed else node.name)
    return {"file": str(path), "tests": tests, "real": real,
            "synthetic": synthetic}


class _RefFile:
    """A test module read from a git REF rather than the working tree.

    `classify_module` only needs a path to name and text to parse, so this
    carries both. It is not a Path subclass on purpose: a partial Path
    lookalike invites someone to call `.is_file()` on it and get a plausible
    lie, which is the failure mode this class exists to remove.
    """

    def __init__(self, rel: str, text: str):
        self._rel, self._text = rel, text

    def read_text(self, *a, **k) -> str:
        return self._text

    def __str__(self) -> str:
        return self._rel

    def __fspath__(self) -> str:
        return self._rel


def _changed_test_modules(repo: Path, base: str, head: str) -> List[Path]:
    r = subprocess.run(
        ["git", "-C", str(repo), "diff", "--name-only",
         "--diff-filter=AM", f"{base}...{head}"],
        capture_output=True, text=True)
    if r.returncode != 0:
        return []
    out = []
    for rel in r.stdout.split():
        p = Path(rel)
        if not (p.name.startswith("test_") and p.suffix == ".py"):
            continue
        f = repo / rel
        if f.is_file():
            out.append(f)
            continue
        # The file exists at HEAD but not in this WORKING TREE — the normal
        # state when reviewing a PR branch from a main checkout. Judging the
        # working tree made the checker SKIP with "no test module added or
        # modified" on exactly the changes it exists to judge; found running
        # it against #425, which adds a 462-line test module. Same defect as
        # #416 and #414: the tree you are standing in is not the change under
        # review. Read the blob from the ref instead.
        blob = subprocess.run(
            ["git", "-C", str(repo), "show", f"{head}:{rel}"],
            capture_output=True, text=True)
        if blob.returncode == 0:
            out.append(_RefFile(rel, blob.stdout))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--base")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--repo", default=".")
    ap.add_argument("--json", dest="json_out")
    a = ap.parse_args(argv)

    if a.files:
        mods = [Path(f) for f in a.files if Path(f).is_file()]
    elif a.base:
        mods = _changed_test_modules(Path(a.repo).resolve(), a.base, a.head)
    else:
        print("[SKIP] real_artefact_test_backing_check: give FILEs or --base.")
        return 2

    if not mods:
        print("[SKIP] real_artefact_test_backing_check: this change adds or "
              "modifies no test module — nothing to classify.")
        return 2

    reports = [classify_module(m) for m in mods]
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(reports, indent=2) + "\n")

    tot = sum(len(r["tests"]) for r in reports)
    tot_real = sum(len(r["real"]) for r in reports)
    print(f"real_artefact_test_backing_check (ADVISORY): "
          f"{tot_real} of {tot} test(s) driven by a checked-in artefact, "
          f"across {len(reports)} changed test module(s)")
    for r in reports:
        if r.get("error"):
            print(f"   ? {r['file']}: {r['error']}")
            continue
        print(f"   {len(r['real'])}/{len(r['tests'])}  {r['file']}")
        for t in r["real"]:
            print(f"        real: {t}")
    if tot and tot_real == 0:
        print("   NOTE: every test in this change is a fixture authored "
              "alongside it. Such a suite cannot distinguish the change from "
              "its own absence — ask for a mutation run in which a "
              "REAL-artefact test is among the dead, or say why no in-repo "
              "artefact exercises this change.")
    print("   ADVISORY: this reports a split; it does not prove a "
          "real-artefact test is non-vacuous (an implication with a false "
          "antecedent passes either way). Only a mutation run does.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
