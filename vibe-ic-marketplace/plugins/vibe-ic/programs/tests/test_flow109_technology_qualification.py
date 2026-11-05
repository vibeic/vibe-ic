"""Native technology resolution, before RTL and without wrapper identities."""
import json
import os
from pathlib import Path

import pytest

ciel = pytest.importorskip('ciel')
import flow109_technology_qualification as technology
import flow_engine


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = Path(os.environ['PDK_ROOT']).resolve()
    variants = [family.default_variant for family in ciel.Family.by_name.values()
                if (root / family.default_variant).is_dir()]
    assert variants, 'A real installed PDK is required.'
    monkeypatch.setenv('VIBEIC_LIBRELANE_PDK_ROOT', str(root))
    monkeypatch.delenv('VIBEIC_EDA_IMAGE', raising=False)
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L19_CONSTRAINTS_PDK.json').write_text(json.dumps({'fields': {'pdk_target': variants[0]}}))
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'top_module': 'neutral'}))
    return tmp_path


def run(project):
    result = technology.execute(project, project / 'technology')
    return result, flow_engine.evaluate(flow_engine.ToolResult(**result), [])


def test_pre_rtl_native_resolution_without_context_or_image(project):
    result, status = run(project)
    assert status == 'PASS', result
    assert {'pdk', 'standard_cell_library', 'default_corner'} <= set(result['metrics'])
    resolved = json.loads((project / 'technology/resolved.json').read_text())
    assert resolved['VERILOG_FILES'] == []
    assert not (project / 'phase3').exists()
    assert not list(project.rglob('*.v'))


@pytest.mark.parametrize('damage', ['missing_library', 'missing_rtl'])
def test_native_configuration_errors_still_fail(project, damage):
    path = project / 'phase3/librelane/config.json'
    path.parent.mkdir(parents=True)
    config = {'meta': {'version': 2}, 'DESIGN_NAME': 'neutral', 'VERILOG_FILES': []}
    if damage == 'missing_library':
        config['EXTRA_LIBS'] = [str(project / 'missing.lib')]
    else:
        config['VERILOG_FILES'] = [str(project / 'missing.v')]
    path.write_text(json.dumps(config))
    result, status = run(project)
    assert status == 'FAIL', result
    assert result['detail']


@pytest.mark.parametrize('unreadable', [False, True])
def test_unavailable_revision_does_not_refuse_native_configuration(project, monkeypatch, unreadable):
    def revision(*args):
        if unreadable:
            raise OSError('Revision metadata is unreadable')
        return None
    monkeypatch.setattr(technology, '_installed_revision', revision)
    result, status = run(project)
    assert status == 'PASS', result
    assert 'installed_pdk_revision' not in result['metrics']


def test_missing_pdk_declaration_is_not_measured(project):
    (project / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json').unlink()
    result, status = run(project)
    assert status == 'NOT_MEASURED'
    assert 'No PDK declared' in result['detail']


def test_native_consumer_resolves_project_relative_sdc(project):
    sdc = project / 'constraints.sdc'
    sdc.write_text('create_clock -period 20 [get_ports clk]\n')
    path = project / 'phase3/librelane/config.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'meta': {'version': 2}, 'DESIGN_NAME': 'neutral',
        'VERILOG_FILES': [], 'PNR_SDC_FILE': 'dir::constraints.sdc', 'SIGNOFF_SDC_FILE': 'dir::constraints.sdc'}))
    result, status = run(project)
    assert status == 'PASS', result
    resolved = json.loads((project / 'technology/resolved.json').read_text())
    assert resolved['PNR_SDC_FILE'] == resolved['SIGNOFF_SDC_FILE'] == str(sdc)
