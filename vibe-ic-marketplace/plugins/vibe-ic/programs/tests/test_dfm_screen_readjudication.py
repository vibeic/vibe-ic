from pathlib import Path

import dfm_screen_check as dfm


DEF = '''VERSION 5.8 ;
DESIGN unit ;
NETS 1 ;
- signal ( inst A ) + ROUTED met1 ( 0 0 ) fixed_via ;
END NETS
'''

LEF = '''LAYER cut1
  TYPE CUT ;
END cut1
VIA fixed_via
  LAYER met1 ;
    RECT 0 0 1 1 ;
  LAYER cut1 ;
    RECT 0 0 .2 .2 ;
    RECT .3 0 .5 .2 ;
  LAYER met2 ;
    RECT 0 0 1 1 ;
END fixed_via
'''


def test_explicit_native_inputs_do_not_read_retired_density_records(tmp_path, monkeypatch):
    route = tmp_path / 'native.def'
    route.write_text(DEF)
    lef = tmp_path / 'native.tlef'
    lef.write_text(LEF)

    def unexpected(*args, **kwargs):
        raise AssertionError('Captured native inputs do not use retired run records.')

    monkeypatch.setattr(dfm, '_step34_tool_density', unexpected)
    monkeypatch.setattr(dfm, '_step34_density_in_process', unexpected)
    monkeypatch.setattr(dfm, '_router_via_counts', unexpected)
    monkeypatch.setattr(dfm, '_locate_lef_files', unexpected)
    result = dfm.audit(tmp_path, routed_def=route, tech_lefs=[lef],
                       router_counts={'singlecut': 0, 'multicut': 1})
    assert result['via_redundancy']['signal_via_uses'] == 1
    assert result['via_redundancy']['single_cut_fraction'] == 0
    assert result['via_redundancy']['router_agreement']['verdict'] == 'AGREE'
    assert result['verdict'] == 'PASS'


def test_explicit_missing_def_cannot_be_replaced_by_old_density(tmp_path):
    old = tmp_path / 'reports/density.json'
    old.parent.mkdir()
    old.write_text('{}')
    result = dfm.audit(tmp_path, routed_def=tmp_path / 'absent.def', tech_lefs=[])
    assert result['rc'] == 2
    assert 'captured routed DEF is missing' in result['reason']
