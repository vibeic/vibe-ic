#!/usr/bin/env python3
"""regression_report_aggregate.py — Pattern-B extraction from
`skills/regression-manage/SKILL.md` Workflow step 1 + Output format.

The skill narrated the summary dashboard (pass %, P0 count, trend) as
LLM prose. It is deterministic arithmetic over the run log:

  per-job:   pass / fail / error / timeout counts
  overall:   totals, pass %  (pass / total, total = sum of all outcomes)
  trend:     if a prior pass % is supplied → delta vs previous run
             ("up" / "down" / "flat")
  p0_count:  carried through from the severity classifier (caller may
             pass it; the aggregator does not re-derive severity)

Honest-FAIL contract: a job record missing the four outcome counters,
a negative count, or a non-integer count is reported as an error and
the CLI exits 2. Garbage / non-list JSON exits 2. A regression with
zero passing tests in a non-empty run yields pass_pct == 0.0 (an honest
0 %, not a vacuous PASS) and the CLI exits 1 when overall pass % is
below the (optional) `--min-pass-pct` gate.

CLI:
  python3 regression_report_aggregate.py --jobs-json <in.json> \\
      [--prev-pass-pct <float>] [--p0-count <int>] \\
      [--min-pass-pct <float>] [--json <out.json>] [--md <out.md>]
  exit 0 = pass % >= gate (or no gate); exit 1 = below gate;
  exit 2 = input error.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

_OUTCOMES = ("pass", "fail", "error", "timeout")


class InputError(ValueError):
    """Raised when a job record is malformed."""


@dataclass
class JobSummary:
    job: str
    passed: int
    failed: int
    errored: int
    timed_out: int
    total: int
    pass_pct: float

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _coerce_count(rec: Dict[str, Any], key: str, job: str) -> int:
    if key not in rec:
        raise InputError(f"job {job!r} missing counter {key!r}")
    v = rec[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise InputError(
            f"job {job!r} counter {key!r} must be a non-negative "
            f"integer; got {v!r}")
    if v < 0:
        raise InputError(
            f"job {job!r} counter {key!r} is negative ({v})")
    return v


def summarize_job(rec: Dict[str, Any]) -> JobSummary:
    if not isinstance(rec, dict):
        raise InputError(f"job record is not an object: {rec!r}")
    job = str(rec.get("job", "")).strip()
    if not job:
        raise InputError(f"missing/empty 'job' field in {rec!r}")
    passed = _coerce_count(rec, "pass", job)
    failed = _coerce_count(rec, "fail", job)
    errored = _coerce_count(rec, "error", job)
    timed_out = _coerce_count(rec, "timeout", job)
    total = passed + failed + errored + timed_out
    pass_pct = round(100.0 * passed / total, 2) if total else 0.0
    return JobSummary(job=job, passed=passed, failed=failed,
                      errored=errored, timed_out=timed_out,
                      total=total, pass_pct=pass_pct)


def aggregate(records: List[Dict[str, Any]],
              prev_pass_pct: Optional[float] = None,
              p0_count: int = 0) -> Dict[str, Any]:
    if not isinstance(records, list):
        raise InputError("top-level JSON must be a list of job records")
    jobs = [summarize_job(r) for r in records]
    tot_pass = sum(j.passed for j in jobs)
    tot_fail = sum(j.failed for j in jobs)
    tot_err = sum(j.errored for j in jobs)
    tot_to = sum(j.timed_out for j in jobs)
    grand = tot_pass + tot_fail + tot_err + tot_to
    overall_pct = round(100.0 * tot_pass / grand, 2) if grand else 0.0

    trend = None
    delta = None
    if prev_pass_pct is not None:
        delta = round(overall_pct - prev_pass_pct, 2)
        trend = "up" if delta > 0 else ("down" if delta < 0 else "flat")

    return {
        "jobs": [j.as_dict() for j in jobs],
        "totals": {
            "pass": tot_pass, "fail": tot_fail,
            "error": tot_err, "timeout": tot_to, "total": grand,
        },
        "overall_pass_pct": overall_pct,
        "prev_pass_pct": prev_pass_pct,
        "trend": trend,
        "trend_delta": delta,
        "p0_count": p0_count,
        "emitted_by": "regression_report_aggregate",
    }


def report_to_markdown(rep: Dict[str, Any], date: str = "") -> str:
    t = rep["totals"]
    out = [f"# Regression report {date}".rstrip(),
           "",
           "_Emitted by `regression_report_aggregate.py`._",
           "",
           "## Summary dashboard",
           "",
           f"- Overall pass: **{rep['overall_pass_pct']}%** "
           f"({t['pass']}/{t['total']})",
           f"- P0 (tape-out blockers): **{rep['p0_count']}**"]
    if rep["trend"] is not None:
        out.append(f"- Trend vs previous: {rep['trend']} "
                   f"({rep['trend_delta']:+} pp)")
    out += ["",
            "## Per-job",
            "",
            "| Job | Pass | Fail | Error | Timeout | Pass % |",
            "|---|---|---|---|---|---|"]
    for j in rep["jobs"]:
        out.append(f"| {j['job']} | {j['passed']} | {j['failed']} | "
                   f"{j['errored']} | {j['timed_out']} | {j['pass_pct']}% |")
    out.append("")
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--jobs-json", type=Path, required=True,
                   help='JSON list: [{"job", "pass", "fail", "error", '
                        '"timeout"}, ...]')
    p.add_argument("--prev-pass-pct", type=float, default=None)
    p.add_argument("--p0-count", type=int, default=0)
    p.add_argument("--min-pass-pct", type=float, default=None)
    p.add_argument("--date", default="")
    p.add_argument("--json", type=Path, dest="out_json")
    p.add_argument("--md", type=Path, dest="out_md")
    args = p.parse_args(argv)

    if not args.jobs_json.is_file():
        print(f"FAIL: input file not found: {args.jobs_json}",
              file=sys.stderr)
        return 2
    try:
        raw = json.loads(args.jobs_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"FAIL: cannot parse JSON: {e}", file=sys.stderr)
        return 2

    try:
        rep = aggregate(raw, prev_pass_pct=args.prev_pass_pct,
                        p0_count=args.p0_count)
    except InputError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 2

    if args.out_json:
        args.out_json.write_text(
            json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    md = report_to_markdown(rep, date=args.date)
    if args.out_md:
        args.out_md.write_text(md, encoding="utf-8")
    else:
        print(md)

    if args.min_pass_pct is not None and \
            rep["overall_pass_pct"] < args.min_pass_pct:
        print(f"WARN: overall pass {rep['overall_pass_pct']}% below "
              f"gate {args.min_pass_pct}%", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
