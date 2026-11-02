"""The arithmetic oracle's function comes from the typed declaration field alone."""
import json
from pathlib import Path
import subprocess
import sys

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


@pytest.mark.parametrize('width,malformed', [(8, 8.0), (1, True)])
@pytest.mark.parametrize('malformed_location', ['declaration.json', 'plugin_output/declaration.json'])
def test_each_function_field_is_validated_before_declaration_agreement(
        tmp_path, width, malformed, malformed_location):
    p = project(tmp_path)
    (p / 'plugin_output').mkdir()
    for location in ('declaration.json', 'plugin_output/declaration.json'):
        field = function(modulus_bits=malformed if location == malformed_location else width)
        (p / location).write_text(json.dumps({'function': field}))
    field, reason = oracle.declared_function(p)
    assert field is None and 'malformed' in reason, (field, reason)


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


def test_missing_source_handoff_keeps_existing_expert_resume_metadata(tmp_path):
    p = project(tmp_path, declare=False)
    import design_one_shot_runner as runner
    step = runner.step_professional_tb_gen(p, 'neutral_arithmetic', '')
    report = json.loads((p / 'reports/phase2/gates/professional_tb.json').read_text())
    out = p / 'phase2/stage1/sim_professional/neutral_arithmetic'
    assert (step.status, report['status'], report['ran_cocotb']) == (
        'NOT_MEASURED', 'INCOMPLETE', False), (step.detail, report)
    assert report.get('reference_model_tier') == 'hook_unfilled', report
    assert report.get('out_dir') == str(out), report
    assert report.get('reference_model_handoff') == professional.reference_model_handoff(out), report
    assert not out.exists()


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


@pytest.mark.parametrize('declared', [False, True])
def test_parameter_width_one_is_resolved_only_from_a_declared_default(tmp_path, declared):
    p = project(tmp_path, widths=('[W-1:0]',) * 3, operator='^')
    if declared:
        rtl = p / 'phase2/stage1/rtl'
        rtl.mkdir(parents=True)
        (rtl / 'neutral_arithmetic.v').write_text(
            'module neutral_arithmetic #(parameter W=1)(input [W-1:0] left,right, '
            'output [W-1:0] result); assign result=left^right; endmodule\n')
    spec, reason = extract(p)
    if declared:
        assert spec is not None, reason
        assert [spec[k] for k in ('operand_a_width', 'operand_b_width', 'result_width')] == [1, 1, 1]
    else:
        assert spec is None and 'unresolved' in reason, (spec, reason)


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
    if declare:
        (root / 'declaration.json').write_text(json.dumps({
            'function': function('*', size, 'p', ('x', 'y'))}))
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
    (p / 'declaration.json').write_text(json.dumps({'function': field}))
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


def producer_project(tmp_path, location=None, field=None):
    from test_serial_parallel_mul_synth import _mk_project, _SPM_PORTS
    p = _mk_project(tmp_path, ports=_SPM_PORTS, top='source_intent_unit',
                    l2_text='serial-parallel multiplier: p = (x * y) mod 2^N')
    (p / 'reports').mkdir()
    (p / 'reports/ic_class.json').write_text(json.dumps({
        'ic_class': 'digital_arithmetic_primitive'}))
    if location:
        path = p / location
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'integer_encoding': 'unsigned', 'function': field}))
    return p


def emit_serial(p, action='--emit'):
    import serial_parallel_mul_synth as synth
    result = subprocess.run([sys.executable, synth.__file__, str(p), action],
                            capture_output=True, text=True)
    (p / (action[2:] + '.stdout')).write_text(result.stdout)
    (p / (action[2:] + '.stderr')).write_text(result.stderr)
    return result


def professional_step(p):
    import design_one_shot_runner as runner
    import professional_tb_check as consumer
    step = runner.step_professional_tb_gen(p, 'source_intent_unit', '')
    (p / 'native-step.json').write_text(json.dumps(step.__dict__, default=str, indent=2))
    report = json.loads((p / 'reports/phase2/gates/professional_tb.json').read_text())
    return step, report, consumer.check(p)


def test_serial_producer_without_source_function_preserves_author_handoff(tmp_path):
    p = producer_project(tmp_path)
    for action in ('--emit', '--refresh-contract'):
        result = emit_serial(p, action)
        assert result.returncode == 0, result.stdout + result.stderr
        assert (p / 'phase2/stage1/rtl/source_intent_unit.v').stat().st_size > 0
        field, reason = oracle.declared_function(p)
        assert field is None and 'function field' in reason, (field, reason)
    step, report, check = professional_step(p)
    assert (step.status, report['status'], report['ran_cocotb']) == (
        'NOT_MEASURED', 'INCOMPLETE', False), (step.detail, report, check)
    assert report['fallback_skill'] == 'testbench-gen', report
    assert check['verdict'] == 'NOT_CHECKED', check


def test_serial_legacy_output_function_cannot_become_input_authority_on_refresh(tmp_path):
    import serial_parallel_mul_synth as synth
    p = producer_project(tmp_path)
    spec, reason = synth.extract_serial_parallel_mul_spec(p, 'digital_arithmetic_primitive')
    assert spec is not None, reason
    rtl = p / 'phase2/stage1/rtl/source_intent_unit.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text(synth.emit_rtl(spec))
    path = p / 'plugin_output/declaration.json'
    path.parent.mkdir()
    legacy = {**synth.plugin_declaration(spec), 'function': function('*', 32, 'p', ('x', 'y'))}
    original = (json.dumps(legacy, indent=4) + '\n\n').encode()
    path.write_bytes(original)
    before = path.stat()
    result = emit_serial(p, '--refresh-contract')
    assert result.returncode == 0, result.stdout + result.stderr
    assert path.read_bytes() == original
    after = path.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
    step, report, check = professional_step(p)
    assert (step.status, report['status'], check['verdict']) == (
        'NOT_MEASURED', 'INCOMPLETE', 'NOT_CHECKED'), (step.detail, report, check)
    assert report['ran_cocotb'] is False and report['fallback_skill'] == 'testbench-gen', report
    assert path.read_bytes() == original


@pytest.mark.parametrize('location', ['declaration.json', 'plugin_output/declaration.json'])
@pytest.mark.parametrize('broken', [False, True], ids=['correct-dut', 'wrong-output'])
def test_serial_producer_preserves_source_function_and_native_falsifiability(
        tmp_path, location, broken):
    field = function('*', 32, 'p', ('y', 'x'))
    p = producer_project(tmp_path, location, field)
    if location == 'plugin_output/declaration.json':
        (p / 'declaration.json').write_text(json.dumps({'function': field}))
    source = (p / location).read_bytes()
    result = emit_serial(p)
    assert result.returncode == 0, result.stdout + result.stderr
    assert oracle.declared_function(p) == (field, '')
    if location == 'declaration.json':
        assert (p / location).read_bytes() == source
    if broken:
        rtl = p / 'phase2/stage1/rtl/source_intent_unit.v'
        text = rtl.read_text()
        assert 'assign p = pr;' in text
        rtl.write_text(text.replace('assign p = pr;', "assign p = 1'b0;"))
    step, report, check = professional_step(p)
    status = 'FAIL' if broken else 'PASS'
    assert (step.status, report['status'], check['verdict']) == (status,) * 3, (
        step.detail, report, check)
    assert report['ran_cocotb'] is True and report['functional_mismatch'] is broken, report
    native = p / 'phase2/stage1/sim_professional/source_intent_unit'
    assert (native / 'cocotb_run.log').stat().st_size > 0
    assert (native / 'results.xml').stat().st_size > 0


@pytest.mark.parametrize('location', ['declaration.json', 'plugin_output/declaration.json'])
@pytest.mark.parametrize('field', [
    pytest.param(function('+', 32, 'p', ('x', 'y')), id='add-conflicts-with-multiply'),
    pytest.param(function('*', 16, 'p', ('x', 'y')), id='different-modulus'),
    pytest.param(function('*', 32, 'x', ('p', 'y')), id='reversed-port-roles'),
    pytest.param(function(['*'], 32, 'p', ('x', 'y')), id='malformed-operator'),
])
def test_serial_producer_refuses_incompatible_source_function_before_publication(
        tmp_path, location, field):
    p = producer_project(tmp_path, location, field)
    before = (p / location).read_bytes()
    result = emit_serial(p)
    assert result.returncode == 2, result.stdout + result.stderr
    assert json.loads(result.stdout)['verdict'] == 'DEFER'
    assert (p / location).read_bytes() == before
    assert not (p / 'phase2').exists()
