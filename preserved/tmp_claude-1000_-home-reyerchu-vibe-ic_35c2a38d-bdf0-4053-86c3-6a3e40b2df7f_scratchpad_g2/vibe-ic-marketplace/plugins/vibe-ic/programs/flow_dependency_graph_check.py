#!/usr/bin/env python3
"""flow_dependency_graph_check — recompute the flow-gate's dependency dimension.

WHY
===
The flow-gate dashboard publishes 63 steps x 8 dimensions = 504 cells under the
words "every cell is a predicate recomputed against the current source, not a
stored verdict read back".

Nothing recomputes them. The page's own generator says so in its docstring and
carries the eight distributions forward untouched, so each is a judgement made
once and restated since. As of this commit, ONE of the eight is genuinely
recomputed (`flow_step_can_fail_check`, the "can this step fail" dimension).
This makes it TWO — the dependency dimension, which asks whether `blocks_on` is
declared correctly.

That dimension is fully decidable from the flow yaml, which is why it is worth
doing properly rather than assessing:

  * every `blocks_on` target must be a step that exists — a reference to an id
    the flow does not declare blocks on nothing, and the ordering guard that
    reads this graph would silently skip it;
  * the graph must be acyclic — a cycle makes "wait for your dependencies"
    unsatisfiable, and the transitive walk that enforces step ordering would
    either loop or, worse, quietly stop;
  * a step with NO dependencies is a root, and roots are a design decision. The
    declared ones are the flow's genuine entry points; a NEW root means a step
    was detached from the chain, deliberately or by an edit that dropped a line.

MEASURED on `origin/main`: 63 steps, 60 declaring dependencies, 0 dangling
references, 0 cycles, 3 roots — the Phase-1 doc entry, the analog spec entry and
the structural pre-flight. All three legitimate.

The baseline started as FOUR because the exploratory measurement was taken in a
checkout 700 commits behind, where spec-to-RTL had no dependencies; on the
current tree it blocks on the Phase-1 doc entry. This check caught that on its
first run against the real tree, which is the argument for recomputing rather
than assessing in one line.

So this dimension is CLEAN, and that is worth stating: the point of recomputing
is to know, not to find something. What it buys is that the next edit which
breaks it fails immediately instead of being restated as clean for months.

EXIT
    0  the graph is sound and the roots are the declared ones
    1  a dangling reference, a cycle, or a root that is not declared
    2  the flow could not be read or declares no steps — a check that scanned
       nothing has not passed
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set

try:
    import yaml
except ImportError:                                     # pragma: no cover
    yaml = None

# Steps that legitimately begin a chain. Like the sibling baselines in this
# repo, it MAY ONLY SHRINK — a new root is a step that fell off the chain until
# someone says otherwise, and saying otherwise means editing this line.
# vibe-ic#923 — P0 left this set when it gained the ordering edge its own
# `required_inputs: [{from: 1}]` had always implied. The set may only SHRINK,
# and this is what shrinking looks like.
# vibe-ic#1070 — A1 left it for the identical reason. A1 declared TWO
# `required_inputs` from D1 (`L1_DATASHEET.json`, `L5_ADI_SPEC.json`) while
# carrying `blocks_on: []`, so it was baselined here as a legitimate entry
# point on a justification its own declarations contradicted. Now that the
# edge is declared, keeping A1 here would be the contradiction this checker
# fails on by design ("a declared entry point but now has dependencies").
# Measured before the shrink: with the YAML edge declared and this line
# unchanged, the checker returns rc 1 on exactly that message.
DECLARED_ROOTS = {"D1"}


def load_steps(path: Path) -> Optional[List[dict]]:
    if yaml is None:
        return None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    steps: List[dict] = []

    def walk(o):
        if isinstance(o, dict):
            if "id" in o and "name" in o:
                steps.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)
    return [s for s in steps if not str(s.get("id", "")).startswith("stage")]


def find_cycles(graph: Dict[str, List[str]]) -> List[List[str]]:
    """Every cycle reachable in the dependency graph, as node paths."""
    WHITE, GREY, BLACK = 0, 1, 2
    colour = {k: WHITE for k in graph}
    cycles: List[List[str]] = []

    def visit(node: str, stack: List[str]) -> None:
        colour[node] = GREY
        stack.append(node)
        for nxt in graph.get(node, []):
            if colour.get(nxt) == GREY:
                cycles.append(stack[stack.index(nxt):] + [nxt])
            elif colour.get(nxt, WHITE) == WHITE:
                visit(nxt, stack)
        colour[node] = BLACK
        stack.pop()

    for node in list(graph):
        if colour[node] == WHITE:
            visit(node, [])
    return cycles


def analyse(steps: List[dict]) -> Dict[str, object]:
    ids: Set[str] = {str(s["id"]) for s in steps}
    dangling: Dict[str, List[str]] = {}
    roots: List[str] = []
    graph: Dict[str, List[str]] = {}
    for s in steps:
        sid = str(s["id"])
        deps = [str(x) for x in (s.get("blocks_on") or [])]
        if not deps:
            roots.append(sid)
        missing = [d for d in deps if d not in ids]
        if missing:
            dangling[sid] = missing
        # Dangling edges are excluded from the graph so cycle detection reports
        # cycles and not the consequences of a separate defect.
        graph[sid] = [d for d in deps if d in ids]
    return {"steps": len(steps), "dangling": dangling,
            "cycles": find_cycles(graph), "roots": sorted(roots),
            "new_roots": sorted(set(roots) - DECLARED_ROOTS),
            "declared_roots_absent": sorted(DECLARED_ROOTS - set(roots))}


def main(argv=None) -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--flow", type=Path,
                    default=here.parent / "flow" / "phase1_phase2_phase3.yaml")
    ap.add_argument("--json", type=Path, default=None)
    a = ap.parse_args(argv)

    if yaml is None:
        print("flow_dependency_graph_check: rc=2 NOT CHECKED — pyyaml unavailable")
        return 2
    steps = load_steps(a.flow)
    if not steps:
        print(f"flow_dependency_graph_check: rc=2 NOT CHECKED — no steps in {a.flow}")
        return 2

    rec = analyse(steps)
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(rec, indent=2, default=list) + "\n",
                          encoding="utf-8")

    problems = 0
    for sid, missing in sorted(rec["dangling"].items()):          # type: ignore
        problems += 1
        print(f"flow_dependency_graph_check: FAIL — step {sid} blocks_on "
              f"{', '.join(missing)}, which the flow does not declare. A "
              f"reference to a step that does not exist blocks on nothing, and "
              f"the ordering guard reading this graph skips it silently.")
    for cyc in rec["cycles"]:                                     # type: ignore
        problems += 1
        print(f"flow_dependency_graph_check: FAIL — dependency cycle "
              f"{' -> '.join(cyc)}. 'Wait for your dependencies' cannot be "
              f"satisfied, and the transitive walk either loops or stops.")
    for sid in rec["new_roots"]:                                  # type: ignore
        problems += 1
        print(f"flow_dependency_graph_check: FAIL — step {sid} declares no "
              f"blocks_on and is not a declared entry point. A new root is a "
              f"step that fell off the chain until someone says otherwise.")
    for sid in rec["declared_roots_absent"]:                      # type: ignore
        problems += 1
        print(f"flow_dependency_graph_check: FAIL — {sid} is a declared entry "
              f"point but now has dependencies. Good news, and DECLARED_ROOTS "
              f"must shrink to match.")

    if problems:
        return 1
    print(f"flow_dependency_graph_check: PASS — {rec['steps']} step(s), "
          f"0 dangling reference(s), 0 cycle(s), "
          f"{len(rec['roots'])} root(s) all declared")  # type: ignore
    return 0


if __name__ == "__main__":
    sys.exit(main())
