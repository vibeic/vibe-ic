"""Exact scalar reset authority; independent expected values from input."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import phase1_doc_one_shot_runner as D

@pytest.mark.parametrize('text,expected',[
 ('CTRL reset value = 0x4.', '0x4'),
 ('CTRL power-up value is 8.', '0x8'),
 ('CTRL is cleared by reset.', '0x0'),
 ('CTRL has no documented reset. STATUS default value = 1.', None),
 ('CTRL.MODE default value = 1.', None),
 ('CTRL bit 2 default value = 1.', None),
 ('CTRL default value (MODE = 1, INIT/NEXT = 0).', None),
 ('CTRL reset value = 0x4 or 0x8.', None),
 ('CTRL reset value = 0x4.\nCTRL reset value = 0x8.', None),
 ('CTRL reset value is unspecified.', None),
 ('CTRL is not cleared by reset.', None),
 ('Previously CTRL reset value was 0x1.', None),
 ('| Address | Name | Reset value | Access |\n|---|---|---|---|\n| 0x08 | CTRL | 0x4 | RW |', '0x4'),
 ('| Address | Name | Reset value | Access |\n|---|---|---|---|\n| 0x09 | CTRL | 0x1 | RW |', None),
],ids=['explicit_scalar','power_up','clear_zero','other_register','field_qualified','bit_partial','partial_assignments','alternative','contradiction','unspecified','negated','historical','explicit_table','different_address'])
def test_scalar_binding(text,expected):
 row={'name':'CTRL','address_int':8}
 D._v1_6_503_lift_scalar_reset_from_prose([row],{'L5.md':text})
 assert row.get('reset_value')==expected

def test_preserve_existing_authority():
 row={'name':'CTRL','reset_value':'0x80','reset_value_source':'owner'}
 D._v1_6_503_lift_scalar_reset_from_prose([row],{'L5.md':'CTRL reset value = 0x4.'})
 assert row=={'name':'CTRL','reset_value':'0x80','reset_value_source':'owner'}

def test_source_namespace():
 row={'name':'CTRL','address_int':8,'evidence':'input/docs/own.md'}
 D._v1_6_503_lift_scalar_reset_from_prose([row],{'own.md':'CTRL has no documented scalar reset.','other.md':'CTRL reset value = 0x1.'})
 assert 'reset_value' not in row

def test_original_partial_contract():
 text=(Path(__file__).resolve().parents[2]/'tests/phase1_fixtures/scalar_reset_binding_local/L4_command_protocol.md').read_text()
 row={'name':'CTRL','address_int':8}
 D._v1_6_503_lift_scalar_reset_from_prose([row],{'L4_command_protocol.md':text})
 assert 'reset_value' not in row
