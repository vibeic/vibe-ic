#!/usr/bin/env python3
"""
plugin_change_pytest_gate.py -- "Plugin-test hard rule" pre-claim-DONE gate.

For skill: benchmark-verify (final "Plugin-test hard rule")

The rule
--------
If a verification run modified ANY plugin code (a chip-agnostic fix to
`benchmark_verify_report.py`, a checker, a runner, ...), you may NOT claim the
benchmark DONE until you have re-run the FULL pytest suite and it PASSED.
"Full" means BOTH test trees: `programs/tests/` AND `tests/` (per pytest.ini,
the integration/regression gates live in `tests/`). Validating with only
`programs/tests/` misses the gates and does not satisfy the rule.

This program turns that conditional into a mechanical gate:

  1. Detect whether plugin code changed.
       - default: `git diff --name-only` + untracked, under <plugin-root>,
         filtered to *.py (excluding the test files themselves is NOT done —
         a changed test still requires the suite to have run).
       - or pass an explicit `--changed-files f1 f2 ...` list (e.g. from an
         orchestrator that already tracked edits).
  2. If NO plugin code changed -> the gate is INAPPLICABLE -> PASS.
  3. If plugin code changed -> a `--pytest-log` is REQUIRED, and that log must
     attest a clean FULL-suite run:
        - a pytest summary line showing it PASSED (`N passed` with 0 failed /
          0 errors), AND
        - evidence BOTH trees ran: items collected from `programs/tests` AND
          from `tests` (a bare-`pytest` run collects both per testpaths +
          rootdir; we require both path roots to appear).
     Missing log, unreadable log, a failing/erroring summary, or a log that
     only ran `programs/tests/` -> FAIL.

Honest-failure contract
------------------------
  - plugin changed + no/garbage/failing/partial log  -> FAIL (exit 1)
  - plugin changed + clean full-suite log            -> PASS (exit 0)
  - no plugin change                                 -> PASS (exit 0, N/A)
  - cannot determine git state AND no explicit list  -> FAIL (exit 2)
    (never a silent PASS: if we can't prove "no change", we don't excuse it)

Usage:
    python3 plugin_change_pytest_gate.py <plugin_root> \
        [--pytest-log <pytest_output.txt>] \
        [--changed-files f1 f2 ...] [--json <out>]

Exit codes:
    0 = PASS  (no plugin change, OR plugin change + clean full-suite pytest)
    1 = FAIL  (plugin change without a clean full-suite pytest attestation)
    2 = ERROR (cannot determine change state / I/O error)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class Finding:
    rule: str
    severity: str
    message: str
    file: str = ""


@dataclass
class AuditResult:
    program: str = "plugin_change_pytest_gate"
    verdict: str = "FAIL"          # PASS | FAIL | ERROR
    passed: bool = False
    findings: List[Finding] = field(default_factory=list)
    summary: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# pytest log parsing
# ---------------------------------------------------------------------------
# Summary lines like:
#   "==== 1234 passed in 56.78s ===="
#   "==== 1234 passed, 3 warnings in 56.78s ===="
#   "==== 2 failed, 1230 passed in 60s ===="
#   "==== 5 errors in 3s ===="
_PASSED_RE = re.compile(r"\b(\d+)\s+passed\b", re.I)
_FAILED_RE = re.compile(r"\b(\d+)\s+failed\b", re.I)
_ERROR_RE = re.compile(r"\b(\d+)\s+errors?\b", re.I)
# Both-tree evidence: collected items rooted at each tree.
_PROGRAMS_TREE_RE = re.compile(r"programs/tests[/\\]", re.I)
_TESTS_TREE_RE = re.compile(r"(?<![a-z/])tests[/\\]test_", re.I)


def parse_pytest_log(text: str) -> dict:
    """Return {passed:int|None, failed:int, errors:int, programs_tree:bool,
    tests_tree:bool, clean:bool}."""
    passed = None
    m = _PASSED_RE.search(text)
    if m:
        passed = int(m.group(1))
    failed = 0
    for m in _FAILED_RE.finditer(text):
        failed = max(failed, int(m.group(1)))
    errors = 0
    for m in _ERROR_RE.finditer(text):
        errors = max(errors, int(m.group(1)))
    programs_tree = bool(_PROGRAMS_TREE_RE.search(text))
    tests_tree = bool(_TESTS_TREE_RE.search(text))
    clean = (passed is not None and passed > 0
             and failed == 0 and errors == 0)
    return {"passed": passed, "failed": failed, "errors": errors,
            "programs_tree": programs_tree, "tests_tree": tests_tree,
            "clean": clean}


# ---------------------------------------------------------------------------
# Plugin change detection
# ---------------------------------------------------------------------------
def _git_changed_py(plugin_root: Path) -> Optional[List[str]]:
    """Return *.py files changed (modified/untracked) under plugin_root via
    git, or None if git state cannot be determined."""
    if not plugin_root.exists():
        return None
    try:
        # Tracked modifications (working tree + staged) relative to HEAD.
        diff = subprocess.run(
            ["git", "-C", str(plugin_root), "diff", "--name-only", "HEAD"],
            capture_output=True, text=True, timeout=30)
        untr = subprocess.run(
            ["git", "-C", str(plugin_root), "ls-files", "--others",
             "--exclude-standard"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if diff.returncode != 0 and untr.returncode != 0:
        return None
    names = set()
    for line in (diff.stdout + "\n" + untr.stdout).splitlines():
        line = line.strip()
        if line.endswith(".py"):
            names.add(line)
    return sorted(names)


def _is_plugin_code(rel_path: str) -> bool:
    """A *.py under programs/ or _shared/ or tests/ or the plugin root is
    plugin code for the purpose of this rule."""
    p = rel_path.replace("\\", "/")
    return p.endswith(".py")


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------
def audit(plugin_root: Path,
          pytest_log: Optional[Path] = None,
          changed_files: Optional[List[str]] = None) -> AuditResult:
    result = AuditResult()

    # --- Step 1: determine changed plugin code -----------------------------
    if changed_files is not None:
        changed = [f for f in changed_files if _is_plugin_code(f)]
        source = "explicit"
    else:
        git_changed = _git_changed_py(plugin_root)
        if git_changed is None:
            result.verdict = "ERROR"
            result.passed = False
            result.findings.append(Finding(
                rule="CHANGE_STATE_UNKNOWN", severity="ERROR",
                message="Cannot determine plugin change state (no git, or "
                        "not a repo) and no --changed-files given. Refusing "
                        "to excuse a possible change (ERROR, not PASS)."))
            result.summary = {"plugin_root": str(plugin_root)}
            return result
        changed = [f for f in git_changed if _is_plugin_code(f)]
        source = "git"

    # --- Step 2: no plugin change -> gate N/A -> PASS ----------------------
    if not changed:
        result.verdict = "PASS"
        result.passed = True
        result.findings.append(Finding(
            rule="NO_PLUGIN_CHANGE", severity="INFO",
            message="No plugin *.py changed — pytest hard rule inapplicable."))
        result.summary = {"change_source": source, "changed_files": [],
                          "pytest_required": False}
        return result

    # --- Step 3: plugin changed -> full-suite pytest attestation REQUIRED --
    result.summary = {"change_source": source, "changed_files": changed,
                      "pytest_required": True}

    if pytest_log is None:
        result.verdict = "FAIL"
        result.passed = False
        result.findings.append(Finding(
            rule="PYTEST_LOG_REQUIRED", severity="ERROR",
            message=f"{len(changed)} plugin *.py changed but no --pytest-log "
                    "supplied. Re-run the FULL suite (bare `pytest`) first."))
        return result

    if not pytest_log.exists():
        result.verdict = "FAIL"
        result.passed = False
        result.findings.append(Finding(
            rule="PYTEST_LOG_MISSING", severity="ERROR",
            message="Supplied --pytest-log does not exist.",
            file=str(pytest_log)))
        return result

    try:
        text = pytest_log.read_text(errors="replace")
    except OSError:
        result.verdict = "FAIL"
        result.passed = False
        result.findings.append(Finding(
            rule="PYTEST_LOG_UNREADABLE", severity="ERROR",
            message="Supplied --pytest-log could not be read.",
            file=str(pytest_log)))
        return result

    parsed = parse_pytest_log(text)
    result.summary["pytest"] = parsed

    if not parsed["clean"]:
        result.verdict = "FAIL"
        result.passed = False
        reason = []
        if parsed["passed"] is None:
            reason.append("no 'N passed' summary")
        if parsed["failed"]:
            reason.append(f"{parsed['failed']} failed")
        if parsed["errors"]:
            reason.append(f"{parsed['errors']} errors")
        result.findings.append(Finding(
            rule="PYTEST_NOT_CLEAN", severity="ERROR",
            message="pytest log is not a clean pass (" + "; ".join(reason)
                    + ").", file=str(pytest_log)))
        return result

    if not parsed["tests_tree"]:
        # The integration/regression gates in tests/ were not collected.
        result.verdict = "FAIL"
        result.passed = False
        result.findings.append(Finding(
            rule="PYTEST_PARTIAL_SUITE", severity="ERROR",
            message="pytest log shows no items from the top-level `tests/` "
                    "tree — the integration/regression gates did not run. "
                    "Re-run bare `pytest` (collects BOTH trees), not "
                    "`pytest programs/tests/` alone.",
            file=str(pytest_log)))
        return result

    if not parsed["programs_tree"]:
        result.verdict = "FAIL"
        result.passed = False
        result.findings.append(Finding(
            rule="PYTEST_PARTIAL_SUITE", severity="ERROR",
            message="pytest log shows no items from `programs/tests/` — "
                    "the unit suite did not run.",
            file=str(pytest_log)))
        return result

    result.verdict = "PASS"
    result.passed = True
    result.findings.append(Finding(
        rule="PYTEST_FULL_SUITE_CLEAN", severity="INFO",
        message=f"Plugin code changed and the FULL suite passed "
                f"({parsed['passed']} passed, both trees collected)."))
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
_EXIT = {"PASS": 0, "FAIL": 1, "ERROR": 2}


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Plugin-test hard rule: refuse DONE if plugin code "
                    "changed without a clean full-suite pytest")
    parser.add_argument("plugin_root", help="Plugin root directory (git repo)")
    parser.add_argument("--pytest-log", default=None,
                        help="Path to the pytest output to attest a clean run")
    parser.add_argument("--changed-files", nargs="*", default=None,
                        help="Explicit changed-file list (overrides git probe)")
    parser.add_argument("--json", default=None, help="Output JSON report path")
    args = parser.parse_args(argv)

    result = audit(
        Path(args.plugin_root),
        Path(args.pytest_log) if args.pytest_log else None,
        args.changed_files)

    report = asdict(result)
    report_json = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json)

    print(report_json)
    return _EXIT.get(result.verdict, 2)


if __name__ == "__main__":
    sys.exit(main())
