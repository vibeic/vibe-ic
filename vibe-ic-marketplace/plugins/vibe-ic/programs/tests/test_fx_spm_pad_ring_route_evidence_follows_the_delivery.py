"""FX_SPM_GATES_2 (2): the pad-ring route attestation is owed by a die only.

MEASURED on the same-RTL spm x gf180mcuD run (lane cmpb N5; deliverable
HARDMACRO, a core-only design with no pad ring): step 37 FAILED
`required_outputs missing: ['reports/phase3/pad_ring_route_evidence.json']`
(missing_artefact). Its only producer, `step_pad_ring_final_evidence`, runs
only under `_chip_path_requests_pad_ring(project)` -- step 15.5ic's condition
-- so the flow owed a HARDMACRO an artefact its producer correctly never
writes.

The rule: step 37 keeps declaring the attestation (every other reader --
matrix pins, the publisher, d4 grounding -- sees the step unchanged), and
`output_conditions` makes that ONE entry NOT_APPLICABLE when the step-15.5ic
route condition is false: an owner-declared hardmacro with no operator slot,
or no live slot/SELF_TAPEOUT route marker. A DIE on a live route still owes it.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(HERE))

import pytest                                            # noqa: E402

import _tapeout_declaration as TD                        # noqa: E402
import flow_compliance_check as F                        # noqa: E402
import test_issue2277_hardmacro_owes_no_die_steps as H   # noqa: E402
from _invocation_fixture import bind_invocation_top, preserve_invocation_runtime

EVIDENCE = "reports/phase3/pad_ring_route_evidence.json"
GDS = "phase3/stage4/gds/top.gds"


def _step37():
    return H._steps()["37"]


def _mini_step():
    """Step 37's own declaration of the attestation and its output condition,
    with a gate that only asks for the GDS -- so the verdict is decided by
    the required_outputs rule under test, not by the real step's programs."""
    real = _step37()
    return {"id": "37", "name": real["name"], "stage": real["stage"],
            "required_outputs": ["phase3/stage4/gds/*.gds", EVIDENCE],
            "output_conditions": real.get("output_conditions"),
            "gate": {"all_of": [{"files_exist": ["phase3/stage4/gds/*.gds"]}]},
            "blocks_on": []}


def _run(tmp_path, *, with_evidence=False, no_route=False, **kw):
    project = H._project(tmp_path, **kw)
    bind_invocation_top(project, 'top')
    if no_route:
        for slot in (project / "input/submission_template/slots").glob("*.yaml"):
            slot.unlink()
        (project / "input/submission_template/SELF_TAPEOUT.txt").unlink(
            missing_ok=True)
    gds = project / GDS
    gds.parent.mkdir(parents=True, exist_ok=True)
    gds.write_bytes(b"\x00\x06\x00\x02\x02\x58" * 64)
    if with_evidence:
        ev = project / EVIDENCE
        ev.parent.mkdir(parents=True, exist_ok=True)
        ev.write_text('{"verdict": "PASS"}\n')
    return F.check_step(project, _mini_step(), {})


def test_step_37_still_declares_it_with_the_die_steps_own_clause():
    step = _step37()
    assert EVIDENCE in step["required_outputs"]
    cond = (step.get("output_conditions") or {}).get(EVIDENCE)
    assert cond, "step 37 declares no condition for the attestation"
    assert cond["delivery_declares"] == \
        H._steps()["15.5ic"]["condition"]["delivery_declares"]
    assert cond == H._steps()["15.5ic"]["condition"]


def test_a_declared_hardmacro_does_not_owe_the_route_attestation(tmp_path):
    """RED on main: `required_outputs missing: [...pad_ring_route_evidence...]`."""
    r = _run(tmp_path)                                   # HARDMACRO, no slot
    blob = " ".join(r.reasons)
    assert r.status != "FAIL", blob
    assert f"required_outputs missing" not in blob
    assert f"declared output {EVIDENCE!r} NOT_APPLICABLE for this delivery" in blob
    assert "tapeout_declaration.json" in blob and "HARDMACRO" in blob
    binding = r.output_binding
    assert binding["n_specs"] == binding["n_satisfied"] == \
        len(binding["specs"]) == 1
    assert binding["not_owed"] == [EVIDENCE]


@pytest.mark.parametrize("kw", [
    {"deliverable": "DIE"},
    {"deliverable": "DIE", "self_tapeout": True},
    {"declaration": False},
], ids=["die", "die-self-tapeout", "unreadable-declaration"])
def test_a_die_still_owes_it(tmp_path, kw):
    r = _run(tmp_path, **kw)
    assert r.status == "FAIL" and r.reason_class == "missing_artefact", r.reasons
    assert any(f"required_outputs missing: ['{EVIDENCE}']" in x for x in r.reasons)


def test_a_die_that_has_it_passes(tmp_path):
    r = _run(tmp_path, with_evidence=True, deliverable="DIE")
    assert r.status != "FAIL", r.reasons


@pytest.mark.parametrize("kw", [
    {}, {"deliverable": "DIE"}, {"deliverable": "DIE", "self_tapeout": True},
], ids=["hardmacro", "die", "die-self-tapeout"])
def test_the_requirement_asks_the_producers_own_question(tmp_path, kw):
    """On valid live routes, the requirement agrees with the producer."""
    project = H._project(tmp_path, **kw)
    owed = F._output_not_owed(project, _step37(), EVIDENCE) is None
    assert owed is bool(TD.requests_pad_ring(project))


def test_bought_slot_hardmacro_refuses_in_producer_and_both_requirements(
        tmp_path):
    project = H._project(tmp_path, operator={"path": "t.yaml",
                                             "slot": "slot_1x1"})
    def outcome(call):
        try:
            return f"ACCEPTED: {call()!r}"
        except ValueError as exc:
            return f"REFUSED: {exc}"

    observed = [
        outcome(lambda: TD.requests_pad_ring(project)),
        outcome(lambda: F._check_condition(
            project, H._steps()["15.5ic"]["condition"])),
        outcome(lambda: F._output_not_owed(project, _step37(), EVIDENCE)),
    ]
    expected = ("REFUSED: deliverable HARDMACRO (IP path) contradicts a "
                "bought shuttle slot (IC path); declare one route in "
                "input/step_0_5ic_answers.json")
    assert observed == [expected] * 3


def test_bought_slot_die_still_owes_the_route_attestation(tmp_path):
    operator = {"path": "t.yaml", "slot": "slot_1x1"}
    project = H._project(tmp_path / "producer", deliverable="DIE",
                         operator=operator)
    assert TD.requests_pad_ring(project) is True
    assert F._check_condition(project,
                              H._steps()["15.5ic"]["condition"]) is True
    assert F._output_not_owed(project, _step37(), EVIDENCE) is None
    missing = _run(tmp_path / "missing", deliverable="DIE", operator=operator)
    assert missing.status == "FAIL"
    assert missing.reason_class == "missing_artefact"
    present = _run(tmp_path / "present", deliverable="DIE", operator=operator,
                   with_evidence=True)
    assert present.status != "FAIL", present.reasons


@pytest.mark.parametrize("kw", [
    {"deliverable": "DIE"}, {"declaration": False},
], ids=["die-no-route", "unreadable-declaration-no-route"])
def test_no_route_has_no_attestation_producer_or_requirement(tmp_path, kw):
    project = H._project(tmp_path, **kw)
    for slot in (project / "input/submission_template/slots").glob("*.yaml"):
        slot.unlink()
    assert TD.requests_pad_ring(project) is False
    assert F._check_condition(project, H._steps()["15.5ic"]["condition"]) is False
    why = F._output_not_owed(project, _step37(), EVIDENCE)
    assert why and "NOT_APPLICABLE" in why and "slots" in why, why
    r = _run(tmp_path / "audit", no_route=True, **kw)
    assert r.status != "FAIL", r.reasons
    assert r.output_binding["not_owed"] == [EVIDENCE]


def test_an_entry_without_a_condition_is_always_owed(tmp_path):
    project = H._project(tmp_path)                       # HARDMACRO
    assert F._output_not_owed(project, _step37(),
                              "phase3/stage4/gds/*.gds") is None
