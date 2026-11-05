"""Final declaration orchestration; native KLayout is exercised by the real row."""
import json
from pathlib import Path
from types import SimpleNamespace

import tapeout_declaration_gen as declaration


def test_final_gds_uses_published_stream_after_relocation(tmp_path):
    path = tmp_path / 'phase3/stage4/gds/design.gds'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'layout fixture')
    selected = tmp_path / 'phase3/librelane/37-default-promotion.json'
    selected.parent.mkdir(parents=True)
    selected.write_text(json.dumps({'canonical': '/old/project/phase3/stage4/gds/design.gds'}))
    assert declaration.final_gds(tmp_path) == path


def test_measurement_writes_final_declaration_and_preserves_initial_contract(tmp_path, monkeypatch):
    gds = tmp_path / 'design.gds'
    gds.write_bytes(b'layout fixture')
    source = tmp_path / declaration.TD.DECLARATION_REL
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({'answers': {'die_area_um': [0, 0, 200, 200]}}))
    original = source.read_bytes()
    def run(command, **kwargs):
        output = Path(next(arg[4:] for arg in command if arg.startswith('out=')))
        output.write_text(json.dumps({'tool': 'KLayout', 'top_cell': 'actual_top',
                                     'bbox_um': [0, 0, 100, 100], 'polygon_count': 2,
                                     'zero_area_polygon_count': 0}))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(declaration.subprocess, 'run', run)
    record = declaration.measure_final(tmp_path, gds)
    assert record['verdict'] == 'PASS'
    assert record['measurement']['bbox_um'] == [0, 0, 100, 100]
    assert record['declared_contract']['answers']['die_area_um'] == [0, 0, 200, 200]
    assert source.read_bytes() == original
    assert record['gds'] == 'design.gds'
    assert record['exit_code'] == 0
    assert 'gds_sha256' not in record
    assert json.loads((tmp_path / declaration.FINAL_REL).read_text()) == record
