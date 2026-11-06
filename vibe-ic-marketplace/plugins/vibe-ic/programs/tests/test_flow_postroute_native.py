import json
import sys
from types import ModuleType, SimpleNamespace

import pytest

import flow_engine as engine


@pytest.mark.parametrize("grt_repair", [False, True])
@pytest.mark.parametrize("changed", [None, 0, 1])
def test_post_route_extraction_uses_repaired_rerouted_state_with_fillers(tmp_path, monkeypatch, grt_repair, changed):
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
        'OpenROAD.RepairDesignPostGRT': transform('repair_grt_design', 'global-routed', 'grt-design-repaired'),
        'OpenROAD.ResizerTimingPostGRT': transform('repair_grt_timing', 'grt-design-repaired', 'grt-timing-repaired'),
        'OpenROAD.DetailedRouting': transform('detail_route',
            'grt-timing-repaired' if grt_repair else 'global-routed', 'detail-routed'),
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
    chain.config = {'RUN_POST_GRT_DESIGN_REPAIR': grt_repair,
                    'RUN_POST_GRT_RESIZER_TIMING': grt_repair}
    chain.owner = SimpleNamespace(config=chain.config, gating_config_vars={
        'OpenROAD.RepairDesignPostGRT': ['RUN_POST_GRT_DESIGN_REPAIR'],
        'OpenROAD.ResizerTimingPostGRT': ['RUN_POST_GRT_RESIZER_TIMING'],
    })
    chain.state = State({'odb': 'routed-with-fillers'})
    monkeypatch.setattr(chain, 'prepare', lambda **kwargs: None)
    row = next(row for row in engine.read_json(engine.TABLE)['steps']
               if row['name'] == 'post_route_timing_repair')
    result = chain.execute(tmp_path / 'step', row['tool'])
    assert result.exit_code == 0
    assert engine.evaluate(result, []) == 'PASS'
    assert events == (['extract_before', 'repair', 'timing'] if changed == 0 else
                     ['extract_before', 'repair', 'place', 'global_route',
                      *(['repair_grt_design', 'repair_grt_timing'] if grt_repair else []),
                      'detail_route', 'fill', 'extract', 'timing'])
    assert [step['name'] for step in result.native_steps] == row['tool']['steps']
    repaired = [step for step in result.native_steps if step['name'] in {
        'OpenROAD.RepairDesignPostGRT', 'OpenROAD.ResizerTimingPostGRT'}]
    assert all(step['ran'] == (grt_repair and changed != 0) for step in repaired)
