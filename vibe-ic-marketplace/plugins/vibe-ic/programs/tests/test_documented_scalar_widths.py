import json,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import phase1_doc_one_shot_runner as D
HEADER='# Register map\n| Address | Name | R/W | Width | Description |\n|---|---|---|---|---|\n'
@pytest.mark.parametrize('width,expected',[('16',16),('64',64),('unknown',None),('16\nCONFLICT',None)],ids=['explicit16','explicit64','missing_width','contradictory_width'])
def test_scalar_declared_width(tmp_path,width,expected):
 rows='| 0x40 | PAYLOAD | RW | '+width.replace('\nCONFLICT','')+' | Payload word |\n'
 if 'CONFLICT' in width: rows+='| 0x40 | PAYLOAD | RW | 32 | conflicting declaration |\n'
 text=HEADER+rows;docs=tmp_path/'input/docs';docs.mkdir(parents=True);(docs/'registers.md').write_text(text)
 data=json.loads(D.gen_l4_regmap(tmp_path,{'registers.md':text}).path.read_text());row=next(r for r in data['registers'] if r['name']=='PAYLOAD')
 assert row.get('width_bits')==expected
 assert row['address_int']==64 and row['access']=='RW'
 assert all(f.get('bits')=='WHOLE_REG' for f in row.get('fields',[])), 'width capture must not invent field layout'
