"""Public document-only width authority, through normal producer and CLI."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import phase1_doc_one_shot_runner as runner

PROGRAMS = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / 'fixtures/phase1_local/l8_width_role_authority/width_authority.md'


def _assert_public_contract(data):
    parameters = {row['name']: str(row.get('default')) for row in data['parameters']}
    assert parameters['QUEUE_DEPTH'] == '17'
    widths = [row for row in data['timing_parameters'] if 'width_bits' in row]
    print('PUBLIC_WIDTH_ROWS ' + json.dumps(widths, sort_keys=True))
    assert widths == []


def test_public_unrelated_parameter_is_not_authority_for_role_widths(tmp_path):
    source = tmp_path / 'input/docs/width_authority.md'
    source.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURE, source)
    result = runner.gen_l8_timing_waveform(tmp_path, {source.name: source.read_text()})
    _assert_public_contract(json.loads(result.path.read_text()))


def test_public_cli_does_not_promote_data_format_roles_to_width_parameters(tmp_path):
    source = tmp_path / 'input/docs/width_authority.md'
    source.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURE, source)
    command = [sys.executable, str(PROGRAMS / 'phase1_doc_one_shot_runner.py'),
               str(tmp_path), '--ic-name', 'neutral_width_authority']
    run = subprocess.run(command, capture_output=True, text=True, check=False)
    (tmp_path / 'cli.stdout').write_text(run.stdout)
    (tmp_path / 'cli.stderr').write_text(run.stderr)
    print('PUBLIC_CLI_PROCESS ' + json.dumps({'argv': command, 'returncode': run.returncode}))
    assert run.returncode == 0, run.stdout + run.stderr
    data = json.loads((tmp_path / 'phase1/generated_docs/L8_RTL_CONSTANTS.json').read_text())
    _assert_public_contract(data)


def _emit_control(root, text):
    source = root / 'input/docs/width_control.md'
    source.parent.mkdir(parents=True)
    source.write_text(text)
    result = runner.gen_l8_timing_waveform(root, {source.name: text})
    return result, json.loads(result.path.read_text())


def test_unanchored_timestamp_prose_remains_source_without_becoming_a_parameter(tmp_path):
    _, data = _emit_control(tmp_path, 'The output is a 256-bit digest.\n\n'
                           'A 64-bit timestamp is recorded.')
    rows = [row for row in data['timing_parameters'] if 'width_bits' in row]
    assert {row['name'] for row in rows} == {'digest'}
    assert rows[0]['low_confidence'] is False
    assert 'A 64-bit timestamp is recorded.' in (tmp_path / 'input/docs/width_control.md').read_text()


def test_conflicting_source_observations_keep_both_rows_and_require_review(tmp_path):
    result, data = _emit_control(tmp_path, 'The output is a 256-bit digest.\n\n'
                                'The output is a 512-bit digest.')
    rows = [row for row in data['timing_parameters'] if row.get('name') == 'digest']
    assert [row['width_bits'] for row in rows] == [256, 512]
    assert [row['literal'] for row in rows] == ['256', '512']
    assert [row['evidence']['line'] for row in rows] == [1, 3]
    assert all(row['source'] == row['evidence']['source'] == 'input/docs/width_control.md'
               and row['low_confidence'] is True for row in rows)


def test_paired_clock_widths_keep_both_endpoints_without_duplicate_bigrams(tmp_path):
    _, data = _emit_control(tmp_path, 'A 96-bit ToD clock from the 64-bit relative clock.')
    rows = [row for row in data['timing_parameters'] if 'width_bits' in row]
    assert {row['name']: row['width_bits'] for row in rows} == {
        'tod_clock': 96, 'relative_clock': 64}
    assert len(rows) == 2
    assert rows[0]['evidence']['derived_from_pair'] == {
        'name': 'relative_clock', 'width_bits': 64}


def test_real_named_parameter_retains_its_identifier_and_default(tmp_path):
    _, data = _emit_control(tmp_path, '# Parameters\n\n#### TAG_WIDTH (default = 80)\n\n'
                           'The message contains an 80-bit tag.')
    assert {row['name']: str(row.get('default')) for row in data['parameters']} == {'TAG_WIDTH': '80'}
    assert not [row for row in data['timing_parameters'] if 'width_bits' in row]


@pytest.mark.parametrize('source,name,width,expected', [
    ('parameter counter = 24; 24-bit counter', 'counter', 24, True),
    ('parameter QUEUE_DEPTH = 17; 24-bit counter', 'counter', 24, False),
    ('parameter tag = 17; 80-bit tag', 'tag', 80, False),
], ids=['same_identifier_and_value', 'different_identifier', 'different_value'])
def test_structural_anchor_joins_its_own_identifier_and_literal(source, name, width, expected):
    position = source.index(str(width) + '-bit')
    assert runner._v1_6_360_width_role_has_structural_anchor(
        source, name, position, width=width) is expected


def test_finite_digest_candidate_cannot_authorize_another_role_in_the_same_sentence(tmp_path):
    _, data = _emit_control(tmp_path, 'parameter QUEUE_DEPTH = 17;\n'
                           'The output is a 24-bit counter and an 80-bit digest.\n')
    rows = {row['name']: row for row in data['timing_parameters'] if 'width_bits' in row}
    assert 'counter' not in rows
    assert rows['digest']['width_bits'] == 80
    assert rows['digest']['low_confidence'] is True
