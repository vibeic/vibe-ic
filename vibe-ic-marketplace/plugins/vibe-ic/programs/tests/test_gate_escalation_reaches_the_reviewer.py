"""A routed ESCALATE that reaches no consumer is a measurement thrown away.

`gate_directed_rtl_repair` marks a gate finding it cannot mechanically repair
as ESCALATE: the gate is confident about the SHAPE, but only a spec can say
whether that shape is a defect here. The runner records the verdict and moves
on. Nothing repairs it — correctly — and nothing else was ever told.

RTLLM clean-room run 2026-09-07, `asyn_fifo`. The record below is verbatim from
that project's `reports/orchestrator/phase2_one_shot.json`:

    defect: counter-decode-lookahead-phase   verdict: FINDING
    router_verdict: ESCALATE                 blocking: false
      wptr <= bin2gray(waddr_bin + wen);
      rptr <= bin2gray(raddr_bin + ren);

The gate was RIGHT: the reference registers the gray code of the CURRENT binary
value, this candidate registered the gray of the LOOKAHEAD, both pointers were
published one cycle early, and it was the run's single official failure. The
blind reviewer, never told, wrote a write-then-read FIFO challenge that never
reaches the full/empty boundary where the phase is observable, and recorded a
semantic PASS on a candidate the Program had already described in writing.

Both directions are pinned here: a routed escalation must become an obligation,
and a project without one must produce the contract it produced before this
existed, byte for byte.
"""
import json
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import benchmark_dispatch as B  # noqa: E402


#: Verbatim from the failing run, trimmed to the fields a consumer reads.
_ASYN_FIFO_REPORT = {
    "project": "asyn_fifo",
    "steps": [
        {"name": "complexity_advisory", "extras": {"advisory_only": True}},
        {"name": "determinism_gates", "extras": {
            "counter_decode_lookahead_advisory": {
                "defect": "counter-decode-lookahead-phase",
                "verdict": "FINDING",
                "files_scanned": 1,
                "blocking": False,
                "gate": "counter_decode_lookahead_phase_check",
                "router_verdict": "ESCALATE",
                "why_advisory_here": (
                    "a lookahead decode is legitimate when the spec asks for "
                    "the level to lead"),
                "findings": [
                    {"signal": "wptr", "counter": "waddr_bin", "via": "inline",
                     "statement": "wptr <= bin2gray(waddr_bin + wen);",
                     "sensitivity": "posedge wclk or negedge wrstn",
                     "file": "asyn_fifo.v"},
                    {"signal": "rptr", "counter": "raddr_bin", "via": "inline",
                     "statement": "rptr <= bin2gray(raddr_bin + ren);",
                     "sensitivity": "posedge rclk or negedge rrstn",
                     "file": "asyn_fifo.v"},
                ],
            }}},
    ],
}


def _project(tmp_path, report):
    """A project directory carrying exactly the runner's own report."""
    out = tmp_path / "proj"
    (out / "reports" / "orchestrator").mkdir(parents=True, exist_ok=True)
    if report is not None:
        (out / "reports" / "orchestrator" / "phase2_one_shot.json").write_text(
            json.dumps(report), encoding="utf-8")
    return out


def test_the_routed_escalation_reaches_the_contract(tmp_path):
    """THE REGRESSION. Both named signals must arrive as one obligation."""
    found = B._program_gate_escalations(_project(tmp_path, _ASYN_FIFO_REPORT))
    assert len(found) == 1, "the routed ESCALATE did not reach any consumer"
    assert found[0]["gate"] == "counter_decode_lookahead_phase_check"
    assert found[0]["defect"] == "counter-decode-lookahead-phase"
    assert found[0]["step"] == "determinism_gates"
    assert [s for s, _ in found[0]["signals"]] == ["rptr", "wptr"]

    row = B._gate_escalation_obligation(found[0])
    assert row["kind"] == "gate_escalation"
    assert row["coverage_tokens"] == ["rptr", "wptr"]
    assert "wptr <= bin2gray(waddr_bin + wen);" in row["evidence"]
    assert "DISCRIMINATE" in row["requirement"].upper() or \
           "DIFFER" in row["requirement"], (
        "the obligation must ask the test to discriminate the finding, not "
        "merely to mention it")


def test_a_project_with_no_escalation_is_unchanged(tmp_path):
    """THE CONTROL that keeps this additive. A candidate the gates had nothing
    to say about must see the contract it saw before this existed — same
    obligations, same hash, same actor string."""
    prompt = "Design a 4-bit counter with synchronous reset."
    candidate = {"rtl_paths": []}
    before = B._program_review_obligation_contract(prompt, candidate)
    quiet = _project(tmp_path, {"project": "p", "steps": [
        {"name": "determinism_gates", "extras": {"advisory_only": True}}]})
    after = B._program_review_obligation_contract(prompt, candidate, quiet)
    assert after == before, (
        "a project with no routed escalation must produce the identical "
        "contract; this change is additive or it is a regression")
    assert after["actor"] == "programs/spec_coverage_check.py"


def test_the_escalation_is_appended_not_substituted(tmp_path):
    """The structural minimum still ships. Two readers, two questions."""
    prompt = "Design a 4-bit counter with synchronous reset."
    candidate = {"rtl_paths": []}
    base = B._program_review_obligation_contract(prompt, candidate)
    loud = B._program_review_obligation_contract(
        prompt, candidate, _project(tmp_path, _ASYN_FIFO_REPORT))
    assert loud["obligation_count"] == base["obligation_count"] + 1
    assert loud["obligations"][:len(base["obligations"])] == base["obligations"]
    assert loud["obligations"][-1]["kind"] == "gate_escalation"
    assert loud["sha256"] != base["sha256"], (
        "the contract is hash-bound; a new obligation must change the hash or "
        "a reviewer could satisfy the old one")
    assert "routed PROGRAM gate escalations" in loud["actor"]


def test_a_blocking_finding_is_not_routed_again(tmp_path):
    """A blocking gate already stopped the step and was already acted on.
    Re-routing it would turn one failure into two."""
    report = json.loads(json.dumps(_ASYN_FIFO_REPORT))
    adv = report["steps"][1]["extras"]["counter_decode_lookahead_advisory"]
    adv["blocking"] = True
    adv.pop("router_verdict")
    assert B._program_gate_escalations(_project(tmp_path, report)) == []


def test_a_bare_advisory_flag_is_not_a_finding(tmp_path):
    """`advisory_only: true` is a bool, not a record. A reader that assumes a
    dict crashes the whole contract on a step that says nothing."""
    report = {"project": "p", "steps": [
        {"name": "complexity_advisory", "extras": {"advisory_only": True}},
        {"name": "s", "extras": {"x_advisory": {"gate": "g", "findings": []}}},
        {"name": "t", "extras": {"y_advisory": {"findings": [{"signal": "a"}]}}},
    ]}
    assert B._program_gate_escalations(_project(tmp_path, report)) == []


def test_missing_or_unreadable_evidence_is_not_a_finding(tmp_path):
    """An absent record is not a finding. Inventing an obligation from one
    would block a candidate on nothing."""
    assert B._program_gate_escalations(None) == []
    assert B._program_gate_escalations(_project(tmp_path, None)) == []
    broken = _project(tmp_path, None)
    (broken / "reports" / "orchestrator" / "phase2_one_shot.json").write_text(
        "{not json", encoding="utf-8")
    assert B._program_gate_escalations(broken) == []
    listy = _project(tmp_path, None)
    (listy / "reports" / "orchestrator" / "phase2_one_shot.json").write_text(
        "[]", encoding="utf-8")
    assert B._program_gate_escalations(listy) == []


def test_the_derivation_is_deterministic(tmp_path):
    """The contract is recomputed independently at three sites and compared.
    An unstable order makes every task read as stale."""
    shuffled = json.loads(json.dumps(_ASYN_FIFO_REPORT))
    f = shuffled["steps"][1]["extras"]["counter_decode_lookahead_advisory"]
    f["findings"].reverse()
    a = B._program_gate_escalations(_project(tmp_path, _ASYN_FIFO_REPORT))
    b = B._program_gate_escalations(_project(tmp_path / "b", shuffled))
    assert a == b


def test_every_derivation_site_passes_the_project():
    """THE WIRING. Three sites derive this contract and compare the results
    against one another; a site left on the old two-argument call makes every
    task read as `stale, or differs from the current prompt and candidate` and
    blocks the whole run."""
    source = (_PROGRAMS / "benchmark_dispatch.py").read_text(encoding="utf-8")
    calls = source.count("_program_review_obligation_contract(")
    # one definition + three derivation sites
    assert calls == 4, f"expected 4 references, found {calls}"
    assert source.count("_task_project(task)") == 2, (
        "the refresh and validate sites must read the project the same way")
    assert "prompt.read_text(errors=\"replace\"), candidate, project)" in source


def test_no_oracle_path_is_read():
    """§4.05. The reader opens exactly one file, inside the project the
    reviewer is already reviewing, written by a gate from the candidate RTL and
    the prompt. No golden, harness, scorer or expected output is named."""
    import inspect
    src = inspect.getsource(B._program_gate_escalations)
    body = src.split('"""')[-1]      # the code, not the docstring
    for forbidden in ("golden", "reference", "expected", "scorer", "harness",
                      "oracle", "output.context", "testbench"):
        assert forbidden not in body.lower(), (
            f"the escalation reader must not reach for {forbidden!r}")
    assert body.count("read_text") == 1
    assert "phase2_one_shot.json" in body


# --------------------------------------------------------------------------
# Reaching the reviewer is only half of it. An advisory that lands in a second
# reader who may also ignore it has MOVED, not landed: the failing run had the
# finding in writing, in the project, and issued a semantic PASS anyway. So a
# PASS must DISPOSE of each routed escalation — and the disposition must be one
# a correct candidate can always give, or the obligation becomes an unclearable
# gate.
# --------------------------------------------------------------------------

_PROMPT = ("Implement an asynchronous FIFO. The full and empty flags must be "
           "asserted in the same cycle as the pointer they describe.")


def _task_with_escalation(tmp_path):
    escalations = B._program_gate_escalations(
        _project(tmp_path, _ASYN_FIFO_REPORT))
    row = B._gate_escalation_obligation(escalations[0])
    row["id"] = B._review_obligation_id(row)
    return {"program_review_obligations": {"obligations": [row]}}, row["id"]


def test_an_undisposed_escalation_blocks_a_semantic_pass(tmp_path):
    """THE REGRESSION, enforcement half. A PASS that says nothing about the
    gate's finding is exactly what the failing run produced."""
    task, oid = _task_with_escalation(tmp_path)
    reasons = B._gate_escalation_disposition_reasons(task, {}, _PROMPT)
    assert len(reasons) == 1
    assert oid in reasons[0]


def test_a_discriminating_test_disposes_of_it(tmp_path):
    """The reviewer says what the test drives. Always available."""
    task, oid = _task_with_escalation(tmp_path)
    review = {"gate_escalation_dispositions": [{
        "obligation_id": oid,
        "disposition": "DISCRIMINATED",
        "how": ("writes until wfull asserts, then checks the flag rises on the "
                "same edge as the final write rather than one cycle earlier"),
    }]}
    assert B._gate_escalation_disposition_reasons(task, review, _PROMPT) == []


def test_a_disposition_without_substance_is_refused(tmp_path):
    """'covered' is not a disposition. The reviewer must say what differs."""
    task, oid = _task_with_escalation(tmp_path)
    review = {"gate_escalation_dispositions": [{
        "obligation_id": oid, "disposition": "DISCRIMINATED", "how": "covered"}]}
    assert B._gate_escalation_disposition_reasons(task, review, _PROMPT)


def test_the_prompt_may_sanction_the_shape(tmp_path):
    """THE ESCAPE HATCH THAT KEEPS THIS HONEST. A lookahead decode is legal
    when a spec asks the level to lead, and the gate says so itself. Quoting
    the prompt line must clear the obligation."""
    task, oid = _task_with_escalation(tmp_path)
    review = {"gate_escalation_dispositions": [{
        "obligation_id": oid,
        "disposition": "SANCTIONED_BY_PROMPT",
        "prompt_evidence": [{
            "excerpt": "asserted in the same cycle as the pointer they describe",
            "supports": "the prompt fixes the flag phase explicitly",
        }],
    }]}
    assert B._gate_escalation_disposition_reasons(task, review, _PROMPT) == []


def test_a_sanction_the_prompt_does_not_contain_is_refused(tmp_path):
    """The excerpt is checked against the FROZEN prompt by the same verifier
    used for every other prompt claim; an invented line clears nothing."""
    task, oid = _task_with_escalation(tmp_path)
    review = {"gate_escalation_dispositions": [{
        "obligation_id": oid,
        "disposition": "SANCTIONED_BY_PROMPT",
        "prompt_evidence": [{
            "excerpt": "the flags shall lead the pointer by one clock cycle",
            "supports": "the prompt asks for a leading level",
        }],
    }]}
    assert B._gate_escalation_disposition_reasons(task, review, _PROMPT)


def test_an_unknown_disposition_is_refused(tmp_path):
    task, oid = _task_with_escalation(tmp_path)
    for bad in ("ACKNOWLEDGED", "WAIVED", "", "discriminated"):
        review = {"gate_escalation_dispositions": [
            {"obligation_id": oid, "disposition": bad, "how": "x" * 40}]}
        assert B._gate_escalation_disposition_reasons(task, review, _PROMPT), bad


def test_a_review_with_no_escalation_is_never_asked_for_one():
    """THE CONTROL. Every review that passes today must still pass. A task
    whose contract carries no gate_escalation obligation is untouched, whatever
    the review says or omits."""
    for task in ({}, {"program_review_obligations": None},
                 {"program_review_obligations": {"obligations": []}},
                 {"program_review_obligations": {"obligations": [
                     {"kind": "reset", "id": "abc"}]}}):
        assert B._gate_escalation_disposition_reasons(task, {}, _PROMPT) == []


def test_the_disposition_check_runs_only_on_a_semantic_pass():
    """THE WIRING, and its scope. A FAIL already rejects the candidate; asking
    it for dispositions too would add noise to a verdict that is already
    correct. The reviewer is also told the field exists — an envelope that
    never mentions it turns a blocking rule into a trap."""
    source = (_PROGRAMS / "benchmark_dispatch.py").read_text(encoding="utf-8")
    assert ('    if semantic_verdict == "PASS":\n' in source
            and "_gate_escalation_disposition_reasons(\n" in source), (
        "the disposition check is not wired into the PASS path")
    assert '"gate_escalation_dispositions": {' in source, (
        "the required_envelope handed to the reviewer must document the field "
        "a semantic PASS is now rejected for omitting")
