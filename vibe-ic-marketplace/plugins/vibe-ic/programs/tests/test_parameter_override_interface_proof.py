"""Native evidence for a public parameter incorrectly made non-overridable.

Neutral protocol fixtures, not AI judgements or benchmark candidate acceptance.
The same immutable test must execute after repair; compile rejection is never
reported as a runtime FAIL. Existing port-proof controls run separately.
"""
import json
from pathlib import Path

import pytest

import benchmark_dispatch as bd
from test_issue2210_required_interface_omission import _candidate
import test_benchmark_program_first_ai_review as review_fixture


PROMPT = """Module name: configurable_link
Declare parameter BIAS = 3 in the public module interface, so an instantiation
can override BIAS. Input a and output y are each four bits; y equals a + BIAS.
"""
EXCERPT = "Declare parameter BIAS = 3 in the public module interface"
RTL = """module configurable_link(input [3:0] a, output [3:0] y);
localparam BIAS = 3;
assign y = a + BIAS;
endmodule
"""


def challenge(style="named", module="configurable_link", parameter="BIAS"):
    override = f"#(.{parameter}(5))" if style == "named" else ""
    defparam = f"defparam dut.{parameter} = 5;" if style == "defparam" else ""
    return f"""`timescale 1ns/1ps
module vibeic_ai_challenge_tb;
reg [3:0] a = 2;
wire [3:0] y;
{module} {override} dut(.a(a), .y(y));
{defparam}
initial begin
  #1;
  if (y !== 7) begin
    $display("VIBEIC_AI_CHALLENGE=FAIL");
    $fatal(1, "overridden value did not affect output");
  end
  $display("VIBEIC_AI_CHALLENGE=PASS");
  $finish;
end
endmodule
"""


def proof(candidate, source, *, prompt=PROMPT, **changes):
    prompt_path = Path(candidate["manifest_path"]).parent / "public-prompt.md"
    prompt_path.write_text(prompt)
    result = {
        "schema": bd._INTERFACE_PROOF_SCHEMA,
        "kind": "parameter_override", "module": "configurable_link",
        "parameter": "BIAS", "excerpt": EXCERPT,
        "supports": "BIAS is explicitly a public overridable parameter.",
        "prompt_sha256": bd._sha256_text(prompt),
        "prompt_path": str(prompt_path),
        "candidate_rtl_sha256": candidate["rtl_sha256"],
        "challenge_sha256": bd._sha256_text(source),
    }
    result.update(changes)
    return result


def task(candidate, prompt=PROMPT):
    return {"id": candidate["id"], "prompt_sha256": bd._sha256_text(prompt),
            "prompt_path": str(Path(candidate["manifest_path"]).parent / "public-prompt.md"),
            "rtl_sha256": candidate["rtl_sha256"],
            "rtl_paths": candidate["rtl_paths"], "public_original_input": None}


def run(tmp_path, rtl=RTL, source=None, prompt=PROMPT, **changes):
    candidate = _candidate(tmp_path, "neutral", rtl)
    source = challenge() if source is None else source
    path = tmp_path / "challenge.sv"
    path.write_text(source)
    bound = {"path": str(path), "sha256": bd._sha256_text(source),
             "prompt_sha256": bd._sha256_text(prompt),
             "interface_proof": proof(candidate, source, prompt=prompt, **changes)}
    result = bd._run_verification_challenge(candidate, bound)
    (tmp_path / "execution.json").write_text(json.dumps(result, indent=2))
    return candidate, bound, result


@pytest.mark.parametrize("style", ["named", "defparam"])
def test_native_nonoverridable_public_parameter_is_candidate_broken(tmp_path, style):
    candidate, bound, result = run(tmp_path, source=challenge(style))
    assert result["status"] == bd._CHALLENGE_CANDIDATE_BROKEN, result
    assert "Cannot override localparam" in str(result["execution"])
    assert "parameter" in result["reasons"][0]
    assert result["status"] not in ("FAIL", "PASS")
    frozen, reasons = bd._interface_proof_from_review(
        bound["interface_proof"], task(candidate), PROMPT, challenge(style))
    assert reasons == [] and frozen["kind"] == "parameter_override"


def test_fixed_child_passes_same_immutable_challenge_without_spending_parent_proof(tmp_path):
    parent, bound, rejected = run(tmp_path / "parent")
    assert rejected["status"] == bd._CHALLENGE_CANDIDATE_BROKEN
    fixed = RTL.replace("localparam BIAS = 3;", "parameter BIAS = 3;")
    child = _candidate(tmp_path / "child", "neutral", fixed)
    result = bd._run_verification_challenge(child, bound)
    assert result["status"] == "PASS", result
    assert "VIBEIC_AI_CHALLENGE=PASS" in result["output"]
    assert bd._sha256_text(Path(bound["path"]).read_text()) == bound["sha256"]
    assert parent["rtl_sha256"] != child["rtl_sha256"]


@pytest.mark.parametrize("damage", ["syntax", "invented", "other_module", "extra_error"])
def test_native_invalid_test_or_unrelated_module_cannot_earn_attribution(tmp_path, damage):
    source, rtl = challenge(), RTL
    if damage == "syntax":
        source = source.replace("reg [3:0] a = 2;", "reg [3:0] a = 2")
    elif damage == "invented":
        source = challenge(parameter="UNDECLARED")
    elif damage == "other_module":
        rtl += RTL.replace("configurable_link", "other_link")
        source = challenge(module="other_link")
    else:
        source = source.replace("initial begin", "missing_leaf extra();\ninitial begin")
    _, _, result = run(tmp_path, rtl=rtl, source=source)
    assert result["status"] == "INVALID", result


@pytest.mark.parametrize("field", ["candidate_rtl_sha256", "challenge_sha256", "prompt_sha256"])
def test_runtime_stale_proof_is_invalid(tmp_path, field):
    _, _, result = run(tmp_path, **{field: "0" * 64})
    assert result["status"] == "INVALID", result


@pytest.mark.parametrize("change", [
    {"excerpt": "BIAS = 3 in the public module interface"},
    {"parameter": "UNDECLARED"},
    {"module": "other_link"},
    {"prompt_sha256": "0" * 64},
    {"candidate_rtl_sha256": "0" * 64},
    {"challenge_sha256": "0" * 64},
    {"kind": "unknown"},
])
def test_freeze_rejects_unsupported_claims_and_stale_bindings(tmp_path, change):
    candidate = _candidate(tmp_path, "neutral", RTL)
    frozen, reasons = bd._interface_proof_from_review(
        proof(candidate, challenge(), **change), task(candidate), PROMPT, challenge())
    assert frozen is None and reasons


def test_freeze_requires_current_public_source_hash_and_exact_declaration(tmp_path):
    candidate = _candidate(tmp_path, "neutral", RTL)
    current = task(candidate)
    current["public_original_input"] = {"status": "PRESENT", "source_sha256": "a" * 64}
    frozen, reasons = bd._interface_proof_from_review(
        proof(candidate, challenge(), public_source_sha256="b" * 64),
        current, PROMPT, challenge())
    assert frozen is None and "public_source_sha256" in " ".join(reasons)
    for rtl in [RTL.replace("localparam", "parameter"),
                RTL.replace("localparam BIAS = 3;", "// localparam BIAS = 3;"),
                RTL + RTL]:
        other = _candidate(tmp_path / bd._sha256_text(rtl), "neutral", rtl)
        assert bd._interface_proof_from_review(
            proof(other, challenge()), task(other), PROMPT, challenge())[0] is None


@pytest.mark.parametrize("description", [
    "An auxiliary cell uses parameter BIAS = 3. The top BIAS is implementation-local.",
    "Auxiliary cell parameters:\n    parameter BIAS = 3;",
])
def test_foreign_source_parameter_cannot_be_borrowed_for_unique_top(tmp_path, description):
    public = "Module name: configurable_link\n" + description + "\n"
    candidate, bound, result = run(tmp_path, prompt=public, excerpt="parameter BIAS = 3")
    assert result["status"] == "INVALID", result
    frozen, reasons = bd._interface_proof_from_review(
        bound["interface_proof"], task(candidate, public), public, challenge())
    assert frozen is None and "ownership" in " ".join(reasons)


def test_main_parameter_table_before_unique_module_heading_is_owned(tmp_path):
    public = ("The supported choices and corresponding values are shown below:\n"
              "    parameter BIAS = 3;\n    parameter OTHER = 4;\n\n"
              "Module name:\n    configurable_link\n\n"
              "Implementation:\nThe module uses parameters for selectable behavior.\n")
    candidate, bound, result = run(tmp_path, prompt=public, excerpt="parameter BIAS = 3;")
    assert result["status"] == bd._CHALLENGE_CANDIDATE_BROKEN, result
    frozen, reasons = bd._interface_proof_from_review(
        bound["interface_proof"], task(candidate, public), public, challenge())
    assert not reasons and frozen["parameter"] == "BIAS"


def test_actual_review_validator_and_resume_emit_existing_repair_task(tmp_path):
    # These are explicitly protocol-fixture review records, never a claim that
    # a model reviewed a real candidate. Native compiles and resume are real.
    run_root, current = review_fixture._task_with(tmp_path, PROMPT, RTL)
    source = challenge()
    review = review_fixture._valid_review(current)
    evidence = [{"excerpt": EXCERPT, "supports": "The public parameter must remain overridable."}]
    review["semantic_review"] = {
        "verdict": "FAIL", "findings": [{"issue": "Public parameter BIAS became localparam."}],
        "prompt_evidence": evidence,
        "rationale": "The public parameter declaration permits instance overrides, while the candidate declares a non-overridable localparam and rejects the same legal interface probe."}
    review["verification_test"] = review_fixture._write_challenge(
        current, "parameter.sv", source, evidence,
        "The override must elaborate and produce a plus five.",
        "The source explicitly declares parameter BIAS; this neutral test overrides it to five and verifies the changed output using the public four-bit addition contract.")
    review["verification_test"]["interface_proof"] = proof(current["candidate_snapshot"], source)
    review_fixture._write_review(current, review)
    review_fixture._solve_report(run_root, current)
    outcome = bd._validate_ai_review(current)
    (tmp_path / "validated-review.json").write_text(json.dumps(outcome, indent=2))
    assert outcome["status"] == "REPAIR_REQUIRED", outcome
    assert outcome["challenge_result"]["status"] == bd._CHALLENGE_CANDIDATE_BROKEN
    assert bd.cmd_resume("rtllm", "/unused", str(run_root)) == 2
    repairs = bd._read_jsonl(run_root / bd._REPAIR_WORKLIST)
    assert repairs[0]["status"] == "AI_SEMANTIC_REPAIR_REQUIRED", repairs
    assert repairs[0]["challenge_result"]["status"] == bd._CHALLENGE_CANDIDATE_BROKEN
    assert repairs[0]["verified_challenge"]["sha256"] == bd._sha256_text(source)
