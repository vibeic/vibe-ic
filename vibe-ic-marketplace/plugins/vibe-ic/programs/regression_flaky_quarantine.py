#!/usr/bin/env python3
"""regression_flaky_quarantine.py — Pattern-B extraction from
`skills/regression-manage/SKILL.md` Workflow step 5.

The skill encoded "a test that passes on retry is flaky → move to
quarantine" as prose. It is a deterministic rule over per-test retry
results:

  Given a test's ordered list of run results (each "pass" | "fail"):
    * stable_pass   : all results are "pass"          → keep
    * stable_fail   : all results are "fail"          → keep (real fail)
    * flaky         : at least one "pass" AND at least one "fail"
                      → quarantine + open ticket
    * no_data       : empty results list              → error (FAIL)

A flaky test must NOT be allowed to hide a real regression, so the
program records it for quarantine and emits a ticket stub. The
flakiness score = fail_count / total_runs (0 < score < 1 for flaky).

Honest-FAIL contract: a record with no results, a non-bool/str result
token, or a missing 'test' is reported as an error and the CLI exits 2.
Garbage / non-list JSON exits 2. The CLI exits 1 when any test is
quarantined (so CI can gate on it) and 0 when none are.

CLI:
  python3 regression_flaky_quarantine.py --tests-json <in.json> \\
      [--json <out.json>]
  exit 0 = no flaky tests; exit 1 = at least one quarantined;
  exit 2 = input error.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

_VALID_RESULT = {"pass", "fail"}

VERDICTS = ("stable_pass", "stable_fail", "flaky")


class InputError(ValueError):
    """Raised when a test record is malformed."""


@dataclass
class TestVerdict:
    test: str
    verdict: str
    runs: int
    fail_count: int
    flakiness: float
    quarantine: bool
    ticket: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _normalize_results(results: Any, test: str) -> List[str]:
    if not isinstance(results, list) or not results:
        raise InputError(
            f"test {test!r} has empty/invalid 'results' (need a "
            f"non-empty list of 'pass'/'fail')")
    out: List[str] = []
    for r in results:
        # Accept bool (True=pass) or the strings "pass"/"fail".
        if isinstance(r, bool):
            out.append("pass" if r else "fail")
        elif isinstance(r, str) and r.strip().lower() in _VALID_RESULT:
            out.append(r.strip().lower())
        else:
            raise InputError(
                f"test {test!r} has invalid result token {r!r} "
                f"(expected 'pass'/'fail' or bool)")
    return out


def classify_test(rec: Dict[str, Any]) -> TestVerdict:
    """Classify a single test's retry history. Raises InputError if
    malformed."""
    if not isinstance(rec, dict):
        raise InputError(f"test record is not an object: {rec!r}")
    test = str(rec.get("test", "")).strip()
    if not test:
        raise InputError(f"missing/empty 'test' field in {rec!r}")
    if "results" not in rec:
        raise InputError(f"missing 'results' field for test {test!r}")

    results = _normalize_results(rec["results"], test)
    runs = len(results)
    fail_count = sum(1 for r in results if r == "fail")
    pass_count = runs - fail_count

    if fail_count == 0:
        verdict, quarantine, ticket = "stable_pass", False, None
    elif pass_count == 0:
        verdict, quarantine, ticket = "stable_fail", False, None
    else:
        verdict = "flaky"
        quarantine = True
        ticket = (f"QUARANTINE: {test} flaky "
                  f"({pass_count} pass / {fail_count} fail of {runs} runs) "
                  f"— moved to quarantine suite; do not let it mask real "
                  f"regressions")

    return TestVerdict(
        test=test, verdict=verdict, runs=runs, fail_count=fail_count,
        flakiness=round(fail_count / runs, 4),
        quarantine=quarantine, ticket=ticket)


def classify_all(records: List[Dict[str, Any]]) -> List[TestVerdict]:
    if not isinstance(records, list):
        raise InputError("top-level JSON must be a list of test records")
    return [classify_test(r) for r in records]


def build_report(verdicts: List[TestVerdict]) -> Dict[str, Any]:
    counts = {v: 0 for v in VERDICTS}
    quarantined = []
    for v in verdicts:
        counts[v.verdict] = counts.get(v.verdict, 0) + 1
        if v.quarantine:
            quarantined.append(v.test)
    return {
        "verdicts": [v.as_dict() for v in verdicts],
        "counts_by_verdict": counts,
        "quarantined": quarantined,
        "quarantine_count": len(quarantined),
        "total": len(verdicts),
        "emitted_by": "regression_flaky_quarantine",
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tests-json", type=Path, required=True,
                   help='JSON list: [{"test", "results": '
                        '["pass"|"fail", ...]}, ...]')
    p.add_argument("--json", type=Path, dest="out_json")
    args = p.parse_args(argv)

    if not args.tests_json.is_file():
        print(f"FAIL: input file not found: {args.tests_json}",
              file=sys.stderr)
        return 2
    try:
        raw = json.loads(args.tests_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"FAIL: cannot parse JSON: {e}", file=sys.stderr)
        return 2

    try:
        verdicts = classify_all(raw)
    except InputError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2

    report = build_report(verdicts)
    if args.out_json:
        args.out_json.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8")
    print(f"{report['quarantine_count']} flaky test(s) quarantined "
          f"of {report['total']}")
    return 1 if report["quarantine_count"] > 0 else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
