"""Source-cited semantic roles are input facts, not approval receipts."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_signed_judgement as subject


@pytest.fixture
def roles(tmp_path, monkeypatch):
    rtl = tmp_path / 'phase2/stage1/rtl/m.sv'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('always @(posedge clk) if (enable) q <= d;\n')
    intent = tmp_path / 'input/design_input.txt'
    intent.parent.mkdir()
    intent.write_text('Enable updates functional state.\n')
    candidate = {'state': 'q', 'q': [3], 'selector': 2, 'source': 'm.sv:1'}
    request = {'candidates': [candidate], 'netlist_sha256': 'existing-context'}
    monkeypatch.setattr(subject, 'reset_role_request', lambda _: request)
    binding = {'input': {'rtl_files': [str(rtl.relative_to(tmp_path))],
                         'files': [{'path': str(rtl.relative_to(tmp_path))}]}}
    monkeypatch.setattr(subject, '_reset_context', lambda _: (None, None, binding))
    packet = {'reset_roles': [{'candidate': candidate, 'role': 'functional_update',
        'rationale': 'Enable selects the documented functional update.',
        'source_context': [{'file': str(rtl.relative_to(tmp_path)), 'line': 1,
                            'quote': 'if (enable) q <= d;'}],
        'intent': [{'file': str(intent.relative_to(tmp_path)), 'line': 1,
                    'quote': 'Enable updates functional state.'}]}]}
    target = tmp_path / 'reports/audit/ai_judgements/3.json'
    target.parent.mkdir(parents=True)
    return tmp_path, target, packet


def test_plain_source_semantics_need_no_pass_signature_or_hash(roles):
    project, target, packet = roles
    target.write_text(json.dumps(packet))
    result, reason = subject.reset_roles(project)
    assert result == {'q': 'functional_update'}, reason


@pytest.mark.parametrize('change', ['missing', 'unresolved'])
def test_missing_or_unresolved_role_stays_unresolved(roles, change):
    project, target, packet = roles
    if change == 'missing':
        packet['reset_roles'] = []
    else:
        packet['reset_roles'][0]['role'] = 'unresolved'
    target.write_text(json.dumps(packet))
    result, reason = subject.reset_roles(project)
    assert result == ({} if change == 'missing' else {'q': 'unresolved'})
    assert 'unresolved' in reason.lower() or 'do not cover' in reason
