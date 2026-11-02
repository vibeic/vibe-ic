"""A project's staged models must not hide the declared family's installed kit from die rows."""
import hashlib
import json
from pathlib import Path

import pytest

import analog_a6_native_pv as d42
import analog_hardmacro_gds_emit as d60
import analog_pdk_availability as resolver
import declared_pdk_is_the_pdk_used_check as declared
import flow109_final_extract as d69
import gds_antenna_deck_check as d43
import magic_extract_spice_emit as d47
import pad_ring_gen as d32

DEF_TEXT = """VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN neutral_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 1000 1000 ) ;
PINS 1 ;
 - a + NET a + DIRECTION INPUT ;
END PINS
END DESIGN
"""


def _ref(project, relative, text):
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return {'path': relative, 'sha256': hashlib.sha256(text.encode()).hexdigest()}


def _manifest(project, row, body):
    path = project / 'input/flow109' / (row + '.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))


def _d42(project):
    _manifest(project, 'D42', {'layout': _ref(project, 'cand/neutral_top.gds', 'gds'),
                               'logical_netlist': _ref(project, 'cand/top.spice', '.subckt neutral_top a\n.ends\n'),
                               'top': 'neutral_top'})
    return d42._d42_inputs


def _d43(project):
    _manifest(project, 'D43', {'layout': _ref(project, 'cand/neutral_top.gds', 'gds'), 'top': 'neutral_top'})
    return d43._d43_inputs


def _d47(project):
    _manifest(project, 'D47', {
        'layout': _ref(project, 'cand/neutral_top.mag', 'magic\ntech neutral\n<< end >>\n'),
        'logical_netlist': _ref(project, 'cand/top.spice', '.subckt neutral_top a\nR1 a 0 1\n.ends\n'),
        'top': 'neutral_top', 'require_resistance': False,
        'options': {'cthresh': 0.0, 'rthresh': 0, 'ext2spice_scale_off': True,
                    'extract_style': 'ngspice()', 'extresist': True, 'extresist_threshold_mohm': 0}})
    return d47._d47_inputs


def _d60(project):
    gds = _ref(project, 'cand/child.gds', 'gds')
    (project / 'cand').mkdir(exist_ok=True)
    (project / 'cand/child.mag').write_text('magic\ntech neutral\n<< end >>\n')
    inventory = _ref(project, 'input/inventory.json',
                     json.dumps({'instances': {'u0': {'master': 'child', 'gds': gds}}}))
    _manifest(project, 'D31', {'macro_inventory': inventory})
    _manifest(project, 'D60', {'top': 'neutral_top', 'layout': _ref(
        project, 'cand/neutral_top.mag', 'magic\ntech neutral\nuse child u0\n<< end >>\n')})
    return d60._d60_inputs


def _d32(project):
    _manifest(project, 'D32', {'top': 'neutral_top',
                               'floorplan_def': _ref(project, 'cand/floor.def', DEF_TEXT),
                               'pad_assignment': _ref(project, 'cand/assignment.json', '{}'),
                               'logical_netlist': _ref(project, 'cand/top.spice', '.subckt neutral_top a\n.ends\n')})
    return d32._d32_inputs


ROWS = {'D32': (_d32, 'D32_INSTALLED_PDK_UNAVAILABLE'),
        'D42': (_d42, 'D42_INSTALLED_PDK_UNAVAILABLE'),
        'D43': (_d43, 'D43_INSTALLED_DECLARED_PDK_UNAVAILABLE'),
        'D47': (_d47, 'D47_INSTALLED_TECHNOLOGY_UNAVAILABLE'),
        'D60': (_d60, 'D60_INSTALLED_TECHNOLOGY_UNAVAILABLE')}


@pytest.fixture
def project(tmp_path, monkeypatch):
    project = tmp_path / 'project'
    for relative in ('input/pdk/models/neutral.lib', 'input/pdk/klayout/tech/drc/neutral.drc',
                     'input/pdk/klayout/tech/lvs/neutral.lvs'):
        _ref(project, relative, '* staged\n')
    _ref(project, 'input/project.json', '{}')
    monkeypatch.setattr(declared, 'declared_target', lambda p: ('neutral', 'input/project.json:pdk'))
    return project


def _install_kit(tmp_path, monkeypatch):
    root = tmp_path / 'pdks'
    for relative in ('libs.tech/ngspice/models/neutral.lib', 'libs.tech/klayout/tech/drc/neutral.drc',
                     'libs.tech/klayout/tech/lvs/neutral.lvs', 'libs.tech/magic/neutral.tech',
                     'libs.tech/magic/neutral.magicrc'):
        path = root / 'neutral' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('* installed\n')
    monkeypatch.setattr(resolver, 'local_pdks_root', lambda image=None: str(root))


def test_project_rung_still_owns_project_scoped_resolution(project):
    assert resolver.resolve_pdk('neutral', project=project)['source'] == 'project_custom_pdk'


@pytest.mark.parametrize('row', sorted(ROWS))
def test_staged_models_do_not_refuse_a_row_when_the_declared_kit_is_installed(project, tmp_path, monkeypatch, row):
    build, refusal = ROWS[row]
    _install_kit(tmp_path, monkeypatch)
    reader = build(project)
    try:
        reader(project)
    except (ValueError, KeyError, OSError) as exc:
        assert refusal not in str(exc), exc


@pytest.mark.parametrize('row', sorted(ROWS))
def test_staged_decks_alone_do_not_satisfy_an_installed_kit_row(project, monkeypatch, row):
    build, refusal = ROWS[row]
    monkeypatch.setattr(resolver, 'local_pdks_root', lambda image=None: None)
    reader = build(project)
    with pytest.raises(ValueError, match=refusal):
        reader(project)


def _d69(project, monkeypatch):
    density = d69.density
    gds = _ref(project, 'fill/in.gds', 'gds')
    rules = _ref(project, 'fill/rules.json', '{}')
    filled = _ref(project, 'fill/filled.gds', 'filled')
    report_text = json.dumps({'gds_in': str(project / gds['path']), 'gds_out': str(project / filled['path']),
                              'layers': ['m1']})
    report = _ref(project, 'fill/fill-report.json', report_text)
    producer = _ref(project, 'fill/D62.json', json.dumps({'input_gds': gds, 'rules': rules, 'cell': 'neutral_top'}))
    tool = _ref(project, 'fill/tool', 'tool')
    receipt = _ref(project, 'fill/receipt.json', json.dumps({
        'schema': density.SCHEMA, 'step_id': 'D62', 'geometry_format': 'GDS', 'component_status': 'PASS',
        'native_started': True, 'operation_sources': density._gds_sources(), 'manifest': producer,
        'inputs': {'input_gds': gds, 'rules': rules},
        'outputs': {'filled.gds': filled, 'fill-report.json': report},
        'execution': {'returncode': 0, 'argv': ['--gds', str(project / gds['path']), '--config', str(project / rules['path']),
                                               '--out', str(project / filled['path']), '--report', str(project / report['path'])]},
        'verify_only': {'ok': True}, 'tool': tool, 'engine': tool, 'native_launch': {}}))
    _manifest(project, 'D69', {'schema': d69.SCHEMA, 'top': 'neutral_top', 'final_gds': filled, 'fill_receipt': receipt,
                               'fill_launch': tool,
                               'logical_netlist': _ref(project, 'cand/top.spice', '.subckt neutral_top a\nR1 a 0 1\n.ends\n')})
    import metal_fill_emit
    monkeypatch.setattr(metal_fill_emit, 'verify_only', lambda p, r: {'ok': True})
    monkeypatch.setattr(d69, '_original_launch', lambda *a, **k: None)


def test_d69_reaches_past_the_kit_check_with_an_installed_kit(project, tmp_path, monkeypatch):
    _d69(project, monkeypatch)
    _install_kit(tmp_path, monkeypatch)
    with pytest.raises(Exception) as refused:
        d69._analog_inputs(project.resolve())
    assert 'D69_INSTALLED_MODEL_ABSENT' not in str(refused.value), refused.value


def test_d69_without_an_installed_kit_still_refuses(project, monkeypatch):
    _d69(project, monkeypatch)
    monkeypatch.setattr(resolver, 'local_pdks_root', lambda image=None: None)
    with pytest.raises(d69.AdmissionRefusal) as refused:
        d69._analog_inputs(project.resolve())
    assert 'D69_INSTALLED_MODEL_ABSENT' in str(refused.value.args), refused.value.args
