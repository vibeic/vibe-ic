#!/usr/bin/env python3
"""Merge sharded `gate_host_independence_check` runs into ONE verdict (vibe-ic#1144).

WHY A SEPARATE PROGRAM
======================
Sharding is only safe if the pieces can be proven to add back up. The danger is
not that a shard reports the wrong verdict — it is that a shard never reports at
all and the run still prints a confident green over a numerator nobody checked.
That is this repository's founding lesson pointed at its own tooling, so the
aggregator's first job is not merging, it is REFUSING to merge an incomplete set.

THE DENOMINATOR CONTRACT, enforced rather than described
========================================================
Every shard parses the FULL gate list, so each one reports the same
`gates_declared`. For the set to be complete, three things must hold and all
three are checked:

  1. every shard 0..n-1 is present, exactly once, and they agree on `n`;
  2. they agree on `gates_declared` — a shard that parsed a different script is
     answering about a different tree;
  3. probed + not_probed + deferred, summed over shards with no gate claimed
     twice, reaches `gates_declared` exactly.

Any failure is rc 2 with the missing shard or the unclaimed gate NAMED. There is
no branch that returns 0 without having satisfied all three.

WHY DEFERRED IS NOT `not_probed`
================================
`not_probed` means "this gate cannot be driven twice, and here is why" — a
permanent property of the gate. `deferred` means "another shard owns this one".
Folding them together is precisely how a lost shard would read as a declared
exclusion: the count still reaches the denominator, and the coverage is gone.

VERDICT COMPOSITION
===================
    any shard FAIL              -> FAIL     (findings concatenated)
    else any shard PASS         -> PASS
    else all NO_STIMULUS        -> NO_STIMULUS   (rc 2, never a pass — #539)
    any other state in any shard-> that state, propagated, rc 2

A single PASS among NO_STIMULUS shards is a real PASS: the stimulus lives in the
checkout, so a shard whose gates happened not to read it still ran them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

RC_OK = 0
RC_FAIL = 1
RC_UNMEASURABLE = 2


def load(paths: Sequence[Path]) -> List[Dict]:
    out = []
    for p in paths:
        try:
            out.append(json.loads(p.read_text()))
        except (OSError, ValueError) as exc:
            print(f"NOT_MEASURED: shard report {p} is unreadable "
                  f"({type(exc).__name__}: {exc}). A missing shard is missing "
                  f"coverage, never a smaller run.", file=sys.stderr)
            raise SystemExit(RC_UNMEASURABLE)
    return out


def check_complete(reports: List[Dict]) -> Optional[str]:
    """None when the set is provably complete, else the sentence that refuses."""
    if not reports:
        return ("0 shard report(s) given. An aggregate over nothing is not a "
                "pass; it is not a measurement at all.")
    shards = [r.get("shard") for r in reports]
    if any(s is None for s in shards):
        return ("a report carries no `shard` block, so it is a WHOLE-run result "
                "and cannot be combined with shards without double-counting.")
    ns = {s["n"] for s in shards}
    if len(ns) != 1:
        return f"shards disagree about the shard count: {sorted(ns)}"
    n = ns.pop()
    ks = sorted(s["k"] for s in shards)
    if ks != list(range(n)):
        missing = sorted(set(range(n)) - set(ks))
        dupes = sorted({k for k in ks if ks.count(k) > 1})
        return (f"shard set is not 0..{n - 1}: got {ks}"
                + (f"; MISSING {missing}" if missing else "")
                + (f"; DUPLICATED {dupes}" if dupes else ""))
    decl = {r.get("gates_declared") for r in reports}
    if len(decl) != 1:
        return (f"shards disagree about `gates_declared` {sorted(decl)} — they "
                f"did not all parse the same gate script, so they are not "
                f"answering about the same tree.")
    declared = decl.pop()

    probed = sum(r.get("gates_probed", 0) for r in reports)
    not_probed_labels = [g["gate"] for r in reports for g in r.get("not_probed", [])]
    deferred = [g for r in reports for g in r.get("deferred", [])]
    # A gate deferred by every shard is a gate nobody ran. Deferred counts are
    # per-shard, so the honest denominator uses the DISTINCT gates each shard
    # actually drove: probed. not_probed repeats across shards (every shard
    # skips this probe itself), so it is deduplicated before it is counted.
    distinct_not_probed = len(set(not_probed_labels))
    reach = probed + distinct_not_probed
    if reach != declared:
        never = sorted(set(deferred) - set(not_probed_labels))
        return (f"{reach} of {declared} gate(s) accounted for — "
                f"{probed} probed + {distinct_not_probed} not-probed. "
                f"{declared - reach} gate(s) were claimed by NO shard. "
                f"Deferred-by-someone: {len(set(deferred))}. "
                f"Suspects (deferred and never probed): {never[:8]}")
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("reports", nargs="+", type=Path)
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args(argv)

    reports = load(a.reports)
    why = check_complete(reports)
    if why is not None:
        print(f"NOT_MEASURED: the sharded run is INCOMPLETE and its verdict is "
              f"withheld.\n  {why}", file=sys.stderr)
        return RC_UNMEASURABLE

    declared = reports[0]["gates_declared"]
    probed = sum(r["gates_probed"] for r in reports)
    findings = [f for r in reports for f in r.get("findings", [])]
    states = [r["verdict"] for r in reports]
    not_probed = {g["gate"]: g["why"] for r in reports
                  for g in r.get("not_probed", [])}

    if "FAIL" in states:
        verdict = "FAIL"
    elif "PASS" in states:
        verdict = "PASS"
    elif all(s == "NO_STIMULUS" for s in states):
        verdict = "NO_STIMULUS"
    else:
        verdict = next(s for s in states if s not in ("PASS", "NO_STIMULUS"))

    merged = {"verdict": verdict, "gates_declared": declared,
              "gates_probed": probed, "shards": len(reports),
              "not_probed": [{"gate": g, "why": w} for g, w in sorted(not_probed.items())],
              "findings": findings}
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(merged, indent=2) + "\n")

    for label, w in sorted(not_probed.items()):
        print(f"  [NOT PROBED] {label} — {w}", file=sys.stderr)
    for f in findings:
        print(f"  [{f.get('kind')}] {f.get('gate')} — {str(f.get('detail'))[:200]}",
              file=sys.stderr)

    # THE DENOMINATOR, on every verdict line, red or green.
    line = (f"{probed} of {declared} gate(s) ran across {len(reports)} shard(s), "
            f"{len(not_probed)} NOT PROBED (each named above), 0 NOT CHECKED")
    if verdict == "FAIL":
        print(f"[FAIL] host-independence, sharded: {len(findings)} finding(s); "
              f"{line}", file=sys.stderr)
        return RC_FAIL
    if verdict == "PASS":
        print(f"[PASS] host-independence, sharded: {line}")
        return RC_OK
    print(f"[{verdict}] host-independence, sharded: {line}", file=sys.stderr)
    return RC_UNMEASURABLE


if __name__ == "__main__":
    sys.exit(main())
