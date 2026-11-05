"""Input-bound access regressions; no whole extraction or downstream EDA."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import phase1_doc_one_shot_runner as D

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



def test_description_range_is_not_address_authority():
 docs={'register.md':'| Address | Name | Access | Description |\n|---|---|---|---|\n| 0x10-0x1f | DATA | W | other window 0x30-0x3f |'}
 rows=D._extract_memmap_range_constants(docs)
 assert {x['access'] for x in rows if x['address_int'] in (48,63)}=={''}
 assert {x['access'] for x in rows if x['address_int'] in (16,31)}=={'WO'}
