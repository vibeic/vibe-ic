"""The general solve verb owns its clean-room envelope."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import benchmark_dispatch as dispatch  # noqa: E402


def test_full_solve_initialization_is_fresh_and_not_reusable(tmp_path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    run = tmp_path / "run"
    dispatch._prepare_general_solve_run(
        "verilogeval-v2", dataset, run, "verilogeval", 0)
    assert (run / "transcripts").is_dir()
    assert (run / ".bench_config.json").is_file()
    with pytest.raises(SystemExit, match="empty fresh run directory"):
        dispatch._prepare_general_solve_run(
            "verilogeval-v2", dataset, run, "verilogeval", 0)
