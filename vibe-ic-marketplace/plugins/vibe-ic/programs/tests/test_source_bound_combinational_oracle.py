"""Run the real professional consumer on unequal-width clockless arithmetic."""
import json
from pathlib import Path
import subprocess

import pytest

import arith_oracle_tb_gen as oracle
import professional_tb_gen as professional
from test_source_expression_authority import PHASE1_RECORDS, function, phase1_project, project, update_declaration


@pytest.mark.parametrize('op,widths', [('+', (3, 5, 6)), ('-', (5, 3, 4)), ('*', (3, 5, 4)), ('>>', (5, 3, 5))])
@pytest.mark.parametrize('wrong', [False, True])
def test_native_professional_consumer_checks_actual_schema(tmp_path, op, widths, wrong):
    p = project(tmp_path, widths=widths, operator=op)
    a, b, r = widths
    rtl = p / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    expression = 'left ^ right' if wrong else f'left {op} right'
    (rtl / 'neutral_arithmetic.v').write_text(
        f'module neutral_arithmetic(input [{a-1}:0] left, input [{b-1}:0] right, '
        f'output [{r-1}:0] result); assign result = {expression}; endmodule\n')
    import design_one_shot_runner as runner
    import professional_tb_check as consumer
    step = runner.step_professional_tb_gen(p, 'neutral_arithmetic', 'unused')
    report = json.loads((p / 'reports/phase2/gates/professional_tb.json').read_text())
    assert report.get('ran_cocotb') is True, (step, report)
    assert report['reference_model_tier'] == 'closed_form'
    assert report['cocotb_test_denominator']['tests'] == 1
    assert report['cocotb_test_denominator']['skipped'] == 0
    assert (step.status, consumer.check(p)['verdict'], report['functional_mismatch']) == (
        ('FAIL', 'FAIL', True) if wrong else ('PASS', 'PASS', False)), report
    shape, _ = professional.classify_dut(p, 'digital_arithmetic_primitive')
    assert shape['cr']['clk'] is None
    cov = professional.build_coverage_model(shape)
    cps = cov['fields']['covergroups'][0]['coverpoints']
    assert [cp['expr'] for cp in cps] == ['left', 'right']
    assert [max(v for bin in cp['bins'] for v in bin['values']) for cp in cps] == [(1 << a)-1, (1 << b)-1]


def test_generated_consumer_compiles_and_uses_the_declared_function(tmp_path):
    p = project(tmp_path, widths=(3, 5, 4), operator='*')
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert spec is not None, reason
    generated = professional.emit_parallel_arith_tb(professional.classify_dut(p, 'digital_arithmetic_primitive')[0])
    compile(generated, '<generated arithmetic consumer>', 'exec')
    assert oracle.compute_golden(spec['operator'], 7, 31, spec['result_width'], False) == (7 * 31) % 16


@pytest.mark.parametrize('wrong', [False, True])
def test_existing_expert_reference_resumes_an_unsupported_function(tmp_path, wrong):
    p = project(tmp_path, 'result = left + right. Saturate on overflow.', widths=(3, 5, 4), declare=False)
    shape, _ = professional.classify_dut(p, 'digital_arithmetic_primitive')
    assert shape['kind'] == 'generic'
    out = p / 'phase2/stage1/sim_professional/neutral_arithmetic'
    out.mkdir(parents=True)
    expert = out / 'expert_reference_tb.py'
    expert.write_text(professional._emit_common_header(shape) + '''
@cocotb.test()
async def saturated_reference(dut):
    await _reset(dut)
    for left in range(8):
        for right in range(32):
            dut.left.value = left
            dut.right.value = right
            await Timer(1, units="ns")
            assert int(dut.result.value) == min(left + right, 15)
    dut._log.info("PROFESSIONAL_TB PASS")
''')
    before = expert.read_bytes()
    rtl = p / 'phase2/stage1/rtl'
    rtl.mkdir()
    expression = 'left + right' if wrong else "(left + right > 15) ? 4'd15 : left + right"
    (rtl / 'neutral_arithmetic.v').write_text(
        'module neutral_arithmetic(input [2:0] left, input [4:0] right, '
        'output [3:0] result); assign result = ' + expression + '; endmodule\n')
    import design_one_shot_runner as runner
    import professional_tb_check as consumer
    step = runner.step_professional_tb_gen(p, 'neutral_arithmetic', 'unused')
    report = json.loads((p / 'reports/phase2/gates/professional_tb.json').read_text())
    assert report['ran_cocotb'] is True, report
    assert report['reference_model_tier'] == 'expert_filled'
    assert report['cocotb_test_denominator']['tests'] == 1
    assert report['cocotb_test_denominator']['skipped'] == 0
    assert (step.status, consumer.check(p)['verdict'], report['functional_mismatch']) == (
        ('FAIL', 'FAIL', True) if wrong else ('PASS', 'PASS', False)), report
    assert expert.read_bytes() == before


NEUTRAL_SERIAL_MUL = """module neutral_mul{suffix} #(parameter size = 8)(
  input wire clk, input wire rst, input wire [size-1:0] x, input wire y, output wire p);
  reg [size-1:0] s, c; reg yr, pr;
  wire [size-1:0] m = x & {{size{{yr}}}};
  wire [size-1:0] so = m ^ s ^ c;
  wire [size-1:0] co = (m & s) | (m & c) | (s & c);
  always @(posedge clk)
    if (rst) begin s <= 0; c <= 0; yr <= 0; pr <= 0; end
    else begin yr <= y; s <= {{1'b0, so[size-1:1]}}; c <= co; pr <= so[0]; end
  assign p = pr;
endmodule
"""


def run_serial(tmp_path, monkeypatch, wrong, declare):
    monkeypatch.setenv('VIBEIC_EDA_IMAGE', 'unused-repository@sha256:' + '0' * 64)
    p = phase1_project(tmp_path, PHASE1_RECORDS, declare=declare)
    rtl = p / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    source = NEUTRAL_SERIAL_MUL.format(suffix='_core' if wrong else '')
    if wrong:
        source += ('module neutral_mul #(parameter size = 8)(input clk, input rst, input [size-1:0] x, '
                   'input y, output p); wire q; neutral_mul_core #(.size(size)) u(.clk(clk), .rst(rst), '
                   '.x(x), .y(y), .p(q)); assign p = ~q; endmodule\n')
    (rtl / 'neutral_mul.v').write_text(source)
    import design_one_shot_runner as runner
    import professional_tb_check as consumer
    step = runner.step_professional_tb_gen(p, 'neutral_mul', 'unused')
    report = json.loads((p / 'reports/phase2/gates/professional_tb.json').read_text())
    return step, report, consumer.check(p)


@pytest.mark.parametrize('wrong', [False, True])
def test_native_typed_multi_section_design_discriminates_a_wrong_multiplier(tmp_path, monkeypatch, wrong):
    step, report, check = run_serial(tmp_path, monkeypatch, wrong, True)
    assert (report['ran_cocotb'], report['reference_model_tier']) == (True, 'streaming_bounded_latency'), report
    assert (step.status, check['verdict'], report['functional_mismatch']) == (
        ('FAIL', 'FAIL', True) if wrong else ('PASS', 'PASS', False)), report


@pytest.mark.parametrize('wrong', [False, True])
def test_native_prose_only_multi_section_design_is_not_certified(tmp_path, monkeypatch, wrong):
    step, report, check = run_serial(tmp_path, monkeypatch, wrong, False)
    assert (step.status, report['status'], report['ran_cocotb']) == ('NOT_MEASURED', 'INCOMPLETE', False), report
    assert check['verdict'] == 'NOT_CHECKED', check


REVIEW_RULES = [
    ('Output limits', 'The output is limited to the value 7; larger sums stay at 7.'),
    ('輸出限制', '輸出上限為 7，超過時維持 7。'),
    ('Function', '> The output is limited to 7; larger sums stay at 7.\n\n```\nresult = left + right\n```'),
    ('Output behavior', 'The output is the bitwise inverse of the computed value.'),
    ('Function', '> The output is the bitwise inverse of this value.\n\n```\nresult = left + right\n```'),
    ('Function', '```\nresult = left + right\n```\n- result is inverted before it leaves the block'),
    ('Overflow', 'Saturate on overflow.'),
]


@pytest.mark.parametrize('title,rule', REVIEW_RULES)
@pytest.mark.parametrize('expression', ['left + right', "(left + right > 7) ? 4'd7 : left + right", '~(left + right)'])
def test_native_stated_rules_cannot_reach_a_prose_reference(tmp_path, title, rule, expression):
    p = project(tmp_path, widths=(3, 3, 4), declare=False)
    (p / 'phase1/generated_docs/L2_FRS.json').write_text(json.dumps({'frs_sections': [
        {'title': 'Function', 'content': 'result = left + right.'}, {'title': title, 'content': rule}]}))
    rtl = p / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    (rtl / 'neutral_arithmetic.v').write_text(
        'module neutral_arithmetic(input [2:0] left, input [2:0] right, output [3:0] result); '
        f'assign result = {expression}; endmodule\n')
    import design_one_shot_runner as runner
    import professional_tb_check as consumer
    step = runner.step_professional_tb_gen(p, 'neutral_arithmetic', 'unused')
    report = json.loads((p / 'reports/phase2/gates/professional_tb.json').read_text())
    assert (step.status, report['status'], report['ran_cocotb']) == ('NOT_MEASURED', 'INCOMPLETE', False), report
    assert step.extras['fallback_skill'] == 'testbench-gen'
    assert consumer.check(p)['verdict'] == 'NOT_CHECKED'


@pytest.mark.parametrize('modulus,accepted', [(6, True), (3, False)])
def test_native_declared_modulus_must_match_the_result_port(tmp_path, modulus, accepted):
    p = project(tmp_path)
    update_declaration(p, function=function('+', modulus))
    rtl = p / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    (rtl / 'neutral_arithmetic.v').write_text(
        'module neutral_arithmetic(input [2:0] left, input [4:0] right, output [5:0] result); '
        'assign result = left + right; endmodule\n')
    import design_one_shot_runner as runner
    step = runner.step_professional_tb_gen(p, 'neutral_arithmetic', 'unused')
    report = json.loads((p / 'reports/phase2/gates/professional_tb.json').read_text())
    assert (step.status, report['ran_cocotb']) == (('PASS', True) if accepted else ('NOT_MEASURED', False)), report
