#!/usr/bin/env python3
"""regression_failure_route.py — Pattern-B extraction from
`skills/regression-manage/SKILL.md` Workflow step 4.

The skill encoded a fixed routing table as prose:

  timing fail     → /sta-review
  DRC fail        → /drc-fix
  functional fail → /rtl-repair  (testbench-gen for stimulus gaps)
  formal fail     → /formal-verify

This is a deterministic failing-step → target-skill lookup. We key the
lookup on a normalised `failing_step` token (the canonical EDA stage
that produced the failure). A free `error_class` string may also be
supplied; if `failing_step` is unknown but `error_class` carries a
recognised token, we fall back to token-matching.

Honest-FAIL contract: a failure whose step is unknown AND whose
error_class matches no token is routed to the explicit sentinel
"unrouted" (NOT silently dropped, NOT vacuously routed somewhere) and
the CLI exits 1. Garbage / non-list input exits 2. Only a fully-routed
list earns exit 0.

CLI:
  python3 regression_failure_route.py --failures-json <in.json> \\
      [--json <out.json>]
  exit 0 = every failure routed; exit 1 = at least one unrouted;
  exit 2 = input error.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

UNROUTED = "unrouted"

# Canonical failing-step → target skill. Steps are normalised to
# lowercase before lookup.
STEP_ROUTE: Dict[str, str] = {
    "sta": "/sta-review",
    "timing": "/sta-review",
    "drc": "/drc-fix",
    "lvs": "/lvs-triage",
    "ir_drop": "/ir-drop-triage",
    "ir-drop": "/ir-drop-triage",
    "em": "/ir-drop-triage",
    "functional": "/rtl-repair",
    "sim": "/rtl-repair",
    "simulation": "/rtl-repair",
    "lint": "/rtl-repair",
    "synth": "/synth-doctor",
    "synthesis": "/synth-doctor",
    "formal": "/formal-verify",
    "lec": "/equivalence-check",
    "equivalence": "/equivalence-check",
    "coverage": "/coverage-closure",
}

# Fallback: substring tokens in a free error_class string → step.
ERROR_TOKEN_TO_STEP: Dict[str, str] = {
    "setup violation": "sta",
    "hold violation": "sta",
    "negative slack": "sta",
    "wns": "sta",
    "tns": "sta",
    "spacing": "drc",
    "min width": "drc",
    "drc": "drc",
    "lvs": "lvs",
    "mismatch": "lvs",
    "ir drop": "ir_drop",
    "electromigration": "em",
    "assertion failed": "functional",
    "mismatch at time": "functional",
    "miscompare": "functional",
    "property failed": "formal",
    "cex": "formal",
    "lec mismatch": "lec",
}


class InputError(ValueError):
    """Raised when a failure record is malformed."""


@dataclass
class RouteFinding:
    test: str
    failing_step: str
    target_skill: str
    routed: bool

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def route_one(rec: Dict[str, Any]) -> RouteFinding:
    """Route a single failure to a target skill. Raises InputError if
    malformed (missing 'test', or neither 'failing_step' nor
    'error_class' present)."""
    if not isinstance(rec, dict):
        raise InputError(f"failure record is not an object: {rec!r}")
    test = str(rec.get("test", "")).strip()
    if not test:
        raise InputError(f"missing/empty 'test' field in {rec!r}")
    has_step = "failing_step" in rec
    has_err = "error_class" in rec
    if not (has_step or has_err):
        raise InputError(
            f"record needs at least one of 'failing_step' / "
            f"'error_class': {rec!r}")

    step = str(rec.get("failing_step", "")).strip().lower()
    target = STEP_ROUTE.get(step)

    if target is None:
        # Fall back to token-matching on the error class.
        err = str(rec.get("error_class", "")).lower()
        for tok, mapped_step in ERROR_TOKEN_TO_STEP.items():
            if tok in err:
                step = step or mapped_step
                target = STEP_ROUTE.get(mapped_step)
                break

    if target is None:
        return RouteFinding(test=test, failing_step=step or "unknown",
                            target_skill=UNROUTED, routed=False)
    return RouteFinding(test=test, failing_step=step or "unknown",
                        target_skill=target, routed=True)


def route_all(records: List[Dict[str, Any]]) -> List[RouteFinding]:
    if not isinstance(records, list):
        raise InputError("top-level JSON must be a list of failure records")
    return [route_one(r) for r in records]


def build_report(findings: List[RouteFinding]) -> Dict[str, Any]:
    by_skill: Dict[str, int] = {}
    unrouted = 0
    for f in findings:
        by_skill[f.target_skill] = by_skill.get(f.target_skill, 0) + 1
        if not f.routed:
            unrouted += 1
    return {
        "findings": [f.as_dict() for f in findings],
        "counts_by_skill": by_skill,
        "total": len(findings),
        "unrouted_count": unrouted,
        "all_routed": unrouted == 0,
        "emitted_by": "regression_failure_route",
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--failures-json", type=Path, required=True,
                   help='JSON list: [{"test", "failing_step"|'
                        '"error_class"}, ...]')
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
        findings = route_all(raw)
    except InputError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2

    report = build_report(findings)
    if args.out_json:
        args.out_json.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8")
    print(json.dumps(report["counts_by_skill"]))
    if not report["all_routed"]:
        print(f"WARN: {report['unrouted_count']} failure(s) unrouted",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
