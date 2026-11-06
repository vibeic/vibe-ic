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


# ===========================================================================
# NEGATIVE — nothing but the audit ever wrote it, and that never counts
# ===========================================================================




# ===========================================================================
# The narrowing is exactly one branch wide
# ===========================================================================
def _doc(tmp: Path, name: str, payload: Dict[str, Any]) -> Path:
    p = tmp / name
    p.write_text(json.dumps(payload) + "\n")
    return p




# ===========================================================================
# The durable note is a statement about a FILE, not a permanent verdict
# ===========================================================================




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
        ("M1", "reports/analog/mixed_signal/merge.json"),
        # ARRIVED with the 13 producer declarations (lane icspm3, measured
        # 2026-09-15 on spm x gf180mcuD at main b47917a47). Each of these was
        # already a `--json` target of its own step's gate AND a declared
        # `required_output`; what changed is that the step now NAMES the
        # program under `programs:`, so `flow_declared_producer_run` executes
        # it during the run and the document stops being the auditor's own
        # output. They belong in this population for exactly the reason the
        # thirteen above do: the stamp is the same whichever process wrote it,
        # so content cannot decide and the two TIMING facts have the last word.
        ("10", "reports/phase3/sta/pre_pnr_summary.json"),
        ("15", "reports/phase2/gates/stage2_compliance.json"),
        ("21", "reports/phase3/drc_router.json"),
        ("23", "reports/phase3/sta/post_route_summary.json"),
        ("24", "reports/phase3/ir_drop_signoff.json"),
        ("25", "reports/phase3/em_signoff.json"),
        ("25", "reports/phase3/em_current_authority.json"),
        ("26.5ic", "reports/phase3/die_finishing.json"),
        ("31", "reports/phase3/drc_signoff.json"),
        ("31", "reports/phase3/lvs.json"),
        ("37", "reports/phase3/gates/stage3_compliance.json"),
        ("37.5ip", "reports/phase3/digital_hardmacro.json"),
        ("37.5ic", "reports/phase3/tapeout_precheck.json"),
        # ARRIVED 2026-09-15 (lane icspm3) on the SPM verdict run at main
        # 79506306d. These two were NAMED in the first pass and deliberately
        # left, because `flow_compliance_check`'s `--json` document carries
        # none of `_GATE_DOCUMENT_IDENTITY_KEYS` — which is precisely why
        # they had to be declared in the end: with no producer, whether the
        # document exists before the audit begins is a RACE, and on a loaded
        # host it landed the other way (step 2 MISSING instead of INCOMPLETE,
        # stage1_compliance FAILING for the first time). They belong in this
        # population for the population's own stated reason: content cannot
        # decide their authorship, so the two timing facts have the last word
        # — and a declared producer is what makes those facts deterministic.
        # DEPARTED 2026-09-24 (R-0915-141, step-38 half, lane ictier1): ("2",
        # "reports/phase1/gates/stage_phase1_compliance.json"). Step 2 no longer
        # DECLARES its nested stage_phase1 clause's own verdict target, so the
        # auditor's pen no longer points at a declared run artefact there -- the
        # same departure, for the same reason, as 36 and 38 below. spm run23
        # measured the refusal it caused: "AUDIT-CREATED OUTPUT REFUSED".
        ("14", "reports/analog/stage_analog_compliance.json"),
        # DEPARTED 2026-09-23 (R-0915-141, lane icslot): ("36",
        # "reports/audit/tapeout_checklist.json") and ("38",
        # "reports/phase3/foundry_handoff_audit.json"). They left for the reason
        # this population's own message gives -- "the flow stopped pointing the
        # auditor's pen at a declared run artefact" -- which here is the fix, not
        # the regression. Step 36 now declares the checklist that
        # `tapeout_checklist_gen` ASSEMBLES while its gate writes its verdict to
        # `reports/audit/tapeout_signoff.json`; step 38 declares the four package
        # artefacts `foundry_handoff_pack_gen` assembles and no longer declares
        # its gate's own `foundry_handoff_audit.json` at all. Content no longer
        # has to decide their authorship, because one document is no longer two
        # documents at one path -- so the two timing facts are not needed, and
        # these two entries cannot be in this population by construction.
        # See test_a_declared_output_is_not_its_gates_verdict_target.py.
    }
    assert measured == pinned, (
        f"the BOTH-producer-and-gate population moved — arrived: "
        f"{sorted(measured - pinned)}; departed: {sorted(pinned - measured)}. "
        f"Each entry is a path whose audit-vs-run authorship content cannot "
        f"decide; a new one is a new place this rule is load-bearing, and a "
        f"departure means the flow stopped pointing the auditor's pen at a "
        f"declared run artefact. Re-derive both, do not edit one to fit.")
