"""SOURCE_ONLY D60 reader controls; no stream/qualification receipt fabricated."""
import shutil
import subprocess

import pytest
import analog_hardmacro_gds_emit as owner


@pytest.mark.parametrize('extra_cell', [False, True])
def test_existing_native_hierarchy_reader_uses_independent_source_population(tmp_path, extra_cell):
    if not hasattr(owner, '_d60_metric_readback'):
        pytest.skip('reader absent on exact main')
    tool = shutil.which('klayout');assert tool, 'official EDA image required'
    master, gds, script = tmp_path / 'master.gds', tmp_path / 'stream.gds', tmp_path / 'source_only.py'
    script.write_text('import pya\nl=pya.Layout();l.dbu=0.001\n'
        'm=l.create_cell("neutral_master");m.shapes(l.layer(1,0)).insert(pya.Box(0,0,1000,1000))\n'
        f'l.write({str(master)!r})\nt=l.create_cell("neutral_top");t.insert(pya.CellInstArray(m.cell_index(),pya.Trans()))\n'+
        ('l.create_cell("extra_cell")\n' if extra_cell else '') + f'l.write({str(gds)!r})\n')
    proc = subprocess.run([tool, '-b', '-r', str(script)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = {'top': 'neutral_top', 'cells': {'neutral_top': 'source_top.mag', 'neutral_master': 'source_master.mag'},
            'hierarchy': {'neutral_top': {'neutral_master': 1}, 'neutral_master': {}},
            'instances': {'source_instance': 'neutral_master'}, 'views': {'neutral_master': str(master)}}
    observed = owner._d60_metric_readback(tmp_path, data, gds, {'path': tool})['measurement']
    assert observed['status'] == ('FAIL' if extra_cell else 'PASS'), observed
    if not extra_cell:
        assert observed['cells'] == ['neutral_master', 'neutral_top']
        assert observed['instances'] == {'neutral_master': 1}
    assert not (tmp_path / 'qualifications.json').exists()
