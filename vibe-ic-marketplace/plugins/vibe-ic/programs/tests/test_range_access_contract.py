"""Input-bound access regressions; no whole extraction or downstream EDA."""
import sys,json
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import phase1_doc_one_shot_runner as D
import l4_systemrdl_export as R

def table(access):
 return '| Address | Name | R/W | Width |\n|---|---|---|---|\n| 0x10-0x1f | DATA0 ~ DATA15 | '+access+' | 32 |\n'

@pytest.mark.parametrize('access,expected',[('W','WO'),('R','RO'),('R/W','RW'),('','')],ids=['write_only','real_read_only','read_write','missing_access'])
def test_range_table_access(access,expected):
 rows=D._extract_memmap_range_constants({'register.md':table(access)})
 assert {x['access'] for x in rows}=={expected}
 assert {x['address_int'] for x in rows}=={16,31}

@pytest.mark.parametrize('docs,expected',[
 ({'a.md':table('W'),'b.md':table('R')},''),
 ({'a.md':'range 0x10-0x1f','b.md':table('W')},'WO'),
 ({'a.md':table('W'),'b.md':table('W')},'WO'),
 ({'a.md':table('W'),'b.md':'| Address | Name | R/W |\n|---|---|---|\n| 0x20-0x27 | OUT | R |'},'WO'),
],ids=['contradiction','later_authority','corroboration','unrelated_range'])
def test_range_binding(docs,expected):
 rows=D._extract_memmap_range_constants(docs)
 assert {x['access'] for x in rows if x['address_int'] in (16,31)}=={expected}

def test_original_input_l4_consumer(tmp_path):
 root=Path(__file__).resolve().parents[2]/'tests/phase1_fixtures/register_contract_local'
 docs={f.name:f.read_text() for f in root.glob('*.md')}
 result=D.gen_l4_regmap(tmp_path,docs)
 l4=json.loads(result.path.read_text());rows=l4['registers']
 for addr in (16,31):
  row=next(x for x in rows if x.get('address_int')==addr)
  assert row['access']=='WO'
  assert all(x['access']=='WO' for x in row['fields'])
  assert R._norm_access(row['access'])=='WO'
 assert next(x for x in rows if x.get('name')=='STATUS')['access'] in ('R','RO')

def test_description_range_is_not_address_authority():
 docs={'register.md':'| Address | Name | Access | Description |\n|---|---|---|---|\n| 0x10-0x1f | DATA | W | other window 0x30-0x3f |'}
 rows=D._extract_memmap_range_constants(docs)
 assert {x['access'] for x in rows if x['address_int'] in (48,63)}=={''}
 assert {x['access'] for x in rows if x['address_int'] in (16,31)}=={'WO'}
