"""Drive the existing LEC owner against actual qualified, retained D25 inputs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

import pytest
import design_one_shot_runner as runner
import flow109


pytestmark = pytest.mark.skipif(not os.environ.get('FLOW109_D25_REUSE_REFERENCE'),
                                reason='actual immutable native reference required')
_AUDIT = {'active': False, 'attempts': [], 'gate_reads': []}


def _refuse_process(event, args):
    if _AUDIT['active'] and event == 'subprocess.Popen':
        argv = [str(value) for value in args[1]]
        if any(Path(value).name == 'lec_equivalence_check.py' for value in argv):
            _AUDIT['gate_reads'].append(argv)
            return
        _AUDIT['attempts'].append(argv)
        raise AssertionError('unchanged proof or unsupported subprocess dispatch was attempted')


sys.addaudithook(_refuse_process)


def readset(project):
    return {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in project.rglob('*') if p.is_file()}


@pytest.fixture
def subject(tmp_path, monkeypatch):
    project = Path('/out/canonical/projects/good')
    mounts = [line.split() for line in Path('/proc/self/mountinfo').read_text().splitlines()]
    assert any(fields[4] == str(project) and 'rw' in fields[5].split(',') for fields in mounts)
    for child in project.iterdir():
        shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
    shutil.copytree(os.environ['FLOW109_D25_REUSE_REFERENCE'], project, dirs_exist_ok=True)
    features = json.loads((project / 'flow109-manifest.json').read_text())['features']
    context = flow109.execution_context(flow109.resolve_plan(features), 'D25', 'D25')
    context_file = tmp_path / 'context.json'
    context_file.write_text(json.dumps(context))
    attempt = flow109._new_attempt(project, context)
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(context_file))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
    return project, context_file


def invoke(project):
    # Preload the native package; then observe real consumers without replacing
    # any function whose code identity is part of their source readset.
    from librelane.steps.yosys import EQY  # noqa: F401
    observed = {}

    def profile(frame, event, arg):
        if event == 'call' and frame.f_code.co_filename.endswith('librelane_eqy.py'):
            name = frame.f_code.co_name
            observed[name] = observed.get(name, 0) + 1

    before = readset(project)
    _AUDIT['attempts'] = []
    _AUDIT['gate_reads'] = []
    _AUDIT['active'] = True
    previous = sys.getprofile()
    sys.setprofile(profile)
    try:
        result = runner.step_lec_equivalence(project, 'test_counter', '')[-1]
    finally:
        sys.setprofile(previous)
        _AUDIT['active'] = False
    after = readset(project)
    protected = ('input/', 'adopted/', 'requirements/', 'phase1/',
                 'phase2/stage1/rtl/', 'phase2/stage2/synth/', 'phase3/librelane/',
                 'reports/audit/phase1/', 'reports/audit/ai_judgements/')
    historical = {name: digest for name, digest in before.items()
                  if name.startswith(protected) or name in
                  ('reports/lec.json', 'reports/lec.rpt', 'reports/lec_eqy_execution.json')}
    changed = {name: {'before': digest, 'after': after.get(name)}
               for name, digest in historical.items() if after.get(name) != digest}
    outcome = {'status': result.status, 'detail': result.detail,
               'native_calls': observed, 'forbidden_process_attempts': _AUDIT['attempts'],
               'normal_gate_reads': _AUDIT['gate_reads'],
               'historical_evidence_changes': changed}
    target = os.environ.get('FLOW109_D25_REUSE_OBSERVATIONS')
    if target:
        with Path(target).open('a') as stream:
            stream.write(json.dumps(outcome) + '\n')
    assert not _AUDIT['attempts'], _AUDIT['attempts']
    assert not changed, 'reuse rewrote retained native/input/report evidence: ' + str(changed)
    return result, observed


def test_actual_qualified_execution_reopens_without_legacy_or_native_proof(subject):
    project, _ = subject
    result, observed = invoke(project)
    assert result.status == 'PASS', result
    assert observed.get('d25_run') == 1
    assert observed.get('d25_reopen', 0) >= 2
    accepted = result.extras['native_reuse']['metric_acceptance']
    assert accepted['qualification'] == 'PASS'
    assert len(accepted['obligations']) == 3
    assert all(row['status'] == 'PASS' for row in accepted['obligations'])
    assert result.output_files == []  # historical outputs are not new writes
    import step_output_collector as versions
    record = next(row for row in versions._read_index(project)['steps']
                  if str(row['id']) == '13')
    owner = json.loads((versions._versions_root(project) / record['folder'] /
                        'outputs.json').read_text())
    assert owner['canonical_pass'] is True, owner
    assert owner['result']['canonical_consumer']['status'] == 'PASS'


@pytest.mark.parametrize('damage,reason', [
    ('missing-execution', 'D25_NATIVE_EXECUTION_ABSENT'),
    ('stale-execution', 'D25_NATIVE_EXECUTION_UNQUALIFIED'),
    ('foreign-execution-link', 'D25_NATIVE_EXECUTION_ABSENT'),
    ('unapproved-execution', 'METRIC_AUTHORITY_UNAPPROVED'),
    ('unqualified-model', 'D25_MODEL_NOT_QUALIFIED'),
    ('unsupported-purpose', 'D25_PURPOSE_UNSUPPORTED'),
    ('stale-context', 'FLOW109_CONTEXT_STALE'),
])
def test_actual_reuse_refuses_without_falling_back_to_proof(subject, tmp_path,
                                                           damage, reason):
    project, context_file = subject
    execution = project / 'reports/lec_eqy_execution.json'
    if damage == 'missing-execution':
        execution.unlink()
    elif damage == 'stale-execution':
        doc = json.loads(execution.read_text())
        doc['program'] = 'foreign-controller'
        execution.write_text(json.dumps(doc))
    elif damage == 'foreign-execution-link':
        foreign = tmp_path / 'foreign-execution.json'
        foreign.write_bytes(execution.read_bytes())
        execution.unlink()
        execution.symlink_to(foreign)
    elif damage == 'unapproved-execution':
        path = project / 'adopted/base_16/native_execution.json'
        doc = json.loads(path.read_text())
        doc['approval']['status'] = 'UNAPPROVED'
        path.write_text(json.dumps(doc))
    elif damage in ('unqualified-model', 'unsupported-purpose'):
        path = project / 'input/flow109/D25.json'
        doc = json.loads(path.read_text())
        if damage == 'unqualified-model':
            doc['models'][0]['sha256'] = '0' * 64
        else:
            doc['purpose'] = 'unapproved-purpose'
        path.write_text(json.dumps(doc))
    else:
        doc = json.loads(context_file.read_text())
        doc['context_sha256'] = '0' * 64
        context_file.write_text(json.dumps(doc))
    result, _ = invoke(project)
    assert result.status == 'NOT_MEASURED', result
    assert reason in result.detail
