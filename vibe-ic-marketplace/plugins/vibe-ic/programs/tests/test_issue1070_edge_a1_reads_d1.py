"""Step A1 declares it reads D1, so D1 must be in its ancestry. vibe-ic#1070.

THE DEFECT. `flow_step_execution_coverage_check.analyze()` is the ONLY consumer
that can contradict a step which passed its own gate over an input whose
PRODUCER failed. A1 (Analog Spec Extraction) declared TWO `required_inputs`
from D1 — `L1_DATASHEET.json` and `L5_ADI_SPEC.json` — while carrying
`blocks_on: []`, so D1 sat outside A1's ancestry and that guard was disarmed
for both. A FAILED Phase 1 could not red the analog track's entry point, which
then self-certified on the presence of its own spec files.

This is not an analogy to the step-1/D1 defect the flow already paid for and
documents at step 1 — it is the SAME defect on a second step.

A1 ALSO LEAVES `DECLARED_ROOTS`, and that is not incidental. A1 was baselined
in `flow_dependency_graph_check.DECLARED_ROOTS` as a legitimate entry point on
a justification its own `required_inputs` contradicted. With the edge declared
and that register unchanged, the checker returns **rc 1** — "A1 is a declared
entry point but now has dependencies. DECLARED_ROOTS must shrink to match."
MEASURED, and it is why a YAML-only version of this change does not work. The
register may only SHRINK, and #923 set the precedent when P0 left it for
exactly this reason.

MEASURED blast radius (#1070 criterion 2). The issue predicted 44 of 63 steps.
Diffing per-step ancestry SETS: **9** steps grow, A1 through A9 — the analog
track and nothing else. The other 35 predicted descendants already reached D1
through step 1. Corpus census: A1 records `SKIPPED-CONDITION` in all 4 published
runs carrying a per-step list, so **the corpus cannot speak to this edge** —
that zero is structural, not evidence, and is reported as such rather than
banked as a clean result.
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

FLOW = (Path(__file__).resolve().parent.parent.parent
        / "flow" / "phase1_phase2_phase3.yaml")

CONSUMER, PRODUCER = "A1", "D1"


def _steps():
    """Read the STRUCTURE, never the text (vibe-ic#1012): a grep for
    `blocks_on: [22, 24]` would pass on a commented-out line."""
    doc = yaml.safe_load(FLOW.read_text())
    out = []

    def walk(n):
        if isinstance(n, dict):
            if "id" in n and "name" in n:
                out.append(n)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(doc)
    return out


def _graph():
    steps = _steps()
    return steps, {str(s["id"]): [str(x) for x in (s.get("blocks_on") or [])]
                   for s in steps}


def _ancestry(sid, blocks_on, seen=None):
    seen = seen if seen is not None else set()
    for p in blocks_on.get(sid, []):
        if p not in seen:
            seen.add(p)
            _ancestry(p, blocks_on, seen)
    return seen


def test_step_A1_still_declares_that_it_reads_D1():
    """The premise. If this declaration is ever dropped the test below would
    pass vacuously — an edge that no longer needs guarding is trivially
    guarded — so the premise is asserted rather than assumed."""
    steps = {str(s["id"]): s for s in _steps()}
    froms = [str(e.get("from")) for e in (steps[CONSUMER].get("required_inputs") or [])]
    assert PRODUCER in froms, (
        f"step {CONSUMER} no longer declares it reads {PRODUCER}; this test's "
        f"subject is gone and it must be re-derived, not deleted")


def test_the_declared_producer_is_in_the_consumers_ancestry():
    """The repair. 24 must be reachable through `blocks_on` from 25."""
    _, blocks_on = _graph()
    anc = _ancestry(CONSUMER, blocks_on)
    assert PRODUCER in anc, (
        f"step {CONSUMER} declares `required_inputs: from {PRODUCER}` but "
        f"{PRODUCER} is not in its transitive blocks_on ancestry "
        f"{sorted(anc)} — flow_step_execution_coverage_check cannot contradict "
        f"a PASS here when {PRODUCER} FAILED")


def test_the_edge_is_declared_directly_not_only_transitively():
    """`blocks_on` names 24 itself. A transitive-only path would satisfy the
    guard today and break silently the moment the intermediate step's own
    `blocks_on` is edited by someone with no reason to think about EM."""
    _, blocks_on = _graph()
    assert PRODUCER in blocks_on[CONSUMER], blocks_on[CONSUMER]


def test_the_declared_edge_is_the_only_one():
    """22 was already there and stays. Declaring a new edge must not silently
    drop an old one — that would trade one disarmed guard for another."""
    _, blocks_on = _graph()
    assert blocks_on[CONSUMER] == ["D1"], blocks_on[CONSUMER]


def test_no_self_edge_or_cycle_was_introduced():
    """A cycle would make `_ancestry` non-terminating for real consumers and
    would make every member of the cycle its own ancestor."""
    _, blocks_on = _graph()
    assert CONSUMER not in _ancestry(CONSUMER, blocks_on)
