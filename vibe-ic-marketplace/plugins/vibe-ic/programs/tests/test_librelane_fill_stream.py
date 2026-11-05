"""Actual D62 ODB -> native LL stream-out geometry, never GDS hand repair.

Synthetic source inputs and qualification records are developer controls,
not production PDK/fill/finishing qualification. No benchmark inputs are read.
"""
from __future__ import annotations

import pytest
import librelane_fill_stream as stream
from librelane_contract import Refusal


















def test_unknown_native_script_refuses_instead_of_patching_unreviewed_source():
    with pytest.raises(Refusal, match='FILL_STREAM_NATIVE_VERSION_UNSUPPORTED'):
        stream.patched_native_source('print("unreviewed")\n')


@pytest.mark.parametrize('damage', ['transform', 'extra_shape'])
def test_reader_fill_cell_does_not_authorize_changed_position_or_other_geometry(tmp_path, damage):
    import klayout.db as db
    parsed = {'units': 1000, 'top': 'neutral', 'shapes': [{'layer': 'M', 'rect': [1000, 2000, 3000, 4000]}]}
    bare = db.Layout(); bare.dbu = 0.001; bare.create_cell('neutral')
    filled = db.Layout(); filled.dbu = 0.001; top = filled.create_cell('neutral')
    child = filled.create_cell('reader_created_geometry')
    child.shapes(filled.layer(10, 4)).insert(db.Box(1000, 2000, 3000, 4000))
    if damage == 'extra_shape':
        child.shapes(filled.layer(10, 0)).insert(db.Box(0, 0, 100, 100))
    top.insert(db.CellInstArray(child.cell_index(), db.Trans(10, 0) if damage == 'transform' else db.Trans()))
    with pytest.raises(Refusal, match='FILL_STREAM_NATIVE_CELL_TRANSFORM|FILL_STREAM_FILL_GEOMETRY_MISMATCH'):
        stream._native_fill_child(bare, filled, parsed, {'M': [10, 4]})












def test_reviewed_native_clearer_retains_exact_fill_and_rejects_shape_reverse(monkeypatch):
    import ast
    import hashlib
    source = stream.native_script().read_text()
    assert stream.patched_native_source(source) == source
    assert stream.operation_sources()['native/librelane/scripts/klayout/stream_out.py'] == hashlib.sha256(source.encode()).hexdigest()
    tree = ast.parse(source)
    clearer = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'should_clear_cell')
    namespace = {}
    exec(compile(ast.Module(body=[clearer], type_ignores=[]), '<native-clearer>', 'exec'), namespace)
    clear = namespace['should_clear_cell']
    assert not clear('neutral', 'neutral', 0, 0)
    assert not clear('VIA_generated', 'neutral', 0, 1)
    assert not clear('neutral_DEF_FILL', 'neutral', 0, 2)
    assert clear('foreign_DEF_FILL', 'neutral', 0, 3)
    assert clear('ordinary_macro', 'neutral', 0, 4)
    damaged = source.replace('if cell_name == f"{design_name}_DEF_FILL":', 'if False:')
    # Even a mistakenly updated digest must not authorize changed clearing logic.
    monkeypatch.setattr(stream, 'NATIVE_FILL_STREAM_SHA256', hashlib.sha256(damaged.encode()).hexdigest())
    with pytest.raises(Refusal, match='FILL_STREAM_NATIVE_VERSION_UNSUPPORTED'):
        stream.patched_native_source(damaged)
