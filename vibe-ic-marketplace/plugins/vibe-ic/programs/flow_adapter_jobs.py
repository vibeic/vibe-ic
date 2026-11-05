"""One FIFO subprocess lane for independent native adapters."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import pickle
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time


def _worker_command(output: Path) -> list[str]:
    return [sys.executable, str(Path(__file__).resolve()), str(output)]


@dataclass(frozen=True)
class _Job:
    name: str
    directory: Path
    payload: bytes
    config: object


class AdapterJobs:
    def __init__(self, project: Path, route: dict):
        self.project = Path(project).resolve()
        self.route = route
        self._jobs: queue.Queue[_Job | None] = queue.Queue()
        self._completed: queue.Queue[dict] = queue.Queue()
        self._pending: dict[str, None] = {}
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._closed = False
        self._process: subprocess.Popen | None = None
        self._thread = threading.Thread(target=self._run, name="flow-adapter-jobs", daemon=True)
        self._thread.start()

    def submit(self, name: str, directory: Path, tool: dict, *, state=None, config=None) -> None:
        raw_state = state.to_raw_dict() if hasattr(state, "to_raw_dict") else state
        payload = pickle.dumps({"project": self.project, "directory": Path(directory).resolve(),
                                "tool": tool, "route": self.route, "state": raw_state,
                                "config": config}, protocol=pickle.HIGHEST_PROTOCOL)
        captured = pickle.loads(payload)
        job = _Job(name, captured["directory"], payload, captured["config"])
        with self._lock:
            if self._closed:
                raise RuntimeError("AdapterJobs is closed")
            if name in self._pending:
                raise ValueError(f"Adapter job is already pending: {name}")
            self._pending[name] = None
            self._jobs.put(job)

    @property
    def pending(self) -> list[str]:
        with self._lock:
            return list(self._pending)

    def _collected(self, packet: dict) -> dict:
        with self._lock:
            self._pending.pop(packet["name"])
        return packet

    def collect(self) -> list[dict]:
        packets = []
        while True:
            try:
                packets.append(self._collected(self._completed.get_nowait()))
            except queue.Empty:
                return packets

    def drain(self):
        while self.pending:
            yield self._collected(self._completed.get())

    def close(self, cancel: bool = False) -> None:
        with self._lock:
            if cancel:
                self._cancel.set()
                if self._process is not None:
                    self._kill_group(self._process)
            if not self._closed:
                self._closed = True
                self._jobs.put(None)
        self._thread.join()

    @staticmethod
    def _kill_group(process: subprocess.Popen) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            self._completed.put(self._execute(job))

    def _execute(self, job: _Job) -> dict:
        log = job.directory / "adapter-worker.log"
        output = None
        process = None
        started_clock = None
        wall_seconds = 0.0
        try:
            job.directory.mkdir(parents=True, exist_ok=True)
            with log.open("wb") as stream:
                if self._cancel.is_set():
                    raise RuntimeError("Adapter job cancelled before worker launch")
                with tempfile.NamedTemporaryFile(prefix=".adapter-result-", suffix=".pickle",
                                                 dir=job.directory, delete=False) as temporary:
                    output = Path(temporary.name)
                started_clock = time.perf_counter()
                process = subprocess.Popen(_worker_command(output), cwd=self.project,
                    stdin=subprocess.PIPE, stdout=stream, stderr=subprocess.STDOUT,
                    start_new_session=True)
                with self._lock:
                    self._process = process
                    if self._cancel.is_set():
                        self._kill_group(process)
                try:
                    process.communicate(input=job.payload)
                finally:
                    self._kill_group(process)
                    process.wait()
                    with self._lock:
                        self._process = None
                wall_seconds = time.perf_counter() - started_clock
            if process.returncode:
                raise RuntimeError("Adapter worker exited before returning a raw result")
            with output.open("rb") as stream:
                result = pickle.load(stream)
            if not isinstance(result, dict) or not isinstance(result.get("native"), dict):
                raise ValueError("Adapter worker did not return a raw native result dictionary")
            native = result["native"]
        except Exception as exc:
            code = process.returncode if process is not None else None
            native = {"ran": False, "exit_code": code, "metrics": {}, "reports": [str(log)],
                      "detail": f"Adapter worker transport failed (exit {code}): "
                                f"{type(exc).__name__}: {exc}. Log: {log}", "native_steps": []}
        finally:
            if output is not None:
                try:
                    output.unlink(missing_ok=True)
                except OSError as exc:
                    native["detail"] = (native.get("detail", "")
                        + f" Worker temporary output cleanup: {type(exc).__name__}: {exc}")
                    native.setdefault("reports", []).append(str(output))
        if started_clock is not None:
            wall_seconds = time.perf_counter() - started_clock
        return {"name": job.name, "native": native, "config": job.config,
                "wall_seconds": wall_seconds}


def _worker(output: Path) -> None:
    payload = pickle.load(sys.stdin.buffer)
    state = payload["state"]
    if state is not None:
        from librelane.state import State
        state = State.load(state)
    from flow_native_adapters import execute
    started = time.perf_counter()
    native = execute(payload["project"], payload["directory"], payload["tool"], payload["route"],
                     state=state, config=payload["config"])
    result = {"native": native, "adapter_wall_seconds": time.perf_counter() - started}
    with output.open("wb") as stream:
        pickle.dump(result, stream, protocol=pickle.HIGHEST_PROTOCOL)


if __name__ == "__main__":
    _worker(Path(sys.argv[1]))
