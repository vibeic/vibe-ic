#!/usr/bin/env python3
"""full_suite_run_check.py — is the invocation the FULL suite, or a subset?

THE QUESTION IS ASKED OF THE POPULATION, NOT OF A NAME
======================================================
An invocation is FULL when the set of directories it actually runs covers
every test file this plugin has. Both halves of that sentence are DERIVED:

  the population   `git ls-files`, filtered by pytest's OWN collection
                   patterns, minus the trees `landing_unselectable_pytest_
                   corpus._EXCLUDED` declares out WITH their reason. That
                   derivation has been the population question's single
                   answer since v1.13.80 and this program imports it rather
                   than writing a second one — a second definition of "the
                   corpus" drifts, and the direction it drifts in is a tree
                   nothing checks.

  the coverage     for a pytest command, its positional paths (or, with no
                   positional path, `pytest.ini`'s `testpaths`); for a shell
                   runner, the tier list THE RUNNER ITSELF PRINTS.

FULL  iff  no population file lies outside the covered directories.

WHY NOT JUST RECOGNISE `run_tests.sh`
=====================================
Because a check that recognises a FILENAME stays green when someone edits
that file to quietly drop a tree — and dropping a tree is exactly the
failure this gate is for. `run_tests.sh` already answers `--list-tiers` from
the same `TEST_DIRS` array its pytest invocation consumes, so this program
ASKS it and then checks the answer against the population. A runner mutated
to stop discovering `mcp-eda/test` prints one tier fewer, 48 population
files fall outside the covered set, and the invocation is classified SUBSET
naming the tree that went missing. The name of the script is nowhere in the
acceptance condition; a script is interrogated because it resolves inside
the plugin and answers `--list-tiers` with real directories, not because of
what it is called.

WHAT THIS FIXES (the owner-level ruling of 2026-08-31)
======================================================
1. `run_tests.sh` IS a full-suite invocation. It is the only command that
   executes all five test trees. Before this change the program contained
   ZERO occurrences of `run_tests` and reported

       [FAIL] full_suite_run_check: NO pytest invocation found — the suite
              was never run.

   for it. At cadence FULL that is a hard FAIL, so the agent that ran
   everything was told it ran nothing, and the cheapest way to clear the red
   was to run a SUBSET. A gate wrong in this direction does not merely fail
   to catch the shortcut — it recommends it.

2. `programs/tests/` ALONE STOPS COUNTING AS FULL. One tree cannot speak for
   five. MEASURED at e37d10e1e: `programs/tests` leaves 141 tracked test
   files uncovered — `skills/` 82, `mcp-eda/test` 48,
   `tools/phase1_engine/tests` 8, `_shared` 3 — while the 74 tiers
   `run_tests.sh --list-tiers` prints leave 0. This is not special-cased in
   either direction; it is the same subtraction, and it reverses itself
   automatically the day those trees are folded into one.

   This RETIRES `test_only_programs_tests_is_full_since_the_v0219_merge` and
   the live `_integration_tree_has_tests()` probe it rested on. That decision
   was correct for the TWO-TREE world it was made in (top-level `tests/`
   versus `programs/tests`, both collecting 19504). What outran it is that
   three further trees were recognised later — `tools/phase1_engine/tests`
   (#1391), `mcp-eda/test` (#1420) and `skills/*/tests` — and a fourth,
   `_shared`, at v1.13.80. The empty-`tests/` probe is subsumed: an empty
   tree contributes no population file, so it cannot be missing from any
   coverage set.

REFUSAL IS NOT FAILURE
======================
If the population cannot be derived (no git, `git ls-files` fails, an empty
repository) this program exits 2 — NOT DETERMINED. It is never turned into a
PASS, and never into a FAIL either: "I could not look" must not reach a
reader as either "I looked and it was fine" or "I looked and it was broken".

Usage
-----
    python3 full_suite_run_check.py --command "./run_tests.sh"
    python3 full_suite_run_check.py <command_log.txt> [--json <out>]

Exit codes
----------
    0   PASS — at least one full-suite invocation found.
    1   FAIL — an invocation was found but it is a SUBSET, OR no test
            invocation was found at all (the suite was never run).
    2   argument / I/O error, or the population could not be derived.

Missing file -> rc 2. Empty input -> rc 1 (the suite demonstrably was NOT
run; that is an honest FAIL, never a vacuous PASS).

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_PROGRAMS = Path(__file__).resolve().parent
_PLUGIN_DEFAULT = _PROGRAMS.parent

# Subset-selector flags: their presence narrows the run to a fraction of
# whatever directories are named, so no coverage set can rescue them.
_SUBSET_FLAGS = ("-k", "-m")

#: How long a runner gets to answer `--list-tiers`. It is a discovery print,
#: not a test run: measured 0.009 s at e37d10e1e. A script that takes longer
#: than this to list its tiers is not answering the question.
_LIST_TIERS_TIMEOUT = 30
#: Supervision cadence for the listing call above. The default 30 s poll would
#: be the whole budget, so the ceiling could only ever fire once; 1 s makes the
#: deadline mean what it says on a call expected to answer in well under it.
_LIST_TIERS_POLL = 1

#: The flag a runner must answer to be treated as a source of coverage.
_LIST_TIERS_FLAG = "--list-tiers"


#: Memoised: `_load_sibling` re-executes the module on every call, and
#: `runner_tiers` is asked about every candidate command in a commands file.
_WATCHDOG = None


def _watchdog():
    """The supervision primitive, loaded the same way every other sibling is.

    A bare `import _watchdog` works when this file is run as a script and dies
    under `spec_from_file_location`, which is how the gates load it.
    """
    global _WATCHDOG
    if _WATCHDOG is None:
        _WATCHDOG = _load_sibling("_watchdog")
    return _WATCHDOG


def _load_sibling(name: str):
    """Import a sibling program by path, however this file was invoked."""
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


@dataclass
class Invocation:
    line_no: int
    command: str
    is_pytest: bool
    full_suite: bool
    reason: str


@dataclass
class Report:
    passed: bool
    pytest_invocations: int
    full_suite_found: bool
    #: None == the population was derived. A string == NOT DETERMINED, and the
    #: string is why. `passed` is False either way; rc 2 is what separates them.
    undetermined: Optional[str] = None
    population: int = 0
    invocations: List[Invocation] = field(default_factory=list)


# --------------------------------------------------------------------------
# THE POPULATION — imported, never re-derived.
# --------------------------------------------------------------------------
def population(root: Optional[Path] = None) -> Optional[List[str]]:
    """Every tracked test file this plugin owns, plugin-relative, sorted.

    None is a REFUSAL (rc 2), never an empty list. A population of zero and a
    population that could not be read are the same shape to a caller that
    subtracts, and only one of them means the suite is complete.

    The derivation is `landing_unselectable_pytest_corpus`'s — `git ls-files`
    filtered by pytest's own `python_files` patterns, with that program's
    DECLARED exclusions (each carrying its reason) subtracted. Importing it is
    the point: the corpus this gate judges coverage against and the corpus the
    landing enumerates as unreachable must be the same corpus, or a landing
    could run one and be certified against the other.
    """
    plugin = (root or _PLUGIN_DEFAULT).resolve()
    try:
        lu = _load_sibling("landing_unselectable_pytest_corpus")
    except Exception as e:                                  # pragma: no cover
        return None
    repo = lu.repo_root(start=plugin / "programs" / "x.py")
    if repo is None:
        return None
    tracked = lu.tracked_test_files(repo)
    if tracked is None:
        return None
    try:
        prefix = plugin.relative_to(repo).as_posix() + "/"
    except ValueError:                                      # pragma: no cover
        prefix = lu.plugin_rel(repo) + "/"
    # The declared exclusions are spelled repo-relative against that program's
    # own `_PLUGIN_REL`. Re-express them PLUGIN-relative before matching, so a
    # plugin that sits at a different path in the repo (the flattened install
    # cache, a worktree) does not silently stop excluding anything — a missed
    # exclusion inflates the population and reddens a run that IS complete.
    stem = lu._PLUGIN_REL.rstrip("/") + "/"
    excluded = tuple(e.prefix[len(stem):] if e.prefix.startswith(stem)
                     else e.prefix for e in lu._EXCLUDED)
    out = []
    for rel in tracked:
        if not rel.startswith(prefix):
            continue                      # repo-root trees are not this plugin's
        local = rel[len(prefix):]
        if any(local.startswith(x) for x in excluded):
            continue
        out.append(local)
    return sorted(out)


def _uncovered(pop: Sequence[str], dirs: Sequence[str]) -> List[str]:
    """Population files that lie under none of `dirs`."""
    norm = [d.rstrip("/") for d in dirs if d.strip()]
    return [f for f in pop
            if not any(f == d or f.startswith(d + "/") for d in norm)]


def covering_dirs(pop: Sequence[str]) -> List[str]:
    """The minimal TIER directories that cover `pop`, derived from `pop` alone.

    A file's tier is its outermost ancestor directory named `tests`/`test`, and
    its top-level component when it has none (`_shared/test_skill_runner.py`).
    MEASURED at e37d10e1e this reproduces exactly the 74 tiers
    `run_tests.sh --list-tiers` prints — which is the point: a caller that needs
    to NAME the full suite in a command string gets the same set the runner
    discovers, without a second roster and without shelling out to the runner.
    """
    tiers = set()
    for f in pop:
        parts = f.split("/")
        for i, part in enumerate(parts[:-1]):
            if part in ("tests", "test"):
                tiers.add("/".join(parts[:i + 1]))
                break
        else:
            tiers.add(parts[0])
    return sorted(tiers)


def _name_missing_trees(uncovered: Sequence[str]) -> List[str]:
    """Name the MISSING TREES, not 141 individual files.

    Grouped by top-level component and collapsed to that group's longest
    common directory prefix, so `mcp-eda/test` and `tools/phase1_engine/tests`
    are reported at the depth they actually exist at rather than as `mcp-eda`
    and `tools`.
    """
    groups: Dict[str, List[str]] = {}
    for f in uncovered:
        groups.setdefault(f.split("/")[0], []).append(f)
    names = []
    for top, files in sorted(groups.items()):
        parts = [f.split("/")[:-1] for f in files]
        common = parts[0]
        for p in parts[1:]:
            keep = 0
            for a, b in zip(common, p):
                if a != b:
                    break
                keep += 1
            common = common[:keep]
        names.append(("/".join(common) or top) + f" ({len(files)} file(s))")
    return names


# --------------------------------------------------------------------------
# COVERAGE — what a given command actually runs.
# --------------------------------------------------------------------------
def _pytest_verb_index(tokens: List[str]) -> int:
    """Index of the `pytest` verb token. For `python -m pytest`, this is the
    `pytest` token AFTER the `-m`, so the module-flag `-m` is never confused
    with pytest's own `-m` marker selector. Returns -1 if not found."""
    for i, t in enumerate(tokens):
        if t == "pytest" or t.endswith("/pytest"):
            return i
        if t == "-m" and i + 1 < len(tokens) and tokens[i + 1] == "pytest":
            return i + 1
    return -1


def _looks_like_pytest(tokens: List[str]) -> bool:
    joined = " ".join(tokens)
    if re.search(r"(^|\s|/)pytest(\s|$)", joined):
        return True
    if re.search(r"\bpython[0-9.]*\b\s+-m\s+pytest\b", joined):
        return True
    return False


def testpaths(root: Optional[Path] = None) -> List[str]:
    """`pytest.ini`'s `testpaths` — what a bare `pytest` actually runs.

    Read from the file rather than assumed. A bare `pytest` used to be granted
    FULL unconditionally with the reason "pytest.ini testpaths runs both
    trees"; `pytest.ini` has declared ONE testpath since v1.0.0 and
    `single_testpath_guard.py` pins it there on purpose, so that reason was
    describing a config that does not exist. Reading the key means the verdict
    follows the config in whichever direction it moves.
    """
    ini = (root or _PLUGIN_DEFAULT) / "pytest.ini"
    try:
        text = ini.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#") or "=" not in s:
            continue
        key, _, val = s.partition("=")
        if key.strip() == "testpaths":
            return [p.rstrip("/") for p in val.split() if p.strip()]
    return []


def runner_tiers(script: Path) -> Optional[List[str]]:
    """Ask a shell runner which directories it runs. None == it is not one.

    A candidate is interrogated because of what it ANSWERS, never because of
    what it is named:

      * it must resolve to a file inside the plugin;
      * `--list-tiers` must exit 0 within the timeout;
      * every line it prints must be an existing directory in the plugin;
      * it must print at least two of them.

    A hygiene script, a benchmark driver or an invented `some_other_script.sh`
    fails one of those and contributes NO coverage — so it is a subset, which
    is the honest verdict for a command that is not a test runner at all.
    """
    if not script.is_file():
        return None
    plugin = script.parent
    # THE PRECONDITION IS STATIC, AND IT IS NOT A NAME CHECK. Spawning a script
    # because a command string mentioned it is a side effect a VERIFICATION
    # program has no business causing: eleven `.sh` files ship inside this
    # plugin and `hooks/post_install.sh` is one of them. So a candidate must
    # DECLARE the protocol in its own text before it is run. A `run_tests.sh`
    # mutated to drop a tree still declares it — the cheat arm is untouched —
    # and a script that does not implement it is never executed and reads as a
    # subset, which is the safe direction and also the true one.
    try:
        if _LIST_TIERS_FLAG not in script.read_text(encoding="utf-8", errors="replace"):
            return None
    except OSError:                                         # pragma: no cover
        return None
    # SUPERVISED. The script is chosen at RUNTIME, so what it launches cannot be
    # read from here — which is exactly `loop_watchdog_compliance_check`'s class
    # (c): an opaque runner whose contents no AST pass can inspect. The rule it
    # enforces is that such a launch goes through the one supervision primitive
    # this tree has, so its discipline is the same as every other sub-process's
    # and its outcome is a VALUE rather than an exception thrown past a child.
    #
    # Two numbers are set rather than defaulted. The hard ceiling is the SAME
    # number the timeout was, so nothing about the deadline changes; the stall
    # grace is set to it as well, because the 30-minute default would let a
    # silent listing sit for the whole grace before the ceiling could fire.
    # MEASURED, not assumed: neither this call nor the timeout-bounded
    # `subprocess` launch it replaces kills a process GROUP
    # (`_watchdog._default_kill` is `proc.kill()`), so a script that backgrounds
    # work still orphans it. The gain here is the discipline and the structured outcome,
    # and claiming more than that would be claiming something unmeasured.
    proc = _watchdog().run_supervised(
        ["bash", str(script), _LIST_TIERS_FLAG],
        cwd=str(plugin), merge_stderr=False, output_progress=True,
        stall_grace_s=_LIST_TIERS_TIMEOUT,
        hard_ceiling_s=_LIST_TIERS_TIMEOUT,
        poll_s=_LIST_TIERS_POLL,
    )
    # Every non-zero outcome — a natural failure, a launch error (rc 127), a
    # stall kill (199) and the ceiling kill (124) — reads the same here as it
    # did before: this candidate is not a runner. That is the safe direction and
    # also the true one.
    if proc.rc != 0:
        return None
    lines = [ln.strip() for ln in proc.out.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    if not all((plugin / ln).is_dir() for ln in lines):
        return None
    return lines


def _script_candidates(tokens: List[str], plugin: Path) -> List[Path]:
    """Tokens that could be a runner living inside the plugin.

    Path-shaped, `.sh`-suffixed, and resolving inside the plugin — that is the
    whole filter. It selects an INTERROGATION TARGET; the verdict still comes
    from what the script prints.
    """
    out = []
    for t in tokens:
        if t.startswith("-") or not t.endswith(".sh"):
            continue
        p = Path(t)
        cand = p if p.is_absolute() else (plugin / t)
        try:
            cand = cand.resolve()
        except OSError:                                     # pragma: no cover
            continue
        try:
            cand.relative_to(plugin.resolve())
        except ValueError:
            continue
        out.append(cand)
    return out


def _classify_pytest(tokens: List[str],
                     pop: Sequence[str],
                     root: Optional[Path] = None) -> Tuple[bool, str]:
    """(full_suite, reason) for a pytest command. Only tokens AFTER the verb."""
    verb_idx = _pytest_verb_index(tokens)
    args = tokens[verb_idx + 1:] if verb_idx >= 0 else tokens

    for t in args:
        if t in _SUBSET_FLAGS:
            return False, f"subset selector '{t}' narrows the run"
        if t.startswith("-k=") or t.startswith("-m="):
            return False, f"subset selector '{t.split('=')[0]}' narrows the run"

    value_flags = {"-p", "-c", "-o", "--rootdir", "--import-mode"}
    paths: List[str] = []
    skip_next = False
    for t in args:
        if skip_next:
            skip_next = False
            continue
        if t.startswith("--import-mode") and "=" in t:
            continue
        if t in value_flags:
            skip_next = True
            continue
        if t.startswith("-"):
            continue
        paths.append(t.rstrip("/"))

    # A single test FILE is a subset even when it lives under a covered tree.
    if any(p.endswith(".py") for p in paths):
        return False, f"single-file / file-level path(s) {sorted(set(paths))} are a subset"

    if paths:
        dirs, how = sorted(set(paths)), "explicit path(s)"
    else:
        dirs = testpaths(root)
        how = "pytest.ini testpaths"
        if not dirs:
            return False, ("no positional path and pytest.ini declares no "
                           "testpaths — nothing is selected")

    missing = _uncovered(pop, dirs)
    if not missing:
        return True, (f"{how} {dirs} cover all {len(pop)} tracked test file(s)")
    return False, (f"subset — {how} {dirs} leave {len(missing)} of {len(pop)} "
                   f"tracked test file(s) unrun; missing tree(s): "
                   f"{_name_missing_trees(missing)}")


def _classify_runner(script: Path,
                     pop: Sequence[str]) -> Optional[Tuple[bool, str]]:
    """(full_suite, reason) for a shell runner, or None if it is not one."""
    tiers = runner_tiers(script)
    if tiers is None:
        return None
    missing = _uncovered(pop, tiers)
    name = script.name
    if not missing:
        return True, (f"{name} --list-tiers reports {len(tiers)} tier(s) "
                      f"covering all {len(pop)} tracked test file(s)")
    return False, (f"subset — {name} --list-tiers reports {len(tiers)} tier(s), "
                   f"leaving {len(missing)} of {len(pop)} tracked test file(s) "
                   f"unrun; missing tree(s): {_name_missing_trees(missing)}")


# --------------------------------------------------------------------------
def scan_commands(commands: List[str],
                  root: Optional[Path] = None) -> Report:
    pop = population(root)
    if pop is None:
        return Report(passed=False, pytest_invocations=0, full_suite_found=False,
                      undetermined="the tracked test corpus could not be derived "
                                   "from git — NOT DETERMINED, which is neither "
                                   "a pass nor a fail")
    plugin = (root or _PLUGIN_DEFAULT).resolve()
    invocations: List[Invocation] = []
    full_found = False
    n_invocations = 0
    for idx, raw in enumerate(commands, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for seg in re.split(r"&&|;", line):
            seg = seg.strip()
            if not seg:
                continue
            try:
                tokens = shlex.split(seg)
            except ValueError:
                tokens = seg.split()

            verdict: Optional[Tuple[bool, str]] = None
            if _looks_like_pytest(tokens):
                verdict = _classify_pytest(tokens, pop, root)
            else:
                # Not a pytest command line. It may still BE the suite: a
                # runner that execs pytest over every tier is a full-suite
                # invocation and reporting "the suite was never run" for it is
                # the defect this program was rewritten to remove.
                for cand in _script_candidates(tokens, plugin):
                    verdict = _classify_runner(cand, pop)
                    if verdict is not None:
                        break
            if verdict is None:
                continue
            n_invocations += 1
            full, reason = verdict
            full_found = full_found or full
            invocations.append(Invocation(
                line_no=idx, command=seg, is_pytest=True,
                full_suite=full, reason=reason))
    return Report(
        passed=full_found,
        pytest_invocations=n_invocations,
        full_suite_found=full_found,
        undetermined=None,
        population=len(pop),
        invocations=invocations,
    )


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        description="Classify a test invocation as the FULL suite or a SUBSET, "
                    "by covering the git-derived population (chip-AGNOSTIC).")
    p.add_argument("commands_file", nargs="?", default=None,
                   help="File of shell commands, one per line.")
    p.add_argument("--command", default=None,
                   help="A single command string to scan.")
    p.add_argument("--plugin-root", default=None,
                   help="Plugin root to judge against (default: this file's).")
    p.add_argument("--json", default=None, help="Write JSON report to this path.")
    args = p.parse_args(argv)

    if args.command is not None:
        commands = [args.command]
    elif args.commands_file is not None:
        fp = Path(args.commands_file)
        if not fp.is_file():
            print(f"ERROR: commands file not found: {fp}", file=sys.stderr)
            return 2
        try:
            commands = fp.read_text(encoding="utf-8").splitlines()
        except OSError as e:
            print(f"ERROR: cannot read {fp}: {e}", file=sys.stderr)
            return 2
    else:
        print("ERROR: provide a commands file or --command", file=sys.stderr)
        return 2

    root = Path(args.plugin_root).resolve() if args.plugin_root else None
    report = scan_commands(commands, root=root)
    report_json = json.dumps(asdict(report), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json + "\n", encoding="utf-8")

    if report.undetermined:
        print(f"NOT DETERMINED: full_suite_run_check: {report.undetermined}",
              file=sys.stderr)
        return 2

    if report.full_suite_found:
        print(f"[PASS] full_suite_run_check: full-suite invocation found "
              f"(covers all {report.population} tracked test file(s); "
              f"{report.pytest_invocations} invocation(s) seen).")
        for inv in report.invocations:
            if inv.full_suite:
                print(f"  line {inv.line_no} [OK] {inv.command}")
                print(f"    -> {inv.reason}")
        return 0

    if report.pytest_invocations == 0:
        print("[FAIL] full_suite_run_check: NO test invocation found — "
              "the suite was never run.")
        return 1

    print("[FAIL] full_suite_run_check: tests were run but only as a SUBSET "
          f"of the {report.population} tracked test file(s):")
    for inv in report.invocations:
        flag = "OK" if inv.full_suite else "SUBSET"
        print(f"  line {inv.line_no} [{flag}] {inv.command}")
        print(f"    -> {inv.reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
