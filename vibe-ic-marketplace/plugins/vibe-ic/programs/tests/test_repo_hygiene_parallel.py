"""The local hygiene DAG must be faster without becoming a smaller gate."""
from __future__ import annotations

import concurrent.futures
import importlib.util
import errno
import json
import os
import select
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))
spec = importlib.util.spec_from_file_location(
    "_repo_hygiene_parallel", PROGRAMS / "repo_hygiene_parallel.py")
assert spec and spec.loader
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)
import _watchdog as W

host_spec = importlib.util.spec_from_file_location(
    "_host_independence_pipeline",
    PROGRAMS / "gate_host_independence_check.py")
assert host_spec and host_spec.loader
H = importlib.util.module_from_spec(host_spec)
host_spec.loader.exec_module(H)
from gate_process_attestation import process_attestation


def gate(label, state):
    return {"label": label, "state": state, "seconds": 1,
            "exempt_until": None, "exempt_reason": None,
            "exemption_expired": False}


def fixture():
    reference = {
        "gates": [gate("ordinary", "LISTED"),
                  gate(P.HOST_LABEL, "LISTED")],
        "corpora": [], "undisclosed_loops": [], "today": "2026-08-16",
    }
    a = {"listed_only": False, "shard": "0/2", "gates": [
        gate("ordinary", "PASS"), gate(P.HOST_LABEL, "OTHER_SHARD")],
         "corpora": [], "undisclosed_loops": [], "today": "2026-08-16",
         "wiring_errors": []}
    b = {"listed_only": False, "shard": "1/2", "gates": [
        gate("ordinary", "OTHER_SHARD"), gate(P.HOST_LABEL, "PASS")],
         "corpora": [], "undisclosed_loops": [], "today": "2026-08-16",
         "wiring_errors": []}
    attest = [{"label": "ordinary", "complete": True},
              {"label": P.HOST_LABEL, "complete": True}]
    return reference, a, b, attest


def test_complete_dag_preserves_full_dispatch_summary():
    reference, a, b, attest = fixture()
    problems = []
    doc = P.merge_records(reference, [(Path("a"), a), (Path("b"), b)],
                          attest, 12, problems)
    assert problems == []
    assert doc["declared"] == doc["decided"] == doc["passed"] == 2
    assert doc["other_shard"] == 0
    assert doc["parallel"]["complete"] is True
    assert P._summary_rc(doc) == 0
    assert P._completion_message(doc, 12).startswith("[PASS]")


def test_complete_coverage_with_a_red_gate_is_reported_as_fail():
    reference, a, b, attest = fixture()
    a["gates"][0] = gate("ordinary", "FAIL")
    problems = []
    doc = P.merge_records(reference, [(Path("a"), a), (Path("b"), b)],
                          attest, 12, problems)
    assert problems == []
    assert P._summary_rc(doc) == 1
    assert P._completion_message(doc, 12).startswith("[FAIL]")
    assert "failed=1" in P._completion_message(doc, 12)


def test_missing_shard_gate_is_named_and_refused():
    reference, a, _, attest = fixture()
    problems = []
    doc = P.merge_records(reference, [(Path("a"), a)], attest, 12, problems)
    assert any(P.HOST_LABEL in problem for problem in problems)
    assert doc["parallel"]["complete"] is False
    assert P._summary_rc(doc) == 2


def test_duplicate_owner_is_named_and_refused():
    reference, a, b, attest = fixture()
    duplicate = dict(b)
    duplicate["gates"] = [gate("ordinary", "PASS"),
                          gate(P.HOST_LABEL, "PASS")]
    problems = []
    doc = P.merge_records(reference,
                          [(Path("a"), a), (Path("b"), duplicate)],
                          attest, 12, problems)
    assert any("ordinary" in problem and "got 2" in problem
               for problem in problems)
    assert P._summary_rc(doc) == 2


def test_missing_process_attestation_cannot_become_green():
    reference, a, b, attest = fixture()
    problems = []
    doc = P.merge_records(reference, [(Path("a"), a), (Path("b"), b)],
                          attest[:1], 12, problems)
    assert any(P.HOST_LABEL in problem and "attestation" in problem
               for problem in problems)
    assert P._summary_rc(doc) == 2


def test_worker_waits_for_completion_while_progress_events_keep_advancing(
        tmp_path, monkeypatch):
    """A slow run is not killed for exceeding an estimated runtime.

    It emits no stdout; only the owner progress file advances.  The total run
    intentionally lasts several stall windows, proving each measured event
    resets supervision until the process exits naturally.
    """
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.05)
    progress = tmp_path / "live.jsonl"
    child = (
        "import pathlib,sys,time\n"
        "p=pathlib.Path(sys.argv[1])\n"
        "for i in range(8):\n"
        " p.open('a').write(str(i)+'\\n')\n"
        " time.sleep(0.12)\n"
    )
    started = time.monotonic()
    rc, out, problem = P._run(
        [sys.executable, "-c", child, str(progress)], tmp_path,
        os.environ.copy(), progress_path=progress, stall_grace_s=0.3)
    assert time.monotonic() - started > 0.8
    assert (rc, problem) == (0, None), (rc, out, problem)
    assert progress.read_text().splitlines()[-1] == "7"


def test_worker_classifies_silent_idle_process_as_stalled_not_timed_out(
        tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.05)
    rc, out, problem = P._run(
        [sys.executable, "-c", "import time; time.sleep(30)"], tmp_path,
        os.environ.copy(), stall_grace_s=0.3)
    assert rc == W.RC_STALLED
    assert "WATCHDOG_STALLED" in out
    assert problem and "outcome=stalled" in problem


def test_launch_critical_section_does_not_block_term_in_the_job(
        tmp_path, monkeypatch):
    """The helper's registration mask must not leak through exec."""
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.05)
    marker = tmp_path / "graceful-term-observed"
    child = (
        "import pathlib,signal,sys,time\n"
        "marker=pathlib.Path(sys.argv[1])\n"
        "def stop(_signum,_frame):\n"
        " marker.write_text('TERM\\n')\n"
        " raise SystemExit(0)\n"
        "signal.signal(signal.SIGTERM,stop)\n"
        "time.sleep(30)\n"
    )
    rc, out, problem = P._run(
        [sys.executable, "-c", child, str(marker)], tmp_path,
        os.environ.copy(), stall_grace_s=0.3)
    assert rc == W.RC_STALLED, (rc, out, problem)
    assert marker.read_text(encoding="utf-8") == "TERM\n"


def test_parallel_runs_keep_each_helpers_wait_status_isolated(
        tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.05)

    def invoke(code):
        return P._run(
            [sys.executable, "-c",
             f"import time; time.sleep(0.1); raise SystemExit({code})"],
            tmp_path, os.environ.copy(), stall_grace_s=0.3)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(invoke, [3, 7]))
    assert [(rc, problem) for rc, _out, problem in results] == [
        (3, None), (7, None)]


def _require_pidfd_events():
    if (not hasattr(os, "pidfd_open")
            or not hasattr(signal, "pidfd_send_signal")
            or not hasattr(select, "poll") or not Path("/proc").is_dir()):
        pytest.skip("Linux pidfd process-exit events are unavailable")
    try:
        probe = os.pidfd_open(os.getpid())
    except OSError as exc:
        pytest.skip(f"the running kernel cannot provide pidfd events: {exc}")
    else:
        os.close(probe)


def _observe_identity(path: Path, done: threading.Event, holder: dict) -> None:
    """Open the child's pidfd while its published starttime still matches."""
    while not done.is_set():
        try:
            fields = path.read_text(encoding="utf-8").split()
            if len(fields) != 3:
                raise ValueError("identity needs PID, PGRP and starttime")
            pid, pgrp, starttime = (int(field) for field in fields)
            pidfd = os.pidfd_open(pid)
            raw = Path(f"/proc/{pid}/stat").read_text()
            current = int(raw[raw.rfind(")") + 2:].split()[19])
            if current != starttime:
                os.close(pidfd)
                holder["error"] = (
                    f"PID_REUSED: {pid} {starttime} -> {current}")
            else:
                holder.update(pid=pid, pgrp=pgrp, starttime=starttime,
                              pidfd=pidfd)
            return
        except (FileNotFoundError, ProcessLookupError, ValueError):
            time.sleep(0)


def _stalling_tree(tmp_path: Path, monkeypatch, *, detached: bool,
                   trigger: Path | None = None, late_write: Path | None = None):
    """Run a real silent stall and retain the grandchild's kernel exit event."""
    _require_pidfd_events()
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.05)
    ready = tmp_path / ("setsid.identity" if detached else "group.identity")
    done = threading.Event()
    identity: dict = {}
    observer = threading.Thread(
        target=_observe_identity, args=(ready, done, identity), daemon=True)
    observer.start()

    setup = "os.setsid()\n" if detached else ""
    fifo_setup = (
        "fifo=os.open(sys.argv[2], os.O_RDWR | os.O_NONBLOCK)\n"
        if trigger is not None else "")
    tail = (
        "os.read(fifo, 1)\n"
        "pathlib.Path(sys.argv[3]).write_text('ESCAPED_LATE_WRITE\\n')\n"
        if trigger is not None else "time.sleep(30)\n")
    grandchild = (
        "import os,pathlib,signal,sys,time\n"
        f"{setup}"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "pid=os.getpid(); pgrp=os.getpgrp()\n"
        "raw=pathlib.Path('/proc/self/stat').read_text()\n"
        "start=int(raw[raw.rfind(')')+2:].split()[19])\n"
        f"{fifo_setup}"
        "os.close(1); os.close(2)\n"
        "ready=pathlib.Path(sys.argv[1])\n"
        "staged=ready.with_name(ready.name+'.tmp-'+str(pid))\n"
        "staged.write_text(f'{pid} {pgrp} {start}\\n')\n"
        "os.replace(staged, ready)\n"
        f"{tail}"
    )
    child_args = ["sys.argv[1]"]
    if trigger is not None:
        child_args.extend(["sys.argv[2]", "sys.argv[3]"])
    parent = (
        "import os,pathlib,subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}, "
        + ", ".join(child_args) + "])\n"
        "ready=pathlib.Path(sys.argv[1])\n"
        "while not ready.is_file():\n"
        " print('waiting-for-owned-identity', flush=True)\n"
        " time.sleep(0.01)\n"
        "os.close(1); os.close(2)\n"
        "time.sleep(30)\n"
    )
    argv = [sys.executable, "-c", parent, str(ready)]
    if trigger is not None:
        argv.extend([str(trigger), str(late_write)])
    try:
        rc, out, problem = P._run(
            argv, tmp_path, os.environ.copy(), stall_grace_s=0.25)
    finally:
        done.set()
        observer.join()
    assert "error" not in identity, identity.get("error")
    assert "pidfd" in identity, (
        f"child identity was never observed; ready={ready.exists()}")
    return rc, out, problem, identity


def _assert_owned_exit(rc, out, problem, identity, *, detached: bool):
    pidfd = identity["pidfd"]
    poller = select.poll()
    poller.register(pidfd, select.POLLIN | select.POLLHUP | select.POLLERR)
    exited = bool(poller.poll(0))
    if not exited:
        # A failing candidate must not leak the fixture into later tests.
        signal.pidfd_send_signal(pidfd, signal.SIGKILL)
        poller.poll()
    os.close(pidfd)
    assert rc == W.RC_STALLED and problem, (rc, out, problem)
    assert "outcome=stalled" in problem
    assert exited is True, (
        f"ESCAPED_ALIVE={not exited}; pid={identity['pid']}; "
        f"starttime={identity['starttime']}; detached={detached}")
    if detached:
        assert identity["pgrp"] == identity["pid"], identity
    else:
        assert identity["pgrp"] != identity["pid"], identity


@pytest.mark.parametrize("detached", [False, True], ids=["same-pgrp", "setsid"])
def test_stall_returns_only_after_every_owned_descendant_exits(
        tmp_path, monkeypatch, detached):
    result = _stalling_tree(tmp_path, monkeypatch, detached=detached)
    _assert_owned_exit(*result, detached=detached)


def test_setsid_descendant_cannot_perform_a_late_write_after_run_returns(
        tmp_path, monkeypatch):
    trigger = tmp_path / "late-write.trigger"
    late_write = tmp_path / "late-write.txt"
    os.mkfifo(trigger)
    result = _stalling_tree(
        tmp_path, monkeypatch, detached=True,
        trigger=trigger, late_write=late_write)
    _assert_owned_exit(*result, detached=True)
    with pytest.raises(OSError) as exc:
        writer = os.open(trigger, os.O_WRONLY | os.O_NONBLOCK)
        os.close(writer)
    assert exc.value.errno == errno.ENXIO, exc.value
    assert not late_write.exists(), (
        "an owned setsid descendant remained able to write after _run returned")


def test_pidfd_unavailable_refuses_before_launch(tmp_path, monkeypatch):
    marker = tmp_path / "must-not-launch"
    monkeypatch.delattr(P._owned.os, "pidfd_open")
    result = P._owned.run_owned(
        [sys.executable, "-c",
         f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')"],
        tmp_path, os.environ.copy(), progress_path=None,
        stall_grace_s=0.25, poll_s=0.05)
    assert result.launched is False
    assert result.rc == 2
    assert result.final_descendants == []
    assert result.census_ok is False
    assert result.problem and "pidfd_open is unavailable" in result.problem
    assert not marker.exists(), "an unowned process was launched fail-open"


def test_pid_reuse_between_census_and_pidfd_open_fails_closed(monkeypatch):
    real_open = os.open
    readings = iter([(1, 12345), (1, 54321)])
    monkeypatch.setattr(
        P._owned, "_read_proc_identity", lambda _pid: next(readings))
    monkeypatch.setattr(
        P._owned.os, "pidfd_open",
        lambda _pid: real_open("/dev/null", os.O_RDONLY))
    pidfd, identity_ok = P._owned._open_identity_pidfd((777, 12345))
    assert pidfd is None
    assert identity_ok is False, (
        "a reused PID was accepted as the originally-owned process")


def test_reused_root_pid_is_not_walked_as_the_launched_tree(monkeypatch):
    supervisor = os.getpid()
    monkeypatch.setattr(P._owned, "_proc_snapshot_checked", lambda: ({
        supervisor: (1, 100),
        777: (1, 54321),       # same PID, not launched starttime 12345
        888: (777, 60000),     # belongs to the replacement, not our job
    }, True))
    owned, census_ok = P._owned._job_processes_checked((777, 12345), set())
    assert owned == set(), owned
    assert census_ok is False, (
        "a reused root PID was treated as the original ancestry root")


def test_dispatcher_refuses_a_nonzero_final_descendant_census(
        tmp_path, monkeypatch):
    forged = tmp_path / "forged-final-census.py"
    forged.write_text(
        "import json,sys\n"
        "from pathlib import Path\n"
        "result=Path(sys.argv[sys.argv.index('--result')+1])\n"
        "result.write_text(json.dumps({"
        "'protocol':1,'rc':0,'body':'','problem':None,'outcome':'natural',"
        "'launched':True,'census_ok':True,"
        "'final_descendants':[{'pid':123,'starttime':456}],"
        "'observed':[{'pid':123,'starttime':456}],"
        "'capability_error':''}))\n",
        encoding="utf-8")
    monkeypatch.setattr(P._owned, "__file__", str(forged))
    rc, _out, problem = P._run(
        [sys.executable, "-c", "raise SystemExit(0)"], tmp_path,
        os.environ.copy())
    assert rc == 2
    assert problem and "final descendant census is not zero" in problem


def test_transient_incomplete_census_cannot_publish_zero_with_live_descendant(
        tmp_path, monkeypatch):
    """UNKNOWN /proc state is not proof that an adopted daemon vanished."""
    _require_pidfd_events()
    ready = tmp_path / "transient-census.identity"
    real_snapshot = P._owned._proc_snapshot_checked
    scans = 0

    def transiently_incomplete_snapshot():
        nonlocal scans
        scans += 1
        # Calls 1-2 are the pre-launch capability/baseline reads.  Hide the
        # adopted daemon from the first five post-launch reads, then recover.
        # The production failure was that two empty-but-incomplete reads were
        # accepted as a final zero before recovery could expose the live child.
        if 3 <= scans <= 7:
            own = P._owned._read_proc_identity(os.getpid())
            return ({os.getpid(): own} if own is not None else {}, False)
        return real_snapshot()

    monkeypatch.setattr(
        P._owned, "_proc_snapshot_checked", transiently_incomplete_snapshot)
    daemon = (
        "import os,pathlib,signal,sys,time\n"
        "os.setsid()\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "raw=pathlib.Path('/proc/self/stat').read_text()\n"
        "start=int(raw[raw.rfind(')')+2:].split()[19])\n"
        "pathlib.Path(sys.argv[1]).write_text(f'{os.getpid()} {start}\\n')\n"
        "time.sleep(30)\n"
    )
    parent = (
        "import pathlib,subprocess,sys,time\n"
        f"subprocess.Popen([sys.executable, '-c', {daemon!r}, sys.argv[1]])\n"
        "p=pathlib.Path(sys.argv[1])\n"
        "while not p.is_file(): time.sleep(0.001)\n"
    )
    result = P._owned.run_owned(
        [sys.executable, "-c", parent, str(ready)], tmp_path,
        os.environ.copy(), progress_path=None,
        stall_grace_s=1, poll_s=0.02)
    pid, _starttime = (int(value) for value in ready.read_text().split())
    try:
        pidfd = os.pidfd_open(pid)
    except ProcessLookupError:
        pidfd = None
        alive = False
    else:
        poller = select.poll()
        poller.register(pidfd, select.POLLIN | select.POLLHUP | select.POLLERR)
        alive = not bool(poller.poll(0))
    if alive:
        signal.pidfd_send_signal(pidfd, signal.SIGKILL)
        poller.poll()
    if pidfd is not None:
        os.close(pidfd)
    assert alive is False, (
        "INCOMPLETE_CENSUS_PUBLISHED_ZERO_WITH_LIVE_DESCENDANT: "
        f"result={result}; scans={scans}")


def test_launch_registration_masks_term_and_owns_identity_read_failure(
        tmp_path):
    """TERM between Popen and registration cannot outrun pidfd ownership."""
    _require_pidfd_events()
    identity = tmp_path / "launch-window.identity"
    pidfd_marker = tmp_path / "launch-window.pidfd-opened"
    inner = r'''
import os, signal, sys
from pathlib import Path
import _owned_process_supervisor as owned

identity_path = Path(sys.argv[1])
pidfd_marker = Path(sys.argv[2])
real_read = owned._read_proc_identity
real_pidfd_open = owned.os.pidfd_open
fired = False

def traced_pidfd_open(pid, *args, **kwargs):
    value = real_pidfd_open(pid, *args, **kwargs)
    current = real_read(pid)
    if pid != os.getpid() and current is not None and current[0] == os.getpid():
        pidfd_marker.write_text(str(pid))
    return value

def fail_during_registration(pid):
    global fired
    value = real_read(pid)
    if not fired and value is not None and pid != os.getpid() and value[0] == os.getpid():
        fired = True
        identity_path.write_text(f"{pid} {value[1]}\n")
        os.kill(os.getpid(), signal.SIGTERM)
        raise OSError("INJECTED_IDENTITY_READ_FAILURE")
    return value

owned.os.pidfd_open = traced_pidfd_open
owned._read_proc_identity = fail_during_registration
owned.run_owned(
    [sys.executable, "-c",
     "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)"],
    Path.cwd(), os.environ.copy(), progress_path=None,
    stall_grace_s=5, poll_s=0.05)
'''
    env = os.environ.copy()
    env["PYTHONPATH"] = (str(PROGRAMS) + os.pathsep
                         + env.get("PYTHONPATH", ""))
    helper = subprocess.run(
        [sys.executable, "-c", inner, str(identity), str(pidfd_marker)],
        env=env, capture_output=True, text=True)
    pid, _starttime = (int(value) for value in identity.read_text().split())
    try:
        pidfd = os.pidfd_open(pid)
    except ProcessLookupError:
        pidfd = None
        alive = False
    else:
        poller = select.poll()
        poller.register(pidfd, select.POLLIN | select.POLLHUP | select.POLLERR)
        alive = not bool(poller.poll(0))
    if alive:
        signal.pidfd_send_signal(pidfd, signal.SIGKILL)
        poller.poll()
    if pidfd is not None:
        os.close(pidfd)
    observed = {
        "helper_rc": helper.returncode,
        "root_pidfd_opened": pidfd_marker.is_file(),
        "child_alive": alive,
    }
    assert observed == {
        "helper_rc": 128 + signal.SIGTERM,
        "root_pidfd_opened": True,
        "child_alive": False,
    }, observed


def test_post_sigkill_pidfd_wait_has_a_finite_observation_cadence(monkeypatch):
    """A reaper may wait forever overall, but each wait must stay observable."""
    calls = []

    class ObservablePoll:
        def register(self, _fd, _events):
            pass

        def unregister(self, _fd):
            pass

        def poll(self, milliseconds=None):
            calls.append(milliseconds)
            return [(123, select.POLLIN)]

    monkeypatch.setattr(P._owned.select, "poll", ObservablePoll)
    P._owned._wait_pidfds({123: (456, 789)})
    assert calls == [100], (
        f"UNOBSERVABLE_TERMINATION_WAIT: poll arguments={calls}")


def test_reentrant_shutdown_signal_cannot_interrupt_owned_cleanup(monkeypatch):
    monkeypatch.setattr(P._owned, "_IN_SHUTDOWN", True)
    assert P._owned._shutdown_handler(signal.SIGINT, None) is None


def test_dispatcher_returns_rc2_when_reaper_reports_termination_pending(
        tmp_path, monkeypatch):
    """Post-SIGKILL uncertainty blocks without blocking the dispatcher."""
    wrapper = tmp_path / "forced_pending_supervisor.py"
    wrapper.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(PROGRAMS)!r})\n"
        "import _owned_process_supervisor as owned\n"
        "owned._wait_pidfds_until = lambda handles, deadline: dict(handles)\n"
        "raise SystemExit(owned.main())\n",
        encoding="utf-8")
    monkeypatch.setattr(P._owned, "__file__", str(wrapper))
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.02)
    rc, _out, problem = P._run(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp_path, os.environ.copy(), stall_grace_s=0.15)
    observed = {
        "rc": rc,
        "termination_pending": bool(
            problem and "OWNED_SUPERVISOR_TERMINATION_PENDING" in problem),
    }
    assert observed == {"rc": 2, "termination_pending": True}, observed


def test_pending_sidecar_failure_keeps_cleanup_owned_and_returns_rc2(
        tmp_path, monkeypatch):
    """Observability I/O failure must not tear down the sole subreaper."""
    wrapper = tmp_path / "failed_pending_sidecar_supervisor.py"
    wrapper.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(PROGRAMS)!r})\n"
        "import _owned_process_supervisor as owned\n"
        "real_write_json = owned.write_json\n"
        "def fail_pending(path, value, **kwargs):\n"
        " if value.get('state') == 'termination_pending':\n"
        "  raise OSError('INJECTED_PENDING_SIDECAR_FAILURE')\n"
        " return real_write_json(path, value, **kwargs)\n"
        "owned.write_json = fail_pending\n"
        "owned._wait_pidfds_until = lambda handles, deadline: dict(handles)\n"
        "raise SystemExit(owned.main())\n",
        encoding="utf-8")
    monkeypatch.setattr(P._owned, "__file__", str(wrapper))
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.02)
    rc, _out, problem = P._run(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        tmp_path, os.environ.copy(), stall_grace_s=0.15)
    assert rc == 2
    assert problem and "durable pending sidecar failed" in problem
    assert "INJECTED_PENDING_SIDECAR_FAILURE" in problem


def _attest(path: Path, output: str = "[PASS] same"):
    row = process_attestation("ordinary", output, 0, ["python3", "gate.py"])
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")


def test_pipelined_host_comparison_accepts_matching_machine_records(
        tmp_path, monkeypatch):
    monkeypatch.setattr(H, "corpus_gates", lambda _script: [
        H.Gate("ordinary", "$ROOT", "python3 gate.py", None)])
    monkeypatch.setattr(H, "checkout_dirt", lambda _root, _timeout:
                        H.Dirt([], ["?? stimulus"], [], True))
    monkeypatch.setattr(H, "inert_exclusions", lambda _script: [])
    monkeypatch.setattr(H, "sweep_abandoned_scratch", lambda _root: {})
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _attest(a)
    _attest(b)
    result = H.precomputed_audit(tmp_path, a, b)
    assert result.verdict == "PASS"
    assert result.declared == result.probed == 1


def test_pipelined_host_comparison_refuses_a_semantic_mismatch(
        tmp_path, monkeypatch):
    monkeypatch.setattr(H, "corpus_gates", lambda _script: [
        H.Gate("ordinary", "$ROOT", "python3 gate.py", None)])
    monkeypatch.setattr(H, "checkout_dirt", lambda _root, _timeout:
                        H.Dirt([], ["?? stimulus"], [], True))
    monkeypatch.setattr(H, "inert_exclusions", lambda _script: [])
    monkeypatch.setattr(H, "sweep_abandoned_scratch", lambda _root: {})
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    _attest(a, "[PASS] same")
    _attest(b, "[FAIL] changed")
    result = H.precomputed_audit(tmp_path, a, b)
    assert result.verdict == "FAIL"
    assert result.findings[0]["kind"] == "HOST_OR_NONDETERMINISTIC_VERDICT"
