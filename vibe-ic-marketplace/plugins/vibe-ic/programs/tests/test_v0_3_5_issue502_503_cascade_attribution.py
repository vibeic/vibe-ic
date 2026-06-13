"""v0.3.5 — #502 + #503: cascade attribution in flow_compliance_check.

#502: a WAIVED-DEFERRED step's downstream-DEPENDENT steps (transitive
`blocks_on` ancestry in the flow YAML) used to report bare MISSING —
indistinguishable from never-attempted work, and double-counting the
same waiver. Now they convert to DEFERRED-BY-UPSTREAM(parent, ticket).

#503: after a mid-chain FAIL the runner stops the chain, and every
downstream step printed bare `MISSING` — a 25-step cascade read as 25
independent gaps. Now each post-first-FAIL MISSING in the same declared
chain is annotated blocked-by-upstream(<first-fail id>) and the summary
splits the cascade count. Status stays MISSING (strict still fails).

Fixtures pin the REAL shapes from the two real defect artifacts
(#502: deferred analog-layout parent → dependent per-block-PV step with
ticket carried; #503: stage1 formal/FPGA FAIL pair → 25 downstream
MISSING) — using the REAL flow YAML's declared `blocks_on` edges, not a
synthetic graph, so a future edge rename breaks these tests loudly.

Chip-AGNOSTIC: step ids (A5/A6/5/7) are flow-definition structure, not
chip names; the attribution logic itself walks edges generically.
"""
import sys
from pathlib import Path

import yaml

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import flow_compliance_check as FCC  # noqa: E402

_FLOW = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"


def _steps():
    return yaml.safe_load(_FLOW.read_text())["steps"]


def _res(sid, status, reasons=None, name="step", stage="s"):
    return FCC.StepResult(id=sid, name=name, stage=stage, status=status,
                          reasons=list(reasons or []))


# ── #502: waiver chain propagates over blocks_on ─────────────────────

def test_deferred_parent_converts_dependent_missing():
    # REAL shape: analog-layout step WAIVED (ENV_UNAVAILABLE w/ ticket),
    # the per-block-PV step that blocks_on it is MISSING.
    steps = _steps()
    parent = _res("A5", "WAIVED", reasons=[
        "ENV_UNAVAILABLE waiver applied (...) "
        "[ticket=pdk-substitution-v0.2.103, review_required=True]"])
    child = _res("A6", "MISSING",
                 reasons=["no required_outputs found"])
    results = [parent, child]
    info = FCC._attribute_cascade_verdicts(results, steps, waivers={})
    assert child.status == "DEFERRED-BY-UPSTREAM"
    assert "deferred-by-upstream(A5" in child.cascade_note
    assert "ticket=pdk-substitution-v0.2.103" in child.cascade_note
    assert info["deferred_by_upstream"] == [
        ("A6", "A5", "pdk-substitution-v0.2.103")]


def test_ticket_prefers_waivers_dict():
    steps = _steps()
    parent = _res("A5", "WAIVED")
    child = _res("A6", "MISSING")
    FCC._attribute_cascade_verdicts(
        [parent, child], steps,
        waivers={"A5": {"ticket": "tkt-from-dict"}})
    assert "ticket=tkt-from-dict" in child.cascade_note


def test_deferral_is_transitive_over_blocks_on():
    # A7 blocks_on A6 blocks_on A5 (real YAML edges): grandchild
    # MISSING also converts when only A5 is deferred.
    steps = _steps()
    a5 = _res("A5", "WAIVED", reasons=["[ticket=t1]"])
    a6 = _res("A6", "MISSING")
    a7 = _res("A7", "MISSING")
    FCC._attribute_cascade_verdicts([a5, a6, a7], steps, waivers={})
    assert a6.status == "DEFERRED-BY-UPSTREAM"
    assert a7.status == "DEFERRED-BY-UPSTREAM"


def test_unrelated_missing_stays_missing():
    # 對照 (issue 驗收): a MISSING step with NO deferred ancestor keeps
    # its bare verdict — no false attribution.
    steps = _steps()
    a5 = _res("A5", "WAIVED", reasons=["[ticket=t1]"])
    s7 = _res(7, "MISSING")  # main track; no deferred ancestor
    FCC._attribute_cascade_verdicts([a5, s7], steps, waivers={})
    assert s7.status == "MISSING"
    assert s7.cascade_note == ""


def test_fail_never_converts_to_deferred():
    # real counter-evidence survives: a FAIL downstream of a deferred
    # parent stays FAIL.
    steps = _steps()
    a5 = _res("A5", "WAIVED", reasons=["[ticket=t1]"])
    a6 = _res("A6", "FAIL", reasons=["gate exit 1"])
    FCC._attribute_cascade_verdicts([a5, a6], steps, waivers={})
    assert a6.status == "FAIL"


# ── #503: first-FAIL cut point per declared chain ────────────────────

def _main_track_ids(steps):
    return [s["id"] for s in steps
            if isinstance(s.get("id"), int)]


def test_post_fail_missing_is_annotated_blocked():
    # REAL shape: step 5 FAIL (first), step 6 FAIL, steps 7+ MISSING →
    # every post-5 MISSING annotated blocked-by-upstream(5); status
    # stays MISSING; summary count keyed by the FIRST fail only.
    steps = _steps()
    ids = _main_track_ids(steps)
    results = [_res(5, "FAIL"), _res(6, "FAIL")]
    downstream = [i for i in ids if i > 6][:5]
    results += [_res(i, "MISSING") for i in downstream]
    info = FCC._attribute_cascade_verdicts(results, steps, waivers={})
    blocked = [r for r in results if r.cascade_note]
    assert len(blocked) == len(downstream)
    for r in blocked:
        assert r.status == "MISSING"          # strict semantics unchanged
        assert r.cascade_note == "blocked-by-upstream(5)"
    assert info["blocked_by_upstream"] == {5: len(downstream)}


def test_missing_before_first_fail_stays_bare():
    steps = _steps()
    results = [_res(3, "MISSING"), _res(5, "FAIL"), _res(7, "MISSING")]
    FCC._attribute_cascade_verdicts(results, steps, waivers={})
    assert results[0].cascade_note == ""      # before the cut point
    assert results[2].cascade_note == "blocked-by-upstream(5)"


def test_chains_are_isolated():
    # a FAIL in the main chain must NOT annotate analog-chain MISSING.
    steps = _steps()
    main_fail = _res(5, "FAIL")
    analog_missing = _res("A6", "MISSING")
    FCC._attribute_cascade_verdicts([main_fail, analog_missing],
                                    steps, waivers={})
    assert analog_missing.cascade_note == ""
    assert analog_missing.status == "MISSING"


def test_no_fail_no_annotation():
    steps = _steps()
    results = [_res(5, "PASS"), _res(7, "MISSING")]
    info = FCC._attribute_cascade_verdicts(results, steps, waivers={})
    assert results[1].cascade_note == ""
    assert info["blocked_by_upstream"] == {}
