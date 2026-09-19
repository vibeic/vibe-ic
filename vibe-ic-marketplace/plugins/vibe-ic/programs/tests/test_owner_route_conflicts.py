import json
from test_owner_self_tapeout_catalogue import fixture
import _submission_template as ST
import _tapeout_declaration as TD
import general_precheck as GP
import tapeout_precheck as TP


def test_custom_declaration_cannot_borrow_default_die_absence(tmp_path,monkeypatch):
    p,_,_=fixture(tmp_path)
    doc=json.loads((p/TD.DECLARATION_REL).read_text());doc['answers']['deliverable']='HARDMACRO'
    override=tmp_path/'override.json';override.write_text(json.dumps(doc))
    layout=tmp_path/'unreadable-layout';layout.write_bytes(b'no native layout')
    monkeypatch.setattr(GP._pdkauth,'resolve_volume',lambda *a,**k:(None,'unmeasured',[]))
    monkeypatch.setattr(GP._pdkauth,'layer_table',lambda *a,**k:(None,'unmeasured',[]))
    monkeypatch.setattr(GP._pdkauth,'seal_ring_facility',lambda *a,**k:(None,None,[]))
    seen=[]
    monkeypatch.setattr(GP,'_step_delegate',lambda ev,step,*a,**kw:seen.append(kw['seal_route']))
    GP.evaluate(p,layout=layout,declaration_path=override)
    assert seen and all(r!=TD.ROUTE_IP for r in seen)


def test_stale_ip_marker_does_not_reclassify_owner_die(tmp_path):
    p,_,_=fixture(tmp_path)
    # Private neutral fixture only: a stale marker with no active slot files.
    for path in (p/ST.SLOTS_DIR_REL).glob('*.yaml'):path.unlink()
    (p/ST.NO_TEMPLATE_REL).write_text('stale marker, not an owner declaration')
    assert TP.delivery_route(p)[0]!=TP.ROUTE_IP
