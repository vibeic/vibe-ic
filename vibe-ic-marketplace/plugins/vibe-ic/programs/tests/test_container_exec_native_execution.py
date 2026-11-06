"""Selected containers run tools without a software image authenticity gate."""
from __future__ import annotations

import json
import os

import pytest

import _container_exec as ce
import _docker_watchdog as dw
import _eda_pin


@pytest.fixture
def native_exec(monkeypatch, tmp_path):
    calls = tmp_path / "docker_calls.jsonl"
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/usr/bin/env python3\n"
        "import json,os,sys\n"
        "with open(os.environ['DOCKER_CALLS'], 'a') as stream:\n"
        "    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "args = sys.argv[1:]\n"
        "if len(args) < 3 or args[0] != 'exec': sys.exit(1)\n"
        "command = args[2:]\n"
        "os.execvp(command[0], command)\n"
    )
    docker.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("DOCKER_CALLS", str(calls))
    monkeypatch.delenv("VIBEIC_A4_FRESH_PROBES", raising=False)

    def refuse_if_consulted(*args, **kwargs):
        raise AssertionError("image authentication must not decide whether a tool runs")

    monkeypatch.setattr(_eda_pin, "container_image_digest", refuse_if_consulted)
    return calls


def test_selected_container_and_exec_options_are_preserved(native_exec):
    assert ce.docker_exec_argv("selected", "cat", "/work/result", opts=("-w", "/work")) == [
        "docker", "exec", "-w", "/work", "selected", "cat", "/work/result"
    ]


@pytest.mark.parametrize("native_rc", [0, 7, 125])
def test_native_stdout_stderr_and_exit_code_are_returned(native_exec, native_rc):
    result = ce.run_in_container(
        "selected", f"printf 'native output'; printf 'native stderr' >&2; exit {native_rc}",
        deadline_s=5, shell=("bash", "-c"))
    assert result.returncode == native_rc
    assert result.stdout == "native output"
    assert result.stderr == "native stderr"
    assert ce.describe_result(result, 5) is None
    commands = [json.loads(line) for line in native_exec.read_text().splitlines()]
    assert any(command[:6] == ["exec", "selected", "timeout", "-k", "5", "5"]
               for command in commands)


def test_deadline_still_stops_the_native_process(native_exec):
    result = ce.run_in_container("selected", "sleep 20", deadline_s=1,
                                 kill_grace_s=1, shell=("bash", "-c"))
    assert result.returncode == ce.TIMEOUT_EXPIRED_RC
    assert "deadline of 1s expired" in ce.describe_result(result, 1)


@pytest.mark.parametrize("native_rc", [0, 7, 125])
def test_supervised_native_result_and_pidfile_cleanup(native_exec, monkeypatch, tmp_path, native_rc):
    pidfile = tmp_path / "native-job.pid"
    monkeypatch.setattr(dw, "new_job_pidfile", lambda: str(pidfile))
    result = ce.run_in_container_supervised(
        "selected", f"printf 'native supervised output'; exit {native_rc}",
        ceiling_s=5, poll_s=0.05, stall_looks=20, shell=("bash", "-c"))
    assert result.returncode == native_rc
    assert result.stdout == "native supervised output"
    assert not pidfile.exists()
    commands = [json.loads(line) for line in native_exec.read_text().splitlines()]
    assert any(command[:4] == ["exec", "selected", "bash", "-c"] for command in commands)
    assert any("rm -f" in command[-1] for command in commands)
