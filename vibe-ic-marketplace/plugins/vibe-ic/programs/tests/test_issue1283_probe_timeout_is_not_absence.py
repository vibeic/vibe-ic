#!/usr/bin/env python3
"""A probe that never answered must not be recorded as "not there" (#1283).

THE PAIRED GUARD IS THE POINT OF THIS FILE. It would be trivial to make the
container probes stop skipping under load by having them return "present" and
letting the test fail later, or by dropping the guard entirely. Both are worse
than the defect. So every assertion here comes in two halves:

    the probe TIMED OUT      -> UNCHECKABLE, and NOT a claim about the image
    the image is REALLY gone -> ABSENT, and the test still skips, as before

If a future change makes the probe optimistic, `test_a_clean_non_zero_exit_is
_still_absence` and `test_absent_still_skips` fail. If a change re-collapses
the two, `test_a_timeout_is_not_absence` fails.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import eda_container_probe as ecp  # noqa: E402


class _Completed:
    def __init__(self, rc, stdout="", stderr=""):
        self.returncode = rc
        self.stdout = stdout
        self.stderr = stderr


def _patch(monkeypatch, behaviour):
    monkeypatch.setattr(ecp.shutil, "which", lambda _: "/usr/bin/docker")
    monkeypatch.setattr(ecp.subprocess, "run", behaviour)


# ---------------------------------------------------------------------------
# The defect itself
# ---------------------------------------------------------------------------
def test_a_timeout_is_not_absence(monkeypatch):
    """The exact shape that was bitten: TimeoutExpired must NOT read as absent."""
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=120)

    _patch(monkeypatch, boom)
    p = ecp.image_available("ghcr.io/vibeic/vibeic-eda:0.2.89")
    assert p.state == ecp.UNCHECKABLE, p
    assert not p.ok
    # and it must SAY so — the old reason string claimed the image was absent
    assert "did not answer" in p.detail
    assert "0.2.89" not in p.detail or "not able to determine" in p.detail


def test_an_oserror_is_not_absence(monkeypatch):
    def boom(*a, **k):
        raise OSError("fork failed")

    _patch(monkeypatch, boom)
    assert ecp.image_available("x").state == ecp.UNCHECKABLE


# ---------------------------------------------------------------------------
# PAIRED GUARD: absence must still be absence, and must still skip
# ---------------------------------------------------------------------------
def test_a_clean_non_zero_exit_is_still_absence(monkeypatch):
    """docker looked and did not find it. That IS an answer — keep skipping."""
    _patch(monkeypatch, lambda *a, **k: _Completed(1, stderr="Error: No such image: x"))
    p = ecp.image_available("x")
    assert p.state == ecp.ABSENT, p
    assert "No such image" in p.detail


def test_a_zero_exit_is_present(monkeypatch):
    _patch(monkeypatch, lambda *a, **k: _Completed(0, stdout="[]"))
    assert ecp.image_available("x").ok


def test_absent_still_skips(monkeypatch):
    """The guard must not become decorative: ABSENT still stops the test."""
    _patch(monkeypatch, lambda *a, **k: _Completed(1, stderr="No such image"))
    with pytest.raises(pytest.skip.Exception) as exc:
        ecp.require(ecp.image_available("x"), "the image")
    assert "not available" in str(exc.value)


def test_missing_docker_is_absence_not_uncheckable(monkeypatch):
    """No docker at all is a real answer, not a probe failure."""
    monkeypatch.setattr(ecp.shutil, "which", lambda _: None)
    p = ecp.image_available("x")
    assert p.state == ecp.ABSENT
    assert "not installed" in p.detail


# ---------------------------------------------------------------------------
# The routing: NOT CHECKED by default, FAILURE when verification is required
# ---------------------------------------------------------------------------
def test_uncheckable_skips_by_default_but_says_it_is_not_a_pass(monkeypatch):
    monkeypatch.delenv(ecp.REQUIRE_ENV, raising=False)
    with pytest.raises(pytest.skip.Exception) as exc:
        ecp.require(ecp.Probe(ecp.UNCHECKABLE, "docker did not answer"), "the image")
    assert "NOT CHECKED" in str(exc.value)
    assert "NOT a pass" in str(exc.value)


def test_uncheckable_fails_when_verification_is_required(monkeypatch):
    """A run that means to prove real EDA behaviour cannot be satisfied by a
    daemon that was too busy to reply."""
    monkeypatch.setenv(ecp.REQUIRE_ENV, "1")
    with pytest.raises(pytest.fail.Exception) as exc:
        ecp.require(ecp.Probe(ecp.UNCHECKABLE, "docker did not answer"), "the image")
    assert "NOT CHECKED" in str(exc.value)


def test_present_does_not_stop_the_test(monkeypatch):
    ecp.require(ecp.Probe(ecp.PRESENT, ""), "the image")  # returns normally


# ---------------------------------------------------------------------------
# The budget, and the container variants
# ---------------------------------------------------------------------------
def test_the_local_probe_budget_outlasts_contention():
    """30s was the bound that lost the race; this test pins the reason.

    `docker image inspect` never touches a registry, so a large bound cannot
    mask a slow network — it only survives a serialised daemon.
    """
    assert ecp.PROBE_TIMEOUT_S >= 120


def test_a_stopped_container_is_absent_not_present(monkeypatch):
    """`docker inspect` resolves a stopped container fine; Running decides."""
    _patch(monkeypatch, lambda *a, **k: _Completed(0, stdout="false"))
    p = ecp.container_running("vibeic-eda")
    assert p.state == ecp.ABSENT
    assert "not running" in p.detail


def test_a_running_container_is_present(monkeypatch):
    _patch(monkeypatch, lambda *a, **k: _Completed(0, stdout="true"))
    assert ecp.container_running("vibeic-eda").ok


def test_container_probe_timeout_is_uncheckable(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="docker", timeout=120)

    _patch(monkeypatch, boom)
    assert ecp.container_running("vibeic-eda").state == ecp.UNCHECKABLE
    assert ecp.container_execable("vibeic-eda").state == ecp.UNCHECKABLE
