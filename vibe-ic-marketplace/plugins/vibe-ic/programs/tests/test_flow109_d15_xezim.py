"""D15 public owner controls; native replay is explicitly distinct from launch."""
from __future__ import annotations
import json
from _hostpaths import require_repo








OUTPUT = """[UPF] Time: 7, Power domain 'PD_UNIT' is powered down
[UPF] Time: 9, Power domain 'PD_UNIT' is powered up
ok   clamp = 00
ok   retained = a5
Simulation finished at time 10 ($finish called)
"""
















def test_real_registry_keeps_two_obligations_and_predecessors():
    path = require_repo('vibe-ic-marketplace/plugins/vibe-ic/flow/flow109.json')
    row = next(r for r in json.loads(path.read_text())['rows'] if r['id'] == 'D15')
    assert row['acceptance_deps'] == ['D05', 'D09']
    assert {o['metric'] for o in row['obligations']} == {
        'required_power_transitions', 'isolation_retention_behavior_errors'}






# These tests exercise the real completion/qualification consumers, with an
# explicitly SYNTHETIC qualification registry, predecessor rows and transcript.
# They grant no qualification to the preserved native controls or current row.
