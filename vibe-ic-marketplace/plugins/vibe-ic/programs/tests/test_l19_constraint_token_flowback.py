#!/usr/bin/env python3
"""Real-artifact control for prose constraints reaching their L19 consumer.

The source document is the checked-in spm Phase-1 review fixture.  It is not
re-authored beside this test: the test drives the normal Phase-1 front door on
those exact input bytes, then reads the L19 artifact the runner actually wrote.
This is the behavioural negative control for ``l19_constraint_token_emit``;
clean ``origin/main`` runs the assertion and observes an empty token set.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from _hostpaths import require_repo


_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
_RUNNER = _PROGRAMS / "phase1_doc_one_shot_runner.py"
_REAL_INPUT = (
    "vibe-ic-marketplace/plugins/vibe-ic/programs/tests/fixtures/"
    "stage_phase1_on_pass_review/reject_spm/phase1/input_doc"
)
_EXPECTED = {
    "FP_CORE_UTIL",
    "PL_TARGET_DENSITY",
    "FP_PDN_SKIPTRIM",
    "FP_PDN_VOFFSET",
    "FP_PDN_HOFFSET",
    "MAX_FANOUT_CONSTRAINT",
    "create_clock",
    "set_units",
    "set_input_delay",
    "set_output_delay",
}


def test_real_prose_constraints_reach_l19_through_the_phase1_runner(tmp_path):
    source = require_repo(_REAL_INPUT)
    shutil.copytree(source, tmp_path / "input" / "docs")

    env = os.environ.copy()
    env["PYTHONPATH"] = ""
    completed = subprocess.run(
        [sys.executable, str(_RUNNER), str(tmp_path),
         "--ic-name", "spm", "--pdk", "gf180mcuD"],
        cwd=_PROGRAMS,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0

    l19 = json.loads((
        tmp_path / "phase1" / "generated_docs" /
        "L19_CONSTRAINTS_PDK.json"
    ).read_text(encoding="utf-8"))
    fields = l19["fields"]
    got = {
        row.get("token")
        for row in fields.get("constraint_declarations", [])
        if isinstance(row, dict)
    }

    assert got >= _EXPECTED
    assert fields.get("constraints_present") is True
    assert "Spec does not state PDK / timing constraints" not in str(
        fields.get("notes", ""))

    l8 = json.loads((
        tmp_path / "phase1" / "generated_docs" /
        "L8_TIMING_WAVEFORM.json"
    ).read_text(encoding="utf-8"))
    l9 = json.loads((
        tmp_path / "phase1" / "generated_docs" /
        "L9_INTEGRATION_SPEC.json"
    ).read_text(encoding="utf-8"))
    waveform = l8.get("clock_and_reset_waveform")
    observed = {
        "source_period_ns": next((row.get("period_ns")
                                  for row in l8.get("clocks", [])), None),
        "source_reset_polarity": next((row.get("polarity")
                                       for row in l9.get("reset_domains", [])),
                                      None),
        "release_period_ns": next((row.get("period_ns") for row in
                                   (waveform or {}).get("clocks", [])), None),
        "release_reset_polarity": next((row.get("polarity") for row in
                                        (waveform or {}).get("resets", [])),
                                       None),
    }
    assert observed == {
        "source_period_ns": 24,
        "source_reset_polarity": "active_high",
        "release_period_ns": 24,
        "release_reset_polarity": "active_high",
    }
