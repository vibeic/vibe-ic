"""Actual owners and concrete path resolution for Step23's remaining outputs."""
import ast

import pytest

import matrix_d7_artifact_graph as G
from flow_matrix import flowref as F
from test_matrix_d7_outputs_list_complete import _mutated_flow, _SwappedFlow


@pytest.mark.parametrize('basename', ['mcorner_ocv_stance.json', 'multi_corner_spef_stance.json'])
def test_layout_helper_writer_is_not_a_write_of_the_historical_reader_alias(basename):
    tree = ast.parse(f'''import _path_layout as layout

def produce(project):
    report_dir = layout.reports_phase3_dir(project)
    stance = report_dir / "{basename}"
    stance.write_text("measured")
''')
    writes = G._collect_writes(tree, delegates=False)
    assert ('reports', 'phase3', basename) in writes
    assert (basename,) not in writes
    assert ('reports', 'phase3', 'sta', basename) not in writes


def test_unknown_same_named_helper_stays_conservative():
    tree = ast.parse('''import unrelated as layout
report_dir = layout.reports_phase3_dir(project)
(report_dir / "mcorner_ocv_stance.json").write_text("measured")
''')
    assert ('mcorner_ocv_stance.json',) in G._collect_writes(tree, delegates=False)


@pytest.mark.parametrize('sid,path', [
    ('15', 'reports/phase3/pdn_em_sizing.json'),
    ('23', 'phase3/reports/sta.rpt'),
    ('23', 'reports/phase3/mcorner_ocv_stance.json'),
    ('23', 'reports/phase3/multi_corner_spef_stance.json'),
])
def test_conditional_outputs_have_actual_runner_owner_without_a_duplicate_requirement(sid, path):
    assert ('phase3_one_shot_runner', path) in F.program_output_paths(sid)
    assert path not in G._all_declared()
    assert G.declaring_entry(path) is not None


def test_physical_sdc_is_required_by_the_floorplan_that_publishes_it():
    assert 'phase3/stage3/pnr/constraint.sdc' in F.required_outputs('15')


@pytest.mark.parametrize('path', [
    'phase3/stage3/pnr/constraint.sdc',
    'reports/phase3/mcorner_ocv_stance.json',
    'reports/phase3/multi_corner_spef_stance.json',
    'reports/phase3/pdn_em_sizing.json',
    'phase3/reports/sta.rpt',
])
def test_removing_the_real_owner_still_fails_step23(tmp_path, path):
    def remove(doc):
        for step in doc['steps']:
            step['required_outputs'] = [p for p in step.get('required_outputs', []) if p != path]
            step['program_outputs'] = [r for r in step.get('program_outputs', []) if r.get('path') != path]
    changed = _mutated_flow(tmp_path, 'missing-owner.yaml', remove)
    with _SwappedFlow(changed):
        assert any(row.path == path for row in G.findings_for('23'))


def test_step23_has_no_undeclared_current_or_conditional_output():
    assert not G.findings_for('23'), G.findings_for('23')


def test_unresolvable_layout_helper_body_keeps_the_basename_fallback(monkeypatch):
    unknown = ast.parse('def reports_phase3_dir(project):\n    return configured(project)\n')
    original = G._tree
    monkeypatch.setattr(G, '_tree', lambda name: unknown if name == '_path_layout' else original(name))
    G._reports_phase3_helper_tail.cache_clear()
    try:
        tree = ast.parse('''import _path_layout as layout
report_dir = layout.reports_phase3_dir(project)
(report_dir / "mcorner_ocv_stance.json").write_text("measured")
''')
        assert ('mcorner_ocv_stance.json',) in G._collect_writes(tree, delegates=False)
    finally:
        G._reports_phase3_helper_tail.cache_clear()
