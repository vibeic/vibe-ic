#!/usr/bin/env python3
"""ORGANIC #412 — the gate found transcripts recursively and `.sby` only at
the top level, so it reported "nothing claims a proof" for evidence it had
already located.

MEASURED on the published `spm/v1.5.58_ihp-sg13g2` cell: `.sby`, `.sby.log`
and `results.json` all present under `formal/campaign_v1558/`, and the gate
said `NO_RESULTS: formal/results.json absent — nothing claims a proof`. A
false negative on genuine evidence, produced by one function searching two
ways.

REGRESSION SWEEP before shipping: 14 cells carrying a `formal/` directory,
old vs new verdict — 0 changed. The only cell whose OUTPUT changes is the one
with nested evidence, and there the verdict stays FAIL while the FINDING goes
from false ("nothing claims a proof") to true (the archived copies' internal
references do not resolve from the archive location).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
import formal_proof_evidence_check as F  # noqa: E402


def _formal(tmp_path: Path) -> Path:
    d = tmp_path / "phase2" / "stage1" / "formal"
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_a_nested_results_json_is_found(tmp_path):
    d = _formal(tmp_path)
    (d / "campaign_x").mkdir()
    (d / "campaign_x" / "results.json").write_text('{"proved": true}')
    assert F._first_results_json(d).is_file()
    assert F._first_results_json(d).parent.name == "campaign_x"


def test_a_top_level_results_json_still_wins(tmp_path):
    """The paired half: the canonical location must not be displaced by a
    nested copy, or a cell with both starts reading the wrong one."""
    d = _formal(tmp_path)
    (d / "results.json").write_text('{"top": true}')
    (d / "campaign_x").mkdir()
    (d / "campaign_x" / "results.json").write_text('{"nested": true}')
    assert F._first_results_json(d) == d / "results.json"


def test_absent_everywhere_still_reports_the_canonical_path(tmp_path):
    """The message must name `formal/results.json`, not a path that never
    existed — a reader is being told where to put one."""
    d = _formal(tmp_path)
    assert F._first_results_json(d) == d / "results.json"
    assert not F._first_results_json(d).exists()


def test_a_nested_sby_is_found(tmp_path):
    d = _formal(tmp_path)
    (d / "campaign_x").mkdir()
    (d / "campaign_x" / "proof.sby").write_text("[options]\nmode prove\n")
    names = [f.name for f in F._authored_sby_files(d)]
    assert names == ["proof.sby"]


def test_symbiyosys_own_workdir_copy_is_not_counted(tmp_path):
    """SymbiYosys writes its own `config.sby` into each task workdir. A bare
    `rglob("*.sby")` would count the tool's generated artefact as a second
    authored proof — one such file is tracked in this repo today."""
    d = _formal(tmp_path)
    (d / "authored.sby").write_text("[options]\n")
    wd = d / "authored" / "task"
    wd.mkdir(parents=True)
    (wd / "config.sby").write_text("[options]\n")
    (wd / "status").write_text("DONE\n")
    names = [f.name for f in F._authored_sby_files(d)]
    assert names == ["authored.sby"], names


def test_a_config_sby_that_is_NOT_in_a_workdir_still_counts(tmp_path):
    """The paired half. The skip is structural — `config.sby` beside a
    `status`/`logfile.txt` — not a name ban, so a project that legitimately
    names its authored task `config.sby` is not silently ignored."""
    d = _formal(tmp_path)
    (d / "config.sby").write_text("[options]\nmode prove\n")
    assert [f.name for f in F._authored_sby_files(d)] == ["config.sby"]


def test_the_real_nested_cell_no_longer_reports_no_results():
    """End-to-end on the artefact that filed the issue."""
    cell = (_PROGRAMS.parents[3] / "benchmark-data" / "ic" / "spm"
            / "v1.5.58_ihp-sg13g2")
    if not (cell / "phase2/stage1/formal").is_dir():
        pytest.skip("published cell not present")
    rep = F.audit(cell)
    blob = json.dumps(rep)
    assert "NO_RESULTS" not in blob, rep["findings"]
    assert rep.get("sby_log", "").endswith(".sby.log")
