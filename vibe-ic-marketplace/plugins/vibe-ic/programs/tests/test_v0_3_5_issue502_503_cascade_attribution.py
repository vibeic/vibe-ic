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
    # REAL shape, and the ONE the flow declares: step 9 (synthesis) WAIVED,
    # step 14 (synthesis handoff gate) MISSING. 14 blocks_on [9, 13] AND is
    # required to deliver `phase2/stage2/synth/netlist.v`, the artefact 9 is
    # required to write — so 9's waiver is what stopped 14.
    #
    # vibe-ic#776 — this used to be A5 -> A6 (analog layout -> per-block PV).
    # That deferral was real in the WORLD and absent from the FLOW: A6's gate
    # is `analog_a6_block_pv_check . --json ...` and declares no input at all,
    # so nothing in the flow said A6 reads A5's layout. It softened on ORDER.
    steps = _steps()
    parent = _res(9, "WAIVED", reasons=[
        "ENV_UNAVAILABLE waiver applied (...) "
        "[ticket=pdk-substitution-v0.2.103, review_required=True]"])
    child = _res(14, "MISSING",
                 reasons=["no required_outputs found"])
    results = [parent, child]
    info = FCC._attribute_cascade_verdicts(results, steps, waivers={})
    assert child.status == "DEFERRED-BY-UPSTREAM"
    assert "deferred-by-upstream(9" in child.cascade_note
    assert "ticket=pdk-substitution-v0.2.103" in child.cascade_note
    assert info["deferred_by_upstream"] == [
        (14, 9, "pdk-substitution-v0.2.103")]


def test_ticket_prefers_waivers_dict():
    steps = _steps()
    parent = _res(9, "WAIVED")
    child = _res(14, "MISSING")
    FCC._attribute_cascade_verdicts(
        [parent, child], steps,
        waivers={9: {"ticket": "tkt-from-dict"}})
    assert "ticket=tkt-from-dict" in child.cascade_note


def test_deferral_is_transitive_over_the_declared_relation():
    # Step 2's lint gate reads `phase2/stage1/rtl/*.sv|*.v` (step 1's declared
    # output) and `phase1/generated_docs/L8_*.json` (D1's). Waiving D1 alone
    # therefore reaches step 2 even though D1 is TWO ordering hops away —
    # the relation is checked against every transitive ancestor, not chained
    # edge-by-edge, because this flow routinely orders a consumer several hops
    # behind its producer.
    steps = _steps()
    d1 = _res("D1", "WAIVED", reasons=["[ticket=t1]"])
    s1 = _res(1, "MISSING")
    s2 = _res(2, "MISSING")
    FCC._attribute_cascade_verdicts([d1, s1, s2], steps, waivers={})
    assert s2.status == "DEFERRED-BY-UPSTREAM", s2.status
    assert "deferred-by-upstream(D1" in s2.cascade_note


def test_a_waived_ancestor_with_no_declared_relation_does_not_soften():
    """#776 NEGATIVE CONTROL, and the whole defect in one assertion.

    Step 13 is the LEC equivalence check. Its declared outputs are
    `reports/lec.rpt` / `reports/lec.json`, which NO other step in the flow
    reads or produces — yet it has 37 transitive `blocks_on` descendants, i.e.
    the entire tail of the flow. Waiving it used to discount every one of them
    that was MISSING (measured: 34 on an otherwise-all-MISSING run; 24 in the
    two published runs that hit it). None of those steps returns by closing 13.

    The ordering fact is still recorded — attribution WITHOUT softening.
    """
    steps = _steps()
    lec = _res(13, "WAIVED", reasons=["[ticket=t1]"])
    # M-track steps are excluded on purpose: #600 already stops them at M2's
    # declared `known_gap`, which is a different (and correct) attribution.
    tail = [_res(sid, "MISSING") for sid in (23, 30, 38, 41, 44)]
    info = FCC._attribute_cascade_verdicts([lec] + tail, steps, waivers={})
    assert info["deferred_by_upstream"] == [], info["deferred_by_upstream"]
    for r in tail:
        assert r.status == "MISSING", (r.id, r.status)
        assert r.cascade_note == "waived-ancestor-undeclared(13)", r.cascade_note
        joined = " ".join(r.reasons)
        assert "declares reading" in joined
        assert "stays MISSING" in joined


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


# ── #776: the softening surface, pinned ──────────────────────────────────────

def test_declared_dependency_relation_is_small():
    """ANTI-DRIFT. Every entry here is a licence to discount a MISSING step
    behind someone else's waiver, so the whole list must be reviewable in one
    screen and must not grow without a reviewer seeing it.

    MEASURED on the canonical flow at the time of #776:
      * 1221 (step, transitive-blocks_on-ancestor) pairs
      *    6 of them carry a declared dependency

    A new pair appearing here is not automatically wrong — it means a flow edit
    declared a real read — but it must be looked at, because it also means one
    more step can now go quiet behind an upstream waiver.
    """
    steps = _steps()
    ids = [s["id"] for s in steps if str(s.get("id")) != "P0"]

    pairs = set()
    for waived in ids:
        results = [FCC.StepResult(id=i, name="", stage="",
                                  status=("WAIVED" if i == waived
                                          else "MISSING"))
                   for i in ids]
        info = FCC._attribute_cascade_verdicts(
            results, steps, {waived: {"ticket": "T"}})
        for sid, parent, _ticket in info["deferred_by_upstream"]:
            pairs.add((str(sid), str(parent)))

    assert pairs == {
        ("2", "D1"),    # lint gate reads L3/L8/L11 docs D1 writes
        ("4", "D1"),    # TB gate reads L10/L12 docs D1 writes
        ("8", "D1"),    # SDC gate reads L8_TIMING_WAVEFORM D1 writes
        ("2", "1"),     # lint gate argv reads phase2/stage1/rtl/*.sv|*.v
        ("14", "9"),    # handoff must deliver the netlist 9 writes
        ("34", "18"),   # spare-cell gate reads phase3/stage3/pnr/spare_cells
    }, sorted(pairs)


def test_ordering_ancestry_is_two_orders_of_magnitude_wider():
    """The measurement that makes the list above meaningful: how many pairs
    the ORDERING graph alone would have licensed."""
    steps = _steps()
    parents = {s["id"]: list(s.get("blocks_on") or [])
               for s in steps if str(s.get("id")) != "P0"}
    total = 0
    for sid in parents:
        seen, queue = set(), list(parents.get(sid, []))
        while queue:
            pid = queue.pop(0)
            if pid in seen:
                continue
            seen.add(pid)
            queue.extend(parents.get(pid, []))
        total += len(seen)
    # 1311 -> 1448: the census tracks the flow, and the flow gained six
    # gate-carrying steps (0.5ic, 15.5ic, 26.5ic, 37.5ic, 37.5ip, 1.6x).
    # The CLAIM is unchanged and still holds — 6 real data dependencies
    # against 1448 ordering-licensed pairs is still two orders of magnitude.
    assert total == 1448, total
