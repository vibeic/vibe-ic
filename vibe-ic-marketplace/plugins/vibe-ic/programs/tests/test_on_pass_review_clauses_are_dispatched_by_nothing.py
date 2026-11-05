#!/usr/bin/env python3
"""A gate clause outside `steps:` is declared and dispatched by nothing.

WHAT WAS MEASURED, on 4689d581d (v1.13.25), before any of this was written.

Five stages declare an `on_pass_review:` block with its own `gate:` clause —
stage1, stage2, stage_analog, stage3, stage4 — and all five live under the
flow document's top-level `stages:` list. `flow_compliance_check.main` reads
`steps = flow.get("steps", [])` and evaluates gates from that list only; it
never reads `stages:`, and the string `on_pass_review` does not appear in it.

  * ON A REAL PUBLISHED CELL (`ic/spm/v1.10.18_sky130A`),
    `flow_compliance_check` dispatched 125 gates. `stage_on_pass_review`
    appears in that ledger ZERO times. The report enumerates 68 steps — exactly
    `len(flow["steps"])` — and none of the five stage ids is among them.

  * THE POSITIVE CONTROL, in the same run: `synth_netlist_check`,
    `provenance_check` and `slot_pad_budget_check` are step-level
    `program_exit_zero` clauses and all three ARE in the ledger. The ledger is
    not blind to the clause kind.

  * THE A/B THAT ISOLATES THE CAUSE. The same flow, with ONE of the five
    clauses moved into a `steps:` entry (step 9) and nothing else changed:
    ledger 125 -> 126, `stage_on_pass_review` invoked once, `rc=0 PASS`.
    Where the clause sits is the whole of it.

  * AND THE SECOND, INDEPENDENT DEFECT. The same move, with the clause left
    VERBATIM as `stages:` declares it — no `--stage-verdict`, no
    `--compliance` — is dispatched and returns `rc=2`, which
    `flow_compliance_check` scores VACUOUS_PASS. The declared argv cannot
    reach ACCEPT or REJECT, so wiring alone would not have made it a gate.

WHY THIS AUDIT AND NOT A NEW ONE. `flow_gate_enforcement_audit` already has the
right words for this state, in its own `orphaned` comment: "not even the final
compliance audit reaches it, so it runs only if someone invokes it by hand".
But ORPHANED means "not referenced by the flow definition at all", and these
clauses ARE referenced — somewhere the engine never looks. So they scored
AUDIT_ONLY, whose definition at the top of that file is "its verdict cannot
stop the step", which asserts the final audit RUNS it. MEASURED: the rows for
`provenance_check` and `stage_on_pass_review` came back byte-identical —
`AUDIT_ONLY` / `NOT_INVOKED` — while one of them ran 125-deep in the ledger and
the other never ran at all. Two opposite facts under one word.

NOTHING IS REWIRED HERE, deliberately. A step's `gate:` cannot express
`fires_on: stage_pass`, so WHERE these five belong is a flow owner's decision,
and #1253's rule applies: wiring a gate that has never run turns "unverified"
into "blocking", which is a different change.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
ENGINE = PROGRAMS / "flow_compliance_check.py"

sys.path.insert(0, str(PROGRAMS))

#: EVERY FIELD THIS CHANGE INTRODUCES IS READ THROUGH `.get()` / `getattr`,
#: and that is not defensive style — it is what makes these controls RUN
#: against a tree that predates the change. A control that dies of KeyError on
#: the old code has observed nothing about the old code; these ones let it
#: answer, and answer wrongly.
_SECTION_KEY = "section"
_DISPATCHABLE_KEY = "dispatchable"








# ─────────────────────────────────────────────────────────────────────────
# THE COUPLING. `DISPATCHED_SECTION` is a constant in one file about a read
# in another, which is exactly the shape that rots silently. This is the
# control that will not let it.
# ─────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────
# THE TWO DIRECTIONS, on planted blobs that cannot rot when the flow moves.
# ─────────────────────────────────────────────────────────────────────────
_UNDER_STEPS = """
steps:
  - id: 9
    gate:
      all_of:
        - program_exit_zero: "alpha ."
"""

_OUTSIDE_STEPS = """
stages:
  - id: stage1
    on_pass_review:
      gate:
        program_exit_zero: "alpha ."
"""

_BOTH = """
steps:
  - id: 9
    gate:
      all_of:
        - program_exit_zero: "alpha ."
stages:
  - id: stage1
    on_pass_review:
      gate:
        program_exit_zero: "alpha ."
"""












# ─────────────────────────────────────────────────────────────────────────
# THE SHIPPED FLOW — a NON-EMPTY DENOMINATOR on the real document.
# ─────────────────────────────────────────────────────────────────────────
def _on_pass_review_stages():
    """`{stage id: its on_pass_review block}` for every stage that declares one."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    found = {}

    def walk(node, sid=None):
        if isinstance(node, dict):
            here = str(node["id"]) if "id" in node else sid
            if "on_pass_review" in node:
                found[here] = node["on_pass_review"]
            for v in node.values():
                walk(v, here)
        elif isinstance(node, list):
            for v in node:
                walk(v, sid)

    walk(doc)
    return found


def _stages_declaring_a_clause():
    """Only the stages whose `on_pass_review:` carries a `gate:` clause.

    NOT every stage that declares a review. `stage5_manufacturing` (landed
    v1.13.27) declares one with `enabled: false`, a measured
    `not_enabled_reason` ("0 of 105 published run roots"), and NO `gate:` — so
    it declares a gap rather than a gate, and its own note says why: "not
    wired, so nothing reports a review it did not perform". That is the honest
    form of the state this file reports, and counting it as a finding would
    punish the one stage that got it right."""
    return {sid: opr for sid, opr in _on_pass_review_stages().items()
            if opr.get("dispatched_by") is not None}








def test_a_stage_that_declares_a_gap_is_not_counted_as_a_gate():
    """The contrast, pinned, because it is the whole difference this file is
    about: DECLARED AND UNWIRED WITH THE REASON WRITTEN DOWN is not the same
    state as DECLARED AND UNWIRED WITH NOTHING SAID.

    `stage5_manufacturing` carries `enabled: false`, a measured
    `not_enabled_reason`, and no `gate:`. If it ever grows a `gate:` clause it
    joins the finding above automatically — which is the correct way round."""
    all_stages = _on_pass_review_stages()
    with_clause = _stages_declaring_a_clause()
    gapless = sorted(set(all_stages) - set(with_clause))
    assert gapless, (
        "every stage that declares an on_pass_review now carries a gate "
        "clause, so this contrast has no subject; if that is deliberate, this "
        "test is the place to say so")
    for sid in gapless:
        opr = all_stages[sid]
        assert opr.get("enabled") is False, (sid, opr.get("enabled"))
        assert (opr.get("not_enabled_reason") or "").strip(), (
            f"{sid} declares a review with no gate and no "
            f"`not_enabled_reason`: that is a gap nobody can tell from an "
            f"oversight")
    # THE TWO RECORDS OF ONE FACT, COMPARED. The flow says `enabled: false`;
    # the program keeps the same stage out of `_RULES` and in
    # `_DECLARED_NOT_ENABLED`. Two places, one fact, and this is what stops
    # them drifting — a stage the flow re-enables while the program still
    # refuses it would otherwise read as wired from one side and not the
    # other.
    import stage_on_pass_review as S  # noqa: PLC0415
    assert sorted(S._DECLARED_NOT_ENABLED) == gapless, (
        sorted(S._DECLARED_NOT_ENABLED), gapless)
    assert sorted(S._RULES) == sorted(with_clause), (
        sorted(S._RULES), sorted(with_clause))
