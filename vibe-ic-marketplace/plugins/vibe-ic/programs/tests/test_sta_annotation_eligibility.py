from pathlib import Path
import pytest
from test_declared_process_sta_producer import scene,p3

@pytest.fixture
def case(scene,monkeypatch):
 s=scene;state={'kind':'pg'}
 # Neutral explicit DEF net authority; no design-specific names.
 def setup(kind):
  state['kind']=kind
  use='POWER' if kind in ('pg','pg_conflict') else 'SIGNAL'
  nets='- rail ( core_inst P ) + USE '+use+' ;\n'
  if kind=='unconnected':nets=''
  if kind=='pg_conflict':nets+='- other ( core_inst P ) + USE SIGNAL ;\n'
  count=0 if not nets else 2 if kind=='pg_conflict' else 1
  (s['pnr']/'dut.def').write_text(f'VERSION 5.8 ;\nDESIGN dut ;\nNETS {count} ;\n{nets}END NETS\nEND DESIGN\n')
 def run(container,cmd,**kw):
  import re
  t=Path(kw['marker']).read_text();s['calls'].append(t);c=re.search(r'process=(\w+)',t)[1]
  body=f'=== SETUP corner: process={c} ===\nSTA_LINK_INSTANCE core_inst library/core\nSTA_LINK_CENSUS total=1 linked=1 missing=0\n'
  if state['kind']=='unconnected':body+='STA_UNCONNECTED_OUTPUT core_inst/P\n'
  body+='Found 1 unannotated drivers.\n core_inst/P\nFound 0 partially unannotated drivers.\nworst slack max 1\ntns max 0\n'
  body+=f'=== HOLD corner: process={c} ===\nworst slack min 1\ntns min 0\n'
  out=Path(kw['outputs'][0]);out.parent.mkdir(parents=True,exist_ok=True)
  with out.open('w' if len(s['calls'])==1 else 'a') as f:f.write(body)
  return 0,'',''
 monkeypatch.setattr(p3,'_docker_exec',run)
 return s,setup

@pytest.mark.parametrize('kind',['pg','unconnected'])
def test_typed_non_signal_missing_annotation_is_accounted(case,kind):
 s,setup=case;setup(kind);assert s['emit']()
 assert 'Found 1 unannotated drivers.' in s['rpt'].read_text()

@pytest.mark.parametrize('kind',['signal','pg_conflict'])
def test_connected_signal_or_conflicting_pg_still_refused(case,kind):
 s,setup=case;setup(kind);assert not s['emit']();assert not s['rpt'].exists()

def test_absent_def_does_not_invent_exemption(case):
 s,setup=case;setup('pg');(s['pnr']/'dut.def').unlink();assert not s['emit']()
