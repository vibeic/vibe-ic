"""Tier-3 expert references must be consumable, persistent, and non-vacuous."""
from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import sys
import shutil
from pathlib import Path

import pytest


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


@pytest.mark.skipif(shutil.which("yosys") is None, reason="native Yosys is required")
def test_undeclared_ports_use_native_interface_and_keep_expert_hook(tmp_path):
    project = _project(tmp_path)
    document = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    contents = json.loads(document.read_text())
    contents["top_ports"] = []
    document.write_text(json.dumps(contents))
    original = document.read_text()
    (project / "phase2/stage1/rtl/converter.sv").write_text(
        "module converter #(parameter WIDTH = 7) "
        "(input [WIDTH-1:0] sample, input ck4, output reg [WIDTH-1:0] result); "
        "always @(posedge ck4) result <= sample; endmodule\n")

    shape, reason = SUBJECT.classify_dut(project, "unknown")
    assert shape is not None, reason
    assert shape["kind"] == "generic"
    assert {port["name"]: (port["dir"], port["numeric_width"])
            for port in shape["ports"]} == {
                "sample": ("input", 7), "ck4": ("input", 1),
                "result": ("output", 7)}
    first = SUBJECT.generate(project)
    assert first["reference_model_tier"] == "hook_unfilled"
    out = Path(first["out_dir"])
    (out / "expert_reference_tb.py").write_text(EXPERT)
    second = SUBJECT.generate(project)
    assert second["reference_model_tier"] == "expert_filled"
    assert (out / "tb_converter.py").read_text() == EXPERT
    assert document.read_text() == original


@pytest.mark.skipif(shutil.which("yosys") is None, reason="native Yosys is required")
def test_native_interface_failure_does_not_emit_testbench(tmp_path):
    project = _project(tmp_path)
    document = project / "phase1/generated_docs/L9_INTEGRATION_SPEC.json"
    contents = json.loads(document.read_text())
    contents["top_ports"] = []
    document.write_text(json.dumps(contents))
    (project / "phase2/stage1/rtl/converter.sv").write_text(
        "module converter(input sample, output result); syntax error; endmodule\n")

    result = SUBJECT.generate(project)
    assert result["status"] == "SKIP"
    assert "Native interface elaboration failed" in result["reason"]
    assert not (project / "phase2/stage1/sim_professional").exists()


def test_generator_names_only_the_expert_model_it_measured(tmp_path):
    project = _project(tmp_path)
    first = SUBJECT.generate(project)
    assert "reference_model_sha256" not in first
    (Path(first["out_dir"]) / "expert_reference_tb.py").write_text(EXPERT)

    second = SUBJECT.generate(project)
    assert second["reference_model_sha256"] == hashlib.sha256(EXPERT.encode()).hexdigest()


def test_model_identity_names_the_loaded_bytes_when_source_changes(tmp_path, monkeypatch):
    project = _project(tmp_path)
    out = Path(SUBJECT.generate(project)["out_dir"])
    source = out / "expert_reference_tb.py"
    source.write_text(EXPERT)
    real_build = SUBJECT.build_coverage_model

    def replace_after_loading(shape):
        source.write_text(EXPERT + "\n# revised after loading\n")
        return real_build(shape)

    monkeypatch.setattr(SUBJECT, "build_coverage_model", replace_after_loading)
    result = SUBJECT.generate(project)
    emitted = (out / "tb_converter.py").read_text()
    assert emitted == EXPERT
    assert result["reference_model_sha256"] == hashlib.sha256(emitted.encode()).hexdigest()
    assert result["reference_model_sha256"] != SUBJECT.reference_model_identity(out)


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


_SIGNATURE_EXPERT = '''\
import json
from pathlib import Path
import cocotb
from cocotb.triggers import Timer, RisingEdge, FallingEdge, ReadOnly
from cocotb.clock import Clock

CASE = json.loads((Path(__file__).resolve().parents[4] /
    "phase1/generated_docs/L10_TEST_CASES.json").read_text())["fields"]["test_cases"][0]

@cocotb.test()
async def signature_result(dut):
    # The vulnerable expert model starts external storage at zero. Expected
    # zero bytes must remain zero; store-event closure is the producer's job.
    memory = {address: 0 for address in range(64)}
    writes = []
    dut.clk.value = 0
    dut.rst.value = 1
    dut.read_data.value = 0
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    edge = FallingEdge if CASE.get("interface", {}).get("edge") == "negedge" else RisingEdge
    active = CASE.get("interface", {}).get("active_level", 1)
    for cycle in range(16):
        await edge(dut.clk)
        # External synchronous storage commits the previous registered
        # transaction, before the DUT updates its outputs through NBA.
        if int(dut.wr.value) == active:
            address, value = int(dut.addr.value), int(dut.data.value)
            memory[address] = value
            writes.append([address, value])
        await ReadOnly()
        if cycle == 1:
            await Timer(1, unit="ns")
            dut.rst.value = 0
    for address, expected in CASE.get("expected_bytes", {}).items():
        assert memory[int(address)] == expected, (address, memory[int(address)], expected)
    assert int(dut.done.value) == 1
    dut._log.info("ACTUAL_STORE_EVENTS %s", writes)
    dut._log.info("PROFESSIONAL_TB PASS")
'''


def _signature_project(root, mode="complete", *, active=1, edge="posedge",
                       invalid=None):
    expected = {str(address): 0 for address in range(32, 36)}
    expected.update({"36": 0x78, "37": 0x56, "38": 0x34, "39": 0x12})
    case = {"id": "signature_result", "category": "memory_signature",
            "interface": {"clock": "clk", "edge": edge,
                          "write_enable": "wr", "active_level": active,
                          "write_address": "addr", "write_data": "data"},
            "expected_bytes": expected}
    if invalid == "missing-interface":
        case.pop("interface")
    elif invalid == "missing-expected":
        case.pop("expected_bytes")
    elif invalid == "missing-port":
        case["interface"]["write_address"] = "absent_address"
    elif invalid == "duplicate-roles":
        case["interface"]["write_address"] = "data"
    elif invalid == "unbound-coroutine":
        case["id"] = "absent_coroutine"
    elif invalid == "out-of-range-address":
        case["expected_bytes"]["64"] = 0
    elif invalid == "boolean-byte":
        case["expected_bytes"]["32"] = False
    elif invalid == "duplicate-address":
        case["expected_bytes"]["032"] = 0
    elif invalid == "unknown-protocol":
        case["interface"]["ready"] = "read_data"
    elif invalid == "wrong-clock-edge":
        case["interface"]["edge"] = "negedge" if edge == "posedge" else "posedge"
    data_width = 16 if invalid == "wide-writer" else 8
    docs = root / "phase1/generated_docs"
    docs.mkdir(parents=True)
    input_docs = root / "input/docs"
    input_docs.mkdir(parents=True)
    l10 = json.dumps({"fields": {"test_cases": [case]}}, indent=2) + "\n"
    # Authored typed INPUT is copied verbatim into the consuming L10 layer.
    (input_docs / "L10_TEST_CASES.json").write_text(l10)
    (docs / "L10_TEST_CASES.json").write_text(l10)
    (input_docs / "memory_contract.md").write_text(
        "External byte storage commits the previous registered transaction "
        "on the declared clock edge. Every expected byte address must receive "
        "a real write, including zero-valued bytes; completion alone is insufficient.\n")
    (docs / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({
        "top_module": "signature_unit", "ic_class": "digital_cmd_driven",
        "top_ports": [
            {"name": "clk", "dir": "input", "width": 1},
            {"name": "rst", "dir": "input", "width": 1},
            {"name": "read_data", "dir": "input", "width": 8},
            {"name": "wr", "dir": "output", "width": 1},
            {"name": "addr", "dir": "output", "width": 6},
            {"name": "data", "dir": "output", "width": data_width},
            {"name": "done", "dir": "output", "width": 1}],
        "clocks": [{"name": "clk", "edge": edge, "period_ns": 10}],
        "reset_domains": [{"name": "rst", "polarity": "active_high"}],
    }))
    rtl = root / "phase2/stage1/rtl"
    rtl.mkdir(parents=True)
    condition = {"complete": "1", "missing-zero-word": "cycle>=4",
                 "missing-zero-byte": "cycle!=2", "redirected-zero-word": "1",
                 "missing-nonzero-word": "cycle<4", "wrong-zero-value": "1"}[mode]
    offset = "((cycle<4) ? 16 : 0)" if mode == "redirected-zero-word" else "0"
    zero = "((cycle==2) ? 1 : 0)" if mode == "wrong-zero-value" else "0"
    (rtl / "signature_unit.v").write_text(f'''
module signature_unit(input clk, input rst, input [7:0] read_data,
 output reg wr, output reg [5:0] addr, output reg [{data_width-1}:0] data,
 output reg done);
reg [3:0] cycle;
initial begin cycle=0; wr={1-active}; addr=0; data=0; done=0; end
always @({edge} clk) begin
 if (rst) begin cycle<=0; wr<={1-active}; addr<=0; data<=0; done<=0; end
 else begin
  cycle<=cycle+1; wr<={1-active};
  if (cycle<8) begin
   if ({condition}) wr<={active};
   addr<=32+cycle+{offset};
   case (cycle)
    4: data<=8'h78; 5: data<=8'h56; 6: data<=8'h34; 7: data<=8'h12;
    default: data<={zero};
   endcase
  end
  if (cycle==8) done<=1;
 end
end
endmodule
''')
    out = root / "phase2/stage1/sim_professional/signature_unit"
    out.mkdir(parents=True)
    (out / "expert_reference_tb.py").write_text(_SIGNATURE_EXPERT)
    return root, out


@pytest.mark.parametrize("invalid", ["missing-interface", "missing-expected",
    "missing-port", "duplicate-roles", "unbound-coroutine", "wide-writer",
    "out-of-range-address", "boolean-byte", "duplicate-address",
    "unknown-protocol", "wrong-clock-edge"])
def test_issue3012_declared_signature_without_usable_contract_is_unmeasured(tmp_path, invalid):
    project, out = _signature_project(tmp_path, invalid=invalid)
    assert SUBJECT.main([str(project)]) == 2
    assert not (out / "results.xml").exists(), "invalid contract launched native simulation"
    assert not (out / "cocotb_run.log").exists()


def test_issue3012_typed_bundle_remains_current_for_existing_coverage_consumer(tmp_path):
    project, out = _signature_project(tmp_path)
    generated = SUBJECT.generate(project)
    import verilator_coverage_measure as coverage
    plan = coverage._professional_bundle(out / "tb_signature_unit.py")
    assert plan["dut_kind"] == generated["dut_kind"] == "expert_reference"
    assert plan["reference_model_tier"] == "expert_filled"


def test_issue3012_changed_expert_source_still_refuses_coverage(tmp_path):
    project, out = _signature_project(tmp_path)
    SUBJECT.generate(project)
    expert = out / "expert_reference_tb.py"
    expert.write_text(expert.read_text().replace("range(16)", "range(17)"))
    import verilator_coverage_measure as coverage
    with pytest.raises(SystemExit, match="HOOK_UNFILLED_OR_STALE"):
        coverage._professional_bundle(out / "tb_signature_unit.py")
