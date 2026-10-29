"""D11 config identity/output isolation; SOFTWARE native boundary, no tool run."""
import json
import shutil
from pathlib import Path

import pytest
import flow109
import flow109_metric_acceptance as metrics
import flow109_admission as admission
import librelane_contract as contract
from test_flow109_d11_metric_binding import case, put, ref, accept, context


def test_d11_nullable_config_is_bound_by_immutable_reference(case):
    result = accept(case)
    assert result['status'] == 'PASS', result
    config = case['folders']['Verilator.Lint'] / 'config.json'
    actual = json.loads(config.read_bytes())
    assert actual['MACROS'] is None and actual['VERILOG_INCLUDE_DIRS'] == []
    identity = result['obligations'][0]['identity']['configuration']
    assert identity['resolved_config'] == ref(case['project'], config)
    assert identity['consumed_settings_sha256'] == metrics._sha(
        metrics._json_key(metrics.d11_consumed_settings(actual)).encode())
    assert len(identity['native_policy_sha256']) == 64


@pytest.mark.parametrize('mutation', ['missing', 'changed'])
def test_d11_nullable_config_still_requires_exact_native_file(case, mutation):
    config = case['folders']['Verilator.Lint'] / 'config.json'
    if mutation == 'missing':
        config.unlink()
    else:
        config.write_bytes(config.read_bytes() + b'\nchanged\n')
    result = accept(case)
    assert result['status'] == 'NOT_MEASURED', result
    assert 'METRIC_IDENTITY_INCOMPLETE' not in result['reason'], result


@pytest.mark.parametrize('selected', [True, False], ids=['D11', 'legacy'])
def test_d11_config_and_verdict_use_only_current_namespace(case, monkeypatch, tmp_path, selected):
    """Real producer/config emitter/admission/judge; only native resolution/run isolated.

    The copied native records are the existing explicit SOFTWARE fixture, not
    execution evidence. This control tests output ownership, never tool quality.
    """
    import design_one_shot_runner as design
    p = case['project']
    put(p / 'input/project.json', {'pdk': 'gf180mcuD'})
    # This namespace fixture declares a PDK so the real Phase-2 selector runs.
    # Bind that exact SOFTWARE settings projection through normal admission.
    cfg = json.loads(case['config'].read_bytes());cfg['settings']['PDK'] = 'gf180mcuD'
    put(case['config'], cfg)
    registry = json.loads(case['registry'].read_bytes());record = registry['uses'][0]
    record['identity']['config'] = ref(p, case['config']);put(case['registry'], registry)
    ctx = context(str(case['registry'].relative_to(p)),
        [{**record['identity'], 'qualification_sha256': admission.canonical_sha(record)}])
    old_config = p / 'phase3/librelane/step2/lint_resolved.json'
    old_gate = p / 'reports/phase2/lint/verilator_lint_gate.json'
    old_owner = p / 'reports/orchestrator/phase2_one_shot.json'
    for path in (old_config, old_gate, old_owner):
        put(path, {'protected': str(path.relative_to(p)), 'scope': 'old D09 fixture'})
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in (old_config, old_gate, old_owner)}
    if selected:
        src = json.loads(case['source'].read_bytes())
        src['native_run'] = {'purpose': 'D11.default', 'subject': metrics.d11_subject(p),
                            'qualification_registry': ref(p, case['registry'])}
        put(case['source'], src)
        path = p / 'requirements/base_05/source_file_coverage.json'
        doc = json.loads(path.read_bytes());doc['approval']['source_reference'] = ref(p, case['source']);put(path, doc)
        (p / 'adopted/base_05/lint_execution.json').unlink()
        ctxpath = p / 'context.json';put(ctxpath, ctx)
        monkeypatch.setenv(flow109.CONTEXT_ENV, str(ctxpath))
        attempt = flow109._new_attempt(p, ctx)
        monkeypatch.setenv(flow109.ATTEMPT_ENV, str(attempt))
        expected_base = p / 'phase3/librelane/D11' / attempt.name
    else:
        monkeypatch.delenv(flow109.CONTEXT_ENV, raising=False)
        monkeypatch.delenv(flow109.ATTEMPT_ENV, raising=False)
        expected_base = p / 'phase3/librelane/step2'
    defaults = json.loads((case['folders']['Verilator.Lint'] / 'config.json').read_bytes())
    resolved_paths = []

    def resolve(project, image, source, output, **kwargs):
        # Explicit native-config resolver boundary; use this SOFTWARE fixture's
        # policy/settings, preserving the real emitter's selected top and RTL.
        raw = json.loads(source.read_bytes())
        put(output, {**defaults, **raw})
        resolved_paths.extend((source, output))
        return output

    def chain(project, image, steps, **kwargs):
        namespace = kwargs.get('namespace')
        base = p / 'phase3/librelane' / (namespace or kwargs['lane'])
        result = []
        for i, (sid, config, state) in enumerate(steps, 1):
            folder = base / (f'{i:02d}-' + sid.lower().replace('.', '-'))
            original = case['folders'].get(sid)
            if original is not None:
                if original != folder:
                    shutil.copytree(original, folder)
            else:
                put(folder / 'state_out.json', {})
            result.append(folder)
        return result

    monkeypatch.setattr(contract, 'resolve_step_config', resolve)
    monkeypatch.setattr(contract, 'run_chain', chain)
    monkeypatch.setattr(contract, 'pdk_root_resolution', lambda *a, **k: {'path': str(tmp_path)})
    result = design.step_rtl_lint_tool(p, top_name='neutral', pdk_name='gf180mcuD')
    assert result.status == 'PASS', result
    assert resolved_paths and all(path.parent == expected_base for path in resolved_paths)
    gate = expected_base / 'verilator_lint_gate.json' if selected else old_gate
    assert gate.is_file() and str(gate) in result.output_files
    assert json.loads(gate.read_bytes())['verdict'] == 'PASS'
    assert json.loads((expected_base / 'lint_config.json').read_bytes())['DESIGN_NAME'] == 'neutral'
    assert (old_owner.read_bytes(), old_owner.stat().st_mtime_ns) == before[old_owner]
    if selected:
        assert all((path.read_bytes(), path.stat().st_mtime_ns) == value for path, value in before.items())
        assert result.extras['native_fresh'] is True
        assert all(str(p / 'reports/phase2') not in output for output in result.output_files)
    else:
        assert result.extras['native_fresh'] is False
        assert (old_config.read_bytes(), old_config.stat().st_mtime_ns) != before[old_config]
        assert (old_gate.read_bytes(), old_gate.stat().st_mtime_ns) != before[old_gate]
