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
        'ic_class': 'digital_arithmetic_primitive', 'N': widths[2]}))
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


@pytest.mark.parametrize('source,accepted', [
    ('serial-parallel multiplier: result = left * right mod 2^N', True),
    ('serial-parallel multiplier: result = left * right + left', False),
    ('serial-parallel multiplier: Do not implement result = left * right', False),
    ('serial-parallel multiplier: result = left * right. Saturate on overflow.', False),
])
def test_shape_label_colon_preserves_the_complete_expression(source, accepted):
    parsed = oracle._extract_operator(source)
    assert bool(parsed) is accepted, parsed
    if accepted:
        assert parsed == ('result', 'left', '*', 'right')


@pytest.mark.parametrize('polarity,sync,physical,accepted', [
    (None, None, True, False),
    ('active_high', 'sync', True, True),
    ('active_low', 'sync', True, False),
    ('active_high', 'async', True, False),
    ('active_high', 'sync', False, False),
])
def test_reset_clause_requires_its_actual_structured_contract(tmp_path, polarity, sync, physical, accepted):
    p = project(tmp_path, 'multiplier: result = left * right; synchronous active-high reset')
    path = p / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    l9 = json.loads(path.read_text())
    if physical:
        l9['top_ports'] += [{'name': n, 'direction': 'input', 'width': 1} for n in ('clk', 'rst')]
    if polarity is not None:
        l9['reset_domains'] = [{'name': 'rst', 'polarity': polarity, 'sync': sync}]
    path.write_text(json.dumps(l9))
    parsed = oracle._function_operator(p)
    assert bool(parsed) is accepted, parsed
    if accepted:
        assert parsed == ('result', 'left', '*', 'right')


@pytest.mark.parametrize('source,accepted', [
    ('result is the sum of left and right adder', True),
    ('result is the sum of left and right multiplier', False),
    ('Implement a multiplier. The result is the sum of left and right.', False),
    ('result is the sum of left and right bitwise arithmetic', False),
])
def test_affirmative_prose_requires_consistent_shape_labels(tmp_path, source, accepted):
    p = project(tmp_path, source)
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert bool(spec) is accepted, (spec, reason)
    if accepted:
        assert spec['operator'] == '+'


@pytest.mark.parametrize('declared,accepted', [(None, False), (3, False), (6, True), (True, False)])
def test_symbolic_modulus_uses_its_named_declaration(tmp_path, declared, accepted):
    p = project(tmp_path, 'result = left + right mod 2^LIMIT.')
    declaration = p / 'declaration.json'
    data = json.loads(declaration.read_text())
    if declared is not None:
        data['LIMIT'] = declared
    declaration.write_text(json.dumps(data))
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert bool(spec) is accepted, (spec, reason)
    if not accepted:
        assert 'LIMIT' in reason, reason


@pytest.mark.parametrize('title,accepted', [
    ('Function', True), ('Forbidden example: do not implement', False),
    ('Negative example', False), ('Prohibited implementation', False),
    ('Function (not applicable)', False),
    ('Negative examples', False), ('Disallowed example', False),
    ('Illustrative example', False),
])
def test_frs_record_title_retains_its_authority(tmp_path, title, accepted):
    p = project(tmp_path, 'result = left + right.')
    path = p / 'phase1/generated_docs/L2_FRS.json'
    path.write_text(json.dumps({'frs_sections': [{'title': title, 'content': 'result = left + right.'}]}))
    before = {f.relative_to(p): f.read_bytes() for f in p.rglob('*') if f.is_file()}
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert bool(spec) is accepted, (spec, reason)
    assert all((p / name).read_bytes() == value for name, value in before.items())


@pytest.mark.parametrize('wrapper', ['document', 'fields'])
def test_function_wrapper_cannot_restore_a_prohibited_record(tmp_path, wrapper):
    p = project(tmp_path, 'result = left + right.')
    fields = {'function': 'result = left + right.'}
    doc = {'fields': fields}
    (doc if wrapper == 'document' else fields)['title'] = 'Forbidden example: do not implement'
    (p / 'phase1/generated_docs/L2_FRS.json').write_text(json.dumps(doc))
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert spec is None, (spec, reason)


@pytest.mark.parametrize('title,accepted', [('Function', True), ('Forbidden example: do not implement', False)])
def test_existing_overview_fallback_keeps_its_title_polarity(tmp_path, title, accepted):
    p = project(tmp_path, 'result = left + right.')
    docs = p / 'phase1/generated_docs'
    (docs / 'L2_FRS.json').unlink()
    (docs / 'L1_DATASHEET.json').write_text(json.dumps({'title': title, 'overview': 'result = left + right.'}))
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert bool(spec) is accepted, (spec, reason)


@pytest.mark.parametrize('metadata', [
    {'heading': 'Forbidden example: do not implement'},
    {'name': 'Negative example'},
    {'section': 'Forbidden example: do not implement'},
    {'section': 3},
    {'title': 'Function', 'kind': 'negative_example'},
    {'title': 'Function', 'negative': True},
    {'title': 'Function', 'section': 'Negative examples'},
])
def test_frs_record_authority_outside_its_title_defers(tmp_path, metadata):
    p = project(tmp_path, 'result = left + right.')
    (p / 'phase1/generated_docs/L2_FRS.json').write_text(json.dumps({
        'frs_sections': [{**metadata, 'content': 'result = left + right.'}]}))
    before = {f.relative_to(p): f.read_bytes() for f in p.rglob('*') if f.is_file()}
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert spec is None, (spec, reason)
    assert all((p / name).read_bytes() == value for name, value in before.items())


@pytest.mark.parametrize('metadata', [
    {'section': 'h2', 'title': 'Function', 'evidence': 'input/docs/spec.md', 'heading_shape': 'md_atx'},
    {'section': '1.1', 'title': 'Function'},
    {'section': 'unheaded', 'title': 'Functional requirements', 'evidence': 'input/docs/spec.md'},
    {},
])
def test_phase1_record_shapes_keep_their_reference(tmp_path, metadata):
    p = project(tmp_path, 'result = left + right.')
    (p / 'phase1/generated_docs/L2_FRS.json').write_text(json.dumps({
        'frs_sections': [{**metadata, 'content': 'result = left + right.'}]}))
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert spec and spec['operator'] == '+', (spec, reason)


@pytest.mark.parametrize('key', ['function', 'content'])
@pytest.mark.parametrize('nested', [False, True])
def test_function_wrapper_metadata_outside_its_title_defers(tmp_path, key, nested):
    p = project(tmp_path, 'result = left + right.')
    fields = {key: 'result = left + right.', 'heading': 'Forbidden example: do not implement'}
    path = p / 'phase1/generated_docs/L2_FRS.json'
    path.write_text(json.dumps({'fields': fields} if nested else fields))
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert spec is None, (spec, reason)
    fields.pop('heading')
    path.write_text(json.dumps({'fields': fields} if nested else fields))
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert spec and spec['operator'] == '+', (spec, reason)


# The record shape Phase 1 actually writes for a multi-section design document.
PHASE1_FUNCTION = """`neutral_mul` 為 **N-bit modulo 算術乘法器**,計算:

```
p = (x × y) mod 2^N    (N-bit modulo arithmetic multiplication)
```

> **整數編碼說明**:N-bit serial multiplier 對 signed 2's complement 與 unsigned 整數的 **bit pattern 結果完全相同**。

其中:
- **x** 為 **parallel multiplicand**(整體一次給入,N 位元)
- **y** 為 **serial multiplier**(每個時脈週期給入 1 個位元)
- **p** 為 **serial product**(每個時脈週期輸出 1 個位元)
"""
PHASE1_RECORDS = [(title, content) for title, content in (
    ('產品基本資訊', '| 欄位 | 值 |\n|---|---|\n| 功能一句話描述 | signed 整數乘法器 |'),
    ('Tapeout 目標', '| 目標 PDK family | open-source |'),
    ('量產 (Production-readiness) 期望', '- 必須對外時序滿足 L9 SDC 約束'),
    ('不在 L1 約束的事', '- ❌ 不指定 die size'),
    ('功能定義 (Functional Specification)', PHASE1_FUNCTION),
    ('資料寬度', '| `x` | N-bit |\n| `y` | 1-bit |\n| `p` | 1-bit |'),
    ('同步行為', '- 所有資料於 **`clk` 上升沿** 同步取樣與輸出'),
    ('輸出時序語意 (R3 多正確答案空間)', '- 對外行為符合「`p` 為 `x × y` 的 serial 位元流」'),
    ('演算法選擇空間 (Plugin 自由度)', '- functional 等價(對 golden model 100% 一致)'),
    ('不在 L2 約束的事', '- ❌ 不指定 latency cycle 數'),
    ('Module 對外端口表 (Port List)', '| `x` | N-bit(`[size-1:0]`,parameter `size` 預設 32) | input |'),
    ('Design Parameters', '| `size` | 32 | 典型應用為 8 / 16 / 32 |'),
    ('Physical Pad Placement', '| **North (N)** | `x[size-1:0]` |'),
    ('Reset Polarity 與啟動', '- `rst = 1` 進入 reset 狀態'),
    ('不在 L3 約束的事', '- ❌ ESD strategy'),
)]


def phase1_project(root, records=PHASE1_RECORDS, *, size=8):
    docs = root / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L2_FRS.json').write_text(json.dumps({
        'schema_version': 2, 'doc_class': 'frs', 'ic_name': 'neutral_mul',
        'frs_sections': [{'section': 'h2', 'title': title, 'content': content,
                          'evidence': 'input/docs/spec.md', 'heading_shape': 'md_atx'}
                         for title, content in records]}))
    ports = [('clk', 'input', 1), ('rst', 'input', 1), ('x', 'input', size), ('y', 'input', 1), ('p', 'output', 1)]
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({
        'top_module': 'neutral_mul', 'top_ports': [
            {'name': n, 'direction': d, 'width': w, 'msb': w - 1, 'lsb': 0} for n, d, w in ports]}))
    (root / 'reports').mkdir()
    (root / 'reports/ic_class.json').write_text(json.dumps({'ic_class': 'digital_arithmetic_primitive'}))
    (root / 'plugin_output').mkdir()
    (root / 'plugin_output/declaration.json').write_text(json.dumps({
        'bit_order': 'LSB_first', 'integer_encoding': 'unsigned', 'latency_cycles': 2,
        'latency_cycles_origin': 'pre_nba_sample_offset', 'reset_polarity': 'active_high',
        'size_param': size, 'transaction_rearm': 'clocked_reset', 'rearm_reset_cycles': 1,
        'parallel_hold': 'through_final_product_bit'}))
    return root


def test_multi_section_phase1_function_record_keeps_its_serial_reference(tmp_path):
    p = phase1_project(tmp_path)
    assert oracle._function_operator(p) == ('p', 'x', '*', 'y')
    assert oracle._source_modulus(p) == (8, 'N=8')
    spec, reason = oracle.extract_serial_arith_spec(p, 'digital_arithmetic_primitive')
    assert spec, reason
    assert (spec['operator'], spec['width'], spec['signed']) == ('*', 8, False)
    assert professional._detect_stream_operator(p, 'digital_arithmetic_primitive') == '*'


@pytest.mark.parametrize('narrative', [
    'Saturate on overflow.', 'Apply a correction.', 'Do not implement:', 'Negative example:',
    '> 此範例禁止實作', '- **other** is an unrelated rule', '飽和運算:',
])
def test_prose_around_a_fenced_function_cannot_qualify_it(tmp_path, narrative):
    records = [('功能定義', narrative + '\n\n```\np = (x * y) mod 2^N\n```\n')]
    p = phase1_project(tmp_path, records)
    assert oracle._function_operator(p) is None
    spec, reason = oracle.extract_serial_arith_spec(p, 'digital_arithmetic_primitive')
    assert spec is None, reason


@pytest.mark.parametrize('content', [
    '```\np = x * y\n```\n```\np = x + y\n```',
    '```\np = x * y\np = x + y\n```',
    '```\nnot an expression\n```',
    '```\np = (x * y) mod 2^N\n',
])
def test_a_function_record_needs_exactly_one_complete_fenced_expression(tmp_path, content):
    p = phase1_project(tmp_path, [('功能定義', content)])
    assert oracle._function_operator(p) is None


@pytest.mark.parametrize('records,operator', [
    ([('Product metadata', 'A neutral datapath.'), ('Function', 'p = x * y')], '*'),
    ([('Forbidden example: do not implement', 'p = x + y'), ('Function', 'p = x * y')], '*'),
    ([('Negative example', 'p = x + y'), ('功能定義 (Functional Specification)', 'p = x * y')], '*'),
    ([('Forbidden example: do not implement', 'p = x * y')], None),
    ([('Product metadata', 'p = x * y')], None),
    ([('Algorithm', 'p = x + y'), ('Function', 'p = x * y')], None),
    ([('功能定義 (negative example)', 'p = x * y')], None),
    ([('Function', 'p = x * y'), ('Function', 'Saturate on overflow.')], None),
])
def test_function_role_selects_records_and_a_stated_conflict_defers(tmp_path, records, operator):
    found = oracle._function_operator(phase1_project(tmp_path, records))
    assert (found[2] if found else None) == operator


@pytest.mark.parametrize('declared_n,modulus,accepted', [(None, 8, True), (8, 8, True), (6, 6, False)])
def test_mod_2_n_binds_the_declared_size_unless_n_is_itself_declared(tmp_path, declared_n, modulus, accepted):
    p = phase1_project(tmp_path, [('Function', 'p = x * y mod 2^N')])
    if declared_n is not None:
        path = p / 'plugin_output/declaration.json'
        path.write_text(json.dumps({**json.loads(path.read_text()), 'N': declared_n}))
    assert oracle._source_modulus(p)[0] == modulus
    spec, reason = oracle.extract_serial_arith_spec(p, 'digital_arithmetic_primitive')
    assert bool(spec) is accepted, (spec, reason)


def test_only_the_symbol_n_means_the_declared_size(tmp_path):
    p = phase1_project(tmp_path, [('Function', 'p = x * y mod 2^LIMIT')])
    modulus, why = oracle._source_modulus(p)
    assert modulus is None and 'LIMIT' in why


def sign_project(root, *, overview=None, encoding=None, flags=None):
    p = project(root, 'result = left * right.', widths=(4, 4, 8), signed=flags)
    if overview:
        (p / 'phase1/generated_docs/L1_DATASHEET.json').write_text(json.dumps({'overview': overview}))
    if encoding:
        path = p / 'declaration.json'
        path.write_text(json.dumps({**json.loads(path.read_text()), 'integer_encoding': encoding}))
    return p


@pytest.mark.parametrize('case', [
    {'overview': 'Signed 2s complement multiplier.'},
    {'overview': 'Handles signed and unsigned integers.'},
    {'encoding': 'signed_2c', 'flags': (False, False, False)},
    {'encoding': 'unsigned', 'flags': (True, True, True)},
])
def test_unresolved_or_conflicting_sign_defers(tmp_path, case):
    p = sign_project(tmp_path, **case)
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert spec is None and 'sign' in reason, (spec, reason)


@pytest.mark.parametrize('case,signed', [
    ({'overview': 'Signed 2s complement multiplier.', 'encoding': 'signed_2c'}, True),
    ({'overview': 'Signed 2s complement multiplier.', 'flags': (True, True, True)}, True),
    ({'encoding': 'unsigned', 'flags': (False, False, False)}, False),
    ({'encoding': 'signed_2c'}, True),
    ({'overview': 'An unsigned multiplier.'}, False),
    ({}, False),
])
def test_declared_operand_types_set_the_sign(tmp_path, case, signed):
    p = sign_project(tmp_path, **case)
    spec, reason = oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')
    assert spec, reason
    assert spec['signed'] is signed
