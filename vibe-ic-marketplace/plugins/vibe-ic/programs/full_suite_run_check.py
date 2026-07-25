#!/usr/bin/env python3
"""full_suite_run_check.py — full-suite (not subset) pytest gate for the
core-agent loop (extracted from vibe-ic:core-agent-loop §Step 3).

The skill's HARD RULE: before pushing, run the FULL test suite, which is
BOTH test trees:

  * ``programs/tests/``  — unit tests for individual programs.
  * ``tests/``           — the integration/regression GATES (INDEX.md
                           freshness, every-skill-has-compliance,
                           orchestrator branch regressions).

A subset run once let a real regression onto main. ``pytest.ini`` pins
both trees via ``testpaths`` and a comment forbidding a path filter, but
nothing checked that the agent actually invoked pytest *without* a
narrowing path argument.

This program makes that a real deterministic check. It does NOT re-run
pytest (that is the agent's job, and re-running here would be slow and
duplicative); it validates the COMMAND STRING the agent used so a
subset-narrowing invocation FAILs:

  PASS  ``cd $PLUGIN_ROOT && python3 -m pytest -q``     (no path filter)
  PASS  ``pytest``                                       (testpaths drives it)
  PASS  ``python3 -m pytest -q programs/tests tests``    (BOTH trees explicit)
  FAIL  ``python3 -m pytest -q programs/tests/``         (subset — gates skipped)
  FAIL  ``pytest tests/test_compliance.py``              (single file)
  FAIL  ``pytest -k version``                            (-k subset selector)

The check: a pytest invocation is "full suite" iff it supplies EITHER
no positional path argument at all (letting pytest.ini ``testpaths`` run
both trees) OR positional paths that cover BOTH trees. Any narrowing
selector (``-k`` / ``-m`` / a single test file / only one of the two
trees) is a subset and FAILs.

Usage
-----
    python3 full_suite_run_check.py --command "python3 -m pytest -q"
    python3 full_suite_run_check.py <command_log.txt> [--json <out>]

Exit codes
----------
    0   PASS — at least one full-suite pytest invocation found.
    1   FAIL — a pytest invocation was found but it is a SUBSET, OR no
            pytest invocation was found at all (the suite was never run).
    2   argument / I/O error.

Missing file -> rc 2. Empty input -> rc 1 (the suite demonstrably was NOT
run; that is an honest FAIL, never a vacuous PASS).

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


# The two canonical trees that together constitute the full suite.
_TREE_PROGRAMS = "programs/tests"
_TREE_INTEGRATION = "tests"

# Subset-selector flags: their presence narrows the run to a fraction.
_SUBSET_FLAGS = ("-k", "-m")


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
    invocations: List[Invocation] = field(default_factory=list)


def _norm_path(tok: str) -> str:
    """Strip trailing slash so 'programs/tests/' == 'programs/tests'."""
    return tok.rstrip("/")


def _integration_tree_has_tests(root: Optional[Path] = None) -> bool:
    """Does the legacy integration tree still contain any test files?

    Checked live rather than hardcoded, so this gate self-corrects in both
    directions: today the tree is empty (v0.2.19 merged it into
    programs/tests) and an explicit programs/tests run is the full suite;
    the day someone adds a test back under tests/, this returns True and the
    two-tree requirement is enforced again automatically.
    """
    base = root if root is not None else Path(__file__).resolve().parents[1]
    tree = base / _TREE_INTEGRATION
    if not tree.is_dir():
        return False
    return any(tree.glob("test_*.py")) or any(tree.glob("**/test_*.py"))


def _pytest_verb_index(tokens: List[str]) -> int:
    """Index of the `pytest` verb token. For `python -m pytest`, this is the
    `pytest` token AFTER the `-m`, so the module-flag `-m` is never confused
    with pytest's own `-m` marker selector. Returns -1 if not found."""
    for i, t in enumerate(tokens):
        if t == "pytest" or t.endswith("/pytest"):
            return i
        # `python -m pytest`: the verb is the token after `-m` if it's pytest.
        if t == "-m" and i + 1 < len(tokens) and tokens[i + 1] == "pytest":
            return i + 1
    return -1


def _classify_pytest(tokens: List[str]) -> (bool, str):
    """Given the token list of a single pytest command, return
    (full_suite, reason). Only tokens AFTER the pytest verb are args."""
    verb_idx = _pytest_verb_index(tokens)
    args = tokens[verb_idx + 1:] if verb_idx >= 0 else tokens

    # 1. subset selector flags always narrow — but only as pytest ARGS.
    for t in args:
        if t in _SUBSET_FLAGS:
            return False, f"subset selector '{t}' narrows the run"
        if t.startswith("-k=") or t.startswith("-m="):
            return False, f"subset selector '{t.split('=')[0]}' narrows the run"

    # 2. collect positional (non-flag, non-flag-value) path arguments.
    #    -q is store_true; -p / -c / -o / --rootdir / --import-mode take values.
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
        paths.append(_norm_path(t))

    if not paths:
        # No positional path -> pytest.ini testpaths runs the full set.
        return True, "no path filter (pytest.ini testpaths runs both trees)"

    norm = set(paths)
    covers_programs = any(
        p == _TREE_PROGRAMS or p.startswith(_TREE_PROGRAMS + "/")
        for p in norm
    )
    covers_integration = any(
        p == _TREE_INTEGRATION or p.startswith(_TREE_INTEGRATION + "/")
        for p in norm
    )
    # A single test FILE under a tree (path with a '.py') is a subset even
    # if it lives under one of the trees.
    has_file = any(p.endswith(".py") for p in norm)
    if has_file:
        return False, f"single-file / file-level path(s) {sorted(norm)} are a subset"

    if covers_programs and covers_integration:
        return True, f"both trees covered explicitly: {sorted(norm)}"
    # v0.2.19 merged the two test trees: conftest.py records "the two former
    # test trees were merged" and pytest.ini's testpaths is programs/tests
    # alone. When the integration tree holds NO test files, an explicit
    # `programs/tests` path IS the full suite — measured on this tree:
    # `pytest -q --collect-only` and `pytest programs/tests -q --collect-only`
    # both collect 19504. This is detected DYNAMICALLY, not assumed: if the
    # integration tree ever grows test files again, the two-tree requirement
    # reinstates itself without anyone editing this gate.
    if covers_programs and not covers_integration             and not _integration_tree_has_tests():
        return True, ("programs/tests covers the full suite — the integration "
                      "tree holds no test files (merged in v0.2.19)")
    missing = []
    if not covers_programs:
        missing.append(_TREE_PROGRAMS)
    if not covers_integration:
        missing.append(_TREE_INTEGRATION)
    return False, f"subset — missing tree(s): {missing} (only {sorted(norm)})"


def _looks_like_pytest(tokens: List[str]) -> bool:
    joined = " ".join(tokens)
    # `pytest ...` OR `python -m pytest ...` OR `python3 -m pytest`.
    if re.search(r"(^|\s|/)pytest(\s|$)", joined):
        return True
    if re.search(r"\bpython[0-9.]*\b\s+-m\s+pytest\b", joined):
        return True
    return False


def scan_commands(commands: List[str]) -> Report:
    invocations: List[Invocation] = []
    full_found = False
    n_pytest = 0
    for idx, raw in enumerate(commands, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # A command line may chain with && ; split and inspect each segment.
        segments = re.split(r"&&|;", line)
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            try:
                tokens = shlex.split(seg)
            except ValueError:
                tokens = seg.split()
            if not _looks_like_pytest(tokens):
                continue
            n_pytest += 1
            full, reason = _classify_pytest(tokens)
            if full:
                full_found = True
            invocations.append(Invocation(
                line_no=idx, command=seg, is_pytest=True,
                full_suite=full, reason=reason))
    return Report(
        passed=full_found,
        pytest_invocations=n_pytest,
        full_suite_found=full_found,
        invocations=invocations,
    )


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        description="Verify a full-suite (both-trees) pytest run was issued "
                    "by the core-agent before push (chip-AGNOSTIC).")
    p.add_argument("commands_file", nargs="?", default=None,
                   help="File of shell commands, one per line.")
    p.add_argument("--command", default=None,
                   help="A single command string to scan.")
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

    report = scan_commands(commands)
    report_json = json.dumps(asdict(report), indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json + "\n", encoding="utf-8")

    if report.full_suite_found:
        print(f"[PASS] full_suite_run_check: full-suite pytest invocation "
              f"found ({report.pytest_invocations} pytest command(s) seen).")
        return 0

    if report.pytest_invocations == 0:
        print("[FAIL] full_suite_run_check: NO pytest invocation found — "
              "the suite was never run.")
        return 1

    print("[FAIL] full_suite_run_check: pytest was run but only as a SUBSET "
          "(the integration/regression gates were skipped):")
    for inv in report.invocations:
        flag = "OK" if inv.full_suite else "SUBSET"
        print(f"  line {inv.line_no} [{flag}] {inv.command}")
        print(f"    -> {inv.reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
