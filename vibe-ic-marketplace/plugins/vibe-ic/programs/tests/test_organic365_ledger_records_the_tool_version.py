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
