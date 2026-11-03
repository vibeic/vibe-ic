"""Reuse the executed INPUT scenario when authoring a deadline bench."""
import json
from pathlib import Path

import arith_oracle_tb_gen as arith
import sdf_gate_sim as sgs


def test_deadline_bench_reuses_the_executed_population(tmp_path, monkeypatch):
    plan = {'spec': {'top': 'logical_core'}, 'framing': {'fixed': 'original'},
            'pairs': [[3, 7]], 'observation': {'sample_offset_ns': 4}}
    tb = tmp_path / 'executed.v'
    tb.write_text('executed INPUT scenario')
    monkeypatch.setattr(arith, '_scenario_header', lambda _: json.loads(json.dumps(plan)))
    monkeypatch.setattr(sgs, '_postlayout_output_deadline',
                        lambda *a, **kw: {'sample_offset_ns': 18.949, 'basis': 'native STA required time'})
    emitted = []
    def emit(module, prepared, **kwargs):
        emitted.append(prepared)
        return 'deadline bench'
    monkeypatch.setattr(arith, 'emit_arithmetic_scenario_module', emit)
    record = tmp_path / sgs.CHIP_TOP_RECORD_REL
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({'chip_top_verilog': 'wrapper.v'}))
    (tmp_path / 'wrapper.v').write_text('module physical_chip; endmodule')
    case = {'path': str(tb), 'text': tb.read_text(), 'module': 'scenario'}
    text, observation = sgs._bound_arithmetic_case(tmp_path, case, 'logical_core',
        {'rebound': True, 'dut_module': 'physical_chip'}, [], netlist=tmp_path / 'native.v',
        sdc=tmp_path / 'native.sdc', sdfs=[], sta_step_dir=tmp_path / 'native-sta')
    assert text == 'deadline bench'
    assert emitted[0]['pairs'] == plan['pairs']
    assert emitted[0]['framing'] == plan['framing']
    assert observation['sample_offset_ns'] == 18.949
    assert observation['postlayout_deadline']['basis'] == 'native STA required time'
