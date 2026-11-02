"""Run the real professional consumer on unequal-width clockless arithmetic."""
import json
from pathlib import Path
import subprocess

import pytest

import arith_oracle_tb_gen as oracle
import professional_tb_gen as professional
from test_source_expression_authority import project


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
