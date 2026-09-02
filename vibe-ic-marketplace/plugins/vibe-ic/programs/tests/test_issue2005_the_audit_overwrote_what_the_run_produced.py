#!/usr/bin/env python3
"""#2005's refusal, measured in BOTH directions on the shape #306 creates.

THE COLLISION, IN ONE SENTENCE
==============================
`flow_compliance_check` refuses a declared `required_output` that is also this
step's own gate ``--json`` target, because an auditor may not credit an
artefact it authored. #306 says the opposite thing about the same file: a gate
wired ONLY in the yaml "can describe a run that already happened; it cannot
refuse one", so the runner is wired to execute the SAME checker at the SAME
``--json`` path during the run. For the 13 declarations whose gate program is
also listed under the step's ``programs:``, both statements are about one path
and one document, and #2005 decided it by asking the DOCUMENT who wrote it —
which that document cannot know.

MEASURED, on a real completed run (`$HOME/vibeic-designs/spm_rep1`, 2026-08-30):

    reports/orchestrator/phase2_one_shot.json   17:06:53
        crosslayer_rewrite_fidelity  PASS
        ['reports/crosslayer/rewrite_equivalence_check.json']
    reports/crosslayer/rewrite_equivalence_check.json   mtime 17:14:55
    reports/phase2/gates/formal_evidence.json          mtime 17:14:55

i.e. the RUN recorded producing the artefact, and the AUDIT's pen landed on it
eight minutes later, co-timed with a file only the audit writes. The document
is stamped `program: crosslayer_rewrite_equivalence_check` either way, because
that ONE program is both the step's producer and its gate.

AND THE SAME RULE LEAKED THE OTHER WAY. `flow_compliance_check . --phase 2`
run TWICE against that same unchanged tree, before this change:

    pass 1  SELF-CERTIFIED EVIDENCE EXCLUDED (audit_created)
            ['reports/crosslayer/rewrite_equivalence_check.json',
             'reports/phase1/gates/stage_phase1_compliance.json']
    pass 2  SELF-CERTIFIED EVIDENCE EXCLUDED (audit_created)
            ['reports/crosslayer/rewrite_equivalence_check.json']

`stage_phase1_compliance.json` is written by `flow_compliance_check --json`,
whose document carries none of `_GATE_DOCUMENT_IDENTITY_KEYS`, so pass 2 read
the audit's own pass-1 output as the run's — the "MISSING once and PASS forever
after" that #1981 and #2005 both exist to refuse, live in the shipped code.

WHAT EACH TEST BELOW HOLDS
==========================
Both halves run the REAL `check_step`, the REAL `_evaluate_gate` and the REAL
gate programs. Nothing is monkeypatched.

  POSITIVE   the RUN produces the declared output by calling the production
             function that produces it on every real run
             (`design_one_shot_runner.step_crosslayer_rewrite_fidelity`), the
             audit then overwrites it, and it must still be credited. On the
             pre-fix tree this reported MISSING.
  NEGATIVE   the run produces NOTHING, the audit's own gate is the first
             writer, and the verdict must stay MISSING — on every pass. Two
             constructions, because the two halves of the refusal fail
             differently: a gate whose document IS stamped, and a gate whose
             document is NOT (`post_route_signoff_corner_check`, one of the two
             shipped gate programs measured to exit 0 with an unstamped
             ``--json`` document).

The fixture NEVER hand-writes a gate's own report to satisfy an output check.
Where the artefact exists before the audit, it exists because the production
producer wrote it.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
sys.path.insert(0, str(_PROGRAMS))

import flow_compliance_check as FCC          # noqa: E402
import design_one_shot_runner as DOSR        # noqa: E402

#: The declared output at the centre of the measurement, and the step that
#: declares it. Both are re-derived from the yaml below rather than trusted
#: from here; these names only make the test readable.
_REL = "reports/crosslayer/rewrite_equivalence_check.json"
_SID = "2"


def _steps() -> Dict[str, Dict[str, Any]]:
    doc = yaml.safe_load(_FLOW.read_text(errors="replace"))
    return {str(s["id"]): s for s in doc["steps"]}


def _judge_clause(step: Dict[str, Any]) -> Dict[str, str]:
    """Step 2's OWN declared rewrite-fidelity clause, read from the yaml."""
    for clause in step["gate"]["all_of"]:
        if (isinstance(clause, dict) and "program_exit_zero" in clause
                and "crosslayer_rewrite_equivalence_check"
                in clause["program_exit_zero"]):
            return clause
    raise AssertionError(
        "step 2 no longer declares a crosslayer_rewrite_equivalence_check "
        "program_exit_zero clause; re-base this test on the clause that "
        "replaced it rather than deleting the measurement")


def _isolated_step() -> Dict[str, Any]:
    """The real step 2, reduced to the ONE clause under measurement.

    Step 2's other clauses reach for a Phase-1 tree this fixture does not have
    and refuse (correctly) on their own account; a FAIL is not a done claim, so
    the MISSING downgrade this file measures would never be reachable and both
    halves would report the same thing. The clause kept is step 2's own, read
    from the yaml, executed by the real `_evaluate_gate`. `programs:` is the
    real list, which is what makes `crosslayer_rewrite_equivalence_check` both
    a declared producer and the gate — the whole subject.
    """
    real = _steps()[_SID]
    step = dict(real)
    step["gate"] = {"all_of": [_judge_clause(real)]}
    step["required_outputs"] = [_REL]
    step.pop("closed_loop", None)
    step.pop("blocks_on", None)
    return step


def _project(tmp: Path) -> Path:
    p = tmp / "proj"
    rtl = p / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "d.v").write_text("module d(); endmodule\n")
    return p


@pytest.fixture()
def workdir():
    d = Path(tempfile.mkdtemp(prefix="i2005_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ===========================================================================
# The step's own declaration — the premise every assertion below rests on
# ===========================================================================
def test_the_shape_under_measurement_is_still_declared():
    step = _steps()[_SID]
    assert _REL in (step.get("required_outputs") or []), (
        f"step {_SID} no longer declares {_REL} as a required_output; this "
        f"file measures the collision between that declaration and the same "
        f"path being the step's own gate --json target")
    assert _REL in FCC._gate_json_targets(step), (
        f"{_REL} is no longer a --json target of step {_SID}'s own gate")
    assert "crosslayer_rewrite_equivalence_check" in (step.get("programs") or []), (
        "the program that writes this path is no longer listed as a step-2 "
        "producer, so it is no longer the BOTH-producer-and-gate shape this "
        "file is about")


def test_the_production_runner_still_produces_it_during_the_run():
    """#306's half of the collision, asserted rather than assumed.

    If the runner stops writing this path the POSITIVE test below would be
    planting the artefact itself, which is exactly the manufactured
    completeness this file must not do.
    """
    src = (_PROGRAMS / "design_one_shot_runner.py").read_text(errors="replace")
    assert f'out_rel = "{_REL}"' in src, (
        f"design_one_shot_runner no longer writes {_REL} during the run")
    assert "plan.append(step_crosslayer_rewrite_fidelity(project))" in src, (
        "the producer is no longer wired into the phase-2 plan")


# ===========================================================================
# POSITIVE — the run produced it, the audit overwrote it, it still counts
# ===========================================================================
def test_a_run_produced_output_survives_the_audit_overwriting_it(workdir):
    project = _project(workdir)
    step = _isolated_step()

    run = DOSR.step_crosslayer_rewrite_fidelity(project)
    assert run.status == "PASS" and _REL in run.output_files, (
        f"fixture defect: the production producer did not produce {_REL} "
        f"({run.status}: {run.detail}) — nothing below would be measuring a "
        f"run artefact")
    before = (project / _REL).read_bytes()
    assert before, "fixture defect: the producer wrote an empty artefact"

    first = FCC.check_step(project, _isolated_step(), {})
    assert first.status not in ("MISSING",), (
        f"the RUN produced {_REL} before this audit began and the audit's own "
        f"gate then rewrote the same path; reporting {first.status!r} says the "
        f"step has no run evidence for an artefact the run demonstrably "
        f"produced. Reasons: {[str(r)[:200] for r in first.reasons]}")
    assert _REL in first.evidence, (
        f"{_REL} was produced by the run and is not in the credited evidence "
        f"{list(first.evidence)!r}")
    assert not any("audit_created" in str(r) and _REL in str(r)
                   for r in first.reasons), (
        f"{_REL} is still reported as audit-created: "
        f"{[str(r)[:200] for r in first.reasons]}")

    second = FCC.check_step(project, _isolated_step(), {})
    assert second.status == first.status and _REL in second.evidence, (
        f"pass 1 credited {_REL} and pass 2 reported {second.status!r} with "
        f"evidence {list(second.evidence)!r} — a verdict that depends on how "
        f"many times the auditor has run is not a measurement")


# ===========================================================================
# NEGATIVE — nothing but the audit ever wrote it, and that never counts
# ===========================================================================
def test_an_output_only_the_audit_ever_wrote_stays_missing(workdir):
    """The half without which this change would just be the rule switched off.

    Same step, same real gate, same declared output — and the production
    producer is NOT run. The audit's own gate is then the only process that
    can create the file, and it must never buy the step a done claim, on this
    pass or any later one.
    """
    project = _project(workdir)
    assert not (project / _REL).exists()

    seen: List[str] = []
    for _ in range(3):
        res = FCC.check_step(project, _isolated_step(), {})
        seen.append(res.status)
        assert _REL not in res.evidence, (
            f"{_REL} exists only because this audit's own gate wrote it and it "
            f"was credited as run evidence: {list(res.evidence)!r}")
    assert seen == ["MISSING", "MISSING", "MISSING"], (
        f"the run produced nothing and the verdicts across three passes were "
        f"{seen} — the refusal must not decay with the number of passes")


def test_the_refusal_holds_for_a_gate_whose_document_carries_no_stamp(workdir):
    """The direction the CONTENT test could never cover, and it was leaking.

    `_is_gate_verdict_document` can only recognise a gate's own document when
    that gate stamps its name into it. `post_route_signoff_corner_check` is one
    of two shipped gate programs measured to exit 0 while writing a ``--json``
    document carrying none of `_GATE_DOCUMENT_IDENTITY_KEYS`; step 23 declares
    its output. With one other declared output present (so the unconditional
    all-absent early return does not fire), the pre-fix code refused the
    artefact on pass 1 and credited it on pass 2 — MISSING then INCOMPLETE, on
    an unchanged tree.
    """
    project = _project(workdir)
    rel = "reports/phase3/sta/post_route_signoff_corner.json"
    other = "_i2005/produced_by_the_run.txt"
    (project / "_i2005").mkdir(parents=True)
    (project / other).write_text("the run produced this one\n")
    step = {"id": "I2005", "name": "unstamped gate document", "stage": "stage3",
            "programs": [],
            "gate": {"program_exit_zero":
                     f"post_route_signoff_corner_check . --json {rel}"},
            "required_outputs": [other, rel]}
    assert rel in FCC._gate_json_targets(step)

    seen = []
    for _ in range(3):
        res = FCC.check_step(project, dict(step), {})
        seen.append(res.status)
        assert rel not in res.evidence, (
            f"the audit's own unstamped document was credited: "
            f"{list(res.evidence)!r}")
    assert seen == ["MISSING"] * 3, (
        f"three passes over an unchanged tree reported {seen}; the pre-fix "
        f"code reported ['MISSING', 'INCOMPLETE', 'INCOMPLETE'] here")
    assert (project / rel).is_file(), (
        "fixture defect: the gate never wrote its --json target, so the "
        "second and third passes were not the case this test is about")


# ===========================================================================
# The narrowing is exactly one branch wide
# ===========================================================================
def _doc(tmp: Path, name: str, payload: Dict[str, Any]) -> Path:
    p = tmp / name
    p.write_text(json.dumps(payload) + "\n")
    return p


def test_only_the_shared_producer_and_gate_branch_defers_to_timing(workdir):
    gate = frozenset({"g_check", "shared_check"})
    producers = frozenset({"p_gen", "shared_check"})

    gate_only = _doc(workdir, "a.json", {"program": "g_check", "verdict": "X"})
    assert FCC._is_gate_verdict_document(gate_only, gate, producers) is True, (
        "a document stamped ONLY by this step's gate is still the auditor's")

    producer_only = _doc(workdir, "b.json", {"program": "p_gen"})
    assert FCC._is_gate_verdict_document(producer_only, gate, producers) is False

    shared = _doc(workdir, "c.json", {"program": "shared_check"})
    assert FCC._is_gate_verdict_document(shared, gate, producers) is False, (
        "a program that is BOTH a listed producer and this step's gate writes "
        "the same bytes either way, so content must not answer here")

    both_stamps = _doc(workdir, "d.json",
                       {"program": "shared_check", "gate": "g_check"})
    assert FCC._is_gate_verdict_document(both_stamps, gate, producers) is True, (
        "a gate-ONLY stamp anywhere in the document still decides it")

    unstamped = _doc(workdir, "e.json", {"findings": []})
    assert FCC._is_gate_verdict_document(unstamped, gate, producers) is False

    assert FCC._is_gate_verdict_document(gate_only) is True, (
        "the presence-only answer callers that pass no names rely on must be "
        "unchanged")


# ===========================================================================
# The durable note is a statement about a FILE, not a permanent verdict
# ===========================================================================
def test_the_authorship_note_is_verified_against_the_live_file(workdir):
    project = workdir / "notes"
    (project / "reports").mkdir(parents=True)
    rel = "reports/x.json"
    (project / rel).write_text('{"a": 1}\n')

    FCC._record_audit_created(project, "N1", [rel])
    assert FCC._prior_audit_created(project, "N1", [rel]) == {rel}
    assert FCC._prior_audit_created(project, "OTHER", [rel]) == set(), (
        "the note is keyed by (step, path); another step must not inherit it")

    # The RUN re-produces the artefact: the note describes bytes that are gone.
    (project / rel).write_text('{"a": 1, "produced_by": "the run"}\n')
    assert FCC._prior_audit_created(project, "N1", [rel]) == set(), (
        "a note whose recorded size/mtime no longer matches the live file is "
        "stale and must not keep refusing an artefact the run has since "
        "written")

    FCC._record_audit_created(project, "N1", [rel])
    assert FCC._prior_audit_created(project, "N1", [rel]) == {rel}
    FCC._drop_audit_created_note(project, "N1", [rel])
    assert FCC._prior_audit_created(project, "N1", [rel]) == set()


def test_the_note_never_lands_outside_the_auditors_own_directory(workdir):
    project = workdir / "scope"
    project.mkdir()
    note = FCC._authorship_note_path(project, "2", _REL)
    assert note.parent == project / "reports" / "audit" / "audit_created", (
        f"the audit's bookkeeping must stay in its own directory; {note} is "
        f"outside it")


# ===========================================================================
# The population, derived — not a list somebody typed
# ===========================================================================
def test_the_shared_producer_and_gate_population_is_declared_here():
    """How many declarations the narrowed branch can reach, re-derived live.

    A count alone cannot see a swap, so the MEMBERS are pinned. This is the
    population the change is about: every `required_outputs` entry that is also
    a ``--json`` target of a gate command whose program the same step lists
    under `programs:`.
    """
    measured = set()
    for sid, step in _steps().items():
        outs = set(step.get("required_outputs") or [])
        if not outs:
            continue
        progs = {str(p).strip() for p in (step.get("programs") or [])
                 if isinstance(p, str)}

        pairs = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for key, val in node.items():
                    if key.endswith("program_exit_zero"):
                        cmd = val if isinstance(val, str) else str(
                            (val or {}).get("command", ""))
                        toks = cmd.split()
                        for i, tok in enumerate(toks[:-1]):
                            if tok == "--json" and toks:
                                pairs.append((toks[0], toks[i + 1]))
                    else:
                        walk(val)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(step.get("gate") or {})
        for prog, target in pairs:
            if target in outs and prog in progs:
                measured.add((str(sid), target))

    pinned = {
        ("2", "reports/crosslayer/rewrite_equivalence_check.json"),
        ("2", "reports/phase2/lint/rom_init_lint.json"),
        ("2", "reports/phase2/lint/rtl_hygiene.json"),
        ("8", "reports/phase2/sdc_check.json"),
        ("11", "reports/phase2/dft/bsdl_plan.json"),
        ("15.5ic", "reports/phase3/pad_assignment.json"),
        ("26", "reports/phase3/antenna_signoff.json"),
        ("28", "reports/phase2/gates/perc_signoff.json"),
        ("29", "reports/phase2/gates/post_layout_sim.json"),
        ("31", "reports/phase2/gates/erc_density.json"),
        ("36", "reports/audit/tapeout_checklist.json"),
        ("38", "reports/phase3/foundry_handoff_audit.json"),
        ("M1", "reports/analog/mixed_signal/merge.json"),
    }
    assert measured == pinned, (
        f"the BOTH-producer-and-gate population moved — arrived: "
        f"{sorted(measured - pinned)}; departed: {sorted(pinned - measured)}. "
        f"Each entry is a path whose audit-vs-run authorship content cannot "
        f"decide; a new one is a new place this rule is load-bearing, and a "
        f"departure means the flow stopped pointing the auditor's pen at a "
        f"declared run artefact. Re-derive both, do not edit one to fit.")
