"""Local sequential invocation evidence, not native IC qualification."""
from pathlib import Path
from types import SimpleNamespace
import json
import os
import sys

import pytest
import shutil
import subprocess

from _hostpaths import require_repo

PROGRAMS = Path(os.environ.get('VIBEIC_VERSION_REVIEW_PROGRAMS',
                              str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(PROGRAMS))
import step_output_collector as versions
import step_preflight as preflight


def _rtl(project, content=b'earlier working output'):
    path = project / 'phase2/stage1/rtl/chip_top.v'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _record(project, attempt):
    folder = project / attempt.get('storage_root', 'steps') / attempt['folder']
    return folder, json.loads((folder / 'outputs.json').read_text())


def test_different_following_step_preserves_abandoned_partial_bytes(tmp_path):
    output = _rtl(tmp_path)
    accepted = versions.begin_step(tmp_path, '1')
    versions.finish_step(tmp_path, accepted, verdict='PASS', canonical_pass=True)
    abandoned = versions.begin_step(tmp_path, '1')
    output.write_bytes(b'partial bytes from interrupted step 1')
    following = versions.begin_step(tmp_path, '2')
    folder, record = _record(tmp_path, abandoned)
    assert record['status'] == 'INTERRUPTED'
    output.write_bytes(b'following step overwrote the shared working file')
    versions.finish_step(tmp_path, following, verdict='FAIL')
    assert (folder / output.name).read_bytes() == b'partial bytes from interrupted step 1'
    assert versions.latest_pass(tmp_path, '1')['folder'] == accepted['folder']


def test_one_shared_call_does_not_interrupt_its_own_sibling_attempts(tmp_path):
    _rtl(tmp_path)
    attempts = versions.begin_steps(tmp_path, [('11', {}), ('12', {}), ('13', {})])
    assert len(attempts) == 3
    for attempt in attempts:
        folder = tmp_path / 'steps' / attempt['folder']
        assert not (folder / 'outputs.json').exists()
    for attempt, outcome in zip(attempts, ('PASS', 'FAIL', 'NOT_MEASURED')):
        versions.finish_step(tmp_path, attempt, verdict=outcome)
    assert [_record(tmp_path, a)[1]['status'] for a in attempts] == ['PASS', 'FAIL', 'NOT_MEASURED']


def test_input_bytes_survive_later_input_changes(tmp_path):
    _rtl(tmp_path)
    spec = tmp_path / 'input/spec.txt'
    spec.parent.mkdir()
    spec.write_bytes(b'input A')
    attempt = versions.begin_step(tmp_path, '1', {'input/spec.txt': versions._sha(spec)})
    versions.finish_step(tmp_path, attempt, verdict='PASS', canonical_pass=True)
    spec.write_bytes(b'input B')
    folder, record = _record(tmp_path, attempt)
    assert (folder / 'inputs/input/spec.txt').read_bytes() == b'input A'
    assert record['input_files'][0]['sha256'] == versions._sha(folder / 'inputs/input/spec.txt')
    assert versions.latest_pass(tmp_path, '1')['current_inputs'] is False


def test_following_step_freezes_earlier_legacy_alias_bytes(tmp_path):
    output = _rtl(tmp_path, b'original legacy evidence')
    old = tmp_path / 'steps/phase2/stage1/1_legacy'
    old.mkdir(parents=True)
    (old / output.name).symlink_to(output)
    (tmp_path / 'steps/index.json').write_text(json.dumps({'steps': [
        {'id': '1', 'folder': 'phase2/stage1/1_legacy'}]}))
    following = versions.begin_step(tmp_path, '2')
    output.write_bytes(b'later step replaced canonical bytes')
    versions.finish_step(tmp_path, following, verdict='FAIL')
    assert not (old / output.name).is_symlink()
    assert (old / output.name).read_bytes() == b'original legacy evidence'


def test_missing_resolved_input_stops_before_producer(tmp_path):
    _rtl(tmp_path)
    with pytest.raises(OSError, match='input'):
        versions.begin_step(tmp_path, '1', {'input/lost.txt': 'f' * 64})


def _dispatch(project, rows):
    decision = preflight.Decision('design_one_shot_runner', 'dft_lec_chain', ['11', '12', '13'])
    return preflight._retained_dispatch(project, decision, None, lambda: rows, (), {})


def test_real_dft_result_names_keep_each_rows_own_outcome(tmp_path):
    rows = [SimpleNamespace(name='dft_scan_insertion', status='PASS', detail='measured tool result', outputs=[]),
            SimpleNamespace(name='post_dft_opt', status='FAIL', detail='tool refused', outputs=[]),
            SimpleNamespace(name='lec_equivalence', status='NOT_MEASURED', detail='upstream refused', outputs=[])]
    assert _dispatch(tmp_path, rows) is rows
    actual = {r['id']: r['status'] for r in versions._read_index(tmp_path)['steps']}
    assert actual == {'11': 'PASS', '12': 'FAIL', '13': 'NOT_MEASURED'}
    assert all(versions.latest_pass(tmp_path, sid) is None for sid in actual)


def test_unattributed_group_pass_cannot_invent_per_step_pass(tmp_path):
    rows = [SimpleNamespace(name='unattributed_group', status='PASS', detail='', outputs=[])]
    _dispatch(tmp_path, rows)
    actual = {r['id']: r['status'] for r in versions._read_index(tmp_path)['steps']}
    assert actual == {'11': 'NOT_MEASURED', '12': 'NOT_MEASURED', '13': 'NOT_MEASURED'}
    assert all(versions.latest_pass(tmp_path, sid) is None for sid in actual)


def test_shared_interruption_retains_every_active_attempt(tmp_path):
    decision = preflight.Decision('design_one_shot_runner', 'dft_lec_chain', ['11', '12', '13'])
    def interrupted():
        partial = tmp_path / 'reports/native-dft.log'
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.write_bytes(b'partial native log before interruption')
        raise KeyboardInterrupt('local producer interrupted')
    with pytest.raises(KeyboardInterrupt):
        preflight._retained_dispatch(tmp_path, decision, None, interrupted, (), {})
    saved = versions._read_index(tmp_path)['steps']
    assert {r['id']: r['status'] for r in saved} == {'11': 'INTERRUPTED', '12': 'INTERRUPTED', '13': 'INTERRUPTED'}
    for row in saved:
        assert (tmp_path / 'steps' / row['folder'] / 'files/reports/native-dft.log').read_bytes() == b'partial native log before interruption'


def test_default_missing_input_is_retained_without_starting_producer(tmp_path, monkeypatch):
    import phase3_one_shot_runner as runner
    import execution_backend_worker as worker
    import execution_backend_producers as producers
    monkeypatch.setattr(runner, '_backend_parameter_values', lambda *args: {})
    monkeypatch.setattr(worker, 'resolve_input_contract', lambda *args: ['current CTS input absent'])
    def forbidden(*args, **kwargs):
        raise AssertionError('native producer started with a missing input')
    monkeypatch.setattr(producers, 'produce', forbidden)
    result = runner._default_pnr_rows(tmp_path, 'unit', SimpleNamespace(name='unit'), '', ['19'])
    assert result.status == 'NOT_MEASURED'
    row = next(r for r in versions._read_index(tmp_path)['steps'] if r['id'] == '19')
    _, record = _record(tmp_path, row)
    assert record['status'] == 'NOT_MEASURED'
    assert record['result']['missing_inputs'] == ['current CTS input absent']
    assert not record['canonical_pass']


def test_default_condition_skip_has_a_version_without_running_tool(tmp_path, monkeypatch):
    import phase3_one_shot_runner as runner
    import flow_compliance_check as compliance
    import execution_backend_producers as producers
    monkeypatch.setattr(runner, '_backend_parameter_values', lambda *args: {})
    monkeypatch.setattr(compliance, '_check_condition', lambda *args: False)
    def forbidden(*args, **kwargs):
        raise AssertionError('native producer ran for an inapplicable design condition')
    monkeypatch.setattr(producers, 'produce', forbidden)
    runner._default_pnr_rows(tmp_path, 'unit', SimpleNamespace(name='unit'), '', ['15.5ic'])
    row = next(r for r in versions._read_index(tmp_path)['steps'] if r['id'] == '15.5ic')
    _, record = _record(tmp_path, row)
    assert record['status'] == 'NOT_APPLICABLE'
    assert not record['canonical_pass']
    assert versions.latest_pass(tmp_path, '15.5ic') is None


@pytest.fixture(scope='module')
def installed_plugin(tmp_path_factory):
    # Ship production files at an arbitrary cache path, with no enclosing Git
    # checkout. Do not accidentally import the developer's programs in-process.
    destination = tmp_path_factory.mktemp('installed-flow') / 'plugin cache' / 'vibe-ic'
    shutil.copytree(PROGRAMS.parent, destination, ignore=shutil.ignore_patterns(
        '.git', 'node_modules', '__pycache__', '.pytest_cache', 'tests'))
    probe = subprocess.run(['git', '-C', str(destination), 'rev-parse', '--show-toplevel'],
                           capture_output=True, text=True)
    assert probe.returncode != 0, 'installed-layout control is inside a Git checkout'
    return destination


@pytest.mark.parametrize('invalid_clock', [False, True], ids=['valid-sdc', 'bad-clock'])
def test_installed_default_retains_real_sdc_consumer(
        tmp_path, installed_plugin, invalid_clock):
    source = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                          'tests', 'fixtures', 'ppa', 'power', 'activity_basis_pair',
                          'constraint.sdc')
    constraints = tmp_path / 'phase2/stage2/constraints/constraint.sdc'
    constraints.parent.mkdir(parents=True)
    content = source.read_text()
    if invalid_clock:
        import re
        content, count = re.subn(r'(-period\s+)\S+', r'\g<1>-1', content, count=1)
        assert count == 1
    constraints.write_text(content)
    l8 = tmp_path / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json'
    l8.parent.mkdir(parents=True)
    l8.write_text('{"clocks":{}}\n')
    # Select the supported direct SDC consumer, independent of PnR defaults.
    switch = tmp_path / 'phase3/librelane_switch.json'
    switch.parent.mkdir()
    switch.write_text('{"steps":{"8":"direct"}}\n')
    script = r'''
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
import execution_policy as policy
import step_preflight as preflight
import step_output_collector as versions
import design_one_shot_runner as design
project = Path(sys.argv[2])
runtime = policy.bootstrap(project)
assert runtime['policy']['mode'] == 'default'
result = preflight.retained_call(project, '8', design.step_sdc_validation, project)
record = next(row for row in versions._read_index(project)['steps'] if row['id'] == '8')
assert record['status'] == result.status
assert (project / 'reports/phase2/sdc_check.json').is_file()
# Loading installed metadata must not grant Git-bound candidate authority.
import execution_modes as em
try:
    em._canonical_flow_requirements()
except em.Refusal as exc:
    assert exc.code.startswith('PORTFOLIO_CANONICAL_'), exc
else:
    raise AssertionError('installed files acquired Git candidate authority')
print(json.dumps({'status': result.status, 'detail': result.detail}))
'''
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(('GIT_', 'VIBEIC_EXECUTION_', 'VIBEIC_LIBRELANE_'))}
    environment.pop('VIBEIC_IC_IP_ROUTE', None)
    environment.update(PYTHONDONTWRITEBYTECODE='1',
                       CLAUDE_PLUGIN_ROOT=str(installed_plugin),
                       VIBE_IC_PROGRAMS_DIR=str(installed_plugin / 'programs'))
    ran = subprocess.run([sys.executable, '-I', '-c', script,
                          str(installed_plugin / 'programs'), str(tmp_path)],
                         cwd=tmp_path, env=environment, capture_output=True,
                         text=True, timeout=60)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    report = json.loads(ran.stdout.splitlines()[-1])
    assert report['status'] == ('FAIL' if invalid_clock else 'PASS'), report
    if invalid_clock:
        assert 'sdc_syntax_check rc=1' in report['detail']
    else:
        validator = json.loads((tmp_path / 'reports/sdc_validator.json').read_text())
        assert validator['verdict'] == 'PASS'
        assert validator['sdc_files_checked'] == [str(constraints)]
