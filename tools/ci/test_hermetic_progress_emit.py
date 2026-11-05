from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from types import SimpleNamespace
from pathlib import Path

import pytest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location(
    "hermetic_progress_emit", HERE / "hermetic_progress_emit.py")
assert SPEC and SPEC.loader
E = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E)


def _env(monkeypatch, tmp_path, units=("one", "two")):
    plan = tmp_path / "progress-plan.json"
    nonce = "a" * 64
    scope = "landing"
    plan.write_text(json.dumps({
        "nonce": nonce, "protocol": "VIBEIC_PROGRESS/1", "schema": 1,
        "scope": scope, "units": list(units),
    }, sort_keys=True, separators=(",", ":")) + "\n")
    plan_raw = plan.read_bytes()
    monkeypatch.setenv("VIBEIC_HERMETIC_PROGRESS_NONCE", nonce)
    monkeypatch.setenv("VIBEIC_HERMETIC_PROGRESS_SCOPE", scope)
    monkeypatch.setenv("VIBEIC_HERMETIC_PROGRESS_PATH",
                       "/input/progress-plan.json")
    monkeypatch.setenv("VIBEIC_HERMETIC_PROGRESS_PREFIX", "VIBEIC_PROGRESS ")
    monkeypatch.setattr(E.Path, "read_bytes", lambda _self: plan_raw)
    return nonce


def test_exact_start_checkpoints_and_terminal(monkeypatch, tmp_path):
    nonce = _env(monkeypatch, tmp_path)
    rows = []
    for state, unit in (("start", None), ("checkpoint", "one"),
                        ("checkpoint", "two"), ("terminal", None)):
        raw = E.record(state, unit)
        assert raw.startswith(b"VIBEIC_PROGRESS ")
        rows.append(json.loads(raw[len(b"VIBEIC_PROGRESS "):]))
    assert [row["seq"] for row in rows] == [0, 1, 2, 3]
    assert rows[0] == {
        "nonce": nonce, "schema": 1, "scope": "landing", "seq": 0,
        "state": "start", "total": 2,
    }
    assert rows[-1]["state"] == "terminal"
    assert rows[-1]["completed"] == 2


def test_unknown_duplicate_and_nonfinite_plans_refuse(monkeypatch, tmp_path):
    _env(monkeypatch, tmp_path)
    with pytest.raises(E.Refusal, match="not in"):
        E.record("checkpoint", "forged")
    for raw in (
        b'{"nonce":"x","nonce":"y"}\n',
        b'{"nonce":NaN}\n',
    ):
        monkeypatch.setattr(E.Path, "read_bytes", lambda _self, raw=raw: raw)
        with pytest.raises(E.Refusal, match="cannot read"):
            E.record("start")


def _runner():
    spec = importlib.util.spec_from_file_location(
        "_collection_outer_runner", HERE / "hermetic_candidate_runner.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_COLLECTION_UNITS = [
    "pytest:collection-complete", "pytest:test_one.py", "pytest:record-published"]


def test_collection_work_does_not_complete_a_unit(monkeypatch, tmp_path):
    R = _runner()
    nonce = _env(monkeypatch, tmp_path, _COLLECTION_UNITS)
    progress = R.Progress(nonce, "landing", _COLLECTION_UNITS)
    assert progress.accept(E.record("start").rstrip(b"\n")) is False
    # Construct the new wire shape explicitly so the OLD parser can answer
    # the behavioral question without calling an API it did not have.
    row = dict(nonce=nonce, schema=1, scope="landing", total=3, seq=1,
               state="collect_scan", unit=_COLLECTION_UNITS[0],
               completed=0, scanned=1000)
    raw = R.PROGRESS_PREFIX + R._canonical(row)
    try:
        accepted = progress.accept(raw)
    except R.Refusal:
        accepted = False
    assert accepted is True
    assert progress.completed == 0
    with pytest.raises(R.Refusal, match="terminal record"):
        progress.finish()
    with pytest.raises(R.Refusal, match="parent-owned FSM"):
        progress.accept(raw)
    for unit in _COLLECTION_UNITS:
        assert progress.accept(E.record("checkpoint", unit).rstrip(b"\n")) is True
    progress.accept(E.record("terminal").rstrip(b"\n"))
    receipt = progress.finish()
    assert receipt["completed"] == 3
    assert receipt["collect_scanned"] == 1000
    assert receipt["records"] == 6


@pytest.mark.parametrize("change", [
    {"scanned": 0}, {"scanned": 2000}, {"scanned": 1001},
    {"scanned": True}, {"scanned": 1e3}, {"completed": 1},
    {"nonce": "b" * 64}, {"scope": "elsewhere"},
    {"unit": "pytest:test_one.py"}, {"seq": 2}, {"total": 4},
])
def test_forged_collection_work_refuses(monkeypatch, tmp_path, change):
    R = _runner()
    nonce = _env(monkeypatch, tmp_path, _COLLECTION_UNITS)
    progress = R.Progress(nonce, "landing", _COLLECTION_UNITS)
    progress.accept(E.record("start").rstrip(b"\n"))
    row = dict(nonce=nonce, schema=1, scope="landing", total=3, seq=1,
               state="collect_scan", unit=_COLLECTION_UNITS[0],
               completed=0, scanned=1000)
    row.update(change)
    with pytest.raises(R.Refusal):
        progress.accept(R.PROGRESS_PREFIX + R._canonical(row))
    assert progress.completed == 0






@pytest.mark.parametrize("behavior", ["advancing", "stopped", "replayed"])
def test_real_collection_protocol_reaches_outer_supervisor(tmp_path, behavior):
    R = _runner()
    root = tmp_path / "subject"
    evidence = tmp_path / "evidence"
    root.mkdir()
    evidence.mkdir()
    # One real selected file, with enough ordinary scan work to exceed the
    # outer lease. CPU cost per path is solely fixture pacing; checkpoints
    # remain triggered by the shipped +1000 path hook, never by this clock.
    count = 12000 if behavior == "advancing" else 2000
    for i in range(count):
        (root / f"data_{i:05d}.txt").touch()
    (root / "test_one.py").write_text("def test_one(): assert 2 + 2 == 4\n")
    (root / "conftest.py").write_text('''
import time
from pathlib import Path
import _pytest_progress_plugin as P

def pytest_collect_file(file_path, parent):
    until = time.thread_time() + 0.001
    value = 0
    while time.thread_time() < until:
        value = (value * 33 + 7) % 1000003

def pytest_collection_modifyitems(session, config, items):
    behavior = ''' + repr(behavior) + '''
    if behavior == "advancing":
        return
    if behavior == "replayed":
        path = Path(P._path)
        replay = next(line for line in path.read_bytes().splitlines(True)
                      if b'"event":"collect_scan"' in line)
        while True:
            with path.open("ab") as output:
                output.write(replay)
            time.sleep(0.1)
    time.sleep(3600)
''')
    command = [sys.executable, "-B", str(Path(__file__).resolve()),
               "--collection-child", str(root), str(evidence)]
    class AttachedProcess:
        proc = None
        def popen(self, argv):
            assert argv == ["container", "start", "--attach", "bounded-collection"]
            self.proc = subprocess.Popen(command, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, start_new_session=True)
            return self.proc
    adapter = AttachedProcess()
    resources = SimpleNamespace(attach=None)
    progress = R.Progress("a" * 64, "landing", _COLLECTION_UNITS)
    start = time.monotonic()
    rc, reason, receipt = 2, "", None
    try:
        rc, receipt, _streams = R._run_monitored(
            adapter, resources, "bounded-collection", progress, 5,
            evidence / "outer.stdout", evidence / "outer.stderr")
    except R.Refusal as exc:
        reason = str(exc)
    finally:
        if adapter.proc is not None and adapter.proc.poll() is None:
            os.killpg(adapter.proc.pid, signal.SIGTERM)
            adapter.proc.wait(timeout=10)
    result = dict(rc=rc, reason=reason, receipt=receipt,
                  seconds=time.monotonic() - start, completed=progress.completed)
    (evidence / "result.json").write_text(json.dumps(result, sort_keys=True, indent=2))
    probe = json.loads((evidence / "probe.json").read_text())
    assert max(probe["scans"].values()) >= 1000
    if behavior == "advancing":
        assert rc == 0, result
        assert result["seconds"] > 2 * 5, result
        assert receipt["completed"] == len(_COLLECTION_UNITS)
        assert receipt["collect_scanned"] >= 12000
    else:
        assert rc == 2, result
        assert "candidate semantic progress stalled" in reason, result
        assert progress.completed == 0
        assert probe["declared_items"] is None
        if behavior == "replayed":
            assert "non-monotonic sequence" in probe["error"]


if __name__ == "__main__" and sys.argv[1:2] == ["--collection-child"]:
    raise SystemExit(_collection_child(Path(sys.argv[2]), Path(sys.argv[3])))
