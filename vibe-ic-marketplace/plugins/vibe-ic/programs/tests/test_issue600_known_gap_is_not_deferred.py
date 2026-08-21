"""#600 — a documented KNOWN GAP was hidden behind an unrelated waiver.

M2/M3/M4 were reported `DEFERRED-BY-UPSTREAM(13)` — step 13 being the LEC
equivalence check, WAIVED-DEFERRED — under the sentence

    "this step consumes outputs that step 13's waiver deferred
     — same waiver, not an independent gap"

None of that was established. `blocks_on` is an ORDERING edge, and the cascade
inferred a DATA-FLOW claim from it. Measured on the shipped flow:

    `inputs:` declarations                              0
    `required_outputs` declarations                    61
    (step, transitive-ancestor) pairs               1221
    pairs sharing ANY declared output                   1

So the claim cannot be checked from the flow at all — which is why the fix is
not a stronger predicate over outputs (that would kill 1220 of 1221 legitimate
cascades) but a refusal to SOFTEN a verdict on evidence that does not exist.

WHY IT MATTERED. `DEFERRED-BY-UPSTREAM` reads softer than `MISSING` and carries
an implicit roadmap — close the upstream item and these come back. Closing step
13 would have moved none of them: M3 and M4 FAIL on their own declared inputs,
and M2's own flow entry had said "KNOWN GAP, deliberately left declared and RED"
since M2-d4. That text was a COMMENT, so the cascade could not see it. It is a
`known_gap:` declaration now.

VERIFIED END TO END on a real mixed-signal project, which is the report the
issue quotes:

    · [MISSING] Step M2 …  [known-gap(M2)]
    · [MISSING] Step M3 …  [blocked-by-known-gap(M2)]
    · [MISSING] Step M4 …  [blocked-by-known-gap(M2)]

ATTRIBUTION WITHOUT SOFTENING is the shape: M3 and M4 still say what blocks
them, and the verdict stays the true one.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest
import yaml

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_FLOW = _PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"


def _load():
    spec = importlib.util.spec_from_file_location(
        "flow_compliance_check", _PROGRAMS / "flow_compliance_check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["flow_compliance_check"] = mod
    spec.loader.exec_module(mod)
    return mod


FC = _load()


def _res(sid, status, name="s"):
    return FC.StepResult(id=sid, name=name, stage="x", status=status)


def _steps(*specs):
    return [dict(s) for s in specs]


def _cascade(steps, results, waivers=None):
    return FC._attribute_cascade_verdicts(results, steps, waivers or {})


# vibe-ic#776 — softening now requires a DECLARED dependency, not just a
# `blocks_on` edge, so the fixtures below say which step writes the artefact
# and which step's gate reads it. Before #776 these specs carried no
# declaration at all and softened anyway; `test_the_same_chain_without_the_
# declaration_does_not_soften` is the control that pins the difference.
_ART = "reports/phase2/some_artifact.json"


def _writes(sid, **extra):
    return dict(id=sid, required_outputs=[_ART], **extra)


def _reads(sid, blocks_on, **extra):
    return dict(id=sid, blocks_on=list(blocks_on),
                gate={"files_exist": [_ART]}, **extra)


# ── a declared gap is never softened ────────────────────────────────────────
def test_a_step_declaring_its_own_gap_stays_missing():
    steps = _steps({"id": 13}, {"id": "M2", "blocks_on": [13],
                                "known_gap": "no emitter writes these"})
    results = [_res(13, "WAIVED"), _res("M2", "MISSING")]
    _cascade(steps, results)
    m2 = results[1]
    assert m2.status == "MISSING", m2.status
    assert m2.cascade_note == "known-gap(M2)"
    assert "no emitter writes these" in " ".join(m2.reasons)


def test_a_descendant_of_a_declared_gap_is_attributed_to_it_not_to_the_waiver():
    """The nearest blocking ancestor DECLARES a gap, so the walk stops there —
    a waiver further up is not the explanation."""
    steps = _steps({"id": 13},
                   {"id": "M2", "blocks_on": [13], "known_gap": "no emitter"},
                   {"id": "M3", "blocks_on": ["M2"]},
                   {"id": "M4", "blocks_on": ["M3"]})
    results = [_res(13, "WAIVED"), _res("M2", "MISSING"),
               _res("M3", "MISSING"), _res("M4", "MISSING")]
    _cascade(steps, results)
    for r in results[2:]:
        assert r.status == "MISSING", f"{r.id}: {r.status}"
        assert r.cascade_note == "blocked-by-known-gap(M2)", r.cascade_note
        assert "no emitter" in " ".join(r.reasons)


def test_the_softer_verdict_is_not_reachable_through_a_declared_gap():
    """LOAD-BEARING. The whole harm was the softer word plus its implicit
    roadmap: close 13 and these return. They would not."""
    steps = _steps({"id": 13},
                   {"id": "M2", "blocks_on": [13], "known_gap": "g"},
                   {"id": "M3", "blocks_on": ["M2"]})
    results = [_res(13, "WAIVED"), _res("M2", "MISSING"), _res("M3", "MISSING")]
    info = _cascade(steps, results)
    assert not [x for x in info["deferred_by_upstream"]
                if x[0] in ("M2", "M3")], info["deferred_by_upstream"]
    assert all(r.status != "DEFERRED-BY-UPSTREAM" for r in results[1:])


# ── the legitimate cascade is untouched ─────────────────────────────────────
def test_a_plain_waived_ancestor_still_defers():
    """THE ACCEPT CASE. #502's intent is real: a step whose predecessor was
    deferred never ran — when the flow DECLARES the step reads what the
    predecessor writes (#776)."""
    steps = _steps(_writes(12), _reads(13, [12]))
    results = [_res(12, "WAIVED"), _res(13, "MISSING")]
    _cascade(steps, results, {12: {"ticket": "T-1"}})
    assert results[1].status == "DEFERRED-BY-UPSTREAM"
    assert "ticket=T-1" in results[1].cascade_note


def test_the_same_chain_without_the_declaration_does_not_soften():
    """#776 CONTROL for the test above — identical `blocks_on`, identical
    waiver, only the declaration removed. This is the shape that produced
    `DEFERRED-BY-UPSTREAM(13)` on 1153 of the flow's 1221 ancestor pairs."""
    steps = _steps({"id": 12}, {"id": 13, "blocks_on": [12]})
    results = [_res(12, "WAIVED"), _res(13, "MISSING")]
    info = _cascade(steps, results, {12: {"ticket": "T-1"}})
    assert results[1].status == "MISSING", results[1].status
    assert results[1].cascade_note == "waived-ancestor-undeclared(12)"
    assert info["deferred_by_upstream"] == []


def test_the_deferral_reason_no_longer_asserts_what_it_cannot_check():
    """It used to say the step "consumes outputs that step X's waiver
    deferred" off an ORDERING edge alone. #776: it may say so only where the
    flow declares the read, and it must still never use the old phrasing."""
    steps = _steps(_writes(12), _reads(13, [12]))
    results = [_res(12, "WAIVED"), _res(13, "MISSING")]
    _cascade(steps, results, {12: {"ticket": "T-1"}})
    reason = " ".join(results[1].reasons)
    assert "consumes outputs" not in reason, reason
    assert "ORDER" in reason and "the flow declares this step reads" in reason


def test_a_failing_step_is_still_never_converted():
    steps = _steps({"id": 12}, {"id": 13, "blocks_on": [12]})
    results = [_res(12, "WAIVED"), _res(13, "FAIL")]
    _cascade(steps, results, {12: {"ticket": "T-1"}})
    assert results[1].status == "FAIL"


def test_a_gap_declared_but_empty_is_not_a_gap():
    """`known_gap: ""` states nothing; it must not silence the cascade."""
    steps = _steps(_writes(12), _reads(13, [12], known_gap="  "))
    results = [_res(12, "WAIVED"), _res(13, "MISSING")]
    _cascade(steps, results, {12: {"ticket": "T-1"}})
    assert results[1].status == "DEFERRED-BY-UPSTREAM"


def test_an_ANCESTOR_whose_gap_is_empty_does_not_stop_the_walk():
    """The case the self-gap test does not reach, found by mutation: an empty
    `known_gap` on an ANCESTOR would halt the BFS and attribute the step to a
    declaration that states nothing — worse than the waiver it displaced,
    because it names a cause and gives no reason."""
    steps = _steps(_writes(11),
                   _reads(12, [11], known_gap="   "),
                   _reads(13, [12]))
    results = [_res(11, "WAIVED"), _res(12, "MISSING"), _res(13, "MISSING")]
    _cascade(steps, results, {11: {"ticket": "T-9"}})
    assert results[2].status == "DEFERRED-BY-UPSTREAM", results[2].status
    assert "known-gap" not in results[2].cascade_note, results[2].cascade_note


# ── the flow carries the declaration ────────────────────────────────────────
@pytest.fixture(scope="module")
def flow_steps():
    if not _FLOW.is_file():
        pytest.skip("flow file absent")
    d = yaml.safe_load(_FLOW.read_text(encoding="utf-8"))
    out = []
    for v in d.values():
        if isinstance(v, list):
            out += [s for s in v if isinstance(s, dict) and s.get("id") is not None]
    return {s["id"]: s for s in out}


def test_m2_declares_its_gap_in_the_flow(flow_steps):
    """It was a comment for four releases, and a comment is not readable by
    the code that needed it."""
    kg = flow_steps["M2"].get("known_gap")
    assert isinstance(kg, str) and kg.strip(), "M2's KNOWN GAP is a comment again"
    assert "emitter" in kg


def test_the_flow_still_declares_no_inputs(flow_steps):
    """The premise the fix rests on. If `inputs:` ever appears, a real
    data-flow predicate becomes possible and this attribution should be
    revisited rather than left as an ordering statement."""
    assert not any("inputs" in s for s in flow_steps.values()), (
        "the flow now declares inputs — the deferral attribution can and "
        "should be checked against them")
