"""The classified blocker list, beside the tally.

THE MEASUREMENT THIS IS WRITTEN FROM. A cell agent, after running two
experiments in opposite directions in one round:

    real post-route 3-corner STA — strictly BETTER evidence — scored 17 PASSes
    LOWER; disabling a deliberate cross-step check scored 2 PASSes HIGHER while
    the design sat untouched. In neither direction was PASS measuring the
    design. The only number in this report that describes this design is the
    classified blocker list.

The tally is a count of satisfied gates and it moves for reasons that have
nothing to do with a chip. The classified list — plugin defect / design fact /
missing capability — is the part that is about the chip, and until this change
it existed only as prose in a shape no consumer could read.

WHAT THESE TESTS ARE WRITTEN AGAINST. The observable properties of the emitted
list, not this implementation. A different correct classifier passes all of
them; the tests build step records and read back classifications, and the only
implementation detail any of them touches is the two anti-drift pins at the
bottom, which exist precisely because a rule that silently stops firing is the
failure mode the whole file is defending against.

THE OVER-CORRECTIONS THEY CATCH, because each has a cheap wrong version:

  * shrink the list until it looks manageable  -> completeness is a SET
    EQUALITY against the report's own steps, not a length bound;
  * label everything that is not green a plugin defect -> a timed-out gate, an
    absent artefact and a downstream cascade must each stay UNCLASSIFIED;
  * label a substantive-looking gate FAIL a DESIGN_FACT even though the step's
    declared input never arrived -> the same gate failure, moved downstream of
    a non-PASS dependency, must lose the class. This is the one that matters:
    it is the exact shape of the measured finding, a number that looks like it
    is about the design and is not;
  * assign a class the evidence does not determine -> `no-rule-matched` with
    any class other than UNCLASSIFIED is a guard failure.

ANTI-TAUTOLOGY NOTE, stated because the criticism is fair and was made of
another PR here. Most tests below reference `_blocker_classification`, which
this change introduces; run against the pre-change tree they fail at
COLLECTION, on ModuleNotFoundError, which proves nothing about behaviour — a
missing symbol fails whatever the behaviour is. The bidirectional
behavioural controls live in `test_blocker_list_report_contract.py`, which
imports NOTHING this change introduces: it drives `flow_compliance_check`
through its public CLI and asserts on the report it writes, so on the pre-change
tree it collects cleanly and fails on CONTENT. That file is what the negative
control in the PR body is counted from; this one is a specification of the
rules, and its pre-change failure mode is honestly a missing module.
"""
from __future__ import annotations

import importlib
from pathlib import Path

_BC = importlib.import_module("_blocker_classification")
_T = importlib.import_module("_flow_verdict_tiers")
_GUARD = importlib.import_module("blocker_classification_check")
_FCCMOD = importlib.import_module("flow_compliance_check")

_PROGRAMS = Path(__file__).resolve().parents[1]
_FCC = _PROGRAMS / "flow_compliance_check.py"


# ── helpers: step records in the shape the report publishes ────────────────
def _step(sid, status, **kw):
    rec = {
        "id": sid,
        "name": kw.pop("name", f"step {sid}"),
        "stage": kw.pop("stage", "stage2"),
        "status": status,
        "reasons": kw.pop("reasons", []),
        "evidence": [],
        "gate_output": "",
        "cascade_note": kw.pop("cascade_note", ""),
        "self_skip_disclosed": kw.pop("self_skip_disclosed", False),
        "structure_only_disclosed": kw.pop("structure_only_disclosed", False),
        "gate_records": kw.pop("gate_records", None),
    }
    rec.update(kw)
    return rec


def _classify_one(step, flow_steps=None, oss=None):
    out = _BC.build_blockers([step] if isinstance(step, dict) else step,
                             flow_steps=flow_steps, oss_blocked=oss or {})
    return out


# ── 1. completeness: nothing drops off the list ────────────────────────────
def test_every_non_pass_step_the_producer_can_emit_is_on_the_list():
    """Set equality against the producer's own vocabulary.

    `PRODUCER_STATUSES` is the closed list of words `flow_compliance_check`
    can assign. Every one of them that is not a full PASS and not a
    genuinely-inapplicable skip has to appear, or the list is not the thing it
    claims to be.
    """
    inapplicable = {"PASS", "SKIPPED-CONDITION"}
    steps = [_step(f"s{i}", w)
             for i, w in enumerate(sorted(_T.PRODUCER_STATUSES))]
    blockers = _BC.build_blockers(steps)
    listed = {b["step_id"] for b in blockers}
    for i, w in enumerate(sorted(_T.PRODUCER_STATUSES)):
        if w in inapplicable:
            assert f"s{i}" not in listed, f"{w} must not be a blocker"
        else:
            assert f"s{i}" in listed, f"{w} silently dropped off the list"


def test_a_verdict_word_this_module_has_never_seen_is_still_a_blocker():
    """Fail-SAFE derivation, the same device `_flow_verdict_tiers` uses.

    A tier invented tomorrow must land ON the list without anyone remembering
    to come here. The alternative — an enumerated set of blocking words — goes
    quiet on exactly the tier it did not know about, which is how the ordering
    guard lost `STRUCTURE-ONLY` for a whole release.
    """
    invented = _step(99, "SPLENDIDLY-DEGRADED")
    assert _BC.is_blocker(invented)
    assert _BC.build_blockers([invented])[0]["step_id"] == 99


def test_the_list_is_not_shrinkable_by_status_filtering():
    """The over-correction: narrow the definition until the count is small.

    A filter tightened until a number reaches zero has already been caught in
    this repo once. Here the property that stops it is that the list's
    membership is the complement of (full PASS + inapplicable skip), so any
    narrowing shows up as a missing entry rather than a smaller number.
    """
    steps = [_step(1, "FAIL"), _step(2, "MISSING"), _step(3, "WAIVED"),
             _step(4, "PASS-VOIDED-BY-DEPENDENCY"), _step(5, "VACUOUS_PASS"),
             _step(6, "STRUCTURE-ONLY"), _step(7, "INCOMPLETE"),
             _step(8, "SKIPPED-SETUP-REQUIRED"),
             _step(9, "DEFERRED-BY-UPSTREAM")]
    assert len(_BC.build_blockers(steps)) == len(steps)


# ── 2. nothing invented: a passing step never appears ──────────────────────
def test_a_full_pass_step_never_appears_on_the_list():
    """The opposite over-correction, and the worse one on a blocking consumer:
    attributing a blocker to a step that passed FABRICATES work."""
    steps = [_step(1, "PASS"), _step(2, "FAIL")]
    assert [b["step_id"] for b in _BC.build_blockers(steps)] == [2]


def test_an_inapplicable_skip_is_not_a_blocker_but_a_disclosed_gap_is():
    """`SKIPPED-CONDITION` is three situations wearing one word and only the
    third is an unmet requirement. Conflating them either buries the list under
    ~97 'this digital chip has no analog blocks' entries, or hides a real
    disclosed capability gap. Both directions are asserted here."""
    na = _step("A1", "SKIPPED-CONDITION",
               reasons=["condition not met: {'files_exist': ['x.json']}"])
    gap = _step(11, "SKIPPED-CONDITION", self_skip_disclosed=True)
    assert not _BC.is_blocker(na)
    assert _BC.is_blocker(gap)
    out = _BC.build_blockers([na, gap])
    assert [b["step_id"] for b in out] == [11]
    assert out[0]["classification"] == "MISSING_CAPABILITY"


# ── 3. the three classes, and the over-correction beside each ──────────────
def test_a_crashed_gate_is_a_plugin_defect():
    """An unhandled exception in the plugin's own gate program. It produced no
    statement about the design, so the class whose correct response is 'fix the
    plugin' is the only one available."""
    s = _step(4, "FAIL", reasons=[
        "program failed: some_check . --json reports/x.json",
        "output: __CRASH_HINT__: KeyError: 'corner'\n— an unhandled exception "
        "is NOT a gate verdict (INCONCLUSIVE)"])
    b = _BC.build_blockers([s])[0]
    assert b["classification"] == "PLUGIN_DEFECT"
    assert b["basis"] == "gate-crashed"


def test_a_timed_out_gate_is_unclassified_not_a_plugin_defect():
    """OVER-CORRECTION GUARD. A killed gate returned no verdict, exactly like a
    crashed one — but nothing recorded says whether the plugin hung or the
    input was enormous. Calling it a plugin defect is a guess in the direction
    that generates work for the wrong person."""
    s = _step(4, "FAIL", reasons=[
        "program failed: some_check .",
        "output: program TIMED OUT after 600s — timeout is NOT a verdict "
        "(INCONCLUSIVE)"])
    b = _BC.build_blockers([s])[0]
    assert b["classification"] == "UNCLASSIFIED"
    assert b["basis"] == "gate-timed-out"


def test_a_gate_that_ran_with_every_dependency_passed_is_a_design_fact():
    flow = [{"id": 2, "name": "up", "blocks_on": []},
            {"id": 4, "name": "sim", "blocks_on": [2],
             "gate": {"program_exit_zero": "sim_check ."}}]
    steps = [_step(2, "PASS"),
             _step(4, "FAIL", reasons=[
                 "program failed: sim_check . --json reports/sim.json",
                 "output: FAIL — 3 of 40 sequences mismatched"])]
    # the producer's own gate summariser, so `measures` is exercised on the
    # production path rather than on a fallback no run takes
    b = _BC.build_blockers(steps, flow_steps=flow,
                           gate_summary_fn=_FCCMOD._declared_gate_summary)[0]
    assert b["classification"] == "DESIGN_FACT"
    assert b["basis"] == "gate-reached-verdict"
    assert b["measures"] == "sim_check"
    assert "3 of 40 sequences mismatched" in b["observed"]


def test_the_same_gate_failure_downstream_of_a_gap_is_not_a_design_fact():
    """THE REVERSE CASE THAT MATTERS — it is the measured finding in miniature.

    Byte-identical failing step, one variable changed: its declared
    predecessor did not pass. The gate still ran and still returned a
    substantive-looking number, and that number is now about a tree that is
    missing the input this step reads. On the reference run this is
    `si_mcf_sta_check` reporting `NO_SPEF` while parasitic extraction is
    MISSING, and `post_route_signoff_corner_check` reporting a -8.830 ns
    worst-slack on a design with no parasitics. Greening or triaging either as
    a design fact is how a campaign spends a week on the wrong thing.
    """
    flow = [{"id": 22, "name": "spef", "blocks_on": []},
            {"id": 23, "name": "post-route STA", "blocks_on": [22],
             "gate": {"program_exit_zero": "sta_check ."}}]
    reasons = ["optional program failed: sta_check . --json reports/sta.json",
               "output: FAIL — setup worst-slack -8.830 ns at the sign-off "
               "corner is VIOLATED"]
    passed_up = _BC.build_blockers(
        [_step(22, "PASS"), _step(23, "FAIL", reasons=reasons)],
        flow_steps=flow)[0]
    gapped_up = _BC.build_blockers(
        [_step(22, "MISSING"), _step(23, "FAIL", reasons=reasons)],
        flow_steps=flow)
    downstream = next(b for b in gapped_up if b["step_id"] == 23)

    assert passed_up["classification"] == "DESIGN_FACT"
    assert downstream["classification"] == "UNCLASSIFIED"
    assert downstream["basis"] == "derived-from-upstream"
    assert downstream["derived_from"] == ["22"]
    # and the observation is NOT thrown away — it is still readable, just not
    # promoted to a fact about the design.
    assert "-8.830 ns" in downstream["observed"]


def test_env_unavailable_waiver_is_a_named_missing_capability():
    s = _step(6, "WAIVED", reasons=[
        "ENV_UNAVAILABLE waiver applied (natural verdict was FAIL/MISSING): "
        "ENV_UNAVAILABLE (fpga-board-prototype cap-gap): no board on host"])
    b = _BC.build_blockers([s])[0]
    assert b["classification"] == "MISSING_CAPABILITY"
    assert b["basis"] == "env-unavailable-waiver"


def test_an_ordinary_waiver_is_not_a_missing_capability():
    """OVER-CORRECTION GUARD. Reading every waiver as a capability gap turns
    'somebody signed this off' into 'the host lacks a tool', which sends the
    reviewer to buy hardware for a decision a human already made."""
    s = _step(13, "WAIVED", reasons=[
        "WAIVED-DEFERRED: waiver id=13 reason='reviewed by owner 2026-07'"])
    b = _BC.build_blockers([s])[0]
    assert b["classification"] == "UNCLASSIFIED"
    assert b["basis"] != "env-unavailable-waiver"


def test_a_bare_absent_artefact_is_unclassified():
    """ANTI-GUESS. A missing file is equally consistent with a plugin that
    never wrote it, a tool that is not installed, and a step nobody ran. The
    record says so rather than picking one."""
    s = _step(12, "MISSING", reasons=[
        "no required_outputs found (expected: ['phase2/synth/netlist.v'])"])
    b = _BC.build_blockers([s])[0]
    assert b["classification"] == "UNCLASSIFIED"
    assert b["basis"] == "declared-artefact-absent"


def test_a_disclosure_tier_is_unclassified_with_its_own_basis():
    """VACUOUS-PASS / STRUCTURE-ONLY / INCOMPLETE say the step ran and measured
    nothing design-bound. That is a real fact and a distinct one from 'no rule
    matched', so it gets a basis — but it still names no cause to act on, so it
    is not promoted to a class."""
    for word in ("VACUOUS_PASS", "STRUCTURE-ONLY", "INCOMPLETE"):
        b = _BC.build_blockers([_step("D1", word)])[0]
        assert b["classification"] == "UNCLASSIFIED", word
        assert b["basis"] == "disclosure-tier", word


# ── 4. per-gate records inside an umbrella step ────────────────────────────
def test_a_not_invocable_subgate_is_a_plugin_defect():
    """`_gate_invocation`'s own words for this verdict: 'a defect IN the
    caller, never benign'. The umbrella built an argv its own registered gate
    rejects, so the plugin cannot run its own check."""
    s = _step("P0", "FAIL", gate_records=[
        {"name": "l9_completeness_check", "verdict": "NOT_INVOCABLE",
         "message": "argparse rejected the umbrella's argv: the following "
                    "arguments are required: --l9-file", "evidence": {}},
        {"name": "ok_check", "verdict": "PASS", "message": "", "evidence": {}}])
    b = _BC.build_blockers([s])[0]
    subs = b["sub_blockers"]
    assert [x["gate"] for x in subs] == ["l9_completeness_check"]
    assert subs[0]["classification"] == "PLUGIN_DEFECT"


def test_a_failing_subgate_stays_unclassified():
    """ANTI-GUESS, and the calibration is why. A P0 record carries verdict,
    name, message and evidence and NO field separating 'measured the RTL' from
    'could not open the file it audits'. On the reference run two of the four
    FAIL records are literally `read-error: Could not read file`, so reading
    FAIL as DESIGN_FACT would have been wrong on half of them."""
    s = _step("P0", "FAIL", gate_records=[
        {"name": "gap_reset_granularity_check", "verdict": "FAIL",
         "message": "[ERROR] read-error: Could not read file", "evidence": {}}])
    sub = _BC.build_blockers([s])[0]["sub_blockers"][0]
    assert sub["classification"] == "UNCLASSIFIED"


def test_an_umbrella_never_claims_more_than_its_own_subgates():
    """A parent that claims DESIGN_FACT over a sub-list that says 'we do not
    know' five times is the same false confidence the list exists to remove."""
    s = _step("P0", "FAIL", gate_records=[
        {"name": "a", "verdict": "FAIL", "message": "read-error",
         "evidence": {}},
        {"name": "b", "verdict": "NOT_INVOCABLE", "message": "argparse",
         "evidence": {}}])
    b = _BC.build_blockers([s])[0]
    sub_classes = {x["classification"] for x in b["sub_blockers"]}
    order = list(_BC.BLOCKER_CLASSES)
    fail_sub = {x["classification"] for x in b["sub_blockers"]
                if x["verdict"] == "FAIL"}
    assert b["classification"] in fail_sub or not fail_sub
    assert order.index(b["classification"]) >= 0 and sub_classes


def test_gate_records_three_states_survive_into_sub_blockers():
    """`None` = publishes no records; `[]` = published and everything green.
    Merging them puts 'nothing to say' and 'nothing wrong' in one bucket."""
    assert _BC.build_blockers([_step(1, "FAIL")])[0]["sub_blockers"] is None
    assert _BC.build_blockers(
        [_step("P0", "FAIL", gate_records=[])])[0]["sub_blockers"] == []


# ── 5. no class without a rule ─────────────────────────────────────────────
def test_every_emitted_record_names_the_rule_that_decided_it():
    steps = [_step(1, "FAIL"), _step(2, "MISSING"), _step(3, "WAIVED"),
             _step(4, "VACUOUS_PASS"), _step(5, "ODD-NEW-TIER")]
    for b in _BC.build_blockers(steps):
        assert b["basis"].strip(), b
        assert b["classification"] in _BC.BLOCKER_CLASSES


def test_the_guard_refuses_a_class_asserted_with_no_rule_behind_it():
    """The anti-guess property, enforced. Without this, UNCLASSIFIED loses to
    whoever wants the number smaller."""
    report = {"overall": "FAIL",
              "steps": [_step(1, "FAIL")],
              "blockers": [{"step_id": 1, "step_name": "x", "stage": "s",
                            "status": "FAIL", "classification": "DESIGN_FACT",
                            "basis": "no-rule-matched", "measures": "m",
                            "observed": "o", "derived_from": [],
                            "sub_blockers": None}]}
    violations, _ = _GUARD.check_report(report)
    assert any("no rule matched" in v for v in violations), violations


# ── 6. the guard's own properties ──────────────────────────────────────────
def _report(steps, blockers, **kw):
    doc = {"overall": "FAIL", "steps": steps, "blockers": blockers}
    doc.update(kw)
    return doc


def _record(sid, cls="UNCLASSIFIED", basis="declared-artefact-absent"):
    return {"step_id": sid, "step_name": "x", "stage": "s", "status": "FAIL",
            "classification": cls, "basis": basis, "measures": "m",
            "observed": "o", "derived_from": [], "sub_blockers": None}


def test_guard_catches_a_dropped_blocker():
    v, _ = _GUARD.check_report(
        _report([_step(1, "FAIL"), _step(2, "MISSING")], [_record(1)]))
    assert any("absent from `blockers`" in x for x in v), v


def test_guard_catches_an_invented_blocker():
    v, _ = _GUARD.check_report(
        _report([_step(1, "PASS")], [_record(1)]))
    assert any("must not be listed" in x for x in v), v


def test_guard_catches_a_class_outside_the_closed_set():
    v, _ = _GUARD.check_report(
        _report([_step(1, "FAIL")], [_record(1, cls="PROBABLY_FINE")]))
    assert any("outside the closed" in x for x in v), v


def test_guard_catches_counts_that_do_not_sum_to_the_list():
    v, _ = _GUARD.check_report(_report(
        [_step(1, "FAIL")], [_record(1)],
        blocker_class_counts={"PLUGIN_DEFECT": 0, "DESIGN_FACT": 0,
                              "MISSING_CAPABILITY": 0, "UNCLASSIFIED": 7}))
    assert any("does not sum" in x for x in v), v


def test_guard_refuses_an_empty_list_that_came_from_a_crash():
    """An empty list meaning 'the classifier fell over' and one meaning
    'nothing is blocked' must not be the same artifact — that is the
    falsely-clean result this repo keeps closing in other shapes."""
    v, _ = _GUARD.check_report(_report([_step(1, "PASS")], [],
                                       blocker_list_error="ValueError: boom"))
    assert any("must not read as a clean one" in x for x in v), v


def test_guard_passes_a_pre_contract_report_and_says_so():
    """A report written before this contract has no `blockers` key. Failing on
    it would flag state the repo already shipped, which is a bug in the guard,
    not a finding."""
    doc = {"overall": "FAIL", "steps": [_step(1, "FAIL")]}
    v, facts = _GUARD.check_report(doc)
    assert v == []
    assert facts["pre_contract"] is True


def test_guard_accepts_a_report_this_producer_writes(tmp_path):
    """Round-trip: whatever `build_blockers` emits satisfies the guard. A
    producer and a guard that disagree are two contracts, not one."""
    steps = [_step(1, "PASS"), _step(2, "FAIL", reasons=["program failed: g ."]),
             _step("A1", "SKIPPED-CONDITION", reasons=["condition not met"]),
             _step(3, "MISSING", reasons=["no required_outputs found (x)"])]
    blockers = _BC.build_blockers(steps)
    doc = _report(steps, blockers,
                  blocker_class_counts=_BC.class_counts(blockers),
                  blocker_list_error="")
    assert _GUARD.check_report(doc)[0] == []


# ── 7. anti-drift pins on the producer ─────────────────────────────────────
def test_the_sentinels_match_the_producers_own_constants():
    """`_blocker_classification` restates `flow_compliance_check`'s markers
    rather than importing them (the producer imports the classifier, and a
    cycle broken with a lazy import is a second thing to keep correct). This
    pin is what makes a rename in the producer a RED TEST instead of a rule
    that silently stops firing."""
    src = _FCC.read_text()
    assert f'_CRASH_HINT_PREFIX = "{_BC.CRASH_MARKER}: "' in src
    for prefix in _BC.GATE_RAN_PREFIXES:
        assert f'reasons.append(f"{prefix} ' in src, prefix
    assert _BC.TIMEOUT_MARKER in src
    assert _BC.ENV_UNAVAILABLE_MARKER in src


def test_every_producer_status_is_adjudicated_by_membership():
    """The `PRODUCER_STATUSES` pin, reused. A word added to the producer must
    land somewhere on purpose: full PASS, inapplicable skip, or blocker."""
    for word in _T.PRODUCER_STATUSES:
        s = _step("x", word)
        decided = (_T.is_full_pass(word)
                   or _T.normalize(word) == "SKIPPED-CONDITION"
                   or _BC.is_blocker(s))
        assert decided, word


def test_the_class_vocabulary_is_closed_and_carries_the_honest_fourth():
    assert set(_BC.BLOCKER_CLASSES) == {
        "PLUGIN_DEFECT", "DESIGN_FACT", "MISSING_CAPABILITY", "UNCLASSIFIED"}


# ── 8. the commercial-tool (oss_blocked) narrowing — a gap the review named ──
#
# The review of this PR observed that the `oss_blocked` path had NO behavioural
# coverage: `_classify_one(..., oss=...)` was defined and never called, so
# `build_blockers`'s `oss_blocked` argument — the whole commercial-tool rule —
# was never exercised, and deleting the rule outright passed the suite. These
# two tests exercise it in both directions. The caller-side over-correction (a
# producer that keys on BARE table membership instead of the run's own deferral
# decisions) is driven through the real CLI in
# `test_blocker_list_report_contract.py`, because that wiring lives in
# `flow_compliance_check.main`, not here.
def test_a_step_the_run_routed_into_the_oss_deferral_is_a_named_missing_capability():
    """The producer hands `build_blockers` the map of steps THIS RUN actually
    routed into its open-source-constraints deferral — and only those. A step
    in that map is a capability the container does not have, named with the tool
    that would close it. Deleting the rule drops this to
    `declared-artefact-absent`/UNCLASSIFIED, so this assertion is what keeps the
    rule alive."""
    step = _step(13, "MISSING",
                 reasons=["no required_outputs found (expected: ['equiv.json'])"])
    b = _classify_one(step, oss={13: "Formality / Conformal LEC"})[0]
    assert b["classification"] == "MISSING_CAPABILITY"
    assert b["basis"] == "commercial-tool-required"
    assert "Formality / Conformal LEC" in b["why"]


def test_the_oss_class_is_driven_by_the_map_the_caller_passes_not_the_step():
    """REVERSE / OVER-CORRECTION anchor at the unit boundary. The BYTE-IDENTICAL
    step, absent from the deferral map, must NOT be a missing capability — its
    class is `declared-artefact-absent`/UNCLASSIFIED. This is the property the
    caller's narrowing rests on: membership of the step in some table is not, by
    itself, a capability gap; only the run's decision to defer it is. A wiring
    that keyed on bare table membership would make this step MISSING_CAPABILITY
    and is caught end-to-end by
    `test_membership_in_the_oss_table_alone_...` in the report-contract module."""
    step = _step(13, "MISSING",
                 reasons=["no required_outputs found (expected: ['equiv.json'])"])
    b = _classify_one(step, oss={})[0]
    assert b["classification"] == "UNCLASSIFIED"
    assert b["basis"] == "declared-artefact-absent"


# ── 9. setup-required — the other rule the review found unexercised ──────────
def test_setup_required_is_a_named_missing_capability_distinct_from_a_disclosed_gap():
    """`SKIPPED-SETUP-REQUIRED` — the step could not START because its declared
    setup is absent on the host. That is a named capability gap, and a DIFFERENT
    basis from a step that ran and DISCLOSED a gap in place of its artefact.
    Both are MISSING_CAPABILITY and neither may borrow the other's basis, or the
    reader cannot tell 'never started' from 'started and self-reported'.
    Deleting the setup-required rule drops the first to
    no-rule-matched/UNCLASSIFIED; this pins it."""
    setup = _step(11, "SKIPPED-SETUP-REQUIRED")
    disclosed = _step(12, "SKIPPED-CONDITION", self_skip_disclosed=True)
    b_setup = _BC.build_blockers([setup])[0]
    b_disc = _BC.build_blockers([disclosed])[0]
    assert b_setup["classification"] == "MISSING_CAPABILITY"
    assert b_setup["basis"] == "setup-required"
    assert b_disc["classification"] == "MISSING_CAPABILITY"
    assert b_disc["basis"] == "disclosed-capability-gap"
    assert b_setup["basis"] != b_disc["basis"]


def test_an_inapplicable_skip_is_never_read_as_setup_required():
    """REVERSE. A genuinely-inapplicable `SKIPPED-CONDITION` (an analog step on
    a digital chip) is not even a blocker, so it can never be mislabelled a
    setup-required capability gap. The over-correction — reading every skip as
    'setup missing' — would put ~97 inapplicable skips on the list wearing a
    MISSING_CAPABILITY badge."""
    na = _step("A5", "SKIPPED-CONDITION",
               reasons=["condition not met: analog track skipped via --skip-analog"])
    assert not _BC.is_blocker(na)
    assert _BC.build_blockers([na]) == []
