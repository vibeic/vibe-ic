"""SOURCE_ONLY D69/D75 readers and actual completion seam.

Neutral SPEF syntax and the existing bare-die unit fixture are source controls,
not executed extraction receipts, approved models or an IC acceptance claim.
"""
import re
from pathlib import Path

import pytest
import flow109
import flow109_final_extract as extract
import flow109_package_ready as package
import test_flow109_package_ready as package_fixture


def context(row):
    name='Analog IC external trim' if row=='D69' else 'Small digital IC without DFT'
    features=next(p['features'] for p in flow109.load_registry()['reference_profiles'] if p['name']==name)
    return flow109.execution_context(flow109.resolve_plan(features),row,row)


def consume(project,row,component):
    ctx=context(row)
    initial={'step_id':row,'context_sha256':ctx['context_sha256'],'component_status':'NOT_MEASURED',
             'default_row_status':'NOT_MEASURED','completed':False,'whole_flow_acceptance':'NOT_MEASURED','delivery_accepted':False}
    return flow109._selected_step_result(project,ctx,dict(initial,**component),adapter=extract if row=='D69' else package)


@pytest.fixture
def spef(tmp_path):
    path=tmp_path/'final.spef'
    path.write_text('*SPEF "IEEE 1481-1998"\n*DESIGN "unit"\n*C_UNIT 1 PF\n*R_UNIT 1 OHM\n'
                    '*D_NET a 0.2\n*CAP\n1 a 0.1\n2 a b 0.1\n*END\n'
                    '*D_NET b 0.1\n*CAP\n1 b 0.1\n*END\n')
    return path


def values(root,path):
    ref={'path':str(path.relative_to(root)),'sha256':extract._sha(path)}
    if hasattr(extract,'_d69_metric_values'):
        return extract._d69_metric_values(root,{'nom':ref},['a','b'])
    facts=extract.scan_spef(path)
    names=re.findall(r'(?m)^\*D_NET\s+(\S+)',path.read_text())
    failed=(not facts['has_header'] or facts['negative_caps'] or facts['negative_net_totals']
            or set(names)!={'a','b'} or len(names)!=2)
    return {'status':'FAIL' if failed else 'NOT_MEASURED','corners':{'nom':{'facts':facts}}}


def test_final_SPEF_reader_harvests_actual_values_and_units_without_RC_credit(tmp_path,spef):
    observed=values(tmp_path,spef)
    assert observed['status']=='NOT_MEASURED'
    corner=observed['corners']['nom']
    assert corner.get('net_capacitances',[])==[{'net':'a','capacitance':.2},{'net':'b','capacitance':.1}]
    assert corner['capacitance_unit_tokens']==['1 PF']
    assert corner['facts']['coupling_caps']==1 and corner['facts']['grounded_caps']==2


@pytest.mark.parametrize('damage',['negative_cap','negative_total','headerless','missing_required_net'])
def test_actual_final_completion_keeps_native_SPEF_value_failures(tmp_path,spef,monkeypatch,damage):
    text=spef.read_text()
    if damage=='negative_cap':text=text.replace('1 a 0.1','1 a -0.1')
    elif damage=='negative_total':text=text.replace('*D_NET a 0.2','*D_NET a -0.2')
    elif damage=='headerless':text=text.replace('*SPEF "IEEE 1481-1998"\n','')
    else:text=text.replace('*D_NET b 0.1','*D_NET foreign 0.1')
    spef.write_text(text)
    observed=values(tmp_path,spef)
    monkeypatch.setattr(extract,'_d69_metric_observation',lambda *args:observed,raising=False)
    result=consume(tmp_path,'D69',{'component_status':'PASS'})
    assert result['default_row_status']=='FAIL', result
    assert result['completed'] is False


@pytest.mark.parametrize('row',['D69','D75'])
def test_no_native_basis_is_not_empty_population_or_PASS(tmp_path,row):
    result=consume(tmp_path,row,{'component_status':'PASS'})
    assert result['default_row_status']=='NOT_MEASURED' and result['completed'] is False
    assert result['whole_flow_acceptance']=='NOT_MEASURED' and result['delivery_accepted'] is False


@pytest.mark.parametrize('row',['D69','D75'])
def test_prior_failed_obligation_cannot_be_replaced_by_missing_basis(tmp_path,row):
    oid=context(row)['resolved_row']['obligations'][0]['id']
    result=consume(tmp_path,row,{'metric_acceptance':{'status':'FAIL','obligations':[{'id':oid,'status':'FAIL'}]}})
    assert result['default_row_status']=='FAIL',result
    assert any(o['id']==oid and o['status']=='FAIL' for o in result['metric_acceptance']['obligations'])


@pytest.mark.parametrize('check',['pad_side_constraint_check','pad_bterm_coincidence_check','provider_bond_pad_edge',
                                  'package_electrical_feedback','dft_atpg_coverage_check'])
def test_nested_bare_die_native_check_failure_survives_later_missing_input(tmp_path,check):
    result=consume(tmp_path,'D75',{'checks':[{'check':check,'status':'FAIL','detail':'SOURCE_ONLY measured check failure'}]})
    assert result['default_row_status']=='FAIL',result


def test_existing_bare_die_consumers_are_harvested_without_whole_package_credit(tmp_path):
    project=package_fixture._project(tmp_path)
    ctx=package_fixture._context(project)
    component=package.execute(project,ctx)
    assert component['component_status']=='PASS',component
    result=flow109._selected_step_result(project,ctx,component,adapter=package)
    assert result['default_row_status']=='NOT_MEASURED' and result['completed'] is False
    observed=(result.get('metric_acceptance') or {}).get('native_observation') or {}
    assert (observed.get('pad_bterm') or [{}])[0].get('connected_nets',[])==['clk'],result
    assert result['whole_flow_acceptance']=='NOT_MEASURED'


def test_real_bare_die_late_geometry_refusal_keeps_earlier_pad_failure(tmp_path,monkeypatch):
    project=package_fixture._project(tmp_path)
    ctx=package_fixture._context(project)
    monkeypatch.setattr(package.pad_side_constraint_check,'check',lambda *args:{'verdict':'FAIL','source':'SOURCE_ONLY reader edge'})
    (project/'phase3/stage4/gds/chip_top.gds').unlink()
    component=package.execute(project,ctx)
    assert any(c['check']=='pad_side_constraint_check' and c['status']=='FAIL' for c in component['checks'])
    assert component['component_status']=='FAIL',component
    result=flow109._selected_step_result(project,ctx,component,adapter=package)
    assert result['default_row_status']=='FAIL'
