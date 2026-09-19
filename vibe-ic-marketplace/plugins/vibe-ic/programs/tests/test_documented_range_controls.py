import sys,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from _documented_register_ranges import append_documented_ranges
H='| Address | Name | R/W | Width | Description |\n|---|---|---|---|---|\n'
ROW='| 0x30-0x33 | SAMPLE4 ~ SAMPLE7 | W | 16 each | samples |\n'
def test_packed_authority_preserved():
 rows=[{'name':'SAMPLE','array':True,'first_index':4,'count':4,'base_address':48,'stride_bytes':1,'access':'W','width_bits':16,'evidence':'input/docs/registers.md'}];before=copy.deepcopy(rows)
 append_documented_ranges(rows,{'registers.md':H+ROW});assert rows==before

def test_conflicting_access_not_chosen():
 rows=[];append_documented_ranges(rows,{'registers.md':H+ROW+ROW.replace('| W |','| R |')});assert rows==[]

def test_header_column_permutation():
 rows=[];append_documented_ranges(rows,{'registers.md':'| Name | Width | Access | Address | Description |\n|---|---|---|---|---|\n| SAMPLE4 ~ SAMPLE7 | 16 each | W | 0x30-0x33 | samples |\n'})
 assert [(r['name'],r['address_int'],r['access'],r['width_bits']) for r in rows]==[(f'SAMPLE{i}',48+i-4,'W',16) for i in range(4,8)]
