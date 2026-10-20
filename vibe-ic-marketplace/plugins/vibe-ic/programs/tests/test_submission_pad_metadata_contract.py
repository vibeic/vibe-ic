"""Typed operator layer inventories are not pad lists; unknown pads still refuse."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import _submission_template as ST
import submission_template_fetch as FETCH
import submission_template_ingest as ING
import submission_template_check as CHK
import slot_pad_budget_check as BUDGET
import _tapeout_declaration as TD
import _owner_declared as OD


def _fetched(tmp_path, monkeypatch):
    root=tmp_path/'operator';root.mkdir()
    raw={'constants':{'SEAL_RING_SIZE':10},
         'slots':{'neutral':{'width':800,'height':1000,'div_x':1,'div_y':1}},
         'layers':{'excluded': [50,0], 'marker':[60,5]},
         'must_be_absent':['excluded'],'must_be_present':['marker'],'pad_masks':{}}
    monkeypatch.setattr(FETCH,'_in_image',lambda *args:(0,'VIBEIC_TEMPLATE='+json.dumps(raw),''))
    assert FETCH._adapt_wafer_space(tmp_path,'fixture',SimpleNamespace(entrypoint=('python',),shuttle_id='neutral'),root)[0]==['neutral']
    path=root/'neutral.json';return root,path,json.loads(path.read_text())


@pytest.mark.parametrize('empty',[False,True],ids=['declared-layers','empty-layers'])
def test_typed_layer_inventory_is_not_unread_pad_list(tmp_path,monkeypatch,empty):
    root,path,raw=_fetched(tmp_path,monkeypatch)
    if empty:
        raw['FORBIDDEN_LAYERS']=[];raw['REQUIRED_MARKER_LAYERS']=[]
    record=ST.slot_record(path,raw,root)
    assert CHK.check_slot_pads(record)==[]
    assert record['pads']['lists']==[] and record['pads']['count']==0
    assert {x['key']:x['raw'] for x in record['pads']['non_pad_lists']}=={
        key:raw[key] for key in ['FORBIDDEN_LAYERS','REQUIRED_MARKER_LAYERS']}


def test_actual_adapter_pad_seam_reaches_checker_without_invented_pads(tmp_path,monkeypatch):
    root,path,raw=_fetched(tmp_path,monkeypatch)
    project=tmp_path/'design';project.mkdir()
    assert ING.main([str(project),'--template',str(root),'--slot','neutral'])==0
    assert CHK.main([str(project),'--json',ST.REPORT_REL])==0
    doc=json.loads((project/ST.REPORT_REL).read_text())
    slot=doc['ingest']['slots'][0]
    assert slot['pads']['count']==0 and slot['pads']['lists']==[]
    assert slot['core_area'] is None and json.loads(path.read_text())==raw


@pytest.mark.parametrize('case',['unknown-pad-key','missing-required-pad-list','layer-key-hides-pad-names',
    'missing-layer','missing-datatype','negative-layer','boolean-layer','string-datatype','empty-name','unknown-row-field'])
def test_real_unread_pad_or_malformed_layer_still_refused(tmp_path,monkeypatch,case):
    root,path,raw=_fetched(tmp_path,monkeypatch)
    key='FORBIDDEN_LAYERS'
    if case=='unknown-pad-key':raw['PAD_RING']=['north_pad']
    elif case=='missing-required-pad-list':
        raw['PAD_RING']=['north_pad']
        # No recognized PAD/PADS field supplies this declared required pad.
        assert not any(ST.PAD_LIST_KEY_RE.match(k) for k in raw)
    elif case=='layer-key-hides-pad-names':raw[key]=['north_pad']
    elif case=='missing-layer':raw[key][0].pop('layer')
    elif case=='missing-datatype':raw[key][0].pop('datatype')
    elif case=='negative-layer':raw[key][0]['layer']=-1
    elif case=='boolean-layer':raw[key][0]['layer']=True
    elif case=='string-datatype':raw[key][0]['datatype']='pad'
    elif case=='empty-name':raw[key][0]['name']=''
    elif case=='unknown-row-field':raw[key][0]['pads']=['north_pad']
    refusals=CHK.check_slot_pads(ST.slot_record(path,raw,root))
    assert {r['rule'] for r in refusals}=={'PAD_LIST_UNREAD'}


def test_declared_pad_membership_survives_layer_classification(tmp_path,monkeypatch):
    root,path,raw=_fetched(tmp_path,monkeypatch);raw['PADS']=['north','south']
    record=ST.slot_record(path,raw,root)
    assert record['pads']['lists']==[{'key':'PADS','raw':['north','south'],'count':2}]
    assert record['pads']['count']==2 and CHK.check_slot_pads(record)==[]


def test_catalogue_layer_classification_does_not_choose_operator_slot(tmp_path,monkeypatch):
    root,_,_=_fetched(tmp_path,monkeypatch)
    project=tmp_path/'design';project.mkdir()
    assert ING.main([str(project),'--template',str(root)])==0
    assert CHK.main([str(project),'--json',ST.REPORT_REL])==1
    doc=json.loads((project/ST.REPORT_REL).read_text())
    assert doc['ingest']['declared_slot'] is None
    assert {r['rule'] for r in doc['check']['refusals']}=={'SLOT_NOT_DECLARED'}


def _budget_project(tmp_path, monkeypatch, *, small_ring=False, change=None):
    root, path, raw = _fetched(tmp_path, monkeypatch)
    if change == 'missing-contract':
        raw.pop('_vibeic_pad_contract', None)
    elif change == 'malformed-contract':
        raw['_vibeic_pad_contract'] = {'kind': 'geometry_only'}
    elif change == 'unread-pad-list':
        raw['PAD_RING'] = ['unread_pad']
    elif change == 'explicit-empty-pad-list':
        raw['PADS'] = []
    path.write_text(json.dumps(raw))
    project = tmp_path / 'design'
    project.mkdir()
    assert ING.main([str(project), '--template', str(root), '--slot', 'neutral']) == 0
    declaration, _ = TD.merge_answers(TD.blank_declaration(),
        {'deliverable': 'DIE', 'top_cell': 'widget'})
    OD.attest(declaration)
    (project / TD.DECLARATION_REL).write_text(json.dumps(declaration))
    own = {'operator_template': {'slot': 'neutral'},
           'answers': {'deliverable': 'DIE', 'top_cell': 'widget'}}
    (project / ST.DESIGN_ANSWERS_REL).write_text(json.dumps(OD.attest(own)))
    rtl = project / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    (rtl / 'widget.v').write_text(
        'module widget(input i_clk, input i_rst, output [1:0] o_gpio); endmodule\n')
    docs = project / 'input/docs'
    docs.mkdir()
    gpio = 'o_gpio[0]' if small_ring else 'o_gpio'
    (docs / 'placement.md').write_text(
        '# Interface\n\n## Physical Pad Placement\n\n| side | signals |\n'
        '|---|---|\n| E | `i_clk`, `i_rst` |\n| N | `' + gpio + '` |\n')
    if change == 'stale-source':
        path.write_text(path.read_text() + '\n')
    elif change == 'unselected-slot':
        own['operator_template']['slot'] = 'not_selected'
        (project / ST.DESIGN_ANSWERS_REL).write_text(json.dumps(OD.attest(own)))
    return project, path


def _budget(project):
    report = project / 'budget.json'
    rc = BUDGET.main([str(project), '--top', 'widget', '--json', str(report)])
    return rc, json.loads(report.read_text())


def test_geometry_contract_uses_design_bonding_and_preserves_operator_constraints(tmp_path, monkeypatch):
    project, source = _budget_project(tmp_path, monkeypatch)
    binding = (project / ST.DESIGN_ANSWERS_REL).read_bytes()
    rc, report = _budget(project)
    assert (rc, report['verdict']) == (0, 'FITS'), report
    assert report['own_ring']['bonded_declared_bits'] == 2
    assert report['own_ring']['unbonded_count'] == 0
    assert report['own_ring_arithmetic']['ring_geometric_capacity_pads'] is None
    contract = report['operator_geometry_contract']
    assert contract['slot'] == 'neutral'
    assert contract['source_sha256'] == ST.sha256_file(source)
    assert contract['geometric_fit'] == 'NOT_MEASURED'
    assert contract['die_area']['rect'] == ['0', '0', '800', '1000']
    assert contract['forbidden_layers'] == [{'name': 'excluded', 'layer': 50, 'datatype': 0}]
    assert (project / ST.DESIGN_ANSWERS_REL).read_bytes() == binding


def test_geometry_contract_still_rejects_an_unbonded_real_signal(tmp_path, monkeypatch):
    project, _ = _budget_project(tmp_path, monkeypatch, small_ring=True)
    rc, report = _budget(project)
    assert (rc, report['verdict']) == (1, 'DOES_NOT_FIT'), report
    assert report['own_ring']['unbonded_declared_bits'] == ['o_gpio[1]']


@pytest.mark.parametrize('change', ['missing-contract', 'malformed-contract',
    'unread-pad-list', 'explicit-empty-pad-list', 'stale-source', 'unselected-slot'])
def test_missing_or_conflicting_geometry_authority_cannot_borrow_the_design_ring(
        tmp_path, monkeypatch, change):
    project, _ = _budget_project(tmp_path, monkeypatch, change=change)
    rc, report = _budget(project)
    assert (rc, report['verdict']) == (2, 'UNDECIDED'), report
    assert 'operator_geometry_contract' not in report
