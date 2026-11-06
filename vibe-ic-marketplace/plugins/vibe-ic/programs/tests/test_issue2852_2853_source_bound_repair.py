"""Native, source-bound controls for issues 2852 and 2853.

The fixtures are deliberately neutral.  The tests exercise the existing
presence-only API separately from the typed declarations and then drive the
normal ``benchmark_io_adapter.collect`` completion consumer.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

import benchmark_io_adapter as bio
import file_extend_preserve_check as preserve
from _hostpaths import require_repo
from rtl_repair_contract import (
    SCHEMA_MATRIX,
    SCHEMA_PRESERVATION,
    sha256_text,
    validate_matrix_declaration,
    validate_preservation_declaration,
    load_json,
)


ORIGINAL = """module state_unit(input wire clk, reset_n, set_flag, recover, output reg flag);
always @(posedge clk or negedge reset_n) begin
  if (!reset_n) flag <= 1'b0;
  else if (recover) flag <= 1'b0;
  else if (set_flag) flag <= 1'b1;
end
endmodule
"""
REMOVED = ORIGINAL.replace("else if (recover) flag <= 1'b0;",
                           "else if (recover) begin end")
FORMATTED = ORIGINAL.replace("else if (recover) flag <= 1'b0;",
                             "else if (recover)\n    flag <= 1'b0;")
RENAMED = ORIGINAL.replace("state_unit", "renamed_unit", 1)
HELPER = "module supplied_helper(input wire a, output wire y); assign y = a; endmodule\n"


def _fragment_decl(source: str, *, authorized=None, candidate=None, quote=None):
    quote = quote or "else if (recover) flag <= 1'b0;"
    return {
        "schema": SCHEMA_PRESERVATION,
        "sources": [{
            "path": "state_unit.sv",
            "source_sha256": sha256_text(source),
            "candidate_sha256": candidate and sha256_text(candidate),
            "authorized_edit_regions": authorized if authorized is not None else [],
            "preserved_executable_fragments": [{
                "id": "recover_assignment",
                "quote": quote,
            }],
        }],
    }


def _matrix_decl(original: str, candidate: str, *, rows=None, quotes=None):
    return {
        "schema": SCHEMA_MATRIX,
        "source_sha256": sha256_text(original),
        "candidate_sha256": sha256_text(candidate),
        "source_quotes": quotes or ["`ifdef FAST_MODE localparam CYCLES=0.05*1000;"],
        "top": "public_mode_fixture",
        "supported_macros": ["FAST_MODE"],
        "supported_parameters": [],
        "configurations": rows or [
            {"name": "default", "defines": []},
            {"name": "fast", "defines": ["FAST_MODE"]},
        ],
    }


PUBLIC_BUGGY = """module public_mode_fixture #(parameter DURATION=4)
  (input wire clk, reset_n, output reg [7:0] remaining);
`ifdef FAST_MODE
  localparam CYCLES=0.05*1000;
`else
  localparam CYCLES=DURATION;
`endif
always @(posedge clk or negedge reset_n)
  if (!reset_n) remaining <= 8'(CYCLES);
  else if (remaining != 0) remaining <= remaining-1'b1;
endmodule
"""
PUBLIC_FIXED = PUBLIC_BUGGY.replace("8'(CYCLES)", "8'(int'(CYCLES))")


def test_checked_in_rtl_artifact_is_bound_to_its_fresh_source_bytes():
    artifact = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "calibration", "cdc_netlist_cdc_sync.v")
    source = artifact.read_text(errors="replace")
    module = re.search(r"\bmodule\s+([A-Za-z_]\w*)", source)
    assert module is not None
    quote = module.group(0)
    declaration = {
        "schema": SCHEMA_PRESERVATION,
        "sources": [{
            "path": artifact.name,
            "source_sha256": sha256_text(source),
            "candidate_sha256": sha256_text(source),
            "authorized_edit_regions": [],
            "preserved_executable_fragments": [{"quote": quote}],
        }],
    }
    report = validate_preservation_declaration(
        {artifact.name: source}, {artifact.name: source}, declaration)
    assert report["verdict"] == "PASS"


def test_presence_only_remains_honest_for_removed_recovery_assignment():
    assert preserve.check_sets({"state_unit.sv": ORIGINAL},
                               {"state_unit.sv": REMOVED}) == []


def test_typed_declaration_blocks_removed_fragment_and_allows_authorized_edit():
    blocked = validate_preservation_declaration(
        {"state_unit.sv": ORIGINAL}, {"state_unit.sv": REMOVED},
        _fragment_decl(ORIGINAL, candidate=REMOVED))
    assert blocked["verdict"] == "FAIL"
    assert any(f["code"] == "UNAUTHORIZED_FRAGMENT_REMOVAL"
               for f in blocked["findings"])
    span_start = ORIGINAL.index("else if (recover)")
    span_end = ORIGINAL.index("\n", span_start)
    allowed = validate_preservation_declaration(
        {"state_unit.sv": ORIGINAL}, {"state_unit.sv": REMOVED},
        _fragment_decl(ORIGINAL, candidate=REMOVED,
                       authorized=[{"start": span_start, "end": span_end}]))
    assert allowed["verdict"] == "PASS"


def test_formatting_renamed_fsm_and_unchanged_helper_are_preserved():
    decl = _fragment_decl(ORIGINAL, candidate=FORMATTED)
    assert validate_preservation_declaration(
        {"state_unit.sv": ORIGINAL}, {"state_unit.sv": FORMATTED}, decl)["verdict"] == "PASS"
    renamed_decl = _fragment_decl(ORIGINAL, candidate=RENAMED, quote="module state_unit")
    renamed_decl["sources"][0]["preserved_executable_fragments"][0]["rename_bindings"] = {
        "state_unit": "renamed_unit"
    }
    renamed = validate_preservation_declaration(
        {"state_unit.sv": ORIGINAL}, {"state_unit.sv": RENAMED}, renamed_decl)
    assert renamed["verdict"] == "PASS"
    helper_decl = {
        "schema": SCHEMA_PRESERVATION,
        "sources": [
                {"path": "state_unit.sv", "source_sha256": sha256_text(ORIGINAL),
                 "candidate_sha256": sha256_text(ORIGINAL),
             "authorized_edit_regions": [],
             "preserved_executable_fragments": [{"quote": "else if (recover) flag <= 1'b0;"}]},
                {"path": "helper.sv", "source_sha256": sha256_text(HELPER),
                 "candidate_sha256": sha256_text(HELPER),
             "authorized_edit_regions": [],
             "preserved_executable_fragments": [{"quote": "assign y = a;"}]},
        ],
    }
    assert validate_preservation_declaration(
        {"state_unit.sv": ORIGINAL, "helper.sv": HELPER},
        {"state_unit.sv": ORIGINAL, "helper.sv": HELPER}, helper_decl)["verdict"] == "PASS"


@pytest.mark.parametrize("bad", [
    {"source_sha256": "0" * 64},
    {"source_sha256": sha256_text(ORIGINAL), "authorized_edit_regions": [],
     "preserved_executable_fragments": [{"kind": "regex", "quote": "x"}]},
])
def test_hash_mismatch_and_unsupported_fragment_refuse(bad):
    row = {"path": "state_unit.sv", **bad}
    row.setdefault("authorized_edit_regions", [])
    row.setdefault("preserved_executable_fragments", [{"quote": "else if (recover) flag <= 1'b0;"}])
    result = validate_preservation_declaration(
        {"state_unit.sv": ORIGINAL}, {"state_unit.sv": ORIGINAL},
        {"schema": SCHEMA_PRESERVATION, "sources": [row]})
    assert result["verdict"] == "REFUSED"


def test_missing_and_incomplete_source_declaration_refuse():
    missing = validate_preservation_declaration(
        {"state_unit.sv": ORIGINAL}, {"state_unit.sv": ORIGINAL}, None)
    assert missing["verdict"] == "REFUSED"
    incomplete = validate_preservation_declaration(
        {"state_unit.sv": "module state_unit(input wire clk;"},
        {"state_unit.sv": "module state_unit(input wire clk;"},
        _fragment_decl("module state_unit(input wire clk;"))
    assert incomplete["verdict"] == "REFUSED"


def test_native_recovery_counterexample_is_kept_separate_from_presence_gate(tmp_path):
    if shutil.which("iverilog") is None or shutil.which("vvp") is None:
        pytest.fail("native EDA unavailable: recovery control is NOT_MEASURED")
    tb = tmp_path / "preserve_tb.sv"
    tb.write_text("""`timescale 1ns/1ps
module preserve_tb;
reg clk=0; always #5 clk=~clk;
reg reset_n=1, set_flag=0, recover=0; wire flag;
state_unit dut(clk,reset_n,set_flag,recover,flag);
initial begin
  #1 reset_n=0; #1 reset_n=1;
  @(negedge clk) set_flag=1;
  @(negedge clk) begin set_flag=0; recover=1; end
  @(negedge clk);
  if (flag !== 0) $fatal(1,"supplied recovery assignment removed");
  $display("PASS"); $finish;
end
endmodule
""")
    outputs = []
    for name, source in (("before", ORIGINAL), ("after", REMOVED)):
        rtl = tmp_path / f"{name}.sv"
        rtl.write_text(source)
        out = tmp_path / f"{name}.vvp"
        import subprocess
        c = subprocess.run(["iverilog", "-g2012", "-s", "preserve_tb", "-o", str(out),
                            str(rtl), str(tb)], capture_output=True, text=True)
        assert c.returncode == 0, c.stderr
        run = subprocess.run(["vvp", str(out)], capture_output=True, text=True)
        outputs.append((run.returncode, run.stdout + run.stderr))
    assert outputs[0][0] == 0 and "PASS" in outputs[0][1]
    assert outputs[1][0] != 0 and "supplied recovery assignment removed" in outputs[1][1]




def test_matrix_default_only_deleted_branch_and_bad_mapping_refuse(tmp_path):
    candidate = tmp_path / "candidate.sv"
    candidate.write_text(PUBLIC_BUGGY)
    default_only = _matrix_decl(PUBLIC_BUGGY, PUBLIC_BUGGY,
                                rows=[{"name": "default", "defines": []}])
    assert validate_matrix_declaration(
        default_only, original_source=PUBLIC_BUGGY,
        candidate_source=PUBLIC_BUGGY)["verdict"] == "REFUSED"
    deleted = PUBLIC_BUGGY.replace("`ifdef FAST_MODE\n  localparam CYCLES=0.05*1000;\n`else\n", "")
    deleted_decl = _matrix_decl(PUBLIC_BUGGY, deleted)
    deleted_result = validate_matrix_declaration(
        deleted_decl, original_source=PUBLIC_BUGGY,
        candidate_source=deleted)
    assert deleted_result["verdict"] == "FAIL"
    bad = _matrix_decl(PUBLIC_BUGGY, PUBLIC_BUGGY,
                       rows=[{"name": "default", "defines": ["UNSUPPORTED"]},
                             {"name": "fast", "defines": ["FAST_MODE"]}])
    assert validate_matrix_declaration(
        bad, original_source=PUBLIC_BUGGY,
        candidate_source=PUBLIC_BUGGY)["verdict"] == "REFUSED"


def _project(tmp_path: Path, candidate: str, original: str, contract: dict) -> Path:
    project = tmp_path / "project"
    rtl = project / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "state_unit.sv").write_text(candidate)
    report = project / "reports" / "orchestrator"
    report.mkdir(parents=True)
    (report / "phase2_one_shot.json").write_text(json.dumps(
        {"steps": [{"name": "rtl_gen", "status": "PASS", "detail": "fixture"}]}))
    original_dir = project / "input" / "public_original" / "files"
    original_dir.mkdir(parents=True)
    (original_dir / "state_unit.sv").write_text(original)
    return project


def test_normal_collect_consumes_preservation_declaration_before_acceptance(tmp_path):
    contract = {"preservation": _fragment_decl(ORIGINAL, candidate=REMOVED)}
    project = _project(tmp_path, REMOVED, ORIGINAL, contract)
    rejected = bio.collect("rtllm", "neutral", project, repair_contract=contract)
    assert rejected["ok"] is False
    assert rejected["repair_contract"]["preservation"]["verdict"] == "FAIL"
    contract["preservation"] = _fragment_decl(ORIGINAL, candidate=ORIGINAL)
    project = _project(tmp_path / "fixed", ORIGINAL, ORIGINAL, contract)
    accepted = bio.collect("rtllm", "neutral", project, repair_contract=contract)
    assert accepted["ok"] is True
    assert accepted["repair_contract"]["verdict"] == "PASS"


def test_normal_collect_consumes_public_matrix_and_candidate_freshness(tmp_path):
    if shutil.which("iverilog") is None:
        pytest.fail("native EDA unavailable: normal matrix consumer is NOT_MEASURED")
    buggy_contract = {"elaboration_matrix": _matrix_decl(PUBLIC_BUGGY, PUBLIC_BUGGY)}
    project = _project(tmp_path, PUBLIC_BUGGY, PUBLIC_BUGGY, buggy_contract)
    refused = bio.collect("rtllm", "neutral", project, repair_contract=buggy_contract)
    assert refused["ok"] is False
    matrix_report = refused["repair_contract"]["elaboration_matrix"]
    assert matrix_report["verdict"] == "FAIL"
    assert {row["name"]: row["verdict"] for row in matrix_report["configurations"]} == {
        "default": "PASS", "fast": "FAIL"}
    fixed_contract = {"elaboration_matrix": _matrix_decl(PUBLIC_BUGGY, PUBLIC_FIXED)}
    fixed_project = _project(tmp_path / "fixed", PUBLIC_FIXED, PUBLIC_BUGGY, fixed_contract)
    accepted = bio.collect("rtllm", "neutral", fixed_project, repair_contract=fixed_contract)
    assert accepted["ok"] is True
    assert accepted["repair_contract"]["elaboration_matrix"]["verdict"] == "PASS"
    stale = _matrix_decl(PUBLIC_BUGGY, PUBLIC_BUGGY)
    result = bio.collect("rtllm", "neutral", fixed_project,
                         repair_contract={"elaboration_matrix": stale})
    assert result["ok"] is False
    assert result["repair_contract"]["elaboration_matrix"]["verdict"] == "REFUSED"


def test_missing_normal_contract_is_refused_when_required(tmp_path):
    project = _project(tmp_path, ORIGINAL, ORIGINAL, {})
    result = bio.collect("rtllm", "neutral", project, require_repair_contract=True)
    assert result["ok"] is False
    assert result["repair_contract"]["verdict"] == "REFUSED"


def test_supplied_rtl_is_not_itself_a_source_bounded_claim(tmp_path):
    project = _project(tmp_path, ORIGINAL, ORIGINAL, {})
    result = bio.collect("rtllm", "neutral", project, supplied_rtl=True)
    assert result["ok"] is True


def test_strict_collection_never_discovers_an_ambient_contract(tmp_path):
    project = _project(tmp_path, ORIGINAL, ORIGINAL, {})
    reports = project / "reports"
    reports.mkdir(exist_ok=True)
    (reports / "rtl_repair_contract.json").write_text("{}")
    result = bio.collect("rtllm", "neutral", project,
                         supplied_rtl=True, require_repair_contract=True)
    assert result["ok"] is False
    assert {f["code"] for f in result["repair_contract"]["findings"]} == {
        "DECLARATION_MISSING"}


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_contract_json_rejects_nonfinite_constants(tmp_path, constant):
    path = tmp_path / "contract.json"
    path.write_text('{"value": ' + constant + "}")
    with pytest.raises(ValueError, match="non-finite JSON constant"):
        load_json(path)
