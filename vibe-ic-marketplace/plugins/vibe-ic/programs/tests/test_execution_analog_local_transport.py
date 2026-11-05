"""SOURCE_CONTROL transport witness; Python subprocesses are real, Docker/EDA are not."""
import json
import os
import shlex
import sys
import time

import pytest

import _container_exec as ce
import _docker_watchdog as watchdog
import execution_analog_local_transport as transport
import librelane_contract as lc


@pytest.fixture
def transport_case(tmp_path, monkeypatch):
    project = tmp_path / "neutral project"
    binary = project / "bin/docker"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!" + sys.executable + "\n" + '''
import json, os, subprocess, sys
args = sys.argv[1:]
print("SOURCE_CONTROL_DOCKER_ARGV " + json.dumps({
    "argv": args, "execution_env": sorted(k for k in os.environ if k.startswith("VIBEIC_EXECUTION"))}), flush=True)
command = args[args.index("--skip") + 1:]
done = subprocess.run(command, capture_output=True, text=True)
print(done.stdout, end="")
print(done.stderr, end="", file=sys.stderr)
raise SystemExit(done.returncode)
''')
    binary.chmod(0o755)
    monkeypatch.setenv("PATH", str(binary.parent) + os.pathsep + os.environ["PATH"])
    monkeypatch.setenv("VIBEIC_EXECUTION_SOURCE_CONTROL", "must not reach child")
    monkeypatch.setenv("SOURCE_CONTROL_KEEP", "kept")
    parameters = {"docker": str(binary), "cpus": 2, "ram_mb": 128,
                  "image_ref": "correctness.invalid/source-control@sha256:" + "a" * 64}
    return project, parameters, tmp_path / "records/processes.jsonl"


def _witness(stdout):
    return json.loads(next(line.removeprefix("SOURCE_CONTROL_DOCKER_ARGV ")
                           for line in stdout.splitlines() if line.startswith("SOURCE_CONTROL_DOCKER_ARGV ")))


def test_actual_supervisor_records_neutral_process_output_for_all_transport_consumers(transport_case):
    project, parameters, receipts = transport_case
    command = shlex.join([sys.executable, "-c", "import os; print('component:'+os.environ['SOURCE_CONTROL_KEEP'])"])
    originals = (ce.docker_exec_argv, ce.run_in_container, ce.run_in_container_supervised,
                 watchdog.run_docker_supervised, lc.run_container)
    with transport.local_transport(receipts, time.monotonic() + 20, project=project, parameters=parameters):
        normal = ce.run_in_container("host", command)
        rc, stdout, stderr = watchdog.run_docker_supervised("", command, "source-control")
        chained = lc.run_container([parameters["docker"], "run", parameters["image_ref"], "--skip",
                                    sys.executable, "-c", "print('chain component')"], supervised=True)
        assert (normal.returncode, rc, chained.returncode) == (0, 0, 0)
        assert normal.stdout.endswith("component:kept\n") and stdout.endswith("component:kept\n")
        assert normal.stderr == stderr == chained.stderr == ""
        witness = _witness(normal.stdout)
        assert witness["execution_env"] == []
        assert witness["argv"][0] == "run" and "--name" in witness["argv"]
        for flag, expected in (("--cpus", "2"), ("--memory", "128m"), ("--memory-swap", "128m")):
            values = [witness["argv"][index + 1] for index, value in enumerate(witness["argv"]) if value == flag]
            assert values and set(values) == {expected}
        assert "none" in witness["argv"] and str(project) + ":" + str(project) in witness["argv"]
        image = witness["argv"].index(parameters["image_ref"])
        assert witness["argv"][image + 1:image + 4] == ["--skip", "bash", "-lc"]
    assert originals == (ce.docker_exec_argv, ce.run_in_container, ce.run_in_container_supervised,
                         watchdog.run_docker_supervised, lc.run_container)
    rows = [json.loads(line) for line in receipts.read_text().splitlines()]
    assert len(rows) == 3
    assert [row["rc"] for row in rows] == [0, 0, 0]
    assert rows[0]["stdout"] == normal.stdout and rows[1]["stdout"] == stdout
    assert rows[2]["stdout"] == chained.stdout
    assert all(row["observer_pid"] == os.getpid() and row["started_ns"] < row["ended_ns"] for row in rows)




def test_transport_restores_original_callers_after_body_exception(transport_case):
    project, parameters, receipts = transport_case
    originals = (ce.docker_exec_argv, ce.run_in_container, ce.run_in_container_supervised,
                 watchdog.run_docker_supervised, lc.run_container)
    with pytest.raises(RuntimeError, match="source body exception"):
        with transport.local_transport(receipts, time.monotonic() + 20, project=project, parameters=parameters):
            raise RuntimeError("source body exception")
    assert originals == (ce.docker_exec_argv, ce.run_in_container, ce.run_in_container_supervised,
                         watchdog.run_docker_supervised, lc.run_container)
