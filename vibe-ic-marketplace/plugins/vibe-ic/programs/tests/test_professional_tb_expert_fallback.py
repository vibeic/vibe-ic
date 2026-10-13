"""Tier-3 expert references must be consumable, persistent, and non-vacuous."""
from __future__ import annotations

import importlib.util
import ast
import hashlib
import json
import os
import re
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


def _native_signature_run(project):
    import shutil
    if not all(shutil.which(tool) for tool in ("iverilog", "cocotb-config", "make")):
        pytest.skip("native Icarus/cocotb tools unavailable")
    import design_one_shot_runner as runner
    import professional_tb_check as consumer
    step = runner.step_professional_tb_gen(project, "signature_unit", "neutral-unused")
    report = json.loads((project / "reports/phase2/gates/professional_tb.json").read_text())
    result_path = project / "consumer.json"
    rc = consumer.main([str(project), "--json", str(result_path)])
    result = json.loads(result_path.read_text())
    (project / "native-values.json").write_text(json.dumps({
        "step_status": step.status, "native_rc": report.get("cocotb_rc"),
        "junit": report.get("cocotb_test_denominator"), "consumer_rc": rc,
        "consumer": result}, indent=2) + "\n")
    return step, report, rc, result


def _actual_signature_events(project, out):
    log = (out / "cocotb_run.log").read_text()
    events = ast.literal_eval(re.search(r"ACTUAL_STORE_EVENTS (\[[^\n]*\])", log).group(1))
    expected = json.loads((project / "phase1/generated_docs/L10_TEST_CASES.json").read_text())[
        "fields"]["test_cases"][0]["expected_bytes"]
    assert events == [[int(address), value] for address, value in expected.items()]


@pytest.mark.parametrize("mode", ["complete", "missing-zero-word",
    "missing-zero-byte", "redirected-zero-word", "missing-nonzero-word",
    "wrong-zero-value"])
def test_issue3012_native_memory_signature_requires_actual_byte_stores(tmp_path, mode):
    project, out = _signature_project(tmp_path, mode)
    step, report, rc, result = _native_signature_run(project)
    expected = "PASS" if mode == "complete" else "FAIL"
    assert step.status == expected, (mode, report)
    assert result["verdict"] == expected, result
    assert rc == (0 if mode == "complete" else 1)
    assert report["ran_cocotb"] is True
    assert report["cocotb_test_denominator"]["tests"] == 1
    assert report["cocotb_rc"] == (0 if mode == "complete" else 2)
    assert json.loads((project / "phase1/generated_docs/L10_TEST_CASES.json").read_text())[
        "fields"]["test_cases"][0]["expected_bytes"]["32"] == 0
    if mode == "complete":
        _actual_signature_events(project, out)
    else:
        assert report["functional_mismatch"] is True


@pytest.mark.parametrize("active,edge", [(0, "posedge"), (1, "negedge")])
def test_issue3012_native_declared_commit_polarity_and_edge(tmp_path, active, edge):
    project, out = _signature_project(tmp_path, active=active, edge=edge)
    step, report, rc, result = _native_signature_run(project)
    assert (step.status, report["cocotb_rc"], rc, result["verdict"]) == ("PASS", 0, 0, "PASS")
    _actual_signature_events(project, out)


@pytest.mark.parametrize("invalid", ["missing-interface", "missing-expected",
    "missing-port", "duplicate-roles", "unbound-coroutine", "wide-writer",
    "out-of-range-address", "boolean-byte", "duplicate-address",
    "unknown-protocol", "wrong-clock-edge"])
def test_issue3012_declared_signature_without_usable_contract_is_unmeasured(tmp_path, invalid):
    project, out = _signature_project(tmp_path, invalid=invalid)
    import design_one_shot_runner as runner
    import professional_tb_check as consumer
    step = runner.step_professional_tb_gen(project, "signature_unit", "neutral-unused")
    result = consumer.check(project)
    result_path = project / "consumer.json"
    consumer_rc = consumer.main([str(project), "--json", str(result_path)])
    report = json.loads((project / "reports/phase2/gates/professional_tb.json").read_text())
    (project / "native-values.json").write_text(json.dumps({
        "step_status": step.status, "native_rc": report.get("cocotb_rc"),
        "ran_cocotb": report.get("ran_cocotb"), "consumer_rc": consumer_rc,
        "consumer": result}, indent=2) + "\n")
    assert step.status == "NOT_MEASURED", (invalid, step)
    assert result["verdict"] == "NOT_CHECKED", result
    assert consumer_rc == 2
    assert SUBJECT.main([str(project)]) == 2
    assert not (out / "results.xml").exists(), "invalid contract launched native simulation"
    assert not (out / "cocotb_run.log").exists()


@pytest.mark.parametrize("mutation", ["missing-observation", "changed-expectation",
                                      "removed-declaration"])
def test_issue3012_current_signature_cannot_reuse_prior_clean_observation(tmp_path, mutation):
    project, out = _signature_project(tmp_path)
    step, report, rc, result = _native_signature_run(project)
    assert (step.status, rc, result["verdict"]) == ("PASS", 0, "PASS")
    if mutation == "missing-observation":
        observation = out / "memory_signature_signature_result.json"
        if observation.exists():
            observation.rename(out / "preserved-prior-observation.json")
    elif mutation == "changed-expectation":
        l10 = project / "phase1/generated_docs/L10_TEST_CASES.json"
        changed = json.loads(l10.read_text())
        changed["fields"]["test_cases"][0]["expected_bytes"]["32"] = 1
        l10.write_text(json.dumps(changed))
    else:
        l10 = project / "phase1/generated_docs/L10_TEST_CASES.json"
        l10.rename(project / "preserved-prior-L10.json")
    import professional_tb_check as consumer
    result = consumer.check(project)
    assert result["verdict"] == "NOT_CHECKED", result
    assert consumer.main([str(project)]) == 2


def test_issue3012_filtered_native_case_cannot_inherit_an_old_store_record(tmp_path, monkeypatch):
    import shutil
    project, out = _signature_project(tmp_path)
    expert = out / "expert_reference_tb.py"
    expert.write_text(expert.read_text() + '''
@cocotb.test()
async def other_positive(dut):
    await Timer(1, unit="ns")
    assert int(dut.done.value) in (0, 1)
    dut._log.info("PROFESSIONAL_TB PASS unrelated case")
''')
    first_step, first_report, first_rc, first_result = _native_signature_run(project)
    assert (first_step.status, first_rc, first_result["verdict"]) == ("PASS", 0, "PASS")
    preserved = project / "preserved-first-run"
    shutil.copytree(out, preserved)
    for source in (project / "native-values.json", project / "consumer.json",
                   project / "reports/phase2/gates/professional_tb.json"):
        shutil.copy2(source, preserved / source.name)
    monkeypatch.setenv("COCOTB_TEST_FILTER", "other_positive$")
    step, report, rc, result = _native_signature_run(project)
    assert report["cocotb_rc"] == 0, report
    assert report["cocotb_test_denominator"]["passed"] == 1
    assert step.status == "NOT_MEASURED", report
    assert (rc, result["verdict"]) == (2, "NOT_CHECKED"), result


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


_CURRENT_VALUE_EXPERT = '''\
import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def current_value(dut):
    for sample in [0, 1, 1, 0]:
        dut.ck4.value = 0
        dut.sample.value = sample
        await Timer(2, unit="ns")
        dut.ck4.value = 1
        await Timer(2, unit="ns")
        actual = int(dut.result.value)
        expected = EXPECTED
        dut._log.info("CURRENT_VALUE sample=%d actual=%d expected=%d", sample, actual, expected)
        assert actual == expected, (sample, actual, expected)
    dut._log.info("PROFESSIONAL_TB PASS current source VALUE")
'''


def _native_current_value_arm(project, label):
    """Retain the real producer, both engine outputs and compiled identities."""
    import design_one_shot_runner as runner
    import _sim_results_bridge as bridge
    out = project / "phase2/stage1/sim_professional/converter"
    step = runner.step_professional_tb_gen(project, "converter", "neutral-unused")
    report = json.loads((project / "reports/phase2/gates/professional_tb.json").read_text())
    archive = project / "native-qualification" / label
    archive.mkdir(parents=True)
    for name in ("results.xml", "results_icarus.xml", "results_verilator.xml",
                 "cocotb_run.log", "cocotb_run_verilator.log", "sim_differential.json",
                 "tb_converter.py", "expert_reference_tb.py", "Makefile"):
        path = out / name
        if path.is_file():
            shutil.copy2(path, archive / name)
    models = {}
    for engine, rel in (("icarus", "sim_build/sim.vvp"),
                        ("verilator", "sim_build_verilator/Vtop")):
        path = out / rel
        if path.is_file():
            models[engine] = hashlib.sha256(path.read_bytes()).hexdigest()
            shutil.copy2(path, archive / (engine + "-compiled-model"))
    rtl = project / "phase2/stage1/rtl/converter.sv"
    result = {
        "label": label, "step_status": step.status, "step_detail": step.detail,
        "runtime_subject": str(Path(runner.__file__).resolve()),
        "runtime_subject_sha256": hashlib.sha256(Path(runner.__file__).read_bytes()).hexdigest(),
        "native_report": report, "junit_icarus": bridge.parse_junit(out / "results.xml"),
        "junit_verilator": bridge.parse_junit(out / "results_verilator.xml"),
        "rtl_sha256": hashlib.sha256(rtl.read_bytes()).hexdigest(),
        "rtl_mtime_ns": rtl.stat().st_mtime_ns, "compiled_sha256": models,
    }
    shutil.copy2(rtl, archive / rtl.name)
    (archive / "producer.receipt.json").write_text(json.dumps(result, indent=2) + "\n")
    return step, result


@pytest.mark.parametrize("mode", ["direct", "dual"])
def test_native_current_rtl_value_survives_preserved_source_mtime(tmp_path, mode):
    """The same semantic qualification must fail on an old compiled VALUE.

    This deliberately expects B's *new* value on base and candidate alike;
    it does not accept the observed stale failure as a passing diagnostic.
    """
    tools = ("iverilog", "cocotb-config", "make") + (("verilator",) if mode == "dual" else ())
    if not all(shutil.which(tool) for tool in tools):
        pytest.skip("native simulator/cocotb tools unavailable")
    project = _project(tmp_path / mode)
    switch = project / "phase3/librelane_switch.json"
    switch.parent.mkdir(parents=True)
    switch.write_text(json.dumps({"steps": {"4": mode}}))
    out = project / "phase2/stage1/sim_professional/converter"
    out.mkdir(parents=True)
    expert = out / "expert_reference_tb.py"
    rtl = project / "phase2/stage1/rtl/converter.sv"
    original = rtl.read_text()
    old_mtime = 1_600_000_000_000_000_000
    os.utime(rtl, ns=(old_mtime, old_mtime))
    expert.write_text(_CURRENT_VALUE_EXPERT.replace("EXPECTED", "sample"))
    first, a = _native_current_value_arm(project, "A")
    assert first.status == "PASS", a
    assert a["junit_icarus"]["passed"] == 1
    if mode == "dual":
        assert a["junit_verilator"]["passed"] == 1

    rtl.write_text(original.replace("result <= sample", "result <= ~sample"))
    os.utime(rtl, ns=(old_mtime, old_mtime))
    expert.write_text(_CURRENT_VALUE_EXPERT.replace("EXPECTED", "1 - sample"))
    changed, b = _native_current_value_arm(project, "B-preserved-mtime")
    assert a["rtl_sha256"] != b["rtl_sha256"]
    assert a["rtl_mtime_ns"] == b["rtl_mtime_ns"] == old_mtime
    assert changed.status == "PASS", b
    assert b["junit_icarus"]["passed"] == 1
    if mode == "dual":
        assert b["junit_verilator"]["passed"] == 1

    # Keep every old build before measuring the same B source / oracle cleanly.
    for directory in ("sim_build", "sim_build_verilator"):
        path = out / directory
        if path.is_dir():
            path.rename(project / ("preserved-B-" + directory))
    clean, b_clean = _native_current_value_arm(project, "B-clean")
    assert clean.status == "PASS", b_clean
    assert b_clean["rtl_sha256"] == b["rtl_sha256"]
    assert b_clean["junit_icarus"]["passed"] == 1
    if mode == "dual":
        assert b_clean["junit_verilator"]["passed"] == 1

    # Keep B's expected-value oracle and build; a truly bad new RTL must FAIL.
    rtl.write_text(original)
    os.utime(rtl, ns=(old_mtime, old_mtime))
    bad, c = _native_current_value_arm(project, "C-real-bad-value")
    assert bad.status == "FAIL", c
    assert c["junit_icarus"]["failures"] == 1
    if mode == "dual":
        assert c["junit_verilator"]["failures"] == 1
