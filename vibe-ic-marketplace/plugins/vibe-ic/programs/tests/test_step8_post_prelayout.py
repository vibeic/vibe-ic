"""Step 8 waits for its tool producer, then consumes current evidence directly."""
import ast
import json
from pathlib import Path

import pytest
import design_one_shot_runner as D
import librelane_contract as LC
import librelane_prelayout as LP
import vibe_ic_one_shot_runner as V


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


def _prelayout_request_project(root, switch):
    put(root / 'phase1/generated_docs/L8_TIMING_WAVEFORM.json', {
        'clock_domains': [{'role': 'primary', 'source_pin': 'neutral_clk', 'period_ns': 20}]})
    put(root / 'phase1/generated_docs/L9_INTEGRATION_SPEC.json', {'top_module': 'neutral_core'})
    put(root / 'phase1/generated_docs/L19_CONSTRAINTS_PDK.json',
        {'fields': {'pdk_target': 'neutral_pdk'}})
    put(root / 'input/submission_template/tapeout_declaration.json', {})
    (root / 'phase3').mkdir(exist_ok=True)
    if switch is not None:
        put(root / 'phase3/librelane_switch.json', switch)
    return root / 'phase3/prelayout.json'


@pytest.mark.parametrize('switch', [None, {}, {'steps': {'8': 'librelane'}}],
                         ids=['no_switch', 'empty_switch', 'other_switch'])
def test_prelayout_io_absence_preserves_core_config(tmp_path, switch):
    output = _prelayout_request_project(tmp_path, switch)
    config = LP.emit_prelayout_config(tmp_path, 'neutral_pdk', 'neutral_core', None, [], output)
    assert config == {'CLOCK_PERIOD': 20, 'CLOCK_PORT': 'neutral_clk',
                      'DESIGN_NAME': 'neutral_core', 'PDK': 'neutral_pdk', 'VERILOG_FILES': []}
    assert json.loads(output.read_text()) == config
    assert not any(name.startswith('PAD_') for name in config)


@pytest.mark.parametrize('section', [
    {'PAD_LIBS': {'*_tt_025C_1v80': ['/pdk/neutral/io_tt.lib']}},
    {'PAD_LIBS': 123}, {'UNSUPPORTED': True}, {}, None, [], False, 0, '',
], ids=['typed_request', 'invalid_pad_type', 'unknown_key', 'empty_object',
        'null', 'list', 'boolean', 'number', 'empty_string'])
def test_prelayout_io_present_request_has_named_refusal(tmp_path, section):
    output = _prelayout_request_project(tmp_path, {'prelayout_io': section})
    try:
        LP.emit_prelayout_config(tmp_path, 'neutral_pdk', 'neutral_core', None, [], output)
    except LC.Refusal as exc:
        observed = exc.code
        assert 'prelayout_io' in str(exc) and 'core' in str(exc)
    else:
        observed = 'CONFIG_EMITTED_WITHOUT_REQUEST_DIAGNOSTIC'
    assert observed == 'LL_PRELAYOUT_IO_UNSUPPORTED'
    assert not output.exists()
    assert not output.with_suffix('.provenance.json').exists()














def test_public_step8_branch_selects_early_not_postprelayout_consumer():
    tree = ast.parse(Path(V.__file__).read_text())
    main = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == '_main')
    branch = next(node for node in ast.walk(main) if isinstance(node, ast.If)
                  and isinstance(node.test, ast.Name)
                  and node.test.id == '_sdc_early_entry')
    calls = {node.func.id for node in ast.walk(branch)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert '_complete_step8_early_preflight' in calls
    assert '_complete_step8_postcheck' not in calls
    source = ast.unparse(main)
    assert "VIBEIC_FLOW109_CONTEXT" in source
    assert '_sdc_early_entry = ' in source and 'and _flow109_owner_entry' in source
    assert '_sdc_postcheck_entry = ' in source and 'not _flow109_owner_entry' in source


def test_flow109_d20_d26_split_keeps_stable_obligations():
    rows = {row['id']: row for row in json.loads(
        (Path(D.__file__).parents[1] / 'flow/flow109.json').read_text())['rows']}
    d20, d26 = rows['D20'], rows['D26']
    assert d20['profiles'][0]['native_steps'] == []
    assert 'early preflight' in d20['profiles'][0]['dispatch']['consumer']
    assert d26['profiles'][0]['native_steps'] == [
        'OpenROAD.CheckSDCFiles', 'OpenROAD.STAPrePNR']
    assert 'step_sdc_validation_post_prelayout' in d26['profiles'][0]['dispatch']['consumer']
    assert [item['id'] for item in d20['obligations']] == [
        'base_11.invalid_timing_exceptions', 'base_11.cdc_exception_reconciliation']
    assert 'base_11.unconstrained_required_paths' in {
        item['id'] for item in d26['obligations']}
