"""Native frontends consume the already resolved execution top."""
import json
import shutil

import pytest

import execution_policy as execution
import p0_tool_frontend_check as frontend


@pytest.mark.skipif(any(not shutil.which(tool) for tool in ('yosys', 'verilator')),
                    reason='actual native frontends required')
@pytest.mark.parametrize('selection,expected,passed', [
    ('outer_shell', 'outer_shell', True),
    ('missing_selected', 'missing_selected', False),
    (None, 'inner_unit', False),
    ('foreign_project', 'inner_unit', False),
])
def test_native_frontend_uses_current_selected_top(tmp_path, monkeypatch, selection, expected, passed):
    rtl = tmp_path / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    (rtl / 'unit.sv').write_text(
        'module inner_unit #(parameter ENABLE=1)(input a,output y);\n'
        'generate if (ENABLE) UNKNOWN_VARIANT u_missing(); else assign y=a; endgenerate\n'
        'endmodule\n'
        'module outer_shell(input a,output y);inner_unit #(.ENABLE(0)) u_inner(a,y);endmodule\n')
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'top_module': 'inner_unit'}))
    runtime = None if selection is None else {
        'project': tmp_path / 'other' if selection == 'foreign_project' else tmp_path,
        'parameters': {'top': 'outer_shell' if selection == 'foreign_project' else selection}}
    monkeypatch.setattr(execution, '_ordinary_runtime', runtime)
    assert frontend._top(tmp_path) == expected
    result = frontend.check(tmp_path)
    assert result['passed'] is passed, result
    tools = result['tools']
    assert tools['Verilator.Lint']['argv'][tools['Verilator.Lint']['argv'].index('--top-module')+1] == expected
    assert all(tool['exit_code'] == 0 for tool in tools.values()) is passed
