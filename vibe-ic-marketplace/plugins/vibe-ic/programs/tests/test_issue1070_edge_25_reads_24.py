"""Step 25 declares it reads step 24, so 24 must be in its ancestry. vibe-ic#1070.

THE DEFECT. `flow_step_execution_coverage_check.analyze()` is the ONLY consumer
that can contradict a step which passed its own gate over an input whose
PRODUCER failed — it forces Overall FAIL when a PASS step's transitive
`blocks_on` ancestry reaches a non-PASS applicable step. When a step declares
`required_inputs: [{from: X}]` and X is outside that ancestry, the guard is
disarmed for that edge: the step's gate runs, prints PASS, and a FAILED X
cannot contradict it.

Step 25 (EM lifetime) declared `from: 24  outputs: all` — it consumes the
ENTIRETY of IR-drop's output — while `blocks_on` named only 22. EM lifetime is
computed from the current densities step 24 produces, so a failed producer does
not make this consumer's verdict doubtful, it makes it meaningless.

WHY THIS TEST ASSERTS ONE EDGE AND NOT "ZERO UNGUARDED EDGES ANYWHERE".
#1070 found four such edges on three steps, and its own green-light criteria
require them landed SEPARATELY because the transitive blast radii differ by an
order of magnitude — A1 to D1 reaches 44 of 63 steps, 25 to 24 reaches 14, M1
to 37 reaches 4. A whole-flow assertion here would be RED until all three
landed, which would either block this change behind the other two or pressure
someone into bundling them. So the scope of the assertion matches the scope of
the change, and the remaining edges stay visible in `liar_census --probes
blocks` rather than in a test this PR would have to leave failing.

MEASURED before landing (#1070 criterion 2), over every published run tree that
records both steps: 4 of 4 record 24=PASS and 25=PASS, so declaring this edge
flips ZERO published verdicts. It is a guard armed for the future, not a
reinterpretation of the past.
"""
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

FLOW = (Path(__file__).resolve().parent.parent.parent
        / "flow" / "phase1_phase2_phase3.yaml")

CONSUMER, PRODUCER = "25", "24"


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


def test_step_25_still_declares_that_it_reads_24():
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


def test_the_existing_ancestry_was_not_replaced():
    """22 was already there and stays. Declaring a new edge must not silently
    drop an old one — that would trade one disarmed guard for another."""
    _, blocks_on = _graph()
    assert "22" in blocks_on[CONSUMER], blocks_on[CONSUMER]


def test_no_self_edge_or_cycle_was_introduced():
    """A cycle would make `_ancestry` non-terminating for real consumers and
    would make every member of the cycle its own ancestor."""
    _, blocks_on = _graph()
    assert CONSUMER not in _ancestry(CONSUMER, blocks_on)
