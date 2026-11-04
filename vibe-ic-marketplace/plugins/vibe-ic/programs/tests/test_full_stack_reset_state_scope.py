"""A wrapped reset observes the same declared state inside the selected core."""
import hashlib
import json
import re
from pathlib import Path

import pytest

import full_stack_functional_tb as full_stack
from test_fullstacktb_functional_population import _timed_input, _timed_native


def _project(tmp_path, key, *, wrong=False, ambiguous=False):
    root = tmp_path / 'input_case'
    _timed_input(root, key)
    spec = json.loads((root / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json').read_text())
    clock = spec['clocks'][0]['name']
    reset = spec['reset_domains'][0]['name']
    rtl = root / 'phase2/stage1/rtl/public_serial_product.v'
    text = rtl.read_text().replace('endmodule',
        f"reg reset_witness=0; always @(posedge {clock}) if ({reset}) reset_witness <= 1'b{int(wrong)};\nendmodule")
    rtl.write_text(text)
    wrapper = root / 'phase3/stage3/pnr/public_surface.v'
    if wrapper.exists():
        text = wrapper.read_text().replace('public_serial_product core(',
                                           'public_serial_product selected_engine(')
        if ambiguous:
            instance = re.search(r'public_serial_product selected_engine\(.*?\);', text, re.S).group()
            text = text.replace('endmodule', instance.replace('selected_engine', 'second_engine') + '\nendmodule')
        wrapper.write_text(text)
        declaration_path = root / 'plugin_output/declaration.json'
        declaration = json.loads(declaration_path.read_text())
        binding = declaration['verification_stimuli']['arithmetic_observation']['public_surface']['binding']
        binding[str(wrapper.relative_to(root))] = hashlib.sha256(wrapper.read_bytes()).hexdigest()
        declaration_path.write_text(json.dumps(declaration))
    requirement = root / 'phase1/generated_docs/L10_TEST_CASES.json'
    observation = {
        'clock': clock, 'reset': reset, 'active_level': 1, 'edge': 'rising',
        'observation': 'Observe the declared state after an asserted reset edge settles.',
        'source_reference': {'path': str(rtl.relative_to(root)),
                             'sha256': hashlib.sha256(rtl.read_bytes()).hexdigest()},
        'original_requirement_reference': {'path': str(requirement.relative_to(root)),
                                           'sha256': hashlib.sha256(requirement.read_bytes()).hexdigest()},
        'required_observations': [{'state': 'reset_witness', 'width': 1, 'expected_value': 0}],
    }
    decision = root / 'input/flow109/D13/source.json'
    decision.parent.mkdir(parents=True, exist_ok=True)
    decision.write_text(json.dumps({'scenario_requirements': {
        'reset_situations': {'reset_observation': observation}}}))
    return root, observation


@pytest.mark.parametrize('key', ['core4', 'wrapped4_zero', 'wrapped8_delayed'])
def test_native_reset_observes_the_declared_state_through_the_selected_top(tmp_path, key):
    root, observation = _project(tmp_path, key)
    result, rc, consumed = _timed_native(root)
    case = next(c for c in result['cases'] if c['name'] == 'reset_situations')
    assert case['build_rc'] == 0, case
    assert case['run_rc'] == 0 and case['state'] == 'passed', case
    assert result['verdict'] == 'PASS' and rc == 0, consumed
    measured = case['arithmetic_scenario']
    assert measured['plan']['reset_observation'] == observation
    assert measured['transactions'] == 180 and measured['errors'] == 0
    probe, = measured['reset_observations']
    assert probe['samples'] == measured['held_edges'] > 0 and probe['mismatches'] == 0


def test_native_wrong_internal_reset_still_fails_with_correct_functional_output(tmp_path):
    root, _ = _project(tmp_path, 'wrapped4_zero', wrong=True)
    result, rc, consumed = _timed_native(root)
    case = next(c for c in result['cases'] if c['name'] == 'reset_situations')
    assert case['build_rc'] == 0, case
    assert case['run_rc'] == 1 and case['state'] == 'failed', case
    assert result['verdict'] == 'FAIL' and rc == 1, consumed
    measured = case['arithmetic_scenario']
    probe, = measured['reset_observations']
    assert probe['mismatches'] == probe['samples'] > 0
    transcript = (root / case['run_log']).read_text()
    assert 'FAIL: reset expected state reset_witness' in transcript
    assert 'fixed-window bit=' not in transcript


def test_ambiguous_wrapper_refuses_the_required_reset_scope(tmp_path):
    root, _ = _project(tmp_path, 'wrapped4_zero', ambiguous=True)
    top = full_stack.required_full_stack_top(root)
    model = root / 'input/models/public_delay.v'
    staged, why = full_stack.stage_models(root, full_stack.functional_dir(root),
        {'PUBLIC_CLK', 'PUBLIC_OUT'}, None,
        lambda *args: ({str(model): model.read_text()}, 'declared neutral models'))
    assert staged, why
    case = json.loads((root / 'phase1/generated_docs/L10_TEST_CASES.json').read_text())['test_cases'][-1]
    request = {}
    plan = full_stack.arithmetic_plan_for_top(root, case, 'digital_arithmetic_primitive', top, staged, request)
    assert plan is None, plan
    assert request['reason_class'] == full_stack.MISSING_OBSERVATION_CONTRACT
    assert 'one scalar' in '; '.join(request['unsupported_requirements'])


@pytest.mark.parametrize('mode', ['same_bytes', 'wrong_hash', 'wrong_kit', 'ambiguous', 'prior_changed'])
def test_native_wrapped_reset_resolves_only_same_pdk_model_bytes(tmp_path, mode):
    root, _ = _project(tmp_path, 'wrapped4_zero')
    model = root / 'input/models/public_delay.v'
    content = model.read_bytes()
    suffix = Path('neutral_kit/libs.ref/public_io/verilog/public_delay.v')
    live = tmp_path / 'active_pdk' / suffix
    live.parent.mkdir(parents=True)
    live.write_bytes(content)
    prior = tmp_path / 'old_pdk' / suffix
    if mode == 'wrong_kit':
        prior = tmp_path / 'old_pdk/other_kit/libs.ref/public_io/verilog/public_delay.v'
    if mode == 'prior_changed':
        prior.parent.mkdir(parents=True)
        prior.write_bytes(content + b'// changed prior model\n')
    declaration_path = root / 'plugin_output/declaration.json'
    declaration = json.loads(declaration_path.read_text())
    binding = declaration['verification_stimuli']['arithmetic_observation']['public_surface']['binding']
    digest = binding.pop(str(model.relative_to(root)))
    binding[str(prior)] = '0' * 64 if mode == 'wrong_hash' else digest
    wrapper = root / 'phase3/stage3/pnr/public_surface.v'
    digest = binding.pop(str(wrapper.relative_to(root)))
    binding[str(tmp_path / 'old_carrier' / wrapper.relative_to(root))] = digest
    declaration_path.write_text(json.dumps(declaration))
    original = declaration_path.read_bytes()
    models = {str(live): live.read_text()}
    if mode == 'ambiguous':
        second = tmp_path / 'second_pdk' / suffix
        second.parent.mkdir(parents=True)
        second.write_bytes(content)
        models[str(second)] = second.read_text()
    result = full_stack.generate(root, model_resolver=lambda *args: (models, 'neutral relocated models'))
    assert declaration_path.read_bytes() == original
    assert not (root / 'plugin_output/declaration_history').exists()
    if mode == 'same_bytes':
        assert result['verdict'] == 'PASS', result
        assert result['observation_provenance_refresh']['state'] == 'RESOLVED'
        reset = next(c for c in result['cases'] if c['name'] == 'reset_situations')
        assert reset['state'] == 'passed' and reset['build_rc'] == reset['run_rc'] == 0
        measured = reset['arithmetic_scenario']
        assert measured['transactions'] == 180 and measured['errors'] == 0
        assert measured['reset_observations'][0]['mismatches'] == 0
    else:
        assert result['verdict'] == 'NOT_MEASURED', result
        assert result['counts']['executed'] == 0
        assert result['reason_class'] == 'MISSING_OBSERVATION_CONTRACT'
