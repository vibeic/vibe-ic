import sys,json
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import phase1_doc_one_shot_runner as D
HEADER='| Address | Name | R/W | Width | Description |\n|---|---|---|---|---|\n'
def emit(tmp_path,rows):
 text=HEADER+rows;d=tmp_path/'input/docs';d.mkdir(parents=True);(d/'registers.md').write_text(text)
 return json.loads(D.gen_l4_regmap(tmp_path,{'registers.md':text}).path.read_text())['registers']
def bindings(rows):
 out={}
 for r in rows:
  if r.get('elements'):
   for e in r['elements']:
    name=e.get('name') or e.get('name_raw')
    if name:out[name]=(e.get('address_int',e.get('offset')),e.get('access',r.get('access')),e.get('width_bits',r.get('width_bits')))
  else:out[r.get('name')]=(r.get('address_int'),r.get('access'),r.get('width_bits'))
 return out
@pytest.mark.parametrize('access',['W','R'],ids=['write_bank','read_bank'])
def test_range_semantics(tmp_path,access):
 got=bindings(emit(tmp_path,f'| `0x30-0x33` | `SAMPLE4` ~ `SAMPLE7` | {access} | 16 each | samples |\n'))
 assert {k:got.get(k) for k in ['SAMPLE4','SAMPLE5','SAMPLE6','SAMPLE7']}=={f'SAMPLE{i}':(0x30+i-4,access,16) for i in range(4,8)}
@pytest.mark.parametrize('row',[
 '| `0x30-0x34` | `SAMPLE4` ~ `SAMPLE7` | W | 16 each | mismatched cardinality |\n',
 '| `0x30-0x33` | `SAMPLE4` ~ `OTHER7` | W | 16 each | different stems |\n',
 '| `0x33-0x30` | `SAMPLE4` ~ `SAMPLE7` | W | 16 each | reverse addresses |\n',
 '| `0x30-0x33` | `SAMPLE4` ~ `SAMPLE7` | unknown | 16 each | absent access |\n',
],ids=['count_mismatch','stem_mismatch','reverse','unknown_access'])
def test_no_invented_range(tmp_path,row):
 got=bindings(emit(tmp_path,row));assert not any(x in got for x in ['SAMPLE4','SAMPLE5','SAMPLE6','SAMPLE7'])
