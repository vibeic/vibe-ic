"""Explicit original-input export remains gated and byte-bound without a D1 fiction."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import benchmark_io_adapter as bio
import emit_attestation as ea
import emit_attestation_check as checker
import shape_b_sample_export as exporter


def _project(tmp_path, context=None):
    project = tmp_path / "projects" / "logic_unit"
    # Include CRLF and non-ASCII bytes: input identity must not fingerprint a
    # newline-normalized or reconstructed prose copy.
    prompt = "Combinational two-input exclusive OR.\r\n完整來源尾端。\r\n"
    bio.stage("cvdp", {"id": "logic_unit", "record": {"id": "logic_unit",
              "input": {"prompt": prompt, "context": context or {}}}}, project)
    rtl = tmp_path / "candidate_snapshots" / "logic_unit" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "logic_unit.sv").write_text(
        "module logic_unit(input a, input b, output y);\n"
        "assign y = a ^ b;\nendmodule\n")
    return project, rtl


def _export(project, rtl, samples, **kwargs):
    return exporter.export(rtl, "logic_unit", samples,
                           spec_module="logic_unit", project=project, **kwargs)


def test_original_input_provenance_preserves_bytes_without_claiming_phase1(tmp_path):
    project, _ = _project(tmp_path)
    data = (project / "input/phase1_prompt.md").read_bytes()
    original = ea.input_provenance(project, "original")
    assert original["ran"] is False
    assert original["input_contract"] == "original"
    assert original["prompt_path"] == str(project / "input/phase1_prompt.md")
    assert original["prompt_sha256"] == hashlib.sha256(data).hexdigest()
    assert original["prompt_bytes"] == len(data)
    assert original["public_original_input"]["status"] == "NOT_PROVIDED"
    assert ea.provenance_is_current(original)
    assert ea.input_provenance(project) == {"ran": False}
    assert not ea.provenance_is_current({"ran": False})


def test_original_input_provenance_supports_ordinary_prompt_without_public_manifest(tmp_path):
    project = tmp_path / "ordinary"
    (project / "input").mkdir(parents=True)
    (project / "input/phase1_prompt.md").write_text("A combinational XOR interface.\n")
    original = ea.input_provenance(project, "original")
    assert original["public_original_input"] is None
    assert ea.provenance_is_current(original)


@pytest.mark.parametrize("mutation", ["prompt", "context", "manifest"])
def test_original_input_drift_is_rejected_by_existing_checker(tmp_path, mutation):
    project, rtl = _project(tmp_path, {"requirements.txt": "Output follows the XOR truth table.\n"})
    samples = tmp_path / "samples"
    result = _export(project, rtl, samples, rtl_input="original")
    assert result["verdict"] == "PASS", result
    assert checker.main(["--samples", str(samples), "--strict"]) == 0
    if mutation == "prompt":
        path = project / "input/phase1_prompt.md"
        path.write_bytes(path.read_bytes() + b"Changed source.\n")
    elif mutation == "context":
        (project / "input/public_original/files/requirements.txt").write_text("Changed source.\n")
    else:
        (project / "input/public_original/manifest.json").unlink()
    assert checker.main(["--samples", str(samples), "--strict"]) == 1


@pytest.mark.parametrize("replacement", [
    {"ran": False},
    {"ran": True, "input_contract": "original"},
    {"ran": True, "input_contract": "invented"},
])
def test_missing_or_falsely_labelled_input_cannot_select_raw_mode(tmp_path, replacement):
    project, rtl = _project(tmp_path)
    samples = tmp_path / "samples"
    assert _export(project, rtl, samples, rtl_input="original")["verdict"] == "PASS"
    record = ea._load(samples)["logic_unit.v"]
    record["phase1"] = replacement
    (samples / ea.ATTEST_NAME).write_text(json.dumps(record) + "\n")
    assert ea.verify(samples) == (False, ["logic_unit.v"], 1)


def test_original_export_is_explicit_and_does_not_bypass_candidate_hash(tmp_path):
    project, rtl = _project(tmp_path)
    samples = tmp_path / "samples"
    assert _export(project, rtl, samples)["verdict"] == "PASS"
    assert ea.verify(samples) == (False, ["logic_unit.v"], 1)
    assert _export(project, rtl, samples, rtl_input="original")["verdict"] == "PASS"
    provenance = ea._load(samples)["logic_unit.v"]["phase1"]
    assert provenance["ran"] is False
    assert ea.verify(samples) == (True, [], 1)
    with (samples / "logic_unit.v").open("a") as output:
        output.write("// mutation after gated export\n")
    assert ea.verify(samples) == (False, ["logic_unit.v"], 1)


def test_original_export_still_rejects_native_invalid_rtl(tmp_path):
    assert shutil.which("iverilog"), "native emit control requires the pinned EDA image"
    project, rtl = _project(tmp_path)
    (rtl / "logic_unit.sv").write_text(
        "module logic_unit(input a, input b, output y);\n"
        "assign y = ;\nendmodule\n")
    samples = tmp_path / "samples"
    result = _export(project, rtl, samples, rtl_input="original")
    assert result["verdict"] == "FAIL", result
    assert result["reason"] == "guard_rejected", result
    assert not (samples / "logic_unit.v").exists()
    assert not (samples / ea.ATTEST_NAME).exists()


def test_original_cli_export_emits_native_functioning_candidate(tmp_path):
    assert shutil.which("iverilog") and shutil.which("vvp"), "native control requires the pinned EDA image"
    project, rtl = _project(tmp_path)
    samples = tmp_path / "samples"
    assert exporter.main(["--project", str(project), "--rtl-dir", str(rtl),
                          "--leaf", "logic_unit", "--samples", str(samples),
                          "--module", "logic_unit", "--rtl-input", "original"]) == 0
    assert checker.main(["--samples", str(samples), "--strict"]) == 0
    probe = tmp_path / "probe.sv"
    probe.write_text("module Probe; reg a,b; wire y; integer k;\n"
                     "logic_unit dut(.a(a),.b(b),.y(y));\n"
                     "initial begin for(k=0;k<4;k=k+1) begin\n"
                     "{a,b}=k; #1; if(y !== (a^b)) $fatal(1, \"XOR mismatch\");\n"
                     "end $display(\"ORIGINAL_INPUT_EMIT_OK\"); $finish; end endmodule\n")
    simulation = tmp_path / "probe.vvp"
    compile_result = subprocess.run(["iverilog", "-g2012", "-s", "Probe", "-o",
                                     str(simulation), str(samples / "logic_unit.v"),
                                     str(probe)], capture_output=True, text=True)
    assert compile_result.returncode == 0, compile_result.stderr
    run_result = subprocess.run(["vvp", str(simulation)], capture_output=True, text=True)
    assert run_result.returncode == 0, run_result.stdout + run_result.stderr
    assert "ORIGINAL_INPUT_EMIT_OK" in run_result.stdout


def test_original_input_rejects_missing_or_linked_prompt(tmp_path):
    project = tmp_path / "project"
    (project / "input").mkdir(parents=True)
    with pytest.raises((ValueError, OSError)):
        ea.input_provenance(project, "original")
    outside = tmp_path / "outside.md"
    outside.write_text("Unrelated source.\n")
    (project / "input/phase1_prompt.md").symlink_to(outside)
    with pytest.raises(ValueError, match="symbolic link"):
        ea.input_provenance(project, "original")
