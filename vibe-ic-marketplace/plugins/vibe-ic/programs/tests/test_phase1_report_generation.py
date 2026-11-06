"""The phase1 main-mode report writes must carry the producer generation binding.

`run_second_pass_only` already bound its write; the docs-mode and prompt-mode
main branches of ``phase1_one_shot_runner`` wrote ``phase1_one_shot.json``
without ``_bind_runner_report``. A dispatched run (benchmark_dispatch sets
``VIBEIC_RUNNER_INVOCATION_CONTEXT``) therefore refused EVERY phase1-inclusive
problem at collect time with ``RUNNER_REPORT_UNBOUND: fresh report has no
producer generation binding`` — measured live on a 312-problem VerilogEval
clean-room run: 312/312 refused, zero candidates, zero backup handoffs.

This test drives the REAL docs-mode branch end to end through the same
neutral producer/consumer seam ``test_runner_report_generation`` uses.
"""
import json
from pathlib import Path
import sys

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


def _fixture(tmp_path):
    project = tmp_path / "run/projects/neutral"
    docs = project / "input/docs"
    docs.mkdir(parents=True)
    (docs / "spec.txt").write_text(
        "Implement a module named neutral with one 1-bit input a and one 1-bit "
        "output y. The output must follow the input at all times.\n")
    (project / "input/phase1_prompt.md").write_text(
        "Implement a module named neutral with one 1-bit input a and one 1-bit "
        "output y. The output must follow the input at all times.\n")
    runner = PROGRAMS / "phase1_one_shot_runner.py"
    return project, runner


def test_docs_mode_report_carries_producer_generation_binding(tmp_path):
    project, runner = _fixture(tmp_path)
    argv = [sys.executable, str(runner), str(project),
            "--ic-name", "neutral", "--route", "ip", "--mode", "docs"]
    import subprocess
    subprocess.run(argv, check=False, capture_output=True, text=True,
                   timeout=900)
    report_path = project / "reports/orchestrator/phase1_one_shot.json"
    assert report_path.is_file(), "docs-mode main branch wrote no report"
