"""Public finishing owners read native results; these fixtures do not run EDA."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import librelane_contract as contract
import librelane_fill_dfm as fill
import flow109_density_fill as density
import phase3_one_shot_runner as runner


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


def test_default_stream_reuses_unchanged_native_stream(tmp_path, monkeypatch):
    put(tmp_path / fill.DEFAULT_STREAM_REL, {})
    record = {'file_top': 'unit_top', 'pdk': 'unit_pdk'}
    monkeypatch.setattr(fill, 'validate_default_stream', lambda project: record)
    result = fill.default_stream(tmp_path, 'unit_top', SimpleNamespace(name='unit_pdk'), '')
    assert result['file_top'] == 'unit_top'
    assert result['receipt'] == str(tmp_path / fill.DEFAULT_STREAM_REL)


@pytest.mark.parametrize('count,status', [(0, 'PASS'), (3, 'FAIL')])
def test_d62_completes_from_its_native_owner_without_manual_manifest(tmp_path, count, status):
    density_case(tmp_path, count)
    result = density.execute(tmp_path, {'requested_step': 'D62'})
    assert result['default_row_status'] == status
    assert result['completed'] == (status == 'PASS')
    assert result['native_started'] is False
    assert result['metrics'][fill.DENSITY_METRIC] == count


def test_public_stream_entry_uses_native_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(fill, 'validate_default_stream', lambda project:
                        {'stream_state': 'native/state_out.json'})
    result = fill.execute(tmp_path, {'requested_step': 'D60'})
    assert result['completed'] is True
    assert result['native_report'] == 'native/state_out.json'


def test_public_seal_entry_reuses_its_native_state(tmp_path, monkeypatch):
    pre = put(tmp_path / 'phase3/pre.gds', 'native pre-stream fixture')
    sealed = put(tmp_path / 'phase3/sealed.gds', 'native sealed-stream fixture')
    output = state(tmp_path, '26.5ic/01-klayout-sealring', {'gds': str(pre)}, {'gds': str(sealed)})
    die = [0, 0, 20, 20]
    put(tmp_path / 'reports/phase3/die_finishing_librelane.json',
        {'tool': {'state': str(output), 'die_area': die}})
    monkeypatch.setattr(fill, 'validate_default_stream', lambda project:
                        {'stream': str(pre), 'sealed': str(sealed)})
    monkeypatch.setattr(contract, '_runner_floorplan', lambda project: (die, None, {}, '', {}))
    result = fill.execute(tmp_path, {'requested_step': 'D61'})
    assert result['completed'] is True
    assert result['native_started'] is False
    assert result['native_report'] == str(output)


@pytest.mark.parametrize('count,status', [(0, 'PASS'), (2, 'FAIL')])
def test_public_dfm_entry_preserves_native_density_result(tmp_path, monkeypatch, count, status):
    import dfm_screen_check
    density_case(tmp_path, count)
    record = json.loads((tmp_path / fill.RECORD_REL).read_text())
    record['gds']['shipped'] = 'librelane'
    put(tmp_path / fill.RECORD_REL, record)
    monkeypatch.setattr(dfm_screen_check, 'audit', lambda project:
                        {'verdict': 'PASS_WITH_ADVISORIES', 'findings': ['router advisory']})
    result = fill.execute(tmp_path, {'requested_step': 'D63'})
    assert result['default_row_status'] == status
    assert result['metrics'][fill.DENSITY_METRIC] == count
    assert result['advisories'] == ['router advisory']


def test_dfm_runs_its_native_deck_once_when_fill_has_no_density(tmp_path, monkeypatch):
    import dfm_screen_check
    arm = density_case(tmp_path)
    monkeypatch.setattr(fill, 'tool_density', lambda project: None)
    monkeypatch.setattr(fill, 'validate_default_stream', lambda project: {'canonical': arm['subject']})
    monkeypatch.setattr(runner, '_detect_pdk', lambda project: SimpleNamespace(name='unit'))
    monkeypatch.setattr(runner, '_librelane_step_ctx', lambda *args: ('image', tmp_path))
    monkeypatch.setattr(dfm_screen_check, 'audit', lambda project: {'findings': []})
    calls = []
    def native(*args, **kwargs):
        calls.append(kwargs)
        return arm
    monkeypatch.setattr(fill, 'run_density', native)
    first = fill.execute(tmp_path, {'requested_step': 'D63'})
    second = fill.execute(tmp_path, {'requested_step': 'D63'})
    assert first['completed'] and second['completed']
    assert first['native_started'] and not second['native_started']
    assert calls == [{'gds': Path(arm['subject']), 'lane': '35-dfm'}]
