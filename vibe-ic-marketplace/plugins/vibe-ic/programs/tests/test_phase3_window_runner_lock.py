"""A bounded Phase-3 window re-enters its parent's project lock (#588).

The orchestrator (``vibe_ic_one_shot_runner --entry-step 15 --exit-step
38``) holds ``<project>/.runner.lock`` and hands its child the
re-entrancy token.  The window child must make the SAME re-entrancy
decision ``_runner_lock.acquire_or_reenter`` makes -- read-only, since a
window never writes into the project -- and a private copy of the
project must not inherit the parent's live lock and refuse its own
enclosing run.  A genuinely concurrent holder must still be refused.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import _runner_lock
import phase3_one_shot_runner as p3

DEADLINE_S = 300


def _running(pid: int) -> bool:
    """A process that still runs. `kill(pid, 0)` (`_runner_lock._pid_alive`)
    also succeeds on a zombie -- a child the group kill took down that no
    one has reaped yet, as under a subreaper that reaps only at the end."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat.rsplit(")", 1)[-1].split()[0] not in ("Z", "X", "x")


def _write_lock(project: Path, pid: int) -> bytes:
    lock = project / _runner_lock.LOCK_FILENAME
    lock.write_text(json.dumps({"pid": pid, "timestamp": "x",
                                "runner": "vibe_ic_one_shot_runner"}))
    return lock.read_bytes()


def _run_window(project: Path, token):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop(_runner_lock.REENTRANCY_ENV, None)
    if token is not None:
        env[_runner_lock.REENTRANCY_ENV] = token
    return subprocess.run(
        [sys.executable, str(Path(p3.__file__)), str(project),
         "--entry-step", "15", "--exit-step", "38"],
        env=env, capture_output=True, text=True, check=False,
        timeout=DEADLINE_S)


@pytest.fixture
def project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    return project


@pytest.fixture
def stranger():
    proc = subprocess.Popen(["sleep", "120"])
    yield proc.pid
    proc.kill()
    proc.wait(timeout=30)


def test_window_child_reenters_its_parents_lock(project):
    lock_bytes = _write_lock(project, os.getpid())
    before = p3._phase3_file_manifest(project)
    cp = _run_window(project, f"{os.getpid()}:{project.resolve()}")
    assert "CONCURRENT_RUN_REFUSED" not in cp.stderr, cp.stderr
    assert "RUNNER_LOCK_REENTRANT" in cp.stderr, cp.stderr
    # Past the lock, the unadmitted empty project is refused by name later.
    assert "REFUSED" in cp.stderr
    assert (project / _runner_lock.LOCK_FILENAME).read_bytes() == lock_bytes
    assert p3._phase3_file_manifest(project) == before


def _assert_refusal_discloses(cp, project: Path, holder: int, why: str):
    assert cp.returncode == 3
    line = [l for l in cp.stderr.splitlines()
            if l.startswith("CONCURRENT_RUN_REFUSED")]
    assert line, cp.stderr
    line = line[0]
    assert f"pid={holder}" in line
    assert "runner=vibe_ic_one_shot_runner" in line and "since=x" in line
    assert str(project / _runner_lock.LOCK_FILENAME) in line
    assert why in line, line
    assert _runner_lock.REENTRANCY_ENV in line.split(why, 1)[1]


def test_window_without_token_still_refuses_live_lock(project):
    lock_bytes = _write_lock(project, os.getpid())
    cp = _run_window(project, None)
    _assert_refusal_discloses(cp, project, os.getpid(), "no "
                              + _runner_lock.REENTRANCY_ENV + " token")
    assert (project / _runner_lock.LOCK_FILENAME).read_bytes() == lock_bytes


def test_window_token_for_other_project_still_refuses(project, tmp_path):
    _write_lock(project, os.getpid())
    other = (tmp_path / 'other').resolve()
    cp = _run_window(project, f"{os.getpid()}:{other}")
    _assert_refusal_discloses(cp, project, os.getpid(),
                              f"names project {other}")


def test_window_token_not_naming_the_live_holder_still_refuses(project,
                                                                stranger):
    _write_lock(project, stranger)
    cp = _run_window(project, f"{os.getpid()}:{project.resolve()}")
    _assert_refusal_discloses(
        cp, project, stranger,
        f"names pid {os.getpid()}, but the lock is held by pid {stranger}")


def test_reentrant_holder_pid_is_the_acquire_or_reenter_decision(
        project, stranger, monkeypatch):
    env = _runner_lock.REENTRANCY_ENV
    _write_lock(project, os.getpid())
    monkeypatch.setenv(env, f"{os.getpid()}:{project.resolve()}")
    assert _runner_lock.reentrant_holder_pid(project) == os.getpid()
    monkeypatch.setenv(env, f"{os.getpid()}:{project.parent.resolve()}")
    assert _runner_lock.reentrant_holder_pid(project) is None
    monkeypatch.delenv(env)
    assert _runner_lock.reentrant_holder_pid(project) is None
    monkeypatch.setenv(env, "garbage")
    assert _runner_lock.reentrant_holder_pid(project) is None
    (project / _runner_lock.LOCK_FILENAME).write_text('{"pid": "x"}')
    monkeypatch.setenv(env, f"{os.getpid()}:{project.resolve()}")
    assert _runner_lock.reentrant_holder_pid(project) is None
    _write_lock(project, stranger)
    assert _runner_lock.reentrant_holder_pid(project) is None


def test_window_clone_does_not_inherit_the_source_lock(project, tmp_path):
    (project / "input.txt").write_text("content")
    lock_bytes = _write_lock(project, os.getpid())
    clone = tmp_path / "clone" / "project"
    clone.parent.mkdir()
    p3._phase3_window_clone(project, clone)
    assert (clone / "input.txt").read_text() == "content"
    assert not (clone / _runner_lock.LOCK_FILENAME).exists()
    assert (project / _runner_lock.LOCK_FILENAME).read_bytes() == lock_bytes


def _window_log(project: Path, run_id: str) -> Path:
    return (project.parent / ".phase3_window_runs" / project.name / run_id
            / "enclosing_phase3.stderr.log")


def _enclose(project: Path):
    return p3._phase3_window_enclosing(
        project, "top", SimpleNamespace(name="gf180mcuD"),
        SimpleNamespace(container="vibeic-eda"), {"23"}, unit="phase3")


def test_enclosing_phase3_runs_on_its_copy_under_the_parents_token(
        project, monkeypatch):
    """The real enclosing unit: clone, then the unbounded phase3 CLI on the
    copy under the watchdog, inheriting the parent's token.  Its stderr is
    kept in the window's own run dir, which is how this is observed."""
    lock_bytes = _write_lock(project, os.getpid())
    before = p3._phase3_file_manifest(project)
    monkeypatch.setenv(_runner_lock.REENTRANCY_ENV,
                       f"{os.getpid()}:{project.resolve()}")
    monkeypatch.setenv("VIBEIC_PHASE3_WINDOW_RUN_ID", "lockrun")
    monkeypatch.setattr(p3, "_WATCHDOG_STALL_GRACE_S", 120)
    row = _enclose(project)
    log = _window_log(project, "lockrun")
    assert log.is_file(), row.detail
    assert str(log) in row.detail
    assert log.read_text().strip(), "the grandchild's stderr was not kept"
    assert "CONCURRENT_RUN_REFUSED" not in log.read_text(), log.read_text()
    assert (project / _runner_lock.LOCK_FILENAME).read_bytes() == lock_bytes
    assert p3._phase3_file_manifest(project) == before


def test_window_control_lock_stays_under_writable_project(project):
    """A bind-mounted ``/project`` may have an unwritable parent (``/``).

    Bounded-window coordination is runtime control state, so it belongs in
    the project's writable ``.vibeic`` tree instead of beside the mount.
    """
    lock_root = p3._phase3_window_lock_root(project)
    assert lock_root == project / ".vibeic/phase3-window-lock"
    assert lock_root.is_relative_to(project)


def test_window_admission_clone_uses_runtime_scratch(tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(p3.tempfile, "tempdir", str(scratch))
    assert p3._phase3_admission_temp_root() == scratch


def test_enclosing_phase3_hang_is_stopped_by_the_watchdog(
        project, monkeypatch, tmp_path):
    """A grandchild that makes no forward progress is killed with its whole
    process group and reported NOT_MEASURED (stalled) with its reason."""
    pidfile = tmp_path / "orphan.pid"
    hang = ("import subprocess, sys, time\n"
            "p = subprocess.Popen(['sleep', '90'])\n"
            f"open({str(pidfile)!r}, 'w').write(str(p.pid))\n"
            "sys.stderr.write('hang-marker\\n'); sys.stderr.flush()\n"
            "time.sleep(60)\n")
    monkeypatch.setattr(p3, "_phase3_enclosing_cmd",
                        lambda *a: [sys.executable, "-c", hang])
    monkeypatch.setattr(p3, "_WATCHDOG_STALL_GRACE_S", 2)
    monkeypatch.setenv("VIBEIC_PHASE3_WINDOW_RUN_ID", "hangrun")
    before = p3._phase3_file_manifest(project)
    row = _enclose(project)
    assert row.status == "NOT_MEASURED", row.detail
    assert row.reason_class == p3._V.ReasonClass.STALLED
    assert "watchdog stopped as hung" in row.detail
    assert "> 2s" in row.detail and "Remedy" in row.detail
    assert "hang-marker" in row.detail
    log = _window_log(project, "hangrun")
    assert str(log) in row.detail and "hang-marker" in log.read_text()
    assert row.duration_s < 50
    orphan = int(pidfile.read_text())
    deadline = time.monotonic() + 10
    while _running(orphan) and time.monotonic() < deadline:
        time.sleep(0.2)
    alive = _running(orphan)
    if alive:
        os.kill(orphan, 9)
    assert not alive, "the grandchild's process group outlived the stop"
    assert p3._phase3_file_manifest(project) == before


def test_enclosing_phase3_failure_keeps_and_surfaces_stderr(
        project, monkeypatch, capsys):
    fail = ("import sys\n"
            f"print({BANNER!r})\n"
            "for i in range(30): sys.stderr.write(f'line-{i}\\n')\n"
            "sys.exit(7)\n")
    monkeypatch.setattr(p3, "_phase3_enclosing_cmd",
                        lambda *a: [sys.executable, "-c", fail])
    monkeypatch.setenv("VIBEIC_PHASE3_WINDOW_RUN_ID", "failrun")
    row = _enclose(project)
    # It RAN and failed: a plain FAIL (owner outcome-state ruling), never a
    # NOT_MEASURED about something that could not be run.
    assert row.status == "FAIL", row.detail
    assert not row.reason_class
    assert "enclosing rc=7" in row.detail
    assert "ran and exited rc=7 with no verdict" in row.detail
    assert "line-29" in row.detail and "line-5\n" not in row.detail
    log = _window_log(project, "failrun")
    assert log.read_text().splitlines() == [f"line-{i}" for i in range(30)]
    err = capsys.readouterr().err
    assert "ENCLOSING_PHASE3_RC=7" in err and "line-29" in err
    assert str(log) in err
    assert "top=top" in log.with_name("enclosing_phase3.stdout.log").read_text()


def test_a_zombie_is_not_a_surviving_orphan():
    """The liveness read the hang test relies on: an exited, unreaped child
    is a zombie, which `kill(pid, 0)` still reports alive."""
    child = subprocess.Popen(["true"])
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{child.pid}/stat").read_text()
        except OSError:
            break
        if state.rsplit(")", 1)[-1].split()[0] == "Z":
            break
        time.sleep(0.05)
    try:
        assert _runner_lock._pid_alive(child.pid)
        assert not _running(child.pid)
    finally:
        child.wait(timeout=10)
    assert not _running(child.pid)
    sleeper = subprocess.Popen(["sleep", "30"])
    try:
        assert _running(sleeper.pid)
    finally:
        sleeper.kill()
        sleeper.wait(timeout=10)


#: What `main` prints once admission and PDK resolution are done (the run
#: banner), spelled as the runner prints it.
BANNER = "=== phase3_one_shot_runner — pdk=x top=top ==="


def test_the_run_banner_is_the_one_main_prints():
    src = Path(p3.__file__).read_text()
    assert BANNER.startswith(p3._PHASE3_RUN_BANNER)
    assert "_print_run_banner(pdk.name, effective_top, args.top_name)" in src


def _enclose_with(project, monkeypatch, code, run_id, steps=("23",)):
    """A stand-in unit: `code` runs with the private copy as argv[1]."""
    monkeypatch.setattr(p3, "_phase3_enclosing_cmd",
                        lambda iso, *a: [sys.executable, "-c", code, str(iso)])
    monkeypatch.setenv("VIBEIC_PHASE3_WINDOW_RUN_ID", run_id)
    return p3._phase3_window_enclosing(
        project, "top", SimpleNamespace(name="gf180mcuD"),
        SimpleNamespace(container="vibeic-eda"), set(steps), unit="phase3")


def _unit(report=None, rc=1, banner=True, outputs=()):
    """A unit that got past admission (its banner), wrote `outputs` and its
    own report in the copy it was handed, then exited `rc`."""
    rel = str(p3._pl.report_path(Path("ISO"), "phase3_one_shot.json")
              .relative_to("ISO"))
    code = "import json, pathlib, sys\niso = pathlib.Path(sys.argv[1])\n"
    if banner:
        code += f"print({BANNER!r})\n"
    for out in outputs:
        code += (f"q = iso / {out!r}; q.parent.mkdir(parents=True, exist_ok=True);"
                 f" q.write_text('produced')\n")
    if report is not None:
        code += (f"q = iso / {rel!r}; q.parent.mkdir(parents=True, exist_ok=True)\n"
                 f"q.write_text(json.dumps({report!r}))\n")
    return code + f"sys.exit({rc})\n"


def _rows(*rows):
    return {"verdict": "FAIL", "steps": [
        dict(zip(("name", "status", "detail", "reason_class"), r)) for r in rows]}


def test_reportless_host_shortfall_is_found_beyond_the_display_tail():
    banner = p3._PHASE3_RUN_BANNER + "fixture"
    marker = "No space left on device"
    stderr = marker + "\n" + ("x" * 5000)
    status, reason, detail = p3._enclosing_phase3_outcome(
        1, banner, stderr, None, {"15"}, False)
    assert status == "NOT_MEASURED"
    assert reason == p3._V.ReasonClass.EXECUTION_ERROR
    assert "stderr byte offset 0" in detail
    assert p3._enclosing_phase3_outcome(
        1, banner, "x" * 5000, None, {"15"}, False)[0] == "FAIL"


def test_a_fail_in_the_windows_own_step_is_fail_and_names_it(project, monkeypatch):
    import execution_policy
    monkeypatch.setattr(execution_policy, "request", lambda: {"mode": "ultra"})
    report = _rows(("pnr", "FAIL", "global route diverged", ""),
                   ("drc", "NOT_MEASURED", "upstream", "upstream_failed"))
    row = _enclose_with(project, monkeypatch, _unit(report), "ownfail",
                        steps=("15", "16"))
    assert row.status == "FAIL", row.detail
    assert "pnr (15,15.5ic,16,17,18,19,20,21,22) FAIL: global route diverged" in row.detail
    # The row outside the window is disclosed, not blamed.
    assert "rows of steps outside the window: drc (31) NOT_MEASURED" in row.detail


def test_a_fail_outside_the_window_is_not_the_windows_fail(project, monkeypatch):
    import execution_policy
    monkeypatch.setattr(execution_policy, "request", lambda: {"mode": "ultra"})
    """The unit ran every site. Its PnR FAILed and an unplaceable row
    FAILed, but both rows of the window's own step 31 passed: the window
    PASSes and the other rows are named."""
    outputs = ["reports/phase3/drc_signoff.rpt"]
    report = _rows(("pnr", "FAIL", "x", ""), ("drc", "PASS", "", ""),
                   ("lvs", "PASS", "", ""), ("sta_signoff", "FAIL", "y", ""))
    row = _enclose_with(project, monkeypatch, _unit(report, outputs=outputs),
                        "outfail", steps=("31",))
    assert row.status == "PASS", row.detail
    assert "rows of steps outside the window: pnr (15,15.5ic,16,17,18,19,20,21,22) FAIL" in row.detail
    assert "sta_signoff (23) FAIL" in row.detail


def test_a_fail_that_names_no_step_cannot_decide_an_unplaced_window(
        project, monkeypatch):
    """A window step with no row of its own (39: no Phase-3 row runs it) and
    a failing row mapped to no step: the row may be this window's."""
    report = _rows(("mystery_gate", "FAIL", "y", ""))
    row = _enclose_with(project, monkeypatch, _unit(report), "unplaced",
                        steps=("39",))
    assert row.status == "NOT_MEASURED", row.detail
    assert row.reason_class == p3._V.ReasonClass.INCONCLUSIVE
    assert "steps 39 have no row of their own" in row.detail
    assert ("rows mapped to no step (they may be this window's): "
            "mystery_gate (no step) FAIL") in row.detail


def test_a_sign_off_row_of_the_windows_step_decides_it(project, monkeypatch):
    """Window 22..23 (enclosing): post-route STA is step 23's own gate. Its
    FAIL is the window's FAIL, named, never "no row of their own"."""
    import execution_policy
    assert p3._phase3_window_sites("22", "23") == ["default_backend"]
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'ultra'})
    assert p3._phase3_window_sites("22", "23") == ["enclosing_phase3"]
    report = _rows(("pnr", "PASS", "", ""),
                   ("sta_signoff", "FAIL", "WNS -0.42ns", ""))
    row = _enclose_with(project, monkeypatch, _unit(report), "sta23",
                        steps=p3._phase3_window_steps("22", "23"))
    assert row.status == "FAIL", row.detail
    assert "sta_signoff (23) FAIL: WNS -0.42ns" in row.detail


def test_an_out_of_window_drc_fail_does_not_decide_window_9_to_30(
        project, monkeypatch):
    import execution_policy
    monkeypatch.setattr(execution_policy, "request", lambda: {"mode": "ultra"})
    """The front door's `--exit-step 30` window: every row of steps 9..30
    passes and only DRC (31, outside it) fails. The window PASSes."""
    steps = p3._phase3_window_steps("9", "30")
    assert p3._phase3_window_sites("9", "30") == ["enclosing_phase3"]
    names = ["synth", "pad_ring_gen", "pnr", "canonicalize_artefacts",
             "sta_signoff", "sta_corner", "sta_record", "em_signoff",
             "ir_drop_final", "antenna_final", "si_final", "gds", "lvs",
             "path_delay_fault_atpg_run", "sdd_atpg_run"]
    report = _rows(*[(n, "PASS", "", "") for n in names],
                   ("drc", "FAIL", "12 violations", ""))
    row = _enclose_with(project, monkeypatch,
                        _unit(report, outputs=["reports/phase3/sta/post_route_summary.json"]),
                        "win930", steps=steps)
    assert row.status == "PASS", row.detail
    assert "rows of steps outside the window: drc (31) FAIL" in row.detail


def test_window_refuses_report_pointing_into_discarded_copy(project, monkeypatch):
    report = _rows(("sta_signoff", "PASS", "", ""))
    report["verdict"] = "PASS"
    output = "reports/phase3/sta/post_route_summary.json"
    code = ("import json, pathlib, sys\n"
            "iso = pathlib.Path(sys.argv[1])\n"
            f"out = iso / {output!r}\n"
            "out.parent.mkdir(parents=True, exist_ok=True)\n"
            "out.write_text(json.dumps({'input_def': str(iso / 'phase3/input.def')}))\n"
            "report = iso / 'reports/orchestrator/phase3_one_shot.json'\n"
            "report.parent.mkdir(parents=True, exist_ok=True)\n"
            f"report.write_text(json.dumps({report!r}))\n"
            f"print({BANNER!r})\n")
    row = _enclose_with(project, monkeypatch, code, "outside-input", steps=("23",))
    assert row.status == "NOT_MEASURED", row.detail
    assert not (project / output).exists()
    assert "outside project" in row.detail


def test_window_publishes_in_tree_input_with_provenance(project, monkeypatch):
    input_def = project / "phase3/input.def"
    input_def.parent.mkdir(parents=True)
    input_def.write_text("source DEF")
    report = _rows(("sta_signoff", "PASS", "", ""))
    report["verdict"] = "PASS"
    output = "reports/phase3/sta/post_route_summary.json"
    code = ("import json, pathlib, sys\n"
            "iso = pathlib.Path(sys.argv[1])\n"
            f"out = iso / {output!r}\n"
            "out.parent.mkdir(parents=True, exist_ok=True)\n"
            f"out.write_text(json.dumps({{'input_def': {str(input_def)!r}}}))\n"
            "report = iso / 'reports/orchestrator/phase3_one_shot.json'\n"
            "report.parent.mkdir(parents=True, exist_ok=True)\n"
            f"report.write_text(json.dumps({report!r}))\n"
            f"print({BANNER!r})\n")
    row = _enclose_with(project, monkeypatch, code, "inside-input", steps=("23",))
    assert row.status == "PASS", row.detail
    assert (project / output).is_file()
    receipt = project / "reports/audit/windows/inside-input/publication.json"
    assert receipt.is_file()
    publication = json.loads(receipt.read_text())
    assert publication["status"] == "PUBLISHED"
    assert output in publication["outputs"]
    assert "phase3/input.def" in publication["inputs"]


def test_enclosing_window_stops_before_publishing_missing_citation(
        project, monkeypatch):
    report = _rows(("sta_signoff", "PASS", "", ""))
    report["verdict"] = "PASS"
    output = "reports/phase3/sta/post_route_summary.json"
    code = ("import json, pathlib, sys\n"
            "iso = pathlib.Path(sys.argv[1])\n"
            f"out = iso / {output!r}\n"
            "out.parent.mkdir(parents=True, exist_ok=True)\n"
            "out.write_text(json.dumps({'output_files': ['./missing.def']}))\n"
            "record = iso / 'reports/orchestrator/phase3_one_shot.json'\n"
            "record.parent.mkdir(parents=True, exist_ok=True)\n"
            f"record.write_text(json.dumps({report!r}))\n"
            f"print({BANNER!r})\n")

    row = _enclose_with(project, monkeypatch, code, "missing-citation",
                        steps=("23",))

    assert row.status == "NOT_MEASURED", row.detail
    assert row.reason_class == p3._V.ReasonClass.MISSING_ARTEFACT
    assert "window cited input absent: ./missing.def" in row.detail
    assert not (project / output).exists()
    assert not (project / "reports/audit/windows/missing-citation/"
            "publication.json").exists()


@pytest.mark.parametrize("case", ["missing_component", "file_component",
                                  "symlink_parent"])
def test_enclosing_window_resolves_citation_components_before_publication(
        project, tmp_path, monkeypatch, case):
    decoy = project / "payload.def"
    decoy.write_text("decoy bytes")
    if case == "missing_component":
        citation = "absent/../payload.def"
        assert not (project / "absent").exists()
    elif case == "file_component":
        # A regular file before ".." cannot be walked through: the literal
        # spelling does not open, whatever a lexical ".." would reach.
        (project / "x.def").write_text("not a directory")
        citation = "x.def/../payload.def"
        with pytest.raises(NotADirectoryError):
            (project / citation).open()
    else:
        outside = tmp_path / "outside"
        child = outside / "child"
        child.mkdir(parents=True)
        (outside / "payload.def").write_text("outside bytes")
        (project / "link").symlink_to(child, target_is_directory=True)
        citation = "link/../payload.def"
        assert (project / citation).resolve(strict=True) == outside / "payload.def"

    report = _rows(("sta_signoff", "PASS", "", ""))
    report["verdict"] = "PASS"
    output = "reports/phase3/sta/post_route_summary.json"
    code = ("import json, pathlib, sys\n"
            "iso = pathlib.Path(sys.argv[1])\n"
            f"out = iso / {output!r}\n"
            "out.parent.mkdir(parents=True, exist_ok=True)\n"
            f"out.write_text(json.dumps({{'output_files': [{citation!r}]}}))\n"
            "record = iso / 'reports/orchestrator/phase3_one_shot.json'\n"
            "record.parent.mkdir(parents=True, exist_ok=True)\n"
            f"record.write_text(json.dumps({report!r}))\n"
            f"print({BANNER!r})\n")

    row = _enclose_with(project, monkeypatch, code, case, steps=("23",))

    assert row.status == "NOT_MEASURED", row.detail
    assert row.reason_class == p3._V.ReasonClass.MISSING_ARTEFACT
    assert ("window input outside project" if case == "symlink_parent"
            else "window cited input absent") in row.detail
    assert decoy.read_text() == "decoy bytes"
    assert not (project / output).exists()
    assert not (project / f"reports/audit/windows/{case}/publication.json").exists()


@pytest.mark.parametrize("absolute", [False, True])
def test_window_citation_through_a_file_component_is_absent(
        project, tmp_path, absolute):
    """`x.def/../payload.def` with x.def a regular file: the literal path
    raises ENOTDIR, so nothing may be bound to the lexical target."""
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    owner = project if absolute else isolated
    (owner / "x.def").write_text("a file, not a directory")
    (owner / "payload.def").write_text("payload")
    citation = (str(owner / "x.def/../payload.def") if absolute
                else "x.def/../payload.def")
    result = isolated / "result.json"
    result.write_text(json.dumps({"output_files": [citation]}))

    published, error = p3._phase3_window_publication(
        project, isolated, [result], "file-component")

    assert published == []
    assert "window cited input absent" in error, error
    assert not (project / "result.json").exists()
    assert not (project / "reports/audit/windows/file-component/"
                "publication.json").exists()


@pytest.mark.parametrize("spelling", ["carried_link", "root_link", "dotdot"])
def test_window_absolute_citation_spelled_into_the_copy_is_refused(
        project, tmp_path, spelling):
    """A path spelled through the disposable copy dangles once the copy is
    removed, even when it resolves back into the project (bf9318cc8)."""
    (project / "phase3").mkdir()
    (project / "phase3/real.def").write_text("project bytes")
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    if spelling == "carried_link":
        # `cp -a` keeps a legacy absolute intra-project link verbatim.
        (isolated / "steps").mkdir()
        (isolated / "steps/alias").symlink_to(project / "phase3",
                                              target_is_directory=True)
        citation = str(isolated / "steps/alias/real.def")
    elif spelling == "root_link":
        (isolated / "rootlink").symlink_to(project, target_is_directory=True)
        citation = str(isolated / "rootlink/phase3/real.def")
    else:
        citation = f"{isolated}/../{project.name}/phase3/real.def"
    assert Path(citation).resolve(strict=True) == project / "phase3/real.def"
    result = isolated / "result.json"
    result.write_text(json.dumps({"input_def": citation}))

    published, error = p3._phase3_window_publication(
        project, isolated, [result], "spelled-into-copy")

    assert published == []
    assert "window input outside project" in error, error
    assert not (project / "result.json").exists()
    assert not (project / "reports/audit/windows/spelled-into-copy/"
                "publication.json").exists()


@pytest.mark.parametrize("spelling", ["outside_prefix_link", "in_project_link"])
def test_window_absolute_citation_spelling_the_project_by_a_link_publishes(
        project, tmp_path, spelling):
    """Control: an absolute spelling of the project itself, through a link
    that never enters the copy, is still bound by SHA."""
    (project / "phase3").mkdir()
    (project / "phase3/real.def").write_text("project bytes")
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    if spelling == "outside_prefix_link":
        (tmp_path / "plink").symlink_to(project, target_is_directory=True)
        citation = str(tmp_path / "plink/phase3/real.def")
    else:
        (project / "steps").mkdir()
        (project / "steps/alias").symlink_to(project / "phase3",
                                             target_is_directory=True)
        citation = str(project / "steps/alias/real.def")
    result = isolated / "result.json"
    result.write_text(json.dumps({"input_def": citation}))

    published, error = p3._phase3_window_publication(
        project, isolated, [result], "project-by-link")

    assert error == "", error
    assert published == [str(project / "result.json")]
    receipt = json.loads((project / "reports/audit/windows/project-by-link/"
                          "publication.json").read_text())
    assert receipt["status"] == "PUBLISHED"
    assert "phase3/real.def" in receipt["inputs"]


def test_enclosing_window_refuses_citation_through_a_carried_absolute_link(
        project, monkeypatch):
    """The integrity probe: a legacy absolute intra-project link under steps/
    rides into the copy; citing the copy's spelling must not publish."""
    (project / "phase3").mkdir()
    (project / "phase3/input.def").write_text("source DEF")
    (project / "steps/23").mkdir(parents=True)
    (project / "steps/23/input.def").symlink_to(project / "phase3/input.def")
    report = _rows(("sta_signoff", "PASS", "", ""))
    report["verdict"] = "PASS"
    output = "reports/phase3/sta/post_route_summary.json"
    code = ("import json, pathlib, sys\n"
            "iso = pathlib.Path(sys.argv[1])\n"
            f"out = iso / {output!r}\n"
            "out.parent.mkdir(parents=True, exist_ok=True)\n"
            "out.write_text(json.dumps({'input_def': str(iso / 'steps/23/input.def')}))\n"
            "record = iso / 'reports/orchestrator/phase3_one_shot.json'\n"
            "record.parent.mkdir(parents=True, exist_ok=True)\n"
            f"record.write_text(json.dumps({report!r}))\n"
            f"print({BANNER!r})\n")

    row = _enclose_with(project, monkeypatch, code, "carried-link",
                        steps=("23",))

    assert row.status == "NOT_MEASURED", row.detail
    assert "window input outside project" in row.detail
    assert not (project / output).exists()
    assert not (project / "reports/audit/windows/carried-link/"
                "publication.json").exists()


def test_window_publishes_dot_relative_file_reference(project, tmp_path):
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    payload = isolated / "payload with space.def"
    payload.write_text("private output")
    result = isolated / "result.json"
    result.write_text(json.dumps({"output_file": "./payload with space.def"}))

    published, error = p3._phase3_window_publication(
        project, isolated, [result], "dot-relative")

    assert error == "", error
    assert set(published) == {str(project / "result.json"),
                              str(project / payload.name)}
    assert (project / payload.name).read_text() == "private output"
    receipt = json.loads((project / "reports/audit/windows/dot-relative/"
                          "publication.json").read_text())
    assert receipt["status"] == "PUBLISHED"
    assert payload.name in receipt["outputs"]
    assert payload.name in receipt["inputs"]


@pytest.mark.parametrize("spelling", [
    "./payload.def", "payload.def", "a/../payload.def",
    "dir with space/payload.def",
])
@pytest.mark.parametrize("present", [True, False])
def test_window_structured_relative_citation_requires_file(
        project, tmp_path, spelling, present):
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    target = isolated / spelling
    target.parent.mkdir(parents=True, exist_ok=True)
    if present:
        target.write_text("cited output")
    result = isolated / "result.json"
    result.write_text(json.dumps({"output_files": [spelling]}))

    published, error = p3._phase3_window_publication(
        project, isolated, [result], "structured-relative")
    receipt = project / "reports/audit/windows/structured-relative/publication.json"
    if present:
        rel = str(target.resolve().relative_to(isolated.resolve()))
        assert error == "", error
        assert set(published) == {str(project / "result.json"), str(project / rel)}
        assert (project / rel).read_text() == "cited output"
        body = json.loads(receipt.read_text())
        assert body["status"] == "PUBLISHED"
        assert rel in body["inputs"] and rel in body["outputs"]
    else:
        assert published == []
        assert "absent" in error or "missing" in error
        assert not (project / "result.json").exists()
        assert not receipt.exists()


@pytest.mark.parametrize("location", ["project", "outside", "escaping_symlink"])
@pytest.mark.parametrize("present", [True, False])
def test_window_structured_absolute_and_symlink_citations(
        project, tmp_path, location, present):
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    if location == "project":
        target = project / "input.def"
        citation = str(target)
    else:
        target = tmp_path / "outside.def"
        if location == "escaping_symlink":
            link = isolated / "escape.def"
            link.symlink_to(target)
            citation = "escape.def"
        else:
            citation = str(target)
    if present:
        target.write_text("cited input")
    result = isolated / "result.json"
    result.write_text(json.dumps({"output_files": [citation]}))

    published, error = p3._phase3_window_publication(
        project, isolated, [result], "structured-absolute")
    receipt = project / "reports/audit/windows/structured-absolute/publication.json"
    if location == "project" and present:
        assert error == "", error
        assert published == [str(project / "result.json")]
        assert json.loads(receipt.read_text())["inputs"]["input.def"]
    else:
        assert published == []
        assert ("outside" in error if location != "project"
                else "absent" in error or "missing" in error)
        assert not (project / "result.json").exists()
        assert not receipt.exists()


def test_window_does_not_replace_a_run_cited_artefact(project, monkeypatch):
    import hashlib
    output = "reports/phase3/sta/post_route_summary.json"
    target = project / output
    target.parent.mkdir(parents=True)
    target.write_text('{"old_run":true}')
    report_path = project / "reports/orchestrator/phase3_one_shot.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(json.dumps({
        "verdict": "PASS", "steps": [], "cited_artefacts": {
            output: hashlib.sha256(target.read_bytes()).hexdigest()}}))
    report = _rows(("sta_signoff", "PASS", "", ""))
    report["verdict"] = "PASS"
    code = _unit(report, rc=0, outputs=(output,))
    row = _enclose_with(project, monkeypatch, code, "cited-output", steps=("23",))
    assert row.status == "NOT_MEASURED", row.detail
    assert "run-cited artefact" in row.detail
    assert target.read_text() == '{"old_run":true}'


def _rows_main_emits():
    """Every StepResult row name `phase3_one_shot_runner` spells literally,
    plus its declared gate tables: the rows a report can carry. The
    pre-audit producers (tapeout_checklist, gds_xor, foundry_handoff) are
    NOT: main keeps them out of `plan`, so they never reach the report's
    `steps` (review wave 7)."""
    import ast
    tree = ast.parse(Path(p3.__file__).read_text())
    names = {node.args[0].value for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and getattr(node.func, "id", None) == "StepResult"
             and node.args and isinstance(node.args[0], ast.Constant)
             and isinstance(node.args[0].value, str)}
    pre_audit = {g[0] for g in p3._PRE_AUDIT_PRODUCERS}
    return (names | {g[0] for g in p3._PHASE3_GATE_TABLES()}) - pre_audit


def test_every_phase3_step_is_answered_for_by_a_row_main_emits(monkeypatch):
    """One map: dispatch and verdict read the same canonicalizer set, and
    every canonical Phase-3 step 9..38 but the pre-audit producers' has a
    report row that answers for it. Steps 36, 37.3 and 38 (their rows never
    reach the report) and 39 (FPGA sign-off: no Phase-3 row runs it) have
    none, so a window over them is read from the unit's headline or is
    INCONCLUSIVE, which the test above pins."""
    assert p3._phase3_steps_of_row("canonicalize_artefacts") == \
        p3._PHASE3_CANONICALIZER_IDS
    import execution_policy
    assert p3._phase3_window_sites("24", "25") == ["default_backend"]
    monkeypatch.setattr(execution_policy, 'request', lambda: {'mode': 'ultra'})
    assert p3._phase3_window_sites("24", "25") == ["enclosing_canonicalize"]
    covered = set().union(*(p3._phase3_steps_of_row(n) for n in _rows_main_emits()))
    ids = p3._phase3_window_steps("9", "39")
    assert {i for i in ids if i not in covered} == {"36", "37.3", "38", "39", "DT2", "DT3"}
    # Default and Ultra share order, but their native-unit ownership differs.
    assert "22" in p3._phase3_steps_of_row("pnr")
    with monkeypatch.context() as default:
        default.setattr(execution_policy, "request", lambda: {"mode": "default"})
        assert "22" not in p3._phase3_steps_of_row("pnr")
        assert p3._phase3_steps_of_row("default_step_DT2") == frozenset({"DT2"})
    assert "22" in p3._phase3_steps_of_row("pnr")


def test_every_row_main_emits_has_a_step_or_cannot_let_a_window_pass():
    """The other direction (review wave 7): a row either answers for a step,
    or -- when no map places it -- its FAIL keeps EVERY window from PASSing
    (it may be that window's). Checked for every row main emits, for every
    window whose own rows all pass."""
    windows = [("9", "21"), ("22", "23"), ("9", "30"), ("9", "37")]
    unplaced = sorted(n for n in _rows_main_emits()
                      if not p3._phase3_steps_of_row(n))
    for entry, exit_ in windows:
        ids = set(p3._phase3_window_steps(entry, exit_))
        own = sorted(n for n in _rows_main_emits()
                     if p3._phase3_steps_of_row(n) & ids)
        passing = [{"name": n, "status": "PASS"} for n in own]
        # These independent DFT producers moved after final extraction. Their
        # named rows are required evidence, even though the legacy main's AST
        # emits no literal row for them. Do not credit an incomplete fixture.
        for name in ("path_delay_fault_atpg_run", "sdd_atpg_run"):
            if p3._phase3_steps_of_row(name) & ids:
                passing.append({"name": name, "status": "PASS"})
        assert p3._enclosing_report_outcome(
            {"verdict": "FAIL", "steps": passing}, 1, ids, True)[0] == "PASS"
        for name in unplaced:
            got = p3._enclosing_report_outcome(
                {"verdict": "FAIL", "steps": passing + [
                    {"name": name, "status": "FAIL", "detail": "boom"}]},
                1, ids, True)
            assert got[:2] == ("NOT_MEASURED", p3._V.ReasonClass.INCONCLUSIVE), \
                (entry, exit_, name, got)
            assert f"{name} (no step) FAIL: boom" in got[2]
        for name, sid in (("path_delay_fault_atpg_run", "DT2"),
                          ("sdd_atpg_run", "DT3")):
            if sid in ids:
                failed = [dict(row, status="FAIL", detail="measured DFT failure")
                          if row["name"] == name else row for row in passing]
                got = p3._enclosing_report_outcome(
                    {"verdict": "FAIL", "steps": failed}, 1, ids, True)
                assert got[0] == "FAIL", got
                assert f"{name} ({sid}) FAIL: measured DFT failure" in got[2]


@pytest.mark.parametrize("window, row, step", [
    (("22", "23"), "drv_promotion_corroboration", "23"),   # optional {command:} clause
    (("9", "37"), "pad_ring_route_evidence", "37"),        # a required_output of 37
])
def test_a_row_the_flow_places_by_clause_or_output_decides_its_window(
        project, monkeypatch, window, row, step):
    """Review wave 7: these two FAILed rows were unplaced, so the window
    PASSed. They are placed now -- one through step 23's optional
    `{command: ...}` clause, one through step 37's required output -- and
    their FAIL is the window's, by name."""
    ids = set(p3._phase3_window_steps(*window))
    assert step in p3._phase3_steps_of_row(row)
    own = sorted(n for n in _rows_main_emits()
                 if p3._phase3_steps_of_row(n) & ids and n != row)
    report = _rows(*[(n, "PASS", "", "") for n in own],
                   (row, "FAIL", "contradiction", ""))
    got = p3._enclosing_report_outcome(report, 1, ids, True)
    assert got[0] == "FAIL", got
    assert f"{row} ({step}) FAIL: contradiction" in got[2]


def test_an_unplaced_fail_keeps_window_9_to_30_from_passing(project, monkeypatch):
    import execution_policy
    monkeypatch.setattr(execution_policy, "request", lambda: {"mode": "ultra"})
    """Through the real window: every placed row of 9..30 passes and only
    `pad_side_constraint` (placed by no map) FAILs. It may be this window's:
    INCONCLUSIVE, by name -- no longer PASS."""
    steps = p3._phase3_window_steps("9", "30")
    names = ["synth", "pad_ring_gen", "pnr", "canonicalize_artefacts",
             "sta_signoff", "sta_corner", "sta_record", "em_signoff",
             "ir_drop_final", "antenna_final", "si_final", "gds", "lvs",
             "path_delay_fault_atpg_run", "sdd_atpg_run"]
    report = _rows(*[(n, "PASS", "", "") for n in names],
                   ("pad_side_constraint", "FAIL", "pad on the wrong side", ""))
    row = _enclose_with(project, monkeypatch,
                        _unit(report, outputs=["reports/phase3/sta/post_route_summary.json"]),
                        "padside", steps=steps)
    assert row.status == "NOT_MEASURED", row.detail
    assert row.reason_class == p3._V.ReasonClass.INCONCLUSIVE
    assert "pad_side_constraint (no step) FAIL: pad on the wrong side" in row.detail


def test_the_child_is_asked_the_operators_questions():
    """Not the parent's resolved `custom:<dir>` name (refused by
    `_assert_pdk_name_resolvable`), and the window's own geometry."""
    args = SimpleNamespace(pdk="auto", container="c", die_um="600", util=0.4,
                           spare_density=0.02, ic_name="chip",
                           allow_oss_pdk_fallback=True,
                           allow_pdk_target_mismatch=False)
    cmd = p3._phase3_enclosing_cmd(Path("/x/p"), "top",
                                   SimpleNamespace(name="custom:pdk"), args)
    assert cmd[cmd.index("--pdk") + 1] == "auto" and "custom:pdk" not in cmd
    assert cmd[cmd.index("--die-um") + 1] == "600"
    assert cmd[cmd.index("--util") + 1] == "0.4"
    assert cmd[cmd.index("--spare-density") + 1] == "0.02"
    assert cmd[cmd.index("--ic-name") + 1] == "chip"
    assert "--allow-oss-pdk-fallback" in cmd
    assert "--allow-pdk-target-mismatch" not in cmd


def test_a_window_step_not_measured_keeps_its_own_reason(project, monkeypatch):
    report = _rows(("drc", "NOT_MEASURED", "", "tool_absent"),
                   ("lvs", "PASS", "", ""))
    row = _enclose_with(project, monkeypatch, _unit(report), "ownnm",
                        steps=("31",))
    assert row.status == "NOT_MEASURED", row.detail
    assert row.reason_class == "tool_absent"


def test_a_previous_report_in_the_copy_does_not_speak_for_this_run(
        project, monkeypatch):
    """The copy carries the project's last report (PASS). A unit that ran
    and died without writing one must not be read as that PASS."""
    old = p3._pl.report_path(project, "phase3_one_shot.json")
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(json.dumps({"verdict": "PASS"}))
    row = _enclose_with(project, monkeypatch, _unit(rc=9), "stale")
    assert row.status == "FAIL", row.detail
    assert "verdict=None" in row.detail


@pytest.mark.parametrize("rc", [0, 1, 2, 3, 4])
def test_a_unit_that_never_started_a_step_is_not_measured_whatever_its_rc(
        project, monkeypatch, rc):
    """No run banner, no report: every refusal before the first step,
    including rc 1 (a PDK ValueError/SystemExit) and rc 0 (the no-PDK
    `[SKIP]`), is a unit that did not run."""
    code = ("import sys; sys.stderr.write('REFUSED: test\\n'); "
            f"sys.exit({rc})")
    row = _enclose_with(project, monkeypatch, code, f"norun{rc}")
    assert row.status == "NOT_MEASURED", row.detail
    assert row.reason_class == p3._V.ReasonClass.INPUT_ABSENT
    assert "stopped before running a step" in row.detail
    assert "REFUSED: test" in row.detail


def test_the_real_pdk_refusal_is_a_unit_that_never_ran(project, monkeypatch):
    """`_detect_pdk`'s own refusal, run for real in the child on a project
    with a staged input/pdk: a named PDK it cannot resolve raises
    ValueError, the child exits 1 with a traceback and no report."""
    (project / "input" / "pdk" / "lib").mkdir(parents=True)
    (project / "input" / "pdk" / "lib" / "cells.lib").write_text("library(x){}\n")
    code = ("import sys, pathlib\n"
            f"sys.path.insert(0, {str(Path(p3.__file__).parent)!r})\n"
            "import phase3_one_shot_runner as p\n"
            "p._detect_pdk(pathlib.Path(sys.argv[1]), 'no_such_pdk_name')\n"
            f"print({BANNER!r})\n")
    row = _enclose_with(project, monkeypatch, code, "pdkrefusal")
    assert row.status == "NOT_MEASURED", row.detail
    assert "enclosing rc=1" in row.detail
    assert "ValueError" in row.detail and "no_such_pdk_name" in row.detail


def test_the_real_runner_refusing_an_unadmitted_copy_stays_not_measured(
        project, monkeypatch):
    """No stand-in: the real phase-3 CLI on an empty project refuses at
    admission, which is a unit that never ran a step."""
    monkeypatch.setattr(p3, "_WATCHDOG_STALL_GRACE_S", 120)
    monkeypatch.setenv("VIBEIC_PHASE3_WINDOW_RUN_ID", "realrefusal")
    monkeypatch.delenv(_runner_lock.REENTRANCY_ENV, raising=False)
    row = _enclose(project)
    assert row.status == "NOT_MEASURED", row.detail
    assert "stopped before running a step" in row.detail


@pytest.mark.parametrize("sig, status", [("SIGTERM", "NOT_MEASURED"),
                                         ("SIGKILL", "NOT_MEASURED"),
                                         ("SIGSEGV", "FAIL")])
def test_a_unit_killed_by_a_signal(project, monkeypatch, sig, status):
    """Stopped from outside (TERM/KILL): an environment stop, NOT_MEASURED
    naming the signal. A crash of the unit's own (SEGV) after it ran: FAIL."""
    # The banner is printed by main's own `_print_run_banner` -- NOT flushed
    # here -- so a crash right after it keeps the banner only if main does.
    # No core file: the host's core_pattern writes one into the cwd, and in
    # the image `ulimit -c` is unlimited -- set it to 0 in the CHILD (it is
    # inherited) and crash from a scratch cwd (review wave 7).
    code = ("import os, resource, signal, sys, tempfile\n"
            "resource.setrlimit(resource.RLIMIT_CORE, (0, 0))\n"
            "os.chdir(tempfile.mkdtemp())\n"
            f"sys.path.insert(0, {str(Path(p3.__file__).parent)!r})\n"
            "import phase3_one_shot_runner as p\n"
            "p._print_run_banner('x', 'top', 'top')\n"
            f"os.kill(os.getpid(), signal.{sig})\n")
    row = _enclose_with(project, monkeypatch, code, f"sig{sig}")
    assert row.status == status, row.detail
    assert sig in row.detail
    if status == "NOT_MEASURED":
        assert row.reason_class == p3._V.ReasonClass.EXECUTION_ERROR


def test_a_stall_inside_the_unit_is_stalled_not_a_refusal(project, monkeypatch):
    """rc 2 is also RC_UNDETERMINED: the real `exit_undetermined_on_stall`
    around a step that stalled after the unit started."""
    code = ("import sys\n"
            f"sys.path.insert(0, {str(Path(p3.__file__).parent)!r})\n"
            "import _progress_run as pr\n"
            "def main():\n"
            f"    print({BANNER!r})\n"
            "    raise pr.Stalled(['tool'], 3, 1.0, 3.0, {'cpu': True})\n"
            "sys.exit(pr.exit_undetermined_on_stall(main))\n")
    row = _enclose_with(project, monkeypatch, code, "undetermined")
    assert row.status == "NOT_MEASURED", row.detail
    assert row.reason_class == p3._V.ReasonClass.STALLED
    assert "enclosing rc=2" in row.detail and "stalled" in row.detail


def test_a_unit_that_cannot_be_spawned_stays_not_measured(project, monkeypatch):
    monkeypatch.setattr(p3, "_phase3_enclosing_cmd",
                        lambda *a: [str(project / "no-such-interpreter")])
    monkeypatch.setenv("VIBEIC_PHASE3_WINDOW_RUN_ID", "nospawn")
    row = _enclose(project)
    assert row.status == "NOT_MEASURED", row.detail
    assert row.reason_class == p3._V.ReasonClass.EXECUTION_ERROR
    assert "could not be spawned" in row.detail


@pytest.mark.parametrize("status, expected", [("FAIL", "FAIL"),
                                              ("NOT_MEASURED", "NOT_MEASURED")])
def test_an_in_process_unit_keeps_what_it_found(project, monkeypatch, status,
                                                expected):
    monkeypatch.setattr(p3, "step_canonicalize_artefacts", lambda *a, **k:
                        p3.StepResult("canonicalize", status, 0.0, "x",
                                      reason_class=("" if status == "FAIL" else
                                                    p3._V.ReasonClass.TOOL_ABSENT)))
    row = p3._phase3_window_enclosing(
        project, "top", SimpleNamespace(name="gf180mcuD"),
        SimpleNamespace(container="vibeic-eda"), {"24"}, unit="canonicalize")
    assert row.status == expected, row.detail
    if expected == "NOT_MEASURED":
        assert row.reason_class == p3._V.ReasonClass.TOOL_ABSENT


def test_an_in_process_fail_names_what_failed(project, monkeypatch):
    """Review wave 7: the unit's own detail is kept -- canonicalize answers
    for 13 steps, and a red with no subject needs a re-run to explain."""
    monkeypatch.setattr(p3, "step_canonicalize_artefacts", lambda *a, **k:
                        p3.StepResult("canonicalize", "FAIL", 0.0,
                                      "sign-off emit FAILED: post-layout LEC "
                                      "emit FAILED (rc=1)"))
    row = p3._phase3_window_enclosing(
        project, "top", SimpleNamespace(name="gf180mcuD"),
        SimpleNamespace(container="vibeic-eda"), {"24", "25"},
        unit="canonicalize")
    assert row.status == "FAIL", row.detail
    assert "post-layout LEC emit FAILED" in row.detail


@pytest.mark.parametrize("stderr", ["OSError: [Errno 28] No space left on device",
                                    "MemoryError"])
def test_a_host_shortfall_after_the_unit_ran_is_not_red(project, monkeypatch,
                                                        stderr):
    code = (f"import sys\nprint({BANNER!r})\n"
            f"sys.stderr.write({stderr!r} + '\\n')\nsys.exit(1)\n")
    row = _enclose_with(project, monkeypatch, code, "host" + str(len(stderr)))
    assert row.status == "NOT_MEASURED", row.detail
    assert row.reason_class == p3._V.ReasonClass.EXECUTION_ERROR
    assert "host shortfall" in row.detail
