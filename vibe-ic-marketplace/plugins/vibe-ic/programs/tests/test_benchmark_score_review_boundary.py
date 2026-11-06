"""Canonical scoring still requires independent review after entry guard removal."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import benchmark_dispatch as dispatch


@pytest.mark.parametrize("solve", [None, {"acceptance_policy": {"required": False}}])
def test_score_refuses_unreviewed_general_run_before_invoking_tools(tmp_path, monkeypatch, solve):
    (tmp_path / ".bench_config.json").write_text(json.dumps({
        "schema": "vibeic.benchmark.general_run.v1", "bench": "verilogeval-v2",
        "full_dataset": True,
    }))
    if solve is not None:
        (tmp_path / "solve_report.json").write_text(json.dumps(solve))

    def unexpected_tool(*args, **kwargs):
        pytest.fail("unreviewed results must not reach a scorer or tool")

    monkeypatch.setattr(dispatch, "_dispatch_format", lambda bench, run: dispatch._BENCH_FORMAT[bench])
    monkeypatch.setattr(dispatch.subprocess, "call", unexpected_tool)
    with pytest.raises(SystemExit, match="AI Review acceptance is incomplete"):
        dispatch.cmd_score("verilogeval-v2", str(tmp_path), None)
