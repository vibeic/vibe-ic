"""D11 config identity/output isolation; SOFTWARE native boundary, no tool run."""

import pytest
import librelane_contract as contract
from test_flow109_d11_metric_binding import case, accept


def test_d11_explicit_lint_top_precedes_l9_top(monkeypatch, tmp_path):
    import design_one_shot_runner as design
    import _rtl_include_hub as hub

    project = tmp_path / 'project'
    rtl = project / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    source = rtl / 'chip_top.sv'
    source.write_text('module chip_top; endmodule\n')
    monkeypatch.setattr(contract, 'selected_mode', lambda *args: 'librelane')
    monkeypatch.setattr(contract, 'phase2_pdk', lambda *args, **kwargs: ('gf180mcuD', 'test'))
    monkeypatch.setattr(contract, 'resolve_image', lambda *args, **kwargs: 'test-image')
    monkeypatch.setattr(design, '_rcvar_l9_top_ports', lambda *args: ('aes', {}))
    monkeypatch.setattr(hub, 'silicon_rtl_selection', lambda *args: [source])
    observed = {}

    class StopAfterConfig(Exception):
        pass

    def capture(project, pdk, output, top, selected, reason, **kwargs):
        observed['top'] = top
        raise StopAfterConfig

    monkeypatch.setattr(contract, 'emit_lint_config', capture)
    with pytest.raises(StopAfterConfig):
        design.step_rtl_lint_tool(project, pdk_name='gf180mcuD',
                                  top_name='chip_top', container='unused')
    assert observed == {'top': 'chip_top'}




@pytest.mark.parametrize('mutation', ['missing', 'changed'])
def test_d11_nullable_config_still_requires_exact_native_file(case, mutation):
    config = case['folders']['Verilator.Lint'] / 'config.json'
    if mutation == 'missing':
        config.unlink()
    else:
        config.write_bytes(config.read_bytes() + b'\nchanged\n')
    result = accept(case)
    assert result['status'] == 'NOT_MEASURED', result
    assert 'METRIC_IDENTITY_INCOMPLETE' not in result['reason'], result
