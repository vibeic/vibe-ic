"""FS1's current producer must finish both reports before the consumer runs."""
import shutil

import pytest

import _flow_yaml
from test_fs1_fmeda_producer_is_run_by_the_runner import _project, _runner


REPORTS = (
    'reports/phase2/safety/fmeda_coverage.json',
    'reports/phase2/safety/fmeda_coverage_gate.json',
)


@pytest.mark.parametrize('relative', REPORTS)
def test_fs1_declares_the_report_written_by_its_program(relative):
    row = next(row for row in _flow_yaml.load()['steps'] if row['id'] == 'FS1')
    assert relative in row.get('required_outputs', []), row


@pytest.fixture(autouse=True)
def local_injection_backend(monkeypatch):
    # Inside the official image, run its actual iverilog/vvp binaries. The
    # launcher's image identity is not a request for Docker inside Docker.
    if shutil.which('docker') is None:
        monkeypatch.delenv('VIBEIC_EDA_IMAGE', raising=False)
        monkeypatch.delenv('IIC_EDA_IMAGE', raising=False)








def test_no_source_remains_unmeasured(tmp_path):
    project = _project(tmp_path, {'notes.txt': 'no RTL source\n'})
    row = _runner().step_fmeda_fault_injection(project)
    assert row.status == 'NOT_MEASURED', row
