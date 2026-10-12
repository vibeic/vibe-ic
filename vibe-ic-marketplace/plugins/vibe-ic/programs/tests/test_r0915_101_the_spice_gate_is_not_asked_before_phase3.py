"""A gate is asked where its declared input CAN exist, and not earlier.

MEASURED on subservient x gf180mcuD r48 (`_lane_icsub2/c24_proj`), a phase-2-only
run. The P0 umbrella runs in the phase-2 audit, and it asked
`spice_correlation_check` — a gate whose subject is step 22's extracted `*.spef`
and step 23's STA reports, BOTH phase-3 artefacts. The gate answered honestly and
self-skipped, and the prose recogniser booked that skip as an upstream failure::

    BLOCKED: spice_correlation_check — reason_class=BLOCKED_BY_UPSTREAM:
      examined nothing (reason: no_spef); this is NOT a pass over the design

`BLOCKED_BY_UPSTREAM` is not skip-eligible, so a question asked before its answer
could exist kept step P0 non-green on every digital design at once.

ASKED EARLY IS ITS OWN CLASS, AND THE TREE ALREADY HAD IT. R-0915-46/47's
`ASKED_BEFORE_PRODUCER` is exactly this state — "the gate ran, found its subject
absent, and the thing that PRODUCES that subject has not run yet in this flow" —
and it IS skip-eligible, narrowly: granted only while the tree shows the producer
has not run, and never once it has. `spice_correlation_check` simply was not in
`_GATE_SUBJECT_PRODUCED_BY`; the two gates that were are `klayout_deck_mode_check`
and `gate_evidence_completeness_check`.

THE DISCRIMINATOR IS THE PRODUCER'S OWN DECLARED INPUT, NOT ITS OUTPUT. Keying
the predicate on "is there a SPEF" would have said "the producer has not run" of a
producer that ran and FAILED — the opposite finding, and the one case that must
stay BLOCKED_BY_UPSTREAM. So it reads step 22's `required_inputs` entry,
`phase3/stage3/pnr/routed.def` from step 21: absent, extraction was never
reachable; present, it was, and an absent SPEF is a real upstream failure.

THE GATE IS STILL INVOKED, deliberately. Its row stays in P0's population as a
disclosed skip. Removing it from the invoked set would make
`_structural_measurement_line` report PARTIAL — "what those N audit is UNCHECKED
— not clean" — and shrinking `registered` to avoid that would be narrowing a
population to green a row.

chip-AGNOSTIC: paths come from `_path_layout` and from the shipped flow
definition; no chip, PDK or vendor literal appears here.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pytest  # noqa: E402

import flow_compliance_check as F  # noqa: E402
import _flow_reason_taxonomy as RT  # noqa: E402
import _path_layout as PL  # noqa: E402

GATE = "spice_correlation_check"
FLOW_YAML = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"


def _assert_the_mechanism_is_wired():
    """A `None` from `_asked_before_producer` means TWO different things: "this
    gate is in the roster and the producer HAS run" and "this gate is not in the
    roster at all". Every case below that asserts a decline asserts this first,
    or it would pass on a tree where the fix does not exist — measured: the two
    phase-3 cases were green on base main for exactly that reason before this
    helper was added."""
    assert GATE in F._GATE_SUBJECT_PRODUCED_BY, (
        "the roster entry is the premise of every decline asserted here")


def _phase3_reached(project: Path) -> Path:
    """A tree in which step 22 was REACHABLE: its declared input exists."""
    d = PL.pnr_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    (d / "routed.def").write_text("DESIGN t ;\nEND DESIGN\n")
    return project


def _with_spef(project: Path) -> Path:
    e = PL.extracted_dir(project)
    e.mkdir(parents=True, exist_ok=True)
    (e / "parasitic.spef").write_text("*SPEF \"IEEE 1481-1999\"\n")
    return project


# --------------------------------------------------------------------------- #
# (1) a phase-2-only run: asked EARLY, and that is skip-eligible
# --------------------------------------------------------------------------- #
def test_a_phase2_only_run_books_the_gate_as_asked_before_its_producer(tmp_path):
    """RED before this change: the gate was not in the roster, so the prose
    recogniser reached `no_spef` and booked BLOCKED_BY_UPSTREAM."""
    early = F._asked_before_producer(GATE, tmp_path)
    assert early is not None, "a phase-2-only tree must read as asked-early"
    assert early["producer_has_run"] is False
    assert "step 22" in early["producer"]
    assert "routed.def" in early["producer"]


def test_asked_early_is_skip_eligible_and_blocked_by_upstream_is_not():
    """The whole reason the class matters: one keeps P0 green-able and the other
    does not. Asserted on the taxonomy, so a tier change cannot pass silently."""
    assert RT.ASKED_BEFORE_PRODUCER in RT.SKIP_ELIGIBLE
    assert RT.BLOCKED_BY_UPSTREAM not in RT.SKIP_ELIGIBLE
    assert RT.record_verdict(RT.ASKED_BEFORE_PRODUCER) == "SKIP"
    assert RT.p0_tier_for_reason_classes([RT.ASKED_BEFORE_PRODUCER]) == "PASS"


def test_the_gates_own_no_spef_sentence_alone_still_is_not_skip_eligible():
    """The fix is the branch-owned evidence, NOT a new prose recogniser. The
    sentence on its own must keep the reading it had, or the next gate to say
    `no_spef` would inherit a tier nobody granted it."""
    got = RT.infer_nonverdict_reason(
        verdict="SKIP", message="examined nothing (reason: no_spef)",
        evidence={"exit_code": 2, "skip_kind": "input-missing"})
    assert got not in RT.SKIP_ELIGIBLE, got


# --------------------------------------------------------------------------- #
# (2) a phase-3 run that produced a SPEF: the gate is asked and decides
# --------------------------------------------------------------------------- #
def test_a_phase3_run_with_a_spef_is_not_excused(tmp_path):
    """Once the producer has run, the gate owns its own answer again — the
    narrow half of R-0915-46/47."""
    _assert_the_mechanism_is_wired()
    project = _with_spef(_phase3_reached(tmp_path))
    assert F._asked_before_producer(GATE, project) is None


# --------------------------------------------------------------------------- #
# (3) a phase-3 run whose SPEF step FAILED: BLOCKED_BY_UPSTREAM stays
# --------------------------------------------------------------------------- #
def test_a_phase3_run_whose_spef_step_failed_keeps_blocked_by_upstream(tmp_path):
    """THE CASE THE PREDICATE IS SHAPED AROUND. Extraction was reachable and
    delivered nothing; that is a real upstream failure and must NOT be laundered
    into an asked-too-early skip."""
    _assert_the_mechanism_is_wired()
    project = _phase3_reached(tmp_path)          # routed.def present, no SPEF
    assert not list(PL.extracted_dir(project).glob("*.spef"))
    assert F._asked_before_producer(GATE, project) is None
    # and with no branch-owned class, the gate's own sentence still books the
    # upstream cascade, exactly as it did before this change
    got = RT.infer_nonverdict_reason(
        verdict="SKIP", message="examined nothing (reason: no_spef)",
        evidence={"exit_code": 2, "skip_kind": "input-missing"})
    assert RT.record_verdict(got) in ("BLOCKED", "INCOMPLETE")


def test_the_predicate_reads_the_producers_INPUT_not_its_OUTPUT(tmp_path):
    """Stated as its own case because keying on the SPEF would inverse case (3):
    a SPEF present with NO routed.def must still not be read as asked-early."""
    project = _with_spef(tmp_path)               # SPEF but no routed.def
    assert F._asked_before_producer(GATE, project) is not None
    _phase3_reached(project)                     # now the input exists too
    assert F._asked_before_producer(GATE, project) is None


# --------------------------------------------------------------------------- #
# the flow's own declaration is the premise: step 22 owns the SPEF
# --------------------------------------------------------------------------- #
def test_the_flow_still_says_step_22_produces_the_spef_from_routed_def():
    """If the flow moved either edge, this fix would point at the wrong step and
    must fail loudly rather than quietly excuse the gate."""
    yaml = pytest.importorskip("yaml")
    steps = {str(s["id"]): s for s in yaml.safe_load(FLOW_YAML.read_text())["steps"]}
    twenty_two = steps["22"]
    assert any("spef" in str(o).lower()
               for o in twenty_two["required_outputs"]), twenty_two
    assert any(str(i.get("path", "")).endswith("routed.def")
               for i in twenty_two["required_inputs"]), twenty_two
    assert twenty_two["stage"] == "stage3"


def test_the_other_two_roster_entries_are_untouched():
    """This change ADDS one entry; the two that were there keep their producers."""
    roster = F._GATE_SUBJECT_PRODUCED_BY
    assert "klayout_deck_mode_check" in roster
    assert "gate_evidence_completeness_check" in roster
    assert roster["klayout_deck_mode_check"][1] is F._phase3_drc_ran
    assert roster["gate_evidence_completeness_check"][1] is F._completion_audit_written


@pytest.mark.parametrize("stage", ["before_route", "route_without_receipt", "bad_current_before_route",
                                   "refusal_before_route", "tool_result_before_route"])
def test_native_spice_gate_and_p0_keep_the_producer_boundary(tmp_path, monkeypatch, stage):
    import json
    import spice_correlation_check as SC
    rtl = tmp_path / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "core.v").write_text("module core(input a, output b); assign b=a; endmodule\n")
    if stage == "route_without_receipt":
        _phase3_reached(tmp_path)
    elif stage == "bad_current_before_route":
        current = tmp_path / "reports/phase3/spice_correlation.current.json"
        current.parent.mkdir(parents=True)
        current.write_text(json.dumps({"verdict": "PASS", "schema": "foreign"}))
    elif stage in ("refusal_before_route", "tool_result_before_route"):
        name = 'spice_correlation.json' if stage == 'refusal_before_route' else 'spice_path_tool.json'
        result = tmp_path / 'reports/phase3' / name
        result.parent.mkdir(parents=True)
        result.write_text(json.dumps({'verdict': 'NOT_MEASURED', 'status': 'ERROR'}))
    report = tmp_path / "native-spice-gate.json"
    rc = SC.main([str(tmp_path), "--no-spice", "--json", str(report)])
    doc = json.loads(report.read_text())
    early = stage == "before_route"
    assert rc == (2 if early else 1), doc
    assert doc["summary"]["measurement"] == "NOT_MEASURED"
    assert doc["summary"]["skipped"] is early
    if early:
        assert doc["summary"]["reason_class"] == RT.ASKED_BEFORE_PRODUCER
        assert doc["summary"]["current_binding"] == "NOT_YET_PRODUCED"
    else:
        assert not doc["passed"]
        assert any(f["rule"] == "SPICE_CURRENT_INPUTS_UNBOUND" for f in doc["findings"])
    # Only this declared gate is the bounded subject; its actual subprocess runs.
    monkeypatch.setattr(F, "_STRUCTURAL_RTL_GATES", (GATE,))
    records = []
    passed, fails, skips, waivers = F._run_structural_rtl_gates(tmp_path, records_out=records)
    assert len(records) == 1 and records[0]["name"] == GATE
    assert records[0]["verdict"] == ("SKIP" if early else "FAIL"), records
    assert passed is early
    assert not waivers
    if early:
        assert not fails and skips
        assert records[0]["reason_class"] == RT.ASKED_BEFORE_PRODUCER
    else:
        assert fails and not skips
