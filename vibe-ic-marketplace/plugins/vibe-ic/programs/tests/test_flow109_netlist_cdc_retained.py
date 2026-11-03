"""Native-model reuse in the D45 reader; these tests launch no EDA tool."""
import pytest
import flow109_netlist_cdc as d45
from test_flow109_netlist_cdc import _put, _context


@pytest.mark.parametrize('two_domains', [False, True])
def test_reuse_final_native_yosys_model_without_a_d45_manifest(tmp_path, monkeypatch, two_domains):
    ref = _put(tmp_path, 'adopted/final.v', 'module neutral; endmodule\n')
    _put(tmp_path, 'input/flow109/D44.json', {'top': 'neutral', 'adopted_netlist': ref})
    _put(tmp_path, 'reports/flow109/D44/previous/component.json',
         {'inputs': {'/old/project/adopted/final.v': ref['sha256']}})
    cells = {'a': {'type': '$dff', 'parameters': {'WIDTH': 1, 'CLK_POLARITY': 1},
        'port_directions': {'CLK': 'input', 'D': 'input', 'Q': 'output'},
        'connections': {'CLK': [2], 'D': [3], 'Q': [4]}}}
    if two_domains:
        cells['b'] = {'type': '$dff', 'parameters': {'WIDTH': 1, 'CLK_POLARITY': 1},
            'port_directions': {'CLK': 'input', 'D': 'input', 'Q': 'output'},
            'connections': {'CLK': [5], 'D': [4], 'Q': [6]}}
    _put(tmp_path, 'reports/flow109/D44/previous/gate.model.json', {'modules': {'neutral': {
        'attributes': {'top': 1}, 'ports': {'clk': {'direction': 'input', 'bits': [2]},
        'd': {'direction': 'input', 'bits': [3]}, 'q': {'direction': 'output', 'bits': [4]}},
        'netnames': {'clk': {'bits': [2]}, 'clk_b': {'bits': [5]}}, 'cells': cells}}})
    _put(tmp_path, 'phase2/stage2/constraints/functional.sdc', 'create_clock -period 10 [get_ports clk]\n')
    def refuse_prepare(*args):
        raise d45.Refusal('D45_TEST_UNNECESSARY_NATIVE_RUN', 'existing Yosys model')
    monkeypatch.setattr(d45, 'prepare', refuse_prepare)
    result = d45.execute(tmp_path, _context())
    assert result['component_status'] == ('FAIL' if two_domains else 'PASS'), result
    assert result['native_started'] is False
    assert result['native_model_reused'] is True
    assert result['decoded_flop_count'] == (2 if two_domains else 1)
