#!/usr/bin/env python3
"""hygiene_shard_aggregate.py — combine sharded hygiene runs, denominator first.

vibe-ic#1144. Sharding the landing gate across six hosts is only safe if the
combined answer can state its own reach. The failure this program exists to make
impossible is not a wrong verdict — it is a RIGHT-LOOKING verdict over fewer
gates than the caller believes ran.

    71 of 71 gate(s) DECIDED across 6 shard(s), 0 NOT CHECKED

A shard that dies, is never started, or reports a gate nobody else reports must
FAIL THE WHOLE RUN. It must never reduce coverage quietly. That is this
project's founding lesson applied to its own tooling, and it applies hardest
here: the serial script had one denominator and could not lose half of it by
a host running out of disk.

WHAT IS CHECKED, AND WHY EACH ONE
=================================
  * every EXPECTED label appears in some shard's record   — nothing dropped
  * every label DECIDED exactly once across the shards     — nothing double-run,
    which would also mean two hosts mutating two trees and only one being read
  * no shard record missing / unreadable / truncated       — a dead host is a
    failure, not an absence
  * every shard agrees it was sharded (`shard` present)    — a host that ran
    UNSHARDED would decide all 71 and look like success while the plan it was
    given was ignored
  * the union's FAIL/NOT_CHECKED/WROTE_CORPUS are surfaced — the verdict itself

`--expect` is the label set the plan assigned, i.e. what SHOULD have run. It is
required: deriving the denominator from the records themselves would let a run
that lost a shard agree with itself.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082
from pathlib import Path
from typing import Dict, List

#: States in which a gate reached a verdict about its subject.
DECIDED = ("PASS", "FAIL")
#: Ran, but concluded nothing. Never folded into PASS — `_vacuous_exit`'s rule.
UNDECIDED = ("NOT_CHECKED", "WROTE_CORPUS")
#: Declared on this host, owned by another. Not a result.
ELSEWHERE = ("OTHER_SHARD", "LISTED")


def load(paths: List[Path]):
    """Read every shard record, or say precisely which one cannot be read."""
    docs, broken = [], []
    for p in paths:
        try:
            docs.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, ValueError) as exc:
            broken.append(f"{p}: {exc}")
    return docs, broken


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="combine sharded hygiene records")
    ap.add_argument("records", nargs="+", type=Path)
    ap.add_argument("--expect", type=Path, required=True,
                    help="file of every gate label the plan assigned, one per "
                         "line — the DENOMINATOR, which must come from outside "
                         "the records being checked")
    ap.add_argument("--shards", type=int,
                    help="how many shard records to expect; a missing host is "
                         "otherwise indistinguishable from one never planned")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    expected = sorted({l.strip() for l in
                       args.expect.read_text().splitlines() if l.strip()})
    if not expected:
        print("[FAIL] hygiene_shard_aggregate: the expected-label file is "
              "empty; a run over nothing is not a pass")
        return 1

    docs, broken = load(args.records)
    problems: List[str] = list(broken)

    if args.shards is not None and len(args.records) != args.shards:
        problems.append(
            f"{len(args.records)} record(s) given, {args.shards} shard(s) "
            f"planned — a host that never reported is a FAILED run, not a "
            f"smaller one")

    decided: Dict[str, List[str]] = defaultdict(list)
    undecided: Dict[str, str] = {}
    failed: List[str] = []
    wrote: List[str] = []
    seconds = 0

    for path, doc in docs:
        # `is None`, not truthiness: shard indices are 0-BASED (see
        # `hygiene_shard_plan.py --shard`, and its `assignment` array), and
        # `bool(0)` is False. Written as `if not ...`, the record from shard 0
        # — present in every sharded run, and the one the planner hands the
        # single most expensive gate — was reported as a host that had ignored
        # its plan. Every real aggregation failed, naming the one thing that
        # had not gone wrong.
        if doc.get("shard") is None:
            problems.append(
                f"{path}: carries no `shard`, so this host ran UNSHARDED while "
                f"being aggregated as a shard — its verdicts cover a different "
                f"set than the plan assigned")
        seconds = max(seconds, int(doc.get("seconds") or 0))
        for g in doc.get("gates") or []:
            label, state = str(g.get("label")), str(g.get("state"))
            if state in DECIDED:
                decided[label].append(str(doc.get("shard")))
                if state == "FAIL":
                    failed.append(label)
            elif state in UNDECIDED:
                undecided[label] = state
                if state == "WROTE_CORPUS":
                    wrote.append(label)
            elif state not in ELSEWHERE:
                problems.append(f"{path}: unknown state {state!r} for {label!r}")

    seen = set(decided) | set(undecided)
    missing = [l for l in expected if l not in seen]
    if missing:
        problems.append(
            f"{len(missing)} planned gate(s) were run by NO shard: "
            + ", ".join(missing[:8]) + (" …" if len(missing) > 8 else ""))
    twice = sorted(l for l, s in decided.items() if len(s) > 1)
    if twice:
        problems.append(
            f"{len(twice)} gate(s) decided by MORE THAN ONE shard: "
            + ", ".join(f"{l} ({'+'.join(decided[l])})" for l in twice[:5]))
    extra = sorted(seen - set(expected))
    if extra:
        problems.append(
            f"{len(extra)} gate(s) ran that the plan never assigned: "
            + ", ".join(extra[:8]))

    n_dec, n_exp = len(decided), len(expected)
    head = (f"{n_dec} of {n_exp} gate(s) DECIDED across {len(docs)} shard(s), "
            f"{len(undecided)} NOT CHECKED")
    if args.json:
        # vibe-ic#1082 — the declared report destination exists ONLY IF this
        # aggregate completed. A crashed run previously left a half-written
        # file under the FINAL name, which the next reader cannot tell from a
        # complete one; that is the whole point of the shard aggregate, which
        # exists to say what the run's reach WAS.
        atomic_write_text(args.json, json.dumps({
            "expected": n_exp, "decided": n_dec,
            "not_checked": sorted(undecided), "failed": sorted(set(failed)),
            "wrote_corpus": sorted(set(wrote)),
            "shards": len(docs), "critical_path_seconds": seconds,
            "problems": problems,
        }, indent=2) + "\n")

    for p in problems:
        print(f"  [COVERAGE] {p}")
    if problems:
        print(f"[FAIL] hygiene_shard_aggregate: {head} — and the run cannot "
              f"state its own reach, so it is not a result")
        return 1
    if wrote:
        print(f"[FAIL] hygiene_shard_aggregate: {len(wrote)} gate(s) WROTE "
              f"INTO the corpus: {', '.join(sorted(set(wrote))[:5])} [{head}]")
        return 1
    if failed:
        print(f"[FAIL] hygiene_shard_aggregate: {len(set(failed))} gate(s) "
              f"FAILED: {', '.join(sorted(set(failed))[:6])} [{head}]")
        return 1
    if undecided:
        print(f"hygiene_shard_aggregate: {head} — this is NOT a pass over: "
              + ", ".join(sorted(undecided)[:6]))
        return 0
    print(f"[PASS] hygiene_shard_aggregate: {head}; critical path {seconds}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
