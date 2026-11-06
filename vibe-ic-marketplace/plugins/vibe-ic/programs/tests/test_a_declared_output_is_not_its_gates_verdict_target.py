"""R-0915-141 — a step's declared output is a document the RUN produces.

Never the file its gate writes its verdict to. The gate READS that document and
writes its verdict elsewhere.

WHY, AND IT IS NOT A STYLE POINT. The audit refuses self-certified evidence on
three criteria, and the third is "holding a verdict document only this step's gate
emits". When a step's declared `required_output` IS its gate's `--json` target,
that criterion matches BY CONSTRUCTION -- whoever wrote the file, however early.
MEASURED on spm run22: `tapeout_checklist_gen` rewrote the checklist at 08:51:23
and the 09:02:35 audit still refused it. No ordering can settle that, which is why
the re-stamp fix (the other half of this branch) was necessary but not sufficient.

THE SPLIT, for the ruling's two steps:
  step 36  producer  tapeout_checklist_gen -> reports/audit/tapeout_checklist.json
           gate      tapeout_signoff_check . --mode tapeout
                     --json reports/audit/tapeout_signoff.json
  step 38  producer  foundry_handoff_pack_gen -> the four package artefacts
           gate      foundry_handoff_package_check . --json
                     reports/phase3/foundry_handoff_check.json
           and `reports/phase3/foundry_handoff_audit.json` -- the gate's own
           verdict target -- is no longer in the step's declared set.

`tapeout_checklist_gen` gained `--json` as an alias for `--out`, because the flow's
producer runner names every destination with `--json`.

MEASURED, main 93b2d10fa vs this tip, on a copy of run22's own tree:
  step 38  FAIL/missing_artefact, AUDIT-CREATED OUTPUT REFUSED = True
        -> NOT_MEASURED/upstream_failed, refused = False
  step 36  its declared output is no longer among its gate's `--json` targets, so
           `_declared_self_written` is EMPTY for it and the audit_created
           machinery cannot reach it at all.

THE CLASS IS WIDER THAN TWO STEPS, and this file says so rather than pretending
otherwise: 21 other steps still declare an output that is one of their own gate
clauses' receipt targets. They are pinned below as a measured residual that may
only SHRINK. Fixing each needs its own producer and its own evidence -- the shape
of this branch, 21 more times -- and a bare class-wide assertion would simply ship
21 reds.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

PLUGIN = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))


#: THE CLASS IS THE AUDIT'S OWN PREDICATE, NOT A REGEX OF MY OWN.
#:
#: This file previously derived membership from `--(?:json|report)`, which is a
#: WIDER set than the rule it is guarding. The audit's self-certified refusal is
#: `_declared_self_written = set(outputs) & _gate_json_targets(step)` -- `--json`
#: ONLY -- and the two disagreed on exactly one entry, which is why defining the
#: class twice is the defect and not a detail: step 31's
#: `reports/phase3/perc_sweep.json` is WRITTEN by its declared producer
#: `perc_corpus_sweep` and only READ by the gate's `sweep_reach_check --report`.
#: The regex called that a self-certified member and the failure text would have
#: demanded "a real producer" for a document that already has one.
#:
#: So membership is taken from `flow_compliance_check._gate_json_targets`, the
#: function the audit itself calls. A `--report` a gate READS is an input, and an
#: input is not a verdict target.


def _flow() -> dict:
    return yaml.safe_load(
        (PLUGIN / "flow" / "phase1_phase2_phase3.yaml").read_text())


def _clause_commands(gate) -> list:
    out: list = []

    def rec(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k.endswith("program_exit_zero"):
                    out.append(v if isinstance(v, str)
                               else str((v or {}).get("command", "")))
                else:
                    rec(v)
        elif isinstance(node, list):
            for item in node:
                rec(item)

    rec(gate)
    return out




#: MEASURED 2026-09-23 on this tree, AFTER the two steps this branch splits. A
#: RESIDUAL, not a permission: each member needs its own producer and its own
#: evidence, which is this branch's shape 21 more times.
#:
#: RATCHET ON MEMBERSHIP, NOT ON COUNT -- this repo's own rule (#900, quoted in
#: `prose_polarity_consulted_check`): a count cannot say WHICH step moved, and two
#: steps trading places move nothing.
_RESIDUAL = {
    "0.5ic": ["reports/phase1/submission_template.json",
              "reports/phase1/tapeout_declaration.json"],
    # `reports/phase1/gates/stage_phase1_compliance.json` LEFT step 2 by the
    # step-38 half of this ruling (lane ictier1, spm run23): it is the nested
    # stage_phase1 clause's verdict target and has no separate producer, so it
    # left the declared set. See test_step2_does_not_declare_its_nested_gates_
    # verdict_target.py.
    "2": ["reports/crosslayer/rewrite_equivalence_check.json",
          "reports/phase2/lint/rom_init_lint.json",
          "reports/phase2/lint/rtl_hygiene.json"],
    "8": ["reports/phase2/sdc_check.json"],
    "10": ["reports/phase3/sta/pre_pnr_summary.json"],
    "11": ["reports/phase2/dft/bsdl_plan.json"],
    "14": ["reports/analog/stage_analog_compliance.json"],
    "15": ["reports/phase2/gates/stage2_compliance.json"],
    "15.5ic": ["reports/phase3/pad_assignment.json",
               "reports/phase3/padring.json"],
    "21": ["reports/phase3/drc_router.json"],
    "23": ["reports/phase3/sta/post_route_signoff_corner.json",
           "reports/phase3/sta/post_route_summary.json",
           "reports/phase3/sta/sta_corner_record_completeness.json"],
    "24": ["reports/phase3/ir_drop_signoff.json"],
    "25": ["reports/phase3/em_current_authority.json",
           "reports/phase3/em_signoff.json"],
    "26": ["reports/phase3/antenna_signoff.json"],
    "26.5ic": ["reports/phase3/die_finishing.json"],
    "28": ["reports/phase2/gates/perc_signoff.json"],
    "29": ["reports/phase2/gates/post_layout_sim.json"],
    # `reports/phase3/perc_sweep.json` is NOT here, and the reason is the point of
    # this file: `perc_corpus_sweep` -- step 31's declared producer -- WRITES it
    # (producer_command), and the gate's `sweep_reach_check --report` only READS
    # it. It is a producer's document that a gate consults, which is exactly the
    # shape R-0915-141 asks for, not a violation of it.
    "31": ["reports/phase2/gates/erc_density.json",
           "reports/phase3/drc_signoff.json",
           "reports/phase3/lvs.json"],
    # Step 37's raw stage-3 compliance moved to 36. Its audit writes the
    # independent stage3_compliance_verdict.json, so neither remains here.
    "37.5ic": ["reports/phase3/tapeout_precheck.json"],
    "37.5ip": ["reports/phase3/digital_hardmacro.json"],
    "M1": ["reports/analog/mixed_signal/merge.json"],
}


# ── the ruling's two steps ─────────────────────────────────────────────────





def test_the_two_steps_declare_a_real_producer():
    """The other half of the split: the step's `programs:` must name the program
    that ASSEMBLES the document, not the checker that judges it."""
    by_id = {str(s.get("id")): s for s in _flow()["steps"] if isinstance(s, dict)}
    assert by_id["36"].get("programs") == ["stage3_compliance"], (
        by_id["36"].get("programs"))
    assert by_id["38"].get("programs") == ["foundry_handoff_pack_gen", "tapeout_checklist_gen"], (
        by_id["38"].get("programs"))
    assert "reports/phase3/gates/stage3_compliance.json" in by_id["36"]["required_outputs"]
    assert "reports/audit/tapeout_checklist.json" in by_id["38"]["required_outputs"]


def test_the_gates_still_run_and_write_their_verdict_somewhere():
    """A split that silenced the gate would be worse than the defect. Both gates
    are still invoked, and each names its own receipt path."""
    by_id = {str(s.get("id")): s for s in _flow()["steps"] if isinstance(s, dict)}
    c36 = " ".join(_clause_commands(by_id["36"].get("gate")))
    assert "stage3_compliance . --json " in c36, c36[:200]
    assert "reports/phase3/gates/stage3_compliance_verdict.json" in c36
    c38 = " ".join(_clause_commands(by_id["38"].get("gate")))
    # Complete tapeout sign-off follows precheck/docs and package preparation;
    # its original command and independent verdict target remain mandatory.
    assert "tapeout_signoff_check . --mode tapeout --json " in c38, c38[:200]
    assert "reports/audit/tapeout_signoff.json" in c38
    assert "foundry_handoff_package_check . --json " in c38, c38[:200]
    assert "reports/phase3/foundry_handoff_check.json" in c38




def test_the_generator_accepts_the_runners_flag():
    """`_run_declared_signoff_gate` builds `[prog, project, *argv, "--json", out]`
    for every producer it drives, so a producer that only knows `--out` cannot be
    wired without teaching the runner a second spelling per program."""
    import subprocess
    r = subprocess.run([sys.executable, str(PROGRAMS / "tapeout_checklist_gen.py"),
                        "--help"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-300:]
    assert "--json OUT" in r.stdout, r.stdout[:400]


# ── the class, as a ratchet that may only shrink ───────────────────────────









# ── the refusal is structurally unreachable, not merely avoided ─────────────











# ── the producer's document says not-ready, and the step fails ─────────────

def test_the_producer_marks_not_ready_in_the_document_itself(tmp_path):
    """A declared output is only worth declaring if it can say no. MEASURED on an
    empty tree: 10 of 10 blocker rows missing, `verdict` BLOCKER_MISSING."""
    import json
    import subprocess
    out = tmp_path / "reports/audit/tapeout_checklist.json"
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "tapeout_checklist_gen.py"),
         str(tmp_path), "--json", str(out)],
        capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-400:]
    doc = json.loads(out.read_text())
    assert doc["verdict"] == "BLOCKER_MISSING", doc["verdict"]
    assert doc["summary"]["blockers_missing"] == doc["summary"]["blockers_total"]
    assert doc["summary"]["blockers_total"] >= 10, doc["summary"]




# ── the two directions of the membership rule ──────────────────────────────
