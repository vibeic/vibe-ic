#!/usr/bin/env python3
"""regression_failure_dedup.py — Pattern-B extraction from
`skills/regression-manage/SKILL.md` Workflow step 2.

The skill encoded "group identical failures into one issue" as prose.
It is a deterministic normalize-and-hash of the failure signature:

  1. canonicalise the error string —
       * strip line numbers       (`:123:`, `line 123`)
       * strip absolute paths      (keep the basename)
       * strip timestamps          (ISO-8601, [HH:MM:SS], epoch-ish)
       * strip hex addresses       (0x...)
       * collapse run-specific run IDs / PIDs (digits ≥4 long)
       * collapse whitespace
  2. hash the canonical string (sha1, first 12 hex chars)
  3. group failures by hash → one issue per group, with the member
     test list.

Honest-FAIL contract: a record missing the mandatory keys ('test',
'error') is reported as an error and the CLI exits 2. Garbage /
non-list JSON exits 2. An empty list produces zero groups and exits 0
(no failures is a legitimate clean state, not a vacuous PASS — the
group count is honestly 0).

CLI:
  python3 regression_failure_dedup.py --failures-json <in.json> \\
      [--json <out.json>]
  exit 0 = deduped successfully; exit 2 = input error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

_MANDATORY_KEYS = ("test", "error")

# Canonicalisation substitutions, applied in order.
_ISO_TS = re.compile(
    r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_BRACKET_TS = re.compile(r"\[\d{2}:\d{2}:\d{2}(?:\.\d+)?\]")
_HEX_ADDR = re.compile(r"0x[0-9a-fA-F]+")
_LINE_COLON = re.compile(r":\d+:")
_LINE_WORD = re.compile(r"\bline\s+\d+\b", re.I)
_ABS_PATH = re.compile(r"(/[^\s:'\"]+/)+([^\s:'\"/]+)")
_LONG_DIGITS = re.compile(r"\b\d{4,}\b")
_WS = re.compile(r"\s+")


class InputError(ValueError):
    """Raised when a failure record is malformed."""


def canonicalize(error: str) -> str:
    """Return a run-invariant canonical form of an error string."""
    s = error
    s = _ISO_TS.sub("<TS>", s)
    s = _BRACKET_TS.sub("[<TS>]", s)
    s = _HEX_ADDR.sub("<ADDR>", s)
    s = _LINE_COLON.sub(":<N>:", s)
    s = _LINE_WORD.sub("line <N>", s)
    # Replace absolute paths with their basename so the same error from a
    # different scratch dir groups together.
    s = _ABS_PATH.sub(lambda m: m.group(2), s)
    s = _LONG_DIGITS.sub("<N>", s)
    s = _WS.sub(" ", s).strip()
    return s


def signature_hash(canonical: str) -> str:
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:12]


@dataclass
class FailureGroup:
    sig_hash: str
    canonical: str
    members: List[str] = field(default_factory=list)
    count: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def dedup(records: List[Dict[str, Any]]) -> List[FailureGroup]:
    """Group failure records by canonical signature. Insertion order of
    first-seen signatures is preserved for stable output."""
    if not isinstance(records, list):
        raise InputError("top-level JSON must be a list of failure records")
    groups: Dict[str, FailureGroup] = {}
    order: List[str] = []
    for rec in records:
        if not isinstance(rec, dict):
            raise InputError(f"failure record is not an object: {rec!r}")
        for k in _MANDATORY_KEYS:
            if k not in rec:
                raise InputError(
                    f"missing mandatory field {k!r} in {rec!r}")
        test = str(rec["test"]).strip()
        if not test:
            raise InputError(f"empty 'test' field in {rec!r}")
        canon = canonicalize(str(rec["error"]))
        h = signature_hash(canon)
        if h not in groups:
            groups[h] = FailureGroup(sig_hash=h, canonical=canon)
            order.append(h)
        groups[h].members.append(test)
        groups[h].count += 1
    return [groups[h] for h in order]


def build_report(groups: List[FailureGroup],
                  total_input: int) -> Dict[str, Any]:
    return {
        "groups": [g.as_dict() for g in groups],
        "group_count": len(groups),
        "total_failures": total_input,
        "dedup_ratio": (
            round(1 - len(groups) / total_input, 4)
            if total_input else 0.0),
        "emitted_by": "regression_failure_dedup",
    }


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--failures-json", type=Path, required=True,
                   help='JSON list: [{"test", "error"}, ...]')
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
        groups = dedup(raw)
    except InputError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2

    report = build_report(groups, len(raw) if isinstance(raw, list) else 0)
    if args.out_json:
        args.out_json.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8")
    print(f"{report['group_count']} group(s) from "
          f"{report['total_failures']} failure(s)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
