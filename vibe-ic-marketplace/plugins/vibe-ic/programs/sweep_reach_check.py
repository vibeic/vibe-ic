#!/usr/bin/env python3
"""sweep_reach_check.py — refuse to read a sweep as clean when it reached nothing.

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. This is wired at flow step 31 as an
`advisory_program_exit_zero` clause, conditional on the PERC sweep above it
having emitted a report.

ADVISORY because the sweep it judges is advisory itself and emits only when it
found a routed DEF: a reach verdict is exactly as strong as the sweep it reads,
and making the consumer blocking while the producer cannot fail would put the
harder verdict on the weaker evidence. It becomes `program_exit_zero` when the
sweep does.

WHY IT WAS UNWIRED FOR SO LONG, recorded because the mechanism outlived the
instance. Its only non-comment referrer in the entire repository was one line
of argparse help text in `perc_corpus_sweep` — `help="write {rows, reach} here
— the document `sweep_reach_check.py --report` consumes"` — and three separate
wiring auditors read that SENTENCE as an invocation. A reachability instrument
was certified as wired by a description of itself.

A corpus sweep is the standard acceptance evidence for a new guard in this
plugin: run it over every tracked project, publish the exit code. The evidence
has a hole. A sweep that exits 0 having never entered the guard it is exercising
is byte-identical, in its output and in its exit code, to a sweep that ran the
guard over every target and found nothing wrong. One of those is a result and
the other is a measurement that did not happen.

This gate reads the reach block a sweep publishes (``_sweep_reach.REACH_KEY``,
top level or under ``summary``) and puts the question a reviewer would
otherwise have to ask by hand:

    rc 0   at least one target reached the guard's decision point.
           A PARTIAL sweep passes here. 1 of 756 is a thin result and this
           prints how thin, but it is a result.
    rc 1   the sweep published a reach block saying it reached NOTHING, or a
           reach block whose own arithmetic does not close.
    rc 2   no report stated its reach at all — this gate examined nothing, so
           it says so instead of passing. See "APPLIED TO ITSELF" below.

WHAT IT DELIBERATELY DOES NOT DO
================================
It does not require total coverage, or coverage above any threshold. Most
corpora contain targets a rule genuinely does not apply to, so a rule demanding
a sweep prove it reached EVERY target would fire on every honest partial sweep
and would be a worse defect than the one it replaces. It fires on exactly one
shape: a sweep that reached nothing, or that cannot say whether it did.

It also does not decide whether a sweep's own verdict was right. It is a
statement ABOUT the sweep, not a re-run of it.

APPLIED TO ITSELF
=================
This gate is a sweep — over reach reports. It therefore accounts for its own
reach with the same ``SweepReach`` type, publishes it under the same key, and
returns rc 2 through the same ``_vacuous_exit`` router when no supplied report
stated its reach. A gate that checked others for a silent zero while exiting 0
on its own silent zero would be the finding, not the fix.

Usage:
    sweep_reach_check.py --report R.json [--report R2.json ...]
    sweep_reach_check.py --report R.json --require-reach   # missing block -> rc 1
    sweep_reach_check.py --report R.json --json -          # report on stdout
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _sweep_reach as _sr  # noqa: E402
import _vacuous_exit as _vx  # noqa: E402

GATE = "sweep_reach_check"

#: Where a reach block is looked for inside a published report, in order.
_LOOKUP = ("", "summary", "reach_report")


def find_reach_block(doc: Any) -> Optional[Dict[str, Any]]:
    """The reach block inside a published report document, or None.

    Accepts it at the top level, under ``summary`` (where
    ``_gate_denominator.attach`` puts its sibling) or under ``reach_report``.
    Returns None — never ``{}`` — when absent, so "stated nothing" cannot be
    confused with "stated a zero".
    """
    if not isinstance(doc, dict):
        return None
    for prefix in _LOOKUP:
        node = doc if prefix == "" else doc.get(prefix)
        if isinstance(node, dict) and isinstance(node.get(_sr.REACH_KEY), dict):
            return node[_sr.REACH_KEY]
    return None


def judge_report(path: str, doc: Any) -> Tuple[str, List[str], str]:
    """Classify ONE published report.

    Returns ``(state, problems, line)`` where state is one of:
      ``NOT_STATED`` — no reach block; this gate could not put the question
      ``VACUOUS``    — the sweep says it reached nothing
      ``BROKEN``     — the block contradicts itself
      ``REACHED``    — the sweep says it reached at least one target
    """
    block = find_reach_block(doc)
    if block is None:
        return ("NOT_STATED", [], _sr.line_of({}))
    summary = {_sr.REACH_KEY: block}
    problems = _sr.reach_violations(summary)
    line = _sr.line_of(summary)
    if problems:
        return ("BROKEN", problems, line)
    return ("VACUOUS" if block.get("reached") == 0 else "REACHED", [], line)


def run(report_paths: List[str],
        require_reach: bool = False) -> Tuple[Dict[str, Any], _sr.SweepReach]:
    """Judge every supplied report; account for this gate's own reach as we go.

    Returns ``(summary, own_reach)``. The live ``SweepReach`` is returned
    ALONGSIDE the summary rather than stashed inside it: a caller that
    serialises the summary must not have to know to remove a non-JSON object
    first, and the reach block it needs is already in there under
    ``_sweep_reach.REACH_KEY``.
    """
    own = _sr.SweepReach(unit="published sweep reach report",
                         decision_points=("judge_report",))
    rows: List[Dict[str, Any]] = []
    failures: List[str] = []

    for p in report_paths:
        try:
            doc = json.loads(Path(p).read_text())
        except (OSError, ValueError) as exc:
            own.not_reached(p, "report is unreadable or not JSON")
            rows.append({"report": p, "state": "UNREADABLE", "detail": str(exc)[:200]})
            if require_reach:
                failures.append(f"{p}: unreadable ({str(exc)[:120]})")
            continue

        state, problems, line = judge_report(p, doc)
        if state == "NOT_STATED":
            # This gate did not reach its decision point for this report: there
            # was no claim to judge. That is a non-reach, not a pass.
            own.not_reached(p, "report publishes no reach block")
            rows.append({"report": p, "state": state, "line": line})
            if require_reach:
                failures.append(
                    f"{p}: publishes no {_sr.REACH_KEY!r} block, and "
                    "--require-reach was given")
            continue

        own.reached(p, point="judge_report")
        rows.append({"report": p, "state": state, "line": line,
                     "problems": problems})
        if state == "VACUOUS":
            failures.append(
                f"{p}: {line} — this sweep exercised the guard on nothing, so "
                "its verdict is not a reading of the guard")
        elif state == "BROKEN":
            failures.append(f"{p}: reach block is not self-consistent: "
                            + "; ".join(problems))

    passed = not failures
    summary: Dict[str, Any] = {
        "gate": GATE,
        "passed": passed,
        "reports": rows,
        "failures": failures,
        "skipped": own.is_vacuous,
        "reason": ("no supplied report stated its reach"
                   if own.is_vacuous else "reach judged"),
    }
    _sr.attach(summary, own)
    return summary, own


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--report", dest="reports", action="append", default=[],
                    metavar="JSON",
                    help="a sweep's published report (repeatable)")
    ap.add_argument("--require-reach", action="store_true",
                    help="treat a report that publishes no reach block as a "
                         "FAILURE rather than as a question this gate could "
                         "not put")
    ap.add_argument("--json", metavar="PATH",
                    help="write the machine-readable summary here ('-' = stdout)")
    args = ap.parse_args(argv)

    if not args.reports:
        ap.error("give at least one --report")
        return _vx.RC_VACUOUS   # pragma: no cover - argparse exits first

    summary, own = run(args.reports, require_reach=args.require_reach)

    if args.json:
        text = json.dumps(summary, indent=2, sort_keys=True)
        if args.json == "-":
            print(text)
        else:
            Path(args.json).write_text(text + "\n")

    if args.json != "-":
        print(own.verdict_line(GATE, summary["passed"]))
        print("  " + own.line())
        for row in summary["reports"]:
            print(f"  [{row['state']:10s}] {row['report']}")
            if row.get("line"):
                print(f"      {row['line']}")
    for f in summary["failures"]:
        print(f"FAIL: {f}", file=sys.stderr)

    own.announce(GATE, passed=summary["passed"])
    return own.exit_code(summary["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
