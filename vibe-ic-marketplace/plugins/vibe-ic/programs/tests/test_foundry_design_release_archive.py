"""Read actual release content after relocation, without identity records."""
import json
import shutil

import pytest

pytest.importorskip('librelane')
import foundry_handoff_package_check as checker
import foundry_handoff_pack_gen as generator
import flow_engine as engine
from test_flow_ip_docs_native import native_release


@pytest.mark.parametrize('change,expected', [
    ('none', 0), ('hollow_gds', 1), ('wrong_top', 1), ('missing_document', 2)])
def test_relocated_release_reads_actual_geometry_and_documents(tmp_path, monkeypatch, change, expected):
    project, name, state, _ = native_release(tmp_path, monkeypatch)
    tool = next(row['tool'] for row in engine.read_json(engine.TABLE)['steps']
                if row['name'] == 'design_release')
    result = generator.execute(project, tmp_path / 'step', tool,
        {'delivery_target': 'foundry_handoff'}, state=state,
        config={'DESIGN_NAME': name, 'DEFAULT_CORNER': 'nominal', 'PDK': 'sky130A', 'LIB': {}})
    assert result['exit_code'] == 0
    package = tmp_path / 'relocated'
    shutil.copytree(project / tool['destination'], package)
    if change == 'hollow_gds':
        import klayout.db as k
        k.Layout().write(str(package / (name + '.gds')))
    elif change == 'wrong_top':
        mask = package / 'mask_spec.json'
        body = json.loads(mask.read_text())
        body['design_top'] = 'different_top'
        mask.write_text(json.dumps(body))
    elif change == 'missing_document':
        (package / 'wat_plan.json').unlink()
    assert checker.main([str(project), '--package-dir', str(package)]) == expected
    assert not (package / 'release_manifest.json').exists()
    assert not (package / 'SHA256SUMS').exists()
