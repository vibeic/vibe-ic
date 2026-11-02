"""Arithmetic source records must describe a complete affirmative function."""
import json
from pathlib import Path

import pytest

import arith_oracle_tb_gen as oracle
import professional_tb_gen as professional


def project(root, content, *, widths=(3, 5, 6), signed=None):
    docs = root / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    records = content if isinstance(content, list) else [content]
    (docs / 'L2_FRS.json').write_text(json.dumps({
        'frs_sections': [{'title': 'Function', 'content': s} for s in records]}))
    ports = [{'name': n, 'direction': d, 'width': w} for n, d, w in zip(
        ('left', 'right', 'result'), ('input', 'input', 'output'), widths)]
    if signed is not None:
        for p, sign in zip(ports, signed):
            p['signed'] = sign
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({
        'top_module': 'neutral_arithmetic', 'top_ports': ports,
        'ic_class': 'digital_arithmetic_primitive'}))
    (root / 'declaration.json').write_text(json.dumps({
        'ic_class': 'digital_arithmetic_primitive'}))
    return root


@pytest.mark.parametrize('source', [
    'result = left + right.',
    'result = (left + right);',
    'result = ((left) + (right)).',
    'The result is the sum of left and right.',
    'parallel adder result = left + right.',
])
def test_complete_affirmative_expression_and_exact_widths(tmp_path, source):
    p = project(tmp_path, source)
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert spec is not None, reason
    assert (spec['operator'], spec['operand_a'], spec['operand_b'], spec['result']) == (
        '+', 'left', 'right', 'result')
    assert [spec[k] for k in ('operand_a_width', 'operand_b_width', 'result_width')] == [3, 5, 6]


@pytest.mark.parametrize('source', [
    'result = left + right * left.',
    'result = left + right + left.',
    'result = left + right[1:0].',
    'result = left + right ? left : right.',
    'result = left + right >>> 1.',
    'result = left + right garbage.',
    'result = (left + right.',
    'Do not implement result = left + right.',
    'Forbidden example: result = left + right.',
    'Example: result = left + right.',
    'result = left + right. Saturate on overflow.',
    'result = left + right. Apply a correction.',
    'result = left + right # Saturate on overflow.',
    '# Do not implement\nresult = left + right.',
    'multiplier result = left + right.',
    ['result = left + right.', 'Saturate instead of wrapping on overflow.'],
    ['result = left +', 'right.'],
    ['result = left + right.', 'result = left - right.'],
    'result = other + right.',
    'result = left + left.',
    'result = left + right mod 2^4.',
    'subtractor',
])
def test_unsupported_or_nonaffirmative_function_refuses_without_writes(tmp_path, source):
    p = project(tmp_path, source)
    out = p / 'phase2/stage1/sim_full_stack'
    out.mkdir(parents=True)
    existing = out / 'tb_neutral_arithmetic_oracle.v'
    existing.write_bytes(b'operator-owned existing testbench\n')
    before = {f.relative_to(p): f.read_bytes() for f in p.rglob('*') if f.is_file()}
    report, rc = oracle.generate(p, 'digital_arithmetic_primitive')
    assert (rc, report['verdict']) == (2, 'DEFER'), report
    assert report['fallback_skill'] == 'testbench-gen'
    assert {f.relative_to(p): f.read_bytes() for f in p.rglob('*') if f.is_file()} == before


def test_function_records_outweigh_incidental_metadata(tmp_path):
    p = project(tmp_path, 'result = left + right.')
    doc = p / 'phase1/generated_docs/L1_DATASHEET.json'
    doc.write_text(json.dumps({'description': 'Forbidden example: result = left - right.'}))
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert spec is not None, reason
    assert spec['operator'] == '+'


@pytest.mark.parametrize('widths,signs', [
    ((None, 5, 6), None), ((3, 5, 6), (True, False, False)),
    (('0', 5, 6), None), ((0, 5, 6), None), ((True, 5, 6), None),
])
def test_unresolved_width_or_mixed_sign_has_truthful_handoff(tmp_path, widths, signs):
    p = project(tmp_path, 'result = left + right.', widths=widths, signed=signs)
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert spec is None, (spec, reason)
    assert reason


def test_professional_refusal_preserves_existing_bundle(tmp_path):
    p = project(tmp_path, 'result = left + right. Saturate on overflow.')
    out = p / 'existing_bundle'
    out.mkdir()
    (out / 'expert_reference_tb.py').write_bytes(b'operator reference\n')
    before = {f.relative_to(p): f.read_bytes() for f in p.rglob('*') if f.is_file()}
    result = professional.generate(p, out_dir=out)
    assert result['status'] == 'INCOMPLETE', result
    assert result['fallback_skill'] == 'testbench-gen'
    assert {f.relative_to(p): f.read_bytes() for f in p.rglob('*') if f.is_file()} == before


def test_serial_classifier_cannot_bypass_source_refusal(tmp_path):
    p = project(tmp_path, 'result = left * right. Saturate on overflow.', widths=(8, 1, 1))
    shape, _ = professional.classify_dut(p, 'digital_arithmetic_primitive')
    assert shape['kind'] == 'generic', shape
    assert professional.generate(p)['status'] == 'INCOMPLETE'


@pytest.mark.parametrize('declared', [False, True])
def test_parameter_width_requires_the_actual_declared_default(tmp_path, declared):
    p = project(tmp_path, 'result = left * right.',
                widths=('[W-1:0]', '[W-1:0]', '[2*W-1:0]'))
    if declared:
        rtl = p / 'phase2/stage1/rtl'
        rtl.mkdir(parents=True)
        (rtl / 'neutral_arithmetic.v').write_text(
            'module neutral_arithmetic #(parameter W=7)(input [W-1:0] left,right, '
            'output [2*W-1:0] result); assign result=left*right; endmodule\n')
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    if declared:
        assert spec is not None, reason
        assert [spec[k] for k in ('operand_a_width', 'operand_b_width', 'result_width')] == [7, 7, 14]
    else:
        assert spec is None, (spec, reason)


def test_actual_runner_propagates_source_handoff_without_simulation(tmp_path):
    p = project(tmp_path, 'result = left + right. Saturate on overflow.')
    before = {f.relative_to(p): f.read_bytes() for f in p.rglob('*') if f.is_file()}
    import design_one_shot_runner as runner
    step = runner.step_professional_tb_gen(p, 'neutral_arithmetic', 'unused')
    report = json.loads((p / 'reports/phase2/gates/professional_tb.json').read_text())
    assert (step.status, report['status'], report['ran_cocotb']) == ('NOT_MEASURED', 'INCOMPLETE', False)
    assert step.extras['fallback_skill'] == 'testbench-gen'
    assert not (p / 'phase2').exists()
    assert all((p / name).read_bytes() == content for name, content in before.items())


@pytest.mark.parametrize('source,accepted', [
    ('result = left + right mod 2^N (parallel adder)', True),
    ('result = left + right * left.', False),
    ('Do not implement result = left + right.', False),
    ('result = left + right. Saturate on overflow.', False),
])
def test_existing_function_field_has_the_same_source_boundary(tmp_path, source, accepted):
    p = project(tmp_path, source)
    doc = p / 'phase1/generated_docs/L2_FRS.json'
    doc.write_text(json.dumps({'function': source}))
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert bool(spec) is accepted, (spec, reason)
    if accepted:
        assert (spec['operand_a'], spec['operand_b'], spec['result_width']) == ('left', 'right', 6)


@pytest.mark.parametrize('description,accepted', [
    ('serial-parallel bitwise arithmetic', True),
    ('Saturate on overflow', False),
])
def test_existing_serial_record_keeps_only_supported_shape_annotations(tmp_path, description, accepted):
    from test_serial_parallel_declared_function_oracle import _declared_scenario_project
    p = tmp_path / 'serial_contract'
    _declared_scenario_project(p)
    doc = p / 'phase1/generated_docs/L2_FRS.json'
    doc.write_text(json.dumps({'frs_sections': [{
        'content': 'p = (x & y) mod 2^8; ' + description}]}))
    spec, reason = oracle.extract_serial_arith_spec(p, 'digital_arithmetic_primitive')
    assert bool(spec) is accepted, (spec, reason)
    if accepted:
        assert (spec['operator'], spec['parallel'], spec['serial_in'], spec['serial_out']) == ('&', 'x', 'y', 'p')


def test_existing_timed_serial_source_keeps_declared_multiply(tmp_path):
    from test_fullstacktb_functional_population import _timed_fixture
    p = _timed_fixture(tmp_path, 'core4')
    spec, reason = oracle.extract_serial_arith_spec(p, 'digital_arithmetic_primitive')
    assert spec is not None, reason
    assert (spec['operator'], spec['width']) == ('*', 4)
