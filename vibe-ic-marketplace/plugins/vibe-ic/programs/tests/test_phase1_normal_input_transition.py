"""Bounded real checkpoint/input consumer controls; never a new IC approval.

The exact retained case is copied into a disposable container mount at its
original project namespace. Normal intent, independent judgement, assessment,
checkpoint and qualification readers execute. The unchanged canonical gate
commands reuse their exact retained consumer result rather than rerunning the
previously accepted checks. This substitution is a test boundary, not product
logic or a claim of current whole-case canonical acceptance.
"""
import copy
import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

import _flow_yaml
import _phase1_producer_identity as identity
import ai_signed_judgement as judgement
import execution_backend_gates as gates
import execution_policy
import flow109
import flow109_metric_acceptance as metrics
import step_output_collector as versions
import vibe_ic_one_shot_runner as runner


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def edit(path, change):
    body = json.loads(path.read_bytes())
    change(body)
    path.write_text(json.dumps(body, indent=2) + '\n')


@pytest.fixture
def case(monkeypatch):
    if not os.environ.get('PHASE1_TRANSITION_PROJECT'):
        pytest.skip('exact retained transition inputs must be mounted explicitly')
    project = Path(os.environ['PHASE1_TRANSITION_PROJECT'])
    baseline = Path('/out/baseline')
    assert project.is_mount(), 'only the disposable original-namespace mount may be reset'
    for path in project.iterdir():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    shutil.copytree(baseline, project, dirs_exist_ok=True)
    monkeypatch.setattr(execution_policy, '_ordinary_runtime', None)
    monkeypatch.setenv('VIBEIC_PHASE1_INPUT_BASIS', '/basis/TRANSPORT_MANIFEST.json')
    return project


def assess(project, **kw):
    return identity.assess(project, metrics.HERE, checkpoint=True, **kw)


def complete(project, monkeypatch):
    retained = json.loads(Path('/out/FROZEN_CANONICAL_CONSUMER.json').read_bytes())
    # Reuse accepted, unaffected canonical commands. The changed normal
    # input/intent consumers above and the actual completion writer execute.
    monkeypatch.setattr(gates, 'evaluate', lambda *_: copy.deepcopy(retained))
    knobs = json.loads((project / 'phase1/step_identity.json').read_bytes())['phase1']['knobs']
    result = runner._revalidate_phase1_checkpoint(project, knobs)
    features = next(p['features'] for p in flow109.load_registry()['reference_profiles']
                    if p['name'] == 'Small digital IC without DFT')
    context = flow109.execution_context(flow109.resolve_plan(features), 'D01', 'D01')
    return result, context


def qualify(project, context):
    try:
        return metrics._d0102_qualification(project, context, 'D01', {})
    except metrics.MetricRefusal as exc:
        return {'status': 'NOT_MEASURED', 'reason': exc.code, 'detail': str(exc)}


def test_exact_verified_input_transition_preserves_reviewed_outputs(case):
    sidecar = case / 'phase1/step_identity.json'
    before = sidecar.read_bytes(), identity.docs_snapshot(case)
    result = assess(case)
    assert result['state'] == 'REVALIDATE', result  # BASE observes REGENERATE.
    assert result['old']['inputs'] == '74232a78429df4967d458c412337a1aa4da0fdc471dd90c365234ebd4686a5e4'
    assert result['new']['inputs'] == 'e5e5455a57afb37db2006fd5343a3c9ce461d0f4784f3ce4c05c60b9e38705a8'
    assert result['new']['consumed_inputs']['input/feature-decisions.json'] == sha(case/'input/feature-decisions.json')
    assert result['new']['intent']['report_sha256'] == sha(case/'reports/orchestrator/phase1_one_shot.json')
    assert (sidecar.read_bytes(), identity.docs_snapshot(case)) == before


def test_actual_front_door_keeps_checkpoint_without_extraction(case):
    knobs = json.loads((case/'phase1/step_identity.json').read_bytes())['phase1']['knobs']
    assert runner._phase1_decision(case, False, knobs, checkpoint=True) == (False, '')


@pytest.mark.parametrize('damage', ['source_document', 'design_feature', 'profile',
    'decision', 'publication', 'missing_publication', 'publisher_source', 'declaration_source',
    'new_document_input', 'referenced_authority', 'basis_identity', 'current_basis_identity'])
def test_real_semantic_or_unproved_input_changes_still_refuse(case, damage, monkeypatch, tmp_path):
    if damage == 'source_document':
        p=case/'input/docs/L1_product_metadata.md';p.write_bytes(p.read_bytes()+b'\nChanged normative source.\n')
    elif damage == 'design_feature':
        edit(case/'input/flow109-manifest.json', lambda b:b['features'].update(requires_scan=True))
    elif damage == 'profile':
        edit(case/'input/flow109-manifest.json', lambda b:b['step_profiles'].update(D01='different'))
    elif damage == 'decision':
        edit(case/'input/feature-decisions.json', lambda b:b['dft'].update(reason='different author decision'))
    elif damage == 'publication':
        p=case/'plugin_output/declaration.json';p.write_bytes(p.read_bytes()+b'\n')
    elif damage == 'missing_publication':
        (case/'reports/orchestrator/phase1_one_shot.json').unlink()
    elif damage == 'publisher_source':
        edit(case/'reports/orchestrator/phase1_one_shot.json', lambda b:b['dft_intent_output'].update(producer_source_sha256='0'*64))
    elif damage == 'declaration_source':
        p=case/'provenance.jsonl';lines=p.read_text().splitlines()
        for i in range(len(lines)-1,-1,-1):
            b=json.loads(lines[i])
            if b.get('tool')=='spec_declaration_emit' and b.get('exit_code')==0:
                b['source_sha256']='sha256:'+'0'*64;lines[i]=json.dumps(b);break
        p.write_text('\n'.join(lines)+'\n')
    elif damage == 'new_document_input':
        (case/'input/phase1_prompt.md').write_text('A new normative design request.\n')
    elif damage == 'referenced_authority':
        p=case/'input/flow109/current-design-choices-review.json';p.write_bytes(p.read_bytes()+b'\n')
    else:
        copied=tmp_path/'basis';shutil.copytree('/basis',copied)
        field='current_aggregate' if damage=='current_basis_identity' else 'old_aggregate'
        edit(copied/'DIGEST_PARTS_PROOF.json',lambda b:b.update({field:'0'*64}))
        monkeypatch.setenv('VIBEIC_PHASE1_INPUT_BASIS',str(copied/'TRANSPORT_MANIFEST.json'))
    result=assess(case)
    assert result['state'] in ('REGENERATE','REFUSE'),result


def test_missing_input_basis_cannot_nominate_checkpoint(case,monkeypatch):
    monkeypatch.delenv('VIBEIC_PHASE1_INPUT_BASIS')
    assert assess(case)['state']=='REGENERATE'


def test_normal_checkpoint_binds_new_inputs_and_consumes_original_review(case,monkeypatch):
    before=(case/'phase1/step_identity.json').read_bytes()
    assert judgement.check(case,'D1')[0]
    result,context=complete(case,monkeypatch)
    assert result['verdict']=='PASS',result  # BASE observes NOT_MEASURED.
    record=versions.latest_pass(case,'D1')
    assert record['inputs']['input/feature-decisions.json']==sha(case/'input/feature-decisions.json')
    assert record['inputs']['reports/audit/ai_judgements/D1.json']==sha(case/'reports/audit/ai_judgements/D1.json')
    monkeypatch.delenv('VIBEIC_PHASE1_INPUT_BASIS')
    knobs=json.loads(before)['phase1']['knobs']
    assert runner._phase1_decision(case,False,knobs,checkpoint=True)==(False,'')
    accepted=qualify(case,context)
    assert accepted['status']=='PASS',accepted
    assert (case/'phase1/step_identity.json').read_bytes()==before
    assert json.loads((case/'reports/orchestrator/phase1_one_shot.json').read_bytes())['verdict']=='NOT_MEASURED'


@pytest.mark.parametrize('damage',['old_inputs','current_inputs','intent_epoch','basis_epoch','omitted_decision','review'])
def test_actual_qualification_refuses_wrong_transition_epochs(case,monkeypatch,damage):
    result,context=complete(case,monkeypatch)
    assert result['verdict']=='PASS',result
    record=versions.latest_pass(case,'D1')
    path=case/record['storage_root']/record['folder']/'outputs.json'
    def mutate(body):
        assessment=body['result']['checkpoint']['source_assessment']
        if damage=='old_inputs':assessment['old']['inputs']='0'*64
        elif damage=='current_inputs':assessment['new']['inputs']='0'*64
        elif damage=='intent_epoch':assessment['new']['intent']['report_sha256']='0'*64
        elif damage=='basis_epoch':assessment['new']['input_basis']['sha256']='0'*64
        elif damage=='omitted_decision':body['inputs'].pop('input/feature-decisions.json')
        else:body['inputs'].pop('reports/audit/ai_judgements/D1.json')
    edit(path,mutate)
    assert qualify(case,context)['status']=='NOT_MEASURED'


def test_later_admission_metadata_needs_current_epoch_without_doc_regeneration(case,monkeypatch):
    result,context=complete(case,monkeypatch)
    assert result['verdict']=='PASS',result
    edit(case/'input/flow109-manifest.json',lambda b:b.update(qualification_registry='input/flow109/next-qualification.json'))
    current=assess(case)
    assert current['state']=='REVALIDATE',current
    assert current['new']['inputs']!='e5e5455a57afb37db2006fd5343a3c9ce461d0f4784f3ce4c05c60b9e38705a8'
    assert qualify(case,context)['status']=='NOT_MEASURED'


def test_current_review_cannot_launder_measured_extraction_failure(case,monkeypatch):
    edit(case/'reports/orchestrator/phase1_one_shot.json',lambda b:b.update(verdict='FAIL'))
    result,context=complete(case,monkeypatch)
    assert result['verdict']=='PASS',result
    assert qualify(case,context)['status']=='NOT_MEASURED'


@pytest.mark.parametrize('consumer_status',['PASS','FAIL'])
def test_checkpoint_detects_input_race_and_preserves_measured_fail(case,monkeypatch,consumer_status):
    retained=json.loads(Path('/out/FROZEN_CANONICAL_CONSUMER.json').read_bytes())
    before=(case/'phase1/step_identity.json').read_bytes()
    def consume(*_):
        edit(case/'input/feature-decisions.json',lambda b:b['dft'].update(reason='changed during consumer'))
        retained['status']=consumer_status
        retained['step']['status']=consumer_status
        return retained
    monkeypatch.setattr(gates,'evaluate',consume)
    knobs=json.loads(before)['phase1']['knobs']
    result=runner._revalidate_phase1_checkpoint(case,knobs)
    assert result['verdict']==('FAIL' if consumer_status=='FAIL' else 'NOT_MEASURED'),result
    assert (case/'phase1/step_identity.json').read_bytes()==before
