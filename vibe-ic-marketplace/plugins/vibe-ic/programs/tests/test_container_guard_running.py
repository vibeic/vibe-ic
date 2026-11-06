#!/usr/bin/env python3
"""`container_usable` must mean RUNNING the pinned bytes, not merely BUILT from them.

`_container_guard`'s own header argues that "running is not usable": a bare
shared name answers True for whatever container reached it first, so presence
was never proof. The converse went unimplemented. `container_matches_pin` reads
the IMAGE a container was created from, and docker answers that for a STOPPED
container exactly as it does for a live one — so a container holding the pinned
bytes and not running satisfied the guard, while `container_usable` promises in
its first line to be True only when the container "PROVABLY runs the pinned
image".

MEASURED 2026-09-10 on 8HD-8, clean main `c07ba9ef75`: with the pinned
container stopped and its bytes still on the machine, the guard admitted the
two live-path tests of test_lec_include_hub_aggregator, `docker exec` returned
nothing, and both FAILED on an empty string. A stopped runtime is the absent
runtime; it owes a skip, and it was producing a red.

These controls are HERMETIC ON PURPOSE. The condition they pin — bytes match,
container not running — is a two-container state that a host may or may not be
able to stage, and the repo's own falsifier runs pytest INSIDE the pinned image
where there is no docker client at all. Faking the two readings the predicate
consults keeps the control runnable everywhere, and it sits directly behind the
mechanism: it fails on the implementation that omits the running check.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _container_guard as _cg  # noqa: E402


class _Done:
    def __init__(self, rc: int, out: str):
        self.returncode, self.stdout, self.stderr = rc, out, ""


def _stub(monkeypatch, *, running: str, rc: int = 0):
    """Bytes MATCH; docker reports `.State.Running` as `running`."""
    monkeypatch.setattr(_cg.shutil, "which", lambda _n: "/usr/bin/docker")
    monkeypatch.setattr(_cg._pin, "default_container_name",
                        lambda *_a, **_k: "vibeic-eda-deadbeef")
    monkeypatch.setattr(_cg.subprocess, "run",
                        lambda *_a, **_k: _Done(rc, running))


def test_stopped_container_with_the_pinned_bytes_is_not_usable(monkeypatch):
    """THE DEFECT. Matching bytes plus `Running=false` must be False."""
    _stub(monkeypatch, running="false\n")
    assert _cg.container_usable() is False


def test_running_container_with_the_pinned_bytes_is_usable(monkeypatch):
    """THE OTHER DIRECTION — the guard must not simply refuse everything.

    A predicate that answers False for every input passes the test above
    vacuously, so the admitting case is pinned beside it.
    """
    _stub(monkeypatch, running="true\n")
    assert _cg.container_usable() is True


def test_an_unreadable_running_state_is_not_usable(monkeypatch):
    """`docker inspect` failing is NOT a claim that the container runs."""
    _stub(monkeypatch, running="", rc=1)
    assert _cg.container_usable() is False


def test_a_docker_that_cannot_be_run_is_not_usable(monkeypatch):
    """An OSError from the probe is not-usable, never usable."""
    _stub(monkeypatch, running="true\n")

    def _boom(*_a, **_k):
        raise OSError("no docker here")

    monkeypatch.setattr(_cg.subprocess, "run", _boom)
    assert _cg.container_usable() is False
