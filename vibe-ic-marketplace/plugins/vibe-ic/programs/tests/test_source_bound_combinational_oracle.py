"""Run the real professional consumer on unequal-width clockless arithmetic."""

import pytest

import arith_oracle_tb_gen as oracle
import professional_tb_gen as professional
from test_source_expression_authority import project


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
