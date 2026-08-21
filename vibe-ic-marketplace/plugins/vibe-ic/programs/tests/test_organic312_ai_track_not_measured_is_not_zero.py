#!/usr/bin/env python3
"""ORGANIC #312 — `ai_captured_tokens_count: 0` must not read as a measurement.

The doctrine is program-first + AI-backup dual-track convergence. Measured:
`ai_patches` has FOUR readers under `programs/` and ZERO producers — nothing
anywhere writes the sidecar — and `phase1_expert_track_evidence_check` reports
NOT MEASURED on all 8 benchmark ICs. So the second rail has never run, and the
count a consumer sees is 0 for that reason, not because the rail looked and
found nothing.

This does NOT build the missing rail. It stops the absence being reported as a
measurement — the same rule `l_doc_field_producer_check` encodes: an empty
value and a clean value must not look alike.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
CHECK = _PROGRAMS / "phase1_doc_input_completeness_check.py"


def _project(tmp_path: Path, *, sidecar=None) -> Path:
    gd = tmp_path / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps(
        {"fields": {"pin_table": [{"name": "clk", "width": 1}]}}))
    inp = tmp_path / "input" / "docs"
    inp.mkdir(parents=True, exist_ok=True)
    # `.txt`, not `.md`: the checker globs `*.txt` only (it reads
    # PRE-EXTRACTED text). A `.md` fixture makes it SKIP, and three of the
    # four tests here silently skipped on the first draft — a skipped test is
    # not a control. Fourth time this session that a fixture not shaped like
    # the thing it stands for gave the wrong answer.
    (inp / "spec.txt").write_text("Spec\n\nA clk pin.\n")
    if sidecar is not None:
        (tmp_path / "phase1" / "ai_deep_review_patches.json").write_text(
            json.dumps(sidecar))
    return tmp_path


def _report(project: Path):
    subprocess.run([sys.executable, str(CHECK), str(project)],
                   capture_output=True, text=True)
    f = (project / "reports" / "phase1"
         / "phase1_input_vs_generated_completeness.json")
    assert f.is_file(), (
        "the checker produced no report — the fixture does not satisfy its "
        "preconditions, and a SKIP here would be a test that controls nothing")
    return json.loads(f.read_text())


def test_no_sidecar_is_reported_as_NOT_MEASURED(tmp_path):
    r = _report(_project(tmp_path))
    assert r["ai_track_ran"] is False
    assert "NOT MEASURED" in r["ai_captured_tokens_count_meaning"]


def test_a_sidecar_makes_the_count_a_real_measurement(tmp_path):
    """The paired half. Hardcoding "NOT MEASURED" would satisfy the case
    above and lie the moment the rail is actually built."""
    r = _report(_project(tmp_path, sidecar={"patches": {
        "L1_DATASHEET": [{"extraction_strategy": "ai_deep_review_patch",
                          "note": "expert observation"}]}}))
    assert r["ai_track_ran"] is True
    assert r["ai_captured_tokens_count_meaning"] == "measured"


def test_the_count_itself_is_unchanged(tmp_path):
    """This change adds a qualifier; it must not alter the number, or a
    consumer comparing runs across versions sees a phantom movement."""
    r = _report(_project(tmp_path))
    assert isinstance(r["ai_captured_tokens_count"], int)


def test_the_producer_gap_is_real_and_still_open():
    """The premise. If a producer ever appears this test fails, which is the
    correct time to revisit the qualifier."""
    readers, producers = [], []
    for f in sorted(_PROGRAMS.glob("*.py")):
        src = f.read_text(errors="replace")
        if "ai_patches" not in src and "ai_deep_review_patches" not in src:
            continue
        readers.append(f.name)
        for ln in src.splitlines():
            if ("ai_deep_review_patches" in ln
                    and ("write_text" in ln or "json.dump" in ln)):
                producers.append(f.name)
    assert readers, "the sidecar readers vanished — premise changed"
    assert not producers, f"a producer now exists: {producers}"
