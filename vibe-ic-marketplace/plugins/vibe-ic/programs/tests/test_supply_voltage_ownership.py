"""Source-input supply ownership, through extractor and actual L5 producer."""
import json
from pathlib import Path
import pytest
import spec_electrical_extract as electrical
import phase1_doc_one_shot_runner as producer
from _hostpaths import require_repo


def supplies(text):
    return [r for r in electrical.extract(text) if r['kind']=='supply_voltage']


@pytest.mark.parametrize('text,expected',[
 ('Core supply is 1.2 V. Available headroom is 0.6 V. Differential input target is 1.0 V.', [1.2]),
 ('Core supply is 1.8 V; dropout is 0.2 V; reference target is 0.9 V.', [1.8]),
 ('Vref = 0.7 V. VDD = 1.3 V.', [1.3]),
 ('The reference buffer operates from a 3.3 V supply.', [3.3]),
 ('A 1.8 V supply provides 0.3 V headroom.', [1.8]),
 ('VDD range is 1.1–1.3 V at TT. Input amplitude is 0.7 V.', [1.3]),
 ('核心供電為 1.25 V；輸入差動振幅為 0.8 V；電源裕量為 0.2 V。', [1.25]),
 ('VDD = 1.2 V and VDDIO = 1.8 V.', [1.2,1.8]),
 ('| Supply | 1.8 V | nominal |\n| Headroom | 0.6 V | vs supply |', [1.8]),
 ('| Parameter | Value |\n| VDD | 1.2 V |\n| Vin (diff) | 1.0 V relative to VDD |', [1.2]),
 ('| VDD | 1.2 V | headroom 0.6 V |', [1.2]),
 ('| VDD | 1.2 V |\n| Vref | 0.9 V | supply reference target |', [1.2]),
])
def test_supply_values_belong_to_their_own_quantity(text,expected):
    assert [r['value'] for r in supplies(text)]==expected


def test_issue3752_intake_fixture_reaches_actual_l5(tmp_path):
    source=require_repo('vibe-ic-marketplace','plugins','vibe-ic','programs','tests',
        'fixtures','phase1_local','issue3752_supply_ownership','L5_ANALOG_SPEC.md')
    text=source.read_text()
    rows=supplies(text)
    assert {r['value'] for r in rows}=={1.2,1.8},rows
    assert all(r.get('supply_role') and r.get('evidence') for r in rows)


def test_issue3752_normal_l5_supply_values(tmp_path):
    source=require_repo('vibe-ic-marketplace','plugins','vibe-ic','programs','tests',
        'fixtures','phase1_local','issue3752_supply_ownership','L5_ANALOG_SPEC.md')
    text=source.read_text()
    result=producer.gen_l5_adi_spec(tmp_path,{source.name:text})
    actual=json.loads(result.path.read_text())
    supply=[r for r in actual['electrical_specs'] if r.get('parameter')=='supply_voltage']
    assert {float(r['value']) for r in supply}=={1.2,1.8},supply
    assert all(r.get('supply_role') and r.get('evidence') for r in supply)
    (tmp_path/'ACTUAL_SUPPLY_OBSERVATION.json').write_text(json.dumps(supply,indent=2))


@pytest.mark.parametrize('text',[
 'Supply documentation exists. Available headroom is 0.6 V.',
 'VDD is a power pin. Differential input range is 1.0 V.',
 'Supply is required. Reference target is 0.7 V.',
])
def test_normal_l5_does_not_turn_non_rails_into_supplies(tmp_path,text):
    result=producer.gen_l5_adi_spec(tmp_path,{'electrical_spec.md':text})
    actual=json.loads(result.path.read_text())
    assert [r for r in actual['electrical_specs'] if r.get('parameter')=='supply_voltage']==[]


def test_owner_after_numeric_table_field_keeps_role_and_range():
    text=('| Spec | Target | Range | Unit | Note |\n|---|---|---|---|---|\n'
          '| Vout | 1.4 | 1.3–1.5 | V | regulated core supply |\n'
          '| Vin | 2.0 | 1.8–2.2 | V | IOVDD input supply |\n'
          '| Dropout | 0.4 | — | V | headroom vs supply |\n')
    rows=supplies(text)
    assert [r['value'] for r in rows]==[1.4,2.0],rows
    assert [r['range'] for r in rows]==['1.3–1.5','1.8–2.2']


@pytest.mark.parametrize('text,expected', [
    ('Reference target is 0.83 V and core supply is 1.37 V.', [1.37]),
    ('Core supply is 1.37 V and reference target is 0.83 V.', [1.37]),
    ('Reference target is 0.83 V, core supply is 1.37 V.', [1.37]),
    ('Headroom is 0.24 V but core supply is 1.41 V.', [1.41]),
    ('The supply supports 1.31 V and 1.47 V.', [1.31, 1.47]),
    ('Reference target is 0.83 V and the buffer uses a 1.37 V supply.', [1.37]),
])
def test_new_quantity_clause_cannot_borrow_adjacent_owner(tmp_path, text, expected):
    result = producer.gen_l5_adi_spec(tmp_path, {'electrical_spec.md': text})
    actual = json.loads(result.path.read_text())
    rows = [r for r in actual['electrical_specs']
            if r.get('parameter') == 'supply_voltage']
    assert sorted({float(r['value']) for r in rows}) == expected, rows
