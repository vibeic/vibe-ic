#!/usr/bin/env python3
"""An axis that takes ONE value on every arm was not measured under that lever.

THIS GATE BLOCKS (rc=1), AND IT IS RED ON THE TREE IT SHIPPED WITH.

WHAT IT ASKS THE REPOSITORY
===========================
Across a set of arms whose implementations PROVABLY DIFFER, an axis that takes
one distinct value on every arm is not evidence that the lever does not move
it. It is evidence that the axis was not measured under that lever. The two
readings are indistinguishable from the number alone, and only one of them is
a result.

The distinction matters because the flattering reading is the one that gets
published: "the knob has no effect on power" is a finding, and "power was never
re-measured per arm" is a hole, and they arrive as the same constant.

WHAT IT FINDS ON THIS TREE, AND WHY IT IS NOT INVENTORIED
=========================================================
`ppa-e2e/search/trials.json` — 60 arms, 60 DISTINCT knob settings
(`die_um`, `placement_density`, `spare_cell_density`), every arm carrying a
metric list. Seven axes take one value on all sixty:

    power.total_w                  0.000306   on all 60
    design.instance.count          488        on all 60
    area.instances.total.um2       5077.37    on all 60
    antenna.net.violation.count    · antenna.pin.violation.count
    placement.violation.count      · route.drc.violation.count

THE INSTRUMENT DISCRIMINATES, which is what makes the seven meaningful:
`area.design_report.um2` takes 59 distinct values over the same 60 arms and
`timing.setup.worst_slack_ns` takes 49. The constants are not an artefact of
the arms being identical — the arms differ, and those axes move.

Some of the seven may be legitimately invariant: `design.instance.count`
should not change when only floorplan density moves. THE RULE DOES NOT CLAIM
OTHERWISE. It claims the artefact cannot tell the two apart, and that a
constant must therefore be published as NOT MEASURED UNDER THIS LEVER rather
than as a measured invariance.

THE POWER AXIS IS ALREADY KNOWN TO THIS LANE, AND SAYING SO MATTERS.
`ppa-e2e/records/summary.json` records it explicitly:

    "power_invariance": {"n": 60, "distinct_values": 1,
                         "values": {"0.000306": 60},
                         "baseline": 0.000306,
                         "diagnostic_postroute": 0.000573}

So this gate does NOT discover the power constant — the lane measured it,
named it, and published both numbers beside each other. What the gate adds is
that the same question is now asked of every axis by RULE rather than by a
hand-written diagnostic for the one axis somebody suspected: six of the seven
constants it reports have no such entry in `summary.json`, and nothing was
asking about them.

That the lane had to write `power_invariance` by hand is the rule's own
argument. A constant is not self-evidently a defect or self-evidently fine;
somebody has to look, and a rule looks every time.

ONE OF THE SEVEN IS CORROBORATED FROM A SECOND, INDEPENDENT CAPTURE.
`power.total_w = 0.000306 W` is 0.306 mW — the exact figure the chip capture's
`declared_basis_matches_the_session_inputs` record names as a PRE-LAYOUT
number published under a post-layout header, "0.306 mW shipped against
0.573 mW post-route, understating total power by 46.6 per cent", from a
session that linked a 287-instance netlist and read no parasitics. Two lanes,
looking at different artefacts from different directions, land on one number.
That is why this axis is constant across sixty floorplans: it is not a power
measurement of any of them.

There is no inventory. A waiver would turn seven open questions into a green
tick, and the corroborated one is a live 46.6 per cent understatement.

THE PREDICATE
=============
For each committed multi-arm result set: read the arms, require that their
implementations provably differ (distinct knob settings), extract each arm's
metric values by NAME from its metric-record list, and report every axis whose
value set has size 1 across more than one differing arm.

METRIC RECORDS ARE A LIST KEYED BY A `metric` FIELD, not a nested dict. A
generic dict-flattener over `metrics` returns ZERO axes from all sixty arms —
measured — because the names live in a field, not in a key. A zero from that
flattener is indistinguishable from a clean result.

A record with no `value` key is NOT MEASURED and contributes no value, which is
the schema's own invariant: "0, -1 and \"\" never mean 'not measured'".

EXIT
====
  0  no axis is constant across arms that differ
  1  an axis takes one value on every differing arm
  2  cannot determine — no arm set, unreadable, or the arms do not differ
  3  bad invocation
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _atomic_artefact as _aa  # noqa: E402 — vibe-ic#1082

#: Committed multi-arm result sets. A path that does not exist is skipped, and
#: a run where NONE exists is rc 2 — never a pass.
_ARM_SETS = ("ppa-e2e/search/trials.json",)

_ARM_KEYS = ("knobs", "arm", "configuration", "candidate")


def _arms(doc) -> List[dict]:
    if isinstance(doc, list):
        return [r for r in doc if isinstance(r, dict)]
    if isinstance(doc, dict):
        for k in ("trials", "arms", "records", "candidates"):
            v = doc.get(k)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
    return []


def _lever(row: dict) -> Optional[str]:
    for k in _ARM_KEYS:
        if k in row:
            return json.dumps(row[k], sort_keys=True)
    return None


def _values(row: dict) -> Dict[str, object]:
    """metric name -> value, from the metric-record LIST.

    Not a dict flattener: the names live in a `metric` FIELD. A flattener
    returns zero axes over this shape, which reads exactly like a clean run.
    """
    out: Dict[str, object] = {}
    ms = row.get("metrics")
    if not isinstance(ms, list):
        return out
    for rec in ms:
        if not isinstance(rec, dict):
            continue
        name = rec.get("metric")
        if not name or "value" not in rec:
            continue                     # absent value == NOT MEASURED
        out[str(name)] = rec["value"]
    return out


def scan(root: Path) -> Tuple[List[dict], Dict[str, int]]:
    findings: List[dict] = []
    sets_read = 0
    arms_total = 0
    axes_total = 0
    for rel in _ARM_SETS:
        p = root / rel
        if not p.is_file():
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = _arms(doc)
        if len(rows) < 2:
            continue
        levers = {_lever(r) for r in rows if _lever(r) is not None}
        if len(levers) < 2:
            continue                     # the arms do not provably differ
        sets_read += 1
        arms_total += len(rows)
        vals: Dict[str, Set] = collections.defaultdict(set)
        for r in rows:
            for name, v in _values(r).items():
                try:
                    vals[name].add(v if not isinstance(v, list) else tuple(v))
                except TypeError:
                    vals[name].add(json.dumps(v, sort_keys=True))
        axes_total += len(vals)
        for name, vs in sorted(vals.items()):
            if len(vs) == 1:
                findings.append({"arm_set": rel, "axis": name,
                                 "arms": len(rows), "levers": len(levers),
                                 "value": repr(next(iter(vs)))[:40]})
    return findings, {"arm_sets_read": sets_read, "arms": arms_total,
                      "axes_examined": axes_total,
                      "constant_axes": len(findings)}


def _repo_root(start: Path) -> Optional[Path]:
    for p in [start] + list(start.parents):
        if (p / ".git").exists() and (p / "vibe-ic-marketplace").is_dir():
            return p
    return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--json", dest="json_out", default=None)
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 3
    try:
        root = Path(a.root).resolve() if a.root else _repo_root(
            Path(__file__).resolve())
        if root is None or not root.is_dir():
            print("[CANNOT DETERMINE] metric_constant_across_differing_arms: no "
                  "repository root. NOT a pass.", file=sys.stderr)
            return 2
        findings, denom = scan(root)
        if denom["arm_sets_read"] == 0:
            print("[CANNOT DETERMINE] metric_constant_across_differing_arms: no "
                  "multi-arm result set with provably differing arms was found. "
                  "A verdict over no arms is NOT a pass.", file=sys.stderr)
            return 2
        if a.json_out:
            _aa.write_text(Path(a.json_out), json.dumps(
                {"denominators": denom, "findings": findings}, indent=2) + "\n")
    except Exception as exc:                    # noqa: BLE001 — see rc contract
        print(f"[CANNOT DETERMINE] metric_constant_across_differing_arms: the "
              f"walk did not complete ({type(exc).__name__}: {exc}). NOT a "
              f"pass.", file=sys.stderr)
        return 2

    print(f"  arm sets read:        {denom['arm_sets_read']}")
    print(f"  arms:                 {denom['arms']}")
    print(f"  axes examined:        {denom['axes_examined']}")
    print(f"  constant across arms: {denom['constant_axes']}")

    if findings:
        print(f"\n[FAIL] {len(findings)} axis/axes take ONE value on every "
              f"provably-differing arm:")
        for f in findings:
            print(f"   {f['arm_set']}  {f['axis']:34} = {f['value']}"
                  f"   ({f['arms']} arms, {f['levers']} distinct levers)")
        print("\n  A constant here is NOT evidence the lever does not move the "
              "axis; it is\n  evidence the axis was not measured under it, and "
              "the artefact cannot tell\n  the two apart. Publish it as NOT "
              "MEASURED UNDER THIS LEVER, or re-measure\n  the axis per arm. "
              "Some may be legitimately invariant — that is exactly the\n  "
              "claim the artefact is currently unable to support.")
        return 1

    print("[PASS] metric_constant_across_differing_arms_is_not_measured: every "
          "axis moves on at least one arm.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
