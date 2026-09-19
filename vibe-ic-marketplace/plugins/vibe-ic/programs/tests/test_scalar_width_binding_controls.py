import copy,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from _documented_scalar_widths import attach_documented_scalar_widths as apply
TEXT='| Width | Name | Address |\n|---|---|---|\n| 16 | PAYLOAD | 0x40 |\n'
def row(**kw):
 return dict({'name':'PAYLOAD','address_int':64,'evidence':'input/docs/registers.md','fields':[{'field_name':'ENABLE','bits':'0'}],'access':'RW'},**kw)
def test_existing_typed_width_and_fields_preserved():
 regs=[row(width_bits=64)];before=copy.deepcopy(regs);apply(regs,{'registers.md':TEXT});assert regs==before

def test_source_binding_and_permuted_columns():
 regs=[row()];fields=copy.deepcopy(regs[0]['fields']);apply(regs,{'unrelated.md':TEXT.replace('16','32'),'registers.md':TEXT});assert regs[0]['width_bits']==16 and regs[0]['fields']==fields

def test_address_binding():
 regs=[row(address_int=65)];before=copy.deepcopy(regs);apply(regs,{'registers.md':TEXT});assert regs==before

def test_array_preserved():
 regs=[row(array=True)];before=copy.deepcopy(regs);apply(regs,{'registers.md':TEXT});assert regs==before

def test_no_unframed_or_duplicate_width_header():
 for text in ['PAYLOAD is 16 bits at 0x40', '| Address | Name | Width | Width |\n|---|---|---|---|\n| 0x40 | PAYLOAD | 16 | 32 |\n']:
  regs=[row()];before=copy.deepcopy(regs);apply(regs,{'registers.md':text});assert regs==before
