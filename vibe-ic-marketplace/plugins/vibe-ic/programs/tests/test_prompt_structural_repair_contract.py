"""Neutral controls for prompt-only structural rejection and immutable replay.

Native controls require an explicitly selected immutable runtime; missing tools
are NOT_MEASURED, not successful qualification. No dataset or oracle is read.
"""
import copy
import json
import os
import subprocess
from pathlib import Path

import pytest

import benchmark_dispatch as bd
import benchmark_io_adapter as bio
import rtl_repair_contract as rc
import librelane_contract as launch
import test_issue3655_structural_repair_contract as existing

PROMPT_SCHEMA = "vibeic.prompt_structural_contract.v1"
COMPLETION_SCHEMA = "vibeic.prompt_structural_completion.v1"
PROMPT = """Implement module neutral_select with this one-bit interface:
 - input a
 - input b
 - input s
 - output y
Output y selects a when s is zero and b when s is one.
The implementation shall use only multiplexers for the selectable data path.
"""


@pytest.fixture
def native(monkeypatch):
    image = os.environ.get("VIBEIC_STRUCTURAL_TEST_IMAGE")
    container = os.environ.get("VIBEIC_STRUCTURAL_TEST_CONTAINER")
    if not image or "@sha256:" not in image or not container:
        pytest.skip("native prompt structure NOT_MEASURED: select immutable image and container")
    cp = subprocess.run(["docker", "inspect", container], capture_output=True, text=True, check=True)
    info = json.loads(cp.stdout)[0]
    pinned = subprocess.run(["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                            capture_output=True, text=True, check=True).stdout.strip()
    assert pinned == info["Image"]
    monkeypatch.setattr(existing, "IMAGE", image)
    monkeypatch.setattr(existing, "IMAGE_ID", pinned)
    monkeypatch.setattr(existing, "PROMPT", PROMPT)
    # Unit fixture supplies the ordinary original-input selection. Runner gate
    # provenance is unchanged by this patch and is tested by its own suite.
    monkeypatch.setattr(bd, "_task_rtl_input", lambda task: "original")
    return {"backend": "native", "selection": "explicit-neutral-test-runtime",
            "container": container, "container_id": info["Id"],
            "image_id": pinned, "image_digest": image.split("@", 1)[1]}


def task_and_review(tmp_path, native, candidate=existing.WRONG, *, nature=None, bind_header=False):
    run = tmp_path / "run"
    project = run / "projects" / "neutral"
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "neutral_select.sv").write_text(candidate)
    (project / "input").mkdir()
    (project / "input" / "phase1_prompt.md").write_text(PROMPT)
    reports = project / "reports" / "orchestrator"
    reports.mkdir(parents=True)
    (reports / "phase2_one_shot.json").write_text(json.dumps({"steps": [
        {"name": "rtl_gen", "status": "PASS", "detail": "neutral control"}]}))
    bio._stage_public_original("neutral", PROMPT, {}, project)
    got = bio.collect("rtllm", "neutral", project)
    routing = {**existing.ROUTING, "nature": nature or existing.ROUTING["nature"]}
    task = bd._make_ai_review_task("neutral", project, got, routing, 0,
        run, "PROGRAM", program_phases={"phase3_verifying": {"ran": {
            "step4_functional_evidence": "NOT_APPLICABLE"}}})
    task["verification_execution"] = native
    declaration = existing._contract(candidate)
    declaration["schema"] = PROMPT_SCHEMA
    declaration["candidate_path"] = declaration.pop("source_path")
    declaration.pop("source_sha256")
    if bind_header:
        # Author the known neutral fixture binding independently of the producer.
        header = PROMPT.split("```verilog\n", 1)[1].split("\n```", 1)[0]
        declaration["prompt_header_preservation"] = {
            "schema": "vibeic.prompt_header_preservation.v1",
            "prompt_sha256": bd._sha256_text(PROMPT), "module": "neutral_select",
            "header": header, "header_sha256": bd._sha256_text(header)}
    review = existing._write_structural_review(task, candidate, declaration=declaration)
    review["routing"]["ai_nature"] = routing["nature"]
    Path(task["review_path"]).write_text(json.dumps(review))
    return task, review


def save_review(task, review):
    Path(task["review_path"]).write_text(json.dumps(review))


def test_prompt_only_admits_real_structural_counterexample_without_program_pass(tmp_path, native):
    task, review = task_and_review(tmp_path, native)
    verdict = bd._validate_ai_review(task)
    assert verdict["challenge_result"]["status"] == "PASS"
    assert verdict["structural_result"]["verdict"] == "FAIL"
    assert {x["code"] for x in verdict["structural_result"]["findings"]} == {"STRUCTURAL_CONTRACT_VIOLATION"}
    assert verdict["program_review_coverage"]["blocking_gaps"] == 0
    assert verdict["status"] == "REPAIR_REQUIRED", verdict["reasons"]


@pytest.mark.parametrize("case", ["wrong_function", "correct_structure", "unbound_dut", "inherited_failure"])
def test_prompt_only_does_not_admit_unproven_rejection(tmp_path, native, case):
    candidate = existing.WRONG
    if case == "wrong_function":
        candidate = candidate.replace("left | right", "~(left | right)")
    elif case == "correct_structure":
        candidate = existing.RIGHT
    task, review = task_and_review(tmp_path, native, candidate)
    challenge = Path(task["challenge_path"])
    if case == "unbound_dut":
        text = """module vibeic_ai_challenge_tb;
initial begin
 if (1'b0) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1); end
 $display("VIBEIC_AI_CHALLENGE=PASS"); $finish;
end
endmodule
"""
        challenge.write_text(text)
        review["verification_test"]["sha256"] = bd._sha256_text(text)
        save_review(task, review)
    elif case == "inherited_failure":
        text = challenge.read_text().replace("(s ? b : a)", "(s ? a : b)")
        inherited = challenge.with_name("inherited.sv")
        inherited.write_text(text)
        task["verification_challenges"] = [{
            "schema": bd._CHALLENGE_SCHEMA, "id": task["id"],
            "path": str(inherited), "sha256": bd._sha256_text(text),
            "top_module": "vibeic_ai_challenge_tb", "prompt_sha256": task["prompt_sha256"]}]
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED", verdict
    if case == "wrong_function":
        assert verdict["challenge_result"]["status"] == "FAIL"
    elif case == "correct_structure":
        assert verdict["structural_result"]["verdict"] == "PASS"
    elif case == "unbound_dut":
        assert verdict["challenge_result"]["status"] == "PASS"
        assert verdict["program_review_coverage"]["blocking_gaps"] > 0
    else:
        assert verdict["challenge_result"]["status"] == "PASS"
        assert verdict["inherited_challenge_results"][0]["status"] == "FAIL"


def test_prompt_structure_repair_replays_same_contract_and_requires_fresh_review(tmp_path, native):
    task, review = task_and_review(tmp_path, native)
    admitted = bd._validate_ai_review(task)
    assert admitted["status"] == "REPAIR_REQUIRED"
    project = Path(task["project"])
    working = project / "phase2/stage1/rtl/neutral_select.sv"
    working.write_text(existing.RIGHT)
    repaired_hash = bd._sha256_text(bd._candidate_text(bd._rtl_files(project)))
    structural = copy.deepcopy(review["structural_verification"])
    structural["candidate_sha256"] = bd._sha256_text(existing.RIGHT)
    author = {"kind": "AI", "model": "neutral-repair-control"}
    contract = {"schema": COMPLETION_SCHEMA, "prompt_sha256": task["prompt_sha256"],
                "parent_rtl_sha256": task["rtl_sha256"], "candidate_sha256": repaired_hash,
                "challenge_sha256": admitted["verified_challenge"]["sha256"],
                "author": author, "oracle_accessed": False, "structural": structural}
    record = {"schema": bd._AI_REPAIR_RECORD_SCHEMA, "id": task["id"],
              "prompt_sha256": task["prompt_sha256"], "parent_rtl_sha256": task["rtl_sha256"],
              "repaired_rtl_sha256": repaired_hash, "challenge_sha256": contract["challenge_sha256"],
              "author": author, "oracle_accessed": False,
              "rationale": "Use the explicit mux implementation and retain the immutable structural and functional proof contracts.",
              "repair_contract": contract}
    path = bd._repair_record_path(project.parent.parent, task)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    provenance, reasons = bd._validate_repair_record(path, task, repaired_hash, admitted["verified_challenge"])
    assert reasons == [], reasons
    assert bd._requires_repair_contract(task, contract)
    collected = bio.collect("rtllm", "neutral", project, supplied_rtl=True,
                            repair_contract=contract, require_repair_contract=True)
    assert collected["ok"], collected
    proof = collected["repair_contract"]["structural"]
    assert proof["verdict"] == "PASS"
    assert proof["execution"]["script_sha256"] == admitted["structural_result"]["execution"]["script_sha256"]
    fresh = bd._make_ai_review_task("neutral", project, collected, existing.ROUTING, 0,
        project.parent.parent, "AI_REPAIR", verification_challenges=[admitted["verified_challenge"]],
        repair_provenance=provenance, repair_parent_candidate=task["candidate_snapshot"])
    fresh["verification_execution"] = native
    assert bd._validate_ai_review(fresh)["status"] == "PENDING"
    fresh_review = existing._write_structural_review(fresh, existing.RIGHT, declaration=structural)
    fresh_review.pop("structural_verification")
    fresh_review["routing"]["ai_nature"] = fresh["program_routing"]["nature"]
    fresh_review["semantic_review"]["verdict"] = "PASS"
    fresh_review["semantic_review"]["findings"] = []
    save_review(fresh, fresh_review)
    assert bd._validate_ai_review(fresh)["status"] == "ACCEPTED"
    record["repair_contract"]["structural"]["expectations"]["required_cell_types"] = {"$and": 1}
    path.write_text(json.dumps(record))
    _, reasons = bd._validate_repair_record(path, task, repaired_hash, admitted["verified_challenge"])
    assert any("differs from the admitted" in x for x in reasons)
    working.write_text(existing.WRONG)
    bad_contract = copy.deepcopy(contract)
    bad_contract["candidate_sha256"] = bd._sha256_text(existing.WRONG)
    bad_contract["structural"] = copy.deepcopy(review["structural_verification"])
    bad = bio.collect("rtllm", "neutral", project, supplied_rtl=True,
                      repair_contract=bad_contract, require_repair_contract=True)
    assert not bad["ok"]
    assert bad["repair_contract"]["structural"]["verdict"] == "FAIL"


@pytest.mark.parametrize("tamper", ["candidate", "prompt", "unsupported_abstraction", "source_mode"])
def test_prompt_structure_binding_cannot_be_laundered(tmp_path, native, tamper):
    task, review = task_and_review(tmp_path, native)
    declaration = review["structural_verification"]
    if tamper == "candidate":
        declaration["candidate_sha256"] = "0" * 64
    elif tamper == "prompt":
        declaration["requirement_source"]["sha256"] = "0" * 64
    elif tamper == "unsupported_abstraction":
        declaration["abstraction"] = "SOURCE_SYNTAX_ASSIGN_VS_ALWAYS"
    else:
        declaration["source_path"] = declaration["candidate_path"]
    save_review(task, review)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] in {"REJECTED", bd._NOT_MEASURED}
    assert verdict["structural_result"]["verdict"] in {"REFUSED", "NOT_MEASURED"}


@pytest.mark.parametrize("entrypoint,prefix", [(None, []),
    (["/dockerstartup/scripts/ui_startup.sh"], ["--skip"])])
@pytest.mark.parametrize("rc_value", [0, 17])
def test_structural_launcher_normalizes_native_and_legacy_without_masking_exit(tmp_path, monkeypatch, entrypoint, prefix, rc_value):
    monkeypatch.setattr(launch, "_image_entrypoint", lambda *args: entrypoint)
    monkeypatch.setattr(rc, "_docker_image_id", lambda *args: (existing.IMAGE_ID, None))
    monkeypatch.setattr(rc.shutil, "which", lambda name: "/usr/bin/" + name)
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        output_mount = next(x for x in argv if x.endswith(":/out:rw"))
        out = Path(output_mount[:-len(":/out:rw")])
        (out / "rtlil.json").write_text(json.dumps({"modules": {"neutral_select": {
            "cells": {"m": {"type": "$mux"}}}}}))
        return subprocess.CompletedProcess(argv, rc_value, "native-control", "failure-control" if rc_value else "")
    monkeypatch.setattr(rc.subprocess, "run", run)
    candidate = tmp_path / "candidate.sv"
    candidate.write_text(existing.RIGHT)
    declaration = existing._contract(existing.RIGHT)
    result = rc.run_structural_contract(candidate, declaration, original_source=existing.WRONG,
        requirement_sources={"input/phase1_prompt.md": existing.PROMPT})
    assert result["verdict"] == ("PASS" if rc_value == 0 else "NOT_MEASURED")
    argv = calls[0]
    at = argv.index(existing.IMAGE)
    assert argv[at+1:at+1+len(prefix)] == prefix
    assert argv[at+1+len(prefix):at+3+len(prefix)] == ["yosys", "-Q"]
    assert argv[argv.index("--user")+1] == f"{os.getuid()}:{os.getgid()}"
    assert "--network=none" in argv and "--memory=4g" in argv
    assert result["execution"]["returncode"] == rc_value


def test_source_bound_mode_keeps_its_prior_program_pass_requirement(tmp_path, native):
    _, task = existing._review_task(tmp_path, existing.WRONG)
    task["verification_execution"] = native
    existing._write_structural_review(task, existing.WRONG)
    admitted = bd._validate_ai_review(task)
    assert admitted["status"] == "REPAIR_REQUIRED"
    assert admitted["challenge_result"]["status"] == "PASS"
    assert admitted["structural_result"]["verdict"] == "FAIL"
    task["program_verification"]["functional_evidence"] = "NOT_APPLICABLE"
    task["program_verification"]["functional_confirmation_required"] = True
    rejected = bd._validate_ai_review(task)
    assert rejected["status"] == "REJECTED"
    assert any("existing Program" in x for x in rejected["reasons"])
    project = existing._project(tmp_path / "source-repair", existing.RIGHT)
    repaired = bio.collect("rtllm", "neutral", project, supplied_rtl=True,
        repair_contract=existing._normal_repair_contract(existing.RIGHT), require_repair_contract=True)
    assert repaired["ok"], repaired
    assert repaired["repair_contract"]["preservation"]["verdict"] == "PASS"
    assert repaired["repair_contract"]["elaboration_matrix"]["verdict"] == "PASS"
    assert repaired["repair_contract"]["structural"]["verdict"] == "PASS"


def test_issued_contract_exposes_prompt_binding_without_claiming_syntax_proof(tmp_path):
    task, _ = task_and_review(tmp_path, {"backend": "host"})
    shape = task["review_requirements"]["required_envelope"]["structural_verification"]
    alternative = shape["_prompt_only_alternative"]
    assert PROMPT_SCHEMA in alternative
    assert "candidate_path" in alternative and "all active inherited challenges must PASS" in alternative
    assert "source-syntax methods are not established" in alternative


def test_program_output_rebinding_preserves_prompt_structure_obligations():
    contract = {"schema": COMPLETION_SCHEMA, "candidate_sha256": "old-bundle",
                "author": {"kind": "AI", "model": "neutral"},
                "structural": {"schema": PROMPT_SCHEMA, "candidate_path": "logic.sv",
                    "candidate_sha256": "old-file", "expectations": {"required_cell_types": {"$mux": 1}}}}
    rebound = bd._program_output_repair_contract(contract, {"source": "neutral"},
        {"output_rtl_sha256": "new-bundle", "output_rtl": {"logic.sv": {"sha256": "new-file"}}})
    assert rebound["candidate_sha256"] == "new-bundle"
    assert rebound["structural"]["candidate_sha256"] == "new-file"
    assert rebound["structural"]["expectations"] == contract["structural"]["expectations"]
    assert contract["structural"]["candidate_sha256"] == "old-file"


def test_normalizer_refuses_an_ambiguous_explicit_image():
    with pytest.raises(launch.Refusal, match="LL_IMAGE_TOKEN_AMBIGUOUS"):
        launch._image_tool_argv(["docker", "run", "declared", "declared"], image="declared")


HEADER = "module neutral_select(input wire a, b, s, output wire y);"
PARAM_HEADER = "module neutral_select #(parameter P=1)(input wire a, b, s, output wire y);"


def supplied_header_prompt(monkeypatch, header=HEADER, body=""):
    prompt = PROMPT + "\n```verilog\n" + header + "\n" + body + "```\n"
    monkeypatch.setitem(globals(), "PROMPT", prompt)
    monkeypatch.setattr(existing, "PROMPT", prompt)
    return prompt


def test_pure_text_completion_uses_measured_source_absence(tmp_path, native):
    task, _ = task_and_review(tmp_path, native, nature="completion")
    assert bd._requires_source_repair_contract(task) is False
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REPAIR_REQUIRED", verdict
    assert verdict["challenge_result"]["status"] == "PASS"
    assert verdict["structural_result"]["verdict"] == "FAIL"


def test_supplied_header_preserves_source_through_native_repair_and_fresh_review(tmp_path, native, monkeypatch):
    supplied_header_prompt(monkeypatch)
    monkeypatch.setattr(existing, "ROUTING", {**existing.ROUTING, "nature": "completion"})
    original = task_and_review
    def header_review(*args, **kwargs):
        task, review = original(*args, **kwargs, nature="completion", bind_header=True)
        assert bd._requires_source_repair_contract(task) is True
        return task, review
    monkeypatch.setitem(globals(), "task_and_review", header_review)
    test_prompt_structure_repair_replays_same_contract_and_requires_fresh_review(tmp_path, native)


def test_candidate_header_may_change_only_whitespace_and_comments(tmp_path, native, monkeypatch):
    supplied_header_prompt(monkeypatch)
    candidate = existing.WRONG.replace(HEADER, "module /* retained interface */ neutral_select (\ninput wire a,b,s, output wire y\n);")
    task, _ = task_and_review(tmp_path, native, candidate, nature="completion", bind_header=True)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REPAIR_REQUIRED", verdict
    assert verdict["structural_result"]["prompt_header_preservation"]["verdict"] == "PASS"


@pytest.mark.parametrize("change", ["width", "direction", "name", "parameter_default", "removal"])
def test_changed_header_is_not_a_structural_counterexample(tmp_path, native, monkeypatch, change):
    supplied_header_prompt(monkeypatch, PARAM_HEADER)
    header = PARAM_HEADER
    if change == "width":
        header = header.replace("input wire a", "input wire [1:0] a")
    elif change == "direction":
        header = header.replace("output wire y", "input wire y")
    elif change == "name":
        header = header.replace("wire a", "wire renamed")
    elif change == "parameter_default":
        header = header.replace("P=1", "P=2")
    else:
        header = "module neutral_select;"
    candidate = existing.WRONG.replace(HEADER, header)
    task, _ = task_and_review(tmp_path, native, candidate, nature="completion", bind_header=True)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert verdict["structural_result"]["verdict"] == "REFUSED"
    assert any(x["code"] == "STRUCTURAL_PROMPT_HEADER_CHANGED" for x in verdict["structural_result"]["findings"])


@pytest.mark.parametrize("nature", ["spec_generation", "completion"])
def test_functional_only_repair_cannot_discard_embedded_source(tmp_path, native, monkeypatch, nature):
    # Source/record boundary control: no structural declaration means no narrow
    # structural exception, even if a functional repair record is otherwise bound.
    monkeypatch.setattr(bd, "_task_rtl_input", lambda task: "original")
    supplied_header_prompt(monkeypatch)
    bad_function = existing.WRONG.replace("left | right", "left & right")
    task, review = task_and_review(tmp_path, native, bad_function, nature=nature)
    review.pop("structural_verification")
    review["semantic_review"]["findings"] = ["Output y fails the prompt's selection function."]
    review["semantic_review"]["rationale"] = "The exhaustive prompt-derived selection test fails on this exact frozen candidate."
    save_review(task, review)
    prior = bd._validate_ai_review(task)
    assert prior["status"] == "REPAIR_REQUIRED"
    assert prior["challenge_result"]["status"] == "FAIL"
    working = Path(task["project"]) / "phase2/stage1/rtl/neutral_select.sv"
    # A wider input retains every tested functional result, yet changes the
    # supplied source. The repair record must reject it before later gates.
    working.write_text(existing.RIGHT.replace("input wire a", "input wire [1:0] a"))
    project = Path(task["project"])
    got = bio.collect("rtllm", "neutral", project, supplied_rtl=True)
    frozen = bd._archive_candidate("neutral", project, got, project.parent.parent,
        "AI_REPAIR", archive_key="functional-header-mutation-control")
    repaired_function = bd._run_verification_challenge(frozen,
        {**prior["verified_challenge"], "execution_backend": native})
    assert repaired_function["status"] == "PASS"
    repaired = bd._sha256_text(bd._candidate_text(bd._rtl_files(Path(task["project"]))))
    challenge = prior["verified_challenge"]
    record = {"schema": bd._AI_REPAIR_RECORD_SCHEMA, "id": task["id"],
              "prompt_sha256": task["prompt_sha256"], "parent_rtl_sha256": task["rtl_sha256"],
              "repaired_rtl_sha256": repaired, "challenge_sha256": challenge["sha256"],
              "author": {"kind": "AI", "model": "neutral-functional-repair"},
              "oracle_accessed": False,
              "rationale": "Bound neutral functional repair control that must not silently drop a supplied header."}
    path = tmp_path / "functional_repair.json"
    path.write_text(json.dumps(record))
    validated, reasons = bd._validate_repair_record(path, task, repaired, challenge)
    assert bool(validated) is False
    assert validated is None
    assert bd._requires_source_repair_contract(task) is True
    assert any("lacks repair_contract" in x for x in reasons), reasons


@pytest.mark.parametrize("source", [
    HEADER + "\nwire retained;\n", HEADER + "\nassign y=a;\nendmodule\n",
    HEADER + "\nmodule helper;\n", "module neutral_select(input a, output y\n",
])
def test_body_or_incomplete_source_cannot_be_reclassified_as_text(tmp_path, monkeypatch, source):
    monkeypatch.setattr(bd, "_task_rtl_input", lambda task: "original")
    prompt = PROMPT + "\n```verilog\n" + source + "```\n"
    monkeypatch.setitem(globals(), "PROMPT", prompt)
    monkeypatch.setattr(existing, "PROMPT", prompt)
    task, _ = task_and_review(tmp_path, {"backend": "host"})
    assert bd._requires_source_repair_contract(task) is True
    assert rc.prompt_rtl_source_facts(prompt)["kind"] == "UNSUPPORTED"
    assert bd._allows_prompt_structural_binding(task) is False


def test_malformed_public_manifest_is_not_source_absence(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, "_task_rtl_input", lambda task: "original")
    task, _ = task_and_review(tmp_path, {"backend": "host"}, nature="completion")
    manifest = Path(task["project"]) / "input/public_original/manifest.json"
    manifest.write_text("{invalid")
    assert bd._requires_source_repair_contract(task) is True
    assert bd._allows_prompt_structural_binding(task) is False


def test_header_token_comparison_retains_string_defaults():
    left = 'module cedar #(parameter S="a b//x")(input a);'
    assert rc._header_tokens(left) != rc._header_tokens(left.replace("a b", "a  b"))
    assert rc._header_tokens(left) == rc._header_tokens(left.replace("input a", "input /* same */ a"))


def test_header_binding_cannot_be_omitted_or_replaced(tmp_path, native, monkeypatch):
    supplied_header_prompt(monkeypatch)
    task, review = task_and_review(tmp_path, native, nature="completion")
    missing = bd._validate_ai_review(task)
    assert missing["status"] == "REJECTED"
    assert missing["structural_result"]["findings"][0]["code"] == "STRUCTURAL_PROMPT_HEADER_UNBOUND"
    facts = rc.prompt_rtl_source_facts(PROMPT)
    binding = rc.prompt_header_preservation(facts)
    binding["header_sha256"] = "0" * 64
    review["structural_verification"]["prompt_header_preservation"] = binding
    save_review(task, review)
    assert bd._validate_ai_review(task)["status"] == "REJECTED"


def test_source_facts_retain_bodies_outside_fences_and_ignore_comments():
    prompt = "Complete selection.\n```verilog\n" + HEADER + "\n```\n"
    assert rc.prompt_rtl_source_facts(prompt)["kind"] == "HEADER_ONLY"
    assert rc.prompt_rtl_source_facts(prompt + "assign y=a;\n")["kind"] == "UNSUPPORTED"
    assert rc.prompt_rtl_source_facts("wire retained;\n")["kind"] == "UNSUPPORTED"
    comment = "```verilog\n/* module old(input a); assign y=a; endmodule */\n```\n"
    assert rc.prompt_rtl_source_facts(comment)["kind"] == "NONE"
    assert rc.prompt_rtl_source_facts("logic should, where possible, be combinational.\n")["kind"] == "NONE"


@pytest.mark.parametrize("prefix", ["`define W 1\n", "typedef logic flag_t;\n", "(* keep = 1 *)\n"])
def test_header_only_does_not_discard_other_supplied_source(prefix):
    prompt = "Complete the code.\n```verilog\n" + prefix + HEADER + "\n```\n"
    assert rc.prompt_rtl_source_facts(prompt)["kind"] == "UNSUPPORTED"


def test_embedded_body_native_scope_is_not_measured(tmp_path, native, monkeypatch):
    supplied_header_prompt(monkeypatch, body="wire retained;\n")
    task, _ = task_and_review(tmp_path, native, nature="completion")
    verdict = bd._validate_ai_review(task)
    assert verdict["challenge_result"]["status"] == "PASS"
    assert verdict["status"] == bd._NOT_MEASURED
    assert verdict["structural_result"]["verdict"] == "NOT_MEASURED"
    assert verdict["structural_result"]["findings"][0]["code"] == "STRUCTURAL_PROMPT_SOURCE_UNSUPPORTED"



def test_source_facts_do_not_treat_parameter_prose_or_markdown_names_as_hdl():
    prompt = "Interface:\n`P` denotes a constant. The design should expose a parameter with a default of one; complete the selection function.\n"
    assert rc.prompt_rtl_source_facts(prompt)["kind"] == "NONE"
    assert rc.prompt_rtl_source_facts("Complete: module inline_unit(input a); assign y=a; endmodule")["kind"] == "UNSUPPORTED"
    assert rc.prompt_rtl_source_facts("parameter P=1;\n")["kind"] == "UNSUPPORTED"


PORT_HEADER = "module neutral_select(input [2:0] data, output [5:3] result);"
PORT_PROMPT = "Copy data to result through a whole-vector connection.\n```verilog\n" + PORT_HEADER + "\n```\n"
PORT_GOOD = PORT_HEADER + "\nassign result=data;\nendmodule\n"
PORT_BAD = PORT_GOOD.replace("[5:3]", "[2:0]")
PORT_CHALLENGE = '''module vibeic_ai_challenge_tb;
reg [2:0] data; wire [5:3] result; integer i;
neutral_select dut(.data(data), .result(result));
initial begin
 for(i=0;i<8;i=i+1) begin
  data=i; #1;
  if(result !== data) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1); end
 end
 $display("VIBEIC_AI_CHALLENGE=PASS"); $finish;
end
endmodule
'''


def port_task(tmp_path, native, monkeypatch, candidate=PORT_BAD, prompt=PORT_PROMPT):
    monkeypatch.setitem(globals(), "PROMPT", prompt)
    monkeypatch.setattr(existing, "PROMPT", prompt)
    task, review = task_and_review(tmp_path, native, candidate, nature="completion", bind_header=True)
    declaration = review["structural_verification"]
    declaration.update(scope="top_module_ports", expectations={"ports_from_prompt_header": True})
    facts = rc.prompt_rtl_source_facts(prompt)
    declaration["requirement_source"].update(quote=facts["header"], quote_sha256=rc.sha256_text(facts["header"]))
    review["semantic_review"].update(findings=[{"issue": "the supplied port range changed"}],
        rationale="The exact public header defines the declared output bounds independently of whole-vector behavior.")
    Path(task["challenge_path"]).write_text(PORT_CHALLENGE)
    review["verification_test"].update(sha256=rc.sha256_text(PORT_CHALLENGE),
        rationale="Exhaustively exercise all three-bit input values using ordinary whole-vector connections to check the public copy behavior.",
        expected_behavior="Copy every three-bit data value to the result whole-vector port.")
    save_review(task, review)
    return task, review


def test_native_port_range_mismatch_has_functional_pass_and_measured_structural_fail(tmp_path, native, monkeypatch):
    task, review = port_task(tmp_path, native, monkeypatch)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REPAIR_REQUIRED", verdict
    assert verdict["challenge_result"]["status"] == "PASS"
    measured = verdict["structural_result"]
    assert measured["verdict"] == "FAIL"
    assert {x["code"] for x in measured["findings"]} == {"STRUCTURAL_CONTRACT_VIOLATION"}
    assert measured["observation"]["ports"]["result"]["left"] == 2
    assert measured["observation"]["ports"]["result"]["right"] == 0
    assert measured["expected_observation"]["ports"]["result"]["left"] == 5
    assert measured["expected_observation"]["ports"]["result"]["right"] == 3
    assert measured["execution"]["limits"]["memory"] == "2g"
    working = Path(task["project"]) / "phase2/stage1/rtl/neutral_select.sv"
    working.write_text(PORT_GOOD)
    structural = copy.deepcopy(review["structural_verification"])
    structural["candidate_sha256"] = rc.sha256_text(PORT_GOOD)
    contract = {"schema": COMPLETION_SCHEMA, "prompt_sha256": task["prompt_sha256"],
        "candidate_sha256": bd._sha256_text(bd._candidate_text(bd._rtl_files(Path(task["project"])))),
        "structural": structural}
    repaired = bio.collect("rtllm", "neutral", Path(task["project"]), supplied_rtl=True,
        repair_contract=contract, require_repair_contract=True)
    assert repaired["ok"], repaired
    replay = repaired["repair_contract"]["structural"]
    assert replay["verdict"] == "PASS"
    assert replay["execution"]["script_sha256"] == measured["execution"]["script_sha256"]
    author = {"kind": "AI", "model": "neutral-port-repair-control"}
    challenge = verdict["verified_challenge"]
    contract.update(parent_rtl_sha256=task["rtl_sha256"],
        challenge_sha256=challenge["sha256"], author=author, oracle_accessed=False)
    record = {"schema": bd._AI_REPAIR_RECORD_SCHEMA, "id": task["id"],
        "prompt_sha256": task["prompt_sha256"], "parent_rtl_sha256": task["rtl_sha256"],
        "repaired_rtl_sha256": contract["candidate_sha256"], "challenge_sha256": challenge["sha256"],
        "author": author, "oracle_accessed": False,
        "rationale": "Restore the original public declaration and retain the exact admitted native and functional contracts.",
        "repair_contract": contract}
    record_path = bd._repair_record_path(Path(task["project"]).parent.parent, task)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(record))
    provenance, reasons = bd._validate_repair_record(record_path, task, contract["candidate_sha256"], challenge)
    assert reasons == [], reasons
    fresh = bd._make_ai_review_task("neutral", Path(task["project"]), repaired, existing.ROUTING, 0,
        Path(task["project"]).parent.parent, "AI_REPAIR", verification_challenges=[challenge],
        repair_provenance=provenance, repair_parent_candidate=task["candidate_snapshot"])
    fresh["verification_execution"] = native
    assert bd._validate_ai_review(fresh)["status"] == "PENDING"
    fresh_review = copy.deepcopy(review)
    fresh_review.update(prompt_sha256=fresh["prompt_sha256"], rtl_sha256=fresh["rtl_sha256"])
    fresh_review.pop("structural_verification")
    fresh_review["routing"]["ai_nature"] = fresh["program_routing"]["nature"]
    fresh_review["semantic_review"].update(verdict="PASS", findings=[])
    fresh_review["verification_test"]["path"] = str(Path(fresh["challenge_path"]).resolve())
    Path(fresh["challenge_path"]).parent.mkdir(parents=True, exist_ok=True)
    Path(fresh["challenge_path"]).write_text(PORT_CHALLENGE)
    save_review(fresh, fresh_review)
    accepted = bd._validate_ai_review(fresh)
    assert accepted["status"] == "ACCEPTED", accepted
    # Restoring metadata alone is insufficient: significant header tokens are
    # still protected at the actual normal-repair consumer.
    changed = PORT_GOOD.replace("output [5:3]", "output wire [5:3]")
    working.write_text(changed)
    structural["candidate_sha256"] = rc.sha256_text(changed)
    contract["candidate_sha256"] = bd._sha256_text(bd._candidate_text(bd._rtl_files(Path(task["project"]))))
    refused = bio.collect("rtllm", "neutral", Path(task["project"]), supplied_rtl=True,
        repair_contract=contract, require_repair_contract=True)
    assert not refused["ok"]
    assert refused["repair_contract"]["structural"]["findings"][0]["code"] == "STRUCTURAL_PROMPT_HEADER_CHANGED"


@pytest.mark.parametrize("change", ["good", "ascending", "ascending_match", "signed", "default_offset", "zero_match", "order", "reverse"])
def test_native_port_metadata_discriminates_declarations(tmp_path, native, monkeypatch, change):
    candidate, prompt = PORT_GOOD, PORT_PROMPT
    if change == "ascending":
        candidate = candidate.replace("[5:3]", "[3:5]")
    elif change == "signed":
        candidate = candidate.replace("output [5:3]", "output signed [5:3]")
    elif change == "default_offset":
        candidate = PORT_BAD
    elif change == "order":
        candidate = candidate.replace(PORT_HEADER, "module neutral_select(output [5:3] result, input [2:0] data);")
    elif change == "reverse":
        prompt = prompt.replace("[5:3]", "[2:0]")
    elif change == "ascending_match":
        candidate, prompt = candidate.replace("[5:3]", "[3:5]"), prompt.replace("[5:3]", "[3:5]")
    elif change == "zero_match":
        candidate, prompt = PORT_BAD, prompt.replace("[5:3]", "[2:0]")
    task, review = port_task(tmp_path, native, monkeypatch, candidate, prompt)
    proof = bd._run_review_structural_proof(task, task["candidate_snapshot"], review["structural_verification"], prompt)
    assert proof["verdict"] == ("PASS" if change in ("good", "ascending_match", "zero_match") else "FAIL"), proof
    if change == "ascending":
        assert proof["observation"]["ports"]["result"]["upto"] == 1
    elif change == "signed":
        assert proof["observation"]["ports"]["result"]["signed"] == 1
    elif change == "order":
        assert proof["observation"]["ordered_ports"] == ["result", "data"]
        assert proof["expected_observation"]["ordered_ports"] == ["data", "result"]


@pytest.mark.parametrize("tamper", ["invented_expectation", "candidate", "source", "quote", "header", "image", "source_mode"])
def test_port_observation_refuses_invented_or_unbound_contract(tmp_path, native, monkeypatch, tamper):
    task, review = port_task(tmp_path, native, monkeypatch)
    declaration = review["structural_verification"]
    if tamper == "invented_expectation":
        declaration["expectations"]["ports"] = {"result": {"left": 2, "right": 0}}
    elif tamper == "candidate":
        declaration["candidate_sha256"] = "0" * 64
    elif tamper == "source":
        declaration["requirement_source"]["sha256"] = "0" * 64
    elif tamper == "quote":
        declaration["requirement_source"].update(quote="Copy data", quote_sha256=rc.sha256_text("Copy data"))
    elif tamper == "header":
        declaration["prompt_header_preservation"]["header_sha256"] = "0" * 64
    elif tamper == "image":
        declaration["backend"]["image_id"] = "sha256:" + "0" * 64
    else:
        declaration["source_path"] = "neutral_select.sv"
    proof = bd._run_review_structural_proof(task, task["candidate_snapshot"], declaration, PORT_PROMPT)
    assert proof["verdict"] == "REFUSED", proof
    assert "execution" not in proof


@pytest.mark.parametrize("header", [PARAM_HEADER, PORT_HEADER + "\nassign result=data;\nendmodule", PORT_HEADER + "\nmodule other;",
    "module neutral_select(input [2:0] data, output [`WIDTH:3] result);",
    'module neutral_select(input [2:0] data,\n// @\n(* single_bit_vector = 0 *) output [0:0] result);'])
def test_port_source_scope_does_not_infer_unsupported_header(tmp_path, native, monkeypatch, header):
    candidate = tmp_path / "candidate.sv"
    candidate.write_text("`define WIDTH 5\n" + PORT_BAD)
    prompt = "Copy data.\n```verilog\n" + header + "\n```\n"
    declaration = {"schema": PROMPT_SCHEMA, "candidate_path": "neutral_select.sv",
        "candidate_sha256": rc.sha256_text(candidate.read_text()), "top": "neutral_select",
        "abstraction": "RTLIL_AFTER_PROC_OPT", "scope": "top_module_ports",
        "expectations": {"ports_from_prompt_header": True},
        "requirement_source": {"path": "input/phase1_prompt.md", "sha256": rc.sha256_text(prompt),
            "quote": header, "quote_sha256": rc.sha256_text(header)}}
    facts = rc.prompt_rtl_source_facts(prompt)
    if facts["kind"] == "HEADER_ONLY":
        declaration["prompt_header_preservation"] = rc.prompt_header_preservation(facts)
    proof = rc.run_structural_contract(candidate, declaration, original_source=None,
        requirement_sources={"input/phase1_prompt.md": prompt})
    assert proof["verdict"] == "NOT_MEASURED", proof
    assert "execution" not in proof


def test_normal_port_repair_missing_candidate_is_a_typed_refusal(tmp_path):
    structural = {"schema": PROMPT_SCHEMA, "scope": "top_module_ports",
        "abstraction": "RTLIL_AFTER_PROC_OPT", "candidate_path": "neutral_select.sv"}
    result = rc.validate_normal_repair_contract({}, {}, {"structural": structural},
        candidate_path=tmp_path / "missing.sv", original_source=None)
    assert result["verdict"] == "REFUSED"
    assert result["structural"]["findings"][0]["code"] == "STRUCTURAL_CANDIDATE_MISSING"
    assert "execution" not in result["structural"]


@pytest.mark.parametrize("attribute", ["single_bit_vector = 0", 'single_bit_vector = ""',
    "\\single_bit_vector = 0", "irrelevant = 1", "macro_alias", "split_macro", "comment_context"])
def test_native_port_metadata_refuses_candidate_attribute_authority(tmp_path, native, monkeypatch, attribute):
    scalar_header = "module neutral_select(input data, output result);"
    prompt = "Copy data to result.\n```verilog\n" + scalar_header + "\n```\n"
    if attribute == "macro_alias":
        candidate = '`define ALIAS (* single_bit_vector = 0 *)\nmodule neutral_select(input data, `ALIAS output [0:0] result);\nassign result=data;\nendmodule\n'
    elif attribute == "split_macro":
        candidate = '`define OPEN (*\n`define CLOSE *)\nmodule neutral_select(input data, `OPEN single_bit_vector = 0 `CLOSE output [0:0] result);\nassign result=data;\nendmodule\n'
    elif attribute == "comment_context":
        candidate = 'module neutral_select(input data,\n// @\n(* single_bit_vector = 0 *) output [0:0] result);\nassign result=data;\nendmodule\n'
    else:
        candidate = scalar_header.replace("output result", "(* " + attribute + " *) output [0:0] result") + "\nassign result=data;\nendmodule\n"
    task, review = port_task(tmp_path, native, monkeypatch, candidate, prompt)
    proof = bd._run_review_structural_proof(task, task["candidate_snapshot"], review["structural_verification"], prompt)
    assert proof["verdict"] == "NOT_MEASURED", proof
    assert proof["findings"][0]["code"] == "STRUCTURAL_PORT_METADATA_UNTRUSTED"
    assert "execution" not in proof


@pytest.mark.parametrize("variant", ["scalar", "vector", "comment", "string", "wildcard", "wildcard_comment"])
def test_native_port_metadata_scalar_vector_fact_requires_clean_provenance(tmp_path, native, monkeypatch, variant):
    scalar_header = "module neutral_select(input data, output result);"
    prompt = "Copy data to result.\n```verilog\n" + scalar_header + "\n```\n"
    candidate = scalar_header + "\nassign result=data;\nendmodule\n"
    if variant == "vector":
        candidate = candidate.replace("output result", "output [0:0] result")
    elif variant == "comment":
        candidate += '\n// `ALIAS (* single_bit_vector = 0 *)\n'
    elif variant == "string":
        candidate = candidate.replace("assign result", 'localparam NOTE="`ALIAS (* single_bit_vector = 0 *)";\nassign result')
    elif variant in ("wildcard", "wildcard_comment"):
        event = "@(*)" if variant == "wildcard" else "@ /* retained comment */ (*)"
        candidate = candidate.replace("output result", "output reg result").replace("assign result=data;", "always " + event + " result=data;")
    task, review = port_task(tmp_path, native, monkeypatch, candidate, prompt)
    proof = bd._run_review_structural_proof(task, task["candidate_snapshot"], review["structural_verification"], prompt)
    assert proof["verdict"] == ("FAIL" if variant == "vector" else "PASS"), proof
    assert "execution" in proof
    assert proof["observation"]["ports"]["result"]["single_bit_vector"] == (variant == "vector")


@pytest.mark.parametrize("raw", ["comment_like", "quote_like", "plain_identifier", "string_backslash", "header_identifier"])
def test_port_proof_refuses_raw_escaped_syntax_before_masking(tmp_path, native, monkeypatch, raw):
    header = "module neutral_select(input data, output result);"
    prompt = "Copy data to result.\n```verilog\n" + header + "\n```\n"
    candidate = header + "\nassign result=data;\nendmodule\n"
    if raw == "header_identifier":
        prompt = prompt.replace("output result", "output \\result ")
    elif raw == "string_backslash":
        candidate = candidate.replace("assign result", 'localparam NOTE="\\\\escaped";\nassign result')
    else:
        name = {"comment_like": "unused//comment", "quote_like": 'unused"quote', "plain_identifier": "unused"}[raw]
        candidate = 'module neutral_select(input data, output [0:0] result); wire \\' + name + ' ; (* single_bit_vector = 0 *) wire [0:0] result; assign result=data; endmodule\n'
    task, review = port_task(tmp_path, native, monkeypatch, candidate, prompt)
    proof = bd._run_review_structural_proof(task, task["candidate_snapshot"], review["structural_verification"], prompt)
    assert proof["verdict"] == "NOT_MEASURED", proof
    assert proof["findings"][0]["code"] == "STRUCTURAL_PORT_METADATA_UNTRUSTED"
    assert "execution" not in proof
