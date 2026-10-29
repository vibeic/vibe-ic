"""Normal current-source publication/reuse, software-only upstream isolation."""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import os
import shutil
import sys
import time

import pytest
import design_one_shot_runner as runner
import serial_parallel_mul_synth as serial
import ai_signed_judgement as judgement

CLASS = 'digital_arithmetic_primitive'


def end_run():
    runner._finalize_rtl_provenance()
    runner._RTL_SESSION_OWNED = False
    runner._RTL_SESSION_PROJECT = None


def publish(project):
    result = runner.step_rtl_gen(project, CLASS)
    assert result.status == 'PASS', result
    runner._write_phase2_report(runner._pl.report_path(project, 'phase2_one_shot.json'),
        {'project': str(project), 'steps': [asdict(result)], 'verdict': result.status}, project)
    end_run()
    return result


@pytest.fixture
def current(tmp_path, monkeypatch):
    project = tmp_path/'current_unit'
    docs = project/'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs/'L2_FRS.json').write_text(json.dumps({'content':
        'serial-parallel multiplier; synchronous active-high reset'}))
    (docs/'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'top_module':'current_unit',
        'top_ports':[{'name':'clk','direction':'input','width':1},
        {'name':'rst','direction':'input','width':1},
        {'name':'parallel_i','direction':'input','width':8},
        {'name':'serial_i','direction':'input','width':1},
        {'name':'serial_o','direction':'output','width':1}]}))
    # Isolate only the named upstream D01 admission; no receipt/signature is
    # manufactured, and no fixture result grants native or qualification credit.
    def isolated_d01(root):
        return {'current':True, 'detail':'explicit software-only D01 precondition',
                'evidence_sha256':judgement.evidence_sha256(root, 'D1')}
    monkeypatch.setattr(runner, '_serial_d01_state', isolated_d01, raising=False)
    try:
        publish(project)
        yield project
    finally:
        end_run()


def metadata(project):
    return {str(p.relative_to(project)):(p.stat().st_ino,p.stat().st_size,p.stat().st_mtime_ns)
            for p in project.rglob('*') if p.is_file()}


def test_normal_publication_then_actual_no_write_entry(current, monkeypatch):
    archive = current/'steps/retained/history/untouched.bin'
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b'x'*2**20)
    before = metadata(current)
    reads = []
    for name in ('_phase1_fd_digest','_phase1_read_fd'):
        original = getattr(runner,name)
        def observe(fd, original=original):
            reads.append(os.readlink('/proc/self/fd/'+str(fd)))
            return original(fd)
        monkeypatch.setattr(runner,name,observe)
    def forbidden(*args,**kwargs):
        raise AssertionError('eligible path reached a writer/full transaction')
    for name in ('_phase1_snapshot_to_stage','_phase1_stamp_held_session',
                 '_claim_rtl_session','declaration_before_step4'):
        monkeypatch.setattr(runner,name,forbidden)
    monkeypatch.setattr(serial,'main',forbidden)
    monkeypatch.setattr(runner._pr,'run',forbidden)
    result = runner.step_rtl_gen(current,CLASS)
    assert result.status == 'PASS', result
    assert result.extras.get('current_source_read_only') is True
    assert result.extras['spec'] == serial.inspect_current_outputs(current,CLASS)['spec']
    assert metadata(current) == before
    assert not any('/steps/' in p for p in reads)
    assert not runner._RTL_SESSION_OWNED and runner._RTL_SESSION_BINDING is None


@pytest.mark.parametrize('change',['consumed_L9','missing_declaration','declaration_conflict',
    'dispatcher','header','config','missing_proof','forged_proof','ambiguous_report',
    'force','invalid_D01','content_race','directory_race','symlink'])
def test_changed_source_uses_original_transaction(current,monkeypatch,change):
    report = runner._pl.report_path(current,'phase2_one_shot.json')
    if change == 'consumed_L9':
        path=current/'phase1/generated_docs/L9_INTEGRATION_SPEC.json'
        doc=json.loads(path.read_text()); doc['top_ports'][2]['name']='operand_i'
        path.write_text(json.dumps(doc))
        spec,_=serial.extract_serial_parallel_mul_spec(current,CLASS)
        assert serial.emit_rtl(spec).encode() != (current/'phase2/stage1/rtl/current_unit.v').read_bytes()
    elif change == 'missing_declaration':
        (current/'plugin_output/declaration.json').unlink()
    elif change == 'declaration_conflict':
        path=current/'plugin_output/declaration.json'
        doc=json.loads(path.read_text()); doc['latency_cycles']=999
        path.write_text(json.dumps(doc))
    elif change == 'dispatcher':
        path=current/'input/rtl_spec.json'; path.parent.mkdir()
        path.write_text('{}')
    elif change == 'header':
        (current/'phase2/stage1/rtl/extra.vh').write_text('`define EXTRA 1\n')
    elif change == 'config':
        path=current/'phase3/librelane_switch.json'; path.parent.mkdir()
        path.write_text('{"changed":true}')
    elif change in ('missing_proof','forged_proof'):
        doc=json.loads(report.read_text()); extra=doc['steps'][0]['extras']
        if change=='missing_proof': extra.pop('current_source_proof',None)
        else: extra['current_source_proof']['code']='invalid'
        report.write_text(json.dumps(doc))
    elif change == 'ambiguous_report':
        report.write_text(report.read_text().replace('"project":','"project": "conflicting", "project":',1))
    elif change == 'invalid_D01':
        def refuse(root): raise ValueError('real upstream admission refused')
        monkeypatch.setattr(runner,'_serial_d01_state',refuse,raising=False)
    elif change == 'symlink':
        path=current/'phase1/generated_docs/L2_FRS.json'
        path.rename(path.with_suffix('.saved')); path.symlink_to(path.with_suffix('.saved').name)
    elif change in ('content_race','directory_race'):
        original=serial.inspect_current_outputs
        changed=[]
        def raced(*args,**kwargs):
            result=original(*args,**kwargs)
            if not changed:
                changed.append(True)
                path=current/'phase1/generated_docs'
                if change=='content_race':
                    item=path/'L2_FRS.json'; raw=item.read_bytes()
                    item.write_bytes(raw+b' '); item.write_bytes(raw)
                else:
                    saved=current/'phase1/old-docs'; path.rename(saved); shutil.copytree(saved,path)
            return result
        monkeypatch.setattr(serial,'inspect_current_outputs',raced)
    calls=[]
    original=runner._phase1_snapshot_to_stage
    def snapshot(*args,**kwargs):
        calls.append(True)
        return original(*args,**kwargs)
    monkeypatch.setattr(runner,'_phase1_snapshot_to_stage',snapshot)
    result=runner.step_rtl_gen(current,CLASS,force_regen=change=='force')
    assert calls, result
    assert result.extras.get('current_source_read_only') is not True


def test_changed_actual_producer_bytes_declines(current,tmp_path,monkeypatch):
    copy=tmp_path/'programs'
    shutil.copytree(runner.PROGRAMS_DIR,copy,ignore=shutil.ignore_patterns('__pycache__'))
    path=copy/'serial_parallel_mul_synth.py'
    path.write_text(path.read_text()+'\n# actual changed producer input\n')
    monkeypatch.setattr(runner,'PROGRAMS_DIR',copy)
    calls=[]
    original=runner._phase1_snapshot_to_stage
    def snapshot(*a,**k): calls.append(True); return original(*a,**k)
    monkeypatch.setattr(runner,'_phase1_snapshot_to_stage',snapshot)
    result=runner.step_rtl_gen(current,CLASS)
    assert calls and result.extras.get('current_source_read_only') is not True


def test_root_inode_race_refuses_without_write(current,monkeypatch):
    original=serial.inspect_current_outputs
    def raced(*args,**kwargs):
        result=original(*args,**kwargs)
        moved=current.with_name('held-original'); current.rename(moved); current.mkdir()
        return result
    monkeypatch.setattr(serial,'inspect_current_outputs',raced)
    result=runner.step_rtl_gen(current,CLASS)
    assert result.status == 'NOT_MEASURED'
    assert 'PROJECT_BOUNDARY_REPLACED' in str(result.extras)
    assert not list(current.iterdir())


def test_real_missing_D01_cannot_publish_or_reuse(tmp_path):
    with pytest.raises(ValueError,match='D01'):
        runner._serial_d01_state(tmp_path)


@pytest.mark.parametrize('owner', [{'project':'foreign namespace'}, [], None])
def test_real_D01_owner_mismatch_is_not_current(tmp_path,owner):
    report=runner._pl.report_path(tmp_path,'phase1_one_shot.json')
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps(owner))
    receipt=tmp_path/'reports/audit/ai_judgements/D1.json'
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{}')
    with pytest.raises(ValueError,match='owner'):
        runner._serial_d01_state(tmp_path)
