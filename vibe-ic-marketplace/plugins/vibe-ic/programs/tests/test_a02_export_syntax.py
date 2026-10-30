"""Literal KLayout syntax controls for the existing bounded include copier."""
import pytest
from test_execution_analog_pdk_export import setup_export, call


@pytest.mark.parametrize('layout_source', ['source($input, $topcell)', 'src = source($input, $topcell)', 'source($input)', 'source_class = device.device_class', 'include Neutral::DeviceMethods'])
def test_layout_input_and_preprocessor_dependency_are_distinct(setup_export, layout_source):
    project, pdk, facts, _ = setup_export
    deck = pdk / 'libs.tech/klayout/drc/top.drc'
    deck.parent.mkdir(parents=True)
    child = deck.parent / 'rules.drc'
    child.write_text('layer(1, 0).output("neutral_rule")\n')
    deck.write_text(layout_source + '\n# %include rules.drc\n')
    facts['spice_libs'] = []
    facts['drc_deck'] = '/foss/pdks/sky130A/libs.tech/klayout/drc/top.drc'
    result = call(project, facts)
    assert result['status'] == 'MEASURED', result['not_measured']
    assert len(result['files']) == 2
    assert sorted(row['relative_path'] for row in result['files']) == [
        'libs.tech/klayout/drc/rules.drc', 'libs.tech/klayout/drc/top.drc']
