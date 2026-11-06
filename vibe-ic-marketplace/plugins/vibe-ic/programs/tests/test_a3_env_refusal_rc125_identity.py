"""A3 preserves the native cause of stopped and unavailable executions."""
import subprocess
import pytest
import _container_exec as CE
import analog_a3_netlist_emit as A3


def _launch_answer(monkeypatch, stderr, rc=125):
    monkeypatch.setattr(A3.shutil, 'which', lambda _: '/not-executed/docker')
    monkeypatch.setattr(A3, '_docker_ok', lambda _: True)
    monkeypatch.setattr(CE, 'docker_exec_argv', lambda *a, **k: ['probe-supplied'])
    monkeypatch.setattr(A3._pr, 'run_best_effort',
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, 'yes', ''))
    monkeypatch.setattr(CE, 'run_in_container_supervised',
                        lambda *a, **kw: subprocess.CompletedProcess(['launch-supplied'], rc, '', stderr))
    return A3.verify_with_ngspice('own-control', 'block', '* block', '* testbench')

@pytest.mark.parametrize('rc,status', [
    (124, 'SIMULATION_STOPPED_EXTERNALLY'), (127, 'SIMULATION_INVOCATION_FAILED'),
])
def test_other_supervised_exit_codes_keep_their_own_cause(monkeypatch, rc, status):
    got = _launch_answer(monkeypatch, 'shell diagnostic', rc)
    assert got['simulation_status'] == status, got
    assert got['ngspice_rc'] == rc
    assert not got.get('env_refused')
    if rc == 127:
        assert 'could not execute' in got['detail']
        assert 'timeout' not in got['detail']


@pytest.mark.parametrize('stderr', ['', 'native command diagnostic'])
def test_native_125_keeps_the_tools_exit_status(monkeypatch, stderr):
    got = _launch_answer(monkeypatch, stderr, 125)
    assert got['ngspice_rc'] == 125
    assert got['simulation_verified'] is False
    assert got['simulation_status'] == 'DID_NOT_CONVERGE'
