"""Default structural preflight publishes its native outcome without qualification gates."""
import json
import os
from pathlib import Path

import pytest
import flow109
import p0_tool_frontend_check as frontend
import vibe_ic_one_shot_runner as runner
from test_flow109_selection import profile


def selected(root, monkeypatch):
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D10', 'D10')
    path = root / 'context.json'
    path.write_text(json.dumps(context))
    monkeypatch.setenv(flow109.CONTEXT_ENV, str(path))
    monkeypatch.setenv(flow109.ATTEMPT_ENV, str(flow109._new_attempt(root, context)))


@pytest.mark.parametrize('status', ['PASS', 'FAIL', 'NOT_MEASURED'])
def test_default_d10_publishes_native_outcome(tmp_path, monkeypatch, status):
    selected(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, '_d10_p0_native', lambda _: {'status': status})
    result = runner._finish_d10_unimplemented_owner(tmp_path, run_p0=True)
    assert result['verdict'] == status
    terminal = json.loads((Path(os.environ[flow109.ATTEMPT_ENV]) / 'result.json').read_text())
    assert terminal['default_row_status'] == status
    assert terminal['whole_flow_acceptance'] == 'NOT_MEASURED'
    assert terminal['delivery_accepted'] is False
    assert not (tmp_path / 'reports/flow109/default_rows/D11.json').exists()


@pytest.mark.parametrize('tools,expected', [
    ({'Verilator.Lint': {'exit_code': 1}}, 'FAIL'),
    ({'Yosys.JsonHeader': {'exit_code': 0}, 'Verilator.Lint': {'exit_code': 0}}, 'FAIL'),
    ({'Yosys.JsonHeader': {'exit_code': 0}}, 'NOT_MEASURED'),
    ({}, 'NOT_MEASURED'),
])
def test_native_failures_and_incomplete_measurements_stay_distinct(tmp_path, monkeypatch, tools, expected):
    selected(tmp_path, monkeypatch)
    rtl = tmp_path / 'phase2/stage1/rtl'
    rtl.mkdir(parents=True)
    (rtl / 'unit.sv').write_text('module unit(input a, output y); assign y=a; endmodule\n')
    docs = tmp_path / 'phase1/generated_docs'
    docs.mkdir(parents=True)
    (docs / 'L9_INTEGRATION_SPEC.json').write_text(json.dumps({'top_module': 'unit'}))
    tool = tmp_path / 'native-tool'
    tool.write_text('native fixture executable bytes')
    monkeypatch.setattr(runner.shutil, 'which', lambda name: str(tool))
    import librelane_contract as contract
    monkeypatch.delenv(contract.LOCAL_ATTESTATION_ENV, raising=False)
    native = {'passed': False, 'findings': ['native frontend finding'], 'tools': tools}
    monkeypatch.setattr(frontend, 'check', lambda *args, **kwargs: native)
    result = runner._d10_p0_native(tmp_path)
    assert result['status'] == expected, result
    saved = tmp_path / result['producer_result']['path']
    assert json.loads(saved.read_text()) == native
