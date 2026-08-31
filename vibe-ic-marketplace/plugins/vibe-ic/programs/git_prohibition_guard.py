#!/usr/bin/env python3
"""git_prohibition_guard.py — deterministic guard for the core-agent loop
(extracted from vibe-ic:core-agent-loop §Hard prohibitions).

The core-agent loop has a non-negotiable deny-list of destructive git
operations that must NEVER appear in the commands it runs:

  1. `git push --force` / `git push -f`     — loses upstream history.
  2. `git reset --hard`                      — loses local work.
  3. `git commit --no-verify`                — bypasses pre-commit gates
                                               that catch chip-specific
                                               literals.
  4. `git checkout .` / `git checkout --`    — discards work-in-progress.

NOTE — `gh issue close` is NOT forbidden. Under the core<->field backlog
state machine, the core-agent CLOSES an issue after it self-verifies
(reproduce + full plugin test suite the CI way), bumps the version, pushes,
and posts the 5-section 繁中 comment with `core-closed`. The field-agent is
the audit/reopen safety net (`gh issue reopen` when a closed issue is found
inadequate on the real benchmark). Neither `gh issue close` nor
`gh issue reopen` is flagged by this guard.

The skill stated these as English prose "NEVER do X". This program makes
them a real, deterministic pre-commit / pre-run gate: feed it the command
string(s) the agent is about to execute (one per line, or via --command),
and it FAILs (rc=1) if any forbidden pattern is present.

The check is structural — it normalises whitespace and matches on
word-bounded git/gh sub-command + flag combinations so that e.g.
`git   push    --force-with-lease`-style false positives are NOT raised
(``--force-with-lease`` is a distinct, safe flag and is explicitly allowed),
while `git push --force` IS caught.

Usage
-----
    # scan a single command string
    python3 git_prohibition_guard.py --command "git push --force origin main"

    # scan a file of commands (one per line; blanks / # comments ignored)
    python3 git_prohibition_guard.py <commands.txt> [--json <out>]

Exit codes
----------
    0   PASS — no forbidden git/gh operation found.
    1   FAIL — ≥1 forbidden operation found (listed in the report).
    2   argument / I/O error.

A missing file or empty/garbage input is an HONEST error/empty result:
  - missing file  -> rc 2 (cannot scan)
  - empty input   -> rc 0 with `scanned=0`, but flagged `vacuous=true` in
    the JSON so a caller cannot mistake "nothing to scan" for "verified
    clean N commands".

chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional


# Each rule: (id, human description, compiled regex on the NORMALISED line).
# Normalisation = collapse runs of whitespace to a single space, lowercase.
# Word boundaries / negative look-aheads keep safe siblings from matching.
_RULES = [
    (
        "push_force",
        "git push --force / -f (loses upstream history)",
        # `git push` ... `--force` or `-f`, but NOT `--force-with-lease`.
        re.compile(r"\bgit\b[^\n]*\bpush\b[^\n]*(?:--force(?!-with-lease)\b|(?<![\w-])-f\b)"),
    ),
    (
        "reset_hard",
        "git reset --hard (loses local work)",
        re.compile(r"\bgit\b[^\n]*\breset\b[^\n]*--hard\b"),
    ),
    (
        "commit_no_verify",
        "git commit --no-verify (bypasses pre-commit gates)",
        re.compile(r"\bgit\b[^\n]*\bcommit\b[^\n]*--no-verify\b"),
    ),
    (
        "checkout_discard",
        "git checkout . / -- (discards work-in-progress)",
        # `git checkout` followed by a bare `.` or a `--` path-discard.
        re.compile(r"\bgit\b[^\n]*\bcheckout\b\s+(?:\.\s|\.$|--\s)"),
    ),
]


@dataclass
class Violation:
    rule_id: str
    description: str
    line_no: int
    command: str


@dataclass
class Report:
    passed: bool
    scanned: int
    vacuous: bool
    violations: List[Violation] = field(default_factory=list)


def _normalise(line: str) -> str:
    # A QUOTATION IS NOT AN INVOCATION. Prose that documents a forbidden form
    # inside inline code (`git checkout -- <path>`) is how a fix explains the
    # defect it removed; matching it blocked the very landing that removed the
    # defect (measured 2026-09-01, kflow6-a). Backtick spans are blanked before
    # matching; a real command line carries no backticks around itself.
    line = re.sub(r"`[^`]*`", " ", line)
    return re.sub(r"\s+", " ", line).strip().lower()


def scan_commands(commands: List[str]) -> Report:
    """Scan a list of command strings; return a structured Report."""
    violations: List[Violation] = []
    scanned = 0
    for idx, raw in enumerate(commands, start=1):
        norm = _normalise(raw)
        if not norm or norm.startswith("#"):
            continue
        scanned += 1
        for rule_id, desc, rx in _RULES:
            if rx.search(norm):
                violations.append(
                    Violation(rule_id=rule_id, description=desc,
                              line_no=idx, command=raw.strip())
                )
    return Report(
        passed=(len(violations) == 0),
        scanned=scanned,
        vacuous=(scanned == 0),
        violations=violations,
    )


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(
        description="Guard against forbidden git/gh operations in the "
                    "core-agent loop (chip-AGNOSTIC).")
    p.add_argument("commands_file", nargs="?", default=None,
                   help="File of commands, one per line (# / blanks ignored).")
    p.add_argument("--command", default=None,
                   help="A single command string to scan (instead of a file).")
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
    report_dict = asdict(report)
    report_json = json.dumps(report_dict, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(report_json + "\n", encoding="utf-8")

    if report.violations:
        print("[FAIL] git_prohibition_guard: "
              f"{len(report.violations)} forbidden operation(s):")
        for v in report.violations:
            print(f"  line {v.line_no} [{v.rule_id}] {v.description}")
            print(f"    -> {v.command}")
        return 1

    if report.vacuous:
        # Honest: nothing was scanned. Not a verified-clean result.
        print("[PASS] git_prohibition_guard: no commands scanned (vacuous).")
        return 0

    print(f"[PASS] git_prohibition_guard: {report.scanned} command(s) "
          f"clean — no forbidden git/gh operation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
