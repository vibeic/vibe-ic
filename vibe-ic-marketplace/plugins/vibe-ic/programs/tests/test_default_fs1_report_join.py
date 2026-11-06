"""FS1's current producer must finish both reports before the consumer runs."""

import pytest

import _flow_yaml


REPORTS = (
    'reports/phase2/safety/fmeda_coverage.json',
    'reports/phase2/safety/fmeda_coverage_gate.json',
)


@pytest.mark.parametrize('relative', REPORTS)
def test_fs1_declares_the_report_written_by_its_program(relative):
    row = next(row for row in _flow_yaml.load()['steps'] if row['id'] == 'FS1')
    assert relative in row.get('required_outputs', []), row
