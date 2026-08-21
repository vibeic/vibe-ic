"""Step 1 (Spec-to-RTL) must DECLARE its dependency on D1 (Phase 1 extraction).

The defect
----------
`flow/phase1_phase2_phase3.yaml` shipped `blocks_on: []` on step 1 while D1 —
the sole member of `stage_phase1`, whose L1-L27 JSON the file's own header
calls "the universal handoff to Phase 2" — sat with no inbound edge anywhere.
Of the 62 `blocks_on` lines in the flow, NOT ONE named D1.

The enforcement path that missing edge bypassed is live and already correct:
`flow_compliance_check` builds `{str(id): [str(e) for e in blocks_on]}` and
turns every `ordering_violation` returned by
`flow_step_execution_coverage_check.analyze()` into a NON-promotable forced
FAIL; `analyze()` flags any PASS / VACUOUS-PASS step whose transitive
`blocks_on` ancestry reaches an APPLICABLE step that has not truly passed.
With no edge to D1 the guard was structurally blind: on a real completed run
Step 1 reported PASS purely on the presence of `phase2/stage1/rtl/*.v` +
the two extraction-coverage report files, with ZERO reference to D1's verdict.
`required_outputs` being ALL-of-N (#455) only catches a Phase 1 that never ran
at all — `phase1_coverage_report_gen` writes those two reports regardless of
whether D1 FAILED, so a FAILED D1 stayed invisible.

The fix
-------
Declare the dependency that already exists in fact: `blocks_on: [D1]` on
step 1. No code change is needed — both consumers stringify ids.

Direction-1 guards (behaviour that must NOT change)
---------------------------------------------------
* D1 = PASS                → no violation.
* D1 = VACUOUS-PASS        → no violation ("Phase 1 Doc Extraction" is not a
                              sign-off name, so a vacuous process ancestor
                              stays acceptable; this is the status D1 carries
                              on the real digital spm run).
* D1 = SKIPPED-CONDITION   → no violation (the documented SKIP-allowed path:
                              generated_docs populated by external authoring).
* the flow graph stays acyclic and D1 itself gains no parents.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
_PLUGIN = _PROGRAMS.parent
for _p in (str(_PROGRAMS), str(_PLUGIN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import flow_step_execution_coverage_check as _cov     # noqa: E402

FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_PHASE1_STEP = "D1"
_D1_NAME = "Phase 1 Doc Extraction (17 skills + dialogue entry → L1-L27)"


@pytest.fixture(scope="module")
def graph() -> dict:
    g = _cov._load_blocks_on(FLOW)
    assert g, "premise: the flow yaml must parse into a blocks_on graph"
    return g


def _stage_steps(stage_id: str) -> list:
    """Members of a stage, read from the ONE place membership is declared.

    This used to read the per-stage roster ``stages[].steps``. That roster was
    a SECOND declaration of membership, it disagreed with the per-step
    ``stage:`` field for 12 of the 63 steps, and it has been deleted
    (vibe-ic#923). Reading it now would return ``[]`` and make every caller
    vacuously true, so the lookup moved to the surviving declaration and
    asserts that it found somebody.
    """
    import yaml
    doc = yaml.safe_load(FLOW.read_text())
    declared = [str(st.get("id")) for st in (doc.get("stages") or [])]
    assert stage_id in declared, (
        f"premise: stage {stage_id!r} not declared in the flow; got {declared}")
    members = [str(s.get("id")) for s in (doc.get("steps") or [])
               if str(s.get("stage")) == stage_id]
    assert members, (
        f"premise: no step declares stage: {stage_id!r} — an empty membership "
        f"would make every assertion over it vacuously true")
    return members


# ── the declaration itself ───────────────────────────────────────────────────

def test_phase1_step_is_declared_somewhere_in_the_flow(graph):
    """At least one step must name D1 as a dependency. Before the fix this was
    zero — the Phase-1 stage was an island."""
    namers = sorted(sid for sid, edges in graph.items()
                    if _PHASE1_STEP in edges)
    assert namers, (
        "no step in the flow declares blocks_on: [D1]; the Phase 1 stage is "
        "an island and its verdict can never gate anything downstream")


def test_every_stage1_step_transitively_depends_on_phase1(graph):
    """Every RTL-generation step must reach D1 through declared edges — that is
    what makes the ordering guard see a failed Phase 1."""
    missing = [sid for sid in _stage_steps("stage1")
               if _PHASE1_STEP not in _cov._ancestors(sid, graph)]
    assert not missing, (
        f"stage1 steps whose blocks_on ancestry does NOT reach {_PHASE1_STEP}: "
        f"{missing} — a FAILED Phase 1 would not red them")


def test_phase1_step_itself_has_no_parents(graph):
    """D1 is the entry point; giving it parents would create a cycle."""
    assert graph.get(_PHASE1_STEP) == [], (
        f"{_PHASE1_STEP} must remain the flow entry point with no blocks_on "
        f"parents; got {graph.get(_PHASE1_STEP)!r}")


def test_flow_graph_stays_acyclic(graph):
    """Direction-1 guard: the new edge must not introduce a cycle."""
    colour: dict = {}

    def visit(node: str, stack: tuple) -> None:
        if colour.get(node) == "done":
            return
        assert node not in stack, f"cycle in blocks_on: {stack + (node,)}"
        colour[node] = "open"
        for parent in graph.get(node, []):
            visit(parent, stack + (node,))
        colour[node] = "done"

    for sid in graph:
        visit(sid, ())


# ── behavioural discriminator: the guard must now fire ───────────────────────

def _report(d1_status: str, step1_status: str = "PASS") -> dict:
    return {"steps": [
        {"id": _PHASE1_STEP, "name": _D1_NAME, "status": d1_status,
         "stage": "stage_phase1"},
        {"id": "1", "name": "Spec-to-RTL", "status": step1_status,
         "stage": "stage1"},
    ]}


def _violation_ids(d1_status: str, graph: dict) -> list:
    return [(v["terminal_id"], v["signoff_id"])
            for v in _cov.analyze(_report(d1_status), graph)
            .get("ordering_violations", [])]


@pytest.mark.parametrize("d1_status", ["FAIL", "MISSING"])
def test_failed_or_missing_phase1_reds_a_passing_spec_to_rtl(d1_status, graph):
    """THE discriminator. A Step 1 that reports PASS while D1 FAILED/is MISSING
    must produce an ordering violation — which flow_compliance_check converts
    into a non-promotable forced Overall FAIL."""
    got = _violation_ids(d1_status, graph)
    assert ("1", _PHASE1_STEP) in got, (
        f"Step 1 = PASS with D1 = {d1_status} must be an ordering violation; "
        f"got {got!r}")


def test_failed_phase1_reds_the_whole_downstream_main_track(graph):
    """The edge is transitive: descendants of Step 1 are flagged too."""
    rep = _report("FAIL")
    rep["steps"].append({"id": "9", "name": "Synthesis (Yosys → mapped "
                                            "netlist)", "status": "PASS",
                         "stage": "stage2"})
    pairs = [(v["terminal_id"], v["signoff_id"])
             for v in _cov.analyze(rep, graph).get("ordering_violations", [])]
    assert ("9", _PHASE1_STEP) in pairs, (
        f"a downstream step must inherit the violation transitively; "
        f"got {pairs!r}")


# ── direction-1 guards: statuses that must stay silent ───────────────────────

@pytest.mark.parametrize("d1_status", [
    "PASS",
    "VACUOUS-PASS",       # the status D1 carries on the real digital spm run
    "SKIPPED-CONDITION",  # generated_docs populated by external authoring
    "WAIVED",
])
def test_legitimate_phase1_states_raise_no_violation(d1_status, graph):
    """Behaviour that must NOT change: none of these D1 states may red Step 1.
    These pass on BOTH the pre-fix and post-fix trees."""
    got = _violation_ids(d1_status, graph)
    assert got == [], (
        f"D1 = {d1_status} must not produce an ordering violation; got {got!r}")


# ── the edge cuts BOTH ways — disclosed, not accidental ────────────────────
#
# Declaring the edge also makes the #502 cascade reachable for Phase 1 for the
# first time: a MISSING step whose blocks_on ancestry reaches a WAIVED step
# becomes DEFERRED-BY-UPSTREAM, which flow_compliance_check EXCLUDES from the
# `missing` set that drives Overall FAIL (`ok = ... and len(missing) == 0`,
# and total_required subtracts DEFERRED-BY-UPSTREAM). So an explicitly
# ticketed waiver on D1 can now absorb its own downstream MISSING instead of
# being counted twice. That is this codebase's own doctrine ("one waiver = one
# deduction, not two"), it fires ONLY on a disclosed waiver, and a FAIL never
# converts — but it is a real consequence and is pinned here so it can never
# be mistaken for an accident.

def test_waived_phase1_defers_only_what_declares_it_reads_phase1(graph):
    """vibe-ic#776 NARROWED THIS, and the narrowing is the point.

    Before #776 a waiver on D1 absorbed 49 downstream MISSING steps on this
    flow — every step ordered behind it. It now absorbs the three that DECLARE
    they read a Phase-1 doc: steps 2, 4 and 8, whose gates name
    `phase1/generated_docs/L{3,8,10,11,12}*.json` in `condition_files_exist`.

    Step 1 (Spec-to-RTL) is NOT among them, and that is the honest reading of
    the flow as written: step 1 does consume the L-docs, but it consumes them
    inside the runner, and its flow entry declares only
    `files_exist: [phase2/stage1/rtl/*.sv, *.v]` — its own output. The discount
    was being taken on an ordering edge. If the dependency should be declared,
    the fix is one `condition_files_exist` entry on step 1's gate, reviewed on
    its own merits; until then step 1 reports MISSING and says why.
    """
    import yaml as _yaml
    import flow_compliance_check as _fcc
    steps = _yaml.safe_load(FLOW.read_text())["steps"]
    S = _fcc.StepResult
    ids = [s["id"] for s in steps if str(s.get("id")) != "P0"]
    results = [
        S(id=sid, name="", stage="",
          status=("WAIVED" if sid == _PHASE1_STEP else "MISSING"),
          reasons=(["ticket=ABC-1"] if sid == _PHASE1_STEP else []))
        for sid in ids
    ]
    info = _fcc._attribute_cascade_verdicts(results, steps, {},
                                            skip_analog=False)
    by_id = {r.id: r for r in results}

    deferred = sorted(str(sid) for sid, _p, _t in info["deferred_by_upstream"])
    assert deferred == ["2", "4", "8"], deferred
    for sid in (2, 4, 8):
        assert (sid, _PHASE1_STEP, "ABC-1") in info["deferred_by_upstream"], info

    # DIRECTION-1: the ordering fact is recorded, not discarded, and it costs.
    assert by_id[1].status == "MISSING", by_id[1].status
    assert by_id[1].cascade_note == f"waived-ancestor-undeclared({_PHASE1_STEP})"


def test_guard_a_failed_phase1_never_converts_to_deferred(graph):
    """Direction-1 guard on the same mechanism: only WAIVED propagates. Real
    counter-evidence must always survive."""
    import yaml as _yaml
    import flow_compliance_check as _fcc
    steps = _yaml.safe_load(FLOW.read_text())["steps"]
    S = _fcc.StepResult
    results = [
        S(id=_PHASE1_STEP, name=_D1_NAME, stage="stage_phase1", status="FAIL"),
        S(id=1, name="Spec-to-RTL", stage="stage1", status="MISSING"),
    ]
    _fcc._attribute_cascade_verdicts(results, steps, {}, skip_analog=False)
    assert results[1].status == "MISSING", results[1].status


def test_guard_skip_analog_mixed_track_pass_is_unaffected(graph):
    """#667: the M-track BFS now walks through step 1 into D1. It must still
    find the SKIPPED-CONDITION analog ancestor and must not error on the new
    non-integer parent."""
    import yaml as _yaml
    import flow_compliance_check as _fcc
    steps = _yaml.safe_load(FLOW.read_text())["steps"]
    S = _fcc.StepResult
    results = [
        S(id=_PHASE1_STEP, name=_D1_NAME, stage="stage_phase1", status="PASS"),
        S(id=1, name="Spec-to-RTL", stage="stage1", status="PASS"),
        S(id="A8", name="Hardmacro Generation", stage="stage_analog",
          status="SKIPPED-CONDITION"),
        S(id="M2", name="Mixed-signal merge", stage="stage_mixed",
          status="MISSING"),
    ]
    _fcc._attribute_cascade_verdicts(results, steps, {}, skip_analog=True)
    assert results[3].status == "SKIPPED-CONDITION"
    assert results[3].cascade_note == "skipped-by-upstream-analog(A8)"


def test_guard_phase1_step_belongs_to_no_declaration_chain(graph):
    """#503 splits chains by `_track_of`, which returns None for "D1". The new
    edge must not make D1 a chain cut point — the ordering guard, not #503, is
    what catches a failed Phase 1."""
    import flow_compliance_check as _fcc
    assert _fcc._track_of(_PHASE1_STEP) is None


def test_vacuous_pass_stays_acceptable_because_d1_is_not_a_signoff_name():
    """Direction-1 guard on the mechanism, not just the outcome: analyze()
    accepts a VACUOUS-PASS ancestor only for NON sign-off steps. Pin the fact
    that D1's name does not match the sign-off vocabulary, so a future rename
    that silently changes the verdict tier is caught here."""
    assert not _cov._SIGNOFF_RE.search(_D1_NAME), (
        "D1's name now matches the sign-off vocabulary — a VACUOUS-PASS D1 "
        "would start blocking every downstream step; that is a deliberate "
        "policy change, not a rename")
