"""Additional owning consumer controls; no native tool execution."""
from test_owner_self_tapeout_catalogue import fixture
import _tapeout_declaration as TD
import tapeout_precheck as TP
import general_precheck as GP


def test_cli_slot_keeps_operator_authority(tmp_path):
    p,_,_=fixture(tmp_path)
    assert TP.operator_arm_applicability(p,'gf180mcu',explicit_slot='neutral')[0]==TP.RAN


def test_general_ladder_keeps_die_and_self_route(tmp_path,monkeypatch):
    p,_,_=fixture(tmp_path)
    layout=tmp_path/'unreadable-layout';layout.write_bytes(b'neutral invalid layout; no physical result')
    monkeypatch.setattr(GP._pdkauth,'resolve_volume',lambda *a,**k:(None,'unmeasured',[]))
    monkeypatch.setattr(GP._pdkauth,'layer_table',lambda *a,**k:(None,'unmeasured',[]))
    monkeypatch.setattr(GP._pdkauth,'seal_ring_facility',lambda *a,**k:(None,None,[]))
    seen=[]
    def delegate(ev,step,*a,**kw):seen.append((step.step_id,kw['seal_deliverable'],kw['seal_route']))
    monkeypatch.setattr(GP,'_step_delegate',delegate)
    report=GP.evaluate(p,layout=layout)
    assert seen and all(d=='DIE' and r==TD.ROUTE_SELF_TAPEOUT for _,d,r in seen)
    assert report.verdict!=GP.PASS
    assert report.required_steps==len(GP.LADDER)
