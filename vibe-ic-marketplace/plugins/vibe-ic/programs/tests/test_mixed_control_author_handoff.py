"""A generic mixed controller is authored from its own declared interface."""
import json
from pathlib import Path

import design_one_shot_runner as runner


def test_mixed_control_uses_normal_expert_author_handoff(tmp_path, monkeypatch):
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    values = {
        'L1_DATASHEET.json': {'ic_name': 'example_control', 'class_path': 'mixed_signal_otp'},
        'L2_FRS.json': {'has_digital': True, 'has_analog': True,
                       'functional_requirements': ['Digital command controller with OTP sequencing.']},
        'L9_INTEGRATION_SPEC.json': {'top_module': 'cfg_controller', 'parameters': [],
            'top_ports': [{'name': 'clock', 'direction': 'input', 'width': 1},
                          {'name': 'reset_n', 'direction': 'input', 'width': 1},
                          {'name': 'cfg_in', 'direction': 'input', 'width': 4},
                          {'name': 'ready', 'direction': 'output', 'width': 1}]},
    }
    for name, value in values.items():
        (docs / name).write_text(json.dumps(value))
    monkeypatch.setattr(runner, '_RTL_SESSION_OWNED', False)
    monkeypatch.setattr(runner, '_RTL_SESSION_PROJECT', None)
    result = runner.step_rtl_gen(tmp_path, 'mixed_signal_otp')
    assert result.status == 'PASS_WITH_WAIVERS', result.detail
    assert result.extras['fallback_skill'] == 'spec-to-rtl'
    assert not list((tmp_path / 'phase2/stage1/rtl').glob('*.sv'))
    assert 'IC class' in result.detail


def test_protocol_specific_generator_remains_registered():
    entry = runner._lookup_class('aid_class_half_duplex_single_wire')
    assert entry['rtl_gen'] == 'aid_class_rtl_gen.py'
