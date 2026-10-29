"""Source-scoped reset observation through the real unit-TB producer/reader.

The native fixture is explicitly upstream-isolated. Its L10 population contains
only the root-authorized affected reset case; it grants no product approval.
"""
from pathlib import Path
import copy
import hashlib
import inspect
import json
import os
import re
import shutil
import sys

import pytest

PROGRAMS = Path(os.environ.get('E_RESET_PROGRAMS', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(PROGRAMS))
import arith_oracle_tb_gen as arith
import testbench_gen as producer
import _l10_execution as execution

pytestmark = pytest.mark.skipif(
    'E_RESET_FIXTURE_INPUT' not in os.environ,
    reason='root-scoped qualification input unavailable; not native qualification')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def project(tmp_path, wrong=False):
    template = Path(os.environ['E_RESET_FIXTURE_INPUT'])
    root = tmp_path / ('wrong' if wrong else 'good')
    shutil.copytree(template, root)
    rtl = root / 'phase2/stage1/rtl/spm.v'
    observation = json.loads((root / 'input/flow109/D13/source.json').read_text())
    observation = observation['scenario_requirements']['reset']['reset_observation']
    if wrong:
        text, count = re.subn(r"\bpr(\s*<=\s*)1'b0", r"pr\g<1>1'b1", rtl.read_text())
        assert count == 1
        rtl.write_text(text)
    # The counterfactual source fingerprint is a changed qualification input,
    # never a new root approval/signature. Required values remain independent.
    observation['source_reference']['sha256'] = digest(rtl)
    decision = {'purpose': 'UPSTREAM_ISOLATED_RESET_QUALIFICATION_FIXTURE_ONLY',
                'scenario_requirements': {'reset': {'reset_observation': observation}}}
    (root / 'input/flow109/D13/source.json').write_text(json.dumps(decision))
    return root, observation


def emit_and_run(root):
    assert shutil.which('verilator'), 'actual native Verilator is required'
    report = {}
    assert producer.emit_unit_tbs(root, top='spm', report=report) == 1, report
    assert producer.run_unit_tbs(root, container=None, report=report) == 1, report
    record = execution.load_record(root, root / 'phase1/generated_docs/L10_TEST_CASES.json')
    return report, record, execution.scenario_case_state('reset', record)


def test_reset_required_values_actual_good(tmp_path):
    root, observation = project(tmp_path)
    report, record, state = emit_and_run(root)
    assert state[0] == 'PASS', (state, report)
    measured = record['rows']['reset']['arithmetic_scenario']
    assert measured['plan'].get('reset_observation') == observation
    assert measured['complete'] and measured['errors'] == 0
    assert measured['comparisons'] > 0 and measured['transactions'] > 0
    assert [{k: r[k] for k in ('state', 'width', 'expected_value')}
            for r in measured['reset_observations']] == observation['required_observations']
    assert all(r['samples'] == measured['held_edges'] > 0 and r['mismatches'] == 0
               for r in measured['reset_observations'])


def test_reset_wrong_value_actual_native_refuses(tmp_path):
    root, _ = project(tmp_path, wrong=True)
    report, record, state = emit_and_run(root)
    assert state[0] == 'FAIL', (state, report)
    measured = record['rows']['reset']['arithmetic_scenario']
    assert measured['errors'] > 0 and measured['complete']
    wrong = next(r for r in measured['reset_observations'] if r['state'] == 'pr')
    assert wrong['mismatches'] == wrong['samples'] > 0
    log = Path(measured['transcript']).read_text()
    assert 'FAIL: reset expected state pr' in log
    assert 'fixed-window bit=' not in log, 'functional arithmetic must remain unchanged'


def test_reset_omitted_required_monitor_actual_native_unmeasured(tmp_path, monkeypatch):
    root, _ = project(tmp_path)
    # A module-present source intervention drops one emitted required monitor.
    # The plan/readset/required population and all arithmetic assertions stay.
    source = inspect.getsource(arith.emit_arithmetic_scenario_module)
    original = 'for index, required in enumerate(required_reset):'
    assert original in source
    source = source.replace(original, 'for index, required in enumerate(required_reset[:-1]):', 1)
    variant = tmp_path / 'omitted_monitor_emitter.py'
    variant.write_text(source)
    namespace = dict(arith.__dict__)
    exec(compile(source, str(variant), 'exec'), namespace)
    monkeypatch.setattr(arith, 'emit_arithmetic_scenario_module', namespace['emit_arithmetic_scenario_module'])
    report = {}
    assert producer.emit_unit_tbs(root, top='spm', report=report) == 1
    assert producer.run_unit_tbs(root, container=None, report=report) == 0, report
    record = execution.load_record(root, root / 'phase1/generated_docs/L10_TEST_CASES.json')
    assert execution.scenario_case_state('reset', record)[0] == 'NOT_EXECUTED'
    row = record['rows']['reset']
    assert row['arithmetic_scenario']['complete'] is False
    assert len(row['arithmetic_scenario']['reset_observations']) + 1 == len(
        row['arithmetic_scenario']['plan']['reset_observation']['required_observations'])


def test_reset_missing_required_input_normal_producer_refuses(tmp_path):
    root, _ = project(tmp_path)
    path = root / 'input/flow109/D13/source.json'
    doc = json.loads(path.read_text())
    del doc['scenario_requirements']['reset']['reset_observation']
    path.write_text(json.dumps(doc))
    report = {}
    assert producer.emit_unit_tbs(root, top='spm', report=report) == 0, report
    assert not list((root / 'phase2/stage1/sim/tb').glob('*.v'))
    assert report['arithmetic_scenario_requests'][0]['verdict'] == 'NOT_MEASURED'


@pytest.mark.parametrize('change', ['stale_source', 'duplicate_state', 'bad_width'])
def test_reset_invalid_required_input_refuses(tmp_path, change):
    root, _ = project(tmp_path)
    path = root / 'input/flow109/D13/source.json'
    doc = json.loads(path.read_text()); obs = doc['scenario_requirements']['reset']['reset_observation']
    if change == 'stale_source':
        obs['source_reference']['sha256'] = '0' * 64
    elif change == 'duplicate_state':
        obs['required_observations'].append(copy.deepcopy(obs['required_observations'][0]))
    else:
        obs['required_observations'][0]['width'] = True
    path.write_text(json.dumps(doc)); report = {}
    assert producer.emit_unit_tbs(root, top='spm', report=report) == 0, report
    assert report['arithmetic_scenario_requests'][0]['verdict'] == 'NOT_MEASURED'
