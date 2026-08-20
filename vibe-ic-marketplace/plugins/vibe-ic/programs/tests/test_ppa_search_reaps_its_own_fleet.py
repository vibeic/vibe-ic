#!/usr/bin/env python3
"""Stopping a capped search has to stop the search.

MEASURED 2026-08-21 on a 32-core host, mid-campaign: killing the `ppa_search`
process left SIX `phase3_one_shot_runner` children alive, and FOUR of them were
working in run directories the relaunched search had ALREADY DELETED —
`/proc/<pid>/cwd` ended in "(deleted)". Roughly 26 cores were being spent
writing into dead inodes while the new search's `shutil.rmtree` raced them for
the same paths, and the host sat at load 172 with two other agents on it.

A `--jobs`-capped search whose parent dies uncapped is not capped. These tests
pin the reaper, and pin equally hard the thing it CANNOT do — the EDA processes
running inside the shared container do not die with their host-side parent
(measured: two `openroad` processes outlived the python that launched them), and
the program has to say so rather than let a clean exit imply a clean host.

The subprocess here is `sleep`, not an EDA tool: the property under test is
"does this program leave its children running", which has nothing to do with
what the children are.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import List

import pytest

import ppa_search


@pytest.fixture(autouse=True)
def _no_leaked_children():
    yield
    ppa_search._reap_children()


def _spawn(n: int):
    procs = []
    for _ in range(n):
        p = subprocess.Popen([sys.executable, "-c",
                              "import time; time.sleep(600)"])
        with ppa_search._CHILDREN_LOCK:
            ppa_search._CHILDREN.add(p)
        procs.append(p)
    return procs


def test_reaping_terminates_every_tracked_child_PROMPTLY():
    """Bounded in TIME on purpose. `_reap_children` has a `terminate()` and a
    `kill()` fallback, and with the terminate removed the fallback still ends
    up killing everything — after `wait(timeout=10)` expires for each child in
    turn. A search stopped because the host is overloaded cannot spend 10
    seconds per in-flight run deciding to stop; measured, that is exactly the
    window in which the relaunched search starts deleting the directories they
    are still writing into. So the assertion is "they are gone AND it did not
    take long", which the kill-only path cannot satisfy."""
    procs = _spawn(3)
    assert all(p.poll() is None for p in procs)
    t0 = time.time()
    ppa_search._reap_children()
    elapsed = time.time() - t0
    assert all(p.poll() is not None for p in procs), (
        "a search that exits leaving its fleet running is not capped, whatever "
        "--jobs said")
    assert elapsed < 5.0, (
        f"reaping 3 children took {elapsed:.1f}s — the children must be asked "
        "to stop, not waited out")


def test_run_one_registers_its_child_WHILE_IT_RUNS(tmp_path):
    """A child that is never registered cannot be reaped, and nothing else in
    this file would notice: the other tests populate the registry by hand. This
    one goes through `run_one` and looks at the registry while the run is still
    in flight."""
    import threading

    design = tmp_path / "design"
    (design / "phase1" / "generated_docs").mkdir(parents=True)
    slow = tmp_path / "slow_runner.py"
    slow.write_text("import time; time.sleep(600)\n")

    seen: List[int] = []
    done = threading.Event()

    def _go():
        try:
            ppa_search.run_one(design, tmp_path / "out",
                               {"util": 0.3, "die_um": "auto",
                                "spare_density": 0.02},
                               "top", slow, "none", timeout_s=600)
        finally:
            done.set()

    t = threading.Thread(target=_go, daemon=True)
    t.start()
    deadline = time.time() + 30
    while time.time() < deadline and not seen and not done.is_set():
        with ppa_search._CHILDREN_LOCK:
            seen.append(len(ppa_search._CHILDREN))
        if seen and seen[-1] == 0:
            seen.clear()
            time.sleep(0.05)
    assert seen and seen[-1] >= 1, (
        "`run_one` must put its child in the registry WHILE it runs; an "
        "unregistered child survives every stop path this module has")
    ppa_search._reap_children()
    t.join(timeout=30)


def test_reaping_empties_the_registry_and_is_idempotent():
    _spawn(2)
    ppa_search._reap_children()
    assert ppa_search._CHILDREN == set()
    ppa_search._reap_children()  # must not raise on a second call
    assert ppa_search._CHILDREN == set()


def test_reaping_nothing_is_silent_and_harmless():
    ppa_search._reap_children()
    assert ppa_search._CHILDREN == set()


def test_the_reaper_states_what_it_cannot_kill():
    """The container-side tail is real and measured. A reaper that reported a
    clean stop while `openroad` kept running would be the same false-clean this
    repo keeps removing, one layer down."""
    src = Path(ppa_search.__file__).read_text(encoding="utf-8")
    body = src[src.index("def _reap_children"):src.index("def _expand")]
    assert "container" in body
    assert "outlive" in body or "not killed" in body


def test_run_one_deregisters_its_child_when_it_finishes(tmp_path):
    """A child that is never deregistered makes the registry grow without
    bound across 50 runs."""
    design = tmp_path / "design"
    (design / "phase1" / "generated_docs").mkdir(parents=True)
    fake_runner = tmp_path / "fake_runner.py"
    fake_runner.write_text("import sys; sys.exit(0)\n")
    rec = ppa_search.run_one(design, tmp_path / "out",
                             {"util": 0.3, "die_um": "auto",
                              "spare_density": 0.02},
                             "top", fake_runner, "none", timeout_s=60)
    assert rec["rc"] == 0
    assert ppa_search._CHILDREN == set(), (
        "the registry must shrink again, or 50 configurations leave 50 dead "
        "Popen objects in it")
