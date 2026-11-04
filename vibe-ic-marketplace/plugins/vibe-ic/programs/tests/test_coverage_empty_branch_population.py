"""Software coverage-counter controls; these do not claim simulator execution."""
import json
from pathlib import Path

import pytest
import flow109
import verilator_coverage_measure as coverage


def report(tmp_path, *, source=None, dut_branch=False, instrumented=True, rtl=None):
    rtl = rtl or tmp_path / 'neutral.sv'
    if source is not None or not rtl.exists():
        rtl.write_text(source or 'module neutral(input a, output y); assign y=a; endmodule\n')
    tb = tmp_path / 'tb.sv'
    tb.write_text('module tb; endmodule\n')
    def point(path, page, line, name, hits):
        blob = f'\x01f\x02{path}\x01l\x02{line}\x01page\x02{page}/neutral\x01o\x02{name}\x01h\x02tb.dut'
        return f"C '{blob}' {hits}\n"
    raw = point(rtl, 'v_line', 1, 'line1', 1)
    raw += point(rtl, 'v_line', 2, 'line2', 1)
    raw += point(rtl, 'v_toggle', 2, 'a:0->1', 1)
    raw += point(rtl, 'v_toggle', 2, 'a:1->0', 1)
    if instrumented:
        raw += point(tb, 'v_branch', 1, 'true', 1)
        raw += point(tb, 'v_branch', 1, 'false', 0)
    if dut_branch:
        raw += point(rtl, 'v_branch', 2, 'true', 0)
    dat = tmp_path / 'coverage.dat'
    dat.write_text(raw)
    parsed = coverage.parse_coverage_dat(str(dat))
    scoped = coverage.scope_totals(parsed, [str(rtl)])
    data = {'tool': 'verilator', 'coverage_dat': str(dat), 'testbench': str(tb),
            'testbenches': [str(tb)], 'measurement_mode': 'measure-tb',
            'rtl_sources': [str(rtl)], **scoped}
    path = tmp_path / 'coverage.json'
    path.write_text(json.dumps(data))
    return path, data


def test_checker_names_empty_population_without_inventing_branch_percentage(tmp_path, capsys):
    path, data = report(tmp_path)
    original = path.read_bytes()
    assert coverage.main(['check', '--coverage-json', str(path)]) == 0
    assert 'branch=NOT_APPLICABLE (0/0' in capsys.readouterr().out
    assert data['totals']['branch'] == {'covered': 0, 'total': 0, 'pct': 0.0}
    assert path.read_bytes() == original


@pytest.mark.parametrize('source', [
    'module neutral(input a, output reg y); always @* if(a) y=1; else y=0; endmodule',
    '/*verilator coverage_off*/ module neutral(input a, output y); assign y=a; endmodule',
    '`include "hidden.svh"\nmodule neutral(input a, output y); assign y=a; endmodule',
    'module neutral(input a, output y); assign y=a ? 1 : 0; endmodule',
    'module neutral; string misleading="//"; initial if(1) $finish; endmodule',
])
def test_suppressed_or_unresolved_source_cannot_claim_empty_branches(tmp_path, source):
    path, data = report(tmp_path, source=source)
    assert coverage.measured_empty_branch_population(data) is None
    assert coverage.main(['check', '--coverage-json', str(path)]) == 1


@pytest.mark.parametrize('change', ['uncovered', 'unsupported', 'missing', 'forged', 'incomplete_scope'])
def test_live_counter_proof_is_required_and_real_branch_floor_stays(tmp_path, change):
    path, data = report(tmp_path, dut_branch=change in ('uncovered', 'forged'),
                        instrumented=change != 'unsupported')
    if change == 'missing':
        Path(data['coverage_dat']).unlink()
    elif change == 'forged':
        data['totals']['branch'] = {'covered': 0, 'total': 0, 'pct': 0.0}
        data['branch_applicability'] = {'status': 'NOT_APPLICABLE'}
    elif change == 'incomplete_scope':
        other = tmp_path / 'other.sv'; other.write_text('module other; endmodule')
        data['rtl_sources'].append(str(other))
    path.write_text(json.dumps(data))
    assert coverage.measured_empty_branch_population(data) is None
    assert coverage.main(['check', '--coverage-json', str(path)]) == 1


@pytest.mark.parametrize('category', ['line', 'toggle'])
def test_empty_branch_proof_never_exempts_other_floors(tmp_path, category):
    path, _ = report(tmp_path)
    assert coverage.main(['check', '--coverage-json', str(path), '--min-' + category, '101']) == 1


def test_shared_producer_records_applicability_and_cli_uses_it(tmp_path, monkeypatch):
    path, data = report(tmp_path)
    tb, dat = data['testbench'], data['coverage_dat']
    result = {'dats': [dat], 'cov': coverage.parse_coverage_dat(dat),
              'per_testbench': {tb: {'measured': True, 'coverage_dat': dat}},
              'union_refused': '', 'line_union_cross_check': {'status': 'NOT_MEASURED'},
              'measured': [tb], 'scope_used': data['rtl_sources']}
    assert coverage.suite_payload_fields(result)['branch_applicability']['status'] == 'NOT_APPLICABLE'
    monkeypatch.setattr(coverage, 'measure_suite', lambda *a, **kw: result)
    out = tmp_path / 'measured.json'
    assert coverage.main(['measure-tb', '--rtl', data['rtl_sources'][0],
                          '--tb', tb, '--out', str(out)]) == 0
    emitted = json.loads(out.read_text())
    assert emitted['branch_applicability']['status'] == 'NOT_APPLICABLE'
    assert emitted['totals']['branch'] == {'covered': 0, 'total': 0, 'pct': 0.0}


def test_simulation_reader_uses_same_applicability_and_preserves_functional_fail(tmp_path):
    from test_flow109_retained_frontend import case
    from test_flow109_selection import profile
    _, rtl = case(tmp_path, 'D13')
    path, data = report(tmp_path, rtl=rtl)
    destination = tmp_path / 'reports/phase2/coverage/coverage_verilator.json'
    destination.write_bytes(path.read_bytes())
    context = flow109.execution_context(flow109.resolve_plan(profile()), 'D13', 'D13')
    result = flow109._retained_native_result(tmp_path, context)
    assert result['component_status'] == 'PASS', result
    assert result['native_measurements']['branch_applicability']['status'] == 'NOT_APPLICABLE'
    execution = tmp_path / 'reports/phase2/sim/l10_execution.json'
    native = json.loads(execution.read_text()); native['cases'][0]['verdict'] = 'FAIL'
    execution.write_text(json.dumps(native))
    assert flow109._retained_native_result(tmp_path, context)['component_status'] == 'FAIL'
