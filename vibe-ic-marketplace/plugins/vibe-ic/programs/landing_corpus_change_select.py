#!/usr/bin/env python3
"""landing_corpus_change_select.py — change-awareness for the two landing
corpora that run unconditionally, and the CLOSURE PROOF that decides whether
either of them may be skipped.

rc: 0 = answered / 1 = closure NOT proven (``--prove-closure``) / 2 = NOT
DETERMINED. rc=2 is never an empty selection: "I could not look" must not reach
a reader as "nothing was selected".

WHAT THIS IS FOR
================
`tools/gatekeeper-land.sh` runs three non-overlapping pytest corpora on every
landing:

    run_pytest                 the targeted selection  — CHANGE-AWARE, via
                               `programs/ci_targeted_test_select.py`
    run_repo_tools_pytest      repo-root `tools/`      — UNCONDITIONAL
    run_unselectable_pytest    the complement          — UNCONDITIONAL

The two unconditional stages cost the same wall clock on a one-line diff as on
a rewrite. The obvious repair is to give them the same change-awareness the
first stage already has, and this module is that repair — built out of
`ci_targeted_test_select`'s OWN primitives (`_imported_module_names`,
`_LOADER_*`, `_distinctive_key`, `_tool_ref_pattern`, `_glob_patterns_in`), not
a second mechanism that could drift from the first.

IT DOES NOT MAKE EITHER CORPUS SKIPPABLE, AND THE REASON IS MEASURED
====================================================================
A selection may be trusted to SKIP work only if it is COMPLETE: every file
whose verdict a change can flip must be selected. Completeness is the property
this module could not establish, for either corpus, and `--prove-closure`
exists to keep saying so out loud instead of leaving it in a commit message.

Two counterexamples, both EXECUTED rather than argued (2026-08-17, worktree off
`f6b0e77dd`):

  1. repo-tools corpus.
     `tools/ci/test_repo_tools_tests_gate.py` extracts the shell function
     `run_repo_tools_pytest` out of `tools/gatekeeper-land.sh` and RUNS it; that
     function invokes `$PROGRAMS/suite_write_guard.py`. One mutation of
     `programs/suite_write_guard.py` — `return RC_CLEAN` in place of
     `return RC_WROTE if result["blocking"] else RC_CLEAN` — takes the file from

         10 passed in 1.47s
     to
         1 failed, 9 passed in 1.23s
           FAILED …::test_a_repo_test_that_writes_to_the_tree_turns_the_gate_red

     Every edge kind the mechanism has returns NOTHING for that pair:

         rule-7 key   'suite_write_guard.py'   lexical hit  False
         import edge                            False
         loader edge                            []
         glob edge                              set()

     The file mentions `suite_write_guard` once, in a COMMENT, without the
     extension — so even the lexical rule cannot see it. The dependency is real
     and it arrives through a SUBPROCESS: the mechanism has no hop that follows
     what an invoked script itself reads.

  2. unselectable corpus.
     `skills/sta-review/tests/test_compliance.py` loads
     `skills/sta-review/compliance.yaml` through `Path` arithmetic
     (`THIS.parent.parent / "compliance.yaml"`). Emptying that file's
     `requirements:` list takes the file from `2 passed, 1 skipped` to
     `2 failed, 1 passed`. The rule-7 key for the yaml is
     `sta-review/compliance.yaml` — `compliance.yaml` alone is ambiguous across
     64 skills — and the test spells that suffix nowhere:

         rule-7 key   'sta-review/compliance.yaml'   lexical hit  False
         import edge                                  False
         loader edge                                  []

THE PROBE FIRES — the same three questions on two controls, same run:

    _shared/skill_compliance_check.py -> skills/sta-review/tests/test_compliance.py
        key 'skill_compliance_check.py'  lexical hit True   import edge True
    tools/gatekeeper-land.sh          -> tools/ci/test_repo_tools_tests_gate.py
        key 'gatekeeper-land.sh'         lexical hit True

so "no edge" above is a measurement, not a broken probe.

WHY THIS CANNOT BE PATCHED AWAY BY NAMING THE TWO CASES
=======================================================
Both counterexamples share ONE structure, and it is structural rather than
incidental: every edge `ci_targeted_test_select` knows is a ONE-HOP relation
from the test file's own text — an import, an explicit loader call, a literal
path token, a glob pattern. The only transitive closure it performs
(`_helper_consumers`) closes over `import` edges among helpers under
`programs/tests/`. Neither corpus is reached that way:

  * a corpus file that runs a shell script or a `sys.executable` subprocess
    depends on everything THAT process reads, and nothing in the mechanism
    crosses the exec boundary;
  * a corpus file that builds a path with `Path` arithmetic states no token any
    lexical rule can key on;
  * `conftest.py` is injected by pytest and named by nobody — the residual
    `ci_targeted_test_select`'s own docstring already records for its own tree.

Closing one named pair leaves the shape. `--prove-closure` therefore reports
the POPULATION, measured, rather than a list of known-bad files.

HOW `--prove-closure` MEASURES IT
=================================
Statically deciding what a test reads is the halting problem wearing a hat, so
the proof obligation is discharged from a RUN instead. `--touch-audit` loads
this module as a pytest plugin, installs `sys.addaudithook`, and records — per
test FILE — every tracked repo path the session opened and every subprocess it
spawned. `--prove-closure` then asks, for each observed (file, path) pair, the
only question that matters:

    would `select([path])` have selected `file`?

A pair where the answer is no is an edge the mechanism cannot follow, and one
such pair anywhere in a corpus is enough to refuse skipping it.

THE ASYMMETRY IS THE POINT. A run OBSERVES a lower bound on each file's
dependency set: a branch not taken today reads nothing today. So an EMPTY
residual is *not* a proof of completeness and this program never reports it as
one — it reports "no unfollowable edge was observed on this run", which is a
weaker sentence on purpose. A NON-EMPTY residual, on the other hand, is a
proof of INCOMPLETENESS, because each pair in it was executed. Only the
refusing direction is ever proven, which is why the answer here is a refusal.

WHAT IS SAFE TO DO WITH THE SELECTION
=====================================
`--corpus X --base Y` prints the corpus files a diff puts at risk. That is a
REPORT — the same distinction `gatekeeper-land.sh` already draws with its
`report()` helper — and it is useful for a human triaging a red landing. It is
NOT a licence to run the complement less, and `tools/gatekeeper-land.sh` is
deliberately left byte-identical by the change that added this file:
`programs/tests/test_landing_corpus_change_select.py` asserts that both stages
are still invoked unconditionally, so a later branch cannot quietly wire a skip
onto a selection whose completeness nobody established.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ci_targeted_test_select as S            # noqa: E402  the ONE mechanism
import landing_unselectable_pytest_corpus as U  # noqa: E402  the ONE census

#: The two stages that run unconditionally today.
CORPUS_REPO_TOOLS = "repo-tools"
CORPUS_UNSELECTABLE = "unselectable"
CORPORA: Tuple[str, ...] = (CORPUS_REPO_TOOLS, CORPUS_UNSELECTABLE)


class NotDetermined(Exception):
    """The measurement could not be taken. NEVER an empty answer."""


# ---------------------------------------------------------------------------
# Corpus enumeration — the SAME populations the two stages run.
# ---------------------------------------------------------------------------

def corpus_files(repo: Path, corpus: str) -> List[str]:
    """Repo-relative test files in ``corpus``, sorted.

    `repo-tools` mirrors `run_repo_tools_pytest`'s discovery
    (`find tools \\( -name 'test_*.py' -o -name '*_test.py' \\)`) and
    `unselectable` delegates to `landing_unselectable_pytest_corpus`, so neither
    population is restated here. A restated population is the recorded-register
    defect this repo has removed repeatedly: it goes stale silently and in the
    direction that still prints PASS.
    """
    if corpus == CORPUS_REPO_TOOLS:
        root = repo / "tools"
        if not root.is_dir():
            raise NotDetermined(f"{root} is not a directory")
        out = [p.relative_to(repo).as_posix()
               for p in root.rglob("*.py")
               if U._TEST_BASENAME.match(p.name) and p.is_file()]
        if not out:
            raise NotDetermined(
                "discovery matched NO files under tools/ — an empty corpus is "
                "not evidence, it is a broken probe")
        return sorted(out)
    if corpus == CORPUS_UNSELECTABLE:
        files = U.tracked_test_files(repo)
        if files is None:
            raise NotDetermined("`git ls-files` did not answer")
        part = U.partition(files, U.plugin_rel(repo))
        out = list(part["unselectable"])          # type: ignore[arg-type]
        if not out:
            raise NotDetermined(
                "the complement is EMPTY — either every tree is genuinely "
                "covered or the census broke")
        return sorted(out)
    raise NotDetermined(f"unknown corpus {corpus!r}; expected one of {CORPORA}")


# ---------------------------------------------------------------------------
# The mechanism, generalised to an arbitrary corpus.
#
# Every edge below is `ci_targeted_test_select`'s, imported rather than
# reimplemented. What changes is only WHERE it is rooted: that selector's
# indexes are all anchored at `programs/tests/` (`_TESTS_REL`), which is exactly
# why these two corpora are unreachable from it.
# ---------------------------------------------------------------------------

def module_names_of(rel: str) -> Set[str]:
    """Every module name a repo-relative ``.py`` file can be imported by.

    The bare stem plus every dotted suffix of its path
    (``a/b/c.py`` -> ``c``, ``b.c``, ``a.b.c``), because this tree imports
    helpers by bare name after an inline `sys.path.insert` as well as by
    package path. DELIBERATELY GENEROUS: a name shared by two files couples the
    consumers of both, which over-selects. Over-selection is the safe direction
    for a gate; under-selection is the defect.
    """
    p = Path(S._norm(rel))
    if p.suffix != ".py":
        return set()
    parts = list(p.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
        if not parts:
            return set()
    else:
        parts[-1] = p.stem
    return {".".join(parts[i:]) for i in range(len(parts))}


class CorpusIndex:
    """Everything the corpus states about what it depends on, read once.

    Built eagerly because every caller here needs all of it; the cost is a
    single pass over the corpus plus one over the tracked `.py` tree.
    """

    def __init__(self, repo: Path, corpus: str) -> None:
        self.repo = repo
        self.corpus = corpus
        self.files: List[str] = corpus_files(repo, corpus)
        self.file_set: Set[str] = set(self.files)
        repo_files = S._repo_files(repo)
        if repo_files is None:
            raise NotDetermined("`git ls-files` did not answer")
        self.repo_files: List[str] = repo_files
        self.repo_file_set: Set[str] = set(repo_files)

        # name -> tracked .py files that can be imported under it
        self.by_module_name: Dict[str, Set[str]] = {}
        self.imports_of: Dict[str, Set[str]] = {}
        for rel in repo_files:
            if not rel.endswith(".py"):
                continue
            for n in module_names_of(rel):
                self.by_module_name.setdefault(n, set()).add(rel)

        self.text: Dict[str, str] = {}
        self.glob_pats: Dict[str, Set[str]] = {}
        self.loader_stems: Dict[str, Set[str]] = {}
        for rel in self.files:
            self.text[rel] = self._read(rel)
            self.glob_pats[rel] = S._glob_patterns_in(self.text[rel])
            self.loader_stems[rel] = self._loader_stems(self.text[rel])

        self._closure: Dict[str, Set[str]] = {}

    # -- reading ---------------------------------------------------------
    def _read(self, rel: str) -> str:
        try:
            return (self.repo / rel).read_text(encoding="utf-8",
                                               errors="replace")
        except OSError:
            return ""

    def _imports(self, rel: str) -> Set[str]:
        """Module names ``rel`` imports (ancestors included), memoised.

        Fail-open exactly as rule 4 does: an unparseable file contributes no
        edges rather than aborting a selection. A selector that dies on one bad
        file selects nothing, and selecting nothing is the defect.
        """
        got = self.imports_of.get(rel)
        if got is None:
            names = S._imported_module_names(self._read(rel), None)
            got = set() if names is None else names
            self.imports_of[rel] = got
        return got

    @staticmethod
    def _loader_stems(text: str) -> Set[str]:
        """`spec_from_file_location` edges — BOTH the alias and the loaded file.

        Same two readings `_build_import_edge_index` takes (vibe-ic#1176), so a
        test that renames a module on the way in still carries its edge.
        """
        out: Set[str] = {m.group(1) for m in S._LOADER_NAME_RE.finditer(text)}
        for m in S._LOADER_CALL_RE.finditer(text):
            for lit in S._LOADER_PY_LITERAL_RE.finditer(m.group("args")):
                out.add(Path(S._norm(lit.group(1))).stem)
        return out

    # -- the transitive import closure -----------------------------------
    def import_closure(self, rel: str) -> Set[str]:
        """Module names reachable from ``rel`` through imports, transitively.

        THE PART THE TASK NAMES EXPLICITLY. `_helper_consumers` closes over
        helper->helper imports inside `programs/tests/`; this is the same walk
        with the tree it may traverse widened to every tracked `.py`, so an
        `a -> b -> c` chain selects the corpus file when `c` changes.
        """
        got = self._closure.get(rel)
        if got is not None:
            return got
        seen_names: Set[str] = set()
        seen_files: Set[str] = {rel}
        frontier = [rel]
        while frontier:
            cur = frontier.pop()
            for name in self._imports(cur):
                if name in seen_names:
                    continue
                seen_names.add(name)
                for f in self.by_module_name.get(name, ()):  # resolve to files
                    if f not in seen_files:
                        seen_files.add(f)
                        frontier.append(f)
        self._closure[rel] = seen_names
        return seen_names

    # -- selection -------------------------------------------------------
    def select(self, changed: Sequence[str]) -> Set[str]:
        """Corpus files a change to ``changed`` puts at risk.

        The union of the same five edge kinds the targeted selector uses:

          direct   the changed path IS a corpus file       (rule 2)
          import   a corpus file imports it, transitively  (rules 4/5)
          loader   `spec_from_file_location` names it      (rule 5)
          key      a corpus file spells its distinctive
                   path suffix as a literal token          (rule 7)
          glob     a corpus file globs a pattern it matches (rule 8)
        """
        out: Set[str] = set()
        for raw in changed:
            c = S._norm(raw)
            if not c:
                continue
            if c in self.file_set:
                out.add(c)
            if c.endswith(".py"):
                names = module_names_of(c)
                stem = Path(c).stem
                for rel in self.files:
                    if rel in out:
                        continue
                    if names & self.import_closure(rel):
                        out.add(rel)
                    elif stem in self.loader_stems[rel]:
                        out.add(rel)
            key = S._distinctive_key(c, self.repo_files)
            if key:
                pat = S._tool_ref_pattern(key)
                for rel in self.files:
                    if rel not in out and pat.search(self.text[rel]):
                        out.add(rel)
            base = Path(c).name
            for rel in self.files:
                if rel in out:
                    continue
                pats = self.glob_pats[rel]
                if pats and any(fnmatch.fnmatch(base, p)
                                or fnmatch.fnmatch(c, p) for p in pats):
                    out.add(rel)
        return out


# ---------------------------------------------------------------------------
# The closure proof.
# ---------------------------------------------------------------------------

def closure_gaps(index: CorpusIndex,
                 touched: Dict[str, Iterable[str]]) -> List[Tuple[str, str]]:
    """(corpus file, repo path) pairs the mechanism CANNOT follow.

    ``touched`` is the observed read/exec map from `--touch-audit`. Each pair
    returned was executed, so a non-empty result is a PROOF of incompleteness.
    An empty result proves nothing — see the module docstring.

    A key that is not a corpus file is a REFUSAL, never a gap. The first
    version of the audit attributed some tests through pytest's rootdir-relative
    `location[0]` and some through an absolute collector path, so ~100 of 210
    keys were in a different key space — and every one of them scored as an
    unfollowable edge, inflating the finding on the safe-looking side of the
    argument this program is making. A measurement that can only err towards
    its own conclusion is not a measurement.
    """
    stray = sorted(set(touched) - index.file_set)
    if stray:
        raise NotDetermined(
            f"{len(stray)} touch-map key(s) are not files of corpus "
            f"{index.corpus!r} (first: {stray[0]!r}) — the attribution is "
            f"broken, so no gap count from it can be trusted")
    cache: Dict[str, Set[str]] = {}
    gaps: List[Tuple[str, str]] = []
    for rel in sorted(touched):
        for path in sorted(set(touched[rel])):
            if path == rel or path not in index.repo_file_set:
                continue
            sel = cache.get(path)
            if sel is None:
                sel = index.select([path])
                cache[path] = sel
            if rel not in sel:
                gaps.append((rel, path))
    return gaps


# ---------------------------------------------------------------------------
# `--touch-audit` — this module IS the pytest plugin that measures the run.
#
# Same shape as `programs/suite_write_guard.py`: one file that is both a CLI
# and a plugin, so the measuring code and the code that reasons about the
# measurement cannot drift apart.
# ---------------------------------------------------------------------------

_AUDIT: Dict[str, object] = {"repo": None, "current": None, "map": {},
                             "busy": False, "argv": {}}


def _audit_record(kind: str, raw) -> None:
    if _AUDIT["busy"] or _AUDIT["repo"] is None:
        return
    cur = _AUDIT["current"]
    if not cur:
        return
    _AUDIT["busy"] = True
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        if not isinstance(raw, str) or not raw:
            return
        try:
            p = Path(raw)
            if not p.is_absolute():
                p = Path.cwd() / p
            rel = os.path.relpath(str(p.resolve()), str(_AUDIT["repo"]))
        except (OSError, ValueError):
            return
        if rel.startswith(".."):
            return                      # outside the repo — not our dependency
        rel = rel.replace(os.sep, "/")
        if kind == "argv":
            _AUDIT["argv"].setdefault(cur, set()).add(rel)  # type: ignore[union-attr]
        _AUDIT["map"].setdefault(cur, set()).add(rel)       # type: ignore[union-attr]
    finally:
        _AUDIT["busy"] = False


def _audit_hook(event: str, args) -> None:                  # pragma: no cover
    # Exercised in a SUBPROCESS by the tests (an audit hook cannot be removed
    # once installed, so it is never armed inside the measuring session).
    if event == "open":
        _audit_record("open", args[0])
    elif event in ("subprocess.Popen", "os.exec", "os.posix_spawn"):
        target = args[0]
        _audit_record("argv", target)
        argv = args[1] if len(args) > 1 else None
        if isinstance(argv, (list, tuple)):
            for a in argv:
                _audit_record("argv", a)


def pytest_configure(config) -> None:                       # pragma: no cover
    repo = os.environ.get("LANDING_CORPUS_TOUCH_REPO")
    if not repo:
        return
    _AUDIT["repo"] = Path(repo).resolve()
    sys.addaudithook(_audit_hook)


def pytest_collectstart(collector) -> None:                 # pragma: no cover
    path = getattr(collector, "path", None)
    if path is not None and str(path).endswith(".py"):
        _set_current(path)


def pytest_runtest_protocol(item, nextitem) -> None:        # pragma: no cover
    # `item.path` is ABSOLUTE. `location[0]` — the obvious alternative — is
    # relative to pytest's ROOTDIR, and rootdir is not cwd for the unselectable
    # corpus (a `pytest.ini` sits at the plugin root while the stage runs from
    # the repo root). Resolving that against cwd silently produced a SECOND key
    # space: the first audit of that corpus reported 210 keys for 110 files and
    # every plugin-relative key counted as an unfollowable edge. Absolute
    # in, one key space out.
    path = getattr(item, "path", None)
    if path is not None:
        _set_current(path)


def _set_current(path) -> None:                             # pragma: no cover
    repo = _AUDIT["repo"]
    if repo is None:
        return
    try:
        p = Path(str(path))
        if not p.is_absolute():
            p = Path.cwd() / p
        rel = os.path.relpath(str(p.resolve()), str(repo))
    except (OSError, ValueError):
        return
    if not rel.startswith(".."):
        _AUDIT["current"] = rel.replace(os.sep, "/")


def pytest_sessionfinish(session, exitstatus) -> None:      # pragma: no cover
    out = os.environ.get("LANDING_CORPUS_TOUCH_OUT")
    if not out or _AUDIT["repo"] is None:
        return
    _AUDIT["busy"] = True
    try:
        data = {k: sorted(v) for k, v in _AUDIT["map"].items()}  # type: ignore[union-attr]
        Path(out).write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    finally:
        _AUDIT["busy"] = False


def run_touch_audit(repo: Path, corpus: str, out_json: Path,
                    timeout: int = 1800) -> Tuple[int, str]:
    """Run ``corpus`` under the audit hook and write the observed touch map.

    The pytest command is the one the corresponding stage in
    `tools/gatekeeper-land.sh` issues — same cwd (the REPO ROOT, which
    `tools/phase1_engine/gap_detect.py` makes load-bearing), same autoload pin,
    same timeout — because a measurement of a DIFFERENT session would describe
    a different dependency set.

    `PYTHONDONTWRITEBYTECODE=1` is set for BOTH corpora, where the gate sets it
    only for the unselectable one. It is the one deliberate difference and it
    can only SHRINK what is observed (bytecode writes into the shipped tree are
    the thing that token exists to stop, and they are this program's own
    artefacts, never the subject's dependencies).
    """
    files = corpus_files(repo, corpus)
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["LANDING_CORPUS_TOUCH_REPO"] = str(repo)
    env["LANDING_CORPUS_TOUCH_OUT"] = str(out_json)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(Path(__file__).resolve().parent), env.get("PYTHONPATH", "")])
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "pytest_timeout",
           "-p", "landing_corpus_change_select", "-p", "no:cacheprovider",
           "--timeout=180", "--timeout-method=thread", *files]
    r = subprocess.run(cmd, cwd=str(repo), env=env, capture_output=True,
                       text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _changed_paths(repo: Path, base: str) -> List[str]:
    got = S._git_changed_files(base, repo)
    if got is None:
        raise NotDetermined(f"git diff unavailable for base={base!r}")
    return got


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=None, help="repository root")
    ap.add_argument("--corpus", choices=CORPORA, required=True)
    ap.add_argument("--base", default=None,
                    help="select the corpus files at risk from <base>..worktree")
    ap.add_argument("--changed", action="append", default=[],
                    help="an explicit changed path (repeatable); "
                         "mutually exclusive with --base")
    ap.add_argument("--list-corpus", action="store_true",
                    help="print the corpus and exit")
    ap.add_argument("--touch-audit", metavar="OUT",
                    help="run the corpus under the audit hook, writing the "
                         "observed per-file touch map to OUT")
    ap.add_argument("--prove-closure", metavar="TOUCHMAP",
                    help="rc=1 unless every observed (file, path) edge is one "
                         "the mechanism can follow")
    ap.add_argument("--json", metavar="OUT", help="write the report as JSON")
    args = ap.parse_args(list(argv) if argv is not None else None)

    repo = Path(args.repo).resolve() if args.repo else U.repo_root()
    if repo is None or not (repo / ".git").exists():
        print("NOT DETERMINED: no enclosing git repository — this is a refusal "
              "to measure, not an empty selection.", file=sys.stderr)
        return 2

    try:
        if args.touch_audit:
            rc, out = run_touch_audit(repo, args.corpus, Path(args.touch_audit))
            print(out.strip()[-2000:])
            print(f"[touch-audit] pytest rc={rc}; map -> {args.touch_audit}")
            return 0

        index = CorpusIndex(repo, args.corpus)

        if args.list_corpus:
            for rel in index.files:
                print(rel)
            return 0

        if args.prove_closure:
            touched = json.loads(Path(args.prove_closure).read_text())
            gaps = closure_gaps(index, touched)
            observed = sum(len(set(v)) for v in touched.values())
            print(f"corpus {args.corpus}: {len(index.files)} file(s); "
                  f"{len(touched)} file(s) observed touching {observed} "
                  f"repo path(s)")
            if not gaps:
                print("  NOT PROVEN COMPLETE — no unfollowable edge was "
                      "OBSERVED on this run. A run sees a lower bound on each "
                      "file's dependency set, so this is not a completeness "
                      "proof and must not be read as one.")
                return 0
            by_file: Dict[str, List[str]] = {}
            for rel, path in gaps:
                by_file.setdefault(rel, []).append(path)
            print(f"  PROVEN INCOMPLETE — {len(gaps)} executed edge(s) across "
                  f"{len(by_file)} of {len(index.files)} corpus file(s) are "
                  f"invisible to the selection mechanism.")
            for rel in sorted(by_file):
                print(f"    {rel}")
                for path in sorted(by_file[rel])[:6]:
                    print(f"        <- {path}")
                extra = len(by_file[rel]) - 6
                if extra > 0:
                    print(f"        <- … {extra} more")
            print("  THIS CORPUS MUST NOT BE MADE SKIPPABLE: a change to any "
                  "path above flips a verdict that no selection would have "
                  "run.")
            if args.json:
                Path(args.json).write_text(json.dumps(
                    {"corpus": args.corpus, "files": len(index.files),
                     "gaps": [list(g) for g in gaps]},
                    indent=1, sort_keys=True) + "\n")
            return 1

        if args.base and args.changed:
            print("NOT DETERMINED: --base and --changed are mutually "
                  "exclusive.", file=sys.stderr)
            return 2
        changed = (_changed_paths(repo, args.base) if args.base
                   else list(args.changed))
        selected = sorted(index.select(changed))
        for rel in selected:
            print(rel)
        print(f"[landing_corpus_change_select] corpus={args.corpus} "
              f"{len(selected)}/{len(index.files)} file(s) at risk from "
              f"{len(changed)} changed path(s). REPORT ONLY — the stage that "
              f"runs this corpus is unconditional and stays that way until "
              f"--prove-closure stops refusing.", file=sys.stderr)
        if args.json:
            Path(args.json).write_text(json.dumps(
                {"corpus": args.corpus, "changed": list(changed),
                 "selected": selected, "corpus_size": len(index.files)},
                indent=1, sort_keys=True) + "\n")
        return 0
    except NotDetermined as exc:
        print(f"NOT DETERMINED: {exc} — this is a refusal to measure, not an "
              f"empty selection.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
