#!/usr/bin/env python3
"""vibe-ic — the Phase-1 SUFFICIENCY gate of the dual-track convergence, untested.

`gate_cli_mutation_probe` reported it SILENT with no test file. It decides
whether the converged L1-L24 JSON carries enough to proceed, and the flow reads
its exit code:

    rc 0   sufficient, OR insufficient but not asked to enforce
    rc 1   --strict AND required facts are missing
    rc 2   the layers file is not there

The `--strict` split is the interesting part and is why this needs pinning in
both directions: without it, a missing required fact is DISCLOSED and does not
block; with it, it blocks. A test of only one half would let the other invert
unnoticed.

Contract read from the source before writing, not guessed: `main()` reads
exactly one key off the report, `missing_required`.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase1_sufficiency_check as S  # noqa: E402


def _layers(tmp_path):
    p = tmp_path / "layers.json"
    p.write_text('{"L1": {}, "L2": {}}')
    return p


def _rep(missing):
    """The report shape `main()` actually consumes.

    Seven keys, read off the source rather than invented: `main()` touches only
    `missing_required`, but it prints through `_fmt()` first, and `_fmt` reads
    the other six. A stub carrying one key raises KeyError inside the formatter
    and the test fails for a reason that has nothing to do with the gate.
    """
    return {"missing_required": missing, "missing_conditional": [],
            "questions_for_user": [], "layers_seen": ["L1", "L2"],
            "port_count": 4, "sequential": True,
            "verdict": "INSUFFICIENT" if missing else "SUFFICIENT"}


def test_strict_blocks_when_a_required_fact_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "check", lambda path, doc_text="", project=None: _rep([{"fact": "supply_voltage", "question": "V?"}]))
    assert S.main([str(_layers(tmp_path)), "--strict"]) == 1


def test_without_strict_the_same_gap_is_disclosed_not_blocked(tmp_path,
                                                              monkeypatch):
    """The other half of the split. If this inverted, every Phase-1 run would
    start blocking on an incomplete dialogue — which is the normal state early
    in one."""
    monkeypatch.setattr(S, "check", lambda path, doc_text="", project=None: _rep([{"fact": "supply_voltage", "question": "V?"}]))
    assert S.main([str(_layers(tmp_path))]) == 0


def test_strict_passes_when_nothing_is_missing(tmp_path, monkeypatch):
    """…or the first test is met by a gate that always blocks under --strict."""
    monkeypatch.setattr(S, "check", lambda path, doc_text="", project=None: _rep([]))
    assert S.main([str(_layers(tmp_path)), "--strict"]) == 0


def test_a_missing_layers_file_is_rc_2(tmp_path):
    """"I could not look" never shares an exit code with "I looked"."""
    assert S.main([str(tmp_path / "nope.json")]) == 2
