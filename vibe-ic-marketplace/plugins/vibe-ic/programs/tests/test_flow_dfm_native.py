import json
from pathlib import Path

import pytest

import dfm_screen_check as dfm
import flow_engine as engine
import flow_native_adapters as adapters


DEF = '''VERSION 5.8 ;
DESIGN unit ;
VIAS 2 ;
- single + VIARULE vr + CUTSIZE 200 200 + ROWCOL 1 1 ;
- dual + VIARULE vr + CUTSIZE 200 200 + ROWCOL 1 2 ;
END VIAS
NETS 1 ;
- signal ( inst A ) + ROUTED met1 ( 0 0 ) {uses} ;
END NETS
'''


def write_def(path, uses):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DEF.format(uses=' '.join(f'{via} ( {index} 0 )' for index, via in enumerate(uses))))
    return path


def run(tmp_path, state):
    return adapters.execute(tmp_path, tmp_path / 'step', {'adapter': 'dfm'},
                            {'delivery_target': 'ip_hardmacro'}, state=state, config={})


@pytest.mark.parametrize('uses,expected', [(['single', 'dual'], .5), (['single'] * 10, 1.0)])
def test_captured_def_is_recounted_without_legacy_layout_or_other_step_results(tmp_path, uses, expected):
    captured = write_def(tmp_path / 'native' / 'routed.def', uses)
    write_def(tmp_path / 'phase3/stage3/pnr/routed.def', ['dual'])
    result = run(tmp_path, {'def': str(captured)})
    assert result['ran'], result
    assert result['metrics']['signal_via_uses'] == len(uses)
    assert result['metrics']['single_cut_fraction'] == expected
    assert engine.evaluate(engine.ToolResult(**result), []) == 'PASS'
    report = next(Path(path) for path in result['reports'] if path.endswith('dfm_screen.json'))
    record = json.loads(report.read_text())
    assert record['via_redundancy']['single_cut_fraction'] == expected
    if expected == 1.0:
        assert record['verdict'] == 'PASS_WITH_ADVISORIES'
        assert record['rc'] == 1
        assert result['metrics']['advisory_count'] > 0


def test_missing_state_def_does_not_discover_an_old_route(tmp_path):
    write_def(tmp_path / 'phase3/stage3/pnr/routed.def', ['dual'])
    result = run(tmp_path, {})
    assert not result['ran']
    assert result['exit_code'] is None
    assert engine.evaluate(engine.ToolResult(**result), []) == 'NOT_MEASURED'


def test_route_with_no_screened_vias_remains_unmeasured(tmp_path):
    captured = write_def(tmp_path / 'native' / 'routed.def', [])
    result = run(tmp_path, {'def': str(captured)})
    assert result['ran']
    assert engine.evaluate(engine.ToolResult(**result), []) == 'NOT_MEASURED'


def test_generated_dfm_row_runs_its_own_background_tool():
    rows = engine.read_json(engine.TABLE)['steps']
    assert rows[93]['name'] == 'final_electrical_analysis'
    assert rows[94]['name'] == 'design_for_manufacturability'
    row = rows[94]
    assert row['tool']['adapter'] == 'dfm'
    assert row['tool']['parallel'] is True
