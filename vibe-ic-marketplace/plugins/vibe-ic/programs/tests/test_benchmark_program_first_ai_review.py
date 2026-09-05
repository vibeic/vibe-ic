#!/usr/bin/env python3
"""Program First is scoreable only after evidence-bound blind AI review."""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import benchmark_dispatch as bd                         # noqa: E402
import benchmark_io_adapter as bio                      # noqa: E402


def _simulator_absent() -> str:
    """Why this host cannot EXECUTE a verification challenge, or "" if it can.

    MEASURED, one host, one tree, one commit: with `iverilog` and `vvp` on PATH
    this module is 19 passed from four different working directories; with the
    same tree and the same directories but those two binaries off PATH it is
    `4 failed, 15 passed`, the first of them an IndexError on an empty repair
    worklist. The verdict is invariant in CWD and flips entirely on the
    capability -- so four tests that drive a REAL simulation were reporting a
    host capability gap as four behavioural defects.

    They now declare the dependency. This is NOT an unconditional skip: the
    condition is a live probe of the same two binaries the production code
    looks for, `test_the_skip_condition_is_the_production_question` pins it to
    that, and every branch those four tests cover is ALSO covered
    host-independently by the stubbed NOT_MEASURED tests at the end of this
    module -- so nothing here can go quiet on a bare host.
    """
    import shutil                                       # noqa: PLC0415
    missing = [tool for tool in ("iverilog", "vvp") if shutil.which(tool) is None]
    if not missing:
        return ""
    return ("NOT_MEASURED: this host has no " + " and no ".join(missing)
            + "; a verification challenge cannot be executed here, so this "
              "test would be measuring the host, not the code")


_NEEDS_SIMULATOR = pytest.mark.skipif(
    bool(_simulator_absent()),
    reason=_simulator_absent() or "iverilog and vvp are both present")


def _no_simulator(monkeypatch) -> None:
    """Make this process look like a host with no simulator, precisely.

    Only `iverilog` and `vvp` disappear; every other `which` answer is the real
    one, so nothing else in the flow changes shape underneath the assertion.
    """
    import shutil                                       # noqa: PLC0415
    real = shutil.which
    monkeypatch.setattr(
        bd.shutil, "which",
        lambda name, *a, **k: (None if name in ("iverilog", "vvp")
                               else real(name, *a, **k)))


ROUTING = {
    "nature": "spec_generation",
    "route": "SPEC_TO_RTL",
    "source": "no_context_heuristic",
    "needs_ai_parse": True,
}


def _project(tmp_path: Path, *, phase1: bool = True) -> Path:
    """A CANONICAL Program candidate, the shape `--solve` leaves behind.

    Two facts of that shape are load-bearing for `cmd_resume`, and both were
    missing from this fixture until 2026-09-02, when the front door landed in
    #2012 and turned eight resume-driven tests here red at once:

      * the project is RUNNER-OWNED, at `<run>/projects/<id>` -- the gate
        derives the project from the run root, exactly as `--solve` and the
        retry/backup paths do, so a project anywhere else is invisible to it;
      * a D1-entry run has been THROUGH Phase 1 and left hash-bound L-docs in
        `phase1/generated_docs/` -- `emit_attestation.phase1_provenance` is
        `{"ran": False}` without them, and a D1 candidate with no provenance
        is refused as non-canonical before any acceptance is written.

    `phase1=False` builds the same candidate minus the L-docs, for the test
    that pins that refusal.
    """
    project = tmp_path / "run" / "projects" / "p1"
    (project / "input").mkdir(parents=True)
    if phase1:
        docs = project / "phase1" / "generated_docs"
        docs.mkdir(parents=True)
        (docs / "L1_DATASHEET.json").write_text(
            '{"schema": 1, "module": "dut"}\n')
    (project / "input" / "phase1_prompt.md").write_text(
        "Design module dut with input a and output y; assign y = a.\n")
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "dut.v").write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n")
    report = project / "reports" / "orchestrator"
    report.mkdir(parents=True)
    (report / "phase2_one_shot.json").write_text(json.dumps({
        "verdict": "PASS",
        "steps": [{
            "name": "rtl_gen", "status": "PASS", "detail": "fixture",
            "extras": {"deterministic_generator": "fixture_emitter"},
        }],
    }))
    return project


def _task(tmp_path: Path) -> tuple[Path, dict, dict]:
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    return run, task, got


def _valid_review(task: dict) -> dict:
    review = {
        "schema": bd._AI_REVIEW_SCHEMA,
        "id": task["id"],
        "prompt_sha256": task["prompt_sha256"],
        "rtl_sha256": task["rtl_sha256"],
        "reviewer": {"kind": "AI", "model": "test-review-model"},
        "blind": {"oracle_accessed": False},
        "routing": {"verdict": "AGREE", "ai_nature": "spec_generation"},
        "semantic_review": {
            "verdict": "PASS", "findings": [],
            "rationale": "Ports and combinational behavior match the prompt.",
        },
    }
    if (task.get("program_verification") or {}).get(
            "functional_confirmation_required") is True:
        review["verification_test"] = _write_direct_assignment_challenge(task)
    return review


def _write_review(task: dict, review: dict) -> None:
    path = Path(task["review_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(review))


def _write_direct_assignment_challenge(task: dict) -> dict:
    source = r"""
module vibeic_ai_challenge_tb;
  reg a;
  wire y;
  dut candidate(.a(a), .y(y));
  initial begin
    a = 1'b0; #1;
    if (y !== 1'b0) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1); end
    a = 1'b1; #1;
    if (y !== 1'b1) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1); end
    $display("VIBEIC_AI_CHALLENGE=PASS");
    $finish;
  end
endmodule
"""
    path = Path(task["challenge_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return {
        "schema": bd._CHALLENGE_SCHEMA,
        "path": str(path.resolve()),
        "sha256": bd._sha256_text(source),
        "top_module": "vibeic_ai_challenge_tb",
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "The test drives both input values and checks direct equality.",
        }],
        "expected_behavior": "Output y must equal input a combinationally.",
        "rationale": (
            "The prompt states a direct assignment, so two exhaustive scalar "
            "vectors establish whether the candidate implements that exact "
            "observable combinational behavior without relying on any oracle."),
    }


def _truth_table_task(tmp_path: Path) -> tuple[Path, dict]:
    """A two-row contract whose AI confirmation exercises only one row."""
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    (project / "input" / "phase1_prompt.md").write_text(
        """Design module dut with this exact interface:
module dut(input wire [7:0] code, output reg [7:0] value);

| input | output |
|---|---|
| 8'hA5 | 8'h11 |
| 8'h3C | 8'hE7 |
""")
    (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(
        """module dut(input wire [7:0] code, output reg [7:0] value);
always @* begin
  case (code)
    8'hA5: value = 8'h11;
    8'h3C: value = 8'hE7;
    default: value = 8'h00;
  endcase
end
endmodule
""")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    return run, task


def _write_one_row_challenge(task: dict) -> dict:
    source = r"""
module vibeic_ai_challenge_tb;
  reg [7:0] code;
  wire [7:0] value;
  dut candidate(.code(code), .value(value));
  initial begin
    code = 8'hA5; #1;
    if (value !== 8'h11) begin
      $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1);
    end
    $display("VIBEIC_AI_CHALLENGE=PASS");
    $finish;
  end
endmodule
"""
    path = Path(task["challenge_path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return {
        "schema": bd._CHALLENGE_SCHEMA,
        "path": str(path.resolve()),
        "sha256": bd._sha256_text(source),
        "top_module": "vibeic_ai_challenge_tb",
        "prompt_evidence": [{
            "excerpt": "| 8'hA5 | 8'h11 |",
            "supports": "The test exercises the first explicit truth-table row.",
        }],
        "expected_behavior": "Input 8'hA5 must produce output 8'h11.",
        "rationale": (
            "The prompt's first truth-table row supplies both the stimulus and "
            "the expected value, so this test checks that row without an oracle."),
    }


@_NEEDS_SIMULATOR
def test_semantic_pass_cannot_leave_a_structural_prompt_obligation_uncovered(
        tmp_path):
    """One passing example is not whole-spec functional confirmation."""
    _, task = _truth_table_task(tmp_path)
    review = _valid_review(task)
    review["verification_test"] = _write_one_row_challenge(task)
    review["semantic_review"]["prompt_evidence"] = [{
        "excerpt": "| 8'hA5 | 8'h11 |",
        "supports": "The review confirms the first explicit table row.",
    }]
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED", verdict
    assert verdict["program_review_coverage"]["blocking_gaps"] == 2
    assert any("structural prompt obligation" in reason
               for reason in verdict["reasons"]), verdict


def _write_defective_inversion_challenge(task: dict) -> dict:
    """A frozen older proof whose assertion contradicts the prompt."""
    source = r"""
module vibeic_ai_challenge_tb;
  reg a;
  wire y;
  dut candidate(.a(a), .y(y));
  initial begin
    a = 1'b0; #1;
    if (y !== 1'b1) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1); end
    a = 1'b1; #1;
    if (y !== 1'b0) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1); end
    $display("VIBEIC_AI_CHALLENGE=PASS");
    $finish;
  end
endmodule
"""
    path = (Path(task["challenge_path"]).parent /
            "inherited-defective-challenge.sv")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return {
        "schema": bd._CHALLENGE_SCHEMA,
        "id": task["id"],
        "path": str(path.resolve()),
        "sha256": bd._sha256_text(source),
        "top_module": "vibeic_ai_challenge_tb",
        "prompt_sha256": task["prompt_sha256"],
        "reviewed_rtl_sha256": "frozen-older-candidate",
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "The old review incorrectly interpreted direct assignment.",
        }],
        "expected_behavior": "The defective test incorrectly expects inversion.",
        "rationale": (
            "This fixture represents a previously frozen challenge whose own "
            "assertions accidentally contradict the exact prompt behavior."),
    }


def _write_invalid_inherited_challenge(task: dict) -> dict:
    """An older test that cannot elaborate because its own binding is broken."""
    source = r"""
module vibeic_ai_challenge_tb;
  wire y;
  dut candidate(.*);
  initial begin
    #1;
    if (y !== 1'b0) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); $fatal(1); end
    $display("VIBEIC_AI_CHALLENGE=PASS");
    $finish;
  end
endmodule
"""
    path = (Path(task["challenge_path"]).parent /
            "inherited-invalid-challenge.sv")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return {
        "schema": bd._CHALLENGE_SCHEMA,
        "id": task["id"],
        "path": str(path.resolve()),
        "sha256": bd._sha256_text(source),
        "top_module": "vibeic_ai_challenge_tb",
        "prompt_sha256": task["prompt_sha256"],
        "reviewed_rtl_sha256": "frozen-older-candidate",
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "The intended old test was meant to check equality.",
        }],
        "expected_behavior": "The older test intended to check direct assignment.",
        "rationale": (
            "This fixture represents an inherited challenge whose wildcard "
            "binding omits the candidate input and therefore cannot elaborate."),
    }


@_NEEDS_SIMULATOR
def test_fresh_ai_can_supersede_a_failing_defective_inherited_challenge(
        tmp_path):
    """A correction is explicit, prompt-bound, executable, and auditable."""
    _, task, _ = _task(tmp_path)
    inherited = _write_defective_inversion_challenge(task)
    task["verification_challenges"] = [inherited]

    review = _valid_review(task)
    review["verification_test"] = _write_direct_assignment_challenge(task)
    review["challenge_supersessions"] = [{
        "schema": "vibeic.benchmark.challenge_supersession.v1",
        "challenge_sha256": inherited["sha256"],
        "rationale": (
            "The inherited test expects inversion even though the prompt states "
            "a direct assignment. The attached replacement exhaustively checks "
            "both values and therefore corrects that earlier test defect."),
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "Direct assignment requires equality, not inversion.",
        }],
    }]
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "ACCEPTED", verdict
    assert verdict["inherited_challenge_results"][0]["status"] == "SUPERSEDED"
    assert verdict["inherited_challenge_results"][0]["original_status"] == "FAIL"
    assert verdict["challenge_supersessions"][0]["challenge_sha256"] == \
        inherited["sha256"]


@_NEEDS_SIMULATOR
def test_fresh_ai_can_supersede_a_structurally_invalid_inherited_challenge(
        tmp_path):
    """A broken old bench is retired only by a passing prompt-bound test."""
    _, task, _ = _task(tmp_path)
    inherited = _write_invalid_inherited_challenge(task)
    task["verification_challenges"] = [inherited]
    review = _valid_review(task)
    review["verification_test"] = _write_direct_assignment_challenge(task)
    review["challenge_supersessions"] = [{
        "schema": "vibeic.benchmark.challenge_supersession.v1",
        "challenge_sha256": inherited["sha256"],
        "rationale": (
            "The inherited wildcard test omits the prompt-required input and "
            "cannot elaborate. The replacement compiles and exhaustively "
            "checks both values of the exact prompt assignment."),
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "The replacement directly checks the stated equality.",
        }],
    }]
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "ACCEPTED", verdict
    result = verdict["inherited_challenge_results"][0]
    assert result["status"] == "SUPERSEDED"
    assert result["original_status"] == "INVALID"
    assert result["reasons"]


@_NEEDS_SIMULATOR
def test_fresh_ai_cannot_supersede_a_passing_inherited_challenge(tmp_path):
    """A replacement cannot erase older evidence that still validly passes."""
    _, task, _ = _task(tmp_path)
    inherited = _write_direct_assignment_challenge(task)
    inherited_path = (Path(task["challenge_path"]).parent /
                      "inherited-passing-challenge.sv")
    inherited_source = (Path(inherited["path"]).read_text()
                        .replace("module vibeic_ai_challenge_tb;",
                                 "// inherited passing proof\n"
                                 "module vibeic_ai_challenge_tb;", 1))
    inherited_path.write_text(inherited_source)
    inherited.update({
        "id": task["id"],
        "path": str(inherited_path.resolve()),
        "sha256": bd._sha256_text(inherited_source),
        "prompt_sha256": task["prompt_sha256"],
        "reviewed_rtl_sha256": "frozen-older-candidate",
    })
    task["verification_challenges"] = [inherited]
    review = _valid_review(task)
    review["verification_test"] = _write_direct_assignment_challenge(task)
    review["challenge_supersessions"] = [{
        "schema": "vibeic.benchmark.challenge_supersession.v1",
        "challenge_sha256": inherited["sha256"],
        "rationale": (
            "This attempted correction is deliberately invalid because the "
            "inherited challenge still compiles and passes the prompt behavior."),
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "The inherited and replacement tests check equality.",
        }],
    }]
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED", verdict
    assert verdict["inherited_challenge_results"][0]["status"] == "PASS"
    assert any("must validly FAIL or be structurally INVALID" in reason
               for reason in verdict["reasons"]), verdict


# --- issue #2033: an inherited test whose expectation the PUBLIC INPUT refutes -
#
# The reported class is real and both of its cases reproduce, but the deadlock
# it claims does not exist: the guard "a still-PASSING inherited challenge cannot
# be superseded" is evaluated against the candidate UNDER REVIEW, not against the
# historical result on the old candidate. On the prompt-correct repair, a test
# whose expectation the public input refutes FAILS -- and a failing inherited
# challenge has always been supersedable with a prompt-bound passing replacement.
# The three tests below pin that both ways, so a later change cannot quietly
# close the path or open it to a test that is merely inconvenient.


def _task_with(tmp_path: Path, prompt: str, rtl: str) -> tuple[Path, dict]:
    """The canonical review task over a caller-supplied prompt and candidate."""
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    (project / "input" / "phase1_prompt.md").write_text(prompt)
    (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(rtl)
    got = bio.collect("rtllm", "p1", project)
    return run, bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")


def _write_challenge(task: dict, name: str, source: str, evidence: list[dict],
                     expected: str, rationale: str,
                     inherited: bool = False) -> dict:
    path = ((Path(task["challenge_path"]).parent / name) if inherited
            else Path(task["challenge_path"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    record = {
        "schema": bd._CHALLENGE_SCHEMA,
        "path": str(path.resolve()),
        "sha256": bd._sha256_text(source),
        "top_module": "vibeic_ai_challenge_tb",
        "prompt_evidence": evidence,
        "expected_behavior": expected,
        "rationale": rationale,
    }
    if inherited:
        record.update({
            "id": task["id"],
            "prompt_sha256": task["prompt_sha256"],
            "reviewed_rtl_sha256": "frozen-older-candidate",
        })
    return record


def _supersession(target: dict, rationale: str, evidence: list[dict]) -> dict:
    return {
        "schema": "vibeic.benchmark.challenge_supersession.v1",
        "challenge_sha256": target["sha256"],
        "rationale": rationale,
        "prompt_evidence": evidence,
    }


_DEFAULTS_PROMPT = """Design module dut with this exact interface:

module dut #(parameter NUM_INTERRUPTS = 4, parameter ADDR_WIDTH = 8)
           (input wire clk, input wire rst_n, output reg [NUM_INTERRUPTS-1:0] mask);

After reset the mask register must hold all ones across its declared width.
"""

_DEFAULTS_EVIDENCE = [
    {"excerpt": "parameter NUM_INTERRUPTS = 4, parameter ADDR_WIDTH = 8",
     "supports": "The public stub declares the default widths the test must use."},
    {"excerpt": "the mask register must hold all ones across its declared width",
     "supports": "The reset value is all ones over the declared default width."},
]


def _defaults_rtl(num_interrupts: int, addr_width: int) -> str:
    return f"""module dut #(parameter NUM_INTERRUPTS = {num_interrupts},
             parameter ADDR_WIDTH = {addr_width})
  (input wire clk, input wire rst_n, output reg [NUM_INTERRUPTS-1:0] mask);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) mask <= {{NUM_INTERRUPTS{{1'b1}}}};
    else mask <= mask;
  end
endmodule
"""


def _defaults_test(body: str) -> str:
    return r"""
module vibeic_ai_challenge_tb;
  localparam N = %s;
  reg clk = 1'b0; reg rst_n = 1'b0;
  wire [N-1:0] mask;
  dut candidate(.clk(clk), .rst_n(rst_n), .mask(mask));
  always #1 clk = ~clk;
  initial begin
    #5 rst_n = 1'b1; #5;
    if (%s) begin
      $display("VIBEIC_AI_CHALLENGE=FAIL mask=%%h", mask); $fatal(1);
    end
    $display("VIBEIC_AI_CHALLENGE=PASS");
    $finish;
  end
endmodule
""" % body


#: The inherited test the issue describes: local N = 8, no parameter override,
#: and an eight-bit expectation the declared default of four refutes.
_OLD_DEFAULTS_TEST = _defaults_test(("8", "mask !== 8'hff"))
#: The prompt-correct replacement: the declared default width, all ones.
_PUBLIC_DEFAULTS_TEST = _defaults_test(("4", "mask !== {N{1'b1}}"))
#: An inherited test the public input SUPPORTS -- it still passes the repair.
_SUPPORTED_DEFAULTS_TEST = _defaults_test(("4", "mask[0] !== 1'b1"))


def _defaults_inherited(task: dict, source: str, name: str, expected: str,
                        rationale: str) -> dict:
    return _write_challenge(task, name, source, _DEFAULTS_EVIDENCE, expected,
                            rationale, inherited=True)


def _defaults_replacement(task: dict) -> dict:
    return _write_challenge(
        task, "replacement.sv", _PUBLIC_DEFAULTS_TEST, _DEFAULTS_EVIDENCE,
        "The default reset mask must be all ones over the declared width.",
        ("The public module stub declares NUM_INTERRUPTS = 4, so the default "
         "reset mask is four ones; this test instantiates the DUT with no "
         "parameter override and checks exactly that declared default."))


@_NEEDS_SIMULATOR
def test_a_parameter_default_contradiction_is_already_supersedable(tmp_path):
    """Issue #2033 case 1, measured end to end on the prompt-correct repair."""
    _, task = _task_with(tmp_path, _DEFAULTS_PROMPT, _defaults_rtl(4, 8))
    inherited = _defaults_inherited(
        task, _OLD_DEFAULTS_TEST, "inherited-old-default-test.sv",
        "The old test requires the default reset mask to equal 8'hff.",
        ("This inherited challenge declares a local N = 8, never passes it as a "
         "DUT parameter override, and then requires the default reset mask to "
         "equal eight ones."))
    task["verification_challenges"] = [inherited]
    review = _valid_review(task)
    review["verification_test"] = _defaults_replacement(task)
    review["challenge_supersessions"] = [_supersession(
        inherited,
        ("The inherited test hard-codes an eight-bit default reset mask while "
         "the public stub declares NUM_INTERRUPTS = 4, so its own expectation "
         "is refuted by the declared public contract it claims to check."),
        _DEFAULTS_EVIDENCE)]
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "ACCEPTED", verdict
    result = verdict["inherited_challenge_results"][0]
    assert result["status"] == "SUPERSEDED"
    #: The historical bytes, the hash and the original runtime result all stay.
    assert result["original_status"] == "FAIL"
    assert verdict["challenge_supersessions"][0]["challenge_sha256"] == \
        inherited["sha256"]
    assert Path(inherited["path"]).read_text() == _OLD_DEFAULTS_TEST


@_NEEDS_SIMULATOR
def test_a_wrong_inherited_expectation_still_blocks_a_silent_repair(tmp_path):
    """Nothing is retired implicitly: without the correction, the repair stops."""
    _, task = _task_with(tmp_path, _DEFAULTS_PROMPT, _defaults_rtl(4, 8))
    inherited = _defaults_inherited(
        task, _OLD_DEFAULTS_TEST, "inherited-old-default-test.sv",
        "The old test requires the default reset mask to equal 8'hff.",
        ("This inherited challenge declares a local N = 8, never passes it as a "
         "DUT parameter override, and then requires the default reset mask to "
         "equal eight ones."))
    task["verification_challenges"] = [inherited]
    review = _valid_review(task)
    review["verification_test"] = _defaults_replacement(task)
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED", verdict
    assert verdict["inherited_challenge_results"][0]["status"] == "FAIL"
    assert any("does not pass every immutable verification test" in reason
               for reason in verdict["reasons"]), verdict


@_NEEDS_SIMULATOR
def test_a_still_passing_inherited_proof_neither_blocks_nor_can_be_retired(
        tmp_path):
    """The mutation: an inconvenient-but-supported proof is not retirable.

    Both halves matter. A passing inherited proof never blocked acceptance in
    the first place, so no repair needs it retired -- and naming it anyway is
    refused. That is what keeps supersession from becoming a general escape
    hatch for any test somebody would rather not satisfy.
    """
    for name, supersede, expected_status in (
            ("not-named", False, "ACCEPTED"),
            ("named", True, "REJECTED")):
        _, task = _task_with(tmp_path / name, _DEFAULTS_PROMPT,
                             _defaults_rtl(4, 8))
        inherited = _defaults_inherited(
            task, _SUPPORTED_DEFAULTS_TEST,
            "inherited-supported-passing-test.sv",
            "The default reset mask bit zero must be one.",
            ("This inherited challenge checks a reset-mask bit the public input "
             "directly requires to be one, so its expectation is supported, not "
             "refuted, by the declared public contract."))
        task["verification_challenges"] = [inherited]
        review = _valid_review(task)
        review["verification_test"] = _defaults_replacement(task)
        if supersede:
            review["challenge_supersessions"] = [_supersession(
                inherited,
                ("This attempted retirement is illegitimate: the inherited test "
                 "still passes and its expectation is supported by the same "
                 "public input the replacement cites, so nothing about it is "
                 "contradicted."),
                _DEFAULTS_EVIDENCE)]
        _write_review(task, review)

        verdict = bd._validate_ai_review(task)
        assert verdict["status"] == expected_status, (name, verdict)
        assert verdict["inherited_challenge_results"][0]["status"] == "PASS"
        if supersede:
            assert any("must validly FAIL or be structurally INVALID" in reason
                       for reason in verdict["reasons"]), verdict


_LATENCY_PROMPT = """Design module dut with this exact interface:

module dut(input wire clk, input wire rst_n, input wire [1:0] cmd,
           input wire cmd_valid, output reg [3:0] out, output reg out_valid);

Raw command 0 selects output 1. The decoded output must become valid exactly
three clock cycles after the command is accepted.
"""

_LATENCY_EVIDENCE = [
    {"excerpt": "Raw command 0 selects output 1",
     "supports": "The public description fixes the decode of raw command zero."},
    {"excerpt": "valid exactly three clock cycles after the command is accepted",
     "supports": "The public description fixes the decode latency at three cycles."},
]


def _latency_rtl(latency: int) -> str:
    return f"""module dut(input wire clk, input wire rst_n, input wire [1:0] cmd,
           input wire cmd_valid, output reg [3:0] out, output reg out_valid);
  localparam LATENCY = {latency};
  reg [7:0] count;
  reg [1:0] held;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      count <= 8'd0; out <= 4'd0; out_valid <= 1'b0; held <= 2'd0;
    end else if (cmd_valid) begin
      held <= cmd; count <= 8'd1; out_valid <= 1'b0;
    end else if (count != 8'd0 && count < LATENCY) begin
      count <= count + 8'd1;
    end else if (count == LATENCY) begin
      count <= 8'd0; out_valid <= 1'b1;
      out <= (held == 2'd0) ? 4'd1 : 4'd0;
    end else begin
      out_valid <= 1'b0;
    end
  end
endmodule
"""


def _latency_test(cycles: int) -> str:
    return r"""
module vibeic_ai_challenge_tb;
  reg clk = 1'b0; reg rst_n = 1'b0; reg [1:0] cmd = 2'd0; reg cmd_valid = 1'b0;
  wire [3:0] out; wire out_valid;
  integer i;
  dut candidate(.clk(clk), .rst_n(rst_n), .cmd(cmd), .cmd_valid(cmd_valid),
                .out(out), .out_valid(out_valid));
  always #1 clk = ~clk;
  initial begin
    @(posedge clk); rst_n = 1'b1;
    @(posedge clk); cmd = 2'd0; cmd_valid = 1'b1;
    @(posedge clk); cmd_valid = 1'b0;
    for (i = 0; i < %d - 1; i = i + 1) begin
      @(posedge clk);
      if (out_valid !== 1'b0) begin
        $display("VIBEIC_AI_CHALLENGE=FAIL early valid at %%0d", i); $fatal(1);
      end
    end
    @(posedge clk); #0;
    if (out_valid !== 1'b1 || out !== 4'd1) begin
      $display("VIBEIC_AI_CHALLENGE=FAIL out=%%0d valid=%%b", out, out_valid);
      $fatal(1);
    end
    $display("VIBEIC_AI_CHALLENGE=PASS");
    $finish;
  end
endmodule
""" % cycles


def test_the_supersession_contract_publishes_the_precondition_it_enforces(
        tmp_path):
    """The reviewer is told the rule BEFORE it is used to reject them.

    Issue #2033 was filed because the published contract said only that a
    supersession target must "contradict the prompt". The precondition the gate
    actually enforces -- that the target must currently FAIL or be structurally
    INVALID on THIS candidate -- lived in one place: the refusal message, which
    you only read once you have already lost the run. A reviewer following the
    contract exactly could therefore name a still-passing challenge and be
    rejected on a criterion that was never advertised.
    """
    _, task, _ = _task(tmp_path)
    shape = task["review_requirements"]["required_envelope"][
        "challenge_supersessions"][0]
    published = shape["_optional_when"]
    #: The old contract already said this much, and it is not enough on its own.
    assert "contradicts the prompt" in published
    #: The precondition the gate enforces must be visible BEFORE the rejection.
    assert "validly FAIL" in published
    assert "structurally INVALID" in published
    #: And the remedy, so a reviewer is not left guessing what to change.
    assert "still PASSES" in published
    assert "must not be named" in published
    #: Every refusal this feature can emit is now published, not just that one.
    #: Audited against the reasons in _challenge_supersessions_from_review:
    #: object shape, schema, naming an inherited sha256, rationale length and
    #: prompt evidence were already published; these two were not.
    assert "at most once" in published
    assert "DIFFERENT test" in published


@_NEEDS_SIMULATOR
def test_the_passing_target_refusal_names_the_remedy(tmp_path):
    """A refusal that does not say what to change is a trap, not a gate."""
    _, task, _ = _task(tmp_path)
    inherited = _write_challenge(
        task, "inherited-supported-passing-test.sv",
        Path(_write_direct_assignment_challenge(task)["path"]).read_text()
        .replace("module vibeic_ai_challenge_tb;",
                 "// inherited passing proof\nmodule vibeic_ai_challenge_tb;", 1),
        [{"excerpt": "assign y = a",
          "supports": "The inherited test checks the stated equality."}],
        "Output y must equal input a.",
        ("This inherited challenge checks exactly the direct assignment the "
         "prompt states, so its expectation is supported by the public input."),
        inherited=True)
    task["verification_challenges"] = [inherited]
    review = _valid_review(task)
    review["verification_test"] = _write_direct_assignment_challenge(task)
    review["challenge_supersessions"] = [_supersession(
        inherited,
        ("This attempted retirement is illegitimate: the inherited test still "
         "passes and its expectation is supported by the same public input the "
         "replacement cites, so nothing about it is contradicted."),
        [{"excerpt": "assign y = a",
          "supports": "The inherited and replacement tests check equality."}])]
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED", verdict
    reason = next(r for r in verdict["reasons"]
                  if "named for supersession" in r)
    #: The rule, then what is true of THIS target, then the action to take.
    assert "still PASSES" in reason
    assert "not blocking acceptance" in reason
    assert "drop it from challenge_supersessions" in reason


def _row_challenge_source(rows: list[tuple[str, str]]) -> str:
    body = "".join(
        "    code = 8'h%s; #1;\n"
        "    if (value !== 8'h%s) begin\n"
        "      $display(\"VIBEIC_AI_CHALLENGE=FAIL\"); $fatal(1);\n"
        "    end\n" % row for row in rows)
    return ("\nmodule vibeic_ai_challenge_tb;\n"
            "  reg [7:0] code; wire [7:0] value;\n"
            "  dut candidate(.code(code), .value(value));\n"
            "  initial begin\n" + body +
            "    $display(\"VIBEIC_AI_CHALLENGE=PASS\");\n"
            "    $finish;\n  end\nendmodule\n")


_ROW1_EVIDENCE = [{"excerpt": "| 8'hA5 | 8'h11 |",
                   "supports": "The test exercises the first truth-table row."}]
_ROW2_EVIDENCE = [{"excerpt": "| 8'h3C | 8'hE7 |",
                   "supports": "The test exercises the second truth-table row."}]


@pytest.mark.parametrize("rows, evidence, expected", [
    ([("A5", "11")], _ROW1_EVIDENCE, "REJECTED"),
    ([("3C", "E7")], _ROW2_EVIDENCE, "REJECTED"),
    ([("A5", "11"), ("3C", "E7")], _ROW1_EVIDENCE + _ROW2_EVIDENCE, "ACCEPTED"),
])
@_NEEDS_SIMULATOR
def test_supersession_cannot_be_used_to_shrink_coverage(
        tmp_path, rows, evidence, expected):
    """Retiring a refuted test does not retire the obligation it carried.

    A superseded challenge leaves the ACTIVE set the structural-obligation gate
    measures, so retirement is the one move that could quietly reduce what a
    candidate must satisfy. It cannot: the replacement must carry every
    obligation forward, including the one the retired test used to cover and
    the ones it never did. Discriminated three ways so the ACCEPTED arm proves
    the two REJECTED arms are about coverage and not about supersession.
    """
    run, task = _truth_table_task(tmp_path)
    wrong = _write_challenge(
        task, "inherited-wrong-row2.sv",
        _row_challenge_source([("3C", "AA")]), _ROW2_EVIDENCE,
        "The old test expects 8'h3C to produce 8'hAA.",
        ("This inherited challenge claims to check the second truth-table row "
         "but requires 8'hAA where the public table states 8'hE7, so its "
         "expectation is refuted by the public input it cites."),
        inherited=True)
    task["verification_challenges"] = [wrong]
    review = _valid_review(task)
    review["verification_test"] = _write_challenge(
        task, "replacement.sv", _row_challenge_source(rows), evidence,
        "The declared truth-table rows must decode as the public table states.",
        ("The public truth table supplies both the stimulus and the expected "
         "value for each row, so this test checks them without any oracle."))
    review["challenge_supersessions"] = [_supersession(
        wrong,
        ("The inherited test requires 8'hAA for input 8'h3C while the public "
         "table states 8'hE7, so its expectation is refuted by the declared "
         "public contract it claims to check."),
        _ROW2_EVIDENCE)]
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == expected, verdict
    #: The retirement itself is legitimate in all three arms; only coverage differs.
    assert verdict["inherited_challenge_results"][0]["status"] == "SUPERSEDED"
    coverage = (verdict.get("program_review_coverage") or {}).get("status")
    if expected == "REJECTED":
        assert coverage == "FAIL", verdict
        assert any("leaves structural prompt obligation" in reason
                   for reason in verdict["reasons"]), verdict
    else:
        assert coverage == "PASS", verdict
        assert not verdict["reasons"], verdict


@pytest.mark.parametrize("greedy, expected", [(False, 0), (True, 2)])
@_NEEDS_SIMULATOR
def test_the_two_challenge_repair_shape_retires_only_the_refuted_test(
        tmp_path, greedy, expected):
    """The shape the dispatcher actually produces, through the real resume.

    After one repair round a task carries the OLD inherited challenges AND the
    fresh challenge that proved the parent wrong, so the issue's own wording --
    "passes the first inherited test but fails this second inherited test" --
    is a TWO-challenge task. Only the refuted one is retirable, and a review
    that greedily names both loses the whole run rather than the extra target.
    Written through `cmd_resume` so the audit record is read back off disk.
    """
    run, task = _task_with(tmp_path, _LATENCY_PROMPT, _latency_rtl(3))
    wrong = _write_challenge(
        task, "inherited-six-cycle-test.sv", _latency_test(6),
        _LATENCY_EVIDENCE, "The old test accepts a six-cycle decode latency.",
        ("This inherited challenge waits six clock cycles for the decoded "
         "output even though the public description states three."),
        inherited=True)
    proving = _write_challenge(
        task, "inherited-proving-three-cycle.sv",
        "// the challenge that proved the parent candidate wrong\n"
        + _latency_test(3),
        _LATENCY_EVIDENCE,
        "Raw command 0 must produce output 1 exactly three cycles later.",
        ("This inherited challenge is the prompt-derived test that proved the "
         "parent candidate wrong, carried onto the repair by the dispatcher."),
        inherited=True)
    task["verification_challenges"] = [proving, wrong]
    review = _valid_review(task)
    review["verification_test"] = _write_challenge(
        task, "replacement.sv", _latency_test(3), _LATENCY_EVIDENCE,
        "Raw command 0 must produce output 1 exactly three cycles later.",
        ("The public description states a three-cycle decode latency, so this "
         "test drives raw command 0 and checks the output is invalid before, "
         "and correct at, the third cycle."))
    review["challenge_supersessions"] = [
        _supersession(
            target,
            ("The inherited test waits six cycles for the decoded output while "
             "the public description states exactly three, so its expectation "
             "is refuted by the declared public contract it claims to check."),
            _LATENCY_EVIDENCE)
        for target in ([wrong, proving] if greedy else [wrong])]
    _write_review(task, review)
    _solve_report(run, task)

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == expected
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    outcome = acceptance["review_outcomes"][0]
    results = outcome["inherited_challenge_results"]
    if greedy:
        assert acceptance["status"] == "PENDING"
        assert acceptance["accepted_ids"] == []
        assert outcome["status"] == "REJECTED"
        assert any("must validly FAIL or be structurally INVALID" in reason
                   for reason in outcome["reasons"]), outcome
    else:
        assert acceptance["status"] == "COMPLETE"
        assert acceptance["accepted_ids"] == ["p1"]
        assert outcome["status"] == "ACCEPTED"
        #: The proof that still holds is untouched; only the refuted one moves.
        assert [r["status"] for r in results] == ["PASS", "SUPERSEDED"]
        assert results[1]["original_status"] == "FAIL"
        assert results[1]["supersession"]["rationale"]
        assert results[1]["supersession"]["prompt_evidence"]
    #: Superseded is not deleted: the bytes and the hash both survive on disk.
    assert Path(wrong["path"]).read_text() == _latency_test(6)
    assert bd._sha256_text(Path(wrong["path"]).read_text()) == wrong["sha256"]


@_NEEDS_SIMULATOR
def test_a_passing_inherited_proof_does_not_block_the_repair_handoff(tmp_path):
    """The entry to the same loop, on the wrong candidate.

    Here the contradicting inherited test still PASSES, because it was written
    for this candidate. If that PASS were treated as agreement with the review,
    a proven finding could not enter repair at all -- which is the shape issue
    #2033 believed it was seeing. It is REPAIR_REQUIRED, not REJECTED.
    """
    _, task = _task_with(tmp_path, _LATENCY_PROMPT, _latency_rtl(6))
    inherited = _write_challenge(
        task, "inherited-six-cycle-test.sv", _latency_test(6),
        _LATENCY_EVIDENCE, "The old test accepts a six-cycle decode latency.",
        ("This inherited challenge waits six clock cycles for the decoded "
         "output even though the public description states three."),
        inherited=True)
    task["verification_challenges"] = [inherited]
    review = _valid_review(task)
    review["verification_test"] = _write_challenge(
        task, "replacement.sv", _latency_test(3), _LATENCY_EVIDENCE,
        "Raw command 0 must produce output 1 exactly three cycles later.",
        ("The public description states a three-cycle decode latency, so this "
         "test drives raw command 0 and checks the output is invalid before, "
         "and correct at, the third cycle."))
    review["semantic_review"] = {
        "verdict": "FAIL",
        "findings": [{"issue": "out_valid rises six cycles after the command, "
                               "not the three the description states"}],
        "prompt_evidence": _LATENCY_EVIDENCE,
        "rationale": ("The candidate takes six cycles to raise out_valid while "
                      "the public description states exactly three; the attached "
                      "test demonstrates the mismatch without any oracle."),
    }
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REPAIR_REQUIRED", verdict
    assert verdict["challenge_result"]["status"] == "FAIL"
    assert verdict["inherited_challenge_results"][0]["status"] == "PASS"
    assert not verdict["reasons"], verdict


@_NEEDS_SIMULATOR
def test_a_decode_latency_contradiction_is_already_supersedable(tmp_path):
    """Issue #2033 case 2: six inherited cycles against three declared ones."""
    _, task = _task_with(tmp_path, _LATENCY_PROMPT, _latency_rtl(3))
    inherited = _write_challenge(
        task, "inherited-six-cycle-test.sv", _latency_test(6),
        _LATENCY_EVIDENCE, "The old test accepts a six-cycle decode latency.",
        ("This inherited challenge waits six clock cycles for the decoded "
         "output even though the public description states three, so its own "
         "expectation contradicts the declared latency it claims to check."),
        inherited=True)
    task["verification_challenges"] = [inherited]
    review = _valid_review(task)
    review["verification_test"] = _write_challenge(
        task, "replacement.sv", _latency_test(3), _LATENCY_EVIDENCE,
        "Raw command 0 must produce output 1 exactly three cycles later.",
        ("The public description maps raw command 0 to output 1 and states a "
         "three-cycle decode latency, so this test drives that command and "
         "checks the output is invalid before, and correct at, the third cycle."))
    review["challenge_supersessions"] = [_supersession(
        inherited,
        ("The inherited test waits six cycles for the decoded output while the "
         "public description states exactly three, so the inherited expectation "
         "is refuted by the declared public contract it claims to check."),
        _LATENCY_EVIDENCE)]
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "ACCEPTED", verdict
    result = verdict["inherited_challenge_results"][0]
    assert result["status"] == "SUPERSEDED"
    assert result["original_status"] == "FAIL"
    assert Path(inherited["path"]).read_text() == _latency_test(6)

@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda item: item.update(challenge_sha256="0" * 64),
         "must name an inherited challenge"),
        (lambda item: item.update(prompt_evidence=[]),
         "needs prompt-bound evidence"),
        (lambda item: item.update(rationale="too short"),
         "rationale must be at least 80"),
    ],
)
@_NEEDS_SIMULATOR
def test_challenge_supersession_fails_closed_without_bound_evidence(
        tmp_path, mutate, expected):
    _, task, _ = _task(tmp_path)
    inherited = _write_defective_inversion_challenge(task)
    task["verification_challenges"] = [inherited]
    review = _valid_review(task)
    review["verification_test"] = _write_direct_assignment_challenge(task)
    item = {
        "schema": "vibeic.benchmark.challenge_supersession.v1",
        "challenge_sha256": inherited["sha256"],
        "rationale": (
            "The inherited assertion requires inversion while the prompt "
            "requires equality; the replacement test exhaustively checks the "
            "prompt behavior and corrects that earlier test defect."),
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "The exact prompt requires direct equality.",
        }],
    }
    mutate(item)
    review["challenge_supersessions"] = [item]
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any(expected in reason for reason in verdict["reasons"]), verdict


def _proven_fail_review(task: dict) -> dict:
    review = _valid_review(task)
    review["semantic_review"] = {
        "verdict": "FAIL",
        "findings": [{"issue": "output does not directly track input"}],
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "The prompt explicitly requests a direct assignment.",
        }],
        "rationale": (
            "The candidate inverts the input instead of implementing the direct "
            "assignment stated by the prompt; the attached exhaustive one-bit "
            "test demonstrates the mismatch without any benchmark oracle."),
    }
    review["verification_test"] = _write_direct_assignment_challenge(task)
    return review


def _write_ai_repair_record(run: Path, task: dict, challenge: dict) -> dict:
    repaired_hash = bd._sha256_text(bd._candidate_text(
        bd._rtl_files(Path(task["project"]))))
    record = {
        "schema": bd._AI_REPAIR_RECORD_SCHEMA,
        "id": task["id"],
        "prompt_sha256": task["prompt_sha256"],
        "parent_rtl_sha256": task["rtl_sha256"],
        "repaired_rtl_sha256": repaired_hash,
        "challenge_sha256": challenge["sha256"],
        "author": {"kind": "AI", "model": "test-repair-model"},
        "oracle_accessed": False,
        "rationale": (
            "Replace the proven inversion with the prompt-required direct "
            "assignment, then re-run the immutable challenge."),
    }
    path = bd._repair_record_path(run, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return record


def _solve_report(run: Path, task: dict) -> None:
    result = {
        "id": task["id"], "ok": True, "candidate_ready": True,
        "accepted": False, "entry": "D1", "evidence": "RTL_SIM",
        "exit": "8", "routing_verdict": ROUTING,
        "candidate_origin": "PROGRAM", "ai_repair_required": False,
        "awaiting_ai": True, "awaiting_ai_review": True,
        "awaiting_ai_backup": False,
    }
    (run / "solve_report.json").write_text(json.dumps({
        "bench": "rtllm", "format": "rtllm", "total": 1,
        "solved": 1, "accepted": 0,
        "acceptance_policy": {
            "required": True,
            "review_task_schema": bd._REVIEW_TASK_SCHEMA,
            "review_schema": bd._AI_REVIEW_SCHEMA,
        },
        "results": [result],
    }))
    bd._write_jsonl(run / bd._REVIEW_WORKLIST, [task])
    bd._write_jsonl(run / bd._BACKUP_WORKLIST, [])


def test_valid_blind_ai_review_is_hash_bound_and_accepted(tmp_path):
    run, task, got = _task(tmp_path)
    _solve_report(run, task)
    _write_review(task, _valid_review(task))

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 0
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "COMPLETE"
    assert acceptance["accepted_ids"] == ["p1"]
    response = json.loads(Path(task["response_path"]).read_text())
    assert response["completion"] == got["completion"]
    solve = json.loads((run / "solve_report.json").read_text())
    item = solve["results"][0]
    route_review = item["phases"]["phase1_routing"][
        "ai_decided_routing_review"]
    assert route_review["actor"] == "test-review-model"
    assert route_review["authority"] == "FINAL_SEMANTIC_AUTHORITY"
    assert route_review["status"] == "ACCEPTED"
    assert route_review["verdict"] == "AGREE"
    assert item["phases"]["phase3_verifying"]["ai_semantic_review"][
        "verdict"] == "PASS"
    ai_review = item["phases"]["phase3_verifying"]["ai_semantic_review"]
    assert ai_review["program_functional_evidence"] == "NOT_RECORDED"
    assert ai_review["functional_confirmation_required"] is True
    assert ai_review["functional_confirmation_result"] == "PASS"
    assert ai_review["functional_confirmation_challenge_sha256"]
    assert solve["four_phase_summary"]["phase1_ai_review_models"] == {
        "test-review-model": 1}
    assert solve["four_phase_summary"]["phase2_candidate_origin"] == {
        "PROGRAM": 1}
    assert solve["four_phase_summary"]["phase3_ai_semantic_verdict"] == {
        "PASS": 1}
    bd._require_program_first_ai_acceptance(run)

    # A post-review byte change invalidates both the review and score gate.
    Path(task["rtl_paths"][0]).write_text("module dut(); endmodule\n")
    with pytest.raises(SystemExit, match="Program First.*acceptance BLOCKED"):
        bd._require_program_first_ai_acceptance(run)


def test_resume_refreshes_only_program_owned_obligations_for_unchanged_task(
        tmp_path):
    run, task, _ = _task(tmp_path)
    current = copy.deepcopy(task["program_review_obligations"])
    stale = copy.deepcopy(current)
    stale["obligation_count"] += 1
    stale["obligations"].append({
        "id": "obsolete-program-false-positive",
        "kind": "analog_converter",
        "requirement": "obsolete Program-derived obligation",
        "evidence": "ADC token was formerly over-classified",
        "coverage_tokens": ["adc"],
    })
    stale["sha256"] = "0" * 64
    task["program_review_obligations"] = stale
    _solve_report(run, task)
    _write_review(task, _valid_review(task))

    assert bd._validate_ai_review(task)["status"] == "REJECTED"
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 0

    refreshed = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert refreshed["program_review_obligations"] == current
    audit = refreshed["program_review_obligation_refreshes"]
    assert audit == [{
        "schema": "vibeic.benchmark.program_review_obligations_refresh.v1",
        "basis": "UNCHANGED_HASH_BOUND_PROMPT_AND_CANDIDATE",
        "prior_contract": stale,
        "replacement_sha256": current["sha256"],
    }]
    assert json.loads((run / bd._ACCEPTANCE_REPORT).read_text())[
        "status"] == "COMPLETE"


def test_program_obligation_refresh_refuses_changed_prompt_or_candidate(
        tmp_path):
    _, prompt_task, _ = _task(tmp_path / "prompt-case")
    prompt_task["program_review_obligations"] = {"stale": True}
    Path(prompt_task["prompt_path"]).write_text("changed prompt\n")
    assert bd._refresh_program_review_obligations(prompt_task) is False
    assert prompt_task["program_review_obligations"] == {"stale": True}

    _, rtl_task, _ = _task(tmp_path / "rtl-case")
    rtl_task["program_review_obligations"] = {"stale": True}
    Path(rtl_task["rtl_paths"][0]).write_text("module changed(); endmodule\n")
    assert bd._refresh_program_review_obligations(rtl_task) is False
    assert rtl_task["program_review_obligations"] == {"stale": True}


def test_static_ai_pass_is_blocked_without_program_functional_evidence(tmp_path):
    _, task, _ = _task(tmp_path)
    review = _valid_review(task)
    review.pop("verification_test", None)
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any("semantic PASS without Program functional evidence" in reason
               for reason in verdict["reasons"])


def test_program_functional_pass_does_not_require_a_duplicate_ai_test(tmp_path):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM",
        program_phases={"phase3_verifying": {"ran": {
            "step4_functional_evidence": "PASS"}}})
    review = _valid_review(task)
    assert "verification_test" not in review
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "ACCEPTED"
    assert verdict["challenge_result"] is None


@_NEEDS_SIMULATOR
def test_prompt_derived_confirmation_can_close_missing_program_evidence(tmp_path):
    _, task, _ = _task(tmp_path)
    _write_review(task, _valid_review(task))

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "ACCEPTED"
    assert verdict["challenge_result"]["status"] == "PASS"
    assert verdict["verified_challenge"]["prompt_evidence"]


@_NEEDS_SIMULATOR
def test_semantic_pass_is_rejected_when_its_confirmation_fails(tmp_path):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    _write_review(task, _valid_review(task))

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert verdict["challenge_result"]["status"] == "FAIL"
    assert any("AI semantic PASS is not confirmed" in reason
               for reason in verdict["reasons"])


def test_unrunnable_pass_confirmation_is_not_measured(tmp_path, monkeypatch):
    _, task, _ = _task(tmp_path)
    _write_review(task, _valid_review(task))
    _no_simulator(monkeypatch)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == bd._NOT_MEASURED
    assert verdict["reasons"] == []
    assert any("PASS confirmation could not be RUN" in reason
               for reason in verdict["unmeasurable"])


def test_supplied_rtl_accepts_only_explicit_step2_reentry(tmp_path):
    project = _project(tmp_path)
    report = project / "reports" / "orchestrator" / "phase2_one_shot.json"
    report.write_text(json.dumps({
        "verdict": "PASS",
        "steps": [{
            "name": "rtl_gen", "status": "SKIPPED-BY-ENTRY",
            "detail": "run declared --entry-step 2",
        }],
    }))

    ordinary = bio.collect("rtllm", "p1", project)
    supplied = bio.collect("rtllm", "p1", project, supplied_rtl=True)

    assert ordinary["ok"] is False
    assert supplied["ok"] is True
    assert supplied["rtl_gen"] == "SKIPPED-BY-ENTRY"
    assert supplied["supplied_rtl"] is True


@_NEEDS_SIMULATOR
def test_ai_repair_reenters_at_validation_without_regeneration(
        tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    working_rtl = project / "phase2" / "stage1" / "rtl" / "dut.v"
    working_rtl.write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    _solve_report(run, task)
    _write_review(task, _proven_fail_review(task))

    # First resume proves the Program candidate wrong and emits the repair task.
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    repairs = bd._read_jsonl(run / bd._REPAIR_WORKLIST)
    assert repairs[0]["status"] == "AI_SEMANTIC_REPAIR_REQUIRED"
    assert repairs[0]["challenge_result"]["status"] == "FAIL"

    working_rtl.write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n")
    _write_ai_repair_record(
        run, task, bd._validate_ai_review(task)["verified_challenge"])
    seen = []
    real_run = bd.subprocess.run

    def fake_run(argv, *args, **kwargs):
        if "vibe_ic_one_shot_runner.py" not in " ".join(str(v) for v in argv):
            return real_run(argv, *args, **kwargs)
        seen.append(argv)
        report = (Path(task["project"]) / "reports" / "orchestrator" /
                  "phase2_one_shot.json")
        report.write_text(json.dumps({
            "verdict": "PASS",
            "steps": [{
                "name": "rtl_gen", "status": "SKIPPED-BY-ENTRY",
                "detail": "run declared --entry-step 2",
            }],
        }))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("subprocess.run", fake_run)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    assert seen and seen[0][-2:] == ["--entry-step", "2"]
    solve = json.loads((run / "solve_report.json").read_text())
    assert solve["results"][0]["candidate_origin"] == "AI_REPAIR"
    assert solve["results"][0]["candidate_ready"] is True
    refreshed = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert refreshed["rtl_sha256"] != task["rtl_sha256"]
    assert len(refreshed["verification_challenges"]) == 1

    # The next resume must accept the independently reviewed repair even
    # though rtl_gen correctly remains SKIPPED-BY-ENTRY from re-entry step 2.
    _write_review(refreshed, _valid_review(refreshed))
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 0
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "COMPLETE"
    assert acceptance["accepted_ids"] == ["p1"]
    response = json.loads(Path(refreshed["response_path"]).read_text())
    assert "assign y = a" in response["completion"]
    captures = bd._read_jsonl(run / bd._ENHANCEMENT_WORKLIST)
    recovery = next(row for row in captures
                    if row["status"] ==
                    "VERIFIED_AI_RECOVERY_READY_FOR_PROGRAM_CAPTURE")
    assert recovery["program_candidate_snapshot"]["rtl_sha256"] == \
        task["rtl_sha256"]
    assert recovery["repaired_candidate_snapshot"]["rtl_sha256"] == \
        refreshed["rtl_sha256"]
    assert recovery["repair_challenge_results"][0]["status"] == "PASS"
    assert recovery["repair_provenance"]["author"]["model"] == \
        "test-repair-model"
    phases = json.loads((run / "solve_report.json").read_text())["results"][0][
        "phases"]
    assert phases["phase4_debugging"]["ai_semantic_repair"]["actor"] == \
        "test-repair-model"


@_NEEDS_SIMULATOR
def test_ai_resigns_exact_candidate_after_program_gate_normalization(tmp_path):
    run, task, _ = _task(tmp_path)
    project = Path(task["project"])
    working_rtl = project / "phase2" / "stage1" / "rtl" / "dut.v"
    review = _proven_fail_review(task)
    _write_review(task, review)
    challenge = bd._validate_ai_review(task)["verified_challenge"]

    working_rtl.write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n")
    record = _write_ai_repair_record(run, task, challenge)
    record_path = bd._repair_record_path(run, task)
    repair_provenance, reasons = bd._validate_repair_record(
        record_path, task, record["repaired_rtl_sha256"], challenge)
    assert reasons == []

    # Model a deterministic PROGRAM-gate normalization after the AI supplied
    # its first repair.  The old signature must not authorize the new bytes.
    working_rtl.write_text(
        "module dut(input wire a, output wire y); "
        "assign y = a & 1'b1; endmodule\n")
    got = bio.collect("rtllm", "p1", project, supplied_rtl=True)
    final_task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "AI_REPAIR",
        verification_challenges=[challenge],
        program_candidate=task["candidate_snapshot"],
        repair_provenance=repair_provenance)
    rebound, reasons = bd._refresh_final_repair_provenance(final_task)
    assert rebound is None
    assert any("repaired_rtl_sha256" in reason for reason in reasons)

    final_hash = final_task["rtl_sha256"]
    record["pre_gate_ai_rtl_sha256"] = record["repaired_rtl_sha256"]
    record["repaired_rtl_sha256"] = final_hash
    record_path.write_text(json.dumps(record))
    rebound, reasons = bd._refresh_final_repair_provenance(final_task)
    assert reasons == []
    assert rebound["repaired_rtl_sha256"] == final_hash
    assert rebound["pre_gate_ai_rtl_sha256"] != final_hash


def _normalized_repair_with_existing_review(tmp_path, semantic_verdict="PASS"):
    """Synthetic gate-normalized repair, re-signed after its review exists."""
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    working_rtl = project / "phase2" / "stage1" / "rtl" / "dut.v"
    working_rtl.write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    parent = bd._make_ai_review_task(
        "p1", project, bio.collect("rtllm", "p1", project), ROUTING, 0,
        run, "PROGRAM")
    parent_review = _proven_fail_review(parent)
    # The inherited proof exposes inversion at zero. A subsequent full review
    # can discover a different defect at one without rewriting that history.
    challenge_path = Path(parent_review["verification_test"]["path"])
    source = challenge_path.read_text().replace(
        "    a = 1'b1; #1;\n"
        '    if (y !== 1\'b1) begin $display("VIBEIC_AI_CHALLENGE=FAIL"); '
        "$fatal(1); end\n", "")
    challenge_path.write_text(source)
    parent_review["verification_test"].update({
        "sha256": bd._sha256_text(source),
        "expected_behavior": "Output y must be zero when input a is zero.",
        "rationale": (
            "The prompt requires direct assignment, so driving zero must "
            "produce zero. This single prompt-derived vector exposes the "
            "inversion defect without claiming exhaustive input coverage."),
    })
    _write_review(parent, parent_review)
    verdict = bd._validate_ai_review(parent)
    assert verdict["status"] == "REPAIR_REQUIRED", verdict
    challenge = verdict["verified_challenge"]

    working_rtl.write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n")
    record = _write_ai_repair_record(run, parent, challenge)
    record_path = bd._repair_record_path(run, parent)
    provenance, reasons = bd._validate_repair_record(
        record_path, parent, record["repaired_rtl_sha256"], challenge)
    assert reasons == []
    final_expression = "a & 1'b1" if semantic_verdict == "PASS" else "1'b0"
    working_rtl.write_text(
        "module dut(input wire a, output wire y); "
        f"assign y = {final_expression}; endmodule\n")
    task = bd._make_ai_review_task(
        "p1", project, bio.collect("rtllm", "p1", project, supplied_rtl=True),
        ROUTING, 0, run, "AI_REPAIR", verification_challenges=[challenge],
        program_candidate=parent["candidate_snapshot"],
        repair_parent_candidate=parent["candidate_snapshot"],
        repair_provenance=provenance)
    _write_review(task, (_valid_review(task) if semantic_verdict == "PASS"
                         else _proven_fail_review(task)))
    record["pre_gate_ai_rtl_sha256"] = record["repaired_rtl_sha256"]
    record["repaired_rtl_sha256"] = task["rtl_sha256"]
    record_path.write_text(json.dumps(record))
    _solve_report(run, task)
    solve_path = run / "solve_report.json"
    solve = json.loads(solve_path.read_text())
    solve["results"][0]["candidate_origin"] = "AI_REPAIR"
    solve_path.write_text(json.dumps(solve))
    return run, task, record_path


@_NEEDS_SIMULATOR
@pytest.mark.parametrize("semantic_verdict,expected_status,expected_rc", [
    ("PASS", "ACCEPTED", 0),
    ("FAIL", "REPAIR_REQUIRED", 2),
])
def test_resume_rebinds_final_provenance_with_existing_review(
        tmp_path, semantic_verdict, expected_status, expected_rc):
    run, task, record_path = _normalized_repair_with_existing_review(
        tmp_path, semantic_verdict)
    preserved = {str(path): path.read_bytes() for path in [
        Path(task["review_path"]), record_path,
        *[Path(p) for p in task["rtl_paths"] + task["working_rtl_paths"]],
        *[Path(c["path"]) for c in task["verification_challenges"]],
    ]}
    assert bd._validate_ai_review(task)["status"] == "REJECTED"

    rc = bd.cmd_resume("rtllm", "/unused", str(run))
    refreshed = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    verdict = bd._validate_ai_review(refreshed)
    assert verdict["status"] == expected_status, verdict
    assert rc == expected_rc
    assert bd._validate_embedded_repair_provenance(refreshed) == []
    assert refreshed["repair_provenance"]["repaired_rtl_sha256"] == \
        task["rtl_sha256"]
    assert refreshed["repair_provenance"]["pre_gate_ai_rtl_sha256"] == \
        task["repair_provenance"]["repaired_rtl_sha256"]
    assert {k: v for k, v in refreshed.items() if k != "repair_provenance"} == \
        {k: v for k, v in task.items() if k != "repair_provenance"}
    assert all(Path(path).read_bytes() == raw for path, raw in preserved.items())
    assert [r["status"] for r in verdict["inherited_challenge_results"]] == ["PASS"]
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["accepted_ids"] == (["p1"] if expected_rc == 0 else [])
    if semantic_verdict == "FAIL":
        assert verdict["challenge_result"]["status"] == "FAIL"
        repairs = bd._read_jsonl(run / bd._REPAIR_WORKLIST)
        assert [r["status"] for r in repairs] == ["AI_SEMANTIC_REPAIR_REQUIRED"]
        assert not Path(task["response_path"]).exists()


@_NEEDS_SIMULATOR
@pytest.mark.parametrize("field", [
    "schema", "id", "prompt_sha256", "parent_rtl_sha256",
    "repaired_rtl_sha256", "challenge_sha256", "author", "oracle_accessed",
    "rationale", "unreadable", "absent",
])
def test_resume_existing_review_cannot_rebind_invalid_repair_record(tmp_path, field):
    run, task, record_path = _normalized_repair_with_existing_review(tmp_path)
    record = json.loads(record_path.read_text())
    if field == "absent":
        record_path.unlink()
    elif field == "unreadable":
        record_path.write_text("{")
    else:
        record[field] = ({"kind": "AI", "model": "unknown"}
                         if field == "author" else "invalid")
        record_path.write_text(json.dumps(record))
    review_bytes = Path(task["review_path"]).read_bytes()

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    refreshed = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert refreshed["repair_provenance"] == task["repair_provenance"]
    assert bd._validate_ai_review(refreshed)["status"] == "REJECTED"
    assert Path(task["review_path"]).read_bytes() == review_bytes
    assert not Path(task["response_path"]).exists()
    assert json.loads((run / bd._ACCEPTANCE_REPORT).read_text())["accepted_ids"] == []


@_NEEDS_SIMULATOR
@pytest.mark.parametrize("changed", [
    "review_prompt", "review_rtl", "prompt", "frozen_rtl", "working_rtl",
    "inherited_challenge",
])
def test_resume_provenance_refresh_cannot_authorize_changed_review_material(
        tmp_path, changed):
    run, task, _ = _normalized_repair_with_existing_review(tmp_path)
    if changed.startswith("review_"):
        review = json.loads(Path(task["review_path"]).read_text())
        review[changed.removeprefix("review_") + "_sha256"] = "0" * 64
        _write_review(task, review)
    else:
        path = {
            "prompt": task["prompt_path"],
            "frozen_rtl": task["rtl_paths"][0],
            "working_rtl": task["working_rtl_paths"][0],
            "inherited_challenge": task["verification_challenges"][0]["path"],
        }[changed]
        Path(path).write_text(Path(path).read_text() + "\n// changed\n")
    review_bytes = Path(task["review_path"]).read_bytes()

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    refreshed = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert refreshed["verification_challenges"] == task["verification_challenges"]
    assert Path(task["review_path"]).read_bytes() == review_bytes
    assert not Path(task["response_path"]).exists()
    assert json.loads((run / bd._ACCEPTANCE_REPORT).read_text())["accepted_ids"] == []


@_NEEDS_SIMULATOR
def test_proven_ai_edit_cannot_reenter_without_repair_author_record(
        tmp_path, monkeypatch):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    rtl = project / "phase2" / "stage1" / "rtl" / "dut.v"
    rtl.write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    _solve_report(run, task)
    _write_review(task, _proven_fail_review(task))
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2

    rtl.write_text(
        "module dut(input wire a, output wire y); assign y = a; endmodule\n")

    real_run = bd.subprocess.run

    def must_not_run(argv, *args, **kwargs):
        if "vibe_ic_one_shot_runner.py" in " ".join(str(v) for v in argv):
            raise AssertionError(
                "unattributed AI repair must not enter Program gates")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr("subprocess.run", must_not_run)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    repair = bd._read_jsonl(run / bd._REPAIR_WORKLIST)[0]
    assert repair["status"] == "AI_REPAIR_PROVENANCE_REQUIRED"
    assert repair["repaired_rtl_sha256"] == bd._sha256_text(
        bd._candidate_text([rtl]))
    assert not Path(task["response_path"]).exists()


def test_missing_review_stays_pending_and_writes_no_response(tmp_path):
    run, task, _ = _task(tmp_path)
    _solve_report(run, task)

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "PENDING"
    assert acceptance["pending_review"] == 1
    assert not Path(task["response_path"]).exists()


def test_ai_cannot_edit_program_candidate_before_proving_a_finding(
        tmp_path, monkeypatch):
    run, task, _ = _task(tmp_path)
    _solve_report(run, task)
    Path(task["working_rtl_paths"][0]).write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")

    def must_not_run(*args, **kwargs):
        raise AssertionError("unproven AI edit must not enter Program gates")

    monkeypatch.setattr("subprocess.run", must_not_run)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    repair = bd._read_jsonl(run / bd._REPAIR_WORKLIST)[0]
    assert repair["status"] == "UNPROVEN_AI_EDIT_REJECTED"
    assert repair["restore_from"] == task["candidate_snapshot"]["manifest_path"]
    assert not Path(task["response_path"]).exists()


@_NEEDS_SIMULATOR
def test_repair_must_pass_the_same_immutable_challenge(tmp_path):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    rtl = project / "phase2" / "stage1" / "rtl" / "dut.v"
    rtl.write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    original = bio.collect("rtllm", "p1", project)
    program_task = bd._make_ai_review_task(
        "p1", project, original, ROUTING, 0, run, "PROGRAM")
    _write_review(program_task, _proven_fail_review(program_task))
    proven = bd._validate_ai_review(program_task)
    assert proven["status"] == "REPAIR_REQUIRED"

    # This edit differs from Program but still fails the exact same a=0/a=1 test.
    rtl.write_text(
        "module dut(input wire a, output wire y); assign y = 1'b0; endmodule\n")
    repair_payload = bio.collect("rtllm", "p1", project, supplied_rtl=True)
    repair_task = bd._make_ai_review_task(
        "p1", project, repair_payload, ROUTING, 0, run, "AI_REPAIR",
        verification_challenges=[proven["verified_challenge"]],
        program_candidate=program_task["candidate_snapshot"])
    _write_review(repair_task, _valid_review(repair_task))
    verdict = bd._validate_ai_review(repair_task)
    assert verdict["status"] == "REJECTED"
    assert verdict["inherited_challenge_results"][0]["status"] == "FAIL"
    assert any("immutable verification" in reason for reason in verdict["reasons"])


@_NEEDS_SIMULATOR
def test_fresh_ai_fail_plus_inherited_fail_requests_another_repair(tmp_path):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    review = _proven_fail_review(task)
    _write_review(task, review)
    inherited = bd._validate_ai_review(task)["verified_challenge"]
    task["verification_challenges"] = [inherited]

    # Both the fresh prompt-bound challenge and the immutable inherited one
    # reject this candidate.  Agreement that it is still wrong authorizes the
    # next repair; only an attempted PASS over the inherited failure is invalid.
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REPAIR_REQUIRED"
    assert verdict["challenge_result"]["status"] == "FAIL"
    assert verdict["inherited_challenge_results"][0]["status"] == "FAIL"
    assert verdict["reasons"] == []


@_NEEDS_SIMULATOR
def test_fresh_proven_fail_can_repair_past_invalid_inherited_test(tmp_path):
    """A broken old test cannot deadlock a separately proven RTL repair."""
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    task["verification_challenges"] = [
        _write_invalid_inherited_challenge(task)]
    _write_review(task, _proven_fail_review(task))

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REPAIR_REQUIRED", verdict
    assert verdict["challenge_result"]["status"] == "FAIL"
    inherited = verdict["inherited_challenge_results"][0]
    assert inherited["status"] == "INVALID"
    assert inherited["nonblocking_during_proven_repair"] is True
    assert inherited["required_on_fresh_review"] is True
    assert verdict["reasons"] == []


@_NEEDS_SIMULATOR
def test_invalid_inherited_test_still_blocks_semantic_pass(tmp_path):
    """Repair progress is allowed; acceptance still fails closed."""
    _, task, _ = _task(tmp_path)
    task["verification_challenges"] = [
        _write_invalid_inherited_challenge(task)]
    _write_review(task, _valid_review(task))

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED", verdict
    inherited = verdict["inherited_challenge_results"][0]
    assert inherited["status"] == "INVALID"
    assert "nonblocking_during_proven_repair" not in inherited
    assert any("immutable verification" in reason
               for reason in verdict["reasons"]), verdict


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda r: r["reviewer"].update(model="unknown"), "name the AI model"),
        (lambda r: r["blind"].update(oracle_accessed=True), "must be false"),
        (lambda r: r["routing"].update(verdict="DISAGREE"),
         "AGREE or OVERRIDE_PROGRAM"),
        (lambda r: r["semantic_review"].update(verdict="MAYBE"),
         "PASS or FAIL"),
        (lambda r: r.update(rtl_sha256="0" * 64), "stale or wrong"),
    ],
)
def test_review_contract_rejects_fake_or_disagreeing_ai_rail(
        tmp_path, mutate, expected):
    _, task, _ = _task(tmp_path)
    review = copy.deepcopy(_valid_review(task))
    mutate(review)
    _write_review(task, review)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any(expected in reason for reason in verdict["reasons"])


def test_complete_label_cannot_omit_a_problem(tmp_path):
    run, task, _ = _task(tmp_path)
    _solve_report(run, task)
    _write_review(task, _valid_review(task))
    (run / bd._ACCEPTANCE_REPORT).write_text(json.dumps({
        "schema": bd._ACCEPTANCE_SCHEMA, "status": "COMPLETE",
        "accepted": 0, "total": 1, "accepted_ids": [],
    }))
    with pytest.raises(SystemExit, match="does not account for every"):
        bd._require_program_first_ai_acceptance(run)


def _override_review(task: dict) -> dict:
    review = _valid_review(task)
    review["routing"] = {
        "verdict": "OVERRIDE_PROGRAM",
        "ai_nature": "existing_rtl_transform",
    }
    review["override"] = {
        "prompt_evidence": [{
            "excerpt": "assign y = a",
            "supports": "The requested behavior is a direct combinational path.",
        }],
        "explanation": (
            "The prose explicitly defines direct combinational behavior, so "
            "the AI route supersedes the program's generic generation label."),
        "program_limitation": (
            "The structural router treats every prompt-only task as generation."),
        "proposed_program_enhancement": {
            "component": "task_nature_route",
            "proposal": "Recognize explicit transform semantics before fallback.",
            "regression_fixture": "prompt-only direct assignment fixture",
        },
    }
    return review


def test_ai_can_override_program_with_prompt_bound_evidence(tmp_path):
    run, task, _ = _task(tmp_path)
    _solve_report(run, task)
    _write_review(task, _override_review(task))

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 0
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "COMPLETE"
    assert acceptance["review_outcomes"][0]["routing_verdict"] == \
        "OVERRIDE_PROGRAM"
    enhancement = bd._read_jsonl(run / bd._ENHANCEMENT_WORKLIST)
    assert len(enhancement) == 1
    assert enhancement[0]["blocking_acceptance"] is False
    assert enhancement[0]["verified_prompt_evidence"][0]["excerpt"] == \
        "assign y = a"


def test_unexplained_program_override_is_rejected(tmp_path):
    _, task, _ = _task(tmp_path)
    review = _override_review(task)
    review["override"]["prompt_evidence"] = []
    review["override"]["explanation"] = "AI disagrees."
    _write_review(task, review)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any("prompt-bound evidence" in r for r in verdict["reasons"])


def test_detailed_ai_interpretation_can_substitute_for_a_literal_excerpt(tmp_path):
    _, task, _ = _task(tmp_path)
    review = _override_review(task)
    review["override"]["prompt_evidence"] = []
    review["override"]["explanation"] = (
        "The request describes a continuously observable output whose value "
        "tracks the input without any clock, reset, enable, latency, storage, "
        "or transaction boundary. Those omissions are semantically material: "
        "adding sequential state changes when the output becomes visible and "
        "therefore implements a different interface contract from the prose.")
    _write_review(task, review)
    assert bd._validate_ai_review(task)["status"] == "ACCEPTED"


@_NEEDS_SIMULATOR
def test_semantic_disagreement_requires_executable_proof_before_repair(tmp_path):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    _solve_report(run, task)
    _write_review(task, _proven_fail_review(task))

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "PENDING"
    assert acceptance["review_outcomes"][0]["status"] == "REPAIR_REQUIRED"
    repairs = bd._read_jsonl(run / bd._REPAIR_WORKLIST)
    assert repairs[0]["status"] == "AI_SEMANTIC_REPAIR_REQUIRED"
    assert repairs[0]["verified_challenge"]["sha256"] == \
        _proven_fail_review(task)["verification_test"]["sha256"]
    assert "SAME challenge" in repairs[0]["required_next"]
    assert not Path(task["response_path"]).exists()
    assert len(bd._read_jsonl(run / bd._ENHANCEMENT_WORKLIST)) == 1


def test_semantic_fail_without_executable_verification_is_rejected(tmp_path):
    _, task, _ = _task(tmp_path)
    review = _valid_review(task)
    review["semantic_review"] = {
        "verdict": "FAIL", "findings": [{"issue": "AI disagrees"}],
        "rationale": "This output looks wrong.",
    }
    review.pop("verification_test", None)
    _write_review(task, review)
    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any("verification_test" in r for r in verdict["reasons"])


def test_verification_test_cannot_read_external_oracle_files(tmp_path):
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    review = _proven_fail_review(task)
    challenge = Path(task["challenge_path"])
    source = challenge.read_text().replace(
        "module vibeic_ai_challenge_tb;",
        "module vibeic_ai_challenge_tb; reg [7:0] oracle [0:1]; "
        "initial $readmemh(\"golden.txt\", oracle);")
    challenge.write_text(source)
    review["verification_test"]["sha256"] = bd._sha256_text(source)
    _write_review(task, review)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any("self-contained" in reason for reason in verdict["reasons"])


# ---------------------------------------------------------------------------
# a MISSING CAPABILITY is NOT_MEASURED, never a finding about the subject
#
# Everything below runs identically on every host: the simulator is removed by
# a `which` stub, never by the host's luck. That is what stops the four
# `_NEEDS_SIMULATOR` tests above from being a hole -- the branch they cannot
# reach on a bare host is reached here instead.
# ---------------------------------------------------------------------------
def test_the_skip_condition_is_the_production_question(tmp_path, monkeypatch):
    """The probe that gates the four tests must ask the production question.

    If it ever drifted -- probing a different binary, or nothing at all -- the
    four tests could skip on a host that can in fact run them, which is the
    silenced-test failure mode. So it is pinned to the observable behaviour of
    `_run_verification_challenge` in both directions.
    """
    _, task, _ = _task(tmp_path)
    challenge = _write_direct_assignment_challenge(task)
    candidate = task["candidate_snapshot"]

    _no_simulator(monkeypatch)
    assert _simulator_absent(), "the probe must see the stubbed-away simulator"
    assert bd._run_verification_challenge(candidate, challenge)["status"] == \
        bd._CHALLENGE_UNAVAILABLE

    monkeypatch.undo()
    if not _simulator_absent():
        assert bd._run_verification_challenge(candidate, challenge)["status"] \
            != bd._CHALLENGE_UNAVAILABLE, (
            "the probe says this host has a simulator but the production code "
            "still reports UNAVAILABLE -- the skip condition is asking the "
            "wrong question")


def test_an_unrunnable_challenge_is_NOT_MEASURED_not_a_rejected_review(
        tmp_path, monkeypatch):
    """THE BUG. A proven-FAIL review on a host with no simulator was coming
    back REJECTED with "AI finding is not proven" -- an accusation assembled
    out of a missing binary. Nothing about this candidate was established, and
    the verdict must say so in those words."""
    _, task, _ = _task(tmp_path)
    _write_review(task, _proven_fail_review(task))
    _no_simulator(monkeypatch)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == bd._NOT_MEASURED
    assert verdict["reasons"] == [], (
        "an unrunnable proof is not a finding against the review", verdict)
    assert not any("not proven" in r for r in verdict["decision_reasons"]), \
        verdict["decision_reasons"]
    assert any("could not be RUN on this host" in r
               for r in verdict["unmeasurable"]), verdict["unmeasurable"]
    assert any("iverilog" in r for r in verdict["unmeasurable"]), \
        "the reader must be told WHICH capability is missing"


def test_an_unrunnable_INHERITED_challenge_is_also_NOT_MEASURED(
        tmp_path, monkeypatch):
    """The other UNAVAILABLE site. Folding it into `!= PASS` charged a repair
    with failing a test nobody ran."""
    _, task, _ = _task(tmp_path)
    task["verification_challenges"] = [{
        **_write_direct_assignment_challenge(task),
        "id": task["id"], "prompt_sha256": task["prompt_sha256"],
    }]
    _write_review(task, _valid_review(task))
    _no_simulator(monkeypatch)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == bd._NOT_MEASURED
    assert not any("does not pass" in r for r in verdict["decision_reasons"])
    assert any("inherited" in r for r in verdict["unmeasurable"]), \
        verdict["unmeasurable"]


def test_a_real_disagreement_is_still_RED_with_the_simulator_stubbed(
        tmp_path, monkeypatch):
    """The other branch, and the reason NOT_MEASURED is not a way out.

    When the challenge DOES run and the candidate DOES fail it, the verdict is
    REPAIR_REQUIRED and a repair row is written -- exactly as before. The fix
    carved out UNAVAILABLE and nothing else.
    """
    _, task, _ = _task(tmp_path)
    _write_review(task, _proven_fail_review(task))
    monkeypatch.setattr(bd, "_run_verification_challenge",
                        lambda *_a, **_k: {"status": "FAIL", "returncode": 1})

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REPAIR_REQUIRED"
    assert verdict["unmeasurable"] == []


def test_a_challenge_the_candidate_PASSES_is_still_a_rejected_finding(
        tmp_path, monkeypatch):
    """And the accusation itself must survive. A review that claims FAIL over
    a candidate that passes its own test is wrong, and that is a finding about
    the review -- not a NOT_MEASURED."""
    _, task, _ = _task(tmp_path)
    _write_review(task, _proven_fail_review(task))
    monkeypatch.setattr(bd, "_run_verification_challenge",
                        lambda *_a, **_k: {"status": "PASS", "returncode": 0})

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any("not proven" in r for r in verdict["reasons"])


def test_a_malformed_review_outranks_an_unrunnable_proof(tmp_path, monkeypatch):
    """Precedence, stated. A review that is wrong on every host stays REJECTED
    on a host with no simulator; NOT_MEASURED must not become a place for real
    defects to hide."""
    _, task, _ = _task(tmp_path)
    review = _proven_fail_review(task)
    review["semantic_review"]["rationale"] = "no"          # too short: a defect
    _write_review(task, review)
    _no_simulator(monkeypatch)

    verdict = bd._validate_ai_review(task)
    assert verdict["status"] == "REJECTED"
    assert any("rationale" in r for r in verdict["reasons"])


def test_resume_reports_NOT_MEASURED_and_orders_no_repair(
        tmp_path, monkeypatch):
    """End to end, at the level a sweep report actually reads.

    The run must not be COMPLETE, must not accept the candidate, and must not
    put a row on the repair worklist -- telling an author to re-write RTL on
    the strength of a test that did not run is the misdirection this whole fix
    is about. It states the gap in its own field instead.
    """
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True)
    project = _project(tmp_path)
    (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(
        "module dut(input wire a, output wire y); assign y = ~a; endmodule\n")
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM")
    _solve_report(run, task)
    _write_review(task, _proven_fail_review(task))
    _no_simulator(monkeypatch)

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "PENDING"
    assert acceptance["accepted"] == 0
    assert acceptance["review_outcomes"][0]["status"] == bd._NOT_MEASURED
    assert acceptance["not_measured"] == 1
    assert acceptance["pending_repair"] == 0
    assert bd._read_jsonl(run / bd._REPAIR_WORKLIST) == []
    row = acceptance["not_measured_detail"][0]
    assert row["id"] == "p1"
    assert any("iverilog" in r for r in row["reasons"])
    assert "install the missing capability" in row["required_next"]
    assert not Path(task["response_path"]).exists(), \
        "NOT_MEASURED must never publish a result"


@_NEEDS_SIMULATOR
def test_with_a_REAL_simulator_no_verdict_is_NOT_MEASURED(tmp_path):
    """THE CONTROL ON THE FIX ITSELF.

    Everything above proves NOT_MEASURED appears where it should. Nothing above
    proves it stays away everywhere else -- and a "fix" that returned
    NOT_MEASURED for every review would satisfy every one of those tests while
    destroying the lane. So: with a real iverilog on this host, drive both
    substantive outcomes through the REAL challenge runner and require that
    neither is NOT_MEASURED and both carry an empty `unmeasurable`.

      candidate y = ~a  vs a challenge demanding y == a  -> challenge FAIL,
          the AI's finding is PROVEN            -> REPAIR_REQUIRED
      candidate y =  a  vs the same challenge             -> challenge PASS,
          the AI's FAIL claim is unfounded      -> REJECTED

    Note which is which. REPAIR_REQUIRED is the verdict when the candidate
    genuinely fails its proof: rejecting there would be discarding a proven
    finding. REJECTED belongs to the review that could not prove its claim.
    """
    outcomes = {}
    for rtl, label in (
            ("module dut(input wire a, output wire y); assign y = ~a; endmodule\n",
             "candidate fails the proof"),
            ("module dut(input wire a, output wire y); assign y = a; endmodule\n",
             "candidate passes the proof")):
        run = tmp_path / label.replace(" ", "_")
        (run / "responses").mkdir(parents=True)
        project = _project(tmp_path / label.replace(" ", "_") / "p")
        (project / "phase2" / "stage1" / "rtl" / "dut.v").write_text(rtl)
        got = bio.collect("rtllm", "p1", project)
        task = bd._make_ai_review_task(
            "p1", project, got, ROUTING, 0, run, "PROGRAM")
        _write_review(task, _proven_fail_review(task))
        verdict = bd._validate_ai_review(task)
        outcomes[label] = (verdict["status"],
                           verdict["challenge_result"]["status"],
                           verdict["unmeasurable"])

    assert outcomes["candidate fails the proof"][:2] == ("REPAIR_REQUIRED", "FAIL")
    assert outcomes["candidate passes the proof"][:2] == ("REJECTED", "PASS")
    assert all(u == [] for _s, _c, u in outcomes.values()), outcomes
    assert not any(s == bd._NOT_MEASURED for s, _c, _u in outcomes.values()), (
        "with a working simulator NOTHING may come back NOT_MEASURED", outcomes)


# ---------------------------------------------------------------------------
# the Phase-1 front door at resume: judged by what the run EMITTED
#
# #2012 (v1.15.55) put a BLOCKING front door in front of `cmd_resume`: a D1
# candidate must carry hash-bound Phase-1 provenance before anything is
# accepted. Its D1 branch, however, read the TASK's record and never the disk
# -- `current` was computed and ignored -- and it refused results still owed
# a Program retry, which have no outcome to guard at all. The three tests
# below pin the refusal that is right and the two that were not.
# ---------------------------------------------------------------------------
_FUNCTIONAL_PASS = {"phase3_verifying": {"ran": {
    "step4_functional_evidence": "PASS"}}}


def _canonical_task(tmp_path: Path, **kwargs) -> tuple[Path, dict]:
    """A reviewable D1 candidate whose Program evidence already says PASS, so
    the review needs no executable confirmation and no host simulator."""
    run = tmp_path / "run"
    (run / "responses").mkdir(parents=True, exist_ok=True)
    project = _project(tmp_path, **kwargs)
    got = bio.collect("rtllm", "p1", project)
    task = bd._make_ai_review_task(
        "p1", project, got, ROUTING, 0, run, "PROGRAM",
        program_phases=_FUNCTIONAL_PASS)
    return run, task


def test_a_d1_candidate_without_phase1_provenance_is_refused_at_resume(
        tmp_path, capsys):
    """The refusal that is RIGHT, pinned so the canonical fixture above is
    known to pass THROUGH the gate rather than around it: the same candidate
    minus its L-docs is refused by the exact clause that reddened the eight,
    and nothing is published."""
    run, task = _canonical_task(tmp_path, phase1=False)
    assert task["phase1_provenance"] == {"ran": False}
    _solve_report(run, task)
    _write_review(task, _valid_review(task))

    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    err = capsys.readouterr().err
    assert "canonical D1-entry run emitted no Phase-1 provenance" in err, err
    assert not Path(task["response_path"]).exists()
    acceptance = run / bd._ACCEPTANCE_REPORT
    assert (not acceptance.exists()
            or json.loads(acceptance.read_text())["accepted_ids"] == [])


def test_emitted_phase1_provenance_is_bound_when_the_task_does_not_carry_it(
        tmp_path, monkeypatch):
    """THE DEFECT, first half. A task from before provenance was carried in
    review tasks (v1.13.70), or one not written yet, records nothing -- and
    the D1 branch answered that absence with "emitted no Phase-1 provenance"
    while the L-docs sat on disk. The emitted provenance must be read, bound
    into the task, and never regenerated by a runner call."""
    run, task = _canonical_task(tmp_path)
    emitted = task["phase1_provenance"]
    assert emitted["ran"] is True
    stale = {k: v for k, v in task.items() if k != "phase1_provenance"}
    _solve_report(run, stale)
    _write_review(stale, _valid_review(stale))

    def never(_self, argv):
        raise AssertionError(
            f"a D1 run's provenance is bound, never regenerated: {argv}")

    monkeypatch.setattr(bd._RunnerBudget, "run", never)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 0
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "COMPLETE"
    assert acceptance["accepted_ids"] == ["p1"]
    rebound = bd._read_jsonl(run / bd._REVIEW_WORKLIST)[0]
    assert rebound["phase1_provenance"] == emitted
    solve = json.loads((run / "solve_report.json").read_text())
    assert solve["results"][0]["phase1_frontdoor"]["status"] == "REUSED"
    bd._require_program_first_ai_acceptance(run)


def test_a_retryable_worker_error_is_retried_not_refused_at_the_front_door(
        tmp_path, monkeypatch):
    """THE DEFECT, second half. A result whose Program worker died is owed
    the retry `cmd_resume` was built to give it, and has no candidate to
    guard. The front door refused it -- so one D1 crash froze every other
    result in the run behind a message about provenance nobody had yet had
    the chance to emit. The retry must be attempted, its failure must stay
    loud, and the reviewed sibling must still be accepted."""
    run, task = _canonical_task(tmp_path)
    _solve_report(run, task)
    solve = json.loads((run / "solve_report.json").read_text())
    solve["results"].append({
        "id": "p2", "ok": False, "candidate_ready": False,
        "accepted": False, "entry": "D1", "evidence": "RTL_SIM",
        "exit": "8", "routing_verdict": ROUTING, "rc": None,
        "worker_status": "ERROR", "worker_retryable": True,
        "worker_error": "fixture: the worker died before Phase 1",
    })
    solve["total"] = 2
    (run / "solve_report.json").write_text(json.dumps(solve))
    _write_review(task, _valid_review(task))
    attempted: list[list[str]] = []

    def retry(_self, argv):
        attempted.append([str(v) for v in argv])
        return bd._ProcessOutcome(
            rc=None, error="fixture: the worker died again")

    monkeypatch.setattr(bd._RunnerBudget, "run", retry)
    assert bd.cmd_resume("rtllm", "/unused", str(run)) == 2
    # The solve report exists on both sides of the fix; its VALUES are the
    # measurement. Before the fix the resume aborted at the front door and
    # left p1 exactly as --solve wrote it: accepted False.
    resumed = json.loads((run / "solve_report.json").read_text())["results"]
    assert resumed[0]["accepted"] is True
    assert resumed[1]["worker_status"] == "ERROR"
    assert [a[2] if len(a) > 2 else None for a in attempted] == [
        str(run / "projects" / "p2")], attempted
    acceptance = json.loads((run / bd._ACCEPTANCE_REPORT).read_text())
    assert acceptance["status"] == "PENDING"
    assert acceptance["accepted_ids"] == ["p1"]
    assert Path(task["response_path"]).exists()
    repairs = bd._read_jsonl(run / bd._REPAIR_WORKLIST)
    assert [r["status"] for r in repairs] == ["PROJECT_WORKER_ERROR"]
