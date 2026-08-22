"""A declared input dependency that no ordering edge guards. vibe-ic#1070.

`flow_step_execution_coverage_check.analyze()` forces Overall FAIL when a PASS
step's transitive `blocks_on` ancestry reaches a non-PASS applicable step. It is
the ONLY consumer that can contradict a step which passed its own gate over an
input whose PRODUCER failed.

So when a step declares `required_inputs: [{from: X}]` — the flow saying, in its
own words, that this step READS X's output — and X is outside its transitive
`blocks_on` ancestry, that guard is disarmed for that edge. The step's gate runs,
prints PASS, and a FAILED X cannot contradict it.

The flow has already paid for this once and documents it at step 1: with
`blocks_on: []` no edge named D1, so Step 1 self-certified on the presence of RTL
files alone while Phase 1 had failed. It was repaired by declaring the edge —
which arms a guard that already existed.

MEASURED on v1.10.33 (`947547716`), from the YAML STRUCTURE, never its text:

    intra-flow required_inputs edges          75
    external (no such step id)                 4
    NOT in the consumer's ancestry             4   <-- on 3 distinct steps

This test asserts the property over the WHOLE flow rather than over the one edge
this PR declares, because the defect is a class and the previous two instances
were each found by collision rather than by looking.

THE ALLOWLIST IS DEBT, AND IT IS SHRINK-ONLY
--------------------------------------------
The two edges still open are listed with their issue and their measured blast
radius. They are NOT waived on merit — #1070 defers them for sequencing, because
declaring an edge is transitive and A1 -> D1 alone would newly route 44 of 71
steps through D1 while main is red, destroying the only delta anyone can read.

`test_the_allowlist_does_not_outlive_its_truth` fails when an allowlisted edge
turns out to be guarded, so a repaired edge cannot sit here being forgiven for a
reason that stopped being true. That is the failure mode a register like this
otherwise has.
"""
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN = Path(__file__).resolve().parent.parent.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

# (consumer, producer) -> why it is still open. SHRINK-ONLY.
KNOWN_UNGUARDED = {
}


def _steps():
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
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
    ids = {str(s["id"]) for s in steps}
    blocks = {str(s["id"]): [str(x) for x in (s.get("blocks_on") or [])]
              for s in steps}

    def ancestry(sid, seen=None):
        seen = set() if seen is None else seen
        for p in blocks.get(sid, []):
            if p not in seen:
                seen.add(p)
                ancestry(p, seen)
        return seen

    return steps, ids, blocks, ancestry


def _unguarded():
    """(consumer, producer) pairs the flow declares but does not order."""
    steps, ids, _blocks, ancestry = _graph()
    found = set()
    for s in steps:
        sid = str(s["id"])
        anc = ancestry(sid)
        for e in (s.get("required_inputs") or []):
            producer = str(e.get("from"))
            if producer in ids and producer not in anc:
                found.add((sid, producer))
    return found


# ---------------------------------------------------------------------------
# the edge this PR declares
# ---------------------------------------------------------------------------
def test_M1_orders_the_gds_it_declares_it_reads():
    """M1 consumes `phase3/stage4/gds/*.gds` from step 37. Without the ordering
    edge a FAILED stream-out left the A+D merge that consumes its GDS at PASS."""
    _steps_, _ids, _blocks, ancestry = _graph()
    assert "37" in ancestry("M1"), (
        "M1 declares `required_inputs: from: 37` and 37 is not in its "
        "transitive blocks_on ancestry, so a FAILED 37 cannot contradict a "
        "PASSing M1")
    assert ("M1", "37") not in _unguarded()


def test_the_declared_read_that_motivates_the_edge_is_still_declared():
    """The edge is only meaningful while the data dependency it orders exists.
    If someone removes the `from: 37` input, this ordering edge becomes an
    unexplained constraint rather than a repair."""
    m1 = [s for s in _steps() if str(s.get("id")) == "M1"]
    assert m1, "M1 not found in the flow"
    froms = {str(e.get("from")) for e in (m1[0].get("required_inputs") or [])}
    assert "37" in froms, froms


# ---------------------------------------------------------------------------
# the class, and the debt
# ---------------------------------------------------------------------------
def test_no_new_unguarded_declared_input_appears():
    """The whole point: this was found twice by collision and once by a probe.
    A NEW instance must be found by looking."""
    new = _unguarded() - set(KNOWN_UNGUARDED)
    assert not new, (
        "step(s) declare an input the ordering graph does not guard, and they "
        "are not in the known-debt list: "
        + ", ".join(f"{c} reads {p}" for c, p in sorted(new))
        + ". Declare `blocks_on` for the producer, or add it to "
          "KNOWN_UNGUARDED with an issue and a measured blast radius.")


def test_the_allowlist_does_not_outlive_its_truth():
    """A register that forgives a repaired edge is a register that has stopped
    describing the tree. Shrink-only means the entry goes when the edge does."""
    stale = set(KNOWN_UNGUARDED) - _unguarded()
    assert not stale, (
        "KNOWN_UNGUARDED still forgives edge(s) that are now guarded: "
        + ", ".join(f"{c}->{p}" for c, p in sorted(stale))
        + " — delete the entry in the same commit that repaired the edge.")


def test_the_debt_is_exactly_what_1070_measured():
    """Pinned so the count cannot drift upward quietly under a passing suite."""
    assert len(_unguarded()) == 0, sorted(_unguarded())


@pytest.mark.parametrize("consumer,producer", sorted(KNOWN_UNGUARDED))
def test_each_known_edge_is_a_real_declared_read(consumer, producer):
    """Every allowlisted entry must correspond to an actual declared input.
    An entry naming an edge the flow does not declare is forgiving nothing and
    hiding the fact."""
    step = [s for s in _steps() if str(s.get("id")) == consumer]
    assert step, f"{consumer} is not a step in this flow"
    froms = {str(e.get("from")) for e in (step[0].get("required_inputs") or [])}
    assert producer in froms, (
        f"KNOWN_UNGUARDED names {consumer}->{producer} but {consumer} declares "
        f"no such required_input (declares: {sorted(froms)})")
