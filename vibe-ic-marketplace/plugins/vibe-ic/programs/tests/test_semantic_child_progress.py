"""Finite semantic child progress is the only issue-1710 lease signal."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

import _corpus_location
import _published_tree
import _semantic_child_progress as S
import l4_systemrdl_export as L4
import repo_hygiene_parallel as P
import _progress_run as _pr  # noqa: E402


PROGRAMS = Path(__file__).resolve().parents[1]
SCOPE = "test:finite-corpus-work"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    old = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(PROGRAMS) + (os.pathsep + old if old else "")
    return env


def _semantic(tmp_path: Path, source: str, units, *, callback=None,
              grace: float = 0.18):
    return P._run(
        [sys.executable, "-c", source], tmp_path, _env(),
        stall_grace_s=grace,
        semantic_progress_scope=SCOPE,
        semantic_progress_units=units,
        domain_progress_callback=callback)


def test_one_slow_document_uses_finite_chunks_past_old_stall_window(
        tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.02)
    done = tmp_path / "child-finished"
    observed = []

    def relay(scope, completed, total):
        observed.append((scope, completed, total, done.exists()))

    units = [f"document:slow:chunk:{i}/4" for i in range(1, 5)]
    source = f"""
import pathlib,time
from _semantic_child_progress import child_progress
units = {units!r}
def main():
    with child_progress({SCOPE!r}) as progress:
        for unit in units:
            time.sleep(0.09)
            progress.checkpoint(unit)
        time.sleep(0.05)
    pathlib.Path({str(done)!r}).write_text('natural\\n')
    print('natural-output-is-preserved')
    return 0
raise SystemExit(main())
"""
    started = time.monotonic()
    rc, out, problem = _semantic(
        tmp_path, source, units,
        callback=relay)
    elapsed = time.monotonic() - started
    assert elapsed > 0.36 > 0.18, elapsed
    assert (rc, problem) == (0, None), (rc, out, problem)
    assert "natural-output-is-preserved" in out
    assert [(s, c, t) for s, c, t, _done in observed] == [
        (SCOPE, 1, 4), (SCOPE, 2, 4),
        (SCOPE, 3, 4), (SCOPE, 4, 4),
    ]
    assert all(not was_done for *_event, was_done in observed), (
        "the parent delivered progress only after the child had exited")


@pytest.mark.parametrize("body", [
    "import time; time.sleep(5)",
    "import time\nwhile True:\n print('chat', flush=True); time.sleep(.01)",
    "import time\nend=time.monotonic()+5\nwhile time.monotonic()<end: pass",
])
def test_silent_chatty_and_busy_children_cannot_renew_semantic_lease(
        tmp_path, monkeypatch, body):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.02)
    rc, out, problem = _semantic(
        tmp_path, body, ["unit:1"], grace=0.14)
    assert rc == 2, (rc, out, problem)
    assert problem and "SEMANTIC_PROGRESS_NORECORD" in problem
    assert "outcome=stalled" in problem


def test_all_checkpoints_without_natural_terminal_is_norecord(
        tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.02)
    source = f"""
from _semantic_child_progress import child_progress
progress = child_progress({SCOPE!r})
progress.__enter__()
progress.checkpoint('unit:1')
print('exited-without-terminal')
"""
    rc, out, problem = _semantic(tmp_path, source, ["unit:1"])
    assert rc == 2, (rc, out, problem)
    assert "exited-without-terminal" in out
    assert problem and "SEMANTIC_PROGRESS_NORECORD" in problem
    assert "terminal FSM" in problem


def test_forged_nonce_aborts_owned_child_as_norecord(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.02)
    source = f"""
import json,os,time
path = os.environ['{S.ENV_PATH}']
row = {{'schema': 1, 'nonce': '0'*64, 'pid': os.getpid(), 'seq': 0,
       'state': 'start', 'scope': {SCOPE!r}, 'total': 1}}
with open(path, 'a', encoding='utf-8') as stream:
    stream.write(json.dumps(row, sort_keys=True, separators=(',', ':'))+'\\n')
    stream.flush(); os.fsync(stream.fileno())
time.sleep(5)
"""
    rc, out, problem = _semantic(tmp_path, source, ["unit:1"])
    assert rc == 2, (rc, out, problem)
    assert problem and "SEMANTIC_PROGRESS_NORECORD" in problem
    assert "outcome=aborted" in problem


def test_child_cannot_replace_parent_bound_progress_inode(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.02)
    source = f"""
import json,os,time
path = os.environ['{S.ENV_PATH}']
os.unlink(path)
row = {{'schema': 1, 'nonce': os.environ['{S.ENV_NONCE}'],
       'pid': os.getpid(), 'seq': 0, 'state': 'start',
       'scope': {SCOPE!r}, 'total': 1}}
with open(path, 'w', encoding='utf-8') as stream:
    stream.write(json.dumps(row)+'\\n')
time.sleep(5)
"""
    rc, out, problem = _semantic(tmp_path, source, ["unit:1"])
    assert rc == 2, (rc, out, problem)
    assert problem and "SEMANTIC_PROGRESS_NORECORD" in problem
    assert "identity changed" in problem or "disappeared" in problem


def test_parent_rejects_symlink_replacement_even_when_it_resolves_to_same_inode(
        tmp_path):
    plan = S.prepare_parent(tmp_path, SCOPE, [], _env())
    monitor = S.ParentMonitor.from_manifest(plan.manifest_path)
    monitor.bind_pid(4321)
    retained = tmp_path / "retained-channel"
    os.link(plan.progress_path, retained)
    plan.progress_path.unlink()
    plan.progress_path.symlink_to(retained)
    _append_rows(retained, monitor._expected(0), monitor._expected(1))
    monitor.sample()
    assert "identity changed" in monitor.error
    monitor.close()


def test_callback_failure_aborts_instead_of_becoming_a_renewal(
        tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.02)
    escaped = tmp_path / "callback-failure-escaped"
    pending_before = list(P._PENDING_REAPERS)
    source = f"""
import pathlib,signal,time
from _semantic_child_progress import child_progress
signal.signal(signal.SIGTERM, signal.SIG_IGN)
with child_progress({SCOPE!r}) as progress:
    time.sleep(.03)
    progress.checkpoint('unit:1')
    time.sleep(5)
    pathlib.Path({str(escaped)!r}).write_text('escaped\\n')
"""

    def refuse(_scope, _completed, _total):
        raise RuntimeError("outer lease unavailable")

    rc, out, problem = _semantic(
        tmp_path, source, ["unit:1", "unit:2"], callback=refuse)
    assert rc == 2, (rc, out, problem)
    assert problem and "callback failed" in problem
    assert "atomic cleanup=shutdown_complete/final_descendants=[]" in problem
    assert not escaped.exists(), "callback failure abandoned its owned child"
    assert list(P._PENDING_REAPERS) == pending_before, (
        "semantic channel failure returned with a live background reaper")


def test_zero_unit_natural_fsm_is_complete_but_never_relays(
        tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.02)
    relays = []
    source = f"""
from _semantic_child_progress import child_progress
with child_progress({SCOPE!r}):
    pass
"""
    rc, out, problem = _semantic(
        tmp_path, source, [], callback=lambda *event: relays.append(event))
    assert (rc, problem) == (0, None), (rc, out, problem)
    assert relays == []


@pytest.mark.parametrize("payload", [
    '{"seq":1,"seq":2}',
    '{"seq":NaN}',
    '{"seq":Infinity}',
])
def test_protocol_json_is_unambiguous(payload):
    with pytest.raises((ValueError, S.ProgressProtocolError)):
        S.strict_loads(payload)


def test_protocol_integer_fields_reject_bool():
    with pytest.raises(S.ProgressProtocolError):
        S.RelayValidator(SCOPE, True, None)


def test_atomic_final_zero_proof_rejects_incomplete_census():
    status = {
        "protocol": 1, "state": "shutdown_complete", "reaper_pid": 10,
        "reaper_starttime": 20, "exit_code": 128 + 15,
        "census_ok": True, "final_descendants": [], "observed": [],
    }
    assert P._shutdown_final_zero(
        status, helper_pid=10, helper_starttime=20, helper_rc=143)
    assert not P._shutdown_final_zero(
        {**status, "census_ok": False}, helper_pid=10,
        helper_starttime=20, helper_rc=143)

    result = {
        "protocol": 1, "rc": 0, "body": "", "problem": None,
        "outcome": "natural", "launched": True, "census_ok": True,
        "final_descendants": [], "observed": [], "capability_error": "",
    }
    assert P._owned_final_zero(result)
    assert not P._owned_final_zero({**result, "census_ok": False})
    assert not P._owned_final_zero({**result, "launched": False})
    assert not P._owned_final_zero({**result, "outcome": "invented"})
    duplicate = {"pid": 11, "starttime": 22}
    assert not P._owned_final_zero(
        {**result, "observed": [duplicate, duplicate]})


def test_file_work_is_split_by_bytes_and_oversize_refuses_before_verdict(
        tmp_path):
    bounded = tmp_path / "bounded.json"
    bounded.write_bytes(b"x" * (S.WORK_CHUNK_BYTES * 2 + 1))
    size = S.WORK_CHUNK_BYTES * 2 + 1
    assert S.file_progress_units(bounded, "document:bounded") == [
        f"document:bounded:bytes:{size}:chunk:1/3",
        f"document:bounded:bytes:{size}:chunk:2/3",
        f"document:bounded:bytes:{size}:chunk:3/3",
        f"document:bounded:bytes:{size}:judged",
    ]
    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as stream:
        stream.truncate(S.MAX_WORK_FILE_BYTES + 1)
    with pytest.raises(S.ProgressProtocolError, match="resource bound"):
        S.file_progress_units(oversized, "document:oversized")


def test_semantic_l4_git_failure_cannot_fallback_to_untracked_disk_population(
        tmp_path, monkeypatch):
    root = tmp_path / "corpus"
    tracked = root / "tracked" / "L4_REGMAP.json"
    untracked = root / "untracked" / "L4_REGMAP.json"
    tracked.parent.mkdir(parents=True)
    untracked.parent.mkdir(parents=True)
    tracked.write_text("{}\n")
    untracked.write_text("{}\n")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "tracked/L4_REGMAP.json"],
                   check=True)
    kept, _found, published = L4._l4_documents(root)
    assert (kept, published) == ([tracked], True)

    seen_kwargs = []

    def expire(argv, **kwargs):
        seen_kwargs.append(dict(kwargs))
        # git is stopped for making no progress now, not for elapsed time.
        raise _pr.Stalled(argv, 3, 1.0, 3.0, {"cpu": True, "io": True})

    monkeypatch.setattr(
        _corpus_location, "not_a_checkout_reason", lambda *_a, **_k: None)
    # A module reaches a process through `subprocess`, through `_pr`
    # (`_progress_run`, the progress-supervised drop-in) or through both.
    # Substituting on only one leaves the real launcher answering the
    # question this test is asking about a fake one, and the test then
    # passes or fails for a reason that has nothing to do with its subject.
    for _launcher in (getattr(_published_tree, "subprocess", None),
                      getattr(_published_tree, "_pr", None)):
        if _launcher is not None:
            monkeypatch.setattr(_launcher, "run", expire)
    ordinary, _found, published = L4._l4_documents(root)
    assert set(ordinary) == {tracked, untracked} and published is False, (
        "the control no longer reaches the historical timeout fallback")
    with pytest.raises(_published_tree.PublishedTreeIndeterminate):
        L4._l4_documents(root, semantic_strict=True)
    # THE INVERSE OF WHAT THIS USED TO ASSERT, and for the reason the
    # assertion had to change. It read `seen_timeouts == [180, None]`: the
    # first probe spent a 180 s bound and the second did not. There is no bound
    # to spend now — git runs to completion however long it legitimately takes
    # and is stopped only if it stops moving — so asserting the ABSENCE is what
    # keeps one from being quietly reintroduced at either call site.
    assert len(seen_kwargs) == 2, seen_kwargs
    assert all("timeout" not in kw for kw in seen_kwargs), (
        f"a wall-clock bound is being spent on a git probe again: "
        f"{seen_kwargs!r}")


@pytest.mark.parametrize("planted,want_rc", [(False, 0), (True, 1)])
@pytest.mark.parametrize("empty_index", [False, True])
def test_semantic_l4_preserves_supported_loose_directory_verdict(
        tmp_path, planted, want_rc, empty_index):
    root = tmp_path / ("loose-planted" if planted else "loose-clean")
    doc = root / "cell" / "L4_REGMAP.json"
    doc.parent.mkdir(parents=True)
    register = ({"an_unclassified_key": 1} if planted else {})
    doc.write_text(json.dumps({"registers": [register]}) + "\n")
    if empty_index:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
    argv = [sys.executable, str(PROGRAMS / "l4_systemrdl_export.py"),
            "audit-corpus", "--root", str(root)]
    ordinary = subprocess.run(argv, capture_output=True, text=True)
    units = L4.semantic_progress_units(root)
    rc, out, problem = P._run(
        argv, tmp_path, _env(), semantic_progress_scope=L4.PROGRESS_SCOPE,
        semantic_progress_units=units)
    assert ordinary.returncode == want_rc, ordinary.stdout + ordinary.stderr
    assert (rc, problem) == (want_rc, None), (rc, out, problem, units)
    assert "NOT a git checkout" in out


def test_semantic_checkout_probe_has_no_inner_duration_verdict(
        tmp_path, monkeypatch):
    seen = []

    def expire(argv, **kwargs):
        seen.append(kwargs.get("timeout"))
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))

    for _launcher in (getattr(_corpus_location, "subprocess", None),
                      getattr(_corpus_location, "_pr", None)):
        if _launcher is not None:
            monkeypatch.setattr(_launcher, "run", expire)
    with pytest.raises(_corpus_location.CorpusIndexIndeterminate):
        _corpus_location.not_a_checkout_reason(
            tmp_path, "routing records", timeout=None, strict=True)
    assert seen == [None]
    with pytest.raises(ValueError, match="without an inner timeout"):
        _corpus_location.not_a_checkout_reason(
            tmp_path, "routing records", timeout=1, strict=True)
    with pytest.raises(ValueError, match="without an inner timeout"):
        _published_tree.published_paths(tmp_path, timeout=1, strict=True)


def test_strict_published_index_accepts_exact_tracked_symlink_blobs(tmp_path):
    root = tmp_path / "published"
    root.mkdir()
    (root / "target.json").write_text("{}\n")
    (root / "link.json").symlink_to("target.json")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "target.json", "link.json"],
                   check=True)
    ordinary = _published_tree.published_paths(root)
    strict = _published_tree.published_paths(
        root, timeout=None, strict=True)
    assert strict == ordinary == frozenset({"target.json", "link.json"})


def test_chatty_hung_l4_git_probe_is_semantic_norecord_not_a_disk_verdict(
        tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DEFAULT_POLL_S", 0.02)
    root = tmp_path / "corpus"
    doc = root / "untracked" / "L4_REGMAP.json"
    doc.parent.mkdir(parents=True)
    doc.write_text("{}\n")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/bin/sh\nwhile :; do echo fake-git-is-chatty; done\n")
    fake_git.chmod(0o755)
    env = _env()
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    rc, out, problem = P._run(
        [sys.executable, str(PROGRAMS / "l4_systemrdl_export.py"),
         "audit-corpus", "--root", str(root), "--corpus-may-be-absent"],
        tmp_path, env, stall_grace_s=0.14,
        semantic_progress_scope=L4.PROGRESS_SCOPE,
        semantic_progress_units=["root:1"])
    assert rc == 2, (rc, out, problem)
    assert problem and "SEMANTIC_PROGRESS_NORECORD" in problem
    assert "outcome=stalled" in problem
    assert "[PASS]" not in out and "NO_CORPUS" not in out


def _append_rows(path: Path, *rows: dict) -> None:
    with path.open("ab") as stream:
        for row in rows:
            stream.write((S._canonical(row) + "\n").encode("utf-8"))


@pytest.mark.parametrize("mutate", [
    lambda row: {**row, "unit": "unit:forged"},
    lambda row: {**row, "seq": 0},
    lambda row: {**row, "completed": True},
    lambda row: {**row, "total": 2},
])
def test_parent_rejects_forged_unit_counts_sequences_and_bool(
        tmp_path, mutate):
    plan = S.prepare_parent(tmp_path, SCOPE, ["unit:1"], _env())
    monitor = S.ParentMonitor.from_manifest(plan.manifest_path)
    monitor.bind_pid(4321)
    _append_rows(plan.progress_path, monitor._expected(0),
                 mutate(monitor._expected(1)))
    monitor.sample()
    assert monitor.error
    monitor.close()


def test_parent_rejects_duplicate_event_and_truncated_history(tmp_path):
    duplicate_dir = tmp_path / "duplicate"
    plan = S.prepare_parent(duplicate_dir, SCOPE, ["unit:1"], _env())
    monitor = S.ParentMonitor.from_manifest(plan.manifest_path)
    monitor.bind_pid(4321)
    checkpoint = monitor._expected(1)
    _append_rows(plan.progress_path, monitor._expected(0), checkpoint,
                 checkpoint)
    monitor.sample()
    assert "differs" in monitor.error
    monitor.close()

    truncate_dir = tmp_path / "truncate"
    plan = S.prepare_parent(truncate_dir, SCOPE, ["unit:1"], _env())
    monitor = S.ParentMonitor.from_manifest(plan.manifest_path)
    monitor.bind_pid(4321)
    _append_rows(plan.progress_path, monitor._expected(0), monitor._expected(1))
    assert monitor.sample() == 1 and not monitor.error
    plan.progress_path.write_bytes(b"")
    monitor.sample()
    assert "truncated" in monitor.error or "rewritten" in monitor.error
    monitor.close()


def test_partial_tail_is_tolerated_only_until_natural_terminal(tmp_path):
    plan = S.prepare_parent(tmp_path, SCOPE, [], _env())
    monitor = S.ParentMonitor.from_manifest(plan.manifest_path)
    monitor.bind_pid(4321)
    start = S._canonical(monitor._expected(0)).encode("utf-8")
    plan.progress_path.write_bytes(start[:-1])
    assert monitor.sample() == 0 and not monitor.error
    with plan.progress_path.open("ab") as stream:
        stream.write(start[-1:] + b"\n")
    assert monitor.sample() == 0 and not monitor.error
    _append_rows(plan.progress_path, monitor._expected(1))
    assert monitor.complete() == ""

    bad_dir = tmp_path / "bad-final"
    plan = S.prepare_parent(bad_dir, SCOPE, [], _env())
    monitor = S.ParentMonitor.from_manifest(plan.manifest_path)
    monitor.bind_pid(4321)
    plan.progress_path.write_bytes(b"{\"schema\":")
    assert "truncated final" in monitor.complete()
