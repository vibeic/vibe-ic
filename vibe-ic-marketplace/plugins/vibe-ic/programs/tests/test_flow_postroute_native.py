import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

import flow_engine as engine


@pytest.mark.parametrize('changes', [False, True])
def test_post_route_extraction_uses_repaired_state_with_fillers(tmp_path, monkeypatch, changes):
    events = []

    class State(dict):
        def __init__(self, values, metrics=None):
            super().__init__(values)
            self.metrics = metrics or {}

        def dumps(self):
            return json.dumps({**self, 'metrics': self.metrics})

    class NativeStep:
        inputs = outputs = []

        def __init__(self, config, state):
            self.state = state

        def start(self, **kwargs):
            views, metrics = self.run(self.state)
            return State({**self.state, **views}, {**self.state.metrics, **metrics})

    class Repair(NativeStep):
        def run(self, state):
            events.append('repair')
            views = {'odb': 'repaired-and-refilled'} if changes else {}
            return views, {'vibeic__prr__changed': int(changes)}

    class Extract(NativeStep):
        def run(self, state):
            assert events == ['repair']
            events.append('extract')
            expected = 'repaired-and-refilled' if changes else 'routed-with-fillers'
            assert state['odb'] == expected
            return {'spef': f"extracted:{state['odb']}"}, {}

    class Timing(NativeStep):
        def run(self, state):
            assert state['spef'] == f"extracted:{state['odb']}"
            events.append('timing')
            return {}, {'timing__setup__ws': 0}

    registry = {'OpenROAD.RCX': Extract, 'OpenROAD.STAPostPNR': Timing}
    steps = ModuleType('librelane.steps')
    steps.Step = SimpleNamespace(factory=SimpleNamespace(get=registry.get))
    steps.StepError = type('StepError', (Exception,), {})
    steps.StepException = type('StepException', (Exception,), {})
    monkeypatch.setitem(sys.modules, 'librelane.steps', steps)

    def load(name):
        assert name == 'librelane_plugins.librelane_plugin_vibeic.postroute_repair'
        registry['Vibeic.PostRouteRepair'] = Repair

    monkeypatch.setattr(engine.importlib, 'import_module', load)
    chain = engine.NativeChain(tmp_path, {'delivery_target': 'ip_hardmacro'})
    chain.owner = SimpleNamespace(config={}, gating_config_vars={})
    chain.state = State({'odb': 'routed-with-fillers'})
    monkeypatch.setattr(chain, 'prepare', lambda: None)
    row = next(row for row in engine.read_json(engine.TABLE)['steps']
               if row['name'] == 'post_route_timing_repair')
    result = chain.execute(tmp_path / 'step', row['tool'])
    assert result.exit_code == 0
    assert events == ['repair', 'extract', 'timing']
    assert result.metrics['vibeic__prr__changed'] == int(changes)
