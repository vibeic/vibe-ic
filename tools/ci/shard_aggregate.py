#!/usr/bin/env python3
"""shard_aggregate.py — combine sharded hygiene-gate runs into ONE verdict.

vibe-ic#1144, step 4. The piece that makes the other three trustworthy: a
sharded gate is only as good as the thing that proves every shard ran.

THE DENOMINATOR IS THE WHOLE POINT
==================================
One full `tools/gatekeeper-land.sh` is 3399 s. Sharding it across the fleet
buys ~8 minutes — and buys, with it, a brand-new way to be wrong that the
serial run never had: **a shard that dies quietly.** If the aggregate is the
union of whatever shard files happen to exist, a dead host does not fail the
run, it shrinks the population, and the roll-up says PASS over a smaller world
without anyone able to see it.

That is this project's founding lesson pointed at its own tooling, so this
program refuses the shape structurally:

  * the expected set of gates comes from a ROSTER, produced by
    `repo_hygiene_gates.sh --list --summary-json` — the same script the shards
    run, so the two cannot drift;
  * the expected number of SHARDS is stated by the caller (`--expect-shards`)
    or by naming each one (`--shard`). **Never a glob of what exists**, because
    a glob cannot tell "this host reported nothing" from "this host was never
    asked";
  * every roster gate must be claimed by exactly one shard. Missing → the run
    fails. Claimed twice → the run fails, because two shards running one gate
    means the split is wrong and coverage was being double-counted;
  * a label no roster knows fails too: a shard running something the roster
    does not list means the shards and the roster are looking at different
    trees.

WHY DUPLICATES ARE A FAILURE AND NOT A MERGE
============================================
The tempting reading of two shards reporting `chip-AGNOSTIC source guard` is
"good, it was checked twice". It is not. The shard split is supposed to
PARTITION the roster; a label in two shards means some other label is in none,
and the count still reaches the roster total. Accepting duplicates would make
the denominator satisfiable by a broken split — the arithmetic would agree
while the coverage did not.

VERDICT PRECEDENCE, and why NOT_CHECKED never folds into PASS
=============================================================
    WROTE_CORPUS  a gate changed the tree every later gate reads
    FAIL          a gate found a defect
    NOT_CHECKED   a gate declined to look (rc 2)
    PASS          a gate reached a verdict and it was clean

`_gate_dispatch.sh` keeps these in separate buckets on purpose and this program
keeps them separate too. A run with 73 PASS and one NOT_CHECKED has not checked
74 gates, and the sentence it prints says so.

EXIT CODES
==========
    0   every roster gate ran and every one of them passed
    1   the shards ran but the result is not clean — a FAIL, a WROTE_CORPUS,
        or a NOT_CHECKED. A defect, or a refusal, that a reader must act on.
    2   the aggregate COULD NOT BE ESTABLISHED — a shard file is missing or
        unreadable, the roster is unusable, a gate is unclaimed or claimed
        twice. "I could not measure" is not "I measured and it was clean", and
        `run` in `_gate_dispatch.sh` (tolerate=0) turns either into a red suite,
        so both block a landing.

chip-AGNOSTIC: it reads process records, never a design.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

RC_OK, RC_NOT_CLEAN, RC_UNESTABLISHED = 0, 1, 2

#: States a gate can carry in a shard record. `LISTED` means the gate was
#: declared but deferred (a `--list` run), which is a roster, never a result.
_RAN_STATES = ("PASS", "FAIL", "NOT_CHECKED", "WROTE_CORPUS")
_LISTED = "LISTED"


class Problem(Exception):
    """Raised when the aggregate cannot be established at all (rc 2)."""


def _load(path: Path, what: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        raise Problem(
            f"{what} {path} does not exist — a shard that produced no record "
            f"is a shard whose gates were NOT checked, and this run cannot say "
            f"otherwise") from None
    except (OSError, json.JSONDecodeError) as exc:
        raise Problem(
            f"{what} {path} could not be read as JSON ({exc}) — a truncated "
            f"record is what a host that died mid-write leaves behind") from None
    if not isinstance(doc, dict) or "gates" not in doc:
        raise Problem(
            f"{what} {path} is not a gate-dispatch summary "
            f"(no 'gates' key) — refusing to guess its shape")
    return doc


def roster_labels(doc: dict, path: Path) -> List[str]:
    labels = [g.get("label", "") for g in doc.get("gates", [])]
    if not labels:
        raise Problem(
            f"roster {path} declares no gates — an aggregate over an empty "
            f"roster is satisfied by every possible set of shards, which is "
            f"the vacuous pass this program exists to refuse")
    dupes = sorted({l for l in labels if labels.count(l) > 1})
    if dupes:
        raise Problem(
            f"roster {path} declares the same label more than once "
            f"({', '.join(dupes[:3])}) — labels are this program's identity "
            f"key and a repeated one makes coverage unprovable")
    return labels


def claims(shards: Sequence[Tuple[Path, dict]]) -> Dict[str, List[Tuple[Path, str]]]:
    """label -> [(shard path, state)], counting only gates that actually RAN."""
    out: Dict[str, List[Tuple[Path, str]]] = {}
    for path, doc in shards:
        if doc.get("listed_only"):
            raise Problem(
                f"shard {path} is a --list record (listed_only), not a run — "
                f"it declares gates without executing any of them")
        for g in doc.get("gates", []):
            state = g.get("state", "")
            if state == _LISTED:
                continue
            out.setdefault(g.get("label", ""), []).append((path, state))
    return out


def aggregate(roster: List[str],
              shards: Sequence[Tuple[Path, dict]]) -> Tuple[int, List[str]]:
    """(exit code, lines to print). Raises Problem when unestablishable."""
    seen = claims(shards)

    unknown = sorted(set(seen) - set(roster))
    if unknown:
        raise Problem(
            f"{len(unknown)} label(s) reported by a shard are not in the "
            f"roster ({', '.join(unknown[:3])}) — the shards and the roster "
            f"are describing different trees")

    missing = [l for l in roster if l not in seen]
    doubled = sorted(l for l, c in seen.items() if len(c) > 1)
    if missing or doubled:
        detail = []
        if missing:
            detail.append(f"{len(missing)} gate(s) claimed by NO shard: "
                          + ", ".join(missing[:5]))
        if doubled:
            detail.append(f"{len(doubled)} gate(s) claimed by MORE THAN ONE "
                          f"shard: " + ", ".join(doubled[:5]))
        raise Problem(
            f"the shard split does not partition the roster — "
            + "; ".join(detail)
            + f". {len(seen)} of {len(roster)} gate(s) accounted for")

    tally = {s: 0 for s in _RAN_STATES}
    offenders: Dict[str, List[str]] = {s: [] for s in _RAN_STATES}
    for label in roster:
        state = seen[label][0][1]
        if state not in tally:
            raise Problem(
                f"gate '{label}' carries an unknown state {state!r} — this "
                f"program will not map a state it does not recognise onto a "
                f"verdict")
        tally[state] += 1
        offenders[state].append(label)

    ran = sum(tally.values())
    lines = [
        f"shard_aggregate: {ran} of {len(roster)} gate(s) ran across "
        f"{len(shards)} shard(s) — {tally['PASS']} passed, "
        f"{tally['FAIL']} failed, {tally['NOT_CHECKED']} NOT CHECKED, "
        f"{tally['WROTE_CORPUS']} wrote the corpus"
    ]

    # Loop denominators survive aggregation. A corpus that expanded to ZERO is
    # invisible in `gates` by construction (it produced none), so it has to be
    # carried across explicitly or sharding would lose the one disclosure
    # vibe-ic#957 exists to make.
    for path, doc in shards:
        for c in doc.get("corpora", []):
            if c.get("items", 0) == 0:
                lines.append(
                    f"  loop corpus \"{c.get('name')}\" expanded over 0 item(s)"
                    f" — it declared 0 gate(s) and NOTHING was checked over it")
            else:
                lines.append(
                    f"  loop corpus \"{c.get('name')}\" expanded over "
                    f"{c['items']} item(s) -> {c.get('gates')} gate(s); those "
                    f"verdicts cover {c['items']} item(s), NOT the corpus")
        for u in doc.get("undisclosed_loops", []) or []:
            lines.append(f"  UNDISCLOSED LOOP in {path.name}: {u}")

    rc = RC_OK
    for state in ("WROTE_CORPUS", "FAIL", "NOT_CHECKED"):
        if tally[state]:
            rc = RC_NOT_CLEAN
            lines.append(f"  {state}: " + ", ".join(offenders[state][:10]))
    lines.append("[PASS] shard_aggregate: every declared gate ran and passed"
                 if rc == RC_OK else
                 "[FAIL] shard_aggregate: the sharded run is NOT clean")
    return rc, lines


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="shard_aggregate")
    ap.add_argument("--roster", required=True,
                    help="summary JSON from `repo_hygiene_gates.sh --list`")
    ap.add_argument("--shard", action="append", default=[],
                    help="a shard's summary JSON (repeatable)")
    ap.add_argument("--shards-dir",
                    help="directory of shard JSONs; requires --expect-shards")
    ap.add_argument("--expect-shards", type=int,
                    help="how many shards MUST be present. Never inferred: a "
                         "glob cannot tell a dead host from an unasked one")
    a = ap.parse_args(argv)

    try:
        paths = [Path(p) for p in a.shard]
        if a.shards_dir:
            if a.expect_shards is None:
                raise Problem(
                    "--shards-dir without --expect-shards would aggregate "
                    "whatever happens to be on disk, so a host that died "
                    "would silently shrink the population instead of failing "
                    "the run")
            paths += sorted(Path(a.shards_dir).glob("*.json"))
        if not paths:
            raise Problem("no shard records named — nothing to aggregate")
        if a.expect_shards is not None and len(paths) != a.expect_shards:
            raise Problem(
                f"expected {a.expect_shards} shard record(s), found "
                f"{len(paths)} — the missing one's gates are UNCHECKED and "
                f"this run will not report a verdict over them")
        roster_doc = _load(Path(a.roster), "roster")
        roster = roster_labels(roster_doc, Path(a.roster))
        shards = [(p, _load(p, "shard")) for p in paths]
        rc, lines = aggregate(roster, shards)
    except Problem as exc:
        sys.stderr.write(f"UNESTABLISHED: {exc}\n")
        sys.stderr.write(
            "This is NOT a pass. The sharded run could not state its own "
            "reach, so it has not checked anything it can vouch for.\n")
        return RC_UNESTABLISHED

    print("\n".join(lines))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
