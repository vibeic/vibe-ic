from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import subprocess
import sys
import time

import pytest

import flow_adapter_jobs as jobs_module


WORKER = r'''
from decimal import Decimal
import os
from pathlib import Path
import pickle
import subprocess
import sys
import time

payload = pickle.load(sys.stdin.buffer)
tool = payload["tool"]
name = tool["name"]
project = Path(payload["project"])
print("worker stdout " + name, flush=True)
print("worker stderr " + name, file=sys.stderr, flush=True)
(project / (name + ".running")).touch()
if tool.get("hold"):
    while not (project / (name + ".release")).exists():
        time.sleep(0.01)
if tool.get("action") == "crash":
    os._exit(7)
if tool.get("action") == "missing":
    sys.exit(0)
if tool.get("action") in {"cancel", "crash_group"}:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    (project / "descendant.pid").write_text(str(child.pid))
    if tool["action"] == "crash_group":
        os._exit(7)
    while True:
        time.sleep(1)
with (project / "writer.log").open("a") as stream:
    stream.write(name + "\n")
native = {
    "ran": True, "exit_code": tool.get("native_exit", 0),
    "metrics": {"precise": Decimal("0.12345678901234567890123456789"),
                "infinite": Decimal("Infinity"), "floating": float("inf")},
    "reports": [str(Path.cwd())], "tool_seconds": Decimal("0.125"),
    "detail": "native detail", "native_steps": [{"name": name,
        "status": "FAIL" if tool.get("native_exit") else "PASS"}],
    "captured": payload, "cgroup": Path("/proc/self/cgroup").read_text(),
}
with Path(sys.argv[1]).open("wb") as stream:
    pickle.dump({"native": native, "adapter_wall_seconds": 0.125}, stream)
(project / (name + ".done")).touch()
'''


@pytest.fixture
def controlled_worker(tmp_path, monkeypatch):
    script = tmp_path / "controlled_worker.py"
    script.write_text(WORKER)
    monkeypatch.setattr(jobs_module, "_worker_command", lambda output: [
        sys.executable, str(script), str(output)])
    return script


def wait_for(path):
    deadline = time.monotonic() + 10
    while not path.exists():
        if time.monotonic() >= deadline:
            pytest.fail(f"Worker did not create {path}")
        time.sleep(0.01)


def assert_process_stopped(pid):
    deadline = time.monotonic() + 5
    while True:
        status = Path(f"/proc/{pid}/stat")
        if not status.exists() or status.read_text().split()[2] == "Z":
            return
        if time.monotonic() >= deadline:
            pytest.fail(f"Worker descendant {pid} is still running")
        time.sleep(0.01)


def test_fifo_progresses_while_parent_waits_on_physical_process(tmp_path, controlled_worker):
    project = tmp_path / "project"
    project.mkdir()
    original_cwd = Path.cwd()
    lane = jobs_module.AdapterJobs(project, {"delivery_target": "rtl"})
    try:
        lane.submit("simulation", project / "simulation", {"name": "simulation", "hold": True})
        lane.submit("gls", project / "gls", {"name": "gls"})
        wait_for(project / "simulation.running")
        assert lane.pending == ["simulation", "gls"]
        assert lane.collect() == []
        assert not (project / "gls.running").exists()

        physical = subprocess.run([sys.executable, "-c", """
from pathlib import Path
import sys, time
project = Path(sys.argv[1])
(project / 'simulation.release').touch()
while not (project / 'gls.done').exists():
    time.sleep(0.01)
(project / 'physical.done').touch()
""", str(project)], timeout=10, check=True)
        assert physical.returncode == 0
        packets = list(lane.drain())
        assert [packet["name"] for packet in packets] == ["simulation", "gls"]
        assert (project / "writer.log").read_text().splitlines() == ["simulation", "gls"]
        assert lane.pending == []
        assert lane.collect() == []
        assert Path.cwd() == original_cwd
        for packet in packets:
            assert packet["wall_seconds"] > 0
            assert packet["native"]["reports"] == [str(project)]
            assert packet["native"]["cgroup"] == Path("/proc/self/cgroup").read_text()
            log = (project / packet["name"] / "adapter-worker.log").read_text()
            assert "worker stdout " + packet["name"] in log
            assert "worker stderr " + packet["name"] in log
    finally:
        lane.close(cancel=True)


def test_submit_captures_state_tool_route_and_precise_config_before_mutation(
        tmp_path, controlled_worker):
    class State:
        def __init__(self):
            self.raw = {"nl": "old.v", "metrics": {"area": Decimal("1.00000000000000001")}}

        def to_raw_dict(self):
            return self.raw

    route = {"delivery_target": "rtl", "features": ["captured"]}
    config = {"CLOCK_PERIOD": Decimal("1.00000000000000000001"), "paths": (Path("old.lib"),),
              "nested": {"values": [Decimal("2.125")]}}
    state = State()
    tool = {"name": "snapshot", "native_exit": 1, "nested": ["old"]}
    lane = jobs_module.AdapterJobs(tmp_path, route)
    try:
        lane.submit("hold", tmp_path / "hold", {"name": "hold", "hold": True})
        wait_for(tmp_path / "hold.running")
        lane.submit("snapshot", tmp_path / "snapshot", tool, state=state, config=config)
        state.raw["nl"] = "new.v"
        state.raw["metrics"]["area"] = Decimal("9")
        config["CLOCK_PERIOD"] = Decimal("9")
        config["nested"]["values"].append(Decimal("9"))
        route["features"].append("changed")
        tool["nested"].append("changed")
        (tmp_path / "hold.release").touch()
        packet = list(lane.drain())[1]
        captured = packet["native"]["captured"]
        assert captured["state"] == {"nl": "old.v", "metrics": {
            "area": Decimal("1.00000000000000001")}}
        expected = {"CLOCK_PERIOD": Decimal("1.00000000000000000001"),
                    "paths": (Path("old.lib"),), "nested": {"values": [Decimal("2.125")]}}
        assert packet["config"] == captured["config"] == expected
        assert isinstance(packet["config"]["CLOCK_PERIOD"], Decimal)
        assert isinstance(packet["config"]["paths"], tuple)
        assert captured["route"]["features"] == ["captured"]
        assert captured["tool"]["nested"] == ["old"]
        native = packet["native"]
        assert native["ran"] is True
        assert native["exit_code"] == 1
        assert native["native_steps"] == [{"name": "snapshot", "status": "FAIL"}]
        assert native["tool_seconds"] == Decimal("0.125")
        assert native["metrics"]["precise"] == Decimal("0.12345678901234567890123456789")
        assert native["metrics"]["infinite"] == Decimal("Infinity")
        assert native["metrics"]["floating"] == float("inf")
    finally:
        lane.close(cancel=True)


def test_cleanup_error_preserves_native_failure_and_queue_progress(tmp_path, controlled_worker, monkeypatch):
    unlink = Path.unlink

    def fail_cleanup(path, *args, **kwargs):
        if path.name.startswith(".adapter-result-") and path.parent == tmp_path / "first":
            raise PermissionError("controlled output cleanup failure")
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    lane = jobs_module.AdapterJobs(tmp_path, {})
    try:
        lane.submit("first", tmp_path / "first", {"name": "first", "native_exit": 1})
        lane.submit("later", tmp_path / "later", {"name": "later"})
        wait_for(tmp_path / "later.done")
        packets = list(lane.drain())
        assert [packet["name"] for packet in packets] == ["first", "later"]
        assert packets[0]["native"]["exit_code"] == 1
        assert "controlled output cleanup failure" in packets[0]["native"]["detail"]
        assert packets[1]["native"]["exit_code"] == 0
        assert lane.pending == []
    finally:
        lane.close(cancel=True)


@pytest.mark.parametrize(("action", "exit_code"), [("crash", 7), ("crash_group", 7), ("missing", 0)])
def test_transport_failure_is_explicit_and_next_job_still_runs(
        tmp_path, controlled_worker, action, exit_code):
    lane = jobs_module.AdapterJobs(tmp_path, {})
    try:
        lane.submit(action, tmp_path / action, {"name": action, "action": action},
                    config={"exact": Decimal("0.1000000000000000001")})
        lane.submit("next", tmp_path / "next", {"name": "next"})
        failure, following = list(lane.drain())
        assert failure["native"]["ran"] is False
        assert failure["native"]["exit_code"] == exit_code
        assert str(exit_code) in failure["native"]["detail"]
        assert failure["wall_seconds"] > 0
        assert "tool_seconds" not in failure["native"]
        assert failure["config"] == {"exact": Decimal("0.1000000000000000001")}
        assert failure["native"]["reports"] == [str(tmp_path / action / "adapter-worker.log")]
        assert "worker stdout " + action in Path(failure["native"]["reports"][0]).read_text()
        assert following["native"]["ran"] is True
        assert lane.pending == []
        if action == "crash_group":
            assert_process_stopped(int((tmp_path / "descendant.pid").read_text()))
    finally:
        lane.close(cancel=True)


def test_drain_streams_results_and_normal_close_preserves_uncollected_packet(
        tmp_path, controlled_worker):
    lane = jobs_module.AdapterJobs(tmp_path, {})
    try:
        lane.submit("first", tmp_path / "first", {"name": "first"})
        lane.submit("second", tmp_path / "second", {"name": "second", "hold": True})
        remaining = lane.drain()
        assert next(remaining)["name"] == "first"
        wait_for(tmp_path / "second.running")
        assert lane.pending == ["second"]
        assert lane.collect() == []
        (tmp_path / "second.release").touch()
        lane.close()
        assert lane.pending == ["second"]
        assert [packet["name"] for packet in lane.collect()] == ["second"]
        assert list(remaining) == []
        assert lane.collect() == []
    finally:
        lane.close(cancel=True)


def test_spawn_failure_retains_exact_error_and_empty_log(tmp_path, monkeypatch):
    executable = tmp_path / "absent-worker"
    monkeypatch.setattr(jobs_module, "_worker_command", lambda output: [str(executable)])
    lane = jobs_module.AdapterJobs(tmp_path, {})
    try:
        lane.submit("absent", tmp_path / "absent", {})
        packet, = list(lane.drain())
        assert packet["native"]["ran"] is False
        assert packet["native"]["exit_code"] is None
        assert "FileNotFoundError" in packet["native"]["detail"]
        assert str(executable) in packet["native"]["detail"]
        assert Path(packet["native"]["reports"][0]).read_bytes() == b""
    finally:
        lane.close(cancel=True)


def test_cancel_kills_only_own_process_group_and_cancels_queued_work(
        tmp_path, controlled_worker):
    unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    lane = jobs_module.AdapterJobs(tmp_path, {})
    try:
        lane.submit("running", tmp_path / "running", {"name": "running", "action": "cancel"})
        lane.submit("queued", tmp_path / "queued", {"name": "queued"})
        wait_for(tmp_path / "descendant.pid")
        descendant = int((tmp_path / "descendant.pid").read_text())
        lane.close(cancel=True)
        assert unrelated.poll() is None
        packets = lane.collect()
        assert [packet["name"] for packet in packets] == ["running", "queued"]
        assert all(packet["native"]["ran"] is False for packet in packets)
        assert packets[0]["native"]["exit_code"] == -9
        assert packets[1]["native"]["exit_code"] is None
        assert not (tmp_path / "queued.running").exists()
        assert lane.pending == []
        assert_process_stopped(descendant)
        lane.close(cancel=True)
        with pytest.raises(RuntimeError, match="closed"):
            lane.submit("late", tmp_path / "late", {})
    finally:
        lane.close(cancel=True)
        unrelated.terminate()
        unrelated.wait(timeout=5)


def test_real_worker_missing_input_runs_without_librelane_or_verdict_publication(tmp_path, monkeypatch):
    worker = Path(jobs_module.__file__).resolve()
    launcher = """
import runpy, sys
sys.modules['librelane'] = None
sys.path.insert(0, sys.argv[1])
sys.argv = sys.argv[2:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
    monkeypatch.setattr(jobs_module, "_worker_command", lambda output: [
        sys.executable, "-c", launcher, str(worker.parent), str(worker), str(output)])
    lane = jobs_module.AdapterJobs(tmp_path, {"delivery_target": "rtl"})
    try:
        lane.submit("missing-input", tmp_path / "missing-input", {"adapter": "gls"})
        packet, = list(lane.drain())
        assert packet["native"]["ran"] is False
        assert packet["native"]["exit_code"] is None
        assert packet["native"]["detail"] == (
            "GLS needs the declared top, native State netlist and corner SDF files.")
        assert not list(tmp_path.rglob("result.json"))
        assert not list(tmp_path.rglob("flow-report.json"))
        assert (tmp_path / "missing-input/adapter-worker.log").is_file()
    finally:
        lane.close(cancel=True)
