"""Step 18 must judge its actual insertion checkpoint, not only a healthy plan."""
import copy
import json
import os
from pathlib import Path
import sys

PROGRAMS = Path(os.environ.get('VIBEIC_VERSION_REVIEW_PROGRAMS',
                              str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(PROGRAMS))
import _flow_yaml
import execution_backend_gates as gates
import spare_cell_coverage_check as coverage


def _project(tmp_path, *, missing_instance=False, wrong_master=False, missing_connection=False):
    pnr = tmp_path / 'phase3/stage3/pnr'
    pnr.mkdir(parents=True)
    plan = {
        'count': 2, 'placed_cells_est': 50, 'actual_density': 0.04,
        'tied_off': True,
        'instances': [{'name': name, 'cell': 'INV', 'llx': 10 * i, 'lly': 10 * i}
                      for i, name in enumerate(('spare_a', 'spare_b'), 1)],
        'tie_off': {'inputs': [{'inst': name, 'pin': 'A', 'net': 'tie_' + name}
                               for name in ('spare_a', 'spare_b')]},
    }
    (pnr / 'spare_cells.json').write_text(json.dumps(plan))
    components = ['- spare_a INV + FIXED ( 1000 1000 ) N ;']
    if not missing_instance:
        components.append('- spare_b ' + ('WRONG' if wrong_master else 'INV') + ' + FIXED ( 2000 2000 ) N ;')
    nets = ['- tie_spare_a ( spare_a A ) ;']
    if not missing_connection:
        nets.append('- tie_spare_b ( spare_b A ) ;')
    (pnr / 'post_spare.def').write_text('\n'.join([
        'VERSION 5.8 ;', 'DESIGN unit ;', f'COMPONENTS {len(components)} ;',
        *components, 'END COMPONENTS', f'NETS {len(nets)} ;', *nets,
        'END NETS', 'END DESIGN',
    ]) + '\n')
    # Existing pure-plan producer output is substantive, but cannot vouch
    # for components/connections that are absent from the actual DEF.
    assert coverage.main([str(tmp_path)]) == 0
    return tmp_path


def _canonical_gate(project):
    row = copy.deepcopy(next(r for r in _flow_yaml.load()['steps'] if str(r['id']) == '18'))
    return gates.evaluate(project, row)


def test_current_inserted_cells_and_connections_pass(tmp_path):
    assert _canonical_gate(_project(tmp_path))['status'] == 'PASS'


def test_healthy_plan_does_not_rescue_missing_def_instance(tmp_path):
    result = _canonical_gate(_project(tmp_path, missing_instance=True))
    assert result['status'] == 'FAIL', result


def test_healthy_plan_does_not_rescue_wrong_def_master(tmp_path):
    result = _canonical_gate(_project(tmp_path, wrong_master=True))
    assert result['status'] == 'FAIL', result


def test_healthy_plan_does_not_rescue_missing_def_tieoff(tmp_path):
    result = _canonical_gate(_project(tmp_path, missing_connection=True))
    assert result['status'] == 'FAIL', result
