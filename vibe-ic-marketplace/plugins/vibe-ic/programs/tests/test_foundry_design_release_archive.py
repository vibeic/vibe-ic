"""Portable packaging tests; measurement-owner leaves are neutral substitutions.

No simulator, PV tool, IC, or real foundry acceptance is exercised here.
The actual generator, file copies, canonical YAML command and checker execute.
"""
import copy
import hashlib
import json
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import foundry_handoff_pack_gen as gen
import foundry_handoff_package_check as check
from test_foundry_handoff_names_its_owner import _project,_precheck
import _step5_trace_fixture as step5

PROGRAMS=Path(__file__).resolve().parents[1]
ROLES=('final_gds','physical_reference_netlist','die_stack','stream_inputs',
       'layer_map','stream_log','tool_provenance','drc_report','lvs_report',
       'antenna_report','density_report','sta_report','sdc','spef')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def neutral(tmp_path,monkeypatch,damage=None):
    project=_project(tmp_path,with_chip_gds=True)
    _precheck(project,verdict='PASS');step5.plant(project)
    layout=project/'phase3/stage4/gds/alpha.gds'
    sources={str(layout.resolve()):{'sha256':digest(layout),'roles':['final_gds']}}
    data=project/'neutral_measurement_owner';data.mkdir()
    for role in ROLES[1:]:
        path=data/(role+'.txt');path.write_text('Neutral retained material: '+role+'\n')
        sources[str(path.resolve())]={'sha256':digest(path),'roles':[role]}
    validations={kind:{'verdict':'PASS','gds_sha256':digest(layout),
                         'rows':{'neutral_count':{'value':0}}}
                 for kind in ('drc','lvs','antenna','density')}
    validations.update({kind:{'verdict':'PASS'} for kind in ('die_stack','stream','sta')})
    if damage=='missing_lvs':
        validations['lvs']={'verdict':'NOT_MEASURED','reason':'current final-GDS LVS not produced'}
        sources={k:v for k,v in sources.items() if 'lvs_report' not in v['roles']}
    elif damage=='old_subject':validations['lvs']['gds_sha256']='0'*64
    elif damage=='measured_fail':validations['lvs']['verdict']='FAIL';validations['lvs']['rows']['neutral_count']['value']=2
    source={'files':sources,'validation':validations,'external_dependencies':{}}
    # Only measurement/readset discovery is substituted. Old code ignores this
    # neutral leaf, so baseline fails on missing copied values / wrong gate rc,
    # never because a newly added API or flag is unavailable.
    monkeypatch.setattr(check,'design_release_sources',lambda *a,**kw:copy.deepcopy(source),raising=False)
    return project,source


def canonical_gate(project):
    import _flow_yaml
    row=next(row for row in _flow_yaml.load()['steps'] if str(row['id'])=='38')
    command=row['gate']['all_of'][0]['program_exit_zero']
    argv=shlex.split(command);argv[0]=str(PROGRAMS/(argv[0]+'.py'))
    result=subprocess.run([sys.executable,*argv],cwd=project,text=True,capture_output=True)
    report=json.loads((project/'reports/phase3/foundry_handoff_check.json').read_text())
    return result,report,command


def test_normal_producer_copies_real_release_values_and_validates_portably(tmp_path,monkeypatch):
    project,source=neutral(tmp_path,monkeypatch)
    assert gen.main([str(project)])==0
    package=project/'phase3/stage4/foundry_handoff'
    path=package/'release_manifest.json'
    manifest=json.loads(path.read_text()) if path.is_file() else {}
    observed={role:sorted(e['sha256'] for e in manifest.get('files',[]) if role in e['roles']) for role in ROLES}
    expected={role:sorted(e['sha256'] for e in source['files'].values() if role in e['roles']) for role in ROLES}
    assert observed==expected,{'observed':observed,'expected':expected}
    for entry in manifest['files']:
        assert digest(package/entry['path'])==entry['sha256']
    assert {p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()} == {
        e['path'] for e in manifest['files']} | {'release_manifest.json','SHA256SUMS'}
    result,report,command=canonical_gate(project)
    assert result.returncode==0 and report['verdict']=='PASS',(result.stdout,result.stderr,report)
    assert report['scope']=='DESIGN_RELEASE' and report['technical_release_complete'] is True
    # Manufacturing-service disclosures remain honest and do not become seven
    # universal design-release requirements.
    assert report['pending_foundry_fields']
    assert manifest['provider_submission']['accepted'] is False
    archive=tmp_path/'release.tar'
    with tarfile.open(archive,'w') as tar:tar.add(package,arcname='release')
    held=tmp_path/'original-held';project.rename(held)
    moved=tmp_path/'relocated';moved.mkdir()
    with tarfile.open(archive) as tar:tar.extractall(moved)
    relocated=moved/'release'
    out=tmp_path/'portable-check.json'
    result=subprocess.run([sys.executable,str(PROGRAMS/'foundry_handoff_package_check.py'),str(relocated),
                           '--package-dir',str(relocated),'--json',str(out)],capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    assert json.loads(out.read_text())['verdict']=='PASS'
    print('PORTABLE_VALUES',json.dumps({'roles':observed,'gate':command,'relocated_rc':result.returncode}))


@pytest.mark.parametrize('damage',['missing_lvs','old_subject','measured_fail'])
def test_normal_step38_gate_refuses_missing_stale_or_failed_final_gds_lvs(tmp_path,monkeypatch,damage):
    project,_source=neutral(tmp_path,monkeypatch,damage)
    assert gen.main([str(project)])==0  # Keep useful partial packaging work.
    result,report,command=canonical_gate(project)
    observed={'rc':result.returncode,'verdict':report['verdict']}
    assert observed=={'rc':1,'verdict':'FAIL'},observed
    assert any(f['rule']=='DESIGN_RELEASE_INCOMPLETE' for f in report['findings']),report
    print('NORMAL_RELEASE_REFUSAL',damage,json.dumps({'actual':observed,'command':command,'findings':report['findings']}))


def test_release_row_refuses_incomplete_archive_instead_of_accepting_skeleton(tmp_path, monkeypatch):
    from types import SimpleNamespace
    project, _ = neutral(tmp_path, monkeypatch, 'missing_lvs')
    layout = project / 'phase3/stage4/gds/alpha.gds'
    (project / 'input').mkdir(exist_ok=True)
    (project / gen.RELEASE_APPROVAL_REL).write_text(json.dumps({
        'approved': True, 'approved_by': 'Source fixture owner',
        'gds': str(layout.relative_to(project)), 'gds_sha256': digest(layout)}))
    # The document producers have their own focused tests; the real package
    # producer and checker must decide this intentionally incomplete archive.
    monkeypatch.setattr(gen, 'subprocess', SimpleNamespace(run=
        lambda command, **kw: subprocess.CompletedProcess(command, 0)))
    result = gen.execute(project, {'context_sha256': 'source-test'})
    assert result['default_row_status'] == 'FAIL' and result['exit_code'] == 1, result


def test_new_timestamp_destination_preserves_source_and_rejects_corrupt_members(tmp_path,monkeypatch):
    project,_source=neutral(tmp_path,monkeypatch)
    before={str(p.relative_to(project)):digest(p) for p in project.rglob('*') if p.is_file()}
    destination=tmp_path/'release-version-one'
    assert gen.main([str(project),'--out-dir',str(destination)])==0
    after={str(p.relative_to(project)):digest(p) for p in project.rglob('*') if p.is_file()}
    assert before==after
    assert not (project/'phase3/stage4/foundry_handoff').exists()
    doc,bad=check.check_design_release(destination);assert not bad,bad
    member=next(e for e in doc['files'] if 'lvs_report' in e['roles'])
    (destination/member['path']).write_text('corrupted current report\n')
    _doc,bad=check.check_design_release(destination)
    assert any('changed archive member' in problem for problem in bad),bad
    assert gen.main([str(project),'--out-dir',str(destination)])==1
    assert before=={str(p.relative_to(project)):digest(p) for p in project.rglob('*') if p.is_file()}


# Reproduce the two independent review findings with the real existing STA
# evaluator and real package entries. Native-output construction/admission and
# unrelated archive readsets remain neutral; no EDA tool is dispatched.
_REAL_RELEASE_SOURCES = check.design_release_sources


@pytest.mark.parametrize('scenario,expected',[
    ('clean','PASS'),('negative','FAIL'),('missing_metric','NOT_MEASURED'),
    ('missing_report','NOT_MEASURED')])
def test_archive_sta_uses_the_existing_signoff_consumer(tmp_path,monkeypatch,scenario,expected):
    from test_f15_step23_gates_read_the_tool_arm import tool_project,rebind,run_gate,STA,CORNERS
    setup={CORNERS[0]:-0.25} if scenario=='negative' else None
    timed=tool_project(tmp_path/'timed',setup=setup)
    if scenario=='missing_metric':
        # A current, bound native report that contains no measured slack.
        for corner in CORNERS:
            (timed/STA/corner/'vibeic_signoff.rpt').write_text(
                'OpenSTA report_checks\nSTA_BASIS: POST_ROUTE_SPEF\n'
                'Startpoint: launch\nEndpoint: capture\nPath Type: max\n'
                'Setup and hold values unavailable\n')
        rebind(timed)
    elif scenario=='missing_report':
        (timed/STA/CORNERS[0]/'vibeic_signoff.rpt').unlink()
    sta_rc,sta_doc=run_gate('sta_report_check',timed,tmp_path)
    assert sta_rc==(0 if scenario=='clean' else 1),sta_doc
    project,source=neutral(tmp_path/'pack',monkeypatch)
    measured=_REAL_RELEASE_SOURCES(timed,project/'phase3/stage4/gds/alpha.gds')
    source['validation']['sta']=measured['validation']['sta']
    for path,entry in measured['files'].items():
        if any(role in ('sta_report','sdc','spef','timed_reference_netlist','tool_provenance') for role in entry['roles']):
            source['files'][path]=entry
    monkeypatch.setattr(check,'design_release_sources',lambda *a,**kw:copy.deepcopy(source))
    assert gen.main([str(project)])==0
    package=project/'phase3/stage4/foundry_handoff'
    manifest=json.loads((package/'release_manifest.json').read_text())
    actual=manifest['validation']['sta']['verdict']
    observation={'scenario':scenario,'normal_sta_rc':sta_rc,'normal_sta':sta_doc,
                 'archive_sta':manifest['validation']['sta'],'expected':expected}
    (tmp_path/'STA_OBSERVATION.json').write_text(json.dumps(observation,indent=2)+'\n')
    assert actual==expected,{'observed':actual,'expected':expected,'normal_sta_rc':sta_rc}
    result,report,_command=canonical_gate(project)
    assert (result.returncode,report['verdict'])==((0,'PASS') if expected=='PASS' else (1,'FAIL'))
    _doc,bad=check.check_design_release(package)
    assert bool(bad)==(expected!='PASS'),bad
    print('STA_CONSUMER_VALUES',json.dumps(observation))


def _provider_package(tmp_path,monkeypatch,*,old='self',current='PASS',missing=False):
    project,source=neutral(tmp_path,monkeypatch)
    old_path=project/'reports/phase3/shuttle_precheck.json'
    if old=='self':old_path.write_text(json.dumps({'verdict':'NOT_APPLICABLE','verdict_is_the_operators':False}))
    elif old=='unreadable':old_path.write_text('{ original checkpoint unreadable')
    else:_precheck(project,verdict=old)
    layout=project/'phase3/stage4/gds/alpha.gds'
    folder=project/'reports/phase3/current-provider';folder.mkdir(parents=True)
    current_path=folder/'precheck.json'
    current_path.write_text(json.dumps({'provider':'current_mpw','status':current,'layout_sha256':digest(layout)}))
    selected={'provider':'current_mpw','slot':'engineering_full','cob':False,
              'official_revision':'neutral_current_revision','status':current,
              'layout_sha256':digest(layout),'source':{'path':str(current_path),'sha256':digest(current_path)},
              'options':{'target':'engineering only; no purchase'},'files':[]}
    record=project/'reports/phase3/provider_die_assembly.json';record.write_text('{}\n')
    assembly={'gds':layout,'sha256':digest(layout),'report':record,'source_project':project,
              'basis':{} if missing else {'provider_precheck':selected},'scope':'provider_die_assembly'}
    # Only the finishing producer's already validated admission is substituted.
    # The current provider files/hash are real neutral files, read by package
    # mode selection and the canonical checker after the leaf returns.
    monkeypatch.setattr(check,'admitted_provider_release',lambda *a,**kw:copy.deepcopy(assembly))
    source['files'][str(current_path)]={'sha256':digest(current_path),'roles':['provider_precheck']}
    source['provider_submission']={'accepted':False,'technical_precheck_status':current if not missing else 'NOT_MEASURED',
                                   'provider':'current_mpw','retained_report':selected['source']}
    source['validation']['provider_precheck']={'verdict':current if not missing else 'NOT_MEASURED','gds_sha256':digest(layout)}
    monkeypatch.setattr(check,'design_release_sources',lambda *a,**kw:copy.deepcopy(source))
    return project,source,current_path


def _in_process_canonical_gate(project,monkeypatch):
    import _flow_yaml
    row=next(row for row in _flow_yaml.load()['steps'] if str(row['id'])=='38')
    command=row['gate']['all_of'][0]['program_exit_zero']
    with monkeypatch.context() as m:
        m.chdir(project)
        rc=check.main(shlex.split(command)[1:])
    return rc,json.loads((project/'reports/phase3/foundry_handoff_check.json').read_text()),command


@pytest.mark.parametrize('old',['self','FAIL','unreadable'])
def test_selected_current_provider_owns_mode_and_normal_gate(tmp_path,monkeypatch,old):
    project,_source,current=_provider_package(tmp_path,monkeypatch,old=old)
    before=digest(project/'reports/phase3/shuttle_precheck.json')
    assert gen.main([str(project)])==0
    package=project/'phase3/stage4/foundry_handoff'
    mask=json.loads((package/'mask_spec.json').read_text())
    mode=mask['handoff_mode']
    observed=(mode['mode'],mode['operator'],mode['precheck_verdict'])
    expected=('shuttle','current_mpw','PASS')
    (tmp_path/'PROVIDER_OBSERVATION.json').write_text(json.dumps({'old':old,'observed':observed,'expected':expected,'mode':mode},indent=2)+'\n')
    assert observed==expected,{'observed':observed,'expected':expected}
    rc,report,command=_in_process_canonical_gate(project,monkeypatch)
    assert (rc,report['verdict'])==(0,'PASS'),report
    assert digest(project/'reports/phase3/shuttle_precheck.json')==before
    manifest=json.loads((package/'release_manifest.json').read_text())
    assert manifest['provider_submission']['accepted'] is False
    assert manifest['provider_submission']['retained_report']['sha256']==digest(current)
    print('CURRENT_PROVIDER_VALUES',json.dumps({'old':old,'mode':mode,'gate':command,'rc':rc,'verdict':report['verdict']}))


def test_current_provider_refusal_or_missing_evidence_never_uses_old_pass(tmp_path,monkeypatch):
    for state,missing in [('FAIL',False),('NOT_MEASURED',False),('PASS',True)]:
        with monkeypatch.context() as m:
            project,_source,_current=_provider_package(tmp_path/(state+str(missing)),m,old='PASS',current=state,missing=missing)
            assert gen.main([str(project)])==0
            rc,report,command=_in_process_canonical_gate(project,m)
            assert (rc,report['verdict'])==(1,'FAIL'),report
            print('CURRENT_PROVIDER_REFUSAL',json.dumps({'selected':state,'missing_basis':missing,'rc':rc,'verdict':report['verdict'],'gate':command}))


# Combined-reader integration uses the frozen provider/native-LVS owners. Their
# output files are neutral fixtures; no PV, extraction or simulation is run.
def _file_ref(path):
    return {'path':str(path.resolve()),'sha256':digest(path),'bytes':path.stat().st_size}


@pytest.mark.parametrize('case,expected',[
    ('timestamps','PASS'),('native_red','FAIL'),
    ('changed_geometry','NOT_MEASURED'),('missing_count','NOT_MEASURED')])
def test_selected_provider_pv_archive_reads_native_rows_and_geometry(tmp_path,monkeypatch,case,expected):
    import die_finishing_gen as owner
    import wafer_space_precheck as pv_owner
    from test_gds_canonical_digest import _rec,_RUN_A
    from _gds_geometry import _iter_records
    import struct
    project,source=neutral(tmp_path/'pack',monkeypatch)
    layout=project/'phase3/stage4/gds/alpha.gds'
    physical=tmp_path/'selected';physical.mkdir()
    subject=physical/'subject.gds'
    records=[]
    for rt,dt,payload in _iter_records(layout.read_bytes()):
        if rt in (0x01,0x05):payload=struct.pack('>12h',*_RUN_A)
        if rt==0x10 and case=='changed_geometry':
            coords=list(struct.unpack('>'+str(len(payload)//4)+'i',payload))
            coords[0]+=100
            payload=struct.pack('>'+str(len(coords))+'i',*coords)
        records.append(_rec(rt,dt,payload))
    subject.write_bytes(b''.join(records))
    def write(path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value)+'\n');return _file_ref(path)
    ids=['ReadLayout','Hierarchy','Size','GenerateID','Render','KLayout.Density',
         'Checker.KLayoutDensity','ZeroArea','CheckerZero','KLayout.Antenna',
         'Checker.KLayoutAntenna','Magic.DRC','Checker.MagicDRC','KLayout.DRC',
         'Checker.KLayoutDRC','WriteLayout']
    count=3 if case=='native_red' else None if case=='missing_count' else 0
    metrics={'klayout__density_error__count':0,'klayout__antenna_error__count':0,
             'klayout__drc_error__count':count,'magic__drc_error__count':7}
    steps=[]
    for index,sid in enumerate(ids):
        folder=physical/f'{index+1:02d}-stage'
        write(folder/'state_in.json',{'gds':str(subject)})
        state=write(folder/'state_out.json',{'gds':str(subject),'metrics':metrics})
        write(folder/'config.json',{'meta':{'step':sid},'ERROR_ON_MAGIC_DRC':False})
        (folder/'COMMANDS').write_text('neutral source-control native output; no tool dispatched\n')
        for kind in ('density','antenna','drc'):
            write(folder/'reports'/(kind+'.klayout.json'),{'total':count if kind=='drc' else 0})
        steps.append({'folder':str(folder),'state_out':state})
    official=write(physical/'official.json',{'expected_steps':ids,'steps':steps})
    record=physical/'reports/phase3/provider_die_assembly.json'
    write(record,{'basis':{'files':{'official_precheck':official}},'output':_file_ref(layout)})
    assembly={'gds':layout,'sha256':digest(layout),'report':record,'source_project':project,
              'basis':{},'scope':'provider_die_assembly'}
    # Only admission is neutral. The real selected PV reader re-reads the GDS
    # record streams, all native states and integer raw counts.
    monkeypatch.setattr(owner,'read_admitted_release',lambda *a,**kw:copy.deepcopy(assembly))
    direct=pv_owner.read_signoff_evidence(project,record)
    measured=_REAL_RELEASE_SOURCES(project,layout,assembly)
    actual={kind:measured['validation'][kind]['verdict'] for kind in ('drc','antenna','density')}
    wanted={kind:direct['rows'][kind]['verdict'] for kind in actual}
    observation={'case':case,'observed':actual,'expected':wanted,'reader':direct,
                 'archive':{kind:measured['validation'][kind] for kind in actual}}
    (tmp_path/'PV_MAPPING_OBSERVATION.json').write_text(json.dumps(observation,indent=2)+'\n')
    assert actual==wanted,{'observed':actual,'expected':wanted}
    assert actual['drc']==expected
    for kind in actual:
        if actual[kind]!='NOT_MEASURED':
            row=measured['validation'][kind]['rows'][kind]
            assert row==direct['rows'][kind]
            assert measured['validation'][kind]['gds_sha256']==digest(layout)
    if case=='timestamps':
        assert direct['rows']['drc']['subject_sha256']!=digest(layout)
        assert direct['rows']['drc']['equivalence']['equivalent'] is True
        assert direct['disclosures'][0]['value']==7
    # The normal producer/checker retain bad PV as incomplete, while a good
    # selected-engine result can be archived without borrowing the old flow.
    source['files'][str(layout.resolve())]['sha256']=digest(layout)
    for kind in actual:source['validation'][kind]=measured['validation'][kind]
    source['files'].update(measured['files'])
    monkeypatch.setattr(check,'design_release_sources',lambda *a,**kw:copy.deepcopy(source))
    assert gen.main([str(project)])==0
    rc,report,command=_in_process_canonical_gate(project,monkeypatch)
    assert (rc,report['verdict'])==((0,'PASS') if expected=='PASS' else (1,'FAIL')),report
    print('SELECTED_PV_MAPPING',json.dumps({'case':case,'rows':actual,'normal_rc':rc,'gate':command}))


def test_native_lvs_bundle_relative_includes_survive_real_relocation(tmp_path,monkeypatch):
    import pya
    import klayout_pdk_lvs as native_owner
    project,source=neutral(tmp_path/'pack',monkeypatch)
    layout=project/'phase3/stage4/gds/alpha.gds'
    work=tmp_path/'native-job';work.mkdir()
    def material(name,text):
        path=work/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(text);return _file_ref(path)
    cells=material('cells.spice','* neutral unit\n.SUBCKT unit a b\nR1 a b 1000\n.ENDS unit\n')
    spice=material('source.spice','* neutral reference\n.include "cells.spice"\n.SUBCKT alpha a b\nX1 a b unit\n.ENDS alpha\n')
    original_driver=material('official-deck-driver.lvs','threads(1)\n# %include pdk_runset/neutral.lvs\n')
    driver=material('../recompare-job/recompare.py',
                    "from pathlib import Path\nimport sys\nsys.path.insert(0,str(Path(__file__).parent/'tools'))\nimport producer\n")
    deck=material('pdk_runset/neutral.lvs','# %include rules/connect.lvs\n')
    sub=material('pdk_runset/rules/connect.lvs','# neutral finite rule source\n')
    library=material('cell_library_0.spice',Path(cells['path']).read_text())
    raw=material('cells.original.spice',Path(cells['path']).read_text())
    tool=material('pdk_runset/tools/translate.py','# neutral translator source\n')
    translated=material('library-translation.log','neutral source-control conversion log\n')
    native=material('actual.lvsdb','neutral native database fixture, not an actual measurement\n')
    native.update(compare_performed=True,circuits=[{'layout':'alpha','reference':'alpha',
                  'status':'Match','layout_pins':2,'reference_pins':2}],top='alpha')
    reference=material('reference.v','module alpha(input a,output b); assign b=a; endmodule\n')
    log=material('native.log','neutral recorded native outcome\n')
    inputs=material('inputs.json','[]\n')
    extraction={key:material('previous/'+name,'neutral retained extraction source\n') for key,name in
                [('report','lvs.json'),('native_result','actual.lvsdb'),('inputs_manifest','inputs.json'),('log','native.log')]}
    extraction['driver_source']=original_driver
    prior_layout=work/'prior.gds';prior_layout.write_bytes(layout.read_bytes())
    extraction['layout_source']=dict(_file_ref(prior_layout),kind='gds')
    producer=material('../recompare-job/tools/producer.py','# neutral retained source\n')
    record={'schema':'vibeic.native_gds_lvs/1','status':'PASS','tool':'klayout',
            'compare_performed':True,'layout_source':dict(_file_ref(layout),kind='gds'),
            'reference_source':reference,'deck':dict(deck,original_source={'path':'/unmounted-pdk/neutral.lvs','sha256':deck['sha256']}),
            'driver_source':driver,'native_result':native,'source_netlist':spice,
            'cell_library_bundle':cells,'cell_libraries':[library],
            'runset_sources':[deck,sub,tool], 'library_translation':{'tool':tool,'input':raw,'output':cells,'log':translated},
            'extraction_basis':extraction,'producer_sources':[producer],
            'log':log,'inputs_manifest':inputs,'execution':{'rc':0,'inputs_unchanged':True}}
    record['geometry_equivalence']=native_owner._native_geometry_equivalence(
        project,extraction['layout_source'],record['layout_source'])
    report=project/'reports/phase3/lvs_verdict.json';report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(record)+'\n')
    measured=_REAL_RELEASE_SOURCES(project,layout)
    assert measured['validation']['lvs']['verdict']=='PASS',measured['validation']['lvs']
    # A current record cannot reuse the proof after its actual geometry changes.
    prior_bytes,report_bytes=prior_layout.read_bytes(),report.read_bytes()
    from test_foundry_handoff_pack_gen import _physical_gds
    prior_layout.write_bytes(_physical_gds(('different_root',)))
    damaged=copy.deepcopy(record)
    damaged['extraction_basis']['layout_source']=dict(_file_ref(prior_layout),kind='gds')
    report.write_text(json.dumps(damaged)+'\n')
    try:
        refused=_REAL_RELEASE_SOURCES(project,layout)['validation']['lvs']
        assert refused['verdict']=='NOT_MEASURED'
        assert 'NATIVE_LVS_LAYOUT_NOT_EQUIVALENT' in refused['reason']
    finally:
        prior_layout.write_bytes(prior_bytes);report.write_bytes(report_bytes)
    missing_path=Path(raw['path']);held_path=missing_path.with_suffix('.held')
    missing_path.rename(held_path)
    try:missing_translation=_REAL_RELEASE_SOURCES(project,layout)['validation']['lvs']['verdict']
    finally:held_path.rename(missing_path)
    source['validation']['lvs']=measured['validation']['lvs']
    source['files'].update(measured['files'])
    source['external_dependencies']=measured['external_dependencies']
    monkeypatch.setattr(check,'design_release_sources',lambda *a,**kw:copy.deepcopy(source))
    destination=tmp_path/'release-version'
    assert gen.main([str(project),'--out-dir',str(destination)])==0
    manifest=json.loads((destination/'release_manifest.json').read_text())
    original={e['source']:e for e in manifest['files']}
    # Move both source trees out of reach. An actual SPICE reader must follow
    # the original relative include in the relocated archive, not just hashes.
    project.rename(tmp_path/'held-project');work.rename(tmp_path/'held-native-job')
    moved=tmp_path/'relocated-release';destination.rename(moved)
    archived=moved/original[spice['path']]['path']
    netlist=pya.Netlist();error=None
    try:netlist.read(str(archived),pya.NetlistSpiceReader())
    except RuntimeError as exc:error=str(exc)
    actual={'include_loaded':error is None and netlist.circuit_by_name('unit') is not None,
            'source_bytes_same':digest(archived)==spice['sha256']}
    observation={'observed':actual,'expected':{'include_loaded':True,'source_bytes_same':True},
                 'parse_error':error,'members':manifest['files']}
    (tmp_path/'BUNDLE_MAPPING_OBSERVATION.json').write_text(json.dumps(observation,indent=2)+'\n')
    assert actual==observation['expected'],{'observed':actual,'expected':observation['expected'],'parse_error':error}
    required=[cells,spice,driver,deck,sub,library,raw,tool,translated,*extraction.values(),producer]
    import os
    bundle_root=Path(os.path.commonpath([str(Path(entry['source']).parent) for entry in manifest['files']
                                      if '/archive/native_lvs/' in '/'+entry['path']]))
    archive_root=next(parent for parent in archived.parents if parent.name==digest(tmp_path/'held-project/reports/phase3/lvs_verdict.json'))
    for entry in required:
        target=moved/original[entry['path']]['path']
        assert target==archive_root/Path(entry['path']).relative_to(bundle_root)
        assert digest(target)==entry['sha256']
    assert missing_translation=='NOT_MEASURED'
    assert (moved/original[driver['path']]['path']).parent/'tools/producer.py'==moved/original[producer['path']]['path']
    # Resolve the driver's actual two-level %include closure as written.
    import re
    def included(path):
        names=re.findall(r'^#\s*%include\s+(\S+)\s*$',path.read_text(),re.M)
        return [path.parent/name for name in names]
    root=moved/original[original_driver['path']]['path'];first=included(root)
    assert first==[moved/original[deck['path']]['path']]
    assert included(first[0])==[moved/original[sub['path']]['path']]
    doc,bad=check.check_design_release(moved);assert not bad,bad
    assert '/unmounted-pdk/neutral.lvs' in doc['external_dependencies']
    (moved/original[cells['path']]['path']).write_text('damaged cells\n')
    _doc,bad=check.check_design_release(moved)
    assert any('changed archive member' in item for item in bad),bad
    print('NATIVE_BUNDLE_RELOCATION',json.dumps(actual))


@pytest.mark.parametrize('case,expected',[
    ('serialization','PASS'),('shape','NOT_MEASURED'),
    ('text','NOT_MEASURED'),('units','NOT_MEASURED')])
def test_archive_requested_lvs_subject_uses_verified_semantics(tmp_path,monkeypatch,case,expected):
    import pya
    import struct
    import _gds_admission as admission
    import klayout_pdk_lvs as native_owner
    from _gds_geometry import _iter_records
    project,source=neutral(tmp_path/'pack',monkeypatch)
    final=project/'phase3/stage4/gds/alpha.gds'
    native_bytes=final.read_bytes()
    # Reverse complete structure blocks, preserving their records/geometry.
    # Raw and date-only canonical digests differ, while LayoutDiff must judge
    # the actual layouts rather than a supplied equality status word.
    prefix,blocks,suffix=[],[],[]
    block=None
    for rt,dt,payload in _iter_records(native_bytes):
        raw=struct.pack('>HBB',len(payload)+4,rt,dt)+payload
        if rt==0x05:block=[]
        if block is not None:
            block.append(raw)
            if rt==0x07:blocks.append(b''.join(block));block=None
        elif blocks:suffix.append(raw)
        else:prefix.append(raw)
    final.write_bytes(b''.join(prefix+list(reversed(blocks))+suffix))
    if case!='serialization':
        layout=pya.Layout();layout.read(str(final))
        if case=='shape':layout.cell('primitive_cell').shapes(layout.layer(1,0)).insert(pya.Box(20,20,30,30))
        elif case=='text':layout.cell('alpha').shapes(layout.layer(1,0)).insert(pya.Text('changed marker',pya.Trans()))
        else:layout.dbu*=2
        layout.write(str(final))
    stream=project/'phase3/stage3/pnr/alpha.gds';stream.write_bytes(final.read_bytes())
    admission.admit_gds(project,stream,'a'*64,[stream.parent/'routed.def',stream.parent/'constraint.sdc'])
    work=tmp_path/'native-basis';work.mkdir()
    native_layout=work/'native-layout.gds';native_layout.write_bytes(native_bytes)
    def material(name,text):
        path=work/name;path.write_text(text);return _file_ref(path)
    cells=material('cells.spice','* neutral cells\n.SUBCKT unit a b\nR1 a b 1000\n.ENDS unit\n')
    schematic=material('source.spice','* neutral reference\n.include "cells.spice"\n')
    native=material('actual.lvsdb','neutral recorded native result; no extraction was run\n')
    native.update(compare_performed=True,circuits=[{'layout':'alpha','reference':'alpha',
                  'status':'Match','layout_pins':2,'reference_pins':2}],top='alpha')
    record={'schema':'vibeic.native_gds_lvs/1','status':'PASS','tool':'klayout',
            'compare_performed':True,'layout_source':dict(_file_ref(native_layout),kind='gds'),
            'reference_source':material('reference.v','module alpha(input a,output b); assign b=a; endmodule\n'),
            'deck':material('deck.lvs','# neutral retained runset\n'),
            'driver_source':material('driver.lvs','# neutral retained driver\n'),
            'native_result':native,'source_netlist':schematic,'cell_library_bundle':cells,
            'log':material('native.log','neutral native output fixture\n'),
            'inputs_manifest':material('inputs.json','[]\n'),
            'execution':{'rc':0,'inputs_unchanged':True}}
    report=project/'reports/phase3/lvs_verdict.json';report.parent.mkdir(parents=True,exist_ok=True)
    report.write_text(json.dumps(record)+'\n')
    before={str(path):digest(path) for path in [report,native_layout,*work.iterdir()] if path.is_file()}
    measured=_REAL_RELEASE_SOURCES(project,final)
    result=measured['validation']['lvs']
    actual={'verdict':result['verdict'],'binds_requested_final':result.get('gds_sha256')==digest(final)}
    wanted={'verdict':expected,'binds_requested_final':expected=='PASS'}
    observation={'case':case,'observed':actual,'expected':wanted,'archive_lvs':result,
                 'native_layout_source':record['layout_source'],'requested_final':_file_ref(final)}
    (tmp_path/'SEMANTIC_SUBJECT_OBSERVATION.json').write_text(json.dumps(observation,indent=2)+'\n')
    assert actual==wanted,{'observed':actual,'expected':wanted}
    if expected=='PASS':
        verified=native_owner.read_current_verdict(project,report,final)
        assert result['requested_subject']==verified['requested_subject']
        assert result['native_layout_source']==record['layout_source']
        assert result['subject_equivalence']==verified['subject_equivalence']
        assert record['layout_source']['sha256']!=digest(final)
        assert str(native_layout.resolve()) in measured['files']
    else:
        assert 'reason' in result
    assert before=={path:digest(Path(path)) for path in before}
    source['files'].update(measured['files'])
    source['files'][str(final.resolve())]['sha256']=digest(final)
    for kind in ('drc','antenna','density'):source['validation'][kind]['gds_sha256']=digest(final)
    source['validation']['lvs']=result
    monkeypatch.setattr(check,'design_release_sources',lambda *a,**kw:copy.deepcopy(source))
    assert gen.main([str(project)])==0
    rc,gate,command=_in_process_canonical_gate(project,monkeypatch)
    assert (rc,gate['verdict'])==((0,'PASS') if expected=='PASS' else (1,'FAIL')),gate
    manifest=json.loads((project/'phase3/stage4/foundry_handoff/release_manifest.json').read_text())
    if expected=='PASS':
        assert manifest['validation']['lvs']['native_layout_source']==record['layout_source']
        assert manifest['validation']['lvs']['requested_subject']['sha256']==digest(final)
    assert before=={path:digest(Path(path)) for path in before}
    print('VERIFIED_REQUESTED_SUBJECT',json.dumps({'case':case,'lvs':actual,'normal_gate':command,'rc':rc}))


@pytest.mark.parametrize('case,expected',[
    ('full_gds','PASS'),('def_only','NOT_MEASURED'),
    ('missing_spice','NOT_MEASURED'),('measured_fail','FAIL')])
def test_selected_ll_full_gds_lvs_uses_its_real_owner_and_portable_materials(tmp_path,monkeypatch,case,expected):
    """Real run_chain/judge/consumer; only the external process is neutral."""
    import librelane_contract as contract
    import librelane_pv_signoff as pv
    import librelane_signoff_evidence as evidence
    from _native_signoff_fixture import producer,put
    project,source=neutral(tmp_path/'pack',monkeypatch)
    layout=project/'phase3/stage4/gds/alpha.gds'
    ll=tmp_path/'selected-ll';ll.mkdir()
    ll_gds=ll/'phase3/stage4/gds/alpha.gds';ll_gds.parent.mkdir(parents=True)
    ll_gds.write_bytes(layout.read_bytes())
    real_chain=contract.run_chain
    materials={}
    def chain(*args,**kwargs):
        monkeypatch.setattr(contract,'run_chain',real_chain)
        # The fixture's external edge is installed immediately before this
        # real run_chain call. Generate files BEFORE normal receipt hashing.
        edge=contract.run_container
        for step,config,_state in args[2]:
            doc=json.loads(config.read_text())
            if case=='def_only':doc['MAGIC_EXT_USE_GDS']=False
            model=ll/'native-inputs/cells.spice';model.parent.mkdir(exist_ok=True)
            model.write_text('.SUBCKT unit a b\nR1 a b 1000\n.ENDS unit\n')
            setup=ll/'native-inputs/setup.tcl';setup.write_text('# neutral native setup\n')
            doc.update(SPICE_MODELS=[str(model)],NETGEN_SETUP_FILE=str(setup))
            put(config,doc);materials.update(model=model,setup=setup)
        def process(command,**kw):
            result=edge(command,**kw)
            folder=Path(command[command.index('-o')+1])
            step=command[command.index('--id')+1]
            if step=='Magic.SpiceExtraction' and case!='missing_spice':
                spice=folder/'alpha.spice'
                spice.write_text('.include "../../../../native-inputs/cells.spice"\n'
                                 '.SUBCKT alpha a b\nX1 a b unit\n.ENDS alpha\n')
                state=json.loads((folder/'state_out.json').read_text());state['spice']=str(spice)
                put(folder/'state_out.json',state);materials['spice']=spice
            if step=='Netgen.LVS':
                report=folder/'reports/lvs.netgen.rpt';report.parent.mkdir(exist_ok=True)
                report.write_text('neutral compare process transcript\n')
            return result
        monkeypatch.setattr(contract,'run_container',process)
        return real_chain(*args,**kwargs)
    monkeypatch.setattr(contract,'run_chain',chain)
    info=producer(ll,monkeypatch,'lvs',gds_path=ll_gds,
                  counts={'design__lvs_error__count':2} if case=='measured_fail' else {})
    # No copied PASS record: real Python producer created the owner judgment.
    # An explicit provider publisher file-ref selects that existing LL owner.
    record=project/'reports/phase3/neutral-selected-assembly.json';record.write_text('{}\n')
    assembly={'gds':layout,'sha256':digest(layout),'report':record,'source_project':project,
              'basis':{'current_signoff':{'lvs':_file_ref(info['record'])}},'scope':'provider_die_assembly'}
    measured=_REAL_RELEASE_SOURCES(project,layout,assembly)
    observed=measured['validation']['lvs']
    assert observed['verdict']==expected,{'observed':observed,'expected':expected}
    if case=='full_gds':
        assert set(observed['rows'])=={'magic__illegal_overlap__count',*pv.PRODUCED['Netgen.LVS']}
        assert any('physical_reference_netlist' in e['roles'] for e in measured['files'].values())
        assert all(str(materials[k]) in measured['files'] for k in ('model','setup','spice'))
        # Current record selection must not accept wrong bytes or an arbitrary
        # same-hash sibling. No legacy report or alternate owner is guessed.
        for damage in ('hash','path'):
            bad=copy.deepcopy(assembly)
            if damage=='hash':bad['basis']['current_signoff']['lvs']['sha256']='0'*64
            else:
                sibling=ll/'reports/phase3/other.json';sibling.write_bytes(info['record'].read_bytes())
                bad['basis']['current_signoff']['lvs']=_file_ref(sibling)
            assert _REAL_RELEASE_SOURCES(project,layout,bad)['validation']['lvs']['verdict']=='NOT_MEASURED'
        import phase3_one_shot_runner as runner
        pv.publish_report(info['folders'][-1],'reports/lvs.netgen.rpt',ll/'reports/phase3/lvs.rpt')
        runner._write_lvs_verdict(ll,'PASS','LVS_MATCH_LIBRELANE_NETGEN','neutral protocol compare',
            {'generated_by':'librelane_pv_signoff.run_half (mig105)','librelane_pv':str(info['record'])})
        assert _REAL_RELEASE_SOURCES(ll,ll_gds)['validation']['lvs']['verdict']=='PASS'
        # Without an explicit selection, a corrupt canonical native report
        # must not fall back to otherwise valid LL receipts.
        canonical=ll/'reports/phase3/lvs_verdict.json';canonical.write_text('{ corrupt current native record')
        assert _REAL_RELEASE_SOURCES(ll,ll_gds)['validation']['lvs']['verdict']=='NOT_MEASURED'
        canonical.unlink()
        before=info['record'].read_bytes();declared=json.loads(before)
        for engine in ('KLayout.LVS','Unknown.Measurement'):
            declared['required_steps']=[*pv.HALVES['lvs'],engine];put(info['record'],declared)
            assert evidence.obligation(ll,'lvs',ll_gds)['verdict']=='NOT_MEASURED'
        info['record'].write_bytes(before)
    source['validation']['lvs']=observed;source['files'].update(measured['files'])
    monkeypatch.setattr(check,'design_release_sources',lambda *a,**kw:copy.deepcopy(source))
    assert gen.main([str(project)])==0
    rc,gate,command=_in_process_canonical_gate(project,monkeypatch)
    assert (rc,gate['verdict'])==((0,'PASS') if expected=='PASS' else (1,'FAIL')),gate
    if case=='full_gds':
        import pya
        package=project/'phase3/stage4/foundry_handoff'
        manifest=json.loads((package/'release_manifest.json').read_text())
        archived=next(e['path'] for e in manifest['files'] if e['source']==str(materials['spice']))
        project.rename(tmp_path/'held-project');ll.rename(tmp_path/'held-ll')
        relocated=tmp_path/'relocated';shutil.move(str(tmp_path/'held-project/phase3/stage4/foundry_handoff'),relocated)
        parsed=pya.Netlist();parsed.read(str(relocated/archived),pya.NetlistSpiceReader())
        assert parsed.circuit_by_name('unit') is not None
        _manifest,bad=check.check_design_release(relocated);assert not bad,bad
    observation={'case':case,'expected':expected,'lvs':observed,'normal_gate':command,'rc':rc,
                 'source_only':'neutral process edge; actual run_chain receipts/judge/obligation/archive/parser'}
    (tmp_path/'LL_RELEASE_OBSERVATION.json').write_text(json.dumps(observation,indent=2)+'\n')
    print('LL_RELEASE_VALUES',json.dumps(observation))


def test_timestamp_kit_ate_closure_survives_normal_gate_and_source_free_relocation(tmp_path,monkeypatch):
    project,_source=neutral(tmp_path/'source',monkeypatch)
    source_record=project/step5.STEP5_REL
    source_trace=project/json.loads(source_record.read_text())['cases'][0]['trace']['vcd']
    original={str(p):digest(p) for p in (source_record,source_trace)}
    destination=tmp_path/'timestamp-kit'
    assert gen.main([str(project),'--out-dir',str(destination)])==0
    # This is the normal canonical Step38 gate over a RO-equivalent kit
    # overlay. Only transport creates the link; the producer's source inputs
    # and the real repository VCD/Step5 record stay byte-identical.
    canonical=project/'phase3/stage4/foundry_handoff'
    canonical.parent.mkdir(parents=True,exist_ok=True)
    canonical.symlink_to(destination,target_is_directory=True)
    rc,report,command=_in_process_canonical_gate(project,monkeypatch)
    observed={'rc':rc,'verdict':report['verdict']}
    assert observed=={'rc':0,'verdict':'PASS'},{'observed':observed,'expected':{'rc':0,'verdict':'PASS'},'findings':report['findings']}
    corner=json.loads((destination/'corner_test_vectors.json').read_text())
    item=next(row for row in corner['open_items'] if row['field']=='PENDING_FOUNDRY_test_patterns')
    assert item['status']=='CLOSED' and len(item['evidence'])==1
    header=destination/item['evidence'][0]['path'];doc=json.loads(header.read_text())
    assert not Path(item['evidence'][0]['path']).is_absolute()
    assert not Path(doc['vectors_file']['path']).is_absolute()
    for name,path in (('source_trace',source_trace),('step5_record',source_record)):
        assert (destination/doc[name]['path']).read_bytes()==path.read_bytes()
    assert original=={p:digest(Path(p)) for p in original}
    project.rename(tmp_path/'held-original')
    relocated=tmp_path/'relocated-kit';destination.rename(relocated)
    retained=relocated/'archive/project'
    bad=check._closing_evidence_problems(retained,item['evidence'],relocated)
    assert bad==[],bad
    _manifest,bad=check.check_design_release(relocated);assert not bad,bad
    # Original missing-vector and failed-Step5 refusal contracts still apply
    # to the same retained consumer after relocation.
    vector=relocated/doc['vectors_file']['path'];held=vector.with_suffix('.held')
    vector.rename(held)
    assert check._closing_evidence_problems(retained,item['evidence'],relocated)
    held.rename(vector)
    record=relocated/doc['step5_record']['path'];before=record.read_bytes()
    changed=json.loads(before);changed['cases'][0]['state']='failed';record.write_text(json.dumps(changed))
    assert any('PASSED case' in problem for problem in check._closing_evidence_problems(retained,item['evidence'],relocated))
    record.write_bytes(before)
    assert not check.check_design_release(relocated)[1]
    observation={'normal':observed,'command':command,'relocated_closure':True,'item':item,
                 'header':doc,'source_inputs_unchanged':True,'missing_vector_refused':True,'failed_step5_refused':True}
    (tmp_path/'PORTABLE_ATE_OBSERVATION.json').write_text(json.dumps(observation,indent=2)+'\n')
    print('PORTABLE_ATE_VALUES',json.dumps(observation))
