"""Select retained qualified components only in their dedicated test modules.

The production registry routes analog steps through ``analog_native_flow``.
These older component controls still exercise the general front door and its
qualification refusals, using a temporary registry with the original adapter
contracts. Canonical native-route tests use the unchanged production registry.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

import flow109


_LEGACY_COMPONENTS = {
    'A01': ('flow109_analog', 'structured_analog_spec_binding', {
        'python3': ['analog_a1_spec_emit', 'analog_a1_spec_extract_check']}),
    'A02': ('flow109_analog_a02', 'declared_analog_model_device_smoke', {
        'ngspice': ['pdk_analog_completeness_check', 'ngspice_model_device_smoke',
                    'flow109_analog_model_check']}),
    'A04': ('flow109_analog_a04', 'source_authorized_analog_topology', {
        'python3': ['analog_a2_topology_emit', 'analog_a2_topology_select_check']}),
    'A05': ('flow109_analog_a05', 'expert_sized_netlist_native_operating_point', {
        'python3': ['analog_a3_netlist_emit', 'analog_a3_netlist_gen_check'],
        'ngspice': ['ngspice_operating_point']}),
}


@pytest.fixture(autouse=True)
def legacy_component_registry(tmp_path_factory, monkeypatch):
    """Keep context construction and subprocess validation on identical bytes."""
    registry = flow109.load_registry()
    for row in registry['rows']:
        if row['id'] not in _LEGACY_COMPONENTS:
            continue
        adapter, scope, engine_steps = _LEGACY_COMPONENTS[row['id']]
        profile = next(p for p in row['profiles'] if p['id'] == 'default')
        profile['execution_status'] = 'EXISTING_COMPONENT_DISPATCH_NOT_109_ACCEPTANCE'
        profile['dispatch'] = {
            'adapter': adapter,
            'native_step_id': 'A1' if row['id'] == 'A01' else 'flow109.' + row['id'],
            'engine_families': list(engine_steps),
            'engine_executables': {engine: engine for engine in engine_steps},
            'engine_steps': engine_steps,
            'operation_scope': scope,
        }
    path = tmp_path_factory.mktemp('legacy-flow109') / 'flow109.json'
    path.write_text(json.dumps(registry, indent=2))
    monkeypatch.setattr(flow109, 'REGISTRY', path)


def run_legacy_component(project: Path, step_id: str, *, audit_launches=False):
    """Run the real front door with the fixture registry, without admission bypass."""
    driver = '''import json,sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import flow109
flow109.REGISTRY = Path(sys.argv[2])
if sys.argv[3]:
    audit = Path(sys.argv[3])
    def observe(event,args):
        if event == 'subprocess.Popen':
            with audit.open('a') as stream:
                stream.write(json.dumps(str(args))+'\\n')
    sys.addaudithook(observe)
import vibe_ic_one_shot_runner as runner
sys.argv=['vibe_ic_one_shot_runner.py',*sys.argv[4:]]
sys.exit(runner.main())
'''
    return subprocess.run([
        sys.executable, '-c', driver, str(flow109.HERE), str(flow109.REGISTRY),
        str(project / 'launches.jsonl') if audit_launches else '', str(project),
        '--flow', '109', '--flow109-manifest', str(project / 'manifest.json'),
        '--entry-step', step_id, '--exit-step', step_id, '--route', 'ip', '--no-dashboard'],
        capture_output=True, text=True)
