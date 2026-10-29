"""SOFTWARE ONLY: real mode consumers with explicit SDK/qualification stand-ins.

No native STA, final geometry, SPM, or platform qualification is claimed.
"""
import copy
import json
import shutil
from pathlib import Path

import pytest
import flow109
import flow109_admission as admission
import flow109_metric_acceptance as metrics
import librelane_contract as contract
import librelane_fill_stream as files
import librelane_signoff as signoff
import execution_backend_gates as gates
import flow_compliance_check as fcc


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, (dict, list)) else value)
    return path


def ref(project, path):
    return files._record(project, path)


def qualified(project, owner, scan=True):
    from test_flow109_selection import profile
    features = profile('Small digital IC without DFT')
    features.update(requires_scan=scan, requires_dft=scan)
    context = flow109.execution_context(flow109.resolve_plan(features), owner, owner)
    uses, entries = [], []
    for spec in context['resolved_row']['tool_uses']:
        binary = Path(shutil.which(spec['executable_name'])).resolve()
        config = ref(project, put(project / ('input/software/' + spec['use_id'].replace('/', '_') + '.json'),
            {'model_sources': signoff.scan_timing_sources()}))
        evidence = ref(project, put(project / 'input/software/evidence.json', {'scope': 'SOFTWARE_ONLY_NOT_NATIVE_QUALIFICATION'}))
        identity = {'use_id': spec['use_id'], 'tool_id': spec['tool_id'], 'version': 'SOFTWARE_ONLY',
            'executable': {'path': str(binary), 'sha256': contract.digest(binary)},
            'build_sha256': contract.digest(binary), 'config': config,
            'pdk': {'applicable': False, 'reason': 'SOFTWARE_ONLY'},
            'deck': {'applicable': False, 'reason': 'SOFTWARE_ONLY'}, 'corner': 'SOFTWARE_ONLY',
            'semantics': {'purpose': owner + '.default', 'native_steps': spec['native_steps']}}
        entry = {'use_id': spec['use_id'], 'status': 'QUALIFIED', 'identity': identity,
                 'reference_evidence': [evidence]}
        entries.append(entry)
        uses.append({**identity, 'qualification_sha256': admission.canonical_sha(entry)})
    registry = 'input/software/registry.json'
    put(project / registry, {'schema': 'vibeic.flow109.qualifications.v1', 'uses': entries,
                            'scope': 'SOFTWARE_ONLY_NOT_NATIVE_QUALIFICATION'})
    return flow109.execution_context(flow109.resolve_plan(features), owner, owner,
        runtime_tool_uses=uses, qualification_registry=registry)


@pytest.fixture
def software(tmp_path, monkeypatch):
    p = tmp_path / 'SOFTWARE_ONLY'; p.mkdir()
    paths = {name: put(p / ('input/' + name), 'SOFTWARE_ONLY ' + name) for name in
             ('netlist.v', 'routed.def', 'routed.odb', 'functional.sdc', 'shift.sdc', 'capture.sdc', 'nom.spef', 'cells.lib', 'rc.rules')}
    state = {k: str(paths[v]) for k, v in [('nl','netlist.v'), ('def','routed.def'), ('odb','routed.odb'), ('sdc','functional.sdc')]}
    state['spef'] = {'nom_*': str(paths['nom.spef'])}
    items = [{'mode': m, 'corner': 'nom_tt', 'check': c} for m in ('shift','capture') for c in ('setup','hold')]
    scenarios = {'required_modes': ['functional','shift','capture'], 'required_corners': ['nom_tt'],
                 'required_checks': ['setup','hold'], 'required_items': items}
    mapping = {'reference': [{**i, 'sdc': ref(p, paths[i['mode'] + '.sdc']),
        'libraries': [ref(p, paths['cells.lib'])], 'rc': {'corner': 'nom', 'model': ref(p, paths['rc.rules'])}} for i in items]}
    source = ref(p, put(p/'input/owner.json', {'scope':'SOFTWARE_ONLY', 'scenario_constraints':scenarios, 'mode_library_rc_mapping':mapping}))
    for name, body, relative, schema in (
        ('scenario_constraints',scenarios,'requirements/base_10/scenario_constraints.json',metrics.AUTHORITY_SCHEMA),
        ('mode_library_rc_mapping',mapping,'adopted/base_10/mode_library_rc_mapping.json','vibeic.flow109.adopted-reference.v1')):
        put(p/relative, {'schema':schema, **body, 'approval':{'status':'APPROVED', 'authority':'requirements_owner','source_reference':source}})
    failures = {}
    # Explicit SOFTWARE stand-in for the existing host-CID live-launch seam.
    # No host/native attestation or platform qualification is being authored.
    launch = {'image':'SOFTWARE_ONLY','image_id':'sha256:'+'1'*64,'cid':'2'*64,
              'attestation_path':str(put(p/'input/software-launch.json',{'scope':'SOFTWARE_ONLY_NOT_NATIVE'}))}
    launch['attestation_sha256'] = contract.digest(Path(launch['attestation_path']))
    monkeypatch.setattr(contract, 'local_image_attestation', lambda _image=None: dict(launch))

    def resolve(project, image, pdk, steps, *, folder, overlay, **kwargs):
        configs = {}
        for step in steps:
            cfg = {'meta':{'step':step}, 'RCX_RULESETS':{'nom_*':str(paths['rc.rules'])},
                   'STA_CORNERS':['nom_tt'], 'CELL_LIBS':{'nom_tt':[str(paths['cells.lib'])]},
                   'SIGNOFF_SDC_FILE':str(paths['functional.sdc'])}
            for key, (value, _) in overlay.items():
                cfg[key] = str(p/value[5:]) if isinstance(value,str) and value.startswith('dir::') else value
            configs[step] = put(p/'phase3/librelane'/folder/(step+'.json'), cfg)
        return configs

    def bridge(project, image, config, views, folder, **kwargs):
        def strings(value):
            return {k:strings(v) for k,v in value.items()} if isinstance(value,dict) else str(value)
        return put(folder/'state.json', strings(views))

    def chain(project, image, steps, *, lane, **kwargs):
        folders = []
        for step, cfg_path, input_path in steps:
            folder = p/'phase3/librelane'/lane/'sta'; folder.mkdir(parents=True, exist_ok=False)
            cfg = json.loads(cfg_path.read_text()); before = json.loads(input_path.read_text())
            # Model the actual SDK consuming Config SDC, rather than trusting the requested mode label.
            before['sdc'] = cfg['SIGNOFF_SDC_FILE']
            out = copy.deepcopy(before); out['metrics'] = {}; out['sdf'] = {}
            mode = Path(out['sdc']).stem
            for corner in cfg['STA_CORNERS']:
                for key, metric in signoff.TIMING_METRICS.items():
                    value = 1.0 if key in ('setup_ws','hold_ws') else 0
                    if failures.get(mode) == key: value = -0.2 if key.endswith('_ws') else 1
                    out['metrics'][metric+'__corner:'+corner] = value
                put(folder/corner/'sta.log', 'SOFTWARE_ONLY native NOT_RUN\n')
                put(folder/corner/signoff.CORNER_REPORT, signoff.DERATE_MARKER+' early=0.95 late=1.05\n')
                put(folder/corner/'unpropagated.rpt', '')
                out['sdf'][corner] = str(put(folder/(corner+'.sdf'), 'SOFTWARE_ONLY SDF'))
            put(folder/'state_in.json', before); put(folder/'state_out.json', out); put(folder/'config.json', cfg)
            inputs = [before[k] for k in ('nl','def','odb','sdc')] + list(before['spef'].values())
            fp = {'step':step, 'image':image, 'local_image':dict(launch),
                  'config':contract.digest(folder/'config.json'), 'state':contract.digest(folder/'state_in.json'),
                  'config_files':contract.config_file_hashes(cfg, []), 'state_files':{v:contract.digest(Path(v)) for v in inputs},
                  'liberty_files':{v:contract.digest(Path(v)) for vals in cfg['CELL_LIBS'].values() for v in vals}}
            put(folder/'input_fingerprint.json', fp); put(folder/'pdk_root.json', {'scope':'SOFTWARE_ONLY'})
            put(folder/'invocation.log', 'SOFTWARE_ONLY native NOT_RUN\n')
            put(folder/'vibeic_receipt.json', {'input':fp, 'sha256':{
                str(f.relative_to(folder)):contract.digest(f) for f in folder.rglob('*') if f.is_file()}})
            folders.append(folder)
        return folders
    monkeypatch.setattr(signoff,'resolve_step_configs',resolve)
    monkeypatch.setattr(signoff,'state_from_direct',bridge)
    monkeypatch.setattr(signoff,'run_chain',chain)
    import librelane_pv_signoff as pv
    monkeypatch.setattr(pv,'tech_lef_overlay',lambda *_:None)
    native = {'image':'SOFTWARE_ONLY','pdk_root':p/'pdk','pdk':'neutral'}
    return p, paths, state, native, failures


def acquire(software, owner='D49'):
    p, paths, state, native, failures = software
    ctx = qualified(p, owner)
    coverage = signoff.run_scan_timing(p,ctx,owner,native,state)
    return ctx, coverage


@pytest.mark.parametrize('damage,expected', [('clean','PASS'),('shift-hold','FAIL'),('capture-setup','FAIL'),
    ('missing-capture','NOT_MEASURED'),('failed-shift-missing-capture','FAIL'),('stale-sdc','NOT_MEASURED'),
    ('forged-state','NOT_MEASURED'),('unbound-metrics','NOT_MEASURED'),('stale-model','NOT_MEASURED'),('missing-qualification','NOT_MEASURED')])
def test_actual_candidate_consumer(software, monkeypatch, damage, expected):
    p, paths, state, native, failures = software
    if damage in ('shift-hold','failed-shift-missing-capture'): failures['shift']='hold_ws'
    if damage=='capture-setup': failures['capture']='setup_ws'
    ctx, coverage = acquire(software)
    if 'missing-capture' in damage: coverage['modes'].pop('capture')
    if damage=='stale-sdc': paths['capture.sdc'].write_text('changed actual input')
    if damage=='forged-state': coverage['modes']['capture'][0]['sta_state']['sha256']='a'*64
    if damage=='unbound-metrics':
        folder=(p/coverage['modes']['capture'][0]['sta_state']['path']).parent
        put(folder/'metrics.json', {'timing__hold__ws__corner:nom_tt':100})
    if damage=='stale-model':
        config=p/ctx['runtime_tool_uses'][0]['config']['path']; config.write_text('{}')
    if damage=='missing-qualification': (p/ctx['qualification_registry']).unlink()
    put(p/signoff.SIGNOFF_RECORD, {'sta_state':str(put(p/'functional-state.json',state)), 'scan_timing_coverage':coverage})
    context_path=put(p/'context.json',ctx); monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT',str(context_path))
    # Other canonical clauses are explicit SOFTWARE upstream fixtures; the changed mode consumer is real.
    monkeypatch.setattr(fcc,'check_step',lambda *_a,**_k:fcc.StepResult(23,'SOFTWARE upstream','phase3','PASS'))
    observed=gates.evaluate(p,gates.canonical_family_row('23'))
    put(p/'actual-consumer.json',observed)
    assert observed['status']==expected, observed
    if damage=='clean':
        assert set(coverage['modes'])=={'shift','capture'}
        a,b=[Path(coverage['modes'][m][0]['sta_state']['path']) for m in ('shift','capture')]
        assert a!=b
        assert json.loads((p/a).read_text())['sdc']==str(paths['shift.sdc'])
        assert json.loads((p/b).read_text())['sdc']==str(paths['capture.sdc'])


def test_optional_run_default_and_namespace_binding(software):
    p, paths, state, native, failures=software
    result=signoff.run(p,**native,routed_def=paths['routed.def'],routed_odb=paths['routed.odb'],
        netlist=paths['netlist.v'],sdc=paths['functional.sdc'],extract=False,direct_spefs={'nom':paths['nom.spef']})
    actual=json.loads((result['sta']/'state_out.json').read_text())
    assert actual['sdc']==str(paths['functional.sdc'])
    assert result['configs']['OpenROAD.STAPostPNR'].parent.name=='22-config'
    for namespace in ('../escape','22-config','fresh-config-with-existing-output'):
        with pytest.raises(contract.Refusal,match='LL_STA_NAMESPACE_INVALID'):
            signoff.run(p,**native,routed_def=paths['routed.def'],netlist=paths['netlist.v'],
                sdc=paths['functional.sdc'],config_folder=namespace)
    assert json.loads((result['sta']/'state_out.json').read_text())==actual


def test_non_scan_candidate_keeps_existing_functional_consumer(software,monkeypatch):
    p,paths,state,native,failures=software
    ctx=qualified(p,'D49',False)
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT',str(put(p/'context.json',ctx)))
    monkeypatch.setattr(fcc,'check_step',lambda *_a,**_k:fcc.StepResult(23,'SOFTWARE upstream','phase3','PASS'))
    (p/'requirements/base_10/scenario_constraints.json').unlink()
    assert gates.evaluate(p,gates.canonical_family_row('23'))['status']=='PASS'


@pytest.mark.parametrize('damage,expected', [('clean','PASS'),('shift-hold','FAIL'),('capture-setup','FAIL'),
    ('missing-capture','NOT_MEASURED'),('failed-shift-missing-capture','FAIL'),('non-scan','PASS')])
def test_actual_final_electrical_component_and_reader(software,monkeypatch,damage,expected):
    import flow109_final_electrical as final
    p,paths,state,native,failures=software
    ctx=qualified(p,'D70',damage!='non-scan')
    if damage in ('shift-hold','failed-shift-missing-capture'): failures['shift']='hold_ws'
    if damage=='capture-setup': failures['capture']='setup_ws'
    parasitics={'odb':ref(p,paths['routed.odb']), 'filled_def':ref(p,paths['routed.def']),
        'adopted_views':{'netlist':ref(p,paths['netlist.v']), 'sdc':ref(p,paths['functional.sdc'])},
        'spefs':{'nom':ref(p,paths['nom.spef'])}, 'final_spefs':{'nom':ref(p,paths['nom.spef'])}}
    d69=ref(p,put(p/'input/software-final-geometry.json',{'scope':'SOFTWARE_ONLY_FINAL_GEOMETRY_NOT_MEASURED'}))
    put(p/final.INPUT,{'schema':final.SCHEMA,'required_corners':['nom_tt'],
        'final_parasitics_receipt':d69,'librelane':{**native,'pdk_root':str(native['pdk_root'])}})
    # Existing final-geometry acceptance is an explicitly scoped upstream fixture, not product code bypass.
    monkeypatch.setattr(final.extract,'validate_final_parasitics',lambda *_:parasitics)
    original=signoff.run_scan_timing
    def acquire_without_capture(*args,**kwargs):
        coverage=original(*args,**kwargs)
        coverage['modes'].pop('capture',None)
        coverage['status']='FAIL' if damage.startswith('failed') else 'NOT_MEASURED'
        return coverage
    if 'missing-capture' in damage:
        monkeypatch.setattr(signoff,'run_scan_timing',acquire_without_capture)
    result=final.execute(p,ctx)
    put(p/'actual-final.json',result)
    assert result['component_status']==expected,result
    assert result['flow109_acceptance']=='NOT_MEASURED'
    if expected=='PASS':
        current=final.validate_final_electrical(p,result['receipt'])
        assert current['component_electrical_current'] is True
        if damage=='clean':
            # Editing only a retained scan input invalidates the real final consumer.
            paths['capture.sdc'].write_text('SOFTWARE_ONLY changed input')
            with pytest.raises(admission.AdmissionRefusal,match='D70_SCAN_MODES_NOT_ACQUIRED'):
                final.validate_final_electrical(p,result['receipt'])


def test_selected_candidate_producer_publishes_the_consumed_mode_measurements(software,monkeypatch):
    from types import SimpleNamespace
    import execution_backend_producers as producers
    import clock_target_provenance as provenance
    import librelane_ir_antenna as power_grid
    import _atomic_artefact as atomic
    p,paths,state,native,failures=software
    ctx=qualified(p,'D49'); failures['shift']='hold_ws'
    monkeypatch.setenv('VIBEIC_FLOW109_CONTEXT',str(put(p/'context.json',ctx)))
    functional=signoff.run(p,**native,routed_def=paths['routed.def'],routed_odb=paths['routed.odb'],
        netlist=paths['netlist.v'],sdc=paths['functional.sdc'],extract=False,direct_spefs={'nom':paths['nom.spef']})
    sta_state=functional['sta']/'state_out.json'
    put(p/signoff.SIGNOFF_RECORD,{'sta_state':str(sta_state),'sta_state_sha256':contract.digest(sta_state),
        'corners':signoff.corner_timing(functional['sta'])})
    put(p/'phase3/stage3/extracted/neutral.spef','SOFTWARE_ONLY')
    noop=lambda *_a,**_k:None
    R=SimpleNamespace(_librelane_handed_spefs=lambda *_:{'nom':paths['nom.spef']},
        _librelane_signoff_record=noop,_librelane_signoff_report_body=lambda:'',_aa=atomic,
        _log_surviving_artefact=noop,_achievable_fmax_from_tool_arm=noop,
        _resolve_clock_spec=lambda *_a,**_k:(10,'SOFTWARE_ONLY'))
    monkeypatch.setattr(producers,'_parameters',lambda *_:(R,None,SimpleNamespace(name='neutral'),None))
    monkeypatch.setattr(provenance,'emit_report',noop); monkeypatch.setattr(provenance,'stamp_signoff_records',noop)
    monkeypatch.setattr(power_grid,'publish_power_connectivity',lambda *_a,**_k:{'verdict':'PASS'})
    producers.produce_signoff(p,{'step_id':'23','top':'neutral','execution_mode':'default',
        'pdk_root':str(native['pdk_root']),'image_id':native['image']})
    monkeypatch.setattr(fcc,'check_step',lambda *_a,**_k:fcc.StepResult(23,'SOFTWARE upstream','phase3','PASS'))
    actual=gates.evaluate(p,gates.canonical_family_row('23'))
    put(p/'actual-selected-producer-consumer.json',actual)
    assert actual['status']=='FAIL',actual
    assert actual['scan_timing_coverage']['status']=='FAIL'
