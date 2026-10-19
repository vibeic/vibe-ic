"""Lint/header must retain the existing full-synthesis frontend selection."""
import json
from pathlib import Path
import shutil

import pytest
import librelane_contract as owner

FIXTURE = Path(__file__).parent / 'fixtures/librelane_lint_frontend'


@pytest.mark.parametrize('files,top,use_slang', [
    (['word_types.sv', 'lane_top.sv'], 'lane_top', True),
    (['plain.v'], 'plain', False),
])
def test_lint_config_carries_selected_reader_to_copied_header(tmp_path, files, top, use_slang):
    rtl = tmp_path / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    selected = []
    for name in files:
        source = rtl / name
        shutil.copyfile(FIXTURE / name, source)
        selected.append(source)
    output = tmp_path / 'lint_config.json'
    result = owner.emit_lint_config(tmp_path, 'sky130A', output, top, selected, 'neutral explicit top')
    assert result.get('USE_SLANG') is use_slang, result
    assert json.loads(output.read_text()) == result
    assert result['VERILOG_FILES'] == [str(path.resolve()) for path in selected]
    header = {**result, 'meta': {'step': 'Yosys.JsonHeader'}}
    assert header['USE_SLANG'] is use_slang
    assert json.loads(output.with_suffix('.provenance.json').read_text())['USE_SLANG']


def test_missing_selected_source_is_still_refused(tmp_path):
    with pytest.raises(owner.Refusal, match='LL_LINT_INPUT_MISSING'):
        owner.emit_lint_config(tmp_path, 'sky130A', tmp_path / 'lint.json',
                               'unknown', [tmp_path / 'missing.sv'], 'explicit missing')
