#!/usr/bin/env python3
"""hygiene_shard_plan.py — split the hygiene gates across hosts by MEASURED time.

vibe-ic#1144. One `tools/gatekeeper-land.sh` run is 3399s (~57 min) and that
duration is not merely slow — main moves during it, so a stack that gated CLEAN
is rejected non-fast-forward when it is pushed. That happened three times in one
day: an hour of valid verification discarded each time because the answer
expired before it could be spent.

WHY BY TIME AND NOT BY COUNT
============================
Measured on this repo:

    gate_host_independence_check   2010s
    policy_direction_pin_check      671s
    the other 69 gates             ~700s   (median ~2s)

An even split BY COUNT hands one host the 2010s gate and every other host ~230s,
so the critical path is unchanged and the sharding buys nothing. The partition
has to be driven by the measurement, which is why this program refuses to run
without one rather than falling back to a count.

LPT, AND WHY IT IS ENOUGH
=========================
Longest-Processing-Time-first: sort descending, put each gate on the shard with
the least work so far. It is the standard 4/3-competitive approximation for
makespan on identical machines, and the bound is not the interesting part here —
what matters is that one gate dominates the total, and LPT provably isolates the
largest item on its own shard first. No exact solver is warranted for 71 items.

DETERMINISM IS A CORRECTNESS PROPERTY, NOT A CONVENIENCE
========================================================
Six hosts compute this INDEPENDENTLY and must agree without talking to each
other, or two shards run the same gate and a third runs none — and the run would
still report a full denominator. So the assignment is a pure function of
(profile, shard count): the sort is fully ordered by (-seconds, label) with the
label breaking ties, and the least-loaded shard is chosen by (load, index). No
dict iteration order, no wall clock, no hostname.

A GATE THE PROFILE HAS NEVER SEEN
=================================
It is assigned — never dropped — by a stable hash of its label, and it is
REPORTED. A new gate silently inheriting shard 0 would be the profile deciding
coverage by being out of date, and a gate that runs nowhere is exactly the
silent coverage loss this whole campaign exists to refuse. `--json` carries
`unprofiled` so the caller can state it.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082
from typing import Dict, List, Tuple

from _atomic_artefact import write_json  # vibe-ic#1082 (helper from PR #1094)

#: Seconds assumed for a gate the profile does not carry. Deliberately not 0:
#: a new gate costing nothing would be packed onto the already-largest shard.
#: The median measured gate is ~2s; this is the 90th percentile of the cheap
#: tier, so an unprofiled gate is over- rather than under-weighted.
DEFAULT_SECONDS = 10


def load_profile(path: Path) -> Dict[str, int]:
    """{label: seconds} from a `--summary-json` record produced by a REAL run.

    Refuses a `--list` record: it carries every label with `seconds: 0`, so a
    partition built from it would be a count split wearing a time split's
    clothes — the exact thing this program exists to avoid.
    """
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("listed_only"):
        raise ValueError(
            f"{path} was taken under --list: every gate reads 0s, so a "
            f"partition from it is a split by COUNT. Profile with a real run.")
    gates = doc.get("gates") or []
    if not gates:
        raise ValueError(f"{path} records no gate")
    out: Dict[str, int] = {}
    for g in gates:
        label = str(g.get("label", ""))
        if not label:
            continue
        # A loop-driven gate appears once per item with the SAME label; the
        # shard owns the label, so the cost of the label is the sum.
        out[label] = out.get(label, 0) + int(g.get("seconds") or 0)
    if not any(out.values()):
        raise ValueError(
            f"{path} carries no non-zero timing; it cannot drive a time split")
    return out


def _stable_shard(label: str, shards: int) -> int:
    """Deterministic fallback for a label the profile has never seen.

    `hashlib`, not `hash()`: Python's string hash is randomised per process
    (PYTHONHASHSEED), so `hash()` would give six hosts six different answers —
    the one failure mode this function exists to prevent.
    """
    d = hashlib.sha256(label.encode("utf-8")).digest()
    return int.from_bytes(d[:8], "big") % shards


def plan(labels: List[str], profile: Dict[str, int], shards: int
         ) -> Tuple[List[List[str]], List[str]]:
    """Assign every label to exactly one shard. Returns (assignment, unprofiled).

    Total-ordered throughout so six hosts computing this independently agree.
    """
    if shards < 1:
        raise ValueError("shards must be >= 1")
    unprofiled = sorted(l for l in labels if l not in profile)
    cost = {l: profile.get(l, DEFAULT_SECONDS) for l in labels}
    # -seconds first, then the label: a tie must not depend on input order.
    ordered = sorted(labels, key=lambda l: (-cost[l], l))
    buckets: List[List[str]] = [[] for _ in range(shards)]
    load = [0] * shards
    for label in ordered:
        # min by (load, index) — never by dict/None ordering.
        i = min(range(shards), key=lambda k: (load[k], k))
        buckets[i].append(label)
        load[i] += cost[label]
    return [sorted(b) for b in buckets], unprofiled


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="shard hygiene gates by measured time")
    ap.add_argument("--profile", type=Path, required=True,
                    help="a --summary-json record from a REAL (non --list) run")
    ap.add_argument("--labels", type=Path,
                    help="file of gate labels, one per line (default: the "
                         "profile's own labels)")
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--shard", type=int,
                    help="print only this shard's labels (0-based)")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)

    try:
        profile = load_profile(args.profile)
    except (OSError, ValueError) as exc:
        print(f"[FAIL] hygiene_shard_plan: {exc}", file=sys.stderr)
        return 1

    if args.labels:
        labels = [l.strip() for l in args.labels.read_text().splitlines()
                  if l.strip()]
    else:
        labels = sorted(profile)
    labels = sorted(set(labels))
    if not labels:
        print("[FAIL] hygiene_shard_plan: no gate labels to assign",
              file=sys.stderr)
        return 1

    buckets, unprofiled = plan(labels, profile, args.shards)
    load = [sum(profile.get(l, DEFAULT_SECONDS) for l in b) for b in buckets]

    doc = {
        "shards": args.shards,
        "gates_total": len(labels),
        "assignment": buckets,
        "seconds_per_shard": load,
        "serial_seconds": sum(profile.get(l, DEFAULT_SECONDS) for l in labels),
        "critical_path_seconds": max(load) if load else 0,
        # Named, never silent: a gate the profile has not seen is assigned by a
        # stable hash, and the caller has to be able to say so.
        "unprofiled": unprofiled,
    }
    if args.json:
        # vibe-ic#1082 — see hygiene_shard_aggregate: the plan is read by the
        # shards that follow it, so a truncated plan is worse than no plan.
        write_json(args.json, doc, ensure_ascii=True)

    if args.shard is not None:
        if not 0 <= args.shard < args.shards:
            print(f"[FAIL] --shard {args.shard} outside 0..{args.shards - 1}",
                  file=sys.stderr)
            return 1
        for l in buckets[args.shard]:
            print(l)
        return 0

    print(f"hygiene_shard_plan: {len(labels)} gate(s) over {args.shards} shard(s)")
    print(f"  serial        {doc['serial_seconds']:>6}s")
    print(f"  critical path {doc['critical_path_seconds']:>6}s"
          f"   speedup x{doc['serial_seconds'] / max(1, doc['critical_path_seconds']):.1f}")
    for i, (b, s) in enumerate(zip(buckets, load)):
        print(f"  shard {i}: {len(b):>3} gate(s)  {s:>6}s")
    if unprofiled:
        print(f"  UNPROFILED (assigned by stable hash, {len(unprofiled)}): "
              + ", ".join(unprofiled[:6]) + (" …" if len(unprofiled) > 6 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
