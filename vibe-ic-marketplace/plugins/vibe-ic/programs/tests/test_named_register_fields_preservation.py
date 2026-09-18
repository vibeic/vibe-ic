"""Independent-review boundary controls for the named-table producer."""
from pathlib import Path
import sys,copy
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from _named_register_fields import attach_named_fields
TEXT='## CTRL Register(0x08)Bit Fields\n| Bit | Name | Function |\n|---|---|---|\n| 0 | START | start |'
@pytest.mark.parametrize('existing,evidence',[
 ({'fields':[{'bits':'2','field_name':'OLD'}]},'input/docs/L5.md'),
 ({'bits':[{'name':'OLD','bit':2}]},'input/docs/L5.md'),
 ({},'input/docs/OTHER.md'),
],ids=['existing_fields','existing_bits','different_source'])
def test_preserve_authority(existing,evidence):
 row={'name':'CTRL','address_int':8,'evidence':evidence,**existing};before=copy.deepcopy(row)
 attach_named_fields([row],{'L5.md':TEXT})
 assert row==before
