"""Native source-bound controls for issue 3655's existing repair consumer."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import benchmark_io_adapter as bio
from _hostpaths import require_repo
from rtl_repair_contract import sha256_text


PROMPT = "The implementation shall use only multiplexers for the selectable data path.\n"
WRONG = """module neutral_select(input wire a, b, s, output wire y);
wire ns, left, right;
assign ns = ~s;
assign left = ns & a;
assign right = s & b;
assign y = left | right;
endmodule
"""
RIGHT = """module neutral_select(input wire a, b, s, output wire y);
assign y = s ? b : a;
endmodule
"""
IMAGE_ID = "sha256:a6713464903bd9f6c3de15cea8653cb0cf1388a24915632190ad64ce3fc2c3d5"
IMAGE = "ghcr.io/vibeic/vibeic-eda@" + IMAGE_ID


def test_checked_in_completion_consumer_forwards_structural_requirement_sources():
    consumer = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "benchmark_io_adapter.py").read_text(errors="replace")
    assert 'contract = {"structural": contract}' in consumer
    assert "requirement_sources=requirement_sources" in consumer


def _native_ready() -> None:
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("native structural control NOT_MEASURED: docker unavailable")
    probe = subprocess.run(
        [docker, "image", "inspect", IMAGE, "--format", "{{.Id}}"],
        capture_output=True, text=True)
    if probe.returncode or probe.stdout.strip() != IMAGE_ID:
        pytest.skip("native structural control NOT_MEASURED: immutable image unavailable")


def _project(tmp_path: Path, candidate: str, original: str = WRONG) -> Path:
    project = tmp_path / "project"
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "neutral_select.sv").write_text(candidate)
    original_dir = project / "input" / "public_original" / "files"
    original_dir.mkdir(parents=True)
    (original_dir / "neutral_select.sv").write_text(original)
    (project / "input" / "phase1_prompt.md").write_text(PROMPT)
    report = project / "reports" / "orchestrator"
    report.mkdir(parents=True)
    (report / "phase2_one_shot.json").write_text(json.dumps(
        {"steps": [{"name": "rtl_gen", "status": "PASS", "detail": "neutral fixture"}]}))
    return project


def _contract(candidate: str) -> dict:
    quote = PROMPT.strip()
    return {
        "schema": "vibeic.native_structural_contract.v1",
        "source_path": "neutral_select.sv",
        "source_sha256": sha256_text(WRONG),
        "candidate_sha256": sha256_text(candidate),
        "top": "neutral_select",
        "abstraction": "RTLIL_AFTER_PROC_OPT",
        "scope": "top_module_cells",
        "requirement_source": {
            "path": "input/phase1_prompt.md",
            "sha256": sha256_text(PROMPT),
            "quote": quote,
            "quote_sha256": sha256_text(quote),
        },
        "backend": {"kind": "docker", "image": IMAGE, "image_id": IMAGE_ID},
        "expectations": {
            "required_cell_types": {"$mux": 1},
            "forbidden_cell_types": ["$and", "$or", "$not"],
            "allow_other_cell_types": False,
        },
    }


def _normal_repair_contract(candidate: str) -> dict:
    return {
        "schema": "vibeic.source_bounded_completion.v1",
        "preservation": {
            "schema": "vibeic.rtl_preservation_declaration.v1",
            "sources": [{
                "path": "neutral_select.sv",
                "source_sha256": sha256_text(WRONG),
                "candidate_sha256": sha256_text(candidate),
                "authorized_edit_regions": [],
                "preserved_executable_fragments": [{"quote": "module neutral_select"}],
            }],
        },
        "elaboration_matrix": {
            "schema": "vibeic.public_elaboration_matrix.v1",
            "source_path": "neutral_select.sv",
            "source_sha256": sha256_text(WRONG),
            "candidate_sha256": sha256_text(candidate),
            "source_quotes": ["module neutral_select"],
            "top": "neutral_select",
            "supported_macros": [],
            "supported_parameters": [],
            "configurations": [{"name": "default"}],
        },
        "structural": _contract(candidate),
    }


def _functional_run(tmp_path: Path, source: str, name: str) -> tuple[int, str]:
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.fail("functional control NOT_MEASURED: iverilog/vvp unavailable")
    rtl = tmp_path / f"{name}.sv"
    tb = tmp_path / f"{name}_tb.sv"
    out = tmp_path / f"{name}.vvp"
    rtl.write_text(source)
    tb.write_text("""module tb;
reg a, b, s; wire y; integer i;
neutral_select dut(a,b,s,y);
initial begin
  for (i=0; i<8; i=i+1) begin
    {s,b,a}=i; #1;
    if (y !== (s ? b : a)) $fatal(1, "functional mismatch");
  end
  $display("FUNCTIONAL_PASS"); $finish;
end
endmodule
""")
    compiled = subprocess.run(
        ["iverilog", "-g2012", "-s", "tb", "-o", str(out), str(rtl), str(tb)],
        capture_output=True, text=True)
    assert compiled.returncode == 0, compiled.stderr
    ran = subprocess.run(["vvp", str(out)], capture_output=True, text=True)
    return ran.returncode, ran.stdout + ran.stderr


def test_actual_consumer_rejects_wrong_structure_and_accepts_replayed_repair(tmp_path):
    _native_ready()
    before_functional = _functional_run(tmp_path, WRONG, "wrong")
    after_functional = _functional_run(tmp_path, RIGHT, "right")
    assert before_functional[0] == after_functional[0] == 0
    assert "FUNCTIONAL_PASS" in before_functional[1]
    assert "FUNCTIONAL_PASS" in after_functional[1]

    wrong = bio.collect(
        "rtllm", "neutral", _project(tmp_path / "wrong", WRONG),
        repair_contract=_contract(WRONG))
    assert wrong["ok"] is False
    assert wrong["repair_contract"]["verdict"] == "FAIL"
    wrong_proof = wrong["repair_contract"]["structural"]
    assert wrong_proof["verdict"] == "FAIL"
    assert wrong_proof["execution"]["image_id"] == IMAGE_ID
    assert wrong_proof["execution"]["limits"] == {
        "cpus": 2, "memory": "4g", "timeout_seconds": 300, "network": "none"}
    assert wrong_proof["observation"]["cell_type_counts"].get("$mux", 0) == 0

    repaired = bio.collect(
        "rtllm", "neutral", _project(tmp_path / "right", RIGHT),
        repair_contract=_contract(RIGHT))
    assert repaired["ok"] is True
    replay = repaired["repair_contract"]["structural"]
    assert replay["verdict"] == "PASS"
    assert replay["execution"]["script_sha256"] == wrong_proof["execution"]["script_sha256"]
    assert replay["observation"]["cell_type_counts"] == {"$mux": 1}

    strict = bio.collect(
        "rtllm", "neutral", _project(tmp_path / "strict", RIGHT),
        supplied_rtl=True, repair_contract=_normal_repair_contract(RIGHT),
        require_repair_contract=True)
    assert strict["ok"] is True
    assert strict["repair_contract"]["preservation"]["verdict"] == "PASS"
    assert strict["repair_contract"]["elaboration_matrix"]["verdict"] == "PASS"
    assert strict["repair_contract"]["structural"]["verdict"] == "PASS"


def test_unconstrained_equivalent_architecture_does_not_fail(tmp_path):
    project = _project(tmp_path, WRONG)
    result = bio.collect("rtllm", "neutral", project)
    assert result["ok"] is True
    assert "repair_contract" not in result


def test_ambiguous_structural_scope_is_not_measured_and_refused(tmp_path):
    contract = _contract(WRONG)
    del contract["scope"]
    result = bio.collect(
        "rtllm", "neutral", _project(tmp_path, WRONG), repair_contract=contract)
    assert result["ok"] is False
    assert result["repair_contract"]["structural"]["verdict"] == "NOT_MEASURED"
    assert {f["code"] for f in result["repair_contract"]["findings"]} == {
        "STRUCTURAL_SCOPE_AMBIGUOUS"}


@pytest.mark.parametrize("tamper", ["source", "candidate", "requirement", "tool"])
def test_structural_identity_drift_is_refused_before_acceptance(tmp_path, tamper):
    contract = _contract(RIGHT)
    if tamper == "source":
        contract["source_sha256"] = "0" * 64
    elif tamper == "candidate":
        contract["candidate_sha256"] = "0" * 64
    elif tamper == "requirement":
        contract["requirement_source"]["sha256"] = "0" * 64
    else:
        contract["backend"]["image_id"] = "0" * 64
    result = bio.collect(
        "rtllm", "neutral", _project(tmp_path, RIGHT), repair_contract=contract)
    assert result["ok"] is False
    assert result["repair_contract"]["structural"]["verdict"] == "REFUSED"


def test_structural_author_cannot_inject_a_synthesis_remap(tmp_path):
    contract = _contract(RIGHT)
    contract["script"] = "synth; abc"
    result = bio.collect(
        "rtllm", "neutral", _project(tmp_path, RIGHT), repair_contract=contract)
    assert result["ok"] is False
    finding = result["repair_contract"]["structural"]["findings"][0]
    assert finding["code"] == "STRUCTURAL_COMMAND_INJECTION_REFUSED"
