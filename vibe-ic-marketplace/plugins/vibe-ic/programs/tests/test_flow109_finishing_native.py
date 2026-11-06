"""Public finishing owners read native results; these fixtures do not run EDA."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import librelane_contract as contract
import librelane_fill_dfm as fill


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    return path


def state(project, lane, before, after):
    folder = project / 'phase3/librelane' / lane
    put(folder / 'state_in.json', before)
    put(folder / 'state_out.json', after)
    put(folder / 'input_fingerprint.json', {'config': 'unused', 'state_files': {
        str(value): contract.digest(Path(value)) for key, value in before.items()
        if key != 'metrics'}})
    return folder / 'state_out.json'


def density_case(project, count=0):
    pre = put(project / 'phase3/pre.gds', 'native pre-stream fixture')
    gds = put(project / 'phase3/filled.gds', 'native filled-stream fixture')
    filler = state(project, 'fill/01-klayout-filler', {'gds': str(pre)}, {'gds': str(gds)})
    measured = state(project, 'density/01-klayout-density', {'gds': str(gds)},
                     {'gds': str(gds), 'metrics': {fill.DENSITY_METRIC: count}})
    arm = {'state': str(measured), 'subject': str(gds),
           'subject_sha256': contract.digest(gds), fill.DENSITY_METRIC: count,
           'filler': {'state': str(filler)}}
    put(project / fill.RECORD_REL, {'gds': {'librelane': arm}})
    return arm


@pytest.mark.parametrize('count', [0, 4])
def test_density_result_is_the_native_count_without_receipt(tmp_path, count):
    arm = density_case(tmp_path, count)
    row = fill.validate_density_result(tmp_path, arm)
    assert row['value'] == count
    assert row['status'] == ('MEASURED' if count == 0 else 'FAIL')


def test_density_new_input_does_not_reuse_previous_measurement(tmp_path):
    arm = density_case(tmp_path)
    Path(arm['subject']).write_text('a later native geometry revision')
    assert fill.validate_density_result(tmp_path, arm)['value'] == 'NOT_MEASURED'
