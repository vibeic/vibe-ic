"""Declared strategy authority through real emitters and handoff consumers.

Native mapping/LEC measurements live in the separate neutral EDA campaign;
receipt-shaped software fixtures here make no native qualification claim.
"""
import json

import pytest
import librelane_contract as LC
import synth_handoff_netlist_check as H
import phase3_one_shot_runner as R
from _ppa.synthesis import STRATEGIES




def emitter_project(tmp_path):
    p = tmp_path / 'project'
    rtl = p / 'phase2/stage1/rtl/top.v'
    rtl.parent.mkdir(parents=True)
    rtl.write_text('module top(input a,output y); assign y=a; endmodule\n')
    return p, rtl


@pytest.mark.parametrize('strategy', STRATEGIES)
def test_declared_strategy_reaches_emitter_and_provenance(tmp_path, strategy):
    p, rtl = emitter_project(tmp_path)
    out = p / 'synth.json'
    before = LC.emit_synthesis_config(p, 'neutral', out, [rtl], [], False)
    assert 'SYNTH_STRATEGY' not in before
    emitted = LC.emit_synthesis_config(p, 'neutral', out, [rtl], [], False)
    assert emitted == {**before, 'SYNTH_STRATEGY': strategy}
    provenance = json.loads(out.with_suffix('.provenance.json').read_text())
    assert provenance['SYNTH_STRATEGY'] == (
        'phase3/librelane_switch.json synthesis_levers.SYNTH_STRATEGY')


@pytest.mark.parametrize('bad', [None, False, 1, 'DELAY 2', [],
    {'SYNTH_STRATEGY': None}, {'SYNTH_STRATEGY': True}, {'SYNTH_STRATEGY': 2},
    {'SYNTH_STRATEGY': ['DELAY 2']}, {'SYNTH_STRATEGY': 'DELAY 9'},
    {'SYNTH_STRATEGY': 'delay 2'}, {'SYNTH_STRATEGY': ' DELAY 2'},
    {'LIB': {'*': ['other.lib']}}, {'CLOCK_PERIOD': 40},
    {'SYNTH_CORNER': 'slow'}, {'SYNTH_ABC_DFF': True},
    {'SYNTH_STRATEGY': 'DELAY 2', 'arbitrary': 1}])
def test_invalid_overlay_cannot_reach_native_config(tmp_path, bad):
    p, rtl = emitter_project(tmp_path)
    with pytest.raises(LC.Refusal, match='LL_SYNTH_LEVER_'):
        LC.emit_synthesis_config(p, 'neutral', p / 'synth.json', [rtl], [], False)


def admit(project, declaration, strategy):
    """Publish a changed neutral receipt-shaped fixture through the real owner."""
    folder = project / 'phase3/librelane/02-yosys-synthesis'
    resolved = project / 'phase3/librelane/synthesis_resolved.json'
    cfg = json.loads(resolved.read_text())
    cfg['SYNTH_STRATEGY'] = strategy
    inp = json.loads((folder / 'input_fingerprint.json').read_text())
    inp['synthesis_levers'] = declaration
    return H.publish_handoff(project, folder, project / 'phase2/stage2/synth/core_synth.v', 'core')
