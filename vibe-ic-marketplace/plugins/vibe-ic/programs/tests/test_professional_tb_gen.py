"""Tests for professional_tb_gen — deterministic pro-TB generation from L-docs.

Pure/structural tests (no container/sim). The full cocotb run (208/208 on the
spm bit-serial multiplier) is exercised in the commercial-PDK/clean-run integration.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

import pytest
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import professional_tb_gen as T  # noqa: E402


def _mk_spm_project(tmp: Path) -> Path:
    """A minimal project: L9 interface (x parametric bus, y/p serial, clk/rst)
    + L2 prose (multiplier) + a parametric RTL (parameter size = 32)."""
    gd = tmp / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"fields": {
        "top_module": "spm",
        "top_ports": [
            {"name": "clk", "dir": "input", "width": 1},
            {"name": "rst", "dir": "input", "width": 1},
            {"name": "x", "dir": "input"},           # parametric width (no number)
            {"name": "y", "dir": "input", "width": 1},
            {"name": "p", "dir": "output", "width": 1}],
        "clocks": [{"name": "clk", "edge": "posedge", "period_ns": 10}],
        "reset_domains": [{"name": "rst", "polarity": "active_high",
                           "sync": "sync"}],
    }}))
    (gd / "L2_FRS.json").write_text(json.dumps({"frs_sections": [
        {"title": "Function", "content": "serial-parallel multiplier "
         "p = (x * y) mod 2^N"}]}))
    # Use the filename Phase 1 ACTUALLY writes. This fixture previously wrote
    # `L16_COMPLIANCE.json`, a name that exists in ZERO real runs — so the test
    # passed while the production read path was dead in every real run. A
    # fixture that invents the file the code happens to open cannot fail.
    (gd / "L16_COMPLIANCE_PROPERTIES.json").write_text(json.dumps({
        "properties": [
            {"english_form": "x must not change during a multiply",
             "anchor_token": "must"}]}))
    rtl = tmp / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "spm.v").write_text(
        "module spm #(parameter size = 32)("
        "input clk, input rst, input [size-1:0] x, input y, output p);\n"
        "endmodule\n")
    return tmp


def test_classify_serial_stream(tmp_path):
    proj = _mk_spm_project(tmp_path)
    shape, why = T.classify_dut(proj, "digital_arithmetic_primitive")
    assert shape is not None, why
    assert shape["kind"] == "serial_stream"
    assert shape["x_port"] == "x" and shape["y_port"] == "y"
    assert shape["p_port"] == "p"
    assert shape["operator"] == "*"


def test_width_resolves_from_rtl_param(tmp_path):
    proj = _mk_spm_project(tmp_path)
    _, ports = T._aog._load_top_ports(proj)
    assert T._resolve_tb_width(proj, ports) == 32   # DUT compiled at size=32


def test_generate_emits_streaming_tb(tmp_path):
    proj = _mk_spm_project(tmp_path)
    res = T.generate(proj)
    assert res["status"] == "PASS"
    assert res["dut_kind"] == "serial_stream"
    assert res["reference_model_tier"] == "streaming_bounded_latency"
    out = Path(res["out_dir"])
    tb = (out / "tb_spm.py").read_text()
    # the streaming scoreboard + coverage + reference are present
    assert "streaming scoreboard locked" in tb
    assert "def _ref(xv, yv)" in tb and "(xv * yv)" in tb
    assert "MAX_LATENCY" in tb and "professional_stream_test" in tb
    assert "N = 32" in tb
    # coverage model + assertions + makefile + vplan emitted
    cov = json.loads((out / "spm_coverage_model.json").read_text())
    assert cov["fields"]["covergroups"][0]["coverpoints"]
    sva = (out / "spm_assertions.sva").read_text()
    assert "assert property" in sva and "isunknown" in sva
    assert (out / "Makefile").is_file()
    assert (out / "verification_plan.json").is_file()


def test_reset_initialises_all_data_inputs_before_asserting(tmp_path):
    # REGRESSION (spm serial-multiplier fail): the generated _reset() MUST drive
    # every data input to a known 0 BEFORE asserting reset, so no X propagates
    # into the datapath / streaming scoreboard during power-up. Without this the
    # bounded-latency + bit-order calibrator locked a WRONG (order, latency) and
    # produced 203/208 false mismatches on functionally-correct RTL; with it the
    # SAME RTL scores 208/208. chip-AGNOSTIC: inputs derived from the interface.
    proj = _mk_spm_project(tmp_path)
    res = T.generate(proj)
    tb = (Path(res["out_dir"]) / "tb_spm.py").read_text()
    # the data inputs are enumerated (x, y) and clk/rst are NOT reset-driven
    assert "DUT_INPUTS = [" in tb
    dut_inputs_line = next(l for l in tb.splitlines()
                           if l.startswith("DUT_INPUTS ="))
    assert "'x'" in dut_inputs_line and "'y'" in dut_inputs_line
    assert "'clk'" not in dut_inputs_line and "'rst'" not in dut_inputs_line
    # ordering: the input-zeroing loop appears BEFORE reset is asserted
    body = tb.split("async def _reset(dut):", 1)[1]
    zero_at = body.index("for _sig in DUT_INPUTS")
    assert_at = body.index("getattr(dut, RST).value = 1")
    assert zero_at < assert_at, "inputs must be zeroed before reset is asserted"
    assert ".value = 0" in body[zero_at:assert_at]


def test_reset_zeroes_inputs_for_parallel_arith(tmp_path):
    # chip-AGNOSTIC: the same input-zeroing must appear for a parallel-arith DUT
    # (different emit path, same _emit_common_header) — the operand ports a/b are
    # enumerated in DUT_INPUTS, clk/rst are not.
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"fields": {
        "top_module": "adder",
        "top_ports": [{"name": "clk", "dir": "input", "width": 1},
                      {"name": "rst", "dir": "input", "width": 1},
                      {"name": "a", "dir": "input", "width": 8},
                      {"name": "b", "dir": "input", "width": 8},
                      {"name": "sum", "dir": "output", "width": 8}],
        "clocks": [{"name": "clk", "edge": "posedge", "period_ns": 10}],
        "reset_domains": [{"name": "rst", "polarity": "active_high"}]}}))
    (gd / "L2_FRS.json").write_text(json.dumps({"frs_sections": [
        {"title": "Function", "content": "sum = a + b"}]}))
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True)
    (rtl / "adder.v").write_text(
        "module adder(input clk, rst, input [7:0] a, b, output [7:0] sum);"
        "endmodule\n")
    res = T.generate(tmp_path)
    tb = (Path(res["out_dir"]) / "tb_adder.py").read_text()
    dut_inputs_line = next(l for l in tb.splitlines()
                           if l.startswith("DUT_INPUTS ="))
    assert "'a'" in dut_inputs_line and "'b'" in dut_inputs_line
    assert "'clk'" not in dut_inputs_line and "'rst'" not in dut_inputs_line
    body = tb.split("async def _reset(dut):", 1)[1]
    assert body.index("for _sig in DUT_INPUTS") < body.index(
        "getattr(dut, RST).value = 1")


def test_coverage_model_has_bins_and_cross(tmp_path):
    proj = _mk_spm_project(tmp_path)
    shape, _ = T.classify_dut(proj, "digital_arithmetic_primitive")
    cov = T.build_coverage_model(shape)
    cps = cov["fields"]["covergroups"][0]["coverpoints"]
    assert len(cps) >= 2
    names = {b["name"] for b in cps[0]["bins"]}
    assert {"zero", "one", "max"} <= names
    assert cov["fields"]["covergroups"][0]["crosses"]


def test_generic_class_emits_nonvacuous_hook(tmp_path):
    # A DUT with no closed-form ref + no serial shape -> generic hook that
    # SKIPs (never a vacuous pass).
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"fields": {
        "top_module": "widget",
        "top_ports": [{"name": "clk", "dir": "input", "width": 1},
                      {"name": "rst", "dir": "input", "width": 1},
                      {"name": "ctrl", "dir": "input", "width": 4},
                      {"name": "status", "dir": "output", "width": 4}],
        "clocks": [{"name": "clk", "edge": "posedge", "period_ns": 10}],
        "reset_domains": [{"name": "rst", "polarity": "active_high"}]}}))
    (tmp_path / "phase2" / "stage1" / "rtl").mkdir(parents=True)
    (tmp_path / "phase2" / "stage1" / "rtl" / "widget.v").write_text(
        "module widget(input clk, rst, input [3:0] ctrl, output [3:0] status);"
        "endmodule\n")
    res = T.generate(tmp_path)
    assert res["dut_kind"] == "generic"
    tb = (Path(res["out_dir"]) / "tb_widget.py").read_text()
    assert "TestSkip" in tb and "unfilled" in tb   # never a vacuous PASS


# Requested operand populations use the native arithmetic producer and consumers.
import design_one_shot_runner as D
import cpu_functional_oracle_waiver_check as G
import phase1_doc_one_shot_runner as R

def _random_goal_project(root, count=64, operator='*', width=8, serial=False):
    docs=root/'input/docs'; docs.mkdir(parents=True)
    text=f'layer: L7\n# Functional verification\n| Test category | Pass criterion | Scope |\n|---|---|---|\n| Random arithmetic functional equivalence | 100% PASS (binary) | Random >= {count} operand pairs (x, y), all matching the independent modulo model |\n'
    (docs/'L7_verification_plan.md').write_text(text)
    cases=R._harvest_test_cases_from_input_tables({'L7_verification_plan.md':text})
    assert len(cases)==1 and cases[0]['kind']=='coverage_goal', cases
    gd=root/'phase1/generated_docs'; gd.mkdir(parents=True)
    ports=[{'name':'clk','dir':'input','width':1},{'name':'rst','dir':'input','width':1},{'name':'x','dir':'input','width':width},{'name':'y','dir':'input','width':1 if serial else width},{'name':'p','dir':'output','width':1 if serial else width}]
    (gd/'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'fields':{'top_module':'neutral_arithmetic','ic_class':'digital_arithmetic_primitive','top_ports':ports,'clocks':[{'name':'clk','period_ns':10}],'reset_domains':[{'name':'rst','polarity':'active_high','sync':'sync'}]}}))
    (gd/'L2_FRS.json').write_text(json.dumps({'frs_sections':[{'title':'Function','content':f'p = (x {operator} y) mod 2^{width}'}]}))
    (gd/'L10_TEST_CASES.json').write_text(json.dumps({'test_cases':cases}))
    rtl=root/'phase2/stage1/rtl'; rtl.mkdir(parents=True)
    if not serial:
        body=f'`timescale 1ns/1ps\nmodule neutral_arithmetic(input clk,rst,input [{width-1}:0] x,y,output [{width-1}:0] p); assign p=x {operator} y; endmodule\n'
    else:
        # LSB serial multiplication, full reset between independently sampled pairs.
        body=f'''`timescale 1ns/1ps
module neutral_arithmetic(input clk,rst,input [{width-1}:0] x,input y,output reg p);
reg [{width-1}:0] accum;
reg [{width-1}:0] next_accum;
always @* next_accum = (accum >> 1) + (y ? x : 0);
always @(posedge clk) if (rst) begin accum <= 0; p <= 0; end
else begin p <= next_accum[0]; accum <= next_accum; end
endmodule
'''
    (rtl/'neutral_arithmetic.v').write_text(body)
    (root/'plugin_output').mkdir()
    (root/'plugin_output/declaration.json').write_text(json.dumps({'bit_order':'LSB_first','latency_cycles':1,'integer_encoding':'unsigned','reset_polarity':'active_high'}))
    return cases[0]


def _random_goal_native(root, monkeypatch):
    old=os.environ.get('PYTHONPATH','')
    monkeypatch.setenv('PYTHONPATH',str(PROG)+os.pathsep+old)
    step=D.step_professional_tb_gen(root, 'neutral_arithmetic', '')
    (root/'native-step.json').write_text(json.dumps(step.__dict__, default=str, indent=2))
    assert step.status=='PASS', step.detail
    return root/'phase2/stage1/sim_professional/neutral_arithmetic'



@pytest.mark.timeout(120)
@pytest.mark.parametrize('count,width', [(64,4),(10000,8)])
def test_requested_random_pairs_are_measured_before_step4_pass(tmp_path,monkeypatch,count,width):
    _random_goal_project(tmp_path,count,'*',width,True)
    out=_random_goal_native(tmp_path,monkeypatch)
    # Both actual Step4 entry branches must consume the quantitative goal.
    professional=D.step_step4_functional_evidence(tmp_path,'digital_arithmetic_primitive')
    assert professional.status=='PASS', professional.detail
    sim=tmp_path/'phase2/stage1/sim'; sim.mkdir()
    shutil.copy2(out/'results.xml',sim/'results.xml')
    canonical=D.step_step4_functional_evidence(tmp_path,'digital_arithmetic_primitive')
    assert canonical.status=='PASS', canonical.detail
    report=tmp_path/'reports/phase2/gates/cpu_functional_oracle_waiver.json'
    row=json.loads(report.read_text())['coverage_goals']['rows'][0]
    assert row['verdict']=='PASS', row
    assert row['achieved_pct']==100.0 and row['achieved_source']
    receipt=json.loads((tmp_path/row['achieved_source']).read_text())
    assert row['requested_random_pairs']==count
    assert receipt['executed_random_pairs']==count
    assert receipt['distinct_random_pairs']==count
    assert receipt['random_mismatches']==0
    assert receipt['width']==width and receipt['framing']['latency']==1
    assert receipt['seed']==(0x9E3779B97F4A7C15 ^ width)
    assert receipt['execution']['returncode']==0
    assert receipt['execution']['argv']==['make','SIM=icarus']
    assert '@sha256:' in receipt['execution']['configured_image']


@pytest.fixture(scope='module')
def _measured_random_goal(tmp_path_factory):
    root=tmp_path_factory.mktemp('measured-random-goal')
    _random_goal_project(root,64,'*',4,True)
    old=os.environ.get('PYTHONPATH','')
    os.environ['PYTHONPATH']=str(PROG)+os.pathsep+old
    try:
        result=D.step_professional_tb_gen(root,'neutral_arithmetic','')
    finally:
        os.environ['PYTHONPATH']=old
    assert result.status=='PASS', result.detail
    return root


@pytest.mark.parametrize('mutation', [
    'below_count','missing_goal_binding','rtl_changed','declaration_changed',
    'goal_changed','image_changed','missing_junit','missing_receipt','not_rerun',
])
def test_random_goal_current_measurement_is_required(tmp_path,_measured_random_goal,mutation):
    root=tmp_path/'case'; shutil.copytree(_measured_random_goal,root)
    out=root/'phase2/stage1/sim_professional/neutral_arithmetic'
    plan=json.loads((out/'verification_plan.json').read_text())['random_goal_plan']
    receipt_path=out/plan['measurement_file']
    receipt=json.loads(receipt_path.read_text())
    if mutation=='below_count':
        receipt['executed_random_pairs']=63; receipt['distinct_random_pairs']=63
        receipt_path.write_text(json.dumps(receipt))
    elif mutation=='missing_goal_binding':
        receipt['goals']=[]; receipt_path.write_text(json.dumps(receipt))
    elif mutation=='rtl_changed':
        rtl=root/'phase2/stage1/rtl/neutral_arithmetic.v'
        rtl.write_text(rtl.read_text()+'\n// current RTL changed\n')
    elif mutation=='declaration_changed':
        decl=root/'plugin_output/declaration.json'
        data=json.loads(decl.read_text()); data['latency_cycles']=2
        decl.write_text(json.dumps(data))
    elif mutation=='goal_changed':
        l10=root/'phase1/generated_docs/L10_TEST_CASES.json'
        data=json.loads(l10.read_text())
        for row in data['test_cases']:
            for key in ('coverage_scope','stimulus'):
                if key in row: row[key]=row[key].replace('64','65')
        l10.write_text(json.dumps(data))
    elif mutation=='image_changed':
        receipt['execution']['configured_image']='neutral/image@sha256:'+'0'*64
        receipt_path.write_text(json.dumps(receipt))
    elif mutation=='missing_junit':
        (out/'results.xml').rename(out/'preserved_prior_results.xml')
    elif mutation=='missing_receipt':
        receipt_path.rename(out/'preserved_prior_measurement.json')
    elif mutation=='not_rerun':
        prior_bytes=receipt_path.read_bytes()
        T.generate(root)
        assert receipt_path.read_bytes()==prior_bytes
    # Absence and stale data cannot inherit the passing testcase denominator.
    row=G._coverage_goal_summary(root)['rows'][0]
    assert row['verdict']=='NOT_MEASURED', row
    assert row['achieved_pct'] is None
    step=D.step_step4_functional_evidence(root,'digital_arithmetic_primitive')
    assert step.status!='PASS', step.detail


@pytest.mark.timeout(120)
@pytest.mark.parametrize('mutation', ['output_inversion','shift_sampling','short_population','duplicate_population'])
def test_native_random_pair_comparisons_and_population_bite(tmp_path,monkeypatch,mutation):
    _random_goal_project(tmp_path,64,'*',4,True)
    if mutation=='output_inversion':
        rtl=tmp_path/'phase2/stage1/rtl/neutral_arithmetic.v'
        rtl.write_text(rtl.read_text().replace('p <= next_accum[0]', 'p <= ~next_accum[0]'))
    elif mutation=='shift_sampling':
        original=T.emit_serial_stream_tb
        def shifted(shape):
            text=original(shape)
            needle='act = _stream_to_val(got, latency, order, N)'
            assert needle in text
            return text.replace(needle,'act = _stream_to_val(got, latency + 1, order, N)')
        monkeypatch.setattr(T,'emit_serial_stream_tb',shifted)
    elif mutation=='short_population':
        original=T._aog._distinct_population_pairs
        monkeypatch.setattr(T._aog,'_distinct_population_pairs',
                            lambda width,count,operator,exclude: original(width,8,operator,exclude))
    else:
        monkeypatch.setattr(T._aog,'_distinct_population_pairs',
                            lambda width,count,operator,exclude: [(3,5)]*count)
    monkeypatch.setenv('PYTHONPATH',str(PROG)+os.pathsep+os.environ.get('PYTHONPATH',''))
    result=D.step_professional_tb_gen(tmp_path,'neutral_arithmetic','')
    if mutation in ('short_population','duplicate_population'):
        assert result.status=='PASS', result.detail  # eight correct comparisons are a smoke PASS
        goal=G._coverage_goal_summary(tmp_path)['rows'][0]
        assert goal['verdict']=='NOT_MEASURED', goal
        assert f"{8 if mutation=='short_population' else 1} random pairs" in goal['why']
    else:
        assert result.status=='FAIL', result.detail
        row=G._coverage_goal_summary(tmp_path)['rows'][0]
        assert row['verdict']=='FAIL', row
    assert D.step_step4_functional_evidence(tmp_path,'digital_arithmetic_primitive').status!='PASS'


@pytest.mark.timeout(120)
def test_missing_serial_framing_stays_unmeasured(tmp_path,monkeypatch):
    _random_goal_project(tmp_path,64,'*',4,True)
    declaration=tmp_path/'plugin_output/declaration.json'
    declaration.rename(tmp_path/'plugin_output/preserved_prior_declaration.json')
    monkeypatch.setenv('PYTHONPATH',str(PROG)+os.pathsep+os.environ.get('PYTHONPATH',''))
    result=D.step_professional_tb_gen(tmp_path,'neutral_arithmetic','')
    assert result.status=='NOT_MEASURED', result.detail
    row=G._coverage_goal_summary(tmp_path)['rows'][0]
    assert row['verdict']=='NOT_MEASURED' and row['achieved_pct'] is None
    assert D.step_step4_functional_evidence(tmp_path,'digital_arithmetic_primitive').status!='PASS'
