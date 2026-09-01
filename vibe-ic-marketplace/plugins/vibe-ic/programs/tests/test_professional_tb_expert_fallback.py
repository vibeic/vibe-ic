"""Tier-3 expert references must be consumable, persistent, and non-vacuous."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


PROGRAMS = Path(os.environ.get(
    "VIBEIC_PROFESSIONAL_TB_SUBJECT",
    str(Path(__file__).resolve().parents[1]),
)).resolve()
SPEC = importlib.util.spec_from_file_location(
    "professional_tb_subject", PROGRAMS / "professional_tb_gen.py")
assert SPEC is not None and SPEC.loader is not None
SUBJECT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SUBJECT
SPEC.loader.exec_module(SUBJECT)


EXPERT = '''\
import cocotb
from cocotb.triggers import RisingEdge

@cocotb.test()
async def reference_model(dut):
    await RisingEdge(dut.ck4)
    assert int(dut.result.value) == int(dut.sample.value)
    dut._log.info("PROFESSIONAL_TB PASS 1/1")
'''


def _project(root: Path) -> Path:
    docs = root / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "converter",
        "top_ports": [
            {"name": "sample", "dir": "input", "width": 1},
            {"name": "result", "dir": "output", "width": 1},
            {"name": "ck4", "dir": "input", "width": 1},
        ],
        "clock_domains": [{"name": "ck4", "source_pin": "ck4"}],
    }))
    (docs / "L8_TIMING_WAVEFORM.json").write_text(json.dumps({
        "clocks": [{"name": "CK4", "source_pin": "ck4",
                    "freq_hz": 1_000_000, "period_ns": 1000}],
    }))
    rtl = root / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    (rtl / "converter.sv").write_text(
        "module converter(input sample, input ck4, output reg result); "
        "always @(posedge ck4) result <= sample; endmodule\n")
    return root


def test_resetless_phase_clock_is_used_without_fabricated_reset(tmp_path):
    result = SUBJECT.generate(_project(tmp_path))
    out = Path(result["out_dir"])
    tb = (out / "tb_converter.py").read_text()
    assertions = (out / "converter_assertions.sva").read_text()
    assert 'CLK = "ck4"' in tb
    assert "RST = None" in tb
    assert "HALF_NS = 500" in tb
    assert "module converter_asserts (input ck4);" in assertions
    assert "input rst" not in assertions


def test_expert_reference_survives_regeneration_and_closes_hook(tmp_path):
    project = _project(tmp_path)
    first = SUBJECT.generate(project)
    out = Path(first["out_dir"])
    assert first["reference_model_tier"] == "hook_unfilled"
    (out / "expert_reference_tb.py").write_text(EXPERT)

    second = SUBJECT.generate(project)
    assert second["dut_kind"] == "expert_reference"
    assert second["reference_model_tier"] == "expert_filled"
    assert (out / "tb_converter.py").read_text() == EXPERT
    plan = json.loads((out / "verification_plan.json").read_text())
    assert plan["reference_model_tier"] == "expert_filled"


def test_skip_based_expert_source_is_rejected(tmp_path):
    project = _project(tmp_path)
    first = SUBJECT.generate(project)
    out = Path(first["out_dir"])
    (out / "expert_reference_tb.py").write_text(
        EXPERT.replace("assert int(dut.result.value) == int(dut.sample.value)",
                       "raise cocotb.result.TestSkip('unfilled')"))
    second = SUBJECT.generate(project)
    assert second["dut_kind"] == "generic"
    assert second["reference_model_tier"] == "hook_unfilled"
    assert "TestSkip" in (out / "tb_converter.py").read_text()
