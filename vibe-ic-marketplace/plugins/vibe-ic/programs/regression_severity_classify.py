#!/usr/bin/env python3
"""regression_severity_classify.py — Pattern-B extraction from
`skills/regression-manage/SKILL.md` Workflow step 3.

The skill encoded the severity classification as prose. It is a pure
decision table over structured run-history fields:

  P0  was-green-now-red                 (tape-out blocker)
  P1  new failure on a feature branch   (not previously seen, not on a
                                          protected/release branch)
  P2  flaky (passes on retry)
  P3  environmental (license / disk / network / tool-infra)

Each predicate is computable from these per-failure fields:
  prev_status   : "pass" | "fail" | "absent"  (status on the previous
                  run of the same job on the same branch)
  branch_type   : "protected" | "release" | "feature" | ...
  retry_pass    : bool   (did a retry of the SAME test pass?)
  error_class   : free string; matched against an ENV_ERROR token set
                  to detect environmental failures

Precedence (highest first), because a single failure can satisfy
several predicates:
  1. environmental  → P3  (don't blame the design for infra)
  2. flaky          → P2  (passes on retry; not a real regression yet)
  3. was-green-now-red on a protected/release branch → P0
  4. new failure on a feature branch                 → P1
  5. fallback                                          → P1

Honest-FAIL contract: a record missing the mandatory keys, or carrying
an unrecognised branch_type / prev_status, is reported as an error and
the CLI exits 2 (input error). A garbage / non-list JSON exits 2. Only
a well-formed list of records earns exit 0/1.

CLI:
  python3 regression_severity_classify.py --failures-json <in.json> \\
      [--json <out.json>]
  exit 0 = classified, no P0; exit 1 = at least one P0 (blocker present);
  exit 2 = input error (garbage / missing fields).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

SEVERITIES = ("P0", "P1", "P2", "P3")

_MANDATORY_KEYS = ("test", "prev_status", "branch_type",
                   "retry_pass", "error_class")

_VALID_PREV = {"pass", "fail", "absent"}
_PROTECTED_BRANCHES = {"protected", "release", "main", "master", "trunk"}

# Tokens that mark an environmental (infra) failure rather than a
# design / test defect. Matched case-insensitively as substrings.
_ENV_TOKENS = (
    "license", "flexlm", "lmgrd", "disk full", "no space",
    "out of disk", "quota", "network", "timeout connecting",
    "connection refused", "lsf", "slurm", "host down",
    "nfs", "permission denied", "tool crash", "segfault in tool",
)

_RATIONALE: Dict[str, str] = {
    "P0": "was-green-now-red on a protected/release branch — tape-out blocker",
    "P1": "new failure on a feature branch",
    "P2": "flaky — passes on retry; not a confirmed regression",
    "P3": "environmental — tool license / disk / network / infra",
}


class InputError(ValueError):
    """Raised when a failure record is malformed."""


@dataclass
class SeverityFinding:
    test: str
    severity: str
    rationale: str

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _is_environmental(error_class: str) -> bool:
    e = (error_class or "").lower()
    return any(tok in e for tok in _ENV_TOKENS)


def classify_one(rec: Dict[str, Any]) -> SeverityFinding:
    """Classify a single failure record. Raises InputError if malformed."""
    if not isinstance(rec, dict):
        raise InputError(f"failure record is not an object: {rec!r}")
    for k in _MANDATORY_KEYS:
        if k not in rec:
            raise InputError(f"missing mandatory field {k!r} in {rec!r}")

    test = str(rec["test"]).strip()
    if not test:
        raise InputError(f"empty 'test' field in {rec!r}")

    prev = str(rec["prev_status"]).strip().lower()
    if prev not in _VALID_PREV:
        raise InputError(
            f"prev_status must be one of {sorted(_VALID_PREV)}; "
            f"got {rec['prev_status']!r}")

    branch = str(rec["branch_type"]).strip().lower()
    if not branch:
        raise InputError(f"empty 'branch_type' in {rec!r}")

    retry_pass = rec["retry_pass"]
    if not isinstance(retry_pass, bool):
        raise InputError(
            f"retry_pass must be a JSON boolean; got {retry_pass!r}")

    error_class = str(rec["error_class"])

    # Precedence order (see module docstring).
    if _is_environmental(error_class):
        sev = "P3"
    elif retry_pass:
        sev = "P2"
    elif prev == "pass" and branch in _PROTECTED_BRANCHES:
        sev = "P0"
    elif prev == "pass":
        # was-green-now-red but on a feature branch — still a real
        # regression, but not a tape-out blocker → P1.
        sev = "P1"
    else:
        # New failure (prev fail/absent) on any branch → P1.
        sev = "P1"

    return SeverityFinding(test=test, severity=sev,
                           rationale=_RATIONALE[sev])


def classify_all(records: List[Dict[str, Any]]) -> List[SeverityFinding]:
    if not isinstance(records, list):
        raise InputError("top-level JSON must be a list of failure records")
    return [classify_one(r) for r in records]


def build_report(findings: List[SeverityFinding]) -> Dict[str, Any]:
    counts = {s: 0 for s in SEVERITIES}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    return {
        "findings": [f.as_dict() for f in findings],
        "counts_by_severity": counts,
        "total": len(findings),
        "p0_present": counts["P0"] > 0,
        "emitted_by": "regression_severity_classify",
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--failures-json", type=Path, required=True,
                   help='JSON list: [{"test", "prev_status", '
                        '"branch_type", "retry_pass", "error_class"}, ...]')
    p.add_argument("--json", type=Path, dest="out_json")
    args = p.parse_args(argv)

    if not args.failures_json.is_file():
        print(f"FAIL: input file not found: {args.failures_json}",
              file=sys.stderr)
        return 2
    try:
        raw = json.loads(args.failures_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"FAIL: cannot parse JSON: {e}", file=sys.stderr)
        return 2

    try:
        findings = classify_all(raw)
    except InputError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2

    report = build_report(findings)
    if args.out_json:
        args.out_json.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8")
    print(json.dumps(report["counts_by_severity"]))
    return 1 if report["p0_present"] else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
