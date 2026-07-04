#!/usr/bin/env python3
r"""test_cvdp_phase1_entry.py — the DETERMINISTIC Phase-1-entry CVDP driver.

ORGANIC-20260705 (cvdp-phase1-canonical-entry). Verifies the driver that forces
every CVDP record THROUGH the plugin's Phase-1 entry (not the legacy blind-author
Shape-C flow):
  * staging reads ONLY input.prompt + input.context — never output/harness (oracle);
  * staging is deterministic (same record → same files/bytes);
  * the input.context real `module (...)` header is placed where Phase-1's
    real-declaration extractor finds it (deterministic top_module);
  * the emit-path classifier honestly separates deterministic json-to-rtl from
    the needs_ai_backup (prose-body → spec-to-rtl) hand-off.

Run: python3 -m pytest programs/tests/test_cvdp_phase1_entry.py -q
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_BENCH = Path(__file__).resolve().parents[2] / "benchmark"
_MOD = _BENCH / "cvdp_phase1_entry.py"
_spec = importlib.util.spec_from_file_location("cvdp_phase1_entry", _MOD)
E = importlib.util.module_from_spec(_spec)
sys.modules["cvdp_phase1_entry"] = E
_spec.loader.exec_module(E)


_CTX_RTL = (
    "module decoder_64b66b (\n"
    "    input  wire        clk_in,\n"
    "    input  wire        rst_in,\n"
    "    input  wire [65:0] decoder_data_in,\n"
    "    output reg  [63:0] decoder_data_out\n"
    ");\nendmodule\n")

RECORD = {
    "id": "cvdp_copilot_demo_0001",
    "input": {
        "prompt": "Implement the module `decoder_64b66b` per the spec.",
        "context": {"rtl/decoder_64b66b.sv": _CTX_RTL},
    },
    # oracle — MUST never be read/staged by the Phase-1 entry.
    "output": {"response": "SECRET GOLDEN RTL", "context": {"x": "y"}},
    "harness": {"src": {"test.py": "SECRET COCOTB HARNESS"}},
}


def test_staging_reads_only_input_not_oracle(tmp_path):
    case = tmp_path / "case"
    E._stage_case(RECORD, case)
    # prompt + context staged
    assert (case / "input" / "phase1_prompt.md").read_text().startswith(
        "Implement the module")
    assert (case / "rtl" / "decoder_64b66b.sv").read_text() == _CTX_RTL
    # the oracle strings must appear NOWHERE under the staged case dir.
    blob = "".join(p.read_text(errors="ignore")
                   for p in case.rglob("*") if p.is_file())
    assert "SECRET GOLDEN RTL" not in blob
    assert "SECRET COCOTB HARNESS" not in blob


def test_staging_is_deterministic(tmp_path):
    def snapshot(root: Path):
        return {str(p.relative_to(root)): p.read_text(errors="ignore")
                for p in sorted(root.rglob("*")) if p.is_file()}
    a = tmp_path / "a"
    b = tmp_path / "b"
    E._stage_case(RECORD, a)
    E._stage_case(RECORD, b)
    assert snapshot(a) == snapshot(b)


def test_context_real_decl_is_placed_for_phase1_extractor(tmp_path):
    # the context RTL must be dropped into input/docs so Phase-1's
    # real-`module (...)`-declaration extractor recovers the true top_module.
    case = tmp_path / "case"
    E._stage_case(RECORD, case)
    docs = list((case / "input" / "docs").glob("*"))
    joined = "".join(p.read_text() for p in docs)
    assert "module decoder_64b66b (" in joined
    # cross-check: the plugin's own extractor recovers it from that doc text.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import phase1_doc_one_shot_runner as P
    assert P._doc_real_module_decl_name(
        {"c.txt": _CTX_RTL}) == "decoder_64b66b"


def test_classify_emit_needs_ai_backup_when_rtl_gen_waived(tmp_path):
    case = tmp_path / "case"
    (case / "phase1" / "generated_docs").mkdir(parents=True)
    (case / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "decoder_64b66b",
                    "top_ports": [{"name": "clk_in"}, {"name": "rst_in"}]}))
    (case / "reports" / "orchestrator").mkdir(parents=True)
    (case / "reports" / "orchestrator" / "phase2_one_shot.json").write_text(
        json.dumps({"steps": [{"name": "rtl_gen", "status": "WAIVED",
                               "note": "rtl_gen=null ... spec-to-rtl"}]}))
    res = E._classify_emit(case)
    assert res["top_module"] == "decoder_64b66b"
    assert res["top_ports_n"] == 2
    assert res["emit_path"] == "needs_ai_backup"
    assert res["rtl_files"] == []


def test_classify_emit_deterministic_when_json_to_rtl_fired(tmp_path):
    case = tmp_path / "case"
    (case / "phase1" / "generated_docs").mkdir(parents=True)
    (case / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json").write_text(
        json.dumps({"top_module": "fsm_top", "top_ports": []}))
    rtl = case / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "fsm_top.sv").write_text("module fsm_top(); endmodule\n")
    (case / "reports" / "orchestrator").mkdir(parents=True)
    (case / "reports" / "orchestrator" / "phase2_one_shot.json").write_text(
        json.dumps({"steps": [{"name": "rtl_gen", "status": "PASS",
                               "note": "deterministic RTL via fsm_table"}]}))
    res = E._classify_emit(case)
    assert res["emit_path"] == "deterministic"
    assert res["rtl_files"] == ["fsm_top.sv"]


def test_allowed_input_keys_exclude_oracle():
    assert "prompt" in E._ALLOWED_INPUT_KEYS
    assert "context" in E._ALLOWED_INPUT_KEYS
    assert "output" not in E._ALLOWED_INPUT_KEYS
    assert "harness" not in E._ALLOWED_INPUT_KEYS


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
