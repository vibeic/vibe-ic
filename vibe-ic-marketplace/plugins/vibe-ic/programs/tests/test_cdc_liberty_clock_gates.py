"""Use the library's clock-gate declaration, keeping data/reset roots separate."""
import json
import sys
from pathlib import Path

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _cdc_netlist as cdc


def model(tmp_path, sense='positive_unate', independent=False):
    library = tmp_path / 'cells.lib'
    library.write_text('''library(test) { cell(neutral_gate) {
      clock_gating_integrated_cell : "latch_posedge";
      pin(C) { direction: input; clock_gate_clock_pin: true; }
      pin(E) { direction: input; clock_gate_enable_pin: true; }
      pin(Z) { direction: output; clock_gate_out_pin: true;
        timing() { related_pin: "C"; timing_sense: "%s"; } }
    } }''' % sense)
    config = tmp_path / 'phase3/librelane/step2/header_resolved.json'
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({'DEFAULT_CORNER': 'nom_tt', 'LIB': {'*_tt': [str(library)]}}))
    cells = {'gate': {'type': 'neutral_gate', 'connections': {'C': [2], 'E': [3], 'Z': [4]}}}
    nl = cdc.Netlist('m', {'clk': ('input', [2]), 'other': ('input', [8])}, cells, {},
        drivers={4: ('gate', 'Z')}, flops=[
            cdc.Flop('launch', '$dff', 2, 1, [3], [5]),
            cdc.Flop('receive', '$dff', 8 if independent else 4, 1, [5], [6])])
    return nl


def test_library_clock_gate_is_related_without_aliasing_data_reset(tmp_path):
    nl = model(tmp_path)
    cdc._load_clock_gates(tmp_path, nl)
    assert nl.domain(nl.flops[0]) == nl.domain(nl.flops[1])
    assert cdc.reg_crossing_findings(nl) == []
    assert nl.root(4) == 4
    assert nl.sample_edge(nl.flops[1]) == 1
    nl.flops[1].clk_pol = 0
    assert nl.sample_edge(nl.flops[1]) == 0


@pytest.mark.parametrize('sense,independent', [('negative_unate', False), ('positive_unate', True)])
def test_unknown_gate_or_independent_clock_remains_crossing(tmp_path, sense, independent):
    nl = model(tmp_path, sense, independent)
    cdc._load_clock_gates(tmp_path, nl)
    assert nl.domain(nl.flops[0]) != nl.domain(nl.flops[1])
    assert any(f['rule'] == 'CDC_REG_NO_SYNC' for f in cdc.reg_crossing_findings(nl))
