"""Partial diagnostic runs can never become canonical benchmark results."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import benchmark_clean_room_check as clean  # noqa: E402
import benchmark_dispatch as dispatch  # noqa: E402
from _benchmark_io_fixture import issue_io_fixture  # noqa: E402


def test_diagnostic_limit_is_marked_and_rejected_by_score(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "Prob001_prompt.txt").write_text("Design a synthetic module.\n")
    run = tmp_path / "run"
    dispatch._prepare_general_solve_run(
        "verilogeval-v2", dataset, run, "verilogeval", 1)
    issue_io_fixture(run, "verilogeval-v2", dataset)
    config = json.loads((run / ".bench_config.json").read_text())
    assert config["full_dataset"] is False
    assert clean.audit(run)[0] == "FAIL"
    with pytest.raises(SystemExit, match="full-dataset general --solve"):
        dispatch.cmd_score("verilogeval-v2", str(run), str(dataset))
