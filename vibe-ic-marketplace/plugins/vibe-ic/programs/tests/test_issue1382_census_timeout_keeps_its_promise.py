#!/usr/bin/env python3
"""The census step's timeout path must keep the promise its own docstring makes.

THE PROMISE, quoted from `gatekeeper_prepare_landing`'s module docstring:
a census step that cannot complete "leaves the landing exactly where it stood
before this step existed ... the only thing it can do is fail to save an hour".

THE DEFECT IT DID NOT KEEP IT UNDER (vibe-ic#1382, refuting PR #1659)
====================================================================
`subprocess.run(..., timeout=N)` kills the child with SIGKILL. A child's
``finally:`` therefore never runs, so the generator's own
``--written-json`` declaration is never written and `_read_written` returns
``[]``. Meanwhile `--fix` has already rewritten anchored figures: the tree IS
dirty. The boundary check downstream then sees a dirty path that nothing
declared and REFUSES, and `gatekeeper-land.sh` exits 1 on a refusal.

So on a loaded host — the exact condition the bound exists for — a best-effort
convenience turned into a landing that could not start. The old comment said
"anything written before it fired is still declared"; nothing was.

WHY THE FIRST TEST BELOW IS THE ONE THAT MATTERS
================================================
It asserts the OS behaviour directly rather than trusting the reading. If a
future Python made `subprocess.run` terminate gracefully, this test would fail
and the fix could be simplified — which is the honest way for a workaround to
expire.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
sys.path.insert(0, str(_PROGRAMS))

import gatekeeper_prepare_landing as G  # noqa: E402
import _progress_run as PR  # noqa: E402
import _watchdog  # noqa: E402


def _supervised(cmd, **kw):
    """`subprocess.run(cmd, capture_output=True, text=True, check=False)` with
    the wall-clock budget REPLACED by forward-progress supervision.

    These call sites used to carry a fixed `timeout=`. That number is not a
    property of the subject — it is a guess about a HOST — and when the guess is
    wrong on a loaded machine `TimeoutExpired` propagates out of the test and is
    recorded as the SUBJECT being broken. The verdict is then manufactured by
    the machine rather than measured on the program; the owner hit exactly that
    on a module nobody had changed.

    `_watchdog.run_host_supervised` bounds NO FORWARD PROGRESS instead — CPU and
    I/O summed over the child's whole /proc tree, plus the growth of its
    captured output — so a child that is merely slow runs to completion however
    long that legitimately takes, while one that is genuinely hung is still
    killed. A kill arrives as rc `_watchdog.RC_STALLED` with WATCHDOG_STALLED on
    stderr: a distinct code none of these subjects produces itself, so a hang
    can never be misread as an ordinary non-zero exit."""
    res = _watchdog.run_host_supervised(cmd, **kw)
    return _watchdog.completed_process(cmd, res)


# ══════════════════════════════════════════════════════════════════════
# The premise, asserted rather than assumed
# ══════════════════════════════════════════════════════════════════════

def test_a_stopped_child_never_runs_its_finally(tmp_path):
    """This is WHY the declaration comes back empty. Assert it, do not argue it.

    THE STOP IS THE SUPERVISOR'S NOW (vibe-ic#2051, R4) and it is still a
    SIGKILL, so the premise is unchanged — but it is asserted against the call
    the census actually makes, not against a `subprocess.run` the census no
    longer contains. If a future supervisor stopped a child gracefully, this
    test fails and the workaround in the stall branch can be simplified: that
    is the honest way for a workaround to expire.
    """
    child = tmp_path / "child.py"
    decl = tmp_path / "written.json"
    child.write_text(
        "import sys, time, pathlib\n"
        "try:\n"
        "    time.sleep(30)\n"
        "finally:\n"
        "    pathlib.Path(sys.argv[1]).write_text('[\"a\"]')\n",
        encoding="utf-8")
    with pytest.raises(PR.Stalled):
        PR.run([sys.executable, str(child), str(decl)],
               stall_looks=4, poll_s=0.25)
    assert not decl.exists(), (
        "the supervisor stopped SIGKILLing a stalled child — the workaround in "
        "_default_census_writer's stall branch can now be simplified")


def test_read_written_reports_an_absent_declaration_as_empty(tmp_path):
    """The other half of the premise: [] is what the caller actually receives."""
    assert G._read_written(tmp_path / "does-not-exist.json") == []


# ══════════════════════════════════════════════════════════════════════
# The behaviour, in both directions, against a real git tree
# ══════════════════════════════════════════════════════════════════════

def _tight(monkeypatch, looks=4, poll_s=0.25):
    """Make the stall REACHABLE inside a test session, and change nothing else.

    The predicate is still "captured output, the process tree's CPU and its
    block I/O ALL sat still for `looks` consecutive looks"; only the spacing
    moves. The writers below write once and then sleep, so they are motionless
    on every signal — which is exactly the shape the census showed when it
    wedged, and exactly what a merely SLOW census is not.

    It is read at call time by `_default_census_writer`, for the reason that
    function records in full: a bound nobody can override in a test is a bound
    whose failure path is unreachable.
    """
    monkeypatch.setattr(G, "CENSUS_STALL_LOOKS", looks)
    monkeypatch.setattr(G, "CENSUS_POLL_S", poll_s)


@pytest.fixture()
def repo(tmp_path):
    """A real repository with one tracked file, so `git checkout --` can restore."""
    r = tmp_path / "r"
    (r / "sub").mkdir(parents=True)
    def git(*a):
        return _supervised(["git", "-C", str(r), *a])
    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (r / "anchor.py").write_text("FIGURE = 164\n", encoding="utf-8")
    (r / "sub" / "index.md").write_text("index v1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "base")
    return r


def _slow_writer(repo_path: Path, target: str, seconds: int) -> Path:
    """A stand-in generator that WRITES first and then hangs — the real shape."""
    p = repo_path / "_slow_gen.py"
    p.write_text(
        "import sys, time, pathlib\n"
        f"pathlib.Path(sys.argv[1]).joinpath({target!r}).write_text('FIGURE = 165\\n')\n"
        f"time.sleep({seconds})\n",
        encoding="utf-8")
    return p


def test_a_stall_leaves_the_tree_exactly_where_it_stood(repo, monkeypatch):
    """THE PROMISE. A census that could not finish must declare nothing AND
    leave nothing."""
    gen = _slow_writer(repo, "anchor.py", 30)
    monkeypatch.setattr(G, "GEN_CENSUS", gen)
    _tight(monkeypatch)

    wrote, reason = G._default_census_writer(repo)

    assert reason and "did not finish" in reason
    assert wrote == [], f"declared {wrote} after a stall"
    assert set(G.dirty_paths(repo)) == set(), (
        "the tree is still dirty after a stall, so the boundary check will "
        "refuse the landing on a path nothing declared — this is #1382")
    assert (repo / "anchor.py").read_text(encoding="utf-8") == "FIGURE = 164\n"


def test_a_stall_does_not_revert_what_an_earlier_step_wrote(repo, monkeypatch):
    """The paired guard for the restore: it must undo the CENSUS, nothing else.

    The index step runs before the census and its write is already dirty. A
    restore that reverted everything dirty would silently discard it.
    """
    (repo / "sub" / "index.md").write_text("index v2 — written by the index step\n",
                                           encoding="utf-8")
    gen = _slow_writer(repo, "anchor.py", 30)
    monkeypatch.setattr(G, "GEN_CENSUS", gen)
    _tight(monkeypatch)

    wrote, reason = G._default_census_writer(repo)

    assert wrote == [] and "did not finish" in (reason or "")
    assert (repo / "sub" / "index.md").read_text(encoding="utf-8").startswith("index v2"), \
        "the stall restore reverted the earlier index step's write"
    assert set(G.dirty_paths(repo)) == {"sub/index.md"}, G.dirty_paths(repo)


def test_a_stall_kills_grandchildren_before_restoring(repo, monkeypatch):
    """An orphan writer must not re-dirty the tree after the function returns."""
    delayed = repo / "_grandchild.py"
    delayed.write_text(
        "import pathlib, sys, time\n"
        "time.sleep(3)\n"
        "pathlib.Path(sys.argv[1]).write_text('LATE\\n')\n",
        encoding="utf-8")
    gen = repo / "_parent_gen.py"
    gen.write_text(
        "import pathlib, subprocess, sys, time\n"
        "root = pathlib.Path(sys.argv[1])\n"
        "root.joinpath('anchor.py').write_text('EARLY\\n')\n"
        f"subprocess.Popen([sys.executable, {str(delayed)!r}, "
        "str(root / 'anchor.py')], stdout=subprocess.DEVNULL, "
        "stderr=subprocess.DEVNULL)\n"
        "time.sleep(30)\n",
        encoding="utf-8")
    monkeypatch.setattr(G, "GEN_CENSUS", gen)
    _tight(monkeypatch)

    wrote, reason = G._default_census_writer(repo)

    assert wrote == [] and "did not finish" in (reason or "")
    assert (repo / "anchor.py").read_text(encoding="utf-8") == "FIGURE = 164\n"
    time.sleep(4)
    assert (repo / "anchor.py").read_text(encoding="utf-8") == "FIGURE = 164\n", \
        "a surviving grandchild wrote after the stall restore"
    assert G.dirty_paths(repo) == set()


def test_a_writer_that_finishes_still_declares_normally(repo, monkeypatch):
    """The can-pass direction: the fix must not disturb the successful path."""
    gen = repo / "_fast_gen.py"
    gen.write_text(
        "import sys, pathlib, json\n"
        "root = pathlib.Path(sys.argv[1])\n"
        "root.joinpath('anchor.py').write_text('FIGURE = 165\\n')\n"
        "i = sys.argv.index('--written-json')\n"
        "pathlib.Path(sys.argv[i + 1]).write_text(json.dumps(['anchor.py']))\n",
        encoding="utf-8")
    monkeypatch.setattr(G, "GEN_CENSUS", gen)
    _tight(monkeypatch)

    wrote, reason = G._default_census_writer(repo)

    assert reason is None, reason
    assert wrote == ["anchor.py"]
    assert (repo / "anchor.py").read_text(encoding="utf-8") == "FIGURE = 165\n", \
        "a successful census had its write reverted"


def test_a_partial_repair_that_finishes_nonzero_still_declares(repo, monkeypatch):
    """`--fix` writing figures and then failing is the NORMAL partial repair.

    Both halves must survive: the paths, and the reason. This is the case the
    original docstring is right about, and the timeout fix must not break it.
    """
    gen = repo / "_partial_gen.py"
    gen.write_text(
        "import sys, pathlib, json\n"
        "root = pathlib.Path(sys.argv[1])\n"
        "root.joinpath('anchor.py').write_text('FIGURE = 165\\n')\n"
        "i = sys.argv.index('--written-json')\n"
        "pathlib.Path(sys.argv[i + 1]).write_text(json.dumps(['anchor.py']))\n"
        "print('census block still stale'); sys.exit(1)\n",
        encoding="utf-8")
    monkeypatch.setattr(G, "GEN_CENSUS", gen)
    _tight(monkeypatch)

    wrote, reason = G._default_census_writer(repo)

    assert wrote == ["anchor.py"], "a partial repair lost its declared write"
    assert reason and "rc=1" in reason, reason
    assert (repo / "anchor.py").read_text(encoding="utf-8") == "FIGURE = 165\n"
