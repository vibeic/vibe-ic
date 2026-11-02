"""Normal resume model backedge, using the real professional producer component.

The route/D1 and RTL-lint preconditions are neutral fixture admissions. The
professional simulator, functional consumer, report writer and runner receipts
are real. This does not qualify the full Phase-1/Flow109 product entry.
"""
from __future__ import annotations
import copy
import dataclasses
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
import benchmark_dispatch as bd
import benchmark_io_adapter as bio
import test_benchmark_program_first_ai_review as issued
from test_professional_tb_expert_fallback import _project

PROGRAMS = Path(bd.__file__).parent
EXPERT = '''import cocotb
from cocotb.triggers import Timer
@cocotb.test()
async def check(dut):
    dut.ck4.value = 0
    for value in (0, 1):
        dut.sample.value = value
        await Timer(2, unit="ns")
        dut.ck4.value = 1
        await Timer(2, unit="ns")
        assert int(dut.result.value) == value
        dut.ck4.value = 0
        await Timer(2, unit="ns")
    dut._log.info("PROFESSIONAL_TB PASS")
'''
PROMPT = "Design converter with sample, ck4 and result. Sample is captured at each rising clock edge.\n"
EVIDENCE = [{"excerpt": "Sample is captured at each rising clock edge.",
             "supports": "The independent verification model observes the declared edge and checks both data values."}]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def fixture_case(tmp_path, monkeypatch, *, parent_origin="AI_BACKUP", parent_entry=None):
    monkeypatch.setenv("VIBEIC_CHALLENGE_BACKEND", "host")
    run = tmp_path / "run"
    project = _project(run / "projects/p1")
    prompt = project / "input/phase1_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text(PROMPT)
    public = bio._stage_public_original("p1", PROMPT, {}, project)
    (run / "responses").mkdir()
    bd._atomic_write_json(run / ".bench_config.json", {
        "schema": "vibeic.benchmark.general_run.v1", "bench": "rtllm", "format": "rtllm",
        "dataset": "/unused", "clean_room": True, "full_dataset": True,
        "diagnostic_limit": 0, "inherited_from": None, "seed_run": None, "reused_samples_from": None})
    route = bd._make_ai_route_task("p1", project, {"public_original_input": public},
        issued.ROUTING, run, "rtllm", benchmark="rtllm", dataset_path=Path("/unused"))
    bd._publish_route_input_anchor(run, bd._route_input_anchor("rtllm", "rtllm", Path("/unused"), [route]))
    bd._write_jsonl(run / bd._ROUTE_WORKLIST, [route])
    receipt = issued._issue_pending_route_fixture(run, route, requested_evidence="behaviour")
    with monkeypatch.context() as precondition:
        def d1(argv, **kwargs):
            issued._emit_d1_fixture_report(Path(argv[2]), json.loads(kwargs["env"][bd._RUNNER_CONTEXT_ENV]))
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        precondition.setattr(bd.subprocess, "run", d1)
        bd._activate_route_d1(project, route, receipt, PROGRAMS / "vibe_ic_one_shot_runner.py",
                               bd._RunnerBudget(1, 1, 1))
    decision, reasons = bd._validate_ai_route(route, run, benchmark="rtllm", dataset=Path("/unused"))
    assert decision is not None, reasons
    rtl_task = bd._make_ai_backup_task("p1", project, ["spec-to-rtl"], "route_declaration",
        "neutral already-authored fixture RTL", "rtllm", Path("/unused"), run,
        expected_public_input=public)
    author = {"schema": "vibeic.benchmark.ai_backup_record.v1", "id": "p1",
        "task_sha256": rtl_task["task_sha256"], "prompt_sha256": rtl_task["prompt_sha256"],
        "source_sha256": public["source_sha256"], "output_manifest": bd._backup_output_manifest(project),
        "rtl_sha256": bd._sha256_text(bd._candidate_text(bd._rtl_files(project))),
        "author": {"kind": "AI", "model": "neutral-fixture-author"}, "oracle_accessed": False,
        "rationale": "This neutral RTL was independently supplied for the source-component fixture only.",
        "disposition": "NO_CHANGE", "prompt_evidence": EVIDENCE}
    bd._atomic_write_json(Path(rtl_task["completion_record_path"]), author)
    completion, errors = bd._validate_backup_completion(rtl_task, run)
    assert completion is not None, errors
    provenance = bd._archive_backup_completion(rtl_task, completion, run)
    runner = tmp_path / "producer/vibe_ic_one_shot_runner.py"
    runner.parent.mkdir()
    runner.write_text('''import dataclasses, json, pathlib, sys
sys.path.insert(0, %r)
import design_one_shot_runner as producer
p = pathlib.Path(sys.argv[1]).resolve()
reference = producer.step_professional_tb_gen(p, "converter", "vibeic-eda")
functional = producer.step_step4_functional_evidence(p, "unknown")
steps = [{"name":"rtl_gen","status":"PASS","detail":"neutral component RTL precondition"},
         {"name":"rtl_validate","status":"PASS","detail":"neutral lint precondition; no lint qualification"},
         dataclasses.asdict(reference), dataclasses.asdict(functional)]
producer._write_phase2_report(p/'reports/orchestrator/phase2_one_shot.json', {
    "project":str(p), "verdict":"PASS" if functional.status == "PASS" else "FAIL",
    "steps":steps, "measurement_scope":"ACTUAL_PROFESSIONAL_PRODUCER_COMPONENT",
    "declared_window":{"entry_step":"2", "exit_step":"4"}}, p)
raise SystemExit(0 if functional.status == "PASS" else 1)
''' % str(PROGRAMS))
    argv = bd._resume_solver_argv(runner, project, parent_origin == "AI_BACKUP", parent_entry or receipt["entry_step"], "4",
                                  "ip", receipt.get("input_contract", "structured"), "rtl")
    process = bd._RunnerBudget(1, 1, 1).run(argv)
    assert process.error is None, process.stderr
    assert process.rc == 1, process.stdout
    got = bd._collect_runner_result(process, argv, "rtllm", "p1", project, supplied_rtl=True)
    assert got["ok"], got
    import flow_phase_attribution as fpa
    phases = fpa.attribute(project, routing=decision, entry=receipt["entry_step"],
        evidence="behaviour", exit_step="4", artefact_collected=True)
    task = bd._make_ai_review_task("p1", project, got, decision, process.rc, run, parent_origin,
        program_phases=phases, runner_invocation=process.invocation, expected_public_input=public)
    task["backup_provenance"] = {**provenance, "gated_rtl_sha256": task["rtl_sha256"]}
    review = issued._valid_review({**task, "program_verification": {"functional_confirmation_required": False}})
    review["verification_test"] = issued._write_challenge(task, "challenge_tb.sv", '''module vibeic_ai_challenge_tb;
reg sample=0, ck4=0; wire result;
converter candidate(.sample(sample),.ck4(ck4),.result(result));
initial begin #2; ck4=1; #2;
if (result !== 0) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $finish; end
ck4=0; sample=1; #2; ck4=1; #2;
if (result !== 1) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $finish; end
$display("VIBEIC_AI_CHALLENGE=PASS"); $finish; end
endmodule
''', EVIDENCE, "Every sampled result equals the input at that rising clock edge.",
        "This independent two-value test exercises both sampled data values on the specified edge and rejects inversion or a stuck output without reading any oracle.")
    issued._write_review(task, review)
    bd._write_jsonl(run / bd._REVIEW_WORKLIST, [task])
    for name in (bd._BACKUP_WORKLIST, bd._REPAIR_WORKLIST, bd._ENHANCEMENT_WORKLIST):
        bd._write_jsonl(run / name, [])
    result = {"id":"p1", "accepted":False, "ok":True, "candidate_ready":True,
        "candidate_origin":parent_origin, "entry":receipt["entry_step"], "exit":"4", "evidence":"behaviour",
        "delivery_route":"ip", "routing_verdict":decision, "route_receipt":receipt,
        "public_original_input":public, "runner_invocation":process.invocation,
        "phases":phases, "awaiting_ai_review":True}
    bd._atomic_write_json(run / "solve_report.json", {"bench":"rtllm", "format":"rtllm", "dataset":"/unused",
        "total":1,"solved":1,"accepted":0,"routing_phase":"COMPLETE",
        "acceptance_policy":{"required":True,"review_task_schema":bd._REVIEW_TASK_SCHEMA,"review_schema":bd._AI_REVIEW_SCHEMA},
        "results":[result]})
    bd._atomic_write_json(run / bd._ACCEPTANCE_REPORT, {"schema":bd._ACCEPTANCE_SCHEMA,"status":"PENDING","accepted":0,"accepted_ids":[],"total":1})
    native_run = bd._RunnerBudget.run
    native_argv = bd._resume_solver_argv
    monkeypatch.setattr(bd, "_resume_solver_argv",
        lambda selected, *args, **kwargs: native_argv(runner, *args, **kwargs))
    calls = []
    def component_run(budget, planned, **kwargs):
        calls.append(list(planned))
        return native_run(budget, planned, **kwargs)
    monkeypatch.setattr(bd._RunnerBudget, "run", component_run)
    return run, project, task, process, calls


def complete_model(item):
    path = Path(item["write_model_to"])
    path.write_text(EXPERT)
    output = bd._backup_artifact_manifest(item)
    record = {"schema":"vibeic.benchmark.ai_backup_record.v1", "artifact_kind":"verification_model",
        "id":item["id"], "task_sha256":item["task_sha256"], "prompt_sha256":item["prompt_sha256"],
        "source_sha256":item["public_original_input"]["source_sha256"], "output_manifest":output,
        "rtl_sha256":item["rtl_sha256"], "model_sha256":output[0]["sha256"],
        "parent_task_sha256":item["parent_task_sha256"], "parent_runner_receipt_sha256":item["parent_runner_receipt_sha256"],
        "parent_native_invocation_id":item["parent_native_invocation_id"],
        "program_source_sha256":item["program_identity"]["source_sha256"],
        "route_receipt_sha256":item["verification_model"]["route_receipt_sha256"],
        "author":{"kind":"AI","model":"neutral-model-author"},"oracle_accessed":False,
        "rationale":"An independently derived model samples the declared clock edge and checks both known data values.",
        "prompt_evidence":EVIDENCE,"disposition":"CHANGED"}
    bd._atomic_write_json(Path(item["completion_record_path"]), record)
    return record


def test_normal_resume_issues_model_then_real_producer_replay_needs_fresh_review(tmp_path, monkeypatch):
    run, project, old, process, calls = fixture_case(tmp_path, monkeypatch)
    old_evidence = {p: Path(p).read_bytes() for p in [old["review_path"], old["challenge_path"],
        process.receipt_path, project / "phase2/stage1/ai_backup_author.json", *old["working_rtl_paths"]]}
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    tasks = bd._read_jsonl(run / bd._BACKUP_WORKLIST)
    assert [t.get("skill") for t in tasks] == ["testbench-gen"], tasks
    item = tasks[0]
    assert item["artifact_kind"] == "verification_model" and "write_rtl_to" not in item
    assert calls == []
    assert bd._read_jsonl(run / bd._REPAIR_WORKLIST) == []
    assert bd._read_json_regular(run / "solve_report.json")["results"][0]["ai_repair_required"] is False
    complete_model(item)
    # Each corrupted author/context is blocked through ordinary resume before
    # any producer replay. Restore only this private fixture's mutable inputs.
    projection = [run / name for name in ("solve_report.json", bd._BACKUP_WORKLIST,
        bd._REVIEW_WORKLIST, bd._REPAIR_WORKLIST, bd._ENHANCEMENT_WORKLIST, bd._ACCEPTANCE_REPORT)]
    author_path = Path(item["completion_record_path"])
    model_path = Path(item["write_model_to"])
    l9 = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    diagnostic = project / "reports/phase2/gates/professional_tb.json"
    for damage in ("model_hash", "parent_hash", "prompt_hash", "source_hash", "blind", "model_bytes",
                   "ldoc", "report", "helper", "external_import", "route", "source_identity", "symlink"):
        originals = {p: p.read_bytes() for p in [*projection, author_path, model_path, l9, diagnostic]}
        helper = model_path.with_name("helper.py")
        try:
            record = json.loads(author_path.read_text())
            fields = {"model_hash":"model_sha256", "parent_hash":"parent_runner_receipt_sha256",
                      "prompt_hash":"prompt_sha256", "source_hash":"program_source_sha256"}
            if damage in fields:
                record[fields[damage]] = "0" * 64
                bd._atomic_write_json(author_path, record)
            elif damage == "blind":
                record["oracle_accessed"] = True
                bd._atomic_write_json(author_path, record)
            elif damage == "model_bytes":
                model_path.write_text(EXPERT + "\n# unsigned change\n")
            elif damage == "ldoc":
                body = json.loads(l9.read_text()); body["top_module"] = "different_top"
                bd._atomic_write_json(l9, body)
            elif damage == "report":
                body = json.loads(diagnostic.read_text()); body["status"] = "PASS"
                bd._atomic_write_json(diagnostic, body)
            elif damage == "helper":
                helper.write_text("VALUE = 1\n")
            elif damage == "route":
                solve = bd._read_json_regular(run / "solve_report.json")
                solve["results"][0]["exit"] = "2"
                bd._atomic_write_json(run / "solve_report.json", solve)
            elif damage == "external_import":
                model_path.write_text(EXPERT + "\nimport pathlib\n")
                record["output_manifest"] = bd._backup_artifact_manifest(item)
                record["model_sha256"] = record["output_manifest"][0]["sha256"]
                bd._atomic_write_json(author_path, record)
            elif damage == "symlink":
                model_path.unlink(); model_path.symlink_to(l9)
            with monkeypatch.context() as mutation:
                if damage == "source_identity":
                    mutation.setattr(bd, "_program_source_identity", lambda: {"source_sha256":"0" * 64})
                assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2, damage
                assert calls == [], damage
                assert bd._read_json_regular(run / "solve_report.json")["accepted"] == 0
        finally:
            helper.unlink(missing_ok=True)
            if model_path.is_symlink(): model_path.unlink()
            for path, raw in originals.items(): path.write_bytes(raw)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    assert len(calls) == 1
    new = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert new["review_path"] != old["review_path"]
    assert new["rtl_sha256"] == old["rtl_sha256"] and new["candidate_origin"] == old["candidate_origin"]
    assert not Path(new["review_path"]).exists()
    assert new["verification_challenges"][-1]["sha256"] == digest(old["challenge_path"])
    assert bd._validate_ai_review(new)["status"] == "PENDING"
    assert bd._runner_reentry_reason(new, {}) is None
    assert all(Path(p).read_bytes() == data for p,data in old_evidence.items())
    gate = bd._read_json_regular(project / "reports/phase2/gates/professional_tb.json")
    assert gate["status"] == "PASS" and gate["cocotb_test_denominator"]["passed"] == 1
    assert gate["cocotb_test_denominator"]["skipped"] == 0
    Path(new["review_path"]).write_bytes(Path(old["review_path"]).read_bytes())
    copied = bd._validate_ai_review(new)
    assert copied["status"] == "REJECTED"
    assert any("verification_model_input_sha256" in reason for reason in copied["reasons"])
    for fields in (("verification_model_provenance", "verification_model_input"),
                   ("verification_model_provenance",), ("verification_model_input",)):
        stripped = copy.deepcopy(new)
        for field in fields: stripped.pop(field)
        rejected = bd._validate_ai_review(stripped)
        assert rejected["status"] == "REJECTED"
        assert any("native model completion requires" in reason for reason in rejected["reasons"])
        assert "VERIFICATION_MODEL_PROVENANCE_UNBOUND" in bd._runner_reentry_reason(stripped, {})
    assert new["program_verification"]["runner_invocation"].get("verification_model_completion") == {
        "task_sha256": item["task_sha256"],
        "record_sha256": new["verification_model_provenance"]["record_sha256"],
        "model_sha256": new["verification_model_input"]["sha256"]}
    stripped = copy.deepcopy(new)
    stripped.pop("verification_model_provenance"); stripped.pop("verification_model_input")
    stripped["program_verification"]["runner_invocation"].pop("verification_model_completion")
    assert "invocation record changed" in bd._runner_reentry_reason(stripped, {})
    assert bd._validate_ai_review(stripped)["status"] == "REJECTED"
    Path(new["review_path"]).unlink()
    provenance = new["verification_model_provenance"]
    for path in (Path(provenance["author_record_path"]), Path(new["verification_model_input"]["path"]),
                 Path(item["completion_record_path"]), project / "phase2/stage1/ai_backup_author.json"):
        raw = path.read_bytes()
        try:
            path.write_bytes(raw + b"\n ")
            assert "VERIFICATION_MODEL_PROVENANCE_UNBOUND" in bd._runner_reentry_reason(new, {})
        finally:
            path.write_bytes(raw)
    assert bd._runner_reentry_reason(new, {}) is None
    # A substantive reverse: the same self-checking expert model must reject a
    # known wrong value on the actual professional producer component.
    rtl = Path(old["working_rtl_paths"][0])
    rtl.write_text(rtl.read_text().replace("result <= sample", "result <= ~sample"))
    wrong = bd._RunnerBudget(1, 1, 1).run(calls[0])
    assert wrong.rc == 1 and wrong.error is None
    bad = bd._read_json_regular(project / "reports/phase2/gates/professional_tb.json")
    assert bad["status"] == "FAIL" and bad["cocotb_test_denominator"]["failures"] == 1
    assert bad["cocotb_test_denominator"]["skipped"] == 0


def test_sidecar_changes_after_native_run_never_create_fresh_review(tmp_path, monkeypatch):
    for sidecar in ("rtl", "model"):
        with monkeypatch.context() as case_patch:
            run, project, old, _, calls = fixture_case(tmp_path / sidecar, case_patch)
            assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
            item = bd._read_jsonl(run / bd._BACKUP_WORKLIST)[0]
            complete_model(item)
            actual = bd._RunnerBudget.run
            target = (project / "phase2/stage1/ai_backup_author.json" if sidecar == "rtl"
                      else Path(item["completion_record_path"]))
            def changed_after_run(budget, argv, **kwargs):
                outcome = actual(budget, argv, **kwargs)
                target.write_bytes(target.read_bytes() + b"\n ")
                return outcome
            case_patch.setattr(bd._RunnerBudget, "run", changed_after_run)
            assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
            result = bd._read_json_regular(run / "solve_report.json")["results"][0]
            assert result["accepted"] is False and result["worker_status"] == "ERROR"
            assert "VERIFICATION_MODEL_MATERIAL_CHANGED_DURING_PROGRAM" in result["worker_error"]
            assert bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]["review_path"] == old["review_path"]
            assert len(calls) == 1 and not Path(old["response_path"]).exists()


def model_source_admission(path):
    try:
        bd._verification_model_self_contained(path)
    except ValueError as exc:
        return "BLOCKED", str(exc)
    return "ELIGIBLE", ""


@pytest.mark.parametrize("fragment", [
    "reader = open\nvalue = reader('unissued_expected.txt').read()",
    "loader = __import__\nhelper = loader('unissued_helper')",
    "scope = globals\nnamespace = scope()",
    "kind = int.__class__",
    "lookup = getattr\nnamespace = lookup(cocotb, '__dict__')",
    "from cocotb import os",
    "import cocotb as alias",
    "timer = Timer\ntimer(1, unit='ns')",
    "module = cocotb\nmodule.test()",
    "logger = dut._log.info\nlogger('aliased API')",
], ids=["open_reference", "import_reference", "namespace_reference", "private_introspection",
        "reflection_reference", "unsupported_member", "module_alias", "timer_alias", "api_alias", "log_alias"])
def test_model_input_subset_rejects_capability_references_and_api_aliases(tmp_path, fragment):
    path = tmp_path / "expert_reference_tb.py"
    path.write_text(EXPERT)
    assert model_source_admission(path) == ("ELIGIBLE", "")
    path.write_text(EXPERT + "\n" + fragment + "\n")
    status, reason = model_source_admission(path)
    assert status == "BLOCKED"
    assert reason.startswith("VERIFICATION_MODEL_")


@pytest.mark.parametrize("fragment", [
    "@cocotb.test(expect_fail=True)\nasync def alternate(dut):\n    assert False",
    "@cocotb.test(expect_error=AssertionError)\nasync def alternate(dut):\n    assert False",
    "@cocotb.test(skip=True)\nasync def alternate(dut):\n    assert False",
    "options = {'expect_fail': True}\n@cocotb.test(**options)\nasync def alternate(dut):\n    assert False",
    "decorator = cocotb.test()",
], ids=["expect_fail", "expect_error", "skip", "expanded_options", "alternate_invocation"])
def test_model_test_decorator_preserves_failure_and_skip_semantics(tmp_path, fragment):
    path = tmp_path / "expert_reference_tb.py"
    path.write_text(EXPERT)
    assert model_source_admission(path) == ("ELIGIBLE", "")
    path.write_text(EXPERT + "\n" + fragment + "\n")
    status, reason = model_source_admission(path)
    assert status == "BLOCKED"
    assert reason == "VERIFICATION_MODEL_TEST_DECORATOR_UNSUPPORTED"


def test_missing_hook_declaration_guards_reject_failed_passed_or_wrong_target(tmp_path, monkeypatch):
    run, project, old, process, calls = fixture_case(tmp_path, monkeypatch)
    report_path = project / "reports/phase2/gates/professional_tb.json"
    out = project / "phase2/stage1/sim_professional/converter"
    plan_path = out / "verification_plan.json"
    junit = out / "results.xml"
    originals = {p:p.read_bytes() for p in (report_path, plan_path, junit)}
    for damage in ("real_failure", "non_skipped_pass", "wrong_status", "wrong_top", "outside_target"):
        try:
            report = json.loads(originals[report_path]); plan = json.loads(originals[plan_path])
            if damage == "real_failure":
                junit.unlink()
                junit.write_text('<testsuite tests="1" failures="1" errors="0" skipped="0"><testcase><failure/></testcase></testsuite>')
                report["cocotb_test_denominator"] = {"tests":1,"failures":1,"errors":0,"skipped":0,"passed":0}
            elif damage == "non_skipped_pass":
                junit.unlink()
                junit.write_text('<testsuite tests="1" failures="0" errors="0" skipped="0"><testcase/></testsuite>')
                report["cocotb_test_denominator"] = {"tests":1,"failures":0,"errors":0,"skipped":0,"passed":1}
            elif damage == "wrong_status": report["status"] = "PASS"
            elif damage == "wrong_top": plan["top"] = "another_top"
            else: report["out_dir"] = str(tmp_path / "outside")
            bd._atomic_write_json(report_path, report); bd._atomic_write_json(plan_path, plan)
            if damage in ("wrong_top", "outside_target"):
                with pytest.raises(ValueError): bd._verification_model_gap(project, process.invocation)
            else:
                assert bd._verification_model_gap(project, process.invocation) is None, damage
        finally:
            for path, data in originals.items():
                if path == junit: path.unlink(missing_ok=True)
                path.write_bytes(data)
    model = out / "expert_reference_tb.py"
    model.write_text(EXPERT)
    with pytest.raises(ValueError): bd._verification_model_gap(project, process.invocation)
    model.unlink()
    # A swapped external parent cannot authorize even a task before completion.
    tasks = bd._read_jsonl(run / bd._REVIEW_WORKLIST)
    tasks[0]["project"] = str(tmp_path / "external")
    bd._write_jsonl(run / bd._REVIEW_WORKLIST, tasks)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    assert bd._read_jsonl(run / bd._BACKUP_WORKLIST) == [] and calls == []
    result = bd._read_json_regular(run / "solve_report.json")["results"][0]
    assert result["verification_model_completion"]["status"] == "BLOCKED"


def test_authoring_parent_window_is_not_silently_replayed_as_verification(tmp_path, monkeypatch):
    run, project, _, _, calls = fixture_case(tmp_path, monkeypatch, parent_origin="PROGRAM", parent_entry="1")
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    assert bd._read_jsonl(run / bd._BACKUP_WORKLIST) == [] and calls == []
    result = bd._read_json_regular(run / "solve_report.json")["results"][0]
    assert "VERIFICATION_MODEL_REPLAY_WINDOW_MISMATCH" in result["verification_model_completion"]["reason"]
