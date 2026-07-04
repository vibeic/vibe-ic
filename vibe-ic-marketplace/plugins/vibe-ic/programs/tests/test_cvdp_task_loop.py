#!/usr/bin/env python3
r"""test_cvdp_task_loop.py — deterministic driver for the 224 plugin_loop records.

Verifies cvdp_task_loop:
  * runs the deterministic interface recovery for a context-bearing debug/modify
    record (reads input.context header-only, never output/harness);
  * classifies a deterministic body solve (RTL emitted + iverilog rc=0) vs
    needs_ai_backup;
  * the two real standard-algorithm records (convolutional encoder / moving
    average) solve deterministically and compile (guarded on dataset presence).

Run: python3 -m pytest programs/tests/test_cvdp_task_loop.py -q
"""
from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

_BENCH = Path(__file__).resolve().parents[2] / "benchmark"
_spec = importlib.util.spec_from_file_location(
    "cvdp_task_loop", _BENCH / "cvdp_task_loop.py")
L = importlib.util.module_from_spec(_spec)
sys.modules["cvdp_task_loop"] = L
_spec.loader.exec_module(L)

_DATASET = (Path(__file__).resolve().parents[5]
            / "benchmark-data" / "datasets" / "cvdp-benchmark-dataset"
            / "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


_DEBUG_REC = {
    "id": "cvdp_copilot_demo_debug_0001",
    "categories": ["cid016", "medium"],
    "input": {
        "prompt": "The module `widget` has a bug; fix it to match the spec.",
        "context": {"rtl/widget.sv": (
            "module widget (\n"
            "  input  wire       clk,\n"
            "  input  wire [7:0] a,\n"
            "  output reg  [7:0] y\n"
            ");\n  always @(posedge clk) y <= a;\nendmodule\n")},
    },
    "output": {"response": "SECRET"},
    "harness": {"src": {"t.py": "SECRET"}},
}


def test_context_target_reads_rtl_module_name():
    assert L._context_target(_DEBUG_REC) == "widget"


def test_debug_record_recovers_interface_deterministically(tmp_path):
    res = L.run_loop_case(_DEBUG_REC, tmp_path)
    assert res["nature"] == "debug"
    assert res["plugin_entry"] == "debug_loop"
    assert res["target_module"] == "widget"
    assert res["iface_ports"] == 3          # clk, a[8], y[8]
    # no deterministic body solver for a novel debug → AI-backup.
    assert res["emit_path"] == "needs_ai_backup"


def test_driver_reads_only_input_not_oracle(tmp_path):
    # run the case, then prove the oracle strings were never written anywhere.
    L.run_loop_case(_DEBUG_REC, tmp_path)
    blob = "".join(p.read_text(errors="ignore")
                   for p in tmp_path.rglob("*") if p.is_file())
    assert "SECRET" not in blob


def test_needs_ai_backup_gets_ic_expert_agent_pack(tmp_path):
    # a novel debug body has no deterministic solver → the loop must hand it to
    # the AI acting AS the IC Expert Agent, with expert-skills + expert-DB.
    res = L.run_loop_case(_DEBUG_REC, tmp_path)
    assert res["emit_path"] == "needs_ai_backup"
    ab = res["ai_backup"]
    assert ab["subagent_type"] == "vibe-ic:ic-expert-agent"
    assert ab["expert_skills"]                 # the debug_loop AI-backup skills
    assert ab["n_skills"] > 0                   # expert-SKILLS digest rendered
    handoff = tmp_path / "cases" / _DEBUG_REC["id"] / "ai_backup" \
        / "ic_expert_agent_handoff.json"
    assert handoff.is_file()


# cid002 completion: the partial RTL (interface) is embedded in the PROMPT, not
# in input.context — the loop recovers it from the in-prompt real module header.
_COMPLETION_IN_PROMPT = {
    "id": "cvdp_copilot_demo_completion_0001",
    "categories": ["cid002", "easy"],
    "input": {
        "prompt": (
            "Complete the following module so it registers `a` into `y`.\n\n"
            "```verilog\n"
            "module widget (\n"
            "  input  wire        clk,\n"
            "  input  wire [7:0]  a,\n"
            "  output reg  [7:0]  y\n"
            ");\n"
            "  // TODO: implement\n"
            "endmodule\n"
            "```\n"),
        "context": None,
    },
    "output": {"response": "SECRET"},
}


def test_completion_recovers_interface_from_in_prompt_header(tmp_path):
    res = L.run_loop_case(_COMPLETION_IN_PROMPT, tmp_path)
    assert res["nature"] == "completion"
    assert res["iface_ports"] == 3          # clk, a[8], y[8]
    assert res["iface_source"] == "in_prompt_header"


def test_recover_interface_from_text_helper():
    txt = ("blah\n```verilog\nmodule foo (input clk, input [3:0] d, "
           "output reg q);\n endmodule\n```")
    ports = L._IR.recover_interface_from_text(txt, "foo")
    names = sorted(p["name"] for p in ports)
    assert names == ["clk", "d", "q"]
    # absent target → []
    assert L._IR.recover_interface_from_text(txt, "nope") == []


# Part C — optimization's deterministic-first is a hygiene/lint BASELINE over the
# context RTL (no interface/solve step for cid007).
_OPTIMIZE_REC = {
    "id": "cvdp_copilot_demo_optimize_0001",
    "categories": ["cid007", "medium"],
    "input": {
        "prompt": "Reduce the area of `widget` without changing behaviour.",
        "context": {"rtl/widget.sv": (
            "module widget (input clk, input [7:0] a, output reg [7:0] y);\n"
            "  always @(posedge clk) y <= a;\nendmodule\n")},
    },
    "output": {"response": "SECRET"},
}


def test_optimization_runs_deterministic_lint_baseline(tmp_path):
    res = L.run_loop_case(_OPTIMIZE_REC, tmp_path)
    assert res["nature"] == "optimization"
    assert res["plugin_entry"] == "optimize_loop"
    assert res["lint_baseline"]["ran"] is True
    # optimization has no interface/solve step
    assert res["iface_ports"] == 0
    assert res["det_rtl"] is False


# Part D — the interface contract emitted from recovered ports.
def test_iface_to_contract_v_emits_valid_header():
    iface = [{"name": "clk", "dir": "input", "width": 1},
             {"name": "d", "dir": "input", "width": 8},
             {"name": "q", "dir": "output", "width": 8}]
    v = L._iface_to_contract_v(iface, "foo")
    assert "module foo (" in v
    assert "input clk" in v
    assert "input [7:0] d" in v
    assert "output [7:0] q" in v
    assert v.rstrip().endswith("endmodule")


@pytest.mark.skipif(not _DATASET.is_file(), reason="CVDP dataset not present")
@pytest.mark.skipif(not shutil.which("iverilog"), reason="iverilog not installed")
@pytest.mark.parametrize("rid,nature,conf_gated", [
    ("cvdp_copilot_convolutional_encoder_0010", "completion", True),
    ("cvdp_copilot_moving_average_0005", "functional_modification", False),
])
def test_standard_algorithm_records_solve_and_compile(tmp_path, rid, nature,
                                                      conf_gated):
    rec = None
    with _DATASET.open() as f:
        for line in f:
            r = json.loads(line)
            if r.get("id") == rid:
                rec = r
                break
    assert rec is not None, rid
    res = L.run_loop_case(rec, tmp_path)
    assert res["nature"] == nature
    assert res["det_rtl"] is True, "deterministic solver should emit RTL"
    assert res["iverilog_ok"] is True, "emitted RTL must compile"
    assert res["emit_path"] == "deterministic"
    # Part D: completion's verify chain gates the body on the recovered interface
    # contract; the conv-encoder body must conform. modify's verify uses
    # equivalence-check (not spec_conformance), so no conformance record.
    if conf_gated:
        assert res["conformance"]["ran"] is True
        assert res["conformance"]["conforms"] is True
    else:
        assert res.get("conformance") is None


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
