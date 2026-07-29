#!/usr/bin/env python3
"""vibe-ic — the Phase-1 ANTI-FABRICATION grounding gate, which had no test.

`gate_cli_mutation_probe` reported it SILENT with no test file at all. Its
subject is whether every evidence literal in the emitted L1-L24 JSON is
GROUNDED in the input documents — i.e. whether Phase 1 invented anything. A gate
about fabrication that nothing exercises is the sharpest form of the problem
this sweep is about.

The property under test is the exit code, because that is what the flow reads:

    rc 0   every literal grounded, OR the gate does not apply (SKIP)
    rc 1   an ungrounded literal — something was fabricated
    rc 2   the question could not be asked
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import phase1_evidence_grounding_check as G  # noqa: E402


def test_an_ungrounded_literal_exits_non_zero(tmp_path, monkeypatch):
    """The defect the gate exists for: a value in the output that is in no
    input document."""
    monkeypatch.setattr(G, "check", lambda project, strict=False: {
        "status": "FAIL", "checked_literals": 5,
        "ungrounded": [{"doc": "datasheet.md", "missing_identifiers": ["0xDEADBEEF"],
                        "literal": "0xDEADBEEF"}]})
    assert G.main([str(tmp_path)]) == 1


def test_all_grounded_exits_zero(tmp_path, monkeypatch):
    """The other direction, or the test above is met by a gate that always
    fails — which would block every Phase-1 run."""
    monkeypatch.setattr(G, "check", lambda project, strict=False: {
        "status": "PASS", "checked_literals": 5, "ungrounded": []})
    assert G.main([str(tmp_path)]) == 0


def test_an_inapplicable_project_is_a_skip_not_a_pass(tmp_path, monkeypatch,
                                                      capsys):
    """rc 0, and it must SAY it skipped. A zero with no reason is the shape
    this repo keeps retiring: nothing was checked, reported as clean."""
    monkeypatch.setattr(G, "check", lambda project, strict=False: {
        "status": "SKIP", "reason": "no input-doc text to ground against",
        "ungrounded": []})
    assert G.main([str(tmp_path)]) == 0
    out = capsys.readouterr()
    assert "SKIP" in (out.out + out.err)


def test_an_error_is_rc_2_not_a_verdict(tmp_path, monkeypatch):
    """"I could not look" must never share an exit code with "I looked and it
    was clean"."""
    def boom(project, strict=False):
        raise ValueError("unparsable layer JSON")
    monkeypatch.setattr(G, "check", boom)
    assert G.main([str(tmp_path)]) == 2
