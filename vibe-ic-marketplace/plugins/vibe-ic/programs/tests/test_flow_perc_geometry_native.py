import json
from types import SimpleNamespace

import pytest

pytest.importorskip('librelane')
from librelane.state import DesignFormat
from librelane.steps import StepError, StepException

import flow_engine as engine
import flow_ic_checks as checks
import latchup_esd_spacing_check as geometry


def test_geometry_reads_actual_lef_classes_without_receipts(tmp_path):
    lef = tmp_path / 'cells.lef'
    lef.write_text('MACRO logic\n CLASS CORE ;\nEND logic\n')
    (tmp_path / 'config.json').write_text(json.dumps({'CELL_LEFS': [str(lef)]}))
    context = geometry.current_lef_context(tmp_path, tmp_path, tmp_path / 'unit.def')
    assert geometry._checked_lef_roles(context, tmp_path / 'unit.def')['logic'] == 'CORE'
    lef.write_text(lef.read_text().replace('CLASS CORE', 'CLASS PAD'))
    assert geometry._checked_lef_roles(context, tmp_path / 'unit.def')['logic'] == 'PAD'


@pytest.mark.parametrize('change', ['none', 'no_taps', 'unknown_class'])
def test_native_perc_reads_supplied_lefs_and_keeps_geometry_verdicts(tmp_path, change):
    lef = tmp_path / 'cells.lef'
    lef.write_text('MACRO logic\n CLASS CORE ;\nEND logic\n'
                   'MACRO well_tie\n CLASS CORE WELLTAP ;\nEND well_tie\n')
    if change == 'unknown_class':
        lef.write_text(lef.read_text().replace(' CLASS CORE ;', ''))
    rows = [f'- logic_{i} logic + PLACED ( {(i % 20) * 4000} {(i // 20) * 4000} ) N ;'
            for i in range(100)]
    if change != 'no_taps':
        rows += [row.replace('- logic_', '- tie_').replace(' logic +', ' well_tie +')
                 for row in list(rows)]
    physical = tmp_path / 'current.def'
    physical.write_text('VERSION 5.8 ;\nDESIGN unit ;\nUNITS DISTANCE MICRONS 1000 ;\n'
        f'DIEAREA ( 0 0 ) ( 250000 250000 ) ;\nCOMPONENTS {len(rows)} ;\n'
        + '\n'.join(rows) + '\nEND COMPONENTS\nEND DESIGN\n')
    step = SimpleNamespace(config={'CELL_LEFS': [str(lef)], 'WELLTAP_CELL': 'well_tie',
                                   'FP_TAPCELL_DIST': 30}, step_dir=tmp_path)
    row = next(row for row in engine.read_json(engine.TABLE)['steps']
               if row['name'] == 'final_perc_esd_and_latch_up')
    tool = engine.choose_tool(row['tool'], {'ic': True})
    assert 'VibeIC.ElectricalRules' in tool['steps']
    assert 'VibeIC.PercGeometry' in tool['steps']
    if change == 'no_taps':
        with pytest.raises(StepError, match='conclusive'):
            checks.PercGeometry.run(step, {DesignFormat.DEF: str(physical)})
        assert json.loads((tmp_path / 'perc_geometry.json').read_text())['any_conclusive_gap']
    elif change == 'unknown_class':
        with pytest.raises(StepException, match='NOT_MEASURED'):
            checks.PercGeometry.run(step, {DesignFormat.DEF: str(physical)})
    else:
        _, metrics = checks.PercGeometry.run(step, {DesignFormat.DEF: str(physical)})
        assert metrics['perc_conclusive_geometry_gaps'] == 0
        assert metrics['perc_tap_count'] == 100
        assert metrics['perc_logic_count'] == 100
        assert 'final_perc_latchup_errors' not in metrics
        report = json.loads((tmp_path / 'perc_geometry.json').read_text())
        assert report['spacing']['status'] == 'SPACING_OK_NECESSARY_NOT_SUFFICIENT'
        assert report['foundry_data_residual']
