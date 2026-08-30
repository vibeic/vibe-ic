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

import json
import sys
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
PLUGIN = PROGRAMS.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
ENGINE = PROGRAMS / "flow_compliance_check.py"

sys.path.insert(0, str(PROGRAMS))
import flow_gate_enforcement_audit as A  # noqa: E402

#: EVERY FIELD THIS CHANGE INTRODUCES IS READ THROUGH `.get()` / `getattr`,
#: and that is not defensive style — it is what makes these controls RUN
#: against a tree that predates the change. A control that dies of KeyError on
#: the old code has observed nothing about the old code; these ones let it
#: answer, and answer wrongly.
_SECTION_KEY = "section"
_DISPATCHABLE_KEY = "dispatchable"


def _section(clause):
    return clause.get(_SECTION_KEY, "<not tagged>")


def _dispatchable(clause):
    return clause.get(_DISPATCHABLE_KEY, "<not tagged>")


def _flow(tmp_path: Path, text: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / "flow.yaml"
    p.write_text(text, encoding="utf-8")
    return p


# ─────────────────────────────────────────────────────────────────────────
# THE COUPLING. `DISPATCHED_SECTION` is a constant in one file about a read
# in another, which is exactly the shape that rots silently. This is the
# control that will not let it.
# ─────────────────────────────────────────────────────────────────────────
def test_the_engine_still_reads_exactly_the_section_this_audit_names():
    """`flow_compliance_check` dispatches from `flow.get("steps", [])`.

    Asserted against the ENGINE'S SOURCE rather than restated in prose,
    because the day it starts reading a second section this audit's
    disclosure becomes a false accusation — the opposite failure, and just as
    bad."""
    src = ENGINE.read_text(encoding="utf-8")
    needle = f'flow.get("{getattr(A, "DISPATCHED_SECTION", "steps")}", [])'
    assert needle in src, (
        f"{ENGINE.name} no longer contains {needle!r}. Either the engine "
        f"dispatches from somewhere else now — in which case "
        f"`DISPATCHED_SECTION` is wrong and this audit is accusing clauses "
        f"that DO run — or the read was spelt differently. Re-derive it; do "
        f"not update the constant on the strength of this message.")


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


def test_a_clause_under_steps_is_dispatchable(tmp_path):
    """POSITIVE control. Without it the two below are satisfied by a walker
    that calls everything unreachable."""
    cs = A.clauses_in_flow(_flow(tmp_path, _UNDER_STEPS))
    assert len(cs) == 1, cs
    assert (_section(cs[0]), _dispatchable(cs[0])) == ("steps", True), cs


def test_a_clause_outside_steps_is_not_dispatchable(tmp_path):
    """The finding, minimised: the same clause, one section over."""
    cs = A.clauses_in_flow(_flow(tmp_path, _OUTSIDE_STEPS))
    assert len(cs) == 1, cs
    assert (_section(cs[0]), _dispatchable(cs[0])) == ("stages", False), cs


def test_the_two_blobs_differ_in_nothing_but_the_section(tmp_path):
    """The A/B is a controlled comparison or it is an anecdote."""
    a = A.clauses_in_flow(_flow(tmp_path / "a", _UNDER_STEPS))
    b = A.clauses_in_flow(_flow(tmp_path / "b", _OUTSIDE_STEPS))
    key = lambda c: (c["slot"], c["gate"], c["command"])  # noqa: E731
    assert [key(c) for c in a] == [key(c) for c in b]
    assert [_dispatchable(c) for c in a] != [_dispatchable(c) for c in b], (a, b)


def test_a_gate_wired_in_both_places_is_not_a_finding(tmp_path):
    """ONE dispatchable clause is enough to reach a gate.

    A gate declared in both sections runs; reporting it would be a false
    accusation, and a report that cries wolf about a gate that DOES run is how
    the real ones get skipped."""
    rep = A.audit(_flow(tmp_path, _BOTH), PROGRAMS)
    assert [u["gate"] for u in (rep.get("undispatchable") or [])] == [], rep.get("undispatchable")
    rep_bad = A.audit(_flow(tmp_path / "x", _OUTSIDE_STEPS), PROGRAMS)
    assert [u["gate"] for u in (rep_bad.get("undispatchable") or [])] == ["alpha"], \
        rep_bad.get("undispatchable")


def test_a_document_shape_the_walker_cannot_read_is_not_called_wired(tmp_path):
    """The safe direction, asserted rather than assumed.

    `section` is None for a document that is not a mapping, and None is not
    `steps`, so such a clause reports UNREACHABLE. An unknown shape must never
    come back `dispatchable=True`: that is the one error this walker can make
    that hides a gate instead of naming one."""
    cs = A.clauses_in_flow(_flow(tmp_path, '- program_exit_zero: "alpha ."\n'))
    assert len(cs) == 1, cs
    assert (_section(cs[0]), _dispatchable(cs[0])) == (None, False), cs


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


def test_every_on_pass_review_clause_in_the_shipped_flow_IS_reachable():
    """THE FINDING IS CLOSED, AND THIS TEST IS HOW IT STAYS CLOSED.

    Its previous name ended `_is_unreachable` and its docstring said "a stage
    that gets WIRED makes this test red, which is the correct way to be told
    the finding is closing". This is that day. The six clauses moved from
    `stages[].on_pass_review.gate` into `steps:` — the only section
    `flow_compliance_check.main` reads — and the assertion inverts with them:
    every clause is now dispatchable, and one that slides back out of `steps:`
    reddens here.

    DERIVED, never typed: the count comes from the flow, so a seventh stage
    landing tomorrow is covered without editing this file."""
    stages = _stages_declaring_a_clause()
    assert stages, "no stage declares an `on_pass_review:` clause — empty denominator"
    cs = A.clauses_in_flow(FLOW)
    opr = [c for c in cs if c["gate"] == "stage_on_pass_review"]
    assert len(opr) == len(stages), (len(opr), sorted(stages))
    assert all(_dispatchable(c) is True for c in opr), opr
    assert all(_section(c) == A.DISPATCHED_SECTION for c in opr), opr
    # and the rest of the document is reachable too, so a green here is about
    # the clauses and not about a walker that lost its way.
    rest = [c for c in cs if c["gate"] != "stage_on_pass_review"]
    assert rest, "no other clause to compare against"
    assert all(_dispatchable(c) is True for c in rest), \
        [c for c in rest if _dispatchable(c) is not True][:5]


def test_the_audit_has_nothing_left_to_disclose_on_the_shipped_flow():
    """The disclosure this file was written to pin is now EMPTY, and empty is
    the claim. It used to assert `names == ["stage_on_pass_review"]` with
    `sections == ["stages"]`; the clauses were moved and the audit agrees."""
    rep = A.audit(FLOW, PROGRAMS)
    undisp = rep.get("undispatchable") or []
    assert undisp == [], undisp


def test_the_disclosure_reaches_the_console_on_both_paths(capsys, tmp_path):
    """A fact about a gate that is not running is needed whichever way the
    exit code went, so unlike `declared_weaker_than_wired` this one is not
    printed only on the PASS path.

    THE SUBJECT IS NOW A PLANTED CLAUSE, NOT THE SHIPPED FLOW. This used to run
    `A.main([])` over the shipped document and assert the disclosure appeared,
    which was a true statement about a real defect: six clauses sat outside
    `steps:`. They were moved, so asserting the disclosure on the shipped flow
    would now be asserting that the defect is still there. The machinery is
    what this test is about, so it is exercised on a flow that puts one clause
    back where the engine cannot reach it."""
    doc = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    # EVERY clause goes back under `stages:` — the exact pre-fix shape.
    # ALL of them, not one, and the reason is a property of the audit worth
    # knowing: `undispatchable` groups BY GATE PROGRAM, so a gate with five
    # dispatchable clauses and one stranded is not disclosed at all. Moving a
    # single clause here would therefore have proved nothing. Per-CLAUSE
    # coverage is `on_pass_review_declared_command_runs_check` P1, which keys
    # on the stage.
    moved = []
    for st in doc["steps"]:
        for sub in ((st.get("gate") or {}).get("all_of") or []):
            if isinstance(sub, dict):
                for k, v in list(sub.items()):
                    # BOTH legal clause shapes. `_evaluate_gate` accepts a bare
                    # command STRING or the dict form `{command: ...}`, and a
                    # clause carrying `advisory_reason:` must be the dict form.
                    # Matching only the string form made this walk find nothing,
                    # so the test failed on its own setup assertion instead of
                    # on the disclosure it exists to prove.
                    cmd_v = v.get("command") if isinstance(v, dict) else v
                    if (isinstance(cmd_v, str)
                            and cmd_v.startswith("stage_on_pass_review")):
                        sub.pop(k)
                        moved.append(cmd_v)
    assert moved, "no on-pass clause found under `steps:` to move back"
    for cmd in moved:
        sid = cmd.split("--stage ", 1)[1].split()[0]
        target = next(s for s in doc["stages"] if s["id"] == sid)
        target["on_pass_review"]["gate"] = {"program_exit_zero": cmd}
    planted = tmp_path / "flow.yaml"
    planted.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")

    rc = A.main(["--flow", str(planted)])
    out = capsys.readouterr().out
    assert rc in (0, 1), rc
    assert "sit OUTSIDE `steps:`" in out, out[-3000:]
    assert "stage_on_pass_review" in out, out[-3000:]


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
