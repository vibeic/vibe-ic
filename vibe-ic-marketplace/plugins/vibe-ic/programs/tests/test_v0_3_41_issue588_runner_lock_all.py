"""ORGANIC #588 — only the top orchestrator took the project runner-lock;
standalone phase1/2/3 runner invocations neither acquired nor honored it,
so the single-driver guarantee had a hole exactly where long phase3
re-runs happen (two standalone phase3 runners could co-write the same
project's pnr/ + reports/).

Fix: _runner_lock.acquire_or_reenter() is the shared entry all four
runners call; the orchestrator exports a re-entrancy env token
(VIBE_IC_RUNNER_LOCK_TOKEN = "<holder_pid>:<project>") via child_env so a
delegated sub-run re-enters the parent lock, while a SECOND standalone
runner on a live project is refused by name.
"""
import os
import sys
from pathlib import Path

import pytest

from _runner_ast_fixture import called_main, live_nodes

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import _runner_lock as RL  # noqa: E402


def test_second_standalone_refused_on_live_project(tmp_path, monkeypatch):
    """A live holder + NO re-entrancy token → the second acquire is
    refused by name (CONCURRENT_RUN_REFUSED)."""
    monkeypatch.delenv(RL.REENTRANCY_ENV, raising=False)
    first = RL.acquire_or_reenter(tmp_path, "phase3_one_shot_runner")
    assert first is not None and not getattr(first, "reentrant", False)
    # Same process pid holds it and is alive → a fresh acquire is refused.
    second = RL.acquire_or_reenter(tmp_path, "phase3_one_shot_runner")
    assert second is None
    first.release()


def test_stale_lock_auto_broken(tmp_path, monkeypatch, capsys):
    """A lock file whose holder pid is dead is auto-broken with the
    STALE_RUNNER_LOCK note, and the new runner takes it."""
    monkeypatch.delenv(RL.REENTRANCY_ENV, raising=False)
    import json
    dead_pid = 999999  # not alive
    (tmp_path / RL.LOCK_FILENAME).write_text(json.dumps(
        {"pid": dead_pid, "timestamp": "2020-01-01T00:00:00Z",
         "runner": "phase3_one_shot_runner"}))
    lock = RL.acquire_or_reenter(tmp_path, "phase3_one_shot_runner")
    assert lock is not None
    err = capsys.readouterr().err
    assert "STALE_RUNNER_LOCK" in err
    lock.release()


def test_delegated_subrun_reenters_parent_lock(tmp_path, monkeypatch, capsys):
    """The orchestrator-shape: parent holds the lock + exports the token;
    a child (same project) re-enters instead of being refused, and its
    release does NOT remove the parent's lock file."""
    monkeypatch.delenv(RL.REENTRANCY_ENV, raising=False)
    parent = RL.acquire_or_reenter(tmp_path, "vibe_ic_one_shot_runner")
    assert parent is not None
    env = RL.child_env(tmp_path, held_lock=parent)
    assert RL.REENTRANCY_ENV in env
    # Simulate the child process seeing the exported token.
    monkeypatch.setenv(RL.REENTRANCY_ENV, env[RL.REENTRANCY_ENV])
    child = RL.acquire_or_reenter(tmp_path, "phase3_one_shot_runner")
    assert getattr(child, "reentrant", False) is True
    assert "RUNNER_LOCK_REENTRANT" in capsys.readouterr().err
    child.release()  # must NOT delete the parent's file
    assert (tmp_path / RL.LOCK_FILENAME).is_file()
    parent.release()
    assert not (tmp_path / RL.LOCK_FILENAME).is_file()


def test_stale_token_does_not_bypass_foreign_lock(tmp_path, monkeypatch):
    """A token naming a DEAD pid must not let a runner bypass a real
    live foreign lock — re-entry requires a live holder whose lock file
    actually exists for that pid."""
    monkeypatch.delenv(RL.REENTRANCY_ENV, raising=False)
    live = RL.acquire_or_reenter(tmp_path, "phase3_one_shot_runner")
    assert live is not None
    # Token claims a dead pid as holder → must NOT re-enter; the real
    # live lock (held by this pid) then refuses the newcomer.
    monkeypatch.setenv(RL.REENTRANCY_ENV, f"999999:{tmp_path.resolve()}")
    refused = RL.acquire_or_reenter(tmp_path, "phase3_one_shot_runner")
    assert refused is None
    live.release()


def test_token_for_other_project_does_not_reenter(tmp_path, monkeypatch):
    """A token for a DIFFERENT project must not re-enter THIS project's
    lock (path-scoped)."""
    monkeypatch.delenv(RL.REENTRANCY_ENV, raising=False)
    other = tmp_path / "other"
    other.mkdir()
    here = tmp_path / "here"
    here.mkdir()
    held = RL.acquire_or_reenter(here, "phase3_one_shot_runner")
    assert held is not None
    monkeypatch.setenv(RL.REENTRANCY_ENV,
                       f"{os.getpid()}:{other.resolve()}")
    # Token names `other`, lock is on `here` → no re-entry → refused
    # (this pid holds a live lock on `here`).
    refused = RL.acquire_or_reenter(here, "phase3_one_shot_runner")
    assert refused is None
    held.release()


def test_child_env_propagates_inherited_token_when_reentrant(
        tmp_path, monkeypatch):
    """A re-entrant process (itself a sub-run) must propagate the
    ORIGINAL top holder's token to ITS children, not its own non-holding
    pid."""
    monkeypatch.delenv(RL.REENTRANCY_ENV, raising=False)
    top = RL.acquire_or_reenter(tmp_path, "vibe_ic_one_shot_runner")
    token = RL.child_env(tmp_path, held_lock=top)[RL.REENTRANCY_ENV]
    monkeypatch.setenv(RL.REENTRANCY_ENV, token)
    mid = RL.acquire_or_reenter(tmp_path, "design_one_shot_runner")
    assert getattr(mid, "reentrant", False) is True
    env = RL.child_env(tmp_path, held_lock=mid)
    assert env[RL.REENTRANCY_ENV] == token  # propagated, not rewritten
    top.release()


def _assert_runner_acquires(src, name):
    import ast
    main = called_main(ast.parse(src))
    calls = [n for n in live_nodes(main) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and isinstance(n.func.value, ast.Name)
             and n.func.value.id == "_runner_lock"
             and n.func.attr == "acquire_or_reenter"]
    assert calls, f"{name}: called implementation never calls acquire_or_reenter"


def test_all_four_runners_call_acquire_or_reenter():
    """Every runner's main must take the shared lock (the hole #588
    closes is exactly the standalone runners that previously didn't)."""
    for name in ("vibe_ic_one_shot_runner", "phase1_one_shot_runner",
                 "design_one_shot_runner", "phase3_one_shot_runner"):
        _assert_runner_acquires((PROG / f"{name}.py").read_text(), name)


@pytest.mark.parametrize("body", [
    '"acquire_or_reenter"\n    return 0',
    'def unused():\n        _runner_lock.acquire_or_reenter(p, r)\n    return 0',
    'return 0\n    _runner_lock.acquire_or_reenter(p, r)',
    'if False:\n        _runner_lock.acquire_or_reenter(p, r)\n    return 0',
])
def test_runner_lock_check_rejects_strings_and_uncalled_code(body):
    src = f'def main():\n    return _main()\ndef _main():\n    {body}\n'
    with pytest.raises(AssertionError, match="never calls"):
        _assert_runner_acquires(src, "disconnected_fixture")


def test_runner_lock_check_rejects_an_uncalled_implementation():
    src = (PROG / "vibe_ic_one_shot_runner.py").read_text()
    assert 'return _main()' in src
    with pytest.raises(AssertionError, match="does not return"):
        _assert_runner_acquires(src.replace('return _main()', 'return 0'),
                               "vibe_ic_one_shot_runner")
