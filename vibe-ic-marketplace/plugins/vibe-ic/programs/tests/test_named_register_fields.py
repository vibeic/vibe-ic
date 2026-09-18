"""Source-bound named bit-table producer regression; no full Phase1 run."""
from pathlib import Path
import sys,json
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import phase1_doc_one_shot_runner as D
import l4_systemrdl_export as R

SUMMARY='''# Register map
| Address | Name | R/W | Description |
|---|---|---|---|
| 0x08 | CTRL | R/W | Control |
| 0x09 | STATUS | R | Status |
'''
def generate(tmp_path,text):
 result=D.gen_l4_regmap(tmp_path,{'L5_register_map.md':text})
 return {r['name']:r for r in json.loads(result.path.read_text())['registers']}
def named(row):
 return {f['field_name']:R._parse_bits(f) for f in row.get('fields',[]) if f.get('field_name')!='WHOLE_REG'}
def block(name='CTRL',addr='0x08',rows='| 0 | START | Start operation |',header='| Bit | Name | Function |'):
 return f'\n## {name} Register({addr})Bit Fields\n\n{header}\n|---|---|---|\n{rows}\n'

@pytest.mark.parametrize('text,expected',[
 (block(),{'START':(0,0)}),
 (block(rows='| 7-4 | MODE | Select mode |'),{'MODE':(7,4)}),
 (block(rows='| MODE | 4:7 | Select mode |',header='| Name | Bits | Description |'),{'MODE':(7,4)}),
 (block(rows='| 0 | START | Start |\n| 1 | DONE | Complete |',header='| Bit | 名稱 | 功能 |'),{'START':(0,0),'DONE':(1,1)}),
],ids=['single','range','permuted_range','bilingual_names'])
def test_named_tables(tmp_path,text,expected):
 rows=generate(tmp_path,SUMMARY+text)
 assert named(rows['CTRL'])==expected
 assert not named(rows['STATUS'])
 assert all(f['access']=='R/W' for f in rows['CTRL']['fields'])

@pytest.mark.parametrize('text',[
 block(name='OTHER'),
 block(addr='0x09'),
 block(rows='| 0-3 | START | a |\n| 2-5 | DONE | b |'),
 block(rows='| 0 | START | a |\n| 1 | START | b |'),
 block()+block(rows='| 1 | START | incompatible |'),
],ids=['unrelated_register','wrong_address','overlap','duplicate_name','conflicting_sections'])
def test_ambiguity_does_not_bind(tmp_path,text):
 rows=generate(tmp_path,SUMMARY+text)
 assert not named(rows['CTRL'])
 assert not named(rows['STATUS'])

def test_original_documented_bits(tmp_path):
 path=Path(__file__).resolve().parents[2]/'tests/phase1_fixtures/named_register_fields_local/L5_register_map.md'
 rows=generate(tmp_path,path.read_text())
 assert named(rows['CTRL'])=={'INIT':(0,0),'NEXT':(1,1),'MODE':(2,2)}
 assert named(rows['STATUS'])=={'READY':(0,0),'VALID':(1,1)}
 assert all(f['access'] in ('R','RO') for f in rows['STATUS']['fields'])
