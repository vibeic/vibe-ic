"""F35 — a write into the directory pytest was INVOKED from must not read clean.

WHAT WAS MEASURED
=================
In the vibeic-eda image (uid 1000, account-home bind) the ATPG engine's LOCAL
route inherited the caller's cwd, and the engine writes relative to `.`: its PLY
parser leaves `parser.out` + `parsetab.py`, its simulator a `thr0x…/tb.sv`. Run
from the plugin root of the tree under test, `suite_write_guard` went RED on
all three. Run from ANOTHER checkout's plugin root against the same tests, the
three files landed in that checkout and the guard printed
`[PASS] … wrote nothing` with the session at rc 0 — because it measured only
the tree that holds its own file, and the cwd was a different tree.

Two fixes, each with its own control here:

  * the guard also measures the invocation checkout when it is another
    checkout of the SAME tree (`_cwd_sibling_root`) — and still does not
    measure an unrelated ambient repository (#1412's side of the line);
  * the local ATPG routes run the engine in a throwaway cwd, as the container
    route always did (`_container_exec.local_engine_cwd`).

The positive sample is the REAL one: the paths and the bytes the engine wrote,
from `fixtures/f35_in_image_cwd_write_sample.json` (see its `_provenance`).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
_PROGRAMS = _TESTS.parent
sys.path.insert(0, str(_PROGRAMS))
sys.path.insert(0, str(_TESTS))

import _container_exec as CE  # noqa: E402
import _progress_run as _pr  # noqa: E402
import fault_atpg_run as F  # noqa: E402
import transition_fault_atpg_run as T  # noqa: E402

















# ── the writer: the local ATPG routes run the engine in a throwaway cwd ────

_ENGINE_LIKE = ("printf x > parser.out && printf x > parsetab.py && "
                "mkdir -p thr0x0000782ab8001030 && "
                "printf x > thr0x0000782ab8001030/tb.sv && echo ENGINE_RAN")


@pytest.fixture
def local_route(monkeypatch, tmp_path):
    real = CE.shutil.which
    monkeypatch.setattr(CE.shutil, "which",
                        lambda n, *a, **k: None if n == "docker"
                        else real(n, *a, **k))
    invoker = tmp_path / "invoker"
    invoker.mkdir()
    monkeypatch.chdir(invoker)
    project = tmp_path / "project"
    project.mkdir()
    return invoker, project


@pytest.mark.parametrize("supervised", [False, True])
def test_stuck_at_local_route_does_not_write_into_the_callers_cwd(
        local_route, supervised):
    invoker, project = local_route
    rc, out, err = F._run_docker(project, [_ENGINE_LIKE], supervised=supervised)
    assert rc == 0 and "ENGINE_RAN" in out, (rc, out, err)
    assert sorted(p.name for p in invoker.iterdir()) == [], (
        "the engine wrote into the caller's cwd")
    assert sorted(p.name for p in project.iterdir()) == []


def test_at_speed_local_route_does_not_write_into_the_callers_cwd(local_route):
    invoker, project = local_route
    rc, out, err = T._run_in_docker(project, _ENGINE_LIKE, timeout=60)
    assert rc == 0 and "ENGINE_RAN" in out, (rc, out, err)
    assert sorted(p.name for p in invoker.iterdir()) == [], (
        "the engine wrote into the caller's cwd")
    assert sorted(p.name for p in project.iterdir()) == []
