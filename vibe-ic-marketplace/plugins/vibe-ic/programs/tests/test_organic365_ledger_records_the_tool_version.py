#!/usr/bin/env python3
"""ORGANIC #365 — the ledger named the tool and the duration, never the BUILD.

The anti-fabrication rule the issue quotes asks for a version per tool call.
A provenance chain that cannot say which build ran cannot attest what it
claims.

Probing per invocation would cost a container exec every time; a tool's
version does not change inside a run, so it is probed ONCE per
(container, tool). These tests pin the memoisation, the explicit
NOT-CAPTURED state, and the two things the probe must never do: recurse into
the ledger, or break the run it documents.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import phase3_one_shot_runner as P  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_cache():
    P._VERSION_CACHE.clear()
    yield
    P._VERSION_CACHE.clear()


def _rows(sink: Path):
    f = sink / "provenance.jsonl"
    return [json.loads(l) for l in f.read_text().splitlines() if l.strip()]


def test_the_version_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_docker_exec_raw",
                        lambda c, cmd, timeout=0: (0, "Yosys 0.57+123\n", ""))
    P.set_invocation_provenance_sink(tmp_path)
    try:
        P._log_invocation("cd /w && yosys -s a.ys", 0, 12, container="c1")
    finally:
        P.set_invocation_provenance_sink(None)
    r = _rows(tmp_path)[0]
    assert r["tool"] == "yosys"
    assert r["version"] == "Yosys 0.57+123"
    assert r["version_capture"] == "probed"


def test_it_is_probed_once_per_tool(tmp_path, monkeypatch):
    """Per-invocation probing would add a container exec to every tool call.
    The version cannot change inside a run."""
    calls = []

    def _probe(c, cmd, timeout=0):
        calls.append(cmd)
        return 0, "OpenROAD 1.2.3\n", ""

    monkeypatch.setattr(P, "_docker_exec_raw", _probe)
    P.set_invocation_provenance_sink(tmp_path)
    try:
        for _ in range(5):
            P._log_invocation("export PATH=/x && openroad a.tcl", 0, 1,
                              container="c1")
    finally:
        P.set_invocation_provenance_sink(None)
    assert len(_rows(tmp_path)) == 5
    assert len(calls) == 1, calls


def test_no_container_is_NOT_CAPTURED_not_a_silent_absence(tmp_path):
    """An unknown build and an unrecorded one must not look alike (#312)."""
    P.set_invocation_provenance_sink(tmp_path)
    try:
        P._log_invocation("yosys -s a.ys", 0, 3)
    finally:
        P.set_invocation_provenance_sink(None)
    r = _rows(tmp_path)[0]
    assert r["version"] is None
    assert "NOT CAPTURED" in r["version_capture"]


def test_a_login_banner_is_not_a_version(tmp_path, monkeypatch):
    """The image prints `[INFO] Final PATH variable: ...` on every login
    shell. `provenance_logger` already had to filter that; taking the first
    line here would have recorded the banner as the build."""
    monkeypatch.setattr(
        P, "_docker_exec_raw",
        lambda c, cmd, timeout=0: (
            0, "[INFO] Final PATH variable: /a:/b\nKLayout 0.29.1\n", ""))
    P.set_invocation_provenance_sink(tmp_path)
    try:
        P._log_invocation("klayout -b -r d.lydrc", 0, 4, container="c1")
    finally:
        P.set_invocation_provenance_sink(None)
    assert _rows(tmp_path)[0]["version"] == "KLayout 0.29.1"


def test_a_probe_that_raises_still_leaves_a_row(tmp_path, monkeypatch):
    """A ledger that can break the run it documents would be traded away the
    first time it did."""
    def _boom(c, cmd, timeout=0):
        raise RuntimeError("container gone")

    monkeypatch.setattr(P, "_docker_exec_raw", _boom)
    P.set_invocation_provenance_sink(tmp_path)
    try:
        P._log_invocation("yosys -s a.ys", 0, 7, container="c1")
    finally:
        P.set_invocation_provenance_sink(None)
    r = _rows(tmp_path)[0]
    assert r["tool"] == "yosys" and r["version"] is None
    assert "NOT CAPTURED" in r["version_capture"]


def test_a_probe_answering_nothing_is_NOT_CAPTURED(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "_docker_exec_raw",
                        lambda c, cmd, timeout=0: (1, "", "unknown option"))
    P.set_invocation_provenance_sink(tmp_path)
    try:
        P._log_invocation("some_future_tool run", 0, 2, container="c1")
    finally:
        P.set_invocation_provenance_sink(None)
    assert _rows(tmp_path)[0]["version"] is None


def test_the_probe_cannot_recurse_into_the_ledger():
    """It must go through `_docker_exec_raw`, which by design does not log.
    Routing it through the supervised path would make every tool call emit a
    second row for its own version probe."""
    src = (_PROGRAMS / "phase3_one_shot_runner.py").read_text()
    i = src.index("def _tool_version(")
    j = src.index("\ndef ", i + 1)
    body = src[i:j]
    assert "_docker_exec_raw(" in body
    assert "_docker_exec(" not in body.replace("_docker_exec_raw(", "")
