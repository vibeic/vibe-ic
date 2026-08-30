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

from _atomic_artefact import write_json  # vibe-ic#1082 (helper from PR #1094)

#: States in which a gate reached a verdict about its subject.
DECIDED = ("PASS", "FAIL")
#: Ran, but concluded nothing. Never folded into PASS — `_vacuous_exit`'s rule.
UNDECIDED = ("NOT_CHECKED", "WROTE_CORPUS")
#: Declared on this host, owned by another. Not a result.
ELSEWHERE = ("OTHER_SHARD", "LISTED")
#: The owning shard decided, before running it, that this change touches none of
#: what the gate declares it reads. `_gate_dispatch.sh` gives it its own state
#: for a reason it writes down: "not a PASS (nothing ran and nothing was
#: examined), not NOT_CHECKED (the gate is perfectly able to run — it simply has
#: nothing here to say)". So it is a FOURTH class here too. Folding it into
#: DECIDED would be this program certifying gates that never executed; folding
#: it into ELSEWHERE would make it invisible and let a shard that scoped
#: EVERYTHING out report a full denominator; and leaving it unlisted — which is
#: what this file did until 2026-08-25 — makes every scoped run refuse with
#: `unknown state 'OUT_OF_SCOPE'`, which is a false alarm and, worse, one that
#: hides the real coverage answer behind a parse error.
NOT_ASKED = ("OUT_OF_SCOPE",)

# TWO QUESTIONS, TWO EXIT CODES — and until vibe-ic#1892 they shared one.
#
# This program answers a COVERAGE question ("can the run state its own reach?")
# and, because it holds the union, it also reports the VERDICT it finds there
# ("did a gate FAIL / write into the corpus?").  Both refusals returned 1, so a
# caller asking the first question read the answer to the second.
#
# `repo_hygiene_parallel` is that caller.  It calls this program to police the
# plan and folds a non-zero rc into its `problems` list, which `_merge` renames
# `parallel coverage: …` and `gatekeeper_review._hygiene_verdict` reports as
# "the hygiene set produced NO RECORD for N of its own shards, so it certifies
# nothing".  MEASURED on 7203d6fce (v1.13.39), one full hygiene set, 501s:
#
#     146/146 gate(s) ran, 9 of 9 shard records present, every planned label
#     decided exactly once — and 6 gates FAILED.
#     -> [FAIL] hygiene_shard_aggregate: 6 gate(s) FAILED: … (rc 1, and NOT ONE
#        [COVERAGE] line, because there was no coverage problem)
#     -> gatekeeper_review: "ERROR — the hygiene set produced NO RECORD for 1 of
#        its own shards … see the [COVERAGE] lines above"  rc 2
#
# Nothing had been lost.  The six FAILs were upgraded to UNKNOWN and the reader
# was sent to look for a shard that never existed, at "[COVERAGE] lines" that
# were never printed.  So the hygiene set could not report a red at all: any
# gate going FAIL collapsed the whole set to "certifies nothing".
#
# rc 2 is this repo's "the question could not be put", which is exactly what an
# unaccountable denominator is, and it is what this program exists to say.  rc 1
# keeps its older meaning: the reach IS accountable and the verdict over it is
# FAIL.  NOTHING IS SILENCED — every refusal that returned non-zero before still
# returns non-zero, every [COVERAGE]/[FAIL] line is unchanged, and the caller
# still refuses to certify a run whose coverage cannot be stated.
#: The run cannot state its own reach: a lost/duplicated/unplanned gate, a
#: missing or unreadable shard record, a host that ignored its shard assignment,
#: or an empty denominator.  UNKNOWN — not pass, not fail.
COVERAGE_UNACCOUNTABLE = 2
#: The reach is accountable and the verdict over it is FAIL: a gate FAILED, or a
#: gate WROTE INTO the corpus it was auditing.
VERDICT_FAILED = 1


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
        # The declared record is written FIRST even here: a caller that reads
        # the machine answer must not be blind precisely when the denominator
        # is the thing that is missing.
        if args.json:
            write_json(args.json, {
                "expected": 0, "decided": 0, "not_checked": [],
                "out_of_scope": [], "failed": [], "wrote_corpus": [],
                "shards": len(args.records), "critical_path_seconds": 0,
                "problems": ["the expected-label file is empty; a run over "
                             "nothing cannot state its reach"],
            }, ensure_ascii=True)
        print("[FAIL] hygiene_shard_aggregate: the expected-label file is "
              "empty; a run over nothing is not a pass")
        return COVERAGE_UNACCOUNTABLE

    docs, broken = load(args.records)
    problems: List[str] = list(broken)

    if args.shards is not None and len(args.records) != args.shards:
        problems.append(
            f"{len(args.records)} record(s) given, {args.shards} shard(s) "
            f"planned — a host that never reported is a FAILED run, not a "
            f"smaller one")

    decided: Dict[str, List[str]] = defaultdict(list)
    undecided: Dict[str, str] = {}
    not_asked: Dict[str, str] = {}
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
            elif state in NOT_ASKED:
                not_asked[label] = state
            elif state not in ELSEWHERE:
                problems.append(f"{path}: unknown state {state!r} for {label!r}")

    seen = set(decided) | set(undecided) | set(not_asked)
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
            f"{len(undecided)} NOT CHECKED, {len(not_asked)} OUT OF SCOPE")
    if args.json:
        # vibe-ic#1082 — the declared report destination exists ONLY IF this
        # aggregate completed. A crashed run previously left a half-written
        # file under the FINAL name, which the next reader cannot tell from a
        # complete one; that is the whole point of the shard aggregate, which
        # exists to say what the run's reach WAS.
        write_json(args.json, {
            "expected": n_exp, "decided": n_dec,
            "not_checked": sorted(undecided), "out_of_scope": sorted(not_asked),
            "failed": sorted(set(failed)),
            "wrote_corpus": sorted(set(wrote)),
            "shards": len(docs), "critical_path_seconds": seconds,
            "problems": problems,
        }, ensure_ascii=True)

    for p in problems:
        print(f"  [COVERAGE] {p}")
    if problems:
        print(f"[FAIL] hygiene_shard_aggregate: {head} — and the run cannot "
              f"state its own reach, so it is not a result")
        return COVERAGE_UNACCOUNTABLE
    if wrote:
        print(f"[FAIL] hygiene_shard_aggregate: {len(wrote)} gate(s) WROTE "
              f"INTO the corpus: {', '.join(sorted(set(wrote))[:5])} [{head}]")
        return VERDICT_FAILED
    if failed:
        print(f"[FAIL] hygiene_shard_aggregate: {len(set(failed))} gate(s) "
              f"FAILED: {', '.join(sorted(set(failed))[:6])} [{head}]")
        return VERDICT_FAILED
    if undecided or not_asked:
        print(f"hygiene_shard_aggregate: {head} — this is NOT a pass over: "
              + ", ".join(sorted(set(undecided) | set(not_asked))[:6]))
        return 0
    print(f"[PASS] hygiene_shard_aggregate: {head}; critical path {seconds}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
