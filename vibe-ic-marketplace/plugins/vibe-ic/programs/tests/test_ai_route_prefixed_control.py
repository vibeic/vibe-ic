"""Value control: Program must not run before an AI route answer."""
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import benchmark_dispatch as bd  # noqa: E402


def test_no_runner_before_ai_route(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "generic_buffer_prompt.txt").write_text(
        "Design a generic one-input output buffer named top_module.")
    calls = []
    monkeypatch.setattr(bd._RunnerBudget, "run",
                        lambda *_a: calls.append(1) or bd._ProcessOutcome(rc=1))

    bd.cmd_solve("verilogeval-human", str(dataset), str(tmp_path / "run"))
    assert calls == []
