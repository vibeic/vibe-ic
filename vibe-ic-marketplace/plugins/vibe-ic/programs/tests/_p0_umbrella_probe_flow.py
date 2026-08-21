#!/usr/bin/env python3
"""Shared fixture: a flow in which P0's declared dependency chain is SATISFIED.

WHY THIS EXISTS
===============
The P0 umbrella tests drive the real `flow_compliance_check.main()` over a
`tmp_path` project with the gate runner stubbed, and assert what the umbrella
says about ITSELF — PASS on a clean fully-invoked sweep, INCOMPLETE when a
registered gate never answered, FAIL when one failed.

`P0` declares `blocks_on: [1]` and step 1 declares `blocks_on: [D1]`. A
`tmp_path` project has run neither, so on the SHIPPED 63-step flow both
ancestors are MISSING, and the step-execution ordering rule (`a PASS a
dependency contradicts is not a PASS`) correctly fires against P0.

WHEN, so nobody re-derives it: the rule landed 2026-08-03 (44e8644ac) and
these files were written two days later, GREEN — `P0` carried no `blocks_on`
edge for the rule to walk. vibe-ic#923 (332b9985e, 2026-08-11) wrote the edge
down while de-duplicating stage membership, and a dormant rule became a live
one over every P0 fixture:

    ✗ [P0] ... = PASS marked done while dependency [1] Spec-to-RTL = MISSING

which rewrites the step's own `PASS` to `PASS_VOIDED_BY_DEPENDENCY` and turns
the run red. That rule is RIGHT — a P0 PASS over RTL no Spec-to-RTL step
produced certifies nothing — and it is pinned by its own tests in
`test_pass_voided_by_dependency.py`. What it is not is the subject of these
files: it decided their verdict BEFORE the umbrella's own word could be read,
so every assertion of the form "the umbrella must still say PASS" was
answering a question about the fixture's empty project instead.

Those PASS-side assertions are half of a deliberate pairing (see
`test_p0_umbrella_verdict_coverage`'s module docstring: "a rule that refuses to
say PASS is trivially satisfiable by never saying PASS"). Losing them leaves
only the never-say-PASS half, which any degenerate predicate satisfies.

WHAT THIS BUILDS
================
A flow-def the test OWNS, derived from the shipped one so it cannot drift:

  * the shipped top-level keys, verbatim;
  * the shipped `P0` step, VERBATIM — `blocks_on` included, so the edge is
    still declared and still adjudicated, not deleted;
  * one STAND-IN per step in P0's transitive `blocks_on` ancestry, carrying its
    real id, its real stage and its real edges among the carried set, and a
    gate that PASSES on a seed file this fixture writes into the project.

So the chain P0 -> 1 -> D1 is present, is walked, and is HEALTHY. The ordering
rule runs at full strength over a satisfied dependency and finds nothing, which
is what lets the umbrella's own verdict reach the report.

Deliberately NOT `blocks_on: []` on P0, and deliberately not a project that
satisfies the real steps 1/D1: the first deletes the edge instead of satisfying
it, and the second couples every P0 test to the whole Phase-1 gate suite — the
exact coupling that produced this breakage.

The stand-ins carry NO `condition` and NO `required_outputs`. A stand-in that
went SKIPPED or MISSING would be excused-or-absent rather than satisfied, and
the fixture would go inert without saying so. `test_the_probe_flow_really_
satisfies_p0s_dependency_chain` and its seed-removed negative control pin both
directions.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]

#: The canonical flow, read for its top-level keys, its real `P0` and the real
#: ancestry P0 declares — never re-typed here, so a change to any of the three
#: reaches this fixture instead of silently desynchronising it.
FLOW_YAML = _PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"

#: The file every stand-in's gate looks for. `write_seed()` creates it; a test
#: that omits it gets the voided run back (that is the negative control).
SEED = "p0_dependency_stand_in.flag"


def _shipped() -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]],
                        Dict[str, Any], List[str]]:
    """(top-level keys, steps by id, the verbatim P0 step, P0's ancestry)."""
    doc = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))
    by_id = {str(s["id"]): s for s in doc["steps"] if s.get("id") is not None}
    p0 = next(dict(s) for s in doc["steps"] if str(s["id"]) == "P0")

    # Transitive blocks_on ancestry, in the same BFS order the ordering check
    # itself walks (`flow_step_execution_coverage_check._ancestors`).
    order: List[str] = []
    seen: set = set()
    queue = [str(x) for x in (p0.get("blocks_on") or [])]
    while queue:
        sid = queue.pop(0)
        if sid in seen or sid not in by_id:
            continue
        seen.add(sid)
        order.append(sid)
        queue.extend(str(x) for x in (by_id[sid].get("blocks_on") or []))
    top = {k: v for k, v in doc.items() if k != "steps"}
    return top, by_id, p0, order


def write_flow(path: Path) -> List[Any]:
    """Write the probe flow to PATH. Returns the stand-in ids, in flow order."""
    top, by_id, p0, order = _shipped()
    carried = set(order)
    stand_ins = [{
        "id": by_id[sid]["id"],
        "name": f"{by_id[sid].get('name', sid)} [P0 dependency stand-in]",
        "stage": by_id[sid].get("stage", "stage1"),
        "blocks_on": [x for x in (by_id[sid].get("blocks_on") or [])
                      if str(x) in carried],
        "gate": {"files_exist": [SEED]},
    } for sid in order]
    top["steps"] = stand_ins + [p0]
    # The shipped `total_steps` describes the shipped flow, not this one. It is
    # not read by `flow_compliance_check`, which counts the steps it loaded —
    # but a fixture that carries a number contradicting its own contents is the
    # shape this suite exists to catch, so it is restated rather than inherited.
    if "total_steps" in top:
        top["total_steps"] = len(top["steps"])
    path.write_text(yaml.safe_dump(top, allow_unicode=True, sort_keys=False),
                    encoding="utf-8")
    return [s["id"] for s in stand_ins]


def write_seed(project: Path) -> Path:
    """Satisfy every stand-in's gate. Omit this to get the voided run back."""
    project.mkdir(parents=True, exist_ok=True)
    seed = project / SEED
    seed.write_text("stand-in gate seed\n", encoding="utf-8")
    return seed


def stand_in_ids() -> List[Any]:
    """The ids `write_flow` will emit, without writing anything."""
    _top, by_id, _p0, order = _shipped()
    return [by_id[sid]["id"] for sid in order]
