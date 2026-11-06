"""Synthetic source controls, not native execution or physical qualification."""
import json
import shlex
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _gds_geometry as GEOM
import _tapeout_declaration as TD
import _owner_declared as OD
import general_precheck as GP
import librelane_contract as LC
import _pdk_layer_authority as PA
import test_general_precheck as G
from _default_backend_fixtures import producer, put


def _gds(path, *, text_type=9, text_layer=77, physical=False, text=True):
    boundaries = [(10, 0, G._rect(0, 0, 100000, 80000))]
    if physical:
        boundaries.append((77, 9, G._rect(100, 100, 200, 200)))
    G.write_gds(path, {'chip_top': {'boundaries': boundaries}})
    if text:
        label = (G._rec(0x0C, 0) + G._rec(0x0D, 2, struct.pack('>h', text_layer))
                 + G._rec(0x16, 2, struct.pack('>h', text_type))
                 + G._rec(0x10, 3, G._xy([(5, 5)]))
                 + G._rec(0x19, 6, G._ascii('synthetic library label'))
                 + G._rec(0x11, 0))
        raw = path.read_bytes()
        path.write_bytes(raw[:-8] + label + raw[-8:])
    return path


def _rebind_receipt(folder, fp):
    put(folder / 'input_fingerprint.json', fp)
    hashes = {str(p.relative_to(folder)): LC.digest(p) for p in folder.iterdir()
              if p.is_file() and p.name != 'vibeic_receipt.json'}
    put(folder / 'vibeic_receipt.json', {'input': fp, 'sha256': hashes})




def _cli(project, candidate):
    out = project / 'text-precheck.json'
    rc = GP.main([str(project), '--pdk', 'neutral', '--gds', str(candidate), '--json', str(out)])
    report = json.loads(out.read_text())
    row = next(r for r in report['steps'] if r['step_id'] == 'General.ForbiddenLayers')
    return rc, row


def test_parser_preserves_nonzero_texttype_in_inclusive_layer_accounting(tmp_path):
    path = _gds(tmp_path / 'library.gds', text_type=9)
    layout = GEOM.read_layout(path)
    text = next(el for el in layout.cells['chip_top'].elements if el.kind == 'TEXT')
    assert text.datatype == 9, 'TEXTTYPE was lost before layer-purpose classification'
    assert (77, 9) in GEOM.layers_used(layout)
    assert (77, 0) not in GEOM.layers_used(layout)








def _installed_technology(tmp_path, monkeypatch, authority):
    root = tmp_path / 'installed'
    volume = root / 'neutral_process'
    tech = volume / 'libs.tech/klayout/tech'
    tech.mkdir(parents=True)
    (tech / 'a.lyp').write_text('<layer-properties><properties><source>10/0@1</source>'
                              '</properties></layer-properties>')
    if authority in ('magic', 'magic-input'):
        path = volume / 'libs.tech/magic/process.tech'
        path.parent.mkdir(parents=True)
        path.write_text('cifinput\nstyle native\nlayer WELL_LABEL\ncalma 77 9\nend\n'
                        if authority == 'magic-input' else
                        'cifoutput\nstyle native\ncalma WELL_LABEL 77 9\nend\n')
    elif authority == 'map':
        (tech / 'process.map').write_text('NAME SIGNAL/LABEL 77 9\n')
    elif authority == 'lyp':
        (tech / 'b.lyp').write_text('<layer-properties><properties><source>77/9@1</source>'
                                  '</properties></layer-properties>')
    elif authority == 'library':
        _gds(volume / 'libs.ref/neutral_io/gds/cells.gds')
    monkeypatch.setenv('PDK_ROOT', str(root))
    monkeypatch.delenv('EDA_CONTAINER', raising=False)
    monkeypatch.delenv('VIBEIC_EDA_CONTAINER', raising=False)
    project = G._project(tmp_path, _gds, {
        'deliverable': 'DIE', 'top_cell': 'chip_top'})
    return volume, project


def _installed_precheck(project):
    report = GP.evaluate(project, runner=G._NEVER_RAN, pdk='neutral_process')
    return report, G._step(report, 'General.ForbiddenLayers')


@pytest.mark.parametrize('authority', ['magic', 'magic-input', 'map', 'lyp', 'library'])
def test_installed_pdk_text_purpose_needs_no_design_stream_receipt(tmp_path, monkeypatch, authority):
    _volume, project = _installed_technology(tmp_path, monkeypatch, authority)
    _report, row = _installed_precheck(project)
    assert row.verdict == GP.PASS, row.evidence
    assert row.measured['unmapped_layers'] == []


def test_single_properties_file_consumer_keeps_its_existing_authority(tmp_path, monkeypatch):
    volume, _project = _installed_technology(tmp_path, monkeypatch, 'magic')
    pairs, path, _tried = PA.layer_table(volume)
    assert pairs == {(10, 0)}
    assert Path(path).is_file() and Path(path).suffix == '.lyp'


@pytest.mark.parametrize('fault', ['undeclared', 'design-only', 'design-symlink', 'wrong-purpose',
                                  'physical', 'declared-forbidden', 'corrupt-library'])
def test_installed_pdk_text_authority_does_not_forgive_design_layers(tmp_path, monkeypatch, fault):
    volume, project = _installed_technology(
        tmp_path, monkeypatch, 'none' if fault in ('undeclared', 'design-only', 'design-symlink') else 'library')
    candidate = project / 'phase3/stage4/gds/chip_top.gds'
    if fault == 'design-only':
        _gds(project / 'design-libraries/cells.gds')
    elif fault == 'design-symlink':
        library = volume / 'libs.ref/neutral_io/gds/cells.gds'
        library.parent.mkdir(parents=True)
        library.symlink_to(candidate)
    elif fault == 'wrong-purpose':
        _gds(candidate, text_type=8)
    elif fault == 'physical':
        _gds(candidate, physical=True)
    elif fault == 'declared-forbidden':
        path = project / TD.DECLARATION_REL
        doc = json.loads(path.read_text())
        doc, ignored = TD.merge_answers(doc, {'forbidden_layers': ['77/9']})
        assert not ignored
        path.write_text(json.dumps(doc))
    elif fault == 'corrupt-library':
        path = volume / 'libs.ref/neutral_io/gds/cells.gds'
        path.write_bytes(path.read_bytes()[:-4])
    report, row = _installed_precheck(project)
    assert row.verdict == GP.FAIL, row.evidence
    assert 'General.ForbiddenLayers' in report.failed_steps
    assert row.measured['unmapped_layers'] or fault == 'declared-forbidden'


@pytest.mark.parametrize('reader_type', [PA.ContainerReader, PA.ImageReader])
@pytest.mark.parametrize('unreachable', [False, True])
def test_installed_text_is_read_only_in_the_selected_pdk_environment(
        tmp_path, monkeypatch, reader_type, unreachable):
    import subprocess
    _volume, project = _installed_technology(tmp_path, monkeypatch, 'library')
    scans = []
    def run(_identity, argv):
        if argv[:3] == ['python3', '-c', PA._GDS_TEXT_LAYERS_SCRIPT]:
            scans.append(argv)
            if unreachable:
                return 127, ''
        cp = subprocess.run(argv, capture_output=True, text=True)
        return cp.returncode, cp.stdout
    reader = reader_type('selected-runtime', runner=run)
    monkeypatch.setattr(GP, 'pdk_reader_for', lambda *_: (reader, 'selected test environment'))
    _report, row = _installed_precheck(project)
    assert scans
    assert row.verdict == (GP.FAIL if unreachable else GP.PASS), row.evidence


def test_installed_library_drawing_is_not_a_text_declaration(tmp_path, monkeypatch):
    from _hostpaths import require_repo
    source = require_repo('vibe-ic-marketplace', 'plugins', 'vibe-ic', 'programs',
                          'tests', 'fixtures', 'density_fill', 'filled.gds')
    geometry = GEOM.read_layout(source)
    markers, label_layer, _why, _tried = PA.flow_marker_layers()
    layer, purpose = next(pair for pair in GEOM.layers_used(geometry)
                          if pair != (10, 0) and not PA.is_flow_marker(*pair, markers, label_layer))
    assert not any(el.kind == 'TEXT' and (el.layer, el.datatype) == (layer, purpose)
                   for cell in geometry.cells.values() for el in cell.elements)
    volume, project = _installed_technology(tmp_path, monkeypatch, 'none')
    library = volume / 'libs.ref/neutral_cells/gds/cells.gds'
    library.parent.mkdir(parents=True)
    library.write_bytes(source.read_bytes())
    _gds(project / 'phase3/stage4/gds/chip_top.gds', text_layer=layer, text_type=purpose)
    _report, row = _installed_precheck(project)
    assert row.verdict == GP.FAIL, row.evidence
