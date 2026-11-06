#!/usr/bin/env python3
"""test_issue2216_required_gate_eligibility.py

#2216: collecting RTL, and an independent semantic PASS on it, were being
conflated with "every required Program gate passed".

MEASURED before the fix, with the issue's own probe against the REAL collector
(`benchmark_io_adapter.collect`) on live main: a project whose owning gate
`rtl_gen` is PASS and whose in-scope downstream gate `rtl_validate` is FAIL
collects `ok=True`. The collector is RIGHT to do that — a failed candidate must
stay reviewable and repairable, and #2216 says so explicitly. The defect is one
step further on: nothing between that collection and the printed
`ACCEPTED by PROGRAM gates` ever asks whether a REQUIRED IN-SCOPE gate failed.

ONE ROOT CAUSE. The accept path asks four artefact questions -- runner-owned
project, reviewed-hash identity, Phase-1 provenance, and the RTL-OWNING gate --
then makes a claim about EVERY gate. `_required_gate_ledger` is the missing
question.

SCOPE IS READ, NOT INVENTED. `step_preflight.RUNNER_PLANS` is the runner's own
(site, flow-step-span) table -- the same one `--exit-step` prunes against -- and
the run declares its own `exit`. With exit 2: `rtl_gen`(1) and `rtl_validate`
(2,3) are in scope; `sim`(4), `yosys_synth`(9) and `dft_lec_chain`(11-13) are
not.

WHY THE BLOCKING PREDICATE IS DELIBERATELY NARROW. Measured on the published
VerilogEval-Human corpus, 61 accepted rows carry 163 FAIL steps
(`lec_equivalence` 61, `final_audit` 47, `sdc_gen` 43, `yosys_synth` 12) and
NOT ONE is an in-scope site gate. A blanket "any FAIL blocks" rule would refuse
all 61 -- that is the all-history-green rule #2216 forbids, and those
out-of-exit failures are #2208's producer/consumer defect. They stay visible in
the ledger and block nothing.

THREE-VALUED ON PURPOSE. `rtl_validate` is BLOCKED on 44 of those 61 rows and
absent on the other 17: a required in-scope gate that never reported. Calling
that ELIGIBLE is the defect; calling it INELIGIBLE would refuse 61 published
candidates for a state nobody measured. It is NOT_MEASURED, and the accepting
message now says so instead of claiming the gates passed.

Every fixture is synthesised here. No design, PDK, vendor or IP identifier
appears in this file, and no oracle, harness or golden is read.

Run: python3 -m pytest programs/tests/test_issue2216_required_gate_eligibility.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from dataclasses import asdict

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import benchmark_dispatch as BD                 # noqa: E402
import flow_phase_attribution as FPA            # noqa: E402
from test_issue1903_shape_c_accepted_export_control import _fixture
from _benchmark_io_fixture import issue_io_fixture


def _solve(exit_step="2", ran=None, not_attempted=None, **extra):
    row = {"id": "synthetic-task", "exit": exit_step,
           "phases": {"phase3_verifying": {
               "ran": dict(ran or {}),
               "not_attempted": dict(not_attempted or {})}}}
    row.update(extra)
    return row


@pytest.mark.parametrize("exit_step,endpoint", [("2", "rtl_validate"), ("4", "sim"),
                                               ("rtl_validate", "rtl_validate")])
def test_unexecuted_requested_endpoint_stays_unmeasured(exit_step, endpoint):
    ran = {"rtl_gen": "PASS", "rtl_validate": "PASS"}
    ran.pop(endpoint, None)
    ledger = BD._required_gate_ledger(_solve(exit_step, ran=ran,
        not_attempted={endpoint: "NOT_APPLICABLE"}))
    assert ledger["eligibility"] == "NOT_MEASURED", ledger
    assert ledger["unmeasured_required"] == [endpoint]
    assert ledger["failed_required"] == []


def test_upstream_and_outside_endpoint_inapplicability_remains_visible():
    ledger = BD._required_gate_ledger(_solve(ran={"rtl_validate": "PASS"},
        not_attempted={"rtl_gen": "NOT_APPLICABLE", "sim": "NOT_APPLICABLE"}))
    assert ledger["eligibility"] == "ELIGIBLE", ledger
    assert ledger["in_scope"]["rtl_gen"] == "NOT_APPLICABLE"
    assert ledger["out_of_scope"]["sim"] == "NOT_APPLICABLE"


@pytest.mark.parametrize("exit_step", ["1", "rtl_gen"])
def test_supplied_source_author_endpoint_need_not_regenerate(exit_step):
    ledger = BD._required_gate_ledger(_solve(exit_step, ran={"reused_ip_consume": "PASS"},
        not_attempted={"rtl_gen": "NOT_APPLICABLE"}))
    assert ledger["eligibility"] == "ELIGIBLE", ledger
    assert ledger["in_scope"]["rtl_gen"] == "NOT_APPLICABLE"
    assert ledger["unmeasured_required"] == []


@pytest.mark.parametrize("status,expected", [("PASS", "ELIGIBLE"),
    ("FAIL", "INELIGIBLE"), ("NOT_MEASURED", "NOT_MEASURED")])
@pytest.mark.parametrize("site,exit_step", [("rtl_validate", "2"), ("sim", "4")])
def test_actual_producer_ownership_scopes_results_without_display_aliases(tmp_path, status, expected, site, exit_step):
    import design_one_shot_runner as runner
    import flow_phase_attribution as attribution
    row = runner.StepResult("arbitrary_consumer_name", status, reason_class="tool_absent")
    (tmp_path / "phase2/stage1/rtl").mkdir(parents=True)
    (tmp_path / "phase2/stage1/rtl/cell.v").write_text("module cell; endmodule\n")
    bound = runner._required_site_row(tmp_path, site, row)
    report = {"steps": [asdict(bound)], "required_site_rtl_sha256": bound.extras["required_site"]["rtl_sha256"]}
    phases = attribution.phase3_verifying(report, None)
    phases["ran"].update(rtl_gen="PASS", rtl_validate="PASS")
    result = {"exit": exit_step, "phases": {"phase3_verifying": phases}}
    ledger = BD._required_gate_ledger(result)
    assert ledger["eligibility"] == expected, ledger
    assert ledger["in_scope"][site] == status
    assert ledger["unscoped"]["arbitrary_consumer_name"] == status


def test_absent_ownership_does_not_invent_display_aliases():
    row = _solve(exit_step="4", ran={"rtl_gen": "PASS", "rtl_lint_tool": "PASS",
                                     "reference_tb": "PASS"})
    ledger = BD._required_gate_ledger(row)
    assert ledger["eligibility"] == "NOT_MEASURED"
    assert ledger["unmeasured_required"] == ["rtl_validate", "sim"]


def test_recorded_failure_cannot_be_laundered_by_pass_in_ownership_copy():
    row = _solve(ran={"rtl_gen": "PASS", "named_check": "FAIL"})
    row["phases"]["phase3_verifying"]["required_site_results"] = [{
        "result_name": "named_check", "status": "PASS", "ownership": {
            "runner": "design_one_shot_runner", "site": "rtl_validate", "flow_steps": ["2", "3"], "rtl_sha256": "a" * 64}}]
    row["phases"]["phase3_verifying"]["required_site_rtl_sha256"] = "a" * 64
    ledger = BD._required_gate_ledger(row)
    assert ledger["eligibility"] == "INELIGIBLE"
    assert ledger["failed_required"] == ["rtl_validate"]


@pytest.mark.parametrize("tamper", ["runner", "site", "flow_steps", "status", "name", "list",
                                   "site_list", "name_list", "status_list"])
def test_malformed_ownership_never_hides_an_existing_in_scope_failure(tamper):
    row = _solve(ran={"rtl_gen": "PASS", "rtl_validate": "FAIL", "named_check": "PASS"})
    proof = {"result_name": "named_check", "status": "PASS", "ownership": {
        "runner": "design_one_shot_runner", "site": "rtl_validate", "flow_steps": ["2", "3"], "rtl_sha256": "a" * 64}}
    row["phases"]["phase3_verifying"]["required_site_rtl_sha256"] = "a" * 64
    if tamper in {"runner", "site", "flow_steps"}:
        proof["ownership"][tamper] = "wrong"
    elif tamper == "status": proof["status"] = "UNKNOWN"
    elif tamper == "name": proof["result_name"] = "absent"
    elif tamper == "site_list": proof["ownership"]["site"] = []
    elif tamper == "name_list": proof["result_name"] = []
    elif tamper == "status_list": proof["status"] = []
    row["phases"]["phase3_verifying"]["required_site_results"] = {} if tamper == "list" else [proof]
    ledger = BD._required_gate_ledger(row)
    assert ledger["eligibility"] == "INELIGIBLE", ledger
    assert ledger["failed_required"] == ["rtl_validate"]
    assert "invalid required-site evidence" in ledger["unmeasured_required"]


def test_out_of_window_owned_failure_is_visible_and_retry_failure_is_not_erased(tmp_path):
    import design_one_shot_runner as runner
    import flow_phase_attribution as attribution
    (tmp_path / "phase2/stage1/rtl").mkdir(parents=True)
    (tmp_path / "phase2/stage1/rtl/cell.v").write_text("module cell; endmodule\n")
    rows = [asdict(runner._required_site_row(tmp_path, "sim", runner.StepResult("check", status)))
            for status in ["FAIL", "PASS"]]
    phases = attribution.phase3_verifying({"steps": rows,
        "required_site_rtl_sha256": rows[-1]["extras"]["required_site"]["rtl_sha256"]}, None)
    phases["ran"].update(rtl_gen="PASS", rtl_validate="PASS")
    result = {"exit": "2", "phases": {"phase3_verifying": phases}}
    short = BD._required_gate_ledger(result)
    assert short["eligibility"] == "ELIGIBLE", short
    assert short["out_of_scope"]["sim"] == "FAIL"
    result["exit"] = "4"
    full = BD._required_gate_ledger(result)
    assert full["eligibility"] == "INELIGIBLE", full
    assert full["failed_required"] == ["sim"]


def test_repaired_candidate_does_not_inherit_failed_gate_on_different_bytes(tmp_path):
    import design_one_shot_runner as runner
    import flow_phase_attribution as attribution
    rtl = tmp_path / "phase2/stage1/rtl/cell.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module cell; wire x=1'b0; endmodule\n")
    old = asdict(runner._required_site_row(tmp_path, "sim", runner.StepResult("check", "FAIL")))
    rtl.write_text("module cell; wire x=1'b1; endmodule\n")
    new = asdict(runner._required_site_row(tmp_path, "sim", runner.StepResult("check", "PASS")))
    phases = attribution.phase3_verifying({"steps": [old, new],
        "required_site_rtl_sha256": new["extras"]["required_site"]["rtl_sha256"]}, None)
    phases["ran"].update(rtl_gen="PASS", rtl_validate="PASS")
    ledger = BD._required_gate_ledger({"exit": "4", "phases": {"phase3_verifying": phases}})
    assert ledger["eligibility"] == "ELIGIBLE", ledger
    assert phases["superseded_required_site_results"] == [{"result_name": "check", "status": "FAIL", "ownership": old["extras"]["required_site"]}]


@pytest.mark.parametrize("prior", ["unrelated", "same_name", "malformed"])
def test_superseded_record_never_unbinds_current_raw_failure(tmp_path, prior):
    import design_one_shot_runner as runner
    import flow_phase_attribution as attribution
    rtl = tmp_path / "phase2/stage1/rtl/cell.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module cell; wire x=1'b0; endmodule\n")
    name = "check" if prior == "same_name" else "unrelated_check"
    old = asdict(runner._required_site_row(tmp_path, "sim", runner.StepResult(name, "FAIL")))
    if prior == "malformed":
        old["extras"]["required_site"]["runner"] = "unknown_runner"
    rtl.write_text("module cell; wire x=1'b1; endmodule\n")
    good = asdict(runner._required_site_row(tmp_path, "rtl_validate", runner.StepResult("check", "PASS")))
    # Legacy/unannotated observations still occur at existing redispatch sites.
    # Their current-name FAIL must not disappear behind unrelated old metadata.
    failed = asdict(runner.StepResult("check", "FAIL"))
    phases = attribution.phase3_verifying({"steps": [old, good, failed],
        "required_site_rtl_sha256": good["extras"]["required_site"]["rtl_sha256"]}, None)
    phases["ran"]["rtl_gen"] = "PASS"
    assert phases["ran"]["check"] == "FAIL"
    ledger = BD._required_gate_ledger({"exit": "2", "phases": {"phase3_verifying": phases}})
    assert ledger["eligibility"] == "INELIGIBLE", ledger
    assert ledger["failed_required"] == ["rtl_validate"]


@pytest.mark.parametrize("tamper", ["runner", "site", "flow_steps", "status", "rtl", "ownership", "list"])
def test_invalid_superseded_observation_cannot_qualify_current_pass(tmp_path, tamper):
    import design_one_shot_runner as runner
    import flow_phase_attribution as attribution
    rtl = tmp_path / "phase2/stage1/rtl/cell.v"
    rtl.parent.mkdir(parents=True)
    rtl.write_text("module cell; wire x=1'b0; endmodule\n")
    old = asdict(runner._required_site_row(tmp_path, "sim", runner.StepResult("old_check", "PASS")))
    rtl.write_text("module cell; wire x=1'b1; endmodule\n")
    good = asdict(runner._required_site_row(tmp_path, "rtl_validate", runner.StepResult("check", "PASS")))
    if tamper in {"runner", "site", "flow_steps"}:
        old["extras"]["required_site"][tamper] = "wrong"
    elif tamper == "status":
        old["status"] = "UNKNOWN"
    elif tamper == "rtl":
        old["extras"]["required_site"]["rtl_sha256"] = "not-a-digest"
    elif tamper == "ownership":
        old["extras"]["required_site"] = []
    phases = attribution.phase3_verifying({"steps": [old, good],
        "required_site_rtl_sha256": good["extras"]["required_site"]["rtl_sha256"]}, None)
    if tamper == "list":
        phases["superseded_required_site_results"] = {}
    phases["ran"]["rtl_gen"] = "PASS"
    ledger = BD._required_gate_ledger({"exit": "2", "phases": {"phase3_verifying": phases}})
    assert ledger["eligibility"] == "NOT_MEASURED", ledger
    assert "invalid required-site evidence" in ledger["unmeasured_required"]


# ── the scope oracle is the runner's own, not one this fix invented ────────



# ── 驗收 1: a required in-scope FAIL cannot be discharged by semantic PASS ──

def test_a_required_in_scope_failure_makes_the_candidate_ineligible():
    """The exact shape the issue's probe produces: owner PASS, in-scope
    downstream FAIL."""
    ledger = BD._required_gate_ledger(_solve(
        ran={"rtl_gen": "PASS", "rtl_validate": "FAIL"}))
    assert ledger["eligibility"] == "INELIGIBLE"
    assert ledger["failed_required"] == ["rtl_validate"]
    assert "INELIGIBLE" in BD._gate_status_note(ledger)
    assert "rtl_validate" in BD._gate_status_note(ledger)


@pytest.mark.parametrize("exit_step", ["2", "rtl_validate"])
def test_the_export_door_refuses_the_same_candidate(tmp_path, exit_step):
    """One claim, TWO doors -- `--resume` prints it and the export re-asserts
    it. A fix on one door leaves the other saying the old thing."""
    reasons = BD._shape_c_task_binding_reasons(
        {"id": "x"}, tmp_path,
        _solve(exit_step=exit_step,
               ran={"rtl_gen": "PASS", "rtl_validate": "FAIL"}))
    assert any("required in-scope PROGRAM gate rtl_validate" in r
               for r in reasons), reasons


@pytest.mark.parametrize("status", ["PASS", "FAIL", "BLOCKED", None])
def test_named_exit_and_numeric_exit_have_the_same_gate_scope(status):
    """Both exit forms select the same real runner site, including its span.

    Changing only the CLI spelling must not hide failures or measured holes.
    An out-of-scope failure remains disclosed without blocking either form.
    """
    ran = {"rtl_gen": "PASS", "sim": "FAIL"}
    if status is not None:
        ran["rtl_validate"] = status
    numeric = BD._required_gate_ledger(_solve(exit_step="2", ran=ran))
    named = BD._required_gate_ledger(_solve(exit_step="rtl_validate", ran=ran))
    numeric.pop("declared_exit")
    named.pop("declared_exit")
    assert named == numeric


# ── 驗收: out-of-exit failures stay VISIBLE and block NOTHING (#2208) ──────

@pytest.mark.parametrize("gate", ["yosys_synth", "sim", "dft_lec_chain"])
def test_an_out_of_exit_failure_is_recorded_and_never_blocks(gate):
    """These are #2208's incorrectly scheduled post-exit consumers. Blocking on
    them would refuse 61 published candidates; hiding them would lose the
    finding. They are recorded, and they do not hold the deliverable."""
    ledger = BD._required_gate_ledger(_solve(
        ran={"rtl_gen": "PASS", "rtl_validate": "PASS", gate: "FAIL"}))
    assert ledger["out_of_scope"].get(gate) == "FAIL"
    assert ledger["failed_required"] == []
    assert ledger["eligibility"] == "ELIGIBLE"


def test_an_unplaceable_gate_is_recorded_and_never_blocks():
    """`sdc_gen` / `final_audit` are not sites in the runner's plan, so this
    ledger cannot place them. Guessing a step id for them would be inventing
    the scope oracle; they are disclosed under `unscoped`."""
    ledger = BD._required_gate_ledger(_solve(
        ran={"rtl_gen": "PASS", "rtl_validate": "PASS",
             "sdc_gen": "FAIL", "final_audit": "FAIL"}))
    assert ledger["unscoped"] == {"final_audit": "FAIL", "sdc_gen": "FAIL"}
    assert ledger["failed_required"] == []


# ── 驗收: a gate that never reported is NOT_MEASURED, never a pass ─────────

@pytest.mark.parametrize("status", ["BLOCKED", "INCOMPLETE", ""])
def test_a_required_gate_that_never_reported_is_not_measured(status):
    ledger = BD._required_gate_ledger(_solve(
        ran={"rtl_gen": "PASS"}, not_attempted={"rtl_validate": status}))
    assert ledger["eligibility"] == BD._NOT_MEASURED
    assert ledger["unmeasured_required"] == ["rtl_validate"]
    note = BD._gate_status_note(ledger)
    assert "NOT_MEASURED" in note and "rtl_validate" in note
    # and it is NEVER rendered as an eligible pass
    assert "ELIGIBLE" not in note.replace("NOT_MEASURED", "")


def test_an_absent_required_gate_is_a_hole_not_a_pass():
    """Absence is not zero. The gate is in scope and simply is not there."""
    ledger = BD._required_gate_ledger(_solve(ran={"rtl_gen": "PASS"}))
    assert ledger["in_scope"]["rtl_validate"] == "(absent)"
    assert ledger["eligibility"] == BD._NOT_MEASURED


# ── 驗收: legitimate skips accept; supplied-RTL re-entry stays supported ───

def test_supplied_rtl_re_entry_with_skipped_by_entry_still_accepts():
    """A supplied-RTL re-entry does not RUN the upstream owner. That is an
    honest skip, and it must not read as a failure."""
    ledger = BD._required_gate_ledger(_solve(
        ran={"rtl_validate": "PASS"},
        # R-0915-85 — `SKIPPED-BY-ENTRY` is `NOT_APPLICABLE`, declared by
        # the run's own `--entry-step`; `flow_phase_attribution` books it
        # under `not_attempted` exactly as before.
        not_attempted={"rtl_gen": "NOT_APPLICABLE"}))
    assert ledger["failed_required"] == []
    assert ledger["eligibility"] == "ELIGIBLE"


@pytest.mark.parametrize("status", ["SKIP", "WAIVED", "ADVISORY", "PASS"])
def test_documented_nonblocking_statuses_accept(status):
    ledger = BD._required_gate_ledger(_solve(
        ran={"rtl_gen": "PASS", "rtl_validate": status}))
    assert ledger["eligibility"] == "ELIGIBLE"
    assert ledger["failed_required"] == []


# ── the ledger REFUSES rather than guesses when it cannot scope ────────────

def test_an_unorderable_exit_scopes_nothing_and_says_so():
    ledger = BD._required_gate_ledger(_solve(
        exit_step="not_a_canonical_step", ran={"rtl_gen": "PASS", "rtl_validate": "FAIL"}))
    assert ledger["in_scope"] == {}
    assert ledger["failed_required"] == []
    assert ledger["eligibility"] == BD._NOT_MEASURED
    assert "not an orderable flow step" in ledger["why"]

    # Fractional IC delivery is a valid boundary in the shared canonical order.
    known = BD._required_gate_ledger(_solve(
        exit_step="37.5ic", ran={"rtl_gen": "PASS", "rtl_validate": "FAIL"}))
    assert known["in_scope"]["rtl_validate"] == "FAIL"


def test_a_missing_gate_record_is_not_measured_not_eligible():
    for row in ({}, {"exit": "2"}, {"exit": "2", "phases": {}}, None, "x"):
        ledger = BD._required_gate_ledger(row)
        assert ledger["eligibility"] == BD._NOT_MEASURED
        assert ledger["failed_required"] == []


# ── the anti-blanket control: the published corpus must still accept ───────

def test_the_published_corpus_shape_is_not_refused_by_this_rule():
    """THE CONTROL, and the reason the blocking predicate is three statuses
    wide and not "any FAIL". This is the exact gate shape measured on the 61
    accepted VerilogEval-Human rows: owner PASS, `rtl_validate` BLOCKED, and
    out-of-exit failures in synth/sdc/lec/audit. It must NOT become
    INELIGIBLE -- and it must not read as ELIGIBLE either."""
    ledger = BD._required_gate_ledger(_solve(
        ran={"rtl_gen": "PASS", "yosys_synth": "FAIL", "sdc_gen": "FAIL",
             "lec_equivalence": "FAIL", "final_audit": "FAIL",
             "complexity_advisory": "ADVISORY"},
        not_attempted={"rtl_validate": "BLOCKED", "sim": "BLOCKED"}))
    assert ledger["failed_required"] == [], (
        "a published accepted candidate was refused -- this is the "
        "all-history-green rule #2216 forbids")
    assert ledger["eligibility"] == BD._NOT_MEASURED
    assert ledger["out_of_scope"]["yosys_synth"] == "FAIL"
    assert "lec_equivalence" in ledger["unscoped"]


def _freshness_fixture(tmp_path, status="PASS"):
    run, dataset, rtl_text = _fixture(tmp_path)
    task = BD._read_jsonl(run / BD._REVIEW_WORKLIST)[0]
    project = Path(task["project"])
    report = project / "reports/orchestrator/phase2_one_shot.json"
    doc = json.loads(report.read_text())
    doc["steps"][1]["status"] = status
    report.write_text(json.dumps(doc))
    solve = json.loads((run / "solve_report.json").read_text())
    result = solve["results"][0]
    result["phases"]["phase3_verifying"] = FPA.phase3_verifying(doc, None)
    solve["acceptance_policy"] = {
        "required": True, "review_task_schema": BD._REVIEW_TASK_SCHEMA,
        "review_schema": BD._AI_REVIEW_SCHEMA,
    }
    (run / "solve_report.json").write_text(json.dumps(solve))
    # Resume must see the same working bytes as the frozen review candidate.
    rtl = project / "phase2/stage1/rtl/TopModule.sv"
    rtl.parent.mkdir(parents=True, exist_ok=True)
    rtl.write_text(rtl_text)
    issue_io_fixture(run, "verilogeval-v2", dataset, task=task)
    return run, dataset, task, report, result


@pytest.mark.parametrize("before,after", [
    ("PASS", "FAIL"), ("FAIL", "PASS"), ("PASS", "BLOCKED"),
])
def test_changed_live_gate_evidence_blocks_export(tmp_path, before, after):
    run, _, task, report, result = _freshness_fixture(tmp_path, before)
    doc = json.loads(report.read_text())
    doc["steps"][1]["status"] = after
    report.write_text(json.dumps(doc))
    reasons = BD._shape_c_task_binding_reasons(task, run, result)
    assert any("evidence is stale" in r for r in reasons), reasons
    with pytest.raises(SystemExit, match="evidence is stale"):
        BD._export_accepted_shape_c_samples("verilogeval-v2", run)
    assert not (run / "samples" / f"{task['id']}_sample01.sv").exists()


@pytest.mark.parametrize("damage", ["absent", "json", "steps"])
def test_unreadable_live_gate_evidence_blocks_export(tmp_path, damage):
    run, _, task, report, result = _freshness_fixture(tmp_path)
    if damage == "absent":
        report.unlink()
    else:
        report.write_text("{" if damage == "json" else '{"steps": [null]}')
    reasons = BD._shape_c_task_binding_reasons(task, run, result)
    assert any("current Program gate evidence" in r for r in reasons), reasons


@pytest.mark.parametrize("status", ["PASS", "BLOCKED"])
def test_unchanged_live_gate_evidence_preserves_export_policy(tmp_path, status):
    run, _, task, _, result = _freshness_fixture(tmp_path, status)
    result["phases"]["phase3_verifying"]["ai_semantic_review"] = {"status": "PASS"}
    reasons = BD._shape_c_task_binding_reasons(task, run, result)
    assert reasons == ([] if status == "PASS" else [BD._gate_status_note(BD._required_gate_ledger(result))])
    assert BD._required_gate_ledger(result)["eligibility"] == (
        "ELIGIBLE" if status == "PASS" else BD._NOT_MEASURED)


@pytest.mark.parametrize("status,changed", [
    ("PASS", False), ("BLOCKED", False), ("PASS", True),
])
def test_resume_checks_live_gate_evidence_before_publication(tmp_path, monkeypatch, status, changed):
    from test_benchmark_program_first_ai_review import _stub_dispatched_reentry
    _stub_dispatched_reentry(monkeypatch)
    run, dataset, task, report, _ = _freshness_fixture(tmp_path, status)
    if changed:
        doc = json.loads(report.read_text())
        doc["steps"][1]["status"] = "FAIL"
        report.write_text(json.dumps(doc))
    BD.cmd_resume("verilogeval-v2", str(dataset), str(run))
    acceptance = json.loads((run / BD._ACCEPTANCE_REPORT).read_text())
    assert acceptance["accepted_ids"] == ([task["id"]] if status == "PASS" and not changed else [])
    if changed:
        repairs = BD._read_jsonl(run / BD._REPAIR_WORKLIST)
        assert any(r.get("status") == "PROGRAM_GATE_EVIDENCE_STALE"
                   for r in repairs), repairs
        assert not Path(task["response_path"]).exists()
        assert (Path(task["project"]) / "phase2/stage1/rtl/TopModule.sv").is_file()


@pytest.mark.parametrize("status", ["PASS", "FAIL", "BLOCKED", "INCOMPLETE"])
@pytest.mark.parametrize("door", ["resume", "export"])
def test_only_eligible_required_gates_publish(tmp_path, monkeypatch, status, door):
    run, dataset, task, _, result = _freshness_fixture(tmp_path, status)
    assert BD._required_gate_ledger(result)["eligibility"] == {
        "PASS": "ELIGIBLE", "FAIL": "INELIGIBLE",
        "BLOCKED": "NOT_MEASURED", "INCOMPLETE": "NOT_MEASURED",
    }[status]
    if door == "resume":
        from test_benchmark_program_first_ai_review import _stub_dispatched_reentry
        _stub_dispatched_reentry(monkeypatch)
        BD.cmd_resume("verilogeval-v2", str(dataset), str(run))
        accepted = json.loads((run / BD._ACCEPTANCE_REPORT).read_text())["accepted_ids"]
        assert accepted == ([task["id"]] if status == "PASS" else [])
        assert Path(task["response_path"]).is_file() == (status == "PASS")
        if status in {"BLOCKED", "INCOMPLETE"}:
            repair = BD._read_jsonl(run / BD._REPAIR_WORKLIST)[0]
            assert repair["status"] == "PROGRAM_GATE_NOT_MEASURED"
            assert "repair_record_requirements" not in repair
    else:
        try:
            BD._export_accepted_shape_c_samples("verilogeval-v2", run)
        except SystemExit as exc:
            assert status != "PASS", str(exc)
        samples = sorted(p.name for p in (run / "samples").glob("*.sv"))
        assert samples == ([f"{task['id']}_sample01.sv"] if status == "PASS" else [])


@pytest.mark.parametrize("status", ["PASS", "FAIL", "BLOCKED"])
@pytest.mark.parametrize("door", ["score", "shape-b"])
def test_retained_acceptance_cannot_export_unmeasured_gates(tmp_path, monkeypatch, status, door):
    run, _, task, _, _ = _freshness_fixture(tmp_path, status)
    BD._atomic_write_json(run / BD._ACCEPTANCE_REPORT, {
        "schema": BD._ACCEPTANCE_SCHEMA, "status": "COMPLETE", "total": 1,
        "accepted": 1, "accepted_ids": [task["id"]]})
    Path(task["response_path"]).write_bytes(Path(task["candidate_snapshot"]["response_payload_path"]).read_bytes())
    if door == "shape-b":
        import benchmark_io_adapter as bio
        monkeypatch.setattr(bio, "problems", lambda *args: [])
        # No input records: an eligible run reaches dataset lookup, but a held
        # ledger must stop earlier, before the existing sample exporter runs.
        with pytest.raises(SystemExit) as caught:
            BD._export_accepted_shape_b_samples("rtllm", tmp_path, run)
        observed = str(caught.value)
        assert ("no dataset input record" in observed) == (status == "PASS"), observed
        if status != "PASS":
            assert "PROGRAM gate" in observed
        return
    try:
        BD._require_program_first_ai_acceptance(run)
        accepted = True
    except SystemExit:
        accepted = False
    assert accepted == (status == "PASS")
