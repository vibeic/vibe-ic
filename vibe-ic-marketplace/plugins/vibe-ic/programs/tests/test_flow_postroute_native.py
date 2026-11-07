import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

import flow_engine as engine


@pytest.mark.parametrize("failure", ["Vibeic.PostRouteSizing", "OpenROAD.DetailedPlacement",
                                    "OpenROAD.DetailedRouting"])
def test_refused_postroute_candidate_retains_every_incoming_view(tmp_path, monkeypatch, failure):
    class State(dict):
        def __init__(self, values, overrides=None, metrics=None):
            super().__init__({**values, **(overrides or {})})
            self.metrics = metrics or {}

        def dumps(self):
            return json.dumps({**self, 'metrics': self.metrics})

    class Refused(Exception):
        pass

    incoming = State({'odb': 'routed.odb', 'def': 'routed.def', 'spef': 'routed.spef',
                      'nl': 'routed.v', 'pnl': 'routed.pnl.v', 'sdf': 'routed.sdf'},
                     metrics={'routing_drc': 0})

    def native_step(name):
        class NativeStep:
            inputs = ['odb']
            outputs = list(incoming)

            def __init__(self, config, state):
                self.state = state

            def run(self, state):
                if name == failure:
                    raise Refused('DPL-0033: candidate refused')
                return {'odb': 'candidate.odb'}, {}

            def start(self, **kwargs):
                views, metrics = self.run(self.state)
                return State({**self.state, **views}, metrics={**self.state.metrics, **metrics})

        return NativeStep

    steps = ModuleType('librelane.steps')
    steps.Step = SimpleNamespace(factory=SimpleNamespace(get=native_step))
    steps.StepError = Refused
    steps.StepException = type('StepException', (Exception,), {})
    monkeypatch.setitem(sys.modules, 'librelane.steps', steps)
    monkeypatch.setattr(engine.importlib, 'import_module', lambda name: None)
    chain = engine.NativeChain(tmp_path, {'delivery_target': 'ip_hardmacro'})
    chain.owner = SimpleNamespace(config={}, gating_config_vars={})
    chain.state = incoming
    monkeypatch.setattr(chain, 'prepare', lambda **kwargs: None)
    row = next(row for row in engine.read_json(engine.TABLE)['steps']
               if row['name'] == 'post_route_timing_repair')
    result = chain.execute(tmp_path / 'repair', row['tool'])
    assert engine.evaluate(result, []) == 'FAIL'
    assert result.exit_code == 1
    assert dict(chain.state) == dict(incoming)
    assert chain.state.metrics == incoming.metrics
    saved = json.loads((tmp_path / 'repair/state_out.json').read_text())
    assert saved == {**incoming, 'metrics': incoming.metrics}


@pytest.mark.parametrize("changed", [None, 0, 1])
def test_post_route_extraction_uses_repaired_rerouted_state_with_fillers(tmp_path, monkeypatch, changed):
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
            return ({'odb': 'repaired-unrouted'} if changed != 0 else {},
                    {'vibeic__postroute__changed': changed} if changed is not None else {})

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
            if changed == 0:
                assert state['odb'] == 'routed-with-fillers'
                assert state['spef'] == 'input-routed-spef'
            else:
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
    assert engine.evaluate(result, []) == 'PASS'
    assert events == (['extract_before', 'repair', 'timing'] if changed == 0 else
                     ['extract_before', 'repair', 'place', 'global_route',
                      'detail_route', 'fill', 'extract', 'timing'])
    assert [step['name'] for step in result.native_steps] == row['tool']['steps']
