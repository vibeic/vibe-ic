"""Bounded Step 15 state handoff remains portable and canonical."""

from __future__ import annotations


import pytest

















def test_portable_gate_publisher_uses_project_relative_paths(tmp_path):
    import phase3_one_shot_runner as phase3
    project = tmp_path / 'project'; project.mkdir()
    (project / 'phase3/stage3/pnr').mkdir(parents=True)
    report = {'netlist': str(project / 'phase2/stage2/synth/top_synth.v'),
              'sdc': str(project / 'phase3/stage3/pnr/step15.constraint.sdc'),
              'source': str(project / 'phase3/librelane/prelayout/state_out.json'),
              'netlist_sha256': 'a' * 64}
    portable = phase3._portable_prelayout_gate(project, report)
    assert portable['sdc'] == 'phase3/stage3/pnr/step15.constraint.sdc'
    assert not portable['sdc'].startswith('/')
    import librelane_contract as llc
    with pytest.raises(llc.Refusal, match='LL_PRELAYOUT_GATE_PATH_ESCAPE'):
        phase3._portable_prelayout_gate(project, {'sdc': '/outside/constraint.sdc'})
