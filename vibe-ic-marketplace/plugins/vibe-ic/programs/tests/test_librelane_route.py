import importlib


import importlib.util


import json


import shutil


import subprocess


import sys


import types


from pathlib import Path


from types import SimpleNamespace


import pytest


PROGRAMS = Path(__file__).resolve().parents[1]


sys.path.insert(0, str(PROGRAMS))


sys.path.insert(0, str(PROGRAMS / 'tests'))


contract = importlib.import_module('librelane_contract')


def put(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))
    return path


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _cmds(deck):
    return [ln.strip() for ln in deck.splitlines()
            if ln.strip() and not ln.lstrip().startswith('#')]


def _has(deck, command):
    import re
    pat = re.compile(r'^(?:if \{\[catch \{)?' + re.escape(command) + r'(?:\s|\}|$)')
    return any(pat.match(ln) for ln in _cmds(deck))


def _load_plugin_routing(monkeypatch):
    """`librelane_plugin_vibeic/routing.py` with LibreLane's classes stubbed
    (the image, not this host, has LibreLane)."""
    class _Registry:
        def register(self):
            return lambda cls: cls

    class Step:
        factory = _Registry()

    class OpenROADStep(Step):
        config_vars = []

        def get_script_path(self):
            return self._stock

        def run(self, state_in, **kwargs):
            self.ran = True
            with open(self.config['VIBEIC_NVR_REPORT_PATH'], 'w') as fh:
                fh.write(self._after)
            return {}, {}

    class DetailedRouting(OpenROADStep):
        pass

    class StepError(RuntimeError):
        pass

    mods = {'librelane': types.ModuleType('librelane'),
            'librelane.common': types.ModuleType('librelane.common'),
            'librelane.config': types.ModuleType('librelane.config'),
            'librelane.state': types.ModuleType('librelane.state'),
            'librelane.steps': types.ModuleType('librelane.steps'),
            'librelane.steps.openroad': types.ModuleType('librelane.steps.openroad'),
            'librelane.steps.step': types.ModuleType('librelane.steps.step')}
    mods['librelane.common'].Path = str
    mods['librelane.config'].Variable = lambda *a, **k: (a, k)
    mods['librelane.state'].State = dict
    mods['librelane.steps.openroad'].DetailedRouting = DetailedRouting
    mods['librelane.steps.openroad'].OpenROADStep = OpenROADStep
    for name in ('MetricsUpdate', 'ViewsUpdate'):
        setattr(mods['librelane.steps.step'], name, dict)
    mods['librelane.steps.step'].Step = Step
    mods['librelane.steps.step'].StepError = StepError
    for name, mod in mods.items():
        monkeypatch.setitem(sys.modules, name, mod)
    path = contract.PLUGIN_ROOT / 'librelane_plugin_vibeic' / 'routing.py'
    spec = importlib.util.spec_from_file_location('mig99_plugin_routing', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, StepError


STOCK_DRT = ('set drt_args [list]\n'
             'lappend drt_args -droute_end_iter $::env(DRT_OPT_ITERS)\n'
             'lappend drt_args -or_seed 42\n'
             'lappend drt_args -verbose 1\n'
             'drt_run $i {*}$drt_args\n')


def test_the_seeded_router_changes_exactly_the_seed_line(tmp_path, monkeypatch):
    plugin, StepError = _load_plugin_routing(monkeypatch)
    out = plugin.seeded_script(STOCK_DRT)
    assert out == STOCK_DRT.replace('-or_seed 42', '-or_seed $::env(VIBEIC_DRT_OR_SEED)')
    for bad in (STOCK_DRT.replace('-or_seed 42', '-or_seed 7'), STOCK_DRT + STOCK_DRT):
        with pytest.raises(ValueError, match='seed cannot be located'):
            plugin.seeded_script(bad)
    step = plugin.DetailedRoutingSeeded()
    step._stock = str(write(tmp_path / 'drt.tcl', STOCK_DRT))
    step.step_dir = str(tmp_path / 'step')
    Path(step.step_dir).mkdir()
    assert Path(step.get_script_path()).read_text() == out
    step._stock = str(write(tmp_path / 'other.tcl', 'detailed_route\n'))
    with pytest.raises(StepError):
        step.get_script_path()


def test_the_reroute_step_records_the_routers_count_before_and_after(tmp_path, monkeypatch):
    plugin, _ = _load_plugin_routing(monkeypatch)
    step = plugin.NamedViolationReroute()
    step.step_dir = str(tmp_path / 'step')
    Path(step.step_dir).mkdir()
    step._after = 'violation type: Short\n'
    step.config = {'VIBEIC_NVR_DRC_REPORT': str(write(tmp_path / 'drt.drc',
                                                      'violation type: Short\n' * 3)),
                   'VIBEIC_NVR_REPORT_PATH': str(tmp_path / 'work/routed_router.drc.rpt')}
    _, metrics = step.run({})
    assert metrics == {'vibeic__route__named_reroute__markers_before': 3,
                       'vibeic__route__named_reroute__markers_after': 1}
    assert (Path(step.step_dir) / 'named_viol_after.drc').read_text() == step._after
    tcl = (contract.PLUGIN_ROOT / 'librelane_plugin_vibeic' / 'named_violation_reroute.tcl')
    assert 'source $::env(VIBEIC_NVR_TCL)' in tcl.read_text()
    assert not _has(tcl.read_text(), 'detailed_route')   # the pass lives in the runner only


def test_every_plugin_step_stays_registered():
    init = (contract.PLUGIN_ROOT / 'librelane_plugin_vibeic' / '__init__.py').read_text()
    for name in ('InsertSpareCells', 'GateLevelSim', 'ClockPathDriveSizing', 'IRDropChecker',
                 'TransientIR', 'DetailedRoutingSeeded', 'NamedViolationReroute'):
        assert f'"{name}"' in init


def test_the_flow_gates_are_read_from_the_resolved_config_and_required(tmp_path):
    put(tmp_path / 'flow_gates.json', {'A.x': {'RUN_A': False, 'RUN_B': True},
                                       'B.y': {'RUN_B': True}})
    assert contract.flow_gated_off(tmp_path) == {'A.x': ['RUN_A']}
    with pytest.raises(contract.Refusal, match='LL_FLOW_GATES_UNRESOLVED'):
        contract.flow_gated_off(tmp_path / 'absent')


def test_the_resolver_writes_the_flows_own_gates():
    src = Path(contract.__file__).read_text()
    assert 'getattr(Chip, "gating_config_vars", {})' in src
    assert '"flow_gates.json"' in src
