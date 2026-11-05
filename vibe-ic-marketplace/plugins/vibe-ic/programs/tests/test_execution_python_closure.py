"""R6 Python execution closure controls; source/software evidence only."""
from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
from execution_provider_catalog import implementation_closure
from programs.tests.test_execution_dispatcher_binding import arm, controller
from programs.tests import test_execution_backend_f3 as fixtures








@pytest.mark.parametrize('option', ['-B', '-u', '-q', '-O', '-OO', '--'])
def test_interpreter_options_share_one_proven_worker(tmp_path, option):
    original = arm(); component = original.components[0]
    candidate = replace(original, arm_id='option_alias', engine_families=('option_label',),
                        components=(replace(component, argv=(component.argv[0], option, *component.argv[1:])),))
    ctl = controller(original, candidate, fixture_root=tmp_path); root = tmp_path / 'run'
    result = ctl.run(fixtures.context16(tmp_path, native_clock=True), root, 'ultra-mode')
    assert list(result['candidate_statuses'].values()) == ['ELIGIBLE']
    assert len(json.loads((root / 'plan.json').read_text())['arms']) == 1
























def test_nonstandard_script_suffix_preserves_local_import_closure(tmp_path):
    entry = tmp_path / 'entry.script'
    helper = tmp_path / 'helper.py'
    entry.write_text('import helper\n')
    helper.write_text('VALUE = 1\n')
    assert implementation_closure(entry, search=[tmp_path]) == {entry, helper}


def test_installed_native_closure_reports_observed_binding(tmp_path):
    import importlib.util
    native = Path(importlib.util.find_spec('cocotb.simulator').origin).resolve()
    entry = tmp_path / 'entry.py'; entry.write_text('import cocotb.simulator\n')
    try:
        closure = implementation_closure(entry, search=[native.parent.parent])
        actual = 'BOUND' if native in closure else 'UNBOUND'
    except ValueError:
        actual = 'REFUSED'
    assert actual == 'BOUND'
