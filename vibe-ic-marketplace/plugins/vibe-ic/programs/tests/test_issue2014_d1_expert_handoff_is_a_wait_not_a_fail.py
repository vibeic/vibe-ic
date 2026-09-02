#!/usr/bin/env python3
"""test_issue2014_d1_expert_handoff_is_a_wait_not_a_fail.py

Step D1 could not be passed by any program-only run, and the reason was a
missing third state (vibe-ic#2014, D1 half).

WHAT WAS MEASURED, on live main v1.16.87, one clean Path-A project, program
only, no agent invoked:

    phase1_expert_parse_track .            -> rc 1
    flow_compliance_check . --stage-id stage_phase1
                                           -> Step D1 FAIL, Overall FAIL
       reason: "program failed: phase1_expert_parse_track ."
       class : DESIGN_FACT / gate-reached-verdict
    step 1 (Spec-to-RTL) basis            -> "derived-from-upstream ... (D1)"

`ai_subtrack` is a TWO-PASS protocol and says so in its own hand-off message:
pass one writes the pack, then "invoke subagent vibe-ic:ic-expert-agent ... and
re-run to consume its answer". A PROGRAM cannot spawn that subagent, so
HANDOFF_EMITTED is what EVERY program-only invocation produces. D1 is the
flow's unconditional first step and D1's gate runs this program directly, so a
non-zero exit on that state is not a fact about any design — it is the front
door refusing everyone. `DESIGN_FACT` was, precisely, the wrong class.

1aa24ef268 already drew this line for the RUNNER's exit code
(`_expert_track_disposition`: CREDITED / PENDING / DEFECT). It could not draw
it for the FLOW, because the flow reads THIS program's exit code, where the
wait and a broken record were one number.

THE THREE STATES, and the two things this file refuses to let collapse again:

    CREDITED  rc 0   an answer was read and converged
    AWAITING  rc 4   the hand-off is written and pass two has not happened
    DEFECT    rc 1   a record readable as neither

  * WAITING MUST NOT BE FAILING. rc 4 + the `INCOMPLETE:` sentinel passes D1's
    clause and lands on the #599 INCOMPLETE tier — "not audited, and someone
    must return" — never a bare PASS.
  * WAITING MUST NOT BE PASSING EITHER. Credit stays withheld:
    `execution.complete` false, `execution.disposition` AWAITING, verdict
    INCOMPLETE, the tier printed on the roll-up line. #1973's measured lie —
    the runner reporting the second track as having "ran" — stays fixed.

AND THE GATE MUST STILL BITE. Two negative controls run the WHOLE clause, not
a fixture of it: a project with no Phase-1 input, and a project whose expert
answer exists in a shape the consumer cannot read. Both must still stop D1. A
repair that let everyone through would be the mirror of the defect it repairs.

Every fixture is synthesised here from neutral parts. No design, PDK, vendor or
IP identifier appears in this file.

Run: python3 -m pytest \\
     programs/tests/test_issue2014_d1_expert_handoff_is_a_wait_not_a_fail.py -q
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_expert_parse_track as T          # noqa: E402
import phase1_one_shot_runner as R             # noqa: E402
import flow_compliance_check as F              # noqa: E402
import _path_layout as _pl                     # noqa: E402
import _progress_run as _pr                    # noqa: E402


_INPUT_DOC = """# Block specification

The converter accepts an external reference on the REFHI terminal and
digitises to 12 bits at 500 ksps. Trim values are restored at power-up.
"""


def _project(tmp_path, name="proj"):
    p = tmp_path / name
    (p / "input" / "docs").mkdir(parents=True)
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "input" / "docs" / "spec.md").write_text(_INPUT_DOC)
    (p / "phase1" / "generated_docs" / "L1_DATASHEET.json").write_text(
        json.dumps({"doc_id": "L1", "fields": {"resolution_bits": 12}}))
    return p


def _pack_dir(project: Path) -> Path:
    return _pl.report_path(project, "phase1/expert_parse_track").parent \
        / "expert_parse_track_pack"


def _write_answer(project: Path, blob):
    d = _pack_dir(project)
    d.mkdir(parents=True, exist_ok=True)
    (d / "l_doc_expectations.json").write_text(json.dumps(blob))


def _run_track(project: Path):
    env = dict(os.environ)
    env["VIBE_IC_DISABLE_LLM_CONFIRM"] = "1"
    cp = _pr.run(
        [sys.executable, str(_PROGRAMS / "phase1_expert_parse_track.py"),
         str(project)], capture_output=True, text=True, env=env)
    return cp.returncode, cp.stdout, cp.stderr


def _report(project: Path):
    return json.loads(
        _pl.report_path(project, "phase1/expert_parse_track.json").read_text())


# ── the producer: three states, three exit codes ───────────────────────────

def test_an_unanswered_handoff_exits_the_awaiting_code_not_a_failure(tmp_path):
    """THE defect, at the producer. Before this landing: rc 1, and D1 red for
    every program-only run of every design."""
    p = _project(tmp_path)
    rc, out, _ = _run_track(p)
    rep = _report(p)

    # behaviour first, on literals — every line below holds against the pre-fix
    # module and simply is not TRUE there.
    assert rep["ai_subtrack"]["status"] == "HANDOFF_EMITTED"
    assert rc != 1, (
        "the designed first pass of a two-pass protocol still exits the code "
        "reserved for a failed run")
    assert rc != 0, "an unanswered hand-off exited 0 — that reads as credit"
    assert rc != 2, (
        "the wait borrowed VACUOUS_PASS, which means 'nothing applied' — "
        "#599 measured that here the input WAS applicable")
    # only now the vocabulary itself
    assert rc == T.AWAITING_EXIT_CODE
    assert T.AWAITING_EXIT_CODE not in (0, 1, 2, 3)


def test_the_wait_says_what_it_is_waiting_for(tmp_path):
    """A state with no named action is the same silence as a bare FAIL. The
    report must carry the subagent, the pack and the move that ends it."""
    p = _project(tmp_path)
    _rc, out, _ = _run_track(p)
    rep = _report(p)

    aw = rep["awaiting"]
    assert aw, "the track is waiting and the report does not say for what"
    assert aw["ai_subtrack_status"] == "HANDOFF_EMITTED"
    assert aw["credited"] is False
    assert "vibe-ic:ic-expert-agent" in aw["action"]
    assert "ic_expert_agent_handoff.json" in aw["action"]
    # and it reaches a human, not only the file
    assert any(line.lstrip().startswith("awaiting:")
               for line in out.splitlines()), out


def test_waiting_is_still_not_credit(tmp_path):
    """The half #1973 was right about. Passing D1's clause must not turn into
    the expert track being reported as having run."""
    p = _project(tmp_path)
    _rc, out, _ = _run_track(p)
    rep = _report(p)

    assert rep["verdict"] == "INCOMPLETE"
    assert rep["execution"]["complete"] is False
    assert rep["execution"]["disposition"] == T.DISPOSITION_AWAITING
    assert rep["denominator"]["total"] == 0
    assert rep["ai_convergence"]["consumed"] == 0
    assert "INCOMPLETE:" in out
    assert "VACUOUS_PASS" not in out
    # the runner's own published summary, which is where #1973's lie lived
    assert R._expert_track_summary(p).startswith("INCOMPLETE — ")


def test_an_unreadable_answer_is_a_defect_and_still_exits_one(tmp_path):
    """The direction that must NOT move. The agent answered; the answer could
    not be read. Reading that as a wait would retire the refusal that
    `test_expert_track_schema_mismatch_is_not_a_pass` exists to keep."""
    p = _project(tmp_path)
    _write_answer(p, {"verdict": "gaps", "complete": False})
    rc, _out, _ = _run_track(p)
    rep = _report(p)

    assert rc == 1, "a refused answer inherited the wait"
    assert rc != T.AWAITING_EXIT_CODE
    assert rep["execution"]["disposition"] == T.DISPOSITION_DEFECT
    assert rep["awaiting"] is None
    assert rep["ai_subtrack"]["status"] == T.AI_SCHEMA_MISMATCH


def test_an_empty_answer_is_a_defect_not_a_wait(tmp_path):
    """CONSUMED_EMPTY is deliberately OUTSIDE the allow-list. HANDOFF_EMITTED
    is an ORDERING state — pass two has not happened, and re-running leaves it.
    CONSUMED_EMPTY is a MEASUREMENT state — pass two happened and decided
    nothing, which is the zero denominator this repo's own
    `gate_zero_denominator_refuses_check` exists to refuse. Re-running does not
    leave it."""
    p = _project(tmp_path)
    _write_answer(p, {"expectations": []})
    rc, _out, _ = _run_track(p)
    rep = _report(p)

    assert rep["ai_subtrack"]["status"] == T.AI_CONSUMED_EMPTY
    assert rc == 1
    assert rep["execution"]["disposition"] == T.DISPOSITION_DEFECT
    assert rep["awaiting"] is None


def test_the_awaiting_set_is_an_allow_list(tmp_path):
    """A producer that grows a new failure state must inherit `1`, never the
    wait. Asserted on the SET, because that is the property — enumerating
    today's members would pass for a set that had been opened up."""
    assert T.AI_AWAITING_STATES == frozenset({T.AI_HANDOFF_EMITTED})
    for s in (T.AI_CONSUMED, T.AI_CONSUMED_EMPTY, T.AI_SCHEMA_MISMATCH,
              T.AI_ERROR, "A_STATE_NOBODY_HAS_WRITTEN_YET"):
        assert s not in T.AI_AWAITING_STATES


# ── the consumers: the flow, and the runner ────────────────────────────────

def test_the_flow_reads_the_wait_as_incomplete_never_as_a_bare_pass():
    """D1's clause is `program_exit_zero`. rc 4 must satisfy it AND raise the
    #599 INCOMPLETE tier, so the roll-up says 'someone must return' rather than
    counting an unaudited expert half as an executed pass."""
    assert F._AWAITING_EXIT_CODE == T.AWAITING_EXIT_CODE, (
        "the flow and the producer disagree about the code")
    assert F._AWAITING_EXIT_CODE not in (0, 1, 2, F._WAIVER_EXIT_CODE)


def test_a_bare_rc_four_with_no_sentinel_is_still_a_failure(tmp_path):
    """BOTH the code and the disclosure, the `_WAIVER_EXIT_CODE` shape. An
    unrelated program's exit 4 must not inherit the tier — otherwise the third
    state becomes a hole any gate can fall through."""
    prog = tmp_path / "silent_four.py"
    prog.write_text("import sys\nprint('nothing to disclose')\n"
                    "sys.exit(4)\n")
    outcome = F._check_program_exit_zero(tmp_path, str(prog))
    passed = outcome[0] if isinstance(outcome, tuple) else outcome.passed
    assert passed is False, (
        "an rc 4 that disclosed nothing was promoted to a stated wait")

    prog2 = tmp_path / "disclosing_four.py"
    prog2.write_text("import sys\nprint('INCOMPLETE: pass two is pending')\n"
                     "sys.exit(4)\n")
    outcome2 = F._check_program_exit_zero(tmp_path, str(prog2))
    passed2, out2 = (outcome2[0], outcome2[1]) if isinstance(outcome2, tuple) \
        else (outcome2.passed, outcome2.reason)
    assert passed2 is True
    assert F._stdout_signals_token(out2, F._INCOMPLETE_STDOUT_TOKEN), (
        "the clause passed and the INCOMPLETE tier was not raised — that is a "
        "bare PASS for an unaudited half")


def test_the_runner_accepts_the_wait_without_crediting_it(tmp_path):
    """The runner's own contract. rc 4 is 'the track ran to a state it
    defines'; whether it is CREDITED is still decided from the REPORT."""
    assert R._EXPERT_TRACK_AWAITING_RC == T.AWAITING_EXIT_CODE, (
        "the runner and the producer disagree about the code")
    disp, _ = R._expert_track_disposition(
        {"ai_subtrack": {"status": T.AI_HANDOFF_EMITTED},
         "ai_convergence": {"consumed": 0},
         "denominator": {"ai": 0, "total": 0}})
    assert disp == R._EXPERT_PENDING, "the rc granted credit"


# ── negative controls: the gate must still bite ────────────────────────────

def _stage_phase1(project: Path):
    cp = _pr.run(
        [sys.executable, str(_PROGRAMS / "flow_compliance_check.py"),
         str(project), "--stage-id", "stage_phase1", "--exclude-step", "0.5ic"],
        capture_output=True, text=True, cwd=str(project))
    return cp.returncode, cp.stdout + cp.stderr


def test_a_project_with_no_phase1_input_is_still_blocked(tmp_path):
    """THE reverse control. The repair must not make D1 pass for everyone: a
    tree that produced no Phase-1 document has to stay stopped, and it does —
    the clause that catches it (`phase1_all_l_docs_present_check` and the
    step's own declared outputs) is untouched by the third state."""
    p = tmp_path / "empty"
    p.mkdir()
    rc, out = _stage_phase1(p)
    assert rc != 0, "a project with no Phase-1 input passed D1"
    assert "Overall: PASS" not in out
    assert "Step D1" in out


def test_a_project_whose_expert_answer_is_unreadable_is_still_blocked(tmp_path):
    """The second reverse control, aimed straight at the new state: DEFECT must
    keep failing D1 through the WHOLE clause, not merely in the producer."""
    p = _project(tmp_path, name="refused")
    _run_track(p)                                # writes the hand-off pack
    _write_answer(p, {"verdict": "gaps", "complete": False})
    rc, out = _stage_phase1(p)
    assert rc != 0, "an unreadable expert answer passed D1"
    assert "Overall: PASS" not in out


#: D1's expert clause, spelled exactly as the flow yaml spells it, ALONE.
#: Evaluated on its own rather than through the whole step on purpose:
#: `_evaluate_gate` short-circuits `all_of` at the first failing sub-gate, so on
#: any fixture thin enough to build here `phase1_all_l_docs_present_check` fails
#: first and this clause never runs — a whole-step assertion would then be green
#: on BOTH trees and would prove nothing. This is the clause the flow runs, and
#: it is what changed.
_D1_EXPERT_CLAUSE = {"all_of": [
    {"program_exit_zero": "phase1_expert_parse_track ."}]}


def test_the_flow_clause_passes_the_wait_and_still_calls_it_incomplete(
        tmp_path):
    """THE forward control, on D1's own clause.

    Pristine main: `passed` is False and the reasons carry "program failed" —
    that is Step D1 red for every program-only run of every design. Here:
    `passed` is True AND the #599 INCOMPLETE hint is raised, so the step is
    reported "not audited, and someone must return" and never a bare PASS.

    The same pair is measured end-to-end on a real Phase-1 tree and recorded in
    this file's header: same project, same command, pristine main -> `Step D1
    FAIL / Overall FAIL / rc 1`; with this change -> `Step D1 INCOMPLETE /
    Overall PASS / rc 0 / INCOMPLETE=1`."""
    p = _project(tmp_path, name="waiting")
    passed, reasons = F._evaluate_gate(p, _D1_EXPERT_CLAUSE)

    assert passed is True, (
        "the hand-off's designed first pass still fails D1's clause: "
        + " | ".join(reasons)[:600])
    assert not any(r.startswith("program failed:") for r in reasons), reasons
    assert any(r.startswith(F._INCOMPLETE_HINT_PREFIX) for r in reasons), (
        "the clause passed and raised NO disclosure — an unaudited expert half "
        "counted as an executed pass, which is the other half of the defect: "
        + " | ".join(reasons)[:600])


def test_the_flow_clause_still_fails_an_unreadable_answer(tmp_path):
    """The paired direction, on the same clause. A comparator that simply
    always passed would be as wrong as one that always failed."""
    p = _project(tmp_path, name="refused_clause")
    _run_track(p)                                # writes the hand-off pack
    _write_answer(p, {"verdict": "gaps", "complete": False})
    passed, reasons = F._evaluate_gate(p, _D1_EXPERT_CLAUSE)

    assert passed is False, "a refused expert answer passed D1's clause"
    assert any(r.startswith("program failed:") for r in reasons), reasons
