#!/usr/bin/env python3
"""#365 third ask — one provenance entry per EDA invocation, with a REAL
duration.

The ledger previously held a handful of BACK-FILLED entries per flow, written
for artefacts found on disk with a `duration_ms` nobody measured. This records
one entry per SUPERVISED tool run and measures it.

SCOPE is the runner's own signal: `_docker_exec(marker=...)` is how this file
already distinguishes an open-ended TOOL RUN from a bounded shell probe
(`command -v`, `ls`, `ps`). Logging the probes as well would bury the tool runs
in noise — the opposite of what the issue asks for.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

_RUNNER = _PROGRAMS / "phase3_one_shot_runner.py"




def _source_span(needle: str, end: str | None = None) -> str:
    """Read a span of the runner's SOURCE, and REFUSE BY NAME when the spelling
    is not there any more.

    `str.index` raises a bare `ValueError: substring not found`. That is not a
    detail: it is how vibe-ic#2114 was reported. This module's wiring pin died
    on `src.index("res = _wd.run_supervised(")` after v1.18.43 moved phase3's
    supervised dispatch onto `_docker_watchdog.run_docker_supervised`, and the
    red said nothing about the property the test exists to guard and nothing
    about WHICH spelling had moved -- it failed before it could measure
    anything. A source probe that has lost its needle must say which needle,
    in which file, so the next reader can re-aim it instead of re-deriving it.
    """
    src = _RUNNER.read_text()
    i = src.find(needle)
    assert i >= 0, (
        "%s no longer contains the spelling %r, so this source probe is "
        "pinned to a contract that has MOVED. Re-aim it at the code that "
        "carries the property now; do not delete it, and do not read this as "
        "a statement about the property itself -- it is a statement about "
        "this probe." % (_RUNNER.name, needle))
    if end is None:
        return src[i:]
    j = src.find(end, i + 1)
    assert j >= 0, (
        "%s contains %r but no %r after it, so this source probe cannot "
        "bound its span. Re-aim it." % (_RUNNER.name, needle, end))
    return src[i:j]






















def test_365_the_sink_is_pointed_at_the_project_by_the_runner():
    _source_span("set_invocation_provenance_sink(project)")


def test_365_bounded_probes_are_not_logged():
    """`_docker_exec_raw` handles the short probes; it must NOT log, or the
    ledger fills with `command -v` / `ls` / `ps` and the tool runs are lost
    in it."""
    body = _source_span("def _docker_exec_raw(", end="\ndef ")
    assert "_log_invocation(" not in body, (
        "`_docker_exec_raw` logs: the ledger will fill with `command -v` / "
        "`ls` / `ps` and the tool runs will be lost in it")
