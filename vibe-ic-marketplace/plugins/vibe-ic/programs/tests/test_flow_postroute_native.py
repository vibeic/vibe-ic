import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

import flow_engine as engine


def test_post_route_extraction_uses_repaired_rerouted_state_with_fillers(tmp_path, monkeypatch):
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
            return {'odb': 'repaired-unrouted'}, {}

    class ExtractBefore(NativeStep):
        def run(self, state):
            events.append('extract_before')
            assert state['odb'] == 'routed-with-fillers'
            return {'spef': 'input-routed-spef'}, {}

    def transform(name, expected, output):
        class Transform(NativeStep):
            def run(self, state):
                assert state['odb'] == expected
                events.append(name)
                return {'odb': output}, {}
        return Transform

    class Extract(NativeStep):
        def run(self, state):
            events.append('extract')
            assert state['odb'] == 'repaired-rerouted-and-refilled'
            return {'spef': f"extracted:{state['odb']}"}, {}

    class Timing(NativeStep):
        def run(self, state):
            assert state['spef'] == f"extracted:{state['odb']}"
            events.append('timing')
            return {}, {'timing__setup__ws': 0}

    registry = {
        'OpenROAD.RCX': Extract, 'OpenROAD.STAPostPNR': Timing,
        'Vibeic.RCXBeforeRepair': ExtractBefore,
        'Vibeic.PostRouteSizing': Repair, 'Vibeic.PostRouteRepair': Repair,
        'OpenROAD.DetailedPlacement': transform('place', 'repaired-unrouted', 'legalized'),
        'OpenROAD.GlobalRouting': transform('global_route', 'legalized', 'global-routed'),
        'OpenROAD.DetailedRouting': transform('detail_route', 'global-routed', 'detail-routed'),
        'OpenROAD.FillInsertion': transform('fill', 'detail-routed', 'repaired-rerouted-and-refilled'),
    }
    steps = ModuleType('librelane.steps')
    steps.Step = SimpleNamespace(factory=SimpleNamespace(get=registry.get))
    steps.StepError = type('StepError', (Exception,), {})
    steps.StepException = type('StepException', (Exception,), {})
    monkeypatch.setitem(sys.modules, 'librelane.steps', steps)

    def load(name):
        pass

    monkeypatch.setattr(engine.importlib, 'import_module', load)
    chain = engine.NativeChain(tmp_path, {'delivery_target': 'ip_hardmacro'})
    chain.owner = SimpleNamespace(config={}, gating_config_vars={})
    chain.state = State({'odb': 'routed-with-fillers'})
    monkeypatch.setattr(chain, 'prepare', lambda **kwargs: None)
    row = next(row for row in engine.read_json(engine.TABLE)['steps']
               if row['name'] == 'post_route_timing_repair')
    result = chain.execute(tmp_path / 'step', row['tool'])
    assert result.exit_code == 0
    assert events == ['extract_before', 'repair', 'place', 'global_route',
                      'detail_route', 'fill', 'extract', 'timing']
    assert [step['name'] for step in result.native_steps] == row['tool']['steps']
