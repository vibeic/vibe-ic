"""Run the real professional consumer on unequal-width clockless arithmetic."""
import json
from pathlib import Path
import subprocess

import pytest

import arith_oracle_tb_gen as oracle
import professional_tb_gen as professional
from test_source_expression_authority import PHASE1_RECORDS, phase1_project, project, sign_project


@pytest.mark.parametrize('op,widths', [('+', (3, 5, 6)), ('-', (5, 3, 4)), ('*', (3, 5, 4)), ('>>', (5, 3, 5))])
@pytest.mark.parametrize('wrong', [False, True])
def test_native_professional_consumer_checks_actual_schema(tmp_path, op, widths, wrong):
    p = project(tmp_path, f'result = left {op} right.', widths=widths)
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


def test_real_checked_in_oracle_consumer_contract(tmp_path):
    from _hostpaths import repo_path
    # Read an existing caller artifact rather than restating its source contract.
    caller = repo_path('vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_v1_0_82_issue745_arith_oracle_tb.py')
    assert caller.is_file()
    text = caller.read_text()
    import re
    source = re.search(r'l2="(p = x \* y mod 2\^N parallel multiplier)"', text).group(1)
    p = project(tmp_path, source.replace('p = x * y', 'result = left * right'))
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert spec is not None, reason
    generated = professional.emit_parallel_arith_tb(professional.classify_dut(p, 'digital_arithmetic_primitive')[0])
    compile(generated, '<generated arithmetic consumer>', 'exec')
    assert oracle.compute_golden(spec['operator'], 7, 31, spec['result_width'], False) == 25


@pytest.mark.parametrize('wrong', [False, True])
def test_existing_expert_reference_resumes_an_unsupported_function(tmp_path, wrong):
    p = project(tmp_path, 'result = left + right. Saturate on overflow.', widths=(3, 5, 4))
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


@pytest.mark.parametrize('case', ['modulus_three', 'modulus_three_masked', 'modulus_unbound',
                                 'forbidden_title', 'forbidden_heading', 'positive_title', 'modulus_six'])
def test_native_review_source_authority_controls(tmp_path, case):
    source = 'result = left + right' + (' mod 2^N' if case.startswith('modulus') else '.')
    p = project(tmp_path, source)
    declaration = p / 'declaration.json'
    d = json.loads(declaration.read_text())
    if case == 'modulus_unbound':
        d.pop('N')
    elif case.startswith('modulus_three'):
        d['N'] = 3
    declaration.write_text(json.dumps(d))
    if case == 'forbidden_title':
        doc = p / 'phase1/generated_docs/L2_FRS.json'
        doc.write_text(json.dumps({'frs_sections': [{
            'title': 'Forbidden example: do not implement', 'content': source}]}))
    if case == 'forbidden_heading':
        doc = p / 'phase1/generated_docs/L2_FRS.json'
        doc.write_text(json.dumps({'frs_sections': [{
            'heading': 'Forbidden example: do not implement', 'content': source}]}))
    rtl = p / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    expression = "(left + right) & 6'd7" if case == 'modulus_three_masked' else 'left + right'
    (rtl / 'neutral_arithmetic.v').write_text(
        'module neutral_arithmetic(input [2:0] left, input [4:0] right, output [5:0] result); '
        'assign result = ' + expression + '; endmodule\n')
    before = {f.relative_to(p): f.read_bytes() for f in p.rglob('*') if f.is_file()}
    import design_one_shot_runner as runner
    step = runner.step_professional_tb_gen(p, 'neutral_arithmetic', 'unused')
    report = json.loads((p / 'reports/phase2/gates/professional_tb.json').read_text())
    if case in ('positive_title', 'modulus_six'):
        assert (step.status, report['status'], report['ran_cocotb']) == ('PASS', 'PASS', True), report
    else:
        assert (step.status, report['status'], report['ran_cocotb']) == ('NOT_MEASURED', 'INCOMPLETE', False), report
        assert step.extras['fallback_skill'] == 'testbench-gen'
        assert not (p / 'phase2/stage1/sim_professional').exists()
    assert all((p / name).read_bytes() == value for name, value in before.items())


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


@pytest.mark.parametrize('wrong', [False, True])
def test_native_multi_section_phase1_source_discriminates_a_wrong_multiplier(tmp_path, monkeypatch, wrong):
    monkeypatch.setenv('VIBEIC_EDA_IMAGE', 'unused-repository@sha256:' + '0' * 64)
    p = phase1_project(tmp_path, PHASE1_RECORDS)
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
    assert (report['ran_cocotb'], report['reference_model_tier']) == (True, 'streaming_bounded_latency'), report
    assert (step.status, consumer.check(p)['verdict'], report['functional_mismatch']) == (
        ('FAIL', 'FAIL', True) if wrong else ('PASS', 'PASS', False)), report


@pytest.mark.parametrize('case', [
    {'overview': 'Signed 2s complement multiplier.'},
    {'encoding': 'signed_2c', 'flags': (False, False, False)},
])
@pytest.mark.parametrize('dut_signed', [False, True])
def test_native_signed_source_cannot_confirm_an_unsigned_reference(tmp_path, case, dut_signed):
    p = sign_project(tmp_path, **case)
    rtl = p / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    expression = '$signed(left) * $signed(right)' if dut_signed else 'left * right'
    (rtl / 'neutral_arithmetic.v').write_text(
        'module neutral_arithmetic(input [3:0] left, input [3:0] right, output [7:0] result); '
        f'assign result = {expression}; endmodule\n')
    import design_one_shot_runner as runner
    step = runner.step_professional_tb_gen(p, 'neutral_arithmetic', 'unused')
    report = json.loads((p / 'reports/phase2/gates/professional_tb.json').read_text())
    assert (step.status, report['status'], report['ran_cocotb']) == ('NOT_MEASURED', 'INCOMPLETE', False), report
    assert step.extras['fallback_skill'] == 'testbench-gen'


@pytest.mark.parametrize('expression', ['left + right', "({1'b0, left} + {1'b0, right}) > 4'd7 ? 3'd7 : left + right"])
def test_native_arithmetic_rule_in_another_record_blocks_the_wrapping_reference(tmp_path, expression):
    p = project(tmp_path, 'result = left + right.', widths=(3, 3, 3))
    path = p / 'phase1/generated_docs/L2_FRS.json'
    doc = json.loads(path.read_text())
    doc['frs_sections'].append({'title': 'Overflow policy', 'content': 'The result saturates on overflow.'})
    path.write_text(json.dumps(doc))
    rtl = p / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    (rtl / 'neutral_arithmetic.v').write_text(
        'module neutral_arithmetic(input [2:0] left, input [2:0] right, output [2:0] result); '
        f'assign result = {expression}; endmodule\n')
    import design_one_shot_runner as runner
    step = runner.step_professional_tb_gen(p, 'neutral_arithmetic', 'unused')
    report = json.loads((p / 'reports/phase2/gates/professional_tb.json').read_text())
    assert (step.status, report['status'], report['ran_cocotb']) == ('NOT_MEASURED', 'INCOMPLETE', False), report
    assert step.extras['fallback_skill'] == 'testbench-gen'
