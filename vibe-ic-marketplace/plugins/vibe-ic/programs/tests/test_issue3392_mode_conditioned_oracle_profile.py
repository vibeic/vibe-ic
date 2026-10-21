"""Issue #3392: Tier-3 oracles receive source-bound mode profiles."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


PROGRAMS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "issue3392_professional_tb", PROGRAMS / "professional_tb_gen.py")
assert SPEC is not None and SPEC.loader is not None
SUBJECT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SUBJECT
SPEC.loader.exec_module(SUBJECT)

EXPERT = '''\
import cocotb
from cocotb.triggers import RisingEdge

@cocotb.test()
async def reference_model(dut):
    await RisingEdge(dut.clk)
    assert int(dut.status.value) >= 0
    dut._log.info("PROFESSIONAL_TB PASS 1/1")
'''


def _project(root: Path, field_prose: str) -> Path:
    docs = root / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "neutral_status",
        "top_ports": [
            {"name": "clk", "dir": "input", "width": 1},
            {"name": "mode", "dir": "input", "width": 1},
            {"name": "status", "dir": "output", "width": 2},
        ],
        "clock_domains": [{"name": "clk", "source_pin": "clk"}],
    }))
    (docs / "L2_FRS.json").write_text(json.dumps({
        "frs_sections": [{
            "title": "STATUS",
            "content": "### STATUS . EVENT_FLAG\n" + field_prose
                       + "\n### STATUS . READY\nREADY is always defined.",
            "evidence": "input/docs/registers.md",
        }],
    }))
    rtl = root / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "neutral_status.sv").write_text(
        "module neutral_status(input clk,mode,output [1:0] status); "
        "assign status={mode,1'b1}; endmodule\n")
    return root


def test_expert_reference_emits_source_bound_mode_profile(tmp_path):
    project = _project(
        tmp_path,
        "This flag is not meaningful if MODE=0 (see Control Register).")
    first = SUBJECT.generate(project)
    out = Path(first["out_dir"])
    (out / "expert_reference_tb.py").write_text(EXPERT)
    result = SUBJECT.generate(project)
    plan = json.loads((out / "verification_plan.json").read_text())
    expected = [{
        "register": "STATUS",
        "field": "EVENT_FLAG",
        "condition": "MODE=0 (see Control Register)",
        "statement": "This flag is not meaningful if MODE=0 (see Control Register).",
        "source": "phase1/generated_docs/L2_FRS.json",
        "oracle_policy": "do_not_assert_exact_field_value_when_condition_holds",
    }]
    assert result["dut_kind"] == "expert_reference"
    assert result["mode_conditioned_field_profiles"] == expected
    assert result["mode_conditioned_oracle_review_required"] is True
    assert plan["mode_conditioned_field_profiles"] == expected
    assert plan["mode_conditioned_oracle_review_required"] is True


def test_defined_exact_value_does_not_create_dont_care_profile(tmp_path):
    project = _project(tmp_path, "This flag must be zero if MODE=0.")
    result = SUBJECT.generate(project)
    plan = json.loads((Path(result["out_dir"]) / "verification_plan.json").read_text())
    assert "mode_conditioned_field_profiles" not in result
    assert "mode_conditioned_field_profiles" not in plan


def test_condition_without_field_heading_is_not_guessed(tmp_path):
    project = _project(
        tmp_path,
        "This flag is not meaningful if MODE=0.")
    l2 = project / "phase1/generated_docs/L2_FRS.json"
    l2.write_text(json.dumps({
        "frs_sections": [{"content": "This flag is not meaningful if MODE=0."}],
    }))
    assert SUBJECT.mode_conditioned_field_profiles(project) == []


@pytest.mark.parametrize("statement", [
    "This field is undefined when MODE=0.",
    "This signal is a don't-care if MODE=0.",
    "This value is a don’t care when MODE=0.",
])
def test_other_explicit_non_meaningful_phrases_are_source_bound(
        tmp_path, statement):
    project = _project(tmp_path, statement)
    profile, = SUBJECT.mode_conditioned_field_profiles(project)
    assert profile["register"] == "STATUS"
    assert profile["field"] == "EVENT_FLAG"
    assert profile["condition"] == "MODE=0"
    assert profile["statement"] == statement
