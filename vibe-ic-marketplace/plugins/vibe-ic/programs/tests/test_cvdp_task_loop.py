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


@pytest.mark.skipif(not _DATASET.is_file(), reason="CVDP dataset not present")
@pytest.mark.skipif(not shutil.which("iverilog"), reason="iverilog not installed")
@pytest.mark.parametrize("rid,nature", [
    ("cvdp_copilot_convolutional_encoder_0010", "completion"),
    ("cvdp_copilot_moving_average_0005", "functional_modification"),
])
def test_standard_algorithm_records_solve_and_compile(tmp_path, rid, nature):
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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
