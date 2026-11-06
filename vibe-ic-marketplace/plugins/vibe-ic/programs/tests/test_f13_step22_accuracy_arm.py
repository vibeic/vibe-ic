"""Numerical SPEF accuracy against a declared field-solver reference."""
import importlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
contract = importlib.import_module("librelane_contract")
signoff = importlib.import_module("librelane_signoff")

def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path

def spef(path, nets):
    """A minimal IEEE-1481 SPEF: one grounded cap per net, totals in pF."""
    body = ['*SPEF "IEEE 1481-1998"', '*DESIGN "t"', '*C_UNIT 1 PF', '*NAME_MAP']
    body += [f'*{i} {n}' for i, n in enumerate(nets, 1)]
    for i, (n, c) in enumerate(nets.items(), 1):
        body += [f'*D_NET *{i} {c}', '*CAP', f'1 *{i}:1 {c}', '*END']
    return write(path, '\n'.join(body) + '\n')

def reference(path, nets, corner='nom'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'kind': 'field_solver_reference', 'rc_corner': corner,
                                'nets': nets, 'failed': {}}))
    return path

REF = {'a': 0.010, 'b': 0.020, 'c': 0.030}

def test_the_arm_that_tracks_the_reference_is_selected(tmp_path):
    close = spef(tmp_path / 'close.spef', {'a': 0.011, 'b': 0.019, 'c': 0.031, 'd': 1.0})
    far = spef(tmp_path / 'far.spef', {'a': 0.014, 'b': 0.027, 'c': 0.041, 'd': 1.0})
    r = reference(tmp_path / 'ref.json', REF)
    got = signoff.accuracy_selection({'direct': far, 'librelane': close}, r, tmp_path / 'acc')
    assert got['selection'] == 'librelane' and got['reason'] is None
    assert got['criterion'] == 'accuracy against the field-solver reference'
    arm = json.loads((tmp_path / 'acc/librelane.json').read_text())
    assert arm['metrics']['c_mean_abs_err_pct']['value'] == pytest.approx(
        (10.0 + 5.0 + 100 / 30) / 3)
    # swapping the SPEFs swaps the selection: the pick follows the numbers
    got = signoff.accuracy_selection({'direct': close, 'librelane': far}, r, tmp_path / 'acc2')
    assert got['selection'] == 'direct'

def test_equal_accuracy_keeps_both_arms(tmp_path):
    same = spef(tmp_path / 's.spef', {'a': 0.011, 'b': 0.019, 'c': 0.031})
    got = signoff.accuracy_selection({'direct': same, 'librelane': same},
                                     reference(tmp_path / 'r.json', REF), tmp_path / 'acc')
    assert got['selection'] == 'UNDETERMINED' and got['reason'] == 'LL_PARETO_TIE'

def test_an_arm_missing_a_reference_net_is_not_measured(tmp_path):
    full = spef(tmp_path / 'f.spef', {'a': 0.011, 'b': 0.019, 'c': 0.031})
    short = spef(tmp_path / 's.spef', {'a': 0.010, 'b': 0.020})
    got = signoff.accuracy_selection({'direct': full, 'librelane': short},
                                     reference(tmp_path / 'r.json', REF), tmp_path / 'acc')
    assert got['selection'] == 'UNDETERMINED' and got['reason'] == 'LL_ARM_NOT_MEASURED'
    assert json.loads((tmp_path / 'acc/librelane.json').read_text())['missing_nets'] == ['c']

@pytest.mark.parametrize('doc', [{'kind': 'field_solver_reference', 'nets': {}},
                                 {'kind': 'other', 'nets': {'a': 1.0}},
                                 {'kind': 'field_solver_reference', 'nets': {'a': 0}}])
def test_an_empty_or_foreign_reference_is_refused(tmp_path, doc):
    p = write(tmp_path / 'r.json', json.dumps(doc))
    with pytest.raises(contract.Refusal, match='LL_RC_REFERENCE_'):
        signoff.load_reference(p)
