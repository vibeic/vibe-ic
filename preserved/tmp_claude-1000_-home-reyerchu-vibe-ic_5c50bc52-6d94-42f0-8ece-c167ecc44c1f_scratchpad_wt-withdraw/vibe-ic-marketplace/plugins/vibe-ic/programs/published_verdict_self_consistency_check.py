#!/usr/bin/env python3
"""published_verdict_self_consistency_check.py — a run's own top-level verdict
may not contradict its own gate reports.

THE DEFECT, MEASURED (vibe-ic#1028, 2026-08-12)
===============================================
The withdrawal ruling for `benchmark-data/ic/` was originally "withdraw anything
not explicitly PASS", judged by each run root's top-level ``RESULT.md``. That
criterion was measured before it was applied, and it does not hold: ``RESULT.md``
is itself a lying verdict. Every one of the three roots whose ``RESULT.md``
claimed PASS was contradicted by gate reports published UNDER THAT SAME ROOT:

    root                        RESULT.md      its own gate reports carrying
                                declared       ``verdict``/``overall`` == FAIL
    ------------------------------------------------------------------------
    ic/sha256                   PASS      ->   23
    ic/edge_llm_accel           PASS      ->   13
    ic/edge_llm_matmul_accel    PASS      ->    5

``ic/edge_llm_accel``'s headline literally read ``STATUS: COMPLETE`` and
``TESTS PASS`` while ``reports/audit/phase23_completion_audit.json``,
``reports/lec.json`` and ``reports/phase2/gates/ip_integration.json`` each
carried ``"verdict": "FAIL"``. So the count of genuinely-passing IC roots in that
corpus was 0 of 14, not 3 — and nothing in the repo measured the gap.

THE GENERAL DEFECT IS NOT THOSE THREE ROOTS. A hand-written ``RESULT.md`` is
prose; the gate reports beside it are machine output. Nothing forced them to
agree, so a corpus could publish a headline PASS indefinitely over machine
evidence that said otherwise, and a reader had no way to tell. Without this gate
the next corpus repeats it exactly.

WHAT THIS PROGRAM DOES
======================
For every published run root (a directory containing ``RESULT.md``) it asks one
question and only one:

    Does ``RESULT.md`` declare PASS **and** does any published gate report under
    that same root declare FAIL?

If so the root is SELF-CONTRADICTORY and the gate goes RED. It decides purely
from what is published — it never re-runs a tool, and it never rewrites
anything. Correcting a published record is the benchmark-agent's commit under
NO-MIX (results and plugin fixes never share a commit), so this program reports
and exits non-zero; it does not repair.

WHAT COUNTS AS A GATE REPORT
----------------------------
A tracked ``*.json`` under the root carrying a top-level string verdict field.
That convention is not invented here — ``benchmark-data/ic/retention.json``
already documents it from the other side ("Do not add a 'verdict' key anywhere
in this file: a JSON carrying one is read as a gate report").

BLOCKING, not advisory. A run whose headline contradicts its own machine
evidence is exactly the class of record this repo exists to refuse.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _vacuous_exit as _vx  # noqa: E402

GATE = "published_verdict_self_consistency_check"

# Fields a gate report uses to carry its verdict, in precedence order.
VERDICT_FIELDS = ("verdict", "overall", "overall_status", "status",
                  "gate_status", "result", "pass_fail")

# Verdict tokens that are a FAIL and nothing else. WAIVED / SKIP / N/A are NOT
# failures — "filed no verdict" is not "failed", and conflating them is how a
# gate starts deleting things it merely failed to measure.
FAIL_TOKENS = {"FAIL", "FAILED", "FAILING"}

# A PASS-like headline. COMPLETE / DEMONSTRATED are included because the corpus
# used them AS the verdict (edge_llm_accel's headline was `STATUS: COMPLETE`),
# and a gate that only recognised the literal word PASS would have let exactly
# the measured case through.
PASS_TOKENS = ("PASS", "COMPLETE", "DEMONSTRATED", "CONVERGED")

# Lines that carry a run's top-level verdict. Anchored to verdict-bearing
# labels so a stray "pass" in prose is not read as a declaration.
VERDICT_LINE = re.compile(
    r"^\s*[>#*\-\s]*\**\s*"
    r"(STATUS|VERDICT|OVERALL|RESULT|OUTCOME|TESTS)\b",
    re.IGNORECASE)


def declared_verdict(result_md_text: str) -> str:
    """PASS | NOT_PASS | UNDECLARED — what RESULT.md claims about itself.

    Only verdict-bearing lines are consulted. An explicit FAIL on such a line
    wins over a PASS token: a root that already admits failure is not the
    defect this gate is about.
    """
    saw_pass = False
    for raw in result_md_text.splitlines():
        if not VERDICT_LINE.match(raw):
            continue
        upper = raw.upper()
        if any(t in upper for t in FAIL_TOKENS):
            return "NOT_PASS"
        if any(t in upper for t in PASS_TOKENS):
            saw_pass = True
    return "PASS" if saw_pass else "UNDECLARED"


def gate_report_verdict(path: str):
    """(field, VERDICT) for a published gate report, or None if not one."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    for field in VERDICT_FIELDS:
        value = doc.get(field)
        if isinstance(value, str) and value.strip():
            return field, value.strip().upper()
    return None


def failing_gate_reports(root: str):
    """Every published gate report under `root` whose verdict is a FAIL."""
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            if not name.endswith(".json"):
                continue
            path = os.path.join(dirpath, name)
            got = gate_report_verdict(path)
            if got and got[1] in FAIL_TOKENS:
                found.append((os.path.relpath(path, root), got[0], got[1]))
    return found


def find_run_roots(corpus: str):
    """Directories that publish a RESULT.md — one per published run root."""
    roots = []
    for dirpath, _dirnames, filenames in os.walk(corpus):
        if "RESULT.md" in filenames:
            roots.append(dirpath)
    return sorted(roots)


def audit(corpus: str):
    """[(root, n_fail, [(relpath, field, verdict), ...]), ...] for bad roots."""
    bad = []
    for root in find_run_roots(corpus):
        try:
            with open(os.path.join(root, "RESULT.md"),
                      "r", encoding="utf-8") as fh:
                text = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        if declared_verdict(text) != "PASS":
            continue
        fails = failing_gate_reports(root)
        if fails:
            bad.append((root, len(fails), fails))
    return bad


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="A run's top-level RESULT.md may not declare PASS while a "
                    "gate report published under that same root declares FAIL.")
    parser.add_argument("--corpus", default="benchmark-data",
                        help="tree to audit (default: benchmark-data)")
    parser.add_argument("--json", dest="as_json", action="store_true",
                        help="emit the finding set as JSON")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.corpus):
        print(f"[FAIL] --corpus {args.corpus!r} is not a directory",
              file=sys.stderr)
        return 2

    bad = audit(args.corpus)
    roots = find_run_roots(args.corpus)

    if args.as_json:
        json.dump({"corpus": args.corpus,
                   "run_roots_examined": len(roots),
                   "self_contradictory": [
                       {"root": r, "failing_gate_reports": n,
                        "reports": [{"path": p, "field": f, "verdict": v}
                                    for p, f, v in items]}
                       for r, n, items in bad]},
                  sys.stdout, indent=2)
        sys.stdout.write("\n")

    # A ZERO POPULATION IS NOT A PASS (#1028).
    #
    # PR #1028 empties `benchmark-data/ic/`, so this gate's population can now
    # legitimately be zero — and a gate that answers 0 over an empty corpus is
    # lie-shape #2 ("passes over a zero denominator") and #3 ("passes on an
    # empty tree") at once. Printing the count is NOT sufficient: prose is not
    # an exit code, and every automated consumer reads the code. The tier is
    # decided by rc alone (`flow_compliance_check._check_program_exit_zero`
    # promotes rc 2 to VACUOUS_PASS), so this must exit 2, not 0.
    if not roots:
        reason = "no-published-run-root"
        _vx.announce_vacuous(GATE, reason)
        print(f"[VACUOUS] {GATE}: 0 published run root(s) under "
              f"{args.corpus!r} — no directory carrying a RESULT.md was "
              f"found, so no run's verdict has been compared against its own "
              f"gate reports. Nothing about this corpus has been judged.",
              file=sys.stderr)
        return _vx.RC_VACUOUS

    if not bad:
        print(f"[PASS] {len(roots)} published run root(s) examined; no "
              f"RESULT.md declares PASS over a FAIL gate report of its own.",
              file=sys.stderr)
        return 0

    print(f"[FAIL] {len(bad)} of {len(roots)} published run root(s) declare "
          f"PASS while their OWN published gate reports declare FAIL:",
          file=sys.stderr)
    for root, count, items in bad:
        print(f"  {root}  RESULT.md=PASS  but {count} gate report(s) FAIL",
              file=sys.stderr)
        for path, field, verdict in items[:5]:
            print(f"      {verdict} [{field}] {path}", file=sys.stderr)
        if count > 5:
            print(f"      ... +{count - 5} more", file=sys.stderr)
    print("\nA headline verdict that contradicts the machine evidence beside "
          "it is not a publishable record. Correcting one is the "
          "benchmark-agent's commit under NO-MIX; this gate reports, it does "
          "not repair.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
