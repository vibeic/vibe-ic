"""Exact producer inputs survive a native-owner checkpoint continuation."""
import json
import shutil
from pathlib import Path
import pytest
import execution_adapters_backend as adapters
import librelane_fill_dfm as fill
import librelane_ir_antenna as ir
import librelane_contract as contract
import submission_template_check as catalogue
import tapeout_declaration_check as declaration
import _submission_template as template
import _default_backend_fixtures as fixtures
from test_d59_current_perc_subject import _geometry_scene, _reseal
from test_owner_self_tapeout_catalogue import _relocated_owner_tree


def scene(tmp_path, monkeypatch):
    project, folder, native_def, _ = _geometry_scene(tmp_path, monkeypatch)
    owner = next(parent for parent in native_def.parents if (parent/'state_out.json').is_file())
    base=tmp_path/'cat';base.mkdir();issued=_relocated_owner_tree(base)
    for dst in (owner,project):shutil.copytree(issued,dst,dirs_exist_ok=True)
    io='reports/phase3/io_pad_chip_top.json';(owner/io).parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(project/io,owner/io)
    native_def.write_text(native_def.read_text()+'\nNETS 1 ;\n- external ( r0 B ) ;\nEND NETS\n')
    views = json.loads((owner/'state_out.json').read_text())
    filled, _ = fixtures.producer(owner, fill.ODB_FILL_STEP,
        {key: views[key] for key in ('odb', 'def')},
        {key: views[key] for key in ('odb', 'def')},
        lane='34/01-openroad-fillinsertion')
    record = owner/fill.RECORD_REL
    record.parent.mkdir(parents=True, exist_ok=True)
    record.write_text(json.dumps({'odb': {'tool': {
        'state': str(filled/'state_out.json'),
        'state_sha256': contract.digest(filled/'state_out.json'),
        'filled_def_sha256': contract.digest(native_def)}}}))
    _reseal(folder)
    pad=owner/'phase3/stage3/pnr/padring.def';pad.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(native_def,pad)
    (project/template.REPORT_REL).unlink()
    return project,owner,folder,native_def


def test_whole_prerequisite_consumer_after_exact_transport(tmp_path,monkeypatch):
    project,owner,folder,native_def=scene(tmp_path,monkeypatch)
    before=declaration.evaluate(project)
    assert any(r['rule']=='ROUTER_CONTRADICTION' for r in before['refusals'])
    restored=adapters.restore_continuation_prerequisites(project)
    assert set(restored['inputs'])=={template.REPORT_REL,'phase3/stage3/pnr/padring.def'}
    assert declaration.evaluate(project)['verdict']=='INCOMPLETE'
    assert catalogue.catalogue_selects_self_tapeout(project)[0] is True
    assert declaration.evaluate(project)['refusals']==[]
    for rel,row in restored['inputs'].items():
        a,b=owner/rel,project/rel
        assert a.read_bytes()==b.read_bytes()
        assert (a.stat().st_dev,a.stat().st_ino)!=(b.stat().st_dev,b.stat().st_ino)
        assert contract.digest(a)==row['sha256']
    assert (project/'reports/phase3/perc_equivalent.json').exists() is False
    # Source-owned repeated preparation is idempotent, never a fake new proof.
    assert adapters.restore_continuation_prerequisites(project)==restored


@pytest.mark.parametrize('damage',['missing_report','missing_padring','stale_source','wrong_owner','wrong_geometry','wrong_wiring','stale_state','conflicting_existing'])
def test_missing_stale_owner_geometry_refuse_without_invalid_pad(tmp_path,monkeypatch,damage):
    project,owner,folder,native_def=scene(tmp_path,monkeypatch)
    if damage=='missing_report':(owner/template.REPORT_REL).unlink()
    elif damage=='missing_padring':(owner/'phase3/stage3/pnr/padring.def').unlink()
    elif damage=='stale_source':
        next((project/template.STAGED_TEMPLATE_REL).glob('*.json')).write_text('{}')
    elif damage=='wrong_owner':
        (owner/'input/step_0_5ic_answers.json').write_text('{}')
    elif damage in ('wrong_geometry','wrong_wiring'):
        pad=owner/'phase3/stage3/pnr/padring.def';text=pad.read_text()
        text=text.replace('350000 350000','340000 350000',1) if damage=='wrong_geometry' else text.replace('- external ( r0 B )','- wrong ( r0 B )',1)
        pad.write_text(text)
    elif damage=='stale_state':(folder/'state_out.json').write_text('{}')
    else:
        target=project/'phase3/stage3/pnr/padring.def';target.parent.mkdir(parents=True,exist_ok=True);target.write_text('different')
    with pytest.raises((ValueError,OSError,contract.Refusal)):
        adapters.restore_continuation_prerequisites(project)
    assert (project/template.REPORT_REL).exists() == (damage in {'missing_padring','wrong_geometry','wrong_wiring','conflicting_existing'})
    if damage != 'conflicting_existing':
        assert not (project/'phase3/stage3/pnr/padring.def').exists()


def test_checkpoint_manifest_carries_genuine_catalogue_and_source(tmp_path,monkeypatch):
    project,owner,_,_=scene(tmp_path,monkeypatch)
    adapters.restore_continuation_prerequisites(project)
    inputs=adapters.backend_project_input_contract(project,'28',collect_missing=True,execution_mode='default')
    assert template.REPORT_REL in inputs
    static=adapters._backend_input_contract('28',{'canonical_row':{}})
    assert {'from':'external','path':template.STAGED_TEMPLATE_REL,'required':False} in static
    assert 'phase3/stage3/pnr' in static


def test_normal_frontdoor_restores_before_d75_attempt(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import flow109
    monkeypatch.setenv(flow109.CONTEXT_ENV,'')
    monkeypatch.setenv(flow109.ATTEMPT_ENV,'')
    from test_flow109_package_ready import _context
    project,owner,_,_=scene(tmp_path,monkeypatch)
    context=_context(project)
    manifest=project/'input/selection.json'
    manifest.write_text(json.dumps({'features':context['features']}))
    class Prepared(RuntimeError):pass
    def before_attempt(*args):
        assert declaration.evaluate(project)['verdict']=='INCOMPLETE'
        raise Prepared('normal prerequisite closure prepared before adapter')
    import flow109_package_ready
    monkeypatch.setattr(flow109_package_ready,'execute',before_attempt)
    args=SimpleNamespace(flow='109',flow109_manifest=manifest,flow109_plan_only=False,
        execution_mode='default',entry_step='D75',exit_step='D75',container='')
    with pytest.raises(Prepared):flow109.prepare_front_door(args,project)


def test_sc_library_endcap_is_not_an_io_ring_instance(tmp_path,monkeypatch):
    project,owner,folder,native_def=scene(tmp_path,monkeypatch)
    sc=project/'input/pdk/sc.lef'
    sc.write_text(sc.read_text()+'\nMACRO physical_boundary\n CLASS ENDCAP PRE ;\nEND physical_boundary\n')
    receipt=json.loads((folder/'vibeic_receipt.json').read_text())
    receipt['input']['config_files'][str(sc)]=contract.digest(sc)
    (folder/'vibeic_receipt.json').write_text(json.dumps(receipt))
    import re
    text=re.sub(r'COMPONENTS (\d+)',lambda m:f'COMPONENTS {int(m[1])+1}',native_def.read_text())
    native_def.write_text(text.replace('END COMPONENTS',
        '- edge physical_boundary + FIXED ( 200000 200000 ) N ;\nEND COMPONENTS'))
    record=json.loads((owner/fill.RECORD_REL).read_text())
    record['odb']['tool']['filled_def_sha256']=contract.digest(native_def)
    (owner/fill.RECORD_REL).write_text(json.dumps(record));_reseal(folder)
    _reseal(native_def.parent)
    restored=adapters.restore_continuation_prerequisites(project)
    assert len(restored['inputs'])==2
    assert catalogue.catalogue_selects_self_tapeout(project)[0] is True


def _current_frontdoor_case(tmp_path, monkeypatch):
    from test_flow109_package_ready import _project, _current_native_authority
    project = _project(tmp_path)
    authority = _current_native_authority(project, monkeypatch)
    # Only the historical publication gets these obsolete supply BTerms.
    # The current native view remains the fixture's valid adopted geometry.
    old = authority['old_def']
    old.write_text(old.read_text().replace('PINS 1 ;', 'PINS 3 ;').replace(
        'END PINS', '- VDD + NET VDD + USE POWER + LAYER Metal5 ( 0 0 ) ( 20 20 ) + PLACED ( 0 0 ) N ;\n'
        '- VSS + NET VSS + USE GROUND + LAYER Metal5 ( 0 0 ) ( 20 20 ) + PLACED ( 100 0 ) N ;\nEND PINS'))
    return project, authority


def _normal_d75_prerequisite(project, monkeypatch):
    from types import SimpleNamespace
    import flow109
    from test_flow109_package_ready import _context
    monkeypatch.setenv(flow109.CONTEXT_ENV, '')
    monkeypatch.setenv(flow109.ATTEMPT_ENV, '')
    context = _context(project)
    manifest = project / 'input/current-selection.json'
    manifest.write_text(json.dumps({'features': context['features']}))
    args = SimpleNamespace(flow='109',flow109_manifest=manifest,flow109_plan_only=False,
        execution_mode='default',entry_step='D75',exit_step='D75',container='')
    try:
        rc = flow109.prepare_front_door(args,project)
    except (ValueError,OSError,contract.Refusal) as exc:
        return {'route':'REFUSED_BEFORE_ADAPTER','reason':str(exc)}
    result = json.loads((project/'reports/flow109/components/D75.json').read_text())
    return {'route':'ADAPTER_EXECUTED','rc':rc,'result':result}


@pytest.mark.parametrize('old_view', ['different_power_bterms','absent'])
def test_normal_frontdoor_uses_d75_validated_native_authority(tmp_path,monkeypatch,old_view):
    from test_flow109_package_ready import _by_name
    project,authority=_current_frontdoor_case(tmp_path,monkeypatch)
    if old_view=='absent':authority['old_def'].unlink()
    old_bytes=authority['old_def'].read_bytes() if authority['old_def'].exists() else None
    observed=_normal_d75_prerequisite(project,monkeypatch)
    assert observed['route']=='ADAPTER_EXECUTED',observed
    assert observed['rc']==0 and observed['result']['component_status']=='PASS',observed
    bound=_by_name(observed['result'],'current_native_geometry_authority')
    assert bound['status']=='PASS'
    assert bound['detail']['def']['sha256']==contract.digest(authority['def'])
    assert bound['detail']['odb']['sha256']==contract.digest(authority['odb'])
    assert observed['result']['flow109_acceptance']=='NOT_MEASURED'
    assert (authority['old_def'].read_bytes() if authority['old_def'].exists() else None)==old_bytes


@pytest.mark.parametrize('damage',['missing_state','stale_tech','wrong_view','foreign_view'])
def test_normal_frontdoor_invalid_current_authority_never_skips_checks(tmp_path,monkeypatch,damage):
    project,authority=_current_frontdoor_case(tmp_path,monkeypatch)
    if damage=='missing_state':(authority['folder']/'state_out.json').unlink()
    elif damage=='stale_tech':authority['tech'].write_text(authority['tech'].read_text()+'\nchanged\n')
    elif damage=='wrong_view':authority['selected']['views']['def']=authority['old_def']
    else:
        foreign=tmp_path/'foreign.def';foreign.write_bytes(authority['def'].read_bytes())
        authority['selected']['views']['def']=foreign
    observed=_normal_d75_prerequisite(project,monkeypatch)
    assert observed['route']=='REFUSED_BEFORE_ADAPTER',observed
    assert observed['reason']


def test_normal_frontdoor_legacy_valid_route_is_unchanged(tmp_path,monkeypatch):
    from test_flow109_package_ready import _project
    observed=_normal_d75_prerequisite(_project(tmp_path),monkeypatch)
    assert observed['route']=='ADAPTER_EXECUTED',observed
    assert observed['rc']==0 and observed['result']['component_status']=='PASS'


def test_normal_frontdoor_current_bad_pad_remains_measured_fail(tmp_path,monkeypatch):
    from test_flow109_package_ready import _by_name
    project,authority=_current_frontdoor_case(tmp_path,monkeypatch)
    authority['def'].write_text(authority['def'].read_text().replace(
        '+ PLACED ( 1820000 640000 ) N ;','+ PLACED ( 1000000 640000 ) N ;'))
    authority['rebind']()
    observed=_normal_d75_prerequisite(project,monkeypatch)
    assert observed['route']=='ADAPTER_EXECUTED',observed
    assert observed['rc']==1 and observed['result']['component_status']=='FAIL'
    assert _by_name(observed['result'],'current_native_geometry_authority')['status']=='PASS'
    assert _by_name(observed['result'],'pad_bterm_coincidence_check')['status']=='FAIL'
