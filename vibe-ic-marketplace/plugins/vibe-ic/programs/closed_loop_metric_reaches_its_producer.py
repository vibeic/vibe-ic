#!/usr/bin/env python3
"""closed_loop_metric_reaches_its_producer.py — can this edge be closed at all?

ENFORCEMENT: advisory

The line above is a DECLARATION, in the anchored form `flow_gate_enforcement_
audit.declared_intent` reads. Why it reports rather than refuses is measured
below, at THE VERDICT.

THE QUESTION NOTHING WAS ASKING
===============================
Two programs already read the flow's `closed_loop` declarations and neither asks
this one:

    closed_loop_edge_check ................ is the declaration WELL-FORMED?
    closed_loop_executable_coverage_check . does something ACTUALLY re-enter?
    this program .......................... COULD anything?

The middle one publishes `EXECUTABLE = 0` over 18 `DECLARED_ONLY` edges. That
number reads like a backlog — eighteen edges nobody got round to wiring. It is
not. Most of those edges cannot be wired at any amount of plumbing, and this
program is the cheap way to find out which, before somebody spends three
attempts discovering it by hand.

WHAT IT MEASURES, AND WHY THAT IS THE DECIDING FACT
===================================================
A closed-loop edge is a repair: the trigger names a quantity that is out of
bounds, and the fallback step is supposed to change the design so it is not. For
that to be possible the step being re-entered has to be able to SEE the
quantity. If it cannot, re-entering it reproduces exactly what it produced
before, and the loop is inert by construction.

Measured on the area edge (step 9 -> 1, "design__instance__area above the
design's DECLARED ceiling ... the structure has to change"):

    grep die_area_budget|area_budget|chip_area
      in deterministic_emit_chain.py, ic_class_registry.json,
         spec_artifact_registry.py                            ->  no hits

`L19.die_area_budget_um` reaches `floorplan_contract` and a set of checkers and
stops there. `step_rtl_gen` is deterministic — no random, no timestamp — so the
same L docs produce the same RTL. Re-entering it on an area overflow returns
BYTE-IDENTICAL RTL, and the loop already has a detector for that,
`FAIL_ECO_INERT`. Wiring that edge produces a loop that correctly declares
itself inert on every run.

THE THREE ANSWERS, AND WHY THEY ARE NOT TWO
===========================================
    REACHABLE      the fallback step's producers read the metric the trigger
                   names. The edge is a wiring job.
    UNREACHABLE    they do not. No amount of plumbing closes this edge; what is
                   needed is a channel from the constraint to the producer, and
                   this program names the producers that would have to grow one.
    UNSTATED       the trigger names no metric at all — it is prose. This is
                   NOT a lesser form of UNREACHABLE: an edge whose trigger says
                   "CDC/RDC violation requires RTL change" may well be closeable,
                   and the question simply cannot be put until the declaration
                   names what is out of bounds. Reported separately so a reader
                   can tell "we checked and it cannot" from "we could not check".

MEASURED ON THE SHIPPED FLOW: 21 declared edges, and exactly 2 of them name a
metric. The other 19 are UNSTATED. That ratio is the finding — a closed-loop
declaration that names no quantity cannot be reasoned about by any program,
including the two that already read these declarations.

THE VERDICT
===========
ADVISORY, and the reason is not caution. UNREACHABLE is a fact about the
tree's CAPABILITIES, not a defect a change introduced: every one of these edges
was declared before this program existed, and refusing on them would redden
every landing over debt no change owns. What blocking would be right for is a
NEW edge declared UNREACHABLE, and that needs a baseline this program does not
yet have. Until then it reports, and the report is the input to a plan.

A ZERO DENOMINATOR REFUSES (rc 2). A flow with no declared closed-loop edges has
nothing to judge, and "nothing to examine" is not "everything examined and
clean".

Chip-AGNOSTIC: the metric names come out of the flow's own trigger text and the
producer list out of the flow's own `programs:` lists. No chip, protocol or PDK
vocabulary participates.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

#: A metric identifier, as the flow's own triggers write them. Two shapes:
#: the OpenROAD/ORFS double-underscore form (`design__instance__area`,
#: `power__total`) and a dotted L-doc field (`L19.die_area_budget_um`).
#: Both are read out of the trigger text; neither is a list this file keeps.
_METRIC_RE = re.compile(
    r"\b[a-z][a-z0-9_]*__[a-z0-9_]+(?:__[a-z0-9_]+)*\b"
    r"|\bL\d+\.[A-Za-z_][A-Za-z0-9_.]*")

REACHABLE = "REACHABLE"
UNREACHABLE = "UNREACHABLE"
UNSTATED = "UNSTATED"


def _flow_path(root: Path) -> Optional[Path]:
    p = (root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "flow"
         / "phase1_phase2_phase3.yaml")
    return p if p.is_file() else None


def _programs_dir(root: Path) -> Optional[Path]:
    p = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
    return p if p.is_dir() else None


def metric_tokens(trigger: str) -> List[str]:
    """Every metric identifier a trigger names, in the order it names them."""
    out: List[str] = []
    for m in _METRIC_RE.findall(trigger or ""):
        if m not in out:
            out.append(m)
    return out


def _leaf_names(metric: str) -> Set[str]:
    """The spellings a producer could plausibly read this metric under.

    `L19.die_area_budget_um` is read as the field `die_area_budget_um`;
    `design__instance__area` is read whole or as its last segment. Both forms
    are searched, because a producer that reads the field is reading the metric
    whatever the declaration calls it.
    """
    names = {metric}
    if "." in metric:
        # `L19.die_area_budget_um` -> `die_area_budget_um`. The field name is
        # what a producer actually reads, and it is specific enough to mean
        # only this metric.
        names.add(metric.split(".")[-1])
    # THE LAST SEGMENT OF A `__` NAME IS NOT SEARCHED, and the first version of
    # this file did search it. `power__total` -> `total` matched the word
    # "total" inside `placement_legality_check` and reported the power edge
    # REACHABLE on the strength of an English word. A metric name earns a
    # producer credit only when the producer names the METRIC — the whole
    # identifier, or the L-doc field it is stored under. A shared suffix is a
    # coincidence, and crediting one turns this program from an instrument into
    # a source of false comfort about which edges are closeable.
    return {n for n in names if len(n) > 6}


def step_producers(step: dict) -> List[str]:
    """The programs a step declares — its `programs:` list plus every program
    token its gate clauses invoke. These are what would have to READ the metric
    for a re-entry to change anything."""
    out: List[str] = []
    for name in (step.get("programs") or []):
        if isinstance(name, str) and name.strip():
            out.append(name.strip().removesuffix(".py"))
    for clause in ((step.get("gate") or {}).get("all_of") or []):
        if not isinstance(clause, dict):
            continue
        for value in clause.values():
            cmd = value.get("command") if isinstance(value, dict) else value
            if isinstance(cmd, str) and cmd.strip():
                out.append(cmd.split()[0].removesuffix(".py"))
    return sorted(set(out))


def producer_reads(program: str, metric_names: Set[str],
                   programs_dir: Path) -> bool:
    """Does this program's source mention any spelling of the metric?

    DELIBERATELY GENEROUS — a bare textual mention counts. Over-crediting is the
    safe direction here: this program's job is to say an edge CANNOT be closed,
    and that accusation must survive the weakest possible reading of the
    evidence. An edge reported UNREACHABLE under a rule this loose is
    unreachable under any.
    """
    f = programs_dir / f"{program}.py"
    if not f.is_file():
        return False
    try:
        text = f.read_text(errors="replace")
    except OSError:
        return False
    return any(n in text for n in metric_names)


def audit(root: Path) -> Dict:
    flow = _flow_path(root)
    progs = _programs_dir(root)
    if flow is None or progs is None:
        return {"edges": [], "denominator": 0, "reason": "no flow or programs"}
    import yaml                                            # noqa: PLC0415
    doc = yaml.safe_load(flow.read_text(errors="replace")) or {}
    steps = {str(s.get("id")): s for s in (doc.get("steps") or [])}

    edges: List[Dict] = []
    for sid, step in steps.items():
        cl = step.get("closed_loop")
        if not isinstance(cl, dict):
            continue
        target = str(cl.get("fallback_to"))
        trigger = str(cl.get("trigger") or "")
        metrics = metric_tokens(trigger)
        row = {"step": sid, "fallback_to": target, "metrics": metrics}
        if not metrics:
            row["verdict"] = UNSTATED
            row["why"] = ("the trigger names no metric identifier, so no "
                          "program can be asked whether it reads one")
            edges.append(row)
            continue
        fallback = steps.get(target)
        if fallback is None:
            row["verdict"] = UNSTATED
            row["why"] = f"fallback step {target} is not in the flow"
            edges.append(row)
            continue
        producers = step_producers(fallback)
        names: Set[str] = set()
        for m in metrics:
            names |= _leaf_names(m)
        readers = [p for p in producers if producer_reads(p, names, progs)]
        row["fallback_producers"] = producers
        row["readers"] = readers
        if readers:
            row["verdict"] = REACHABLE
            row["why"] = (f"{len(readers)} of {len(producers)} producer(s) at "
                          f"step {target} read the metric this trigger names")
        else:
            row["verdict"] = UNREACHABLE
            row["why"] = (
                f"none of step {target}'s {len(producers)} declared producer(s) "
                f"mentions {sorted(names)}; re-entering the step cannot change "
                f"what it produces, so the loop would be inert by construction")
        edges.append(row)
    return {"edges": edges, "denominator": len(edges)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=("for every declared closed_loop edge, can the fallback "
                     "step even SEE the metric its trigger names"))
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 2

    rep = audit(root)
    n = rep["denominator"]
    if not n:
        print("[CANNOT CHECK] closed_loop_metric_reaches_its_producer: this "
              "tree declares no closed_loop edge, so there is nothing to "
              "judge. That is the ABSENCE of a question, not a pass.")
        return 2

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")

    counts = {REACHABLE: 0, UNREACHABLE: 0, UNSTATED: 0}
    for row in rep["edges"]:
        counts[row["verdict"]] += 1
        if row["verdict"] == UNREACHABLE:
            print(f"  [UNREACHABLE] {row['step']} -> {row['fallback_to']}: "
                  f"{row['why']}")
        elif row["verdict"] == REACHABLE:
            print(f"  [REACHABLE]   {row['step']} -> {row['fallback_to']}: "
                  f"{row['why']} ({', '.join(row['readers'])})")
    print(f"closed_loop_metric_reaches_its_producer: {n} declared edge(s); "
          f"REACHABLE={counts[REACHABLE]}, UNREACHABLE={counts[UNREACHABLE]}, "
          f"UNSTATED={counts[UNSTATED]} (a trigger naming no metric cannot be "
          f"asked this question). ADVISORY — reported, never blocking.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
