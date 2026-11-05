"""Read existing native DC without claiming a dependency-failure analysis."""
import json

import pytest
import flow_engine as engine
import flow_native_adapters as adapters
import fmeda_fault_injection_coverage as producer


@pytest.mark.parametrize('detected,baseline,status', [(80, True, 'NOT_MEASURED'),
    (79, True, 'FAIL'), (80, False, 'FAIL')])
def test_safety_case_reads_counts_but_does_not_infer_dfa(tmp_path, detected, baseline, status):
    source = producer._report_path(tmp_path, None)
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({'measured': True, 'injected_faults': 80,
        'detected_faults': detected, 'baseline_valid': baseline}))
    original = source.read_bytes()
    row = engine.read_json(engine.TABLE)['steps'][103]
    result = adapters.execute(tmp_path, tmp_path / 'step', row['tool'], {})
    assert result['ran']
    assert result['metrics']['diagnostic_coverage_pct'] == 100 * detected / 80
    assert result['metrics']['dc_floor_pct'] == 99.0
    assert 'redundancy_separation_dfa' not in result['metrics']
    assert source.read_bytes() == original
    checks = engine.measure(row['checks'], result['metrics'], {}, {'requires_functional_safety': True}, tmp_path)
    assert checks[0]['status'] == 'NOT_MEASURED'
    assert engine.evaluate(engine.ToolResult(**result), checks) == status


def test_safety_case_missing_native_report_is_unmeasured(tmp_path):
    row = engine.read_json(engine.TABLE)['steps'][103]
    result = adapters.execute(tmp_path, tmp_path / 'step', row['tool'], {})
    assert not result['ran'] and not result['metrics']
    checks = engine.measure(row['checks'], result['metrics'], {}, {'requires_functional_safety': True}, tmp_path)
    assert engine.evaluate(engine.ToolResult(**result), checks) == 'NOT_MEASURED'
