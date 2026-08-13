#!/usr/bin/env python3
"""step_metrics.py — one per-step metric schema, and "better or worse than last
time" as a command (vibe-ic#1080).

THE GAP
=======
Adopted from OpenROAD-flow-scripts @ f9ec54a6. ORFS answers "is this run better
or worse than the last one" with one `diff`, because every stage emits the same
flat schema and the aggregator is glob-and-merge
(`flow/util/genMetrics.py:251-301`):

    "cts__timing__setup__ws": -1.39289
    "cts__design__instance__area": 4795.85
    "cts__timing__drv__setup_violation_count": 67

We cannot. `flow/phase1_phase2_phase3.yaml` declares 63 steps, 62 carrying a
gate, and many write `--json reports/.../xxx.json` — but each checker chose its
own shape. Measured on a38902d1: no per-step QoR aggregator exists, and no
run-to-run diff exists.

THE KEY CONVENTION, TAKEN FROM ORFS BECAUSE IT WORKS
====================================================
    <stage>__<domain>__<name>

Flat, fixed-prefix, greppable, diffable. `emit` refuses a key that does not
match, because a schema nobody enforces is a suggestion.

EMITTED BY THE PROGRAM THAT COMPUTED THE NUMBER — NEVER BY LOG REGEX
=====================================================================
#1080 names this explicitly: "a log regex is a proxy for the measurement, not
the measurement (lie-shape #12)". `emit` takes a value from its caller. There is
deliberately no `--from-log` mode, and adding one would defeat the point.

ORACLE-FREE, AND THE DIRECTION FIELD IS WHY IT STAYS THAT WAY
==============================================================
"Better or worse" needs to know whether lower is better, and that is a FACT
ABOUT THE METRIC — violation counts go down, coverage goes up — not a judgement
about the run. So the emitter, which knows what it measured, may declare
`--direction lower_is_better|higher_is_better`. Where it does not, `diff`
reports the change and says `direction unknown` rather than guessing.

That keeps the whole thing oracle-free: it records what happened and, where the
producer stated the metric's polarity, it can say which way it moved. It never
asserts what the value SHOULD have been.

EXIT CODES: 0 PASS, 1 FAIL, 2 VACUOUS/could-not-look.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RC_PASS, RC_FAIL, RC_VACUOUS = 0, 1, 2

METRICS_REL = "reports/metrics"
MERGED_NAME = "metrics.json"

#: `<stage>__<domain>__<name>`; `name` may itself carry `__` (ORFS does:
#: `timing__drv__setup_violation_count`). At least three segments.
KEY_RE = re.compile(r"^[a-zA-Z0-9]+(?:__[a-zA-Z0-9_.:+-]+){2,}$")

DIRECTIONS = ("lower_is_better", "higher_is_better", "unknown")


def stage_file(run_dir: Path, stage: str) -> Path:
    return run_dir / METRICS_REL / f"{stage}.json"


def emit(run_dir: Path, stage: str, key: str, value, direction: str = "unknown"):
    """Record ONE metric. Refuses a key that breaks the schema."""
    if not KEY_RE.match(key):
        raise ValueError(
            f"metric key {key!r} does not match <stage>__<domain>__<name> — a "
            f"schema nobody enforces is a suggestion, so this is refused rather "
            f"than stored in a shape the diff cannot read")
    if not key.startswith(stage + "__"):
        raise ValueError(
            f"metric key {key!r} is not prefixed by its stage {stage!r}; the "
            f"fixed prefix is what makes the merged file greppable per stage")
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
    p = stage_file(run_dir, stage)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {"metrics": {}}
    doc["metrics"][key] = {"value": value, "direction": direction}
    p.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return p


def collect(run_dir: Path):
    """Glob-and-merge every stage file — ORFS's genMetrics, and just as dumb.

    The aggregator does almost nothing ON PURPOSE. Any cleverness here is a
    place for the merged view to disagree with what a step actually recorded.
    """
    merged, sources = {}, []
    d = run_dir / METRICS_REL
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            if p.name == MERGED_NAME:
                continue
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except ValueError:
                continue
            for k, v in (doc.get("metrics") or {}).items():
                merged[k] = v
            sources.append(p.name)
    return merged, sources


def diff(before: dict, after: dict):
    """What moved between two runs. Reports CHANGE; judges only where the
    producer declared the metric's polarity."""
    out = {"improved": [], "regressed": [], "changed_unknown": [],
           "new": sorted(set(after) - set(before)),
           "gone": sorted(set(before) - set(after))}
    for k in sorted(set(before) & set(after)):
        b, a = before[k].get("value"), after[k].get("value")
        if b == a:
            continue
        d = after[k].get("direction") or before[k].get("direction") or "unknown"
        rec = {"key": k, "before": b, "after": a, "direction": d}
        if not isinstance(b, (int, float)) or not isinstance(a, (int, float)):
            out["changed_unknown"].append(rec)
        elif d == "lower_is_better":
            (out["improved"] if a < b else out["regressed"]).append(rec)
        elif d == "higher_is_better":
            (out["improved"] if a > b else out["regressed"]).append(rec)
        else:
            out["changed_unknown"].append(rec)
    return out


def _load_run(p: Path):
    """A run dir, or a merged metrics.json written by `collect`.

    A path that does not exist returns {} rather than raising: "that run is not
    here" is the VACUOUS answer this tool already has a tier for, and a
    traceback would be a worse way to say it.
    """
    if p.is_dir():
        return collect(p)[0]
    if not p.is_file():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return doc.get("metrics") or {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("emit", help="record one metric (from the program that computed it)")
    e.add_argument("run_dir", type=Path)
    e.add_argument("--stage", required=True)
    e.add_argument("--key", required=True)
    e.add_argument("--value", required=True)
    e.add_argument("--direction", default="unknown", choices=DIRECTIONS)

    c = sub.add_parser("collect", help="glob-and-merge every stage file")
    c.add_argument("run_dir", type=Path)

    d = sub.add_parser("diff", help="better or worse than last time")
    d.add_argument("before", type=Path)
    d.add_argument("after", type=Path)
    d.add_argument("--json", dest="json_out", type=Path)

    args = ap.parse_args(argv)

    if args.cmd == "emit":
        try:
            v = json.loads(args.value)
        except ValueError:
            v = args.value
        try:
            p = emit(args.run_dir, args.stage, args.key, v, args.direction)
        except ValueError as exc:
            print(f"[FAIL] {exc}", file=sys.stderr)
            return RC_FAIL
        print(f"[OK] {args.key} = {v!r} ({args.direction}) -> {p}", file=sys.stderr)
        return RC_PASS

    if args.cmd == "collect":
        merged, sources = collect(args.run_dir)
        if not merged:
            print(f"[VACUOUS] step_metrics: no metric was recorded under "
                  f"{args.run_dir / METRICS_REL} — nothing to merge, and this "
                  f"is NOT a run with good numbers", file=sys.stderr)
            return RC_VACUOUS
        out = args.run_dir / METRICS_REL / MERGED_NAME
        out.write_text(json.dumps({"metrics": merged, "sources": sources},
                                  indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"[PASS] merged {len(merged)} metric(s) from {len(sources)} "
              f"stage file(s) -> {out}", file=sys.stderr)
        return RC_PASS

    before, after = _load_run(args.before), _load_run(args.after)
    if not before or not after:
        which = "before" if not before else "after"
        print(f"[VACUOUS] step_metrics diff: the {which} run recorded no "
              f"metric, so 'better or worse' cannot be answered — this is NOT "
              f"a report of no change", file=sys.stderr)
        return RC_VACUOUS

    rep = diff(before, after)
    if args.json_out:
        args.json_out.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")

    for bucket, label in (("regressed", "REGRESSED"), ("improved", "improved"),
                          ("changed_unknown", "changed (direction unknown)")):
        for r in rep[bucket]:
            print(f"  {label:<28} {r['key']}: {r['before']} -> {r['after']}",
                  file=sys.stderr)
    for k in rep["new"]:
        print(f"  {'NEW':<28} {k} = {after[k].get('value')}", file=sys.stderr)
    for k in rep["gone"]:
        print(f"  {'GONE':<28} {k} (was {before[k].get('value')})", file=sys.stderr)

    n = sum(len(rep[b]) for b in ("improved", "regressed", "changed_unknown")) \
        + len(rep["new"]) + len(rep["gone"])
    print(f"[PASS] step_metrics diff: {len(before)} -> {len(after)} metric(s), "
          f"{n} difference(s); {len(rep['regressed'])} regressed, "
          f"{len(rep['improved'])} improved.", file=sys.stderr)
    return RC_PASS


if __name__ == "__main__":
    raise SystemExit(main())
