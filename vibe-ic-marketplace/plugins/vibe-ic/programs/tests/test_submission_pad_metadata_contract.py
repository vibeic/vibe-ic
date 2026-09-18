"""Typed operator layer inventories are not pad lists; unknown pads still refuse."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import _submission_template as ST
import submission_template_fetch as FETCH
import submission_template_ingest as ING
import submission_template_check as CHK


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
