"""T72: the streamed layout's own antenna and route evidence."""
import json
from pathlib import Path
import phase3_one_shot_runner as R


def test_antenna_gates_consume_only_the_declared_router_report():
    for gates in (R._PRESTREAM_GATES, R._FINAL_LAYOUT_GATES):
        antenna = next(spec for spec in gates if spec[0].startswith("antenna"))
        assert antenna[3] == ("--mode", "antenna", "--under",
                              "reports/phase3/antenna.rpt")
    deck = R._antenna_isolated_scoped_retry_tcl("seed.odb", "candidate.odb", "diode")
    assert "candidate.odb.targets.txt" in deck
    assert ".targets.rpt" not in deck


def test_final_route_census_is_measured_and_bound_to_layout(tmp_path, monkeypatch):
    pnr = R._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text("VERSION 5.8 ;\nNETS 1 ;\nEND NETS\nEND DESIGN\n")
    class Pdk:
        tech_lef = tmp_path / "tech.lef"
        cell_lef = tmp_path / "cells.lef"
        macro_lefs = ()
    for lef in (Pdk.tech_lef, Pdk.cell_lef):
        lef.write_text("VERSION 5.8 ;\n")
    monkeypatch.setattr(R, "_layout_basis", lambda *a: ("current-layout", ""))
    monkeypatch.setattr(R, "_to_container_path", lambda path, container: path)
    calls = []
    def openroad(container, command, **kw):
        calls.append(command)
        deck = (tmp_path / "reports/phase3/prestream_route_census.tcl").read_text()
        assert "read_def " + str(pnr / "routed.def") in deck
        assert "PRESTREAM_UNROUTED_NETS" in deck
        return 0, ("PRESTREAM_UNROUTED_NETS: 0\nPRESTREAM_ABUTTED_NETS: 2\n"
                   "PRESTREAM_UNROUTED_SHAPE_BLIND: 0\n"
                   "PRESTREAM_CENSUS_COMPLETE: 1\n"), ""
    monkeypatch.setattr(R, "_docker_exec", openroad)
    rec, error = R._prestream_route_census(tmp_path, "unit", Pdk(), "eda", "current-layout")
    assert error == ""
    assert rec["unrouted_nets"] == 0 and rec["abutted_nets"] == 2
    assert rec["layout_digest"] == "current-layout"
    assert len(calls) == 1
    saved = json.loads((tmp_path / "reports/phase3/prestream_route_census.json").read_text())
    assert saved == rec


def test_failed_or_stale_route_census_is_never_saved_as_measurement(tmp_path, monkeypatch):
    pnr = R._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text("VERSION 5.8 ;\n")
    class Pdk:
        tech_lef = tmp_path / "tech.lef"
        cell_lef = tmp_path / "cells.lef"
        macro_lefs = ()
    monkeypatch.setattr(R, "_to_container_path", lambda path, container: path)
    monkeypatch.setattr(R, "_layout_basis", lambda *a: ("different-layout", ""))
    monkeypatch.setattr(R, "_docker_exec", lambda *a, **kw: (0,
        "PRESTREAM_UNROUTED_NETS: 0\nPRESTREAM_ABUTTED_NETS: 0\n"
        "PRESTREAM_UNROUTED_SHAPE_BLIND: 0\nPRESTREAM_CENSUS_COMPLETE: 1\n", ""))
    rec, error = R._prestream_route_census(tmp_path, "unit", Pdk(), "eda", "old-layout")
    assert rec is None and "layout changed" in error
    assert not (tmp_path / "reports/phase3/prestream_route_census.json").exists()
    monkeypatch.setattr(R, "_layout_basis", lambda *a: ("old-layout", ""))
    monkeypatch.setattr(R, "_docker_exec", lambda *a, **kw: (1, "", "OpenROAD error"))
    rec, error = R._prestream_route_census(tmp_path, "unit", Pdk(), "eda", "old-layout")
    assert rec is None and "incomplete" in error
    assert not (tmp_path / "reports/phase3/prestream_route_census.json").exists()


def test_prestream_route_row_uses_new_census_instead_of_old_log(tmp_path, monkeypatch):
    import si_mcf_repair
    import si_mcf_verdict_basis
    import drc_feedback_repair
    pnr = R._pl.pnr_dir(tmp_path)
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text("VERSION 5.8 ;\nNETS 1 ;\nEND NETS\nEND DESIGN\n")
    (pnr / "placed.def").write_text("VERSION 5.8 ;\n")
    (pnr / "openroad.log").write_text(
        "[INFO DRT-0198] Complete detail routing\n"
        "[INFO DRT-0199] Number of violations = 0\n")
    class Pdk:
        tech_lef = tmp_path / "tech.lef"
        cell_lef = tmp_path / "cells.lef"
        macro_lefs = ()
        drc_deck = None
    for lef in (Pdk.tech_lef, Pdk.cell_lef):
        lef.write_text("VERSION 5.8 ;\n")
    monkeypatch.setattr(R, "_layout_basis", lambda *a: ("current-layout", ""))
    monkeypatch.setattr(R, "step_canonicalize_artefacts", lambda *a, **kw:
                        R.StepResult("canonicalize_artefacts", "PASS", 0, "ok"))
    monkeypatch.setattr(R, "_run_declared_signoff_gate", lambda project, name, *a:
                        R.StepResult(name, "PASS", 0, "ok"))
    monkeypatch.setattr(R, "_signoff_regen", lambda *a: False)
    monkeypatch.setattr(R, "_si_mcf_repair_seam", lambda *a: None)
    monkeypatch.setattr(si_mcf_repair, "run_once", lambda *a, **kw: {"decision": "NO_OP"})
    monkeypatch.setattr(si_mcf_verdict_basis, "apply", lambda *a: None)
    monkeypatch.setattr(drc_feedback_repair, "has_reviewed_rule", lambda *a: False)
    monkeypatch.setattr(R, "_to_container_path", lambda path, container: path)
    monkeypatch.setattr(R, "_docker_exec", lambda *a, **kw: (0,
        "PRESTREAM_UNROUTED_NETS: 0\nPRESTREAM_ABUTTED_NETS: 0\n"
        "PRESTREAM_UNROUTED_SHAPE_BLIND: 0\nPRESTREAM_CENSUS_COMPLETE: 1\n", ""))
    R.step_prestream_gate(tmp_path, "unit", Pdk(), "eda")
    rows = json.loads((tmp_path / "reports/phase3/prestream_gate.json").read_text())["gates"]
    route = next(r for r in rows if r["name"] == "route_connectivity")
    assert route["status"] == "PASS", route
    assert route["output_files"] == [str(tmp_path / "reports/phase3/prestream_route_census.json")]


import pytest


@pytest.mark.parametrize('phase', ['prestream', 'final'])
def test_later_signoff_readers_preserve_completed_ir_em_owner_reports(
        tmp_path, phase):
    """Real report checkers write their own scope and retain measured failure.

    Native tools are not invoked: the existing neutral current/limit fixture
    supplies readable reports, segment currents, wire geometry and Jmax.
    """
    import test_em_peak_current_authority_check as current
    import test_antenna_report_check as antenna
    specs = R._PRESTREAM_GATES if phase == 'prestream' else R._FINAL_LAYOUT_GATES
    programs = {'ir_drop_report_check.py', 'em_report_check.py',
                'em_peak_current_authority_check.py', 'antenna_report_check.py'}
    selected = [spec for spec in specs if spec[1] in programs]
    aliases = {'ir_drop_signoff.json': 'eda_report_audit:ir_drop',
               'em_signoff.json': 'eda_report_audit:em',
               'em_current_authority.json': 'em_peak_current_authority_check',
               'antenna_signoff.json': 'eda_report_audit:antenna'}
    for peak, expected in [('1.0e-06', 'PASS'), ('5.0', 'FAIL')]:
        project = current._project(tmp_path / expected, peak=peak,
                                   with_csv=True, with_jmax=True)
        reports = project / 'reports/phase3'
        (reports / 'ir_drop.rpt').write_text(
            'OpenROAD PSM IR drop analysis\n'
            'power grid mesh nodes: 12458\n'
            'worst voltage drop: 6.8 mV (0.2% Vdd) static IR\n'
            'worst dynamic IR: 9.1 mV (0.3% Vdd)\n'
            + '# synthetic report detail\n' * 100)
        (reports / 'antenna.rpt').write_text(antenna.CLEAN)
        em_report = reports / 'em.rpt'
        em_report.write_text(em_report.read_text() + '# synthetic report detail\n' * 100)
        retained = {}
        for name, program in aliases.items():
            path = reports / name
            path.write_text(json.dumps({'program': program, 'verdict': 'PASS',
                                        'retained_owner': name}) + '\n')
            retained[path] = path.read_bytes()
        native_inputs = {path: path.read_bytes() for path in (
            reports / 'ir_drop.rpt', reports / 'em.rpt', reports / 'em.json',
            reports / 'em_segments.csv', reports / 'em_jmax.json', reports / 'antenna.rpt',
            project / 'phase3/stage3/pnr/routed.def')}
        rows = [R._run_declared_signoff_gate(project, *spec) for spec in selected]
        assert {path: path.read_bytes() for path in retained} == retained
        assert {path: path.read_bytes() for path in native_inputs} == native_inputs
        assert len(rows) == (4 if phase == 'prestream' else 3)
        for spec, row in zip(selected, rows):
            report = project / spec[2]
            assert row.output_files == [str(report)]
            assert report not in retained
            doc = json.loads(report.read_text())
            if spec[1] == 'em_peak_current_authority_check.py':
                assert doc['verdict'] == expected
            else:
                assert doc['passed'] is (row.status == 'PASS')
        authority = next(row for spec, row in zip(selected, rows)
                         if spec[1] == 'em_peak_current_authority_check.py')
        assert authority.status == expected, authority.detail
        if expected == 'PASS':
            assert all(row.status == 'PASS' for row in rows), rows
        else:
            assert any(row.status == 'FAIL' for row in rows), rows


@pytest.fixture
def final_state_carrier(tmp_path, monkeypatch):
    """Ruling #62: native final results, no stage probes or publisher."""
    pnr = tmp_path / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    (pnr / 'routed.def').write_text('COMPONENTS 1 ;\n- u cell + PLACED ( 0 0 ) N ;\nEND COMPONENTS\n')
    (pnr / 'final.odb').write_text('neutral synthetic ODB placeholder')
    (pnr / 'final.v').write_text('module unit(); endmodule\n')
    (pnr / 'final.sdc').write_text('set_max_fanout 4 [current_design]\n')
    folder = tmp_path / 'phase3/librelane/native-final'
    folder.mkdir(parents=True)
    corners = [f'{rc}_{p}' for rc in ('min', 'nom', 'max') for p in ('slow', 'typical', 'fast')]
    metrics = {'route__drc_errors_final': 0, 'route__opens': 0}
    for corner in corners:
        scene = folder / corner
        scene.mkdir()
        lines = []
        for kind, metric in [('max_slew', 'slew'), ('max_capacitance', 'cap'), ('max_fanout', 'fanout')]:
            metrics[f'design__max_{metric}_violation__count__corner:{corner}'] = 0
            lines.append(f'SIGNOFF_DRV_CENSUS {kind} violators=0')
        (scene / 'vibeic_signoff.rpt').write_text('\n'.join(lines) + '\n')
    liberty = folder / 'neutral.lib'
    liberty.write_text('library(neutral) {\n time_unit : "1ns";\n capacitive_load_unit(1,pf);\n'
                       'default_max_transition : 2;\n default_max_capacitance : 1;\n'
                       'cell(buf) { pin(Y) { direction : output; max_transition : 2; max_capacitance : 1; } }\n}\n')
    (folder / 'config.json').write_text(json.dumps({'STA_CORNERS': corners,
        'MAX_FANOUT_CONSTRAINT': 4, 'LIB': {'*': [str(liberty)]}}))
    state = {'def': str(pnr / 'routed.def'), 'odb': str(pnr / 'final.odb'),
             'nl': str(pnr / 'final.v'), 'sdc': str(pnr / 'final.sdc'), 'metrics': metrics}
    # Config/reports belong to the selected native State directory.
    state_path = folder / 'state_out.json'
    state_path.write_text(json.dumps(state))
    (tmp_path / 'state_out.json').symlink_to(state_path)
    (folder / 'check_placement.rpt').write_text('FINAL_CHECK_PLACEMENT_VIOLATIONS 0\n')
    reports = tmp_path / 'reports/phase3'
    reports.mkdir(parents=True)
    (reports / 'si_mcf_sta.json').write_text(json.dumps({'verdict': 'PASS', 'corners': {
        role: {'worst_slack_after_ns': 0.2} for role in ('setup', 'hold')}}))
    (reports / 'dynamic_ir.json').write_text(json.dumps({'max_transient_droop_mv': 1, 'vdd_v': 1}))
    def gate(project, name, *args):
        return R.StepResult(name, 'PASS', 0, 'other native gates held clean')
    import hold_corner_coverage_check, post_route_signoff_corner_check, sta_corner_record_completeness_check
    monkeypatch.setattr(hold_corner_coverage_check, 'judge_tool', lambda *args: ('PASS', 0, {}))
    monkeypatch.setattr(post_route_signoff_corner_check, 'evaluate_tool', lambda *args: {'verdict': 'PASS'})
    monkeypatch.setattr(sta_corner_record_completeness_check, 'evaluate_tool', lambda *args: {'verdict': 'PASS'})
    monkeypatch.setattr(R, '_run_declared_signoff_gate', gate)
    monkeypatch.setattr(R, '_canonicalize_postpnr_prerequisites', lambda *args: pytest.fail('publisher ran'))
    monkeypatch.setattr(R, 'step_canonicalize_artefacts', lambda *args, **kw: pytest.fail('publisher ran'))
    monkeypatch.setattr(R, '_prestream_route_census', lambda *args, **kw: ({'unrouted_nets': 0}, ''))
    monkeypatch.setattr(R, '_layout_basis', lambda *args: ('fixture-layout', ''))
    # Ruling #62/R3: measure the current ODB, independent of historical logs.
    def launch(*args, **kwargs):
        if launch.error:
            raise RuntimeError('native launch failed')
        return launch.rc, ('' if launch.count is None else
            f'PRESTREAM_CHECK_PLACEMENT_VIOLATIONS {launch.count}\n'), ''
    launch.count, launch.rc, launch.error = 0, 0, False
    monkeypatch.setattr(R, '_docker_exec', launch)
    monkeypatch.setattr(R, '_to_container_path', lambda p, c: p)
    return tmp_path, folder, state_path


def _final_gate(carrier):
    project, _, _ = carrier
    result = R.step_prestream_gate(project, 'unit', None, '')
    rows = json.loads((project / 'reports/phase3/prestream_gate.json').read_text())['gates']
    return result, {row['name']: row['status'] for row in rows}


def test_final_state_native_clean_without_historical_requirements(final_state_carrier):
    result, rows = _final_gate(final_state_carrier)
    assert result.status == 'PASS', result.detail
    assert all(status == 'PASS' for status in rows.values()), rows


@pytest.mark.parametrize('gate', ['placement_legality', 'route_completion', 'drv_signoff', 'si'])
def test_final_state_each_native_violation_fails(final_state_carrier, gate):
    project, folder, state_path = final_state_carrier
    state = json.loads(state_path.read_text())
    if gate == 'placement_legality':
        R._docker_exec.count = 1
    elif gate == 'route_completion':
        state['metrics']['route__drc_errors_final'] = 1
    elif gate == 'drv_signoff':
        state['metrics']['design__max_slew_violation__count__corner:min_slow'] = 1
    else:
        p = project / 'reports/phase3/si_mcf_sta.json'
        doc = json.loads(p.read_text())
        doc['corners']['hold']['worst_slack_after_ns'] = -0.01
        p.write_text(json.dumps(doc))
    state_path.write_text(json.dumps(state))
    result, rows = _final_gate(final_state_carrier)
    assert result.status == 'FAIL', result.detail
    assert rows[gate] == 'FAIL', rows


@pytest.mark.parametrize('gate', ['placement_legality', 'route_completion', 'drv_signoff', 'si'])
def test_final_state_missing_native_evidence_is_not_measured(final_state_carrier, gate):
    project, folder, state_path = final_state_carrier
    state = json.loads(state_path.read_text())
    if gate == 'placement_legality':
        R._docker_exec.count = None
    elif gate == 'route_completion':
        del state['metrics']['route__opens']
    elif gate == 'drv_signoff':
        del state['metrics']['design__max_cap_violation__count__corner:max_fast']
    else:
        (project / 'reports/phase3/si_mcf_sta.json').unlink()
    state_path.write_text(json.dumps(state))
    result, rows = _final_gate(final_state_carrier)
    assert result.status == 'NOT_MEASURED', result.detail
    assert rows[gate] == 'NOT_MEASURED', rows


@pytest.mark.parametrize('metric', ['route__opens',
    'design__max_cap_violation__count__corner:max_fast',
    'design__max_fanout_violation__count__corner:nom_typical'])
def test_final_state_native_opens_and_other_drv_types_fail(final_state_carrier, metric):
    _, _, state_path = final_state_carrier
    state = json.loads(state_path.read_text())
    state['metrics'][metric] = 1
    state_path.write_text(json.dumps(state))
    result, rows = _final_gate(final_state_carrier)
    assert result.status == 'FAIL'
    assert rows['route_completion' if metric == 'route__opens' else 'drv_signoff'] == 'FAIL'


def test_final_state_requires_no_publisher_pointer(final_state_carrier):
    project, _, _ = final_state_carrier
    (project / 'state_out.json').unlink()
    result, _ = _final_gate(final_state_carrier)
    assert result.status == 'PASS', result.detail


def test_final_state_native_violation_outweighs_missing_measurement(final_state_carrier):
    _, folder, state_path = final_state_carrier
    R._docker_exec.count = None
    state = json.loads(state_path.read_text())
    state['metrics']['route__opens'] = 1
    state_path.write_text(json.dumps(state))
    result, rows = _final_gate(final_state_carrier)
    assert result.status == 'FAIL'
    assert rows['placement_legality'] == 'NOT_MEASURED'
    assert rows['route_completion'] == 'FAIL'


def test_final_state_scoped_native_route_log_is_final_evidence(final_state_carrier):
    project, _, state_path = final_state_carrier
    state = json.loads(state_path.read_text())
    del state['metrics']['route__drc_errors_final']
    spef = project / 'final.spef'
    spef.write_text('*SPEF \"IEEE 1481-1998\"\n')
    state['spef'] = {'nom_*': str(spef)}
    state_path.write_text(json.dumps(state))
    (project / 'phase3/stage3/pnr/openroad.log').write_text(
        '[INFO DRT-0702] Post-route verification: 0 violation(s).\n'
        '[INFO DRT-0711] Scoped detailed routing: whole-design violations 0 on entry, 0 on exit (delta +0).\n')
    result, rows = _final_gate(final_state_carrier)
    assert result.status == 'PASS', result.detail
    assert rows['route_completion'] == 'PASS'


def test_final_state_missing_native_corner_report_is_not_measured(final_state_carrier):
    _, folder, _ = final_state_carrier
    (folder / 'max_fast/vibeic_signoff.rpt').unlink()
    result, rows = _final_gate(final_state_carrier)
    assert result.status == 'NOT_MEASURED'
    assert rows['drv_signoff'] == 'NOT_MEASURED'


from post_route_signoff_corner_check import evaluate_tool as _native_corner_judge


@pytest.mark.parametrize('slack, expected', [(0.2, 'PASS'), (-0.02, 'FAIL')])
def test_final_state_sta_uses_native_slack_without_publisher(final_state_carrier, monkeypatch, slack, expected):
    import post_route_signoff_corner_check
    monkeypatch.setattr(post_route_signoff_corner_check, 'evaluate_tool', _native_corner_judge)
    _, folder, _ = final_state_carrier
    for report in folder.glob('*/vibeic_signoff.rpt'):
        report.write_text(f'STA_BASIS: POST_ROUTE_SPEF\nworst slack max {slack}\nworst slack min 0.2\n' + report.read_text())
    result, rows = _final_gate(final_state_carrier)
    assert rows['sta_corner'] == expected, result.detail
    assert result.status == expected, result.detail


def test_final_state_placement_front_door_uses_native_legality(final_state_carrier):
    import placement_legality_check
    project, folder, _ = final_state_carrier
    assert placement_legality_check.inspect(project)[0] == 'PASS'
    R._docker_exec.count = 1
    assert placement_legality_check.inspect(project)[0] == 'FAIL'


def test_final_state_drv_front_door_needs_no_history_or_authority(final_state_carrier):
    import drv_signoff_judge
    project, folder, _ = final_state_carrier
    output = project / 'drv.json'
    assert drv_signoff_judge.main([str(project), '--json', str(output)]) == 0
    assert json.loads(output.read_text())['verdict'] == 'PASS'
    report = folder / 'nom_typical/vibeic_signoff.rpt'
    report.write_text(report.read_text().replace('max_fanout violators=0', 'max_fanout violators=1'))
    assert drv_signoff_judge.main([str(project), '--json', str(output)]) == 1
    assert json.loads(output.read_text())['verdict'] == 'FAIL'


_native_layout_basis = R._layout_basis


def test_final_state_basis_uses_state_design_formats(final_state_carrier):
    project, _, _ = final_state_carrier
    digest, refusal = _native_layout_basis(project, 'unit', None, '')
    assert not refusal, refusal
    assert len(digest) == 64
    state = json.loads(final_state_carrier[2].read_text())
    assert R._layout_basis_paths(project, 'unit') == [
        R.Path(state[k]) for k in ('odb', 'def', 'nl', 'sdc')]



def test_final_state_missing_liberty_limits_is_not_measured(final_state_carrier):
    _, folder, _ = final_state_carrier
    (folder / 'neutral.lib').unlink()
    result, rows = _final_gate(final_state_carrier)
    assert result.status == 'NOT_MEASURED'
    assert rows['drv_signoff'] == 'NOT_MEASURED'


def test_final_state_cannot_downgrade_declared_fanout(final_state_carrier):
    _, _, state_path = final_state_carrier
    state = json.loads(state_path.read_text())
    R.Path(state['sdc']).write_text('set_max_fanout 8 [current_design]\n')
    result, rows = _final_gate(final_state_carrier)
    assert result.status == 'FAIL'
    assert rows['drv_signoff'] == 'FAIL'


@pytest.mark.parametrize('count,rc,error,old_count,expected', [
    (0, 0, False, 7, 'PASS'),
    (3, 0, False, 0, 'FAIL'),
    (0, 1, False, 0, 'NOT_MEASURED'),
    (None, 0, False, 0, 'NOT_MEASURED'),
    (0, 0, True, 0, 'NOT_MEASURED'),
])
def test_final_odb_native_measurement_ignores_old_log(final_state_carrier, count, rc, error, old_count, expected):
    import _prestream_native as native
    project, folder, state_path = final_state_carrier
    (folder / 'check_placement.rpt').write_text(f'FINAL_CHECK_PLACEMENT_VIOLATIONS {old_count}\n')
    R._docker_exec.count, R._docker_exec.rc, R._docker_exec.error = count, rc, error
    doc = native.placement(project, state_path)
    assert doc['verdict'] == expected, doc


def test_final_odb_missing_never_launches(final_state_carrier, monkeypatch):
    import _prestream_native as native
    project, _, state_path = final_state_carrier
    Path(json.loads(state_path.read_text())['odb']).unlink()
    monkeypatch.setattr(R, '_docker_exec', lambda *a, **kw: pytest.fail('missing ODB launched'))
    assert native.placement(project, state_path)['verdict'] == 'NOT_MEASURED'


def test_final_odb_launch_inputs_and_native_log(final_state_carrier, monkeypatch):
    import _prestream_native as native
    project, folder, state_path = final_state_carrier
    (folder / 'check_placement.rpt').unlink()
    odb = Path(json.loads(state_path.read_text())['odb'])
    calls = []
    def launch(container, command, **kwargs):
        calls.append((container, command, kwargs))
        script = Path(kwargs['marker']).read_text()
        assert f'read_db "{odb}"' in script
        assert 'check_placement -no_abort' in script
        assert kwargs['inputs'] == [odb]
        return 0, 'PRESTREAM_CHECK_PLACEMENT_VIOLATIONS 0\n', ''
    monkeypatch.setattr(R, '_docker_exec', launch)
    doc = native.placement(project, state_path)
    assert doc['verdict'] == 'PASS', doc
    assert len(calls) == 1
    assert (project / 'reports/phase3/prestream_placement.log').read_text().strip() == 'PRESTREAM_CHECK_PLACEMENT_VIOLATIONS 0'
