"""A step must not declare the same `required_outputs` entry twice.

WHY THIS EXISTS, and it is not hypothetical. On 2026-08-13 two PRs — vibe-ic#1316
and #1318 — were filed two minutes apart, both adding the SAME line to step 27:

    - "reports/phase3/si_mcf_sta.json"

They do not disagree; they are the same fix authored twice. Merged, git places the
two additions at different offsets in one list and BOTH survive: the flow yaml
merges with ZERO conflict markers and step 27 ends up declaring that path twice.
The only merge conflict is in `test_matrix_63x8_ledger.py`, so whoever resolves it
sees *a* conflict — but not this one. The duplicate arrives in the file nobody is
looking at.

And nothing caught it. Measured by taking #1316's branch alone and inserting one
exact copy of the line, changing nothing else:

    #1316 alone            12 failed, 81 passed, 3 xfailed
    #1316 + the duplicate  12 failed, 81 passed, 3 xfailed

Failure sets diffed by node id: ZERO differences. Not merely equal counts — the
same set. `flow_compliance_check.py` has no uniqueness rule for `required_outputs`,
so a duplicated declaration was not just harmless-looking, it was invisible.

WHY THE SCOPE IS **WITHIN A STEP** AND NOT GLOBAL. Two different steps declaring
the same artefact is legitimate and load-bearing — `phase2/stage2/synth/netlist.v`
is declared by two steps on `a38902d1` today. A global uniqueness rule would flag
that and be wrong. The defect is one step naming one artefact twice, which says
nothing the single declaration did not already say and inflates that step's own
denominator: the entry is counted twice in `required_outputs`, so a step with a
duplicate reports more outputs than it has.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Mapping, Sequence

from matrix_63x8 import flowref as F


def duplicated_required_outputs(
    steps: Sequence[Mapping[str, Any]],
) -> Dict[str, List[str]]:
    """``{step id: [entries declared more than once]}``. Empty means clean.

    Takes the steps rather than reading the yaml itself, so the assertion over
    the SHIPPED flow and the paired guard below run the exact same predicate.
    A guard that exercised a private copy of this logic would prove only that
    the copy works.
    """
    out: Dict[str, List[str]] = {}
    for step in steps:
        declared = step.get("required_outputs") or []
        repeats = sorted(e for e, n in Counter(declared).items() if n > 1)
        if repeats:
            out[str(step.get("id"))] = repeats
    return out


def test_no_step_declares_the_same_required_output_twice():
    """The shipped flow, which is the population that actually ships."""
    assert duplicated_required_outputs(F.steps()) == {}


def test_the_population_is_not_empty():
    """Without this, the assertion above could pass over nothing and mean nothing.

    A uniqueness check is exactly the shape that goes quietly green when its
    input vanishes: no steps, no duplicates, PASS.
    """
    steps = F.steps()
    assert len(steps) > 0
    declaring = [s for s in steps if s.get("required_outputs")]
    assert len(declaring) > 0, "no step declares required_outputs — check the loader"


def test_the_check_FIRES_on_a_duplicate_within_one_step():
    """PAIRED GUARD: the real #1316+#1318 collision, reproduced exactly."""
    entry = "reports/phase3/si_mcf_sta.json"
    steps = [{"id": 27, "required_outputs": [
        "reports/phase3/si_crosstalk.rpt OR reports/phase3/si_crosstalk.json",
        entry,
        entry,
    ]}]
    assert duplicated_required_outputs(steps) == {"27": [entry]}


def test_the_same_entry_in_TWO_DIFFERENT_steps_is_NOT_flagged():
    """The other half of the pair, and the one that keeps this rule honest.

    `phase2/stage2/synth/netlist.v` really is declared by two steps. If this
    check flagged that, the only way to green it would be to delete a true
    declaration — a fix strictly worse than the defect. So the rule must be
    provably silent here, not merely untested here.
    """
    shared = "phase2/stage2/synth/netlist.v"
    steps = [
        {"id": 13, "required_outputs": [shared]},
        {"id": 14, "required_outputs": [shared, "phase2/stage2/synth/area.rpt"]},
    ]
    assert duplicated_required_outputs(steps) == {}


def test_a_step_with_no_required_outputs_is_not_an_error():
    """Absent and empty are both clean — this rule is about repetition only."""
    assert duplicated_required_outputs([{"id": "A1"}, {"id": "A2",
                                        "required_outputs": []}]) == {}
