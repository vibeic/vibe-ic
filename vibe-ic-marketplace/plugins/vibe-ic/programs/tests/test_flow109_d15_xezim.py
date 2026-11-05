"""Native power-transition coverage and isolation/retention transcript controls."""
from __future__ import annotations
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
import flow109_frontend as owner


def put(project, name, value):
    path = project / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value))
    return name


def case(project, monkeypatch):
    checks = {'isolation': ['ok   clamp = 00'], 'retention': ['ok   retained = a5']}
    items = [{'id': 'sleep', 'domain': 'PD_UNIT', 'state': 'down', 'time': '7'},
             {'id': 'wake', 'domain': 'PD_UNIT', 'state': 'up', 'time': '9'}]
    return inputs(project, checks, items)


def inputs(project, checks, items):
    context = {'requested_step': 'D15', 'top': 'unit_tb', 'required': items,
        'rtl': [put(project, 'phase2/stage1/rtl/unit.sv', 'module unit; endmodule\n')],
        'testbench': put(project, 'input/verification/unit_tb.sv', 'module unit_tb; initial $finish; endmodule\n'),
        'upf': put(project, 'input/power/unit.upf', 'create_power_domain PD_UNIT\n'),
        'expected_checks': checks}
    return context, context

OUTPUT = """[UPF] Time: 7, Power domain 'PD_UNIT' is powered down
[UPF] Time: 9, Power domain 'PD_UNIT' is powered up
ok   clamp = 00
ok   retained = a5
Simulation finished at time 10 ($finish called)
"""

def replay(monkeypatch, out=OUTPUT, err=''):
    original = owner.subprocess.run
    def run(argv, **kwargs):
        if '--simulate' in argv:
            return SimpleNamespace(returncode=0, stdout=out, stderr=err)
        return original(argv, **kwargs)
    monkeypatch.setattr(owner.subprocess, 'run', run)

def test_public_owner_positive_measures_both_existing_obligations(tmp_path, monkeypatch):
    context, _ = case(tmp_path, monkeypatch)
    replay(monkeypatch)
    result = owner.execute(tmp_path, context)
    assert result['component_status'] == 'PASS', result
    assert result['observations']['obligations'][0]['observed_value'] == ['sleep', 'wake']
    assert result['observations']['obligations'][1]['observed_value'] == 0

@pytest.mark.parametrize('mutation', ['retention', 'isolation', 'transition'])
def test_public_owner_rc0_semantic_or_coverage_failure(tmp_path, monkeypatch, mutation):
    context, _ = case(tmp_path, monkeypatch)
    if mutation == 'transition':
        out = OUTPUT.replace("[UPF] Time: 9, Power domain 'PD_UNIT' is powered up\n", '')
    else:
        line = 'ok   retained = a5' if mutation == 'retention' else 'ok   clamp = 00'
        out = OUTPUT.replace(line, 'FAIL ' + mutation + ': incorrect value')
    replay(monkeypatch, out)
    result = owner.execute(tmp_path, context)
    assert result['component_status'] == 'FAIL', result
    assert result['returncode'] == 0

def test_public_owner_native_warning_refuses(tmp_path, monkeypatch):
    context, _ = case(tmp_path, monkeypatch)
    replay(monkeypatch, err='[UPF] warning: unresolved isolation signal\n')
    result = owner.execute(tmp_path, context)
    assert result['component_status'] == 'NOT_MEASURED'
    assert result.get('observations', {}).get('reason') == 'D15_NATIVE_FEATURE_UNRESOLVED', result

@pytest.mark.parametrize('arm,expected', [('positive', 'PASS'), ('missing_retention', 'FAIL'),
                                        ('missing_isolation', 'FAIL')])
def test_reuse_staged_native_controls_without_launch(tmp_path, monkeypatch, arm, expected):
    if not os.environ.get('D15_STAGED'):
        pytest.skip('native replay receipts unavailable: set D15_STAGED to the staged audit input root')
    staged = Path(os.environ['D15_STAGED'])
    controls = staged / 'xezim-native-controls'
    upstream = staged / 'xezim-upstream'
    context, manifest = case(tmp_path, monkeypatch)
    positive = (controls / 'positive/stdout.log').read_text()
    checks = {'isolation': [line for line in positive.splitlines() if line.startswith('ok   ') and 'clamped' in line],
              'retention': [line for line in positive.splitlines() if line.startswith('ok   ') and 'retained' in line]}
    items = [{'id': name, 'domain': 'PD_ACC', 'state': state, 'time': time}
             for name, state, time in [('sleep', 'down', '77'), ('wake', 'up', '106')]]
    context, manifest = inputs(tmp_path, checks, items)
    manifest['top'] = 'pwr_demo_tb'
    manifest['upf'] = put(tmp_path, 'input/power/native.upf', (controls / arm / 'intent.upf').read_text())
    manifest['rtl'] = [put(tmp_path, 'phase2/stage1/rtl/' + name,
                          (upstream / 'examples/upf' / name).read_text())
                       for name in ('pwr_demo.sv',)]
    manifest['testbench'] = put(tmp_path, 'input/verification/pwr_demo_tb.sv',
        (upstream / 'examples/upf/pwr_demo_tb.sv').read_text())
    replay(monkeypatch, (controls / arm / 'stdout.log').read_text(),
           (controls / arm / 'stderr.log').read_text())
    result = owner.execute(tmp_path, context)
    assert result['component_status'] == expected, result
    assert result['returncode'] == 0

def test_public_owner_missing_behavior_check_is_unmeasured(tmp_path, monkeypatch):
    context, _ = case(tmp_path, monkeypatch)
    replay(monkeypatch, OUTPUT.replace('ok   retained = a5\n', ''))
    result = owner.execute(tmp_path, context)
    assert result['component_status'] == 'NOT_MEASURED'
    assert result.get('observations', {}).get('reason') == 'D15_BEHAVIOR_CHECKS_INCOMPLETE', result
