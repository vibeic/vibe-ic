"""The arithmetic oracle's function comes from the typed declaration field alone."""
import json
from pathlib import Path

import pytest

import arith_oracle_tb_gen as oracle
import professional_tb_gen as professional


def function(operator='+', modulus_bits=6, result='result', operands=('left', 'right')):
    return {'result': result, 'operands': list(operands), 'operator': operator, 'modulus_bits': modulus_bits}


def project(root, content='A neutral arithmetic block.', *, widths=(3, 5, 6), signed=None,
            operator='+', declare=True):
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
    declaration = {'ic_class': 'digital_arithmetic_primitive'}
    if signed is None:
        declaration['integer_encoding'] = 'unsigned'
    if declare:
        declaration['function'] = function(
            operator, widths[2] if type(widths[2]) is int else 1)
    (root / 'declaration.json').write_text(json.dumps(declaration))
    return root


def update_declaration(root, **fields):
    path = root / 'declaration.json'
    path.write_text(json.dumps({**json.loads(path.read_text()), **fields}))


def extract(p):
    return oracle.extract_arith_spec(p, 'digital_arithmetic_primitive')


@pytest.mark.parametrize('operator,widths', [('+', (3, 5, 6)), ('-', (5, 3, 4)), ('*', (3, 5, 4)), ('>>', (5, 3, 5))])
def test_typed_function_supplies_operator_operands_and_exact_widths(tmp_path, operator, widths):
    spec, reason = extract(project(tmp_path, widths=widths, operator=operator))
    assert spec is not None, reason
    assert (spec['operator'], spec['operand_a'], spec['operand_b'], spec['result']) == (
        operator, 'left', 'right', 'result')
    assert [spec[k] for k in ('operand_a_width', 'operand_b_width', 'result_width')] == list(widths)


@pytest.mark.parametrize('source', [
    'result = left + right.',
    'result = left + right mod 2^N',
    'The result is the sum of left and right.',
    '```\nresult = left + right\n```',
])
def test_prose_alone_never_supplies_a_reference(tmp_path, source):
    p = project(tmp_path, source, declare=False)
    before = {f.relative_to(p): f.read_bytes() for f in p.rglob('*') if f.is_file()}
    spec, reason = extract(p)
    assert spec is None and 'function field' in reason, (spec, reason)
    assert all((p / name).read_bytes() == value for name, value in before.items())


@pytest.mark.parametrize('field', [
    'p = x * y',
    [],
    {**function(), 'extra': 1},
    {k: v for k, v in function().items() if k != 'modulus_bits'},
    function(operator='%'),
    function(operator='**'),
    function(modulus_bits=0),
    function(modulus_bits='6'),
    function(modulus_bits=True),
    function(modulus_bits='N'),
    function(operands=('left',)),
    function(operands=('left', 'left')),
    function(operands=('left', 'right', 'carry')),
    function(operands=('left', 7)),
    function(result='not an identifier'),
])
def test_malformed_function_field_defers(tmp_path, field):
    p = project(tmp_path)
    update_declaration(p, function=field)
    spec, reason = extract(p)
    assert spec is None and 'malformed' in reason, (spec, reason)


@pytest.mark.parametrize('field', [
    pytest.param(function(operator=['*']), id='operator-list'),
    pytest.param(function(operator={'symbol': '*'}), id='operator-dict'),
    pytest.param({**function(), 'operands': 2}, id='operands-int'),
    pytest.param({**function(), 'operands': {'left': 0, 'right': 1}}, id='operands-dict'),
])
def test_function_field_types_have_named_malformed_refusal(tmp_path, field):
    p = project(tmp_path)
    update_declaration(p, function=field)
    spec, reason = extract(p)
    assert spec is None and 'malformed' in reason, (spec, reason)


@pytest.mark.parametrize('field', [
    function(operands=('other', 'right')),
    function(operands=('left', 'other')),
    function(result='other'),
    function(modulus_bits=3),
])
def test_function_field_must_agree_with_the_actual_ports(tmp_path, field):
    p = project(tmp_path)
    update_declaration(p, function=field)
    spec, reason = extract(p)
    assert spec is None and reason, (spec, reason)


def test_declaration_files_must_agree(tmp_path):
    p = project(tmp_path)
    (p / 'plugin_output').mkdir()
    (p / 'plugin_output/declaration.json').write_text(json.dumps({'function': function('-')}))
    spec, reason = extract(p)
    assert spec is None and 'different function' in reason, (spec, reason)


@pytest.mark.parametrize('widths,signs', [
    ((None, 5, 6), None), ((3, 5, 6), (True, False, False)),
    (('0', 5, 6), None), ((0, 5, 6), None), ((True, 5, 6), None),
])
def test_unresolved_width_or_mixed_sign_has_truthful_handoff(tmp_path, widths, signs):
    p = project(tmp_path, widths=widths, signed=signs)
    spec, reason = extract(p)
    assert spec is None, (spec, reason)
    assert reason


@pytest.mark.parametrize('encoding,flags,accepted', [
    (None, None, False),
    ('signed_2c', (False, False, False), False),
    ('unsigned', (True, True, True), False),
    ('two_complement_ish', None, False),
    ('signed_2c', None, True),
    ('unsigned', (False, False, False), True),
    (None, (True, True, True), True),
    (None, (False, False, False), True),
])
def test_sign_comes_from_declared_types_and_undeclared_refuses(tmp_path, encoding, flags, accepted):
    p = project(tmp_path, 'Signed 2s complement multiplier.', widths=(4, 4, 8), operator='*', signed=flags or (None,) * 3)
    path = p / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
    l9 = json.loads(path.read_text())
    if flags is None:
        for port in l9['top_ports']:
            port.pop('signed')
    path.write_text(json.dumps(l9))
    if encoding:
        update_declaration(p, integer_encoding=encoding)
    spec, reason = extract(p)
    assert bool(spec) is accepted, (spec, reason)
    if accepted:
        assert spec['signed'] is (flags[0] if flags else encoding == 'signed_2c')
    else:
        assert 'sign' in reason or 'encoding' in reason, reason


def test_professional_refusal_preserves_existing_bundle(tmp_path):
    p = project(tmp_path, declare=False)
    out = p / 'existing_bundle'
    out.mkdir()
    (out / 'expert_reference_tb.py').write_bytes(b'operator reference\n')
    before = {f.relative_to(p): f.read_bytes() for f in p.rglob('*') if f.is_file()}
    result = professional.generate(p, out_dir=out)
    assert result['status'] == 'INCOMPLETE', result
    assert result['fallback_skill'] == 'testbench-gen'
    assert {f.relative_to(p): f.read_bytes() for f in p.rglob('*') if f.is_file()} == before


def test_serial_classifier_cannot_recover_an_operator_from_prose(tmp_path):
    p = project(tmp_path, 'result = left * right', widths=(8, 1, 1), declare=False)
    shape, _ = professional.classify_dut(p, 'digital_arithmetic_primitive')
    assert shape['kind'] == 'generic', shape
    assert professional.generate(p)['status'] == 'INCOMPLETE'


@pytest.mark.parametrize('declared', [False, True])
def test_parameter_width_requires_the_actual_declared_default(tmp_path, declared):
    p = project(tmp_path, widths=('[W-1:0]', '[W-1:0]', '[2*W-1:0]'), operator='*')
    update_declaration(p, function=function('*', 14))
    if declared:
        rtl = p / 'phase2/stage1/rtl'
        rtl.mkdir(parents=True)
        (rtl / 'neutral_arithmetic.v').write_text(
            'module neutral_arithmetic #(parameter W=7)(input [W-1:0] left,right, '
            'output [2*W-1:0] result); assign result=left*right; endmodule\n')
    spec, reason = extract(p)
    if declared:
        assert spec is not None, reason
        assert [spec[k] for k in ('operand_a_width', 'operand_b_width', 'result_width')] == [7, 7, 14]
    else:
        assert spec is None, (spec, reason)


def test_actual_runner_propagates_handoff_without_simulation(tmp_path):
    p = project(tmp_path, declare=False)
    before = {f.relative_to(p): f.read_bytes() for f in p.rglob('*') if f.is_file()}
    import design_one_shot_runner as runner
    step = runner.step_professional_tb_gen(p, 'neutral_arithmetic', 'unused')
    report = json.loads((p / 'reports/phase2/gates/professional_tb.json').read_text())
    assert (step.status, report['status'], report['ran_cocotb']) == ('NOT_MEASURED', 'INCOMPLETE', False)
    assert step.extras['fallback_skill'] == 'testbench-gen'
    assert not (p / 'phase2').exists()
    assert all((p / name).read_bytes() == content for name, content in before.items())


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


def phase1_project(root, records=PHASE1_RECORDS, *, size=8, declare=True):
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
        'parallel_hold': 'through_final_product_bit',
        **({'function': function('*', size, 'p', ('x', 'y'))} if declare else {})}))
    return root


def serial_spec(p):
    return oracle.extract_serial_arith_spec(p, 'digital_arithmetic_primitive')


def test_multi_section_phase1_design_keeps_its_serial_reference_through_the_typed_field(tmp_path):
    p = phase1_project(tmp_path)
    spec, reason = serial_spec(p)
    assert spec, reason
    assert (spec['operator'], spec['width'], spec['signed']) == ('*', 8, False)
    assert professional._detect_stream_operator(p, 'digital_arithmetic_primitive') == '*'


def test_multi_section_prose_without_the_typed_field_hands_off(tmp_path):
    p = phase1_project(tmp_path, declare=False)
    spec, reason = serial_spec(p)
    assert spec is None and 'function field' in reason, (spec, reason)
    assert professional._detect_stream_operator(p, 'digital_arithmetic_primitive') is None


@pytest.mark.parametrize('field,reason', [
    (function('*', 6, 'p', ('x', 'y')), 'modulus_bits'),
    (function('*', 8, 'q', ('x', 'y')), 'data ports'),
    (function('*', 8, 'p', ('x', 'z')), 'data ports'),
])
def test_serial_function_field_must_agree_with_ports_and_word_width(tmp_path, field, reason):
    p = phase1_project(tmp_path)
    path = p / 'plugin_output/declaration.json'
    path.write_text(json.dumps({**json.loads(path.read_text()), 'function': field}))
    spec, why = serial_spec(p)
    assert spec is None and reason in why, (spec, why)


def test_serial_sign_must_be_declared(tmp_path):
    p = phase1_project(tmp_path)
    path = p / 'plugin_output/declaration.json'
    doc = json.loads(path.read_text())
    doc.pop('integer_encoding')
    path.write_text(json.dumps(doc))
    spec, why = serial_spec(p)
    assert spec is None and 'sign' in why, (spec, why)


def test_generated_serial_multiplier_declares_the_function_it_implements():
    import serial_parallel_mul_synth as synth
    source = Path(synth.__file__).read_text()
    assert '"operands": [spec["parallel"], spec["serial_in"]]' in source
