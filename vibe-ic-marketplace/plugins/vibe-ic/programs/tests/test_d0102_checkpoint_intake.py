"""Actual qualification-reader controls; no IC review or native acceptance.

The control envelope is synthetic. Its normal checkpoint shape/full ledger
comes from the supplied retained record, and available referenced outputs are
copied byte-for-byte into temporary storage. Missing historical outputs are
explicit fixture values, never presented as the original bytes. No authority
approval, D1 judgement or signature is authored by these controls.
"""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

import _flow_yaml
import _path_layout as layout
import _phase1_producer_identity as identity
import _step_identity as step_identity
import _step_recorder as recorder
import execution_backend_gates as gates
import flow109
import flow109_metric_acceptance as metrics
import step_output_collector as versions
from programs.tests._hostpaths import require_repo


def put(project, relative, value):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else
                     (json.dumps(value, indent=2) + '\n').encode())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def native_record():
    if not os.environ.get('INTAKE_RETAINED_RECORD') or not os.environ.get('INTAKE_RETAINED_READSET'):
        pytest.skip('retained controls require INTAKE_RETAINED_RECORD and INTAKE_RETAINED_READSET')
    return json.loads(Path(os.environ['INTAKE_RETAINED_RECORD']).read_bytes())


def case(project, *, transition=True, direct=False):
    source = native_record()
    assert source['canonical_pass'] and source['result']['site'] == 'phase1_checkpoint_revalidation'
    row = next(r for r in _flow_yaml.load()['steps'] if str(r['id']) == 'D1')
    original = source['result']['canonical_consumer']
    source_root = Path(os.environ['INTAKE_RETAINED_READSET'])
    exact = []
    for group in original['outputs'].values():
        for relative, digest in group.items():
            path = source_root / relative
            if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest:
                put(project, relative, path.read_bytes())
                exact.append(relative)
            else:
                # Synthetic missing-report fixture only, not repaired history.
                put(project, relative, {'fixture': 'not original retained output', 'value': 7})
    assert exact, 'source control must read actual referenced bytes'
    # Checked-in backing additionally exercises the shipped data-path resolver.
    backing = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs', 'tests',
        'fixtures', 'issue3473_retained_replay', 'historical', 'L8_TIMING_WAVEFORM.json')
    assert isinstance(json.loads(backing.read_bytes()), dict)
    put(project, 'input/docs/spec.md', b'# neutral source control\nsource revision one\n')
    inputs = {'input/docs/spec.md': hashlib.sha256((project/'input/docs/spec.md').read_bytes()).hexdigest()}
    recording = {}
    for invocation in gates.program_invocations(row):
        name = invocation['command'].split()[0]
        path = metrics.HERE / (name + '.py')
        assert path.is_file(), name
        recording['launched:programs/' + path.name] = {'__whole__': hashlib.sha256(path.read_bytes()).hexdigest()}
    # Bind both the current source assessor and this qualification reader.
    for name in ('_phase1_producer_identity.py', 'flow109_metric_acceptance.py'):
        recording['launched:programs/' + name] = {'__whole__': hashlib.sha256((metrics.HERE/name).read_bytes()).hexdigest()}
    recording['__engine_env__'] = {name: recorder._engine_marker(name) for name in recorder.ENGINE_ENV}
    if transition:
        first = next(iter(recording))
        recording[first]['__whole__'] = 'a' * 64  # an explicit historical code epoch
    code, _ = step_identity.code_from_recording(recording)
    knobs = identity.normal_knobs({'ic_name': 'control', 'mode': 'docs'})
    input_record = {'files': list(inputs), 'listed_dirs': [], 'flow_written': []}
    stamp = {'code': code, 'recording': recording, 'outputs': identity.docs_snapshot(project),
             'carried': {}, 'input_record': input_record, 'knobs': knobs, 'plugin_version': 'historical-control',
             'inputs': identity.inputs_digest(project, input_record, knobs), 'derivations': []}
    step_identity.write_sidecar(identity.sidecar_dir(project), identity.KIND,
        {'code': code, 'inputs': stamp['inputs']}, {}, stamp)
    fresh = identity.assess(project, metrics.HERE, checkpoint=True)
    assert fresh['state'] == ('REVALIDATE' if transition else 'REUSE'), fresh
    sidecar = identity.sidecar_dir(project) / step_identity.SIDECAR
    checkpoint = copy.deepcopy(source['result']['checkpoint'])
    checkpoint.update(source_assessment=fresh, producer_identity_sha256=hashlib.sha256(sidecar.read_bytes()).hexdigest())
    consumer = copy.deepcopy(original)
    consumer['outputs'] = gates.contracts(project, row)
    # The source ledger includes a genuine advisory refusal. Do not promote it
    # into a new blocking gate while verifying the full declared population.
    assert any(item.get('rc') == 1 for item in consumer['ledger'])
    result = {'runner': 'phase1_one_shot_runner' if direct else 'vibe_ic_one_shot_runner',
              'site': 'doc_extract' if direct else 'phase1_checkpoint_revalidation',
              'canonical_consumer': consumer}
    if direct:
        result['producer_return'] = 0
    else:
        result.update(checkpoint=checkpoint, detail='', observed_canonical_consumer=copy.deepcopy(consumer))
    attempt = versions.begin_step(project, 'D1', inputs)
    saved = versions.finish_step(project, attempt, verdict='PASS', canonical_pass=True, result=result)
    report = layout.report_path(project, 'phase1_one_shot.json')
    put(project, report.relative_to(project).as_posix(), {'phase':1, 'project':str(project), 'verdict':'PASS'})
    feature = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                   if p['name'] == 'Small digital IC without DFT')
    context = flow109.execution_context(flow109.resolve_plan(feature), 'D01', 'D01')
    return saved, context


def qualify(project, context):
    try:
        return metrics._d0102_qualification(project, context, 'D01', {})
    except metrics.MetricRefusal as exc:
        return {'status':'NOT_MEASURED', 'reason':exc.code, 'detail':str(exc)}


def revise_record(project, record, edit):
    relative = record['storage_root'] + '/' + record['folder'] + '/outputs.json'
    body = json.loads((project/relative).read_bytes())
    edit(body)
    put(project, relative, body)


@pytest.mark.parametrize('transition', [False, True], ids=['current-source', 'discharged-source-transition'])
def test_genuine_normal_checkpoint_reaches_actual_consumer(tmp_path, transition):
    record, context = case(tmp_path, transition=transition)
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    result = qualify(tmp_path, context)
    assert result['status'] == 'PASS', result  # BASE fails by COMPONENT_ONLY value.
    assert all(p.read_bytes() == raw for p, raw in before.items())
    assert record['result']['checkpoint']['producer_started'] is False


def test_existing_producer_completion_is_unchanged(tmp_path):
    _, context = case(tmp_path, transition=False, direct=True)
    assert qualify(tmp_path, context)['status'] == 'PASS'


@pytest.mark.parametrize('change', ['runner', 'site', 'forged_flags', 'identity_bytes',
    'source_input', 'output_bytes', 'transition_value', 'source_epoch', 'missing_ledger',
    'missing_advisory', 'failed_required_value', 'failed_consumer', 'pending_review'])
def test_substantive_bad_checkpoint_values_refuse(tmp_path, change):
    record, context = case(tmp_path)
    def edit(body):
        result = body['result'];consumer = result['canonical_consumer']
        if change == 'runner':result['runner'] = 'foreign_runner'
        elif change == 'site':result['site'] = 'different_site'
        elif change == 'forged_flags':result.pop('observed_canonical_consumer')
        elif change == 'transition_value':result['checkpoint']['source_assessment']['new']['code'] = 'b'*64
        elif change == 'source_epoch':result['checkpoint']['source_assessment']['old']['code'] = 'c'*64
        elif change == 'missing_ledger':consumer['ledger'] = []
        elif change == 'missing_advisory':
            count = len(consumer['ledger'])
            consumer['ledger'] = [i for i in consumer['ledger'] if i['cmd'] != 'constants_validation phase1/generated_docs']
            assert len(consumer['ledger']) == count - 1
        elif change == 'failed_required_value':
            entry = next(i for i in consumer['ledger'] if i['cmd'] == consumer['required_commands'][0])
            entry.update(rc=1, exit_code=1, verdict='FAIL')
        elif change == 'failed_consumer':consumer['status'] = 'FAIL'
        if change not in ('forged_flags','runner','site','transition_value','source_epoch'):
            result['observed_canonical_consumer'] = copy.deepcopy(consumer)
    if change in ('runner','site','forged_flags','transition_value','source_epoch','missing_ledger',
                  'missing_advisory','failed_required_value','failed_consumer'):
        revise_record(tmp_path, record, edit)
    elif change == 'identity_bytes':
        p = identity.sidecar_dir(tmp_path)/step_identity.SIDECAR
        body = json.loads(p.read_bytes());body['phase1']['knobs']['ic_name'] = 'different-control';put(tmp_path,p.relative_to(tmp_path).as_posix(),body)
    elif change == 'source_input':put(tmp_path,'input/docs/spec.md',b'# source revision two\n')
    elif change == 'output_bytes':
        target = next((tmp_path/'phase1/generated_docs').glob('L*.json'))
        body=json.loads(target.read_bytes());body['changed_value']=31;put(tmp_path,target.relative_to(tmp_path).as_posix(),body)
    elif change == 'pending_review':
        report=layout.report_path(tmp_path,'phase1_one_shot.json');put(tmp_path,report.relative_to(tmp_path).as_posix(),
            {'phase':1,'project':str(tmp_path),'verdict':'NOT_MEASURED','ai_judgements':{'D1':'pending existing independent review'}})
    result = qualify(tmp_path, context)
    assert result['status'] == 'NOT_MEASURED', result
    assert result.get('reason'), result


def test_activated_conditional_gate_cannot_reuse_an_unexecuted_ledger(tmp_path):
    _, context = case(tmp_path)
    put(tmp_path,'phase1/agent_docs/L1_DATASHEET.json',{'value':'new independent track'})
    assert qualify(tmp_path,context)['status'] == 'NOT_MEASURED'
