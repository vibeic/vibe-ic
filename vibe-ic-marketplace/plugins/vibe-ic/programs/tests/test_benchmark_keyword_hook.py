"""Regression tests for `hooks/benchmark-keyword-skill-reminder.sh`.

Per user 2026-05-29: "let benchmark, VerilogEval and CVDP be the
trigger keywords". The hook is an UserPromptSubmit hook that fires when
any benchmark keyword appears in the user's prompt and injects a
<system-reminder> directing Claude to load
`vibe-ic:open-benchmark-methodology` + use `/vibe-ic-benchmark`.

These tests run the actual bash script through a subprocess to lock
the trigger / non-trigger boundary.
"""
import subprocess
from pathlib import Path

HOOK = (Path(__file__).resolve().parents[2]
         / "hooks" / "benchmark-keyword-skill-reminder.sh")


def _run_with_prompt(prompt: str) -> str:
    """Send a JSON envelope on stdin; return the hook's stdout."""
    envelope = f'{{"prompt": "{prompt}"}}\n'
    proc = subprocess.run(
        ["bash", str(HOOK)],
        input=envelope, capture_output=True, text=True, timeout=5,
    )
    return proc.stdout


def _triggers(prompt: str) -> bool:
    return "Benchmark keyword detected" in _run_with_prompt(prompt)


class TestTriggerKeywords:
    def test_bare_benchmark_triggers(self):
        assert _triggers("run this benchmark")

    def test_verilogeval_triggers(self):
        assert _triggers("score VerilogEval")

    def test_verilogeval_v2_triggers(self):
        assert _triggers("rerun VerilogEval-v2")

    def test_verilogeval_human_triggers(self):
        assert _triggers("VerilogEval-Human is failing")

    def test_cvdp_triggers(self):
        assert _triggers("run CVDP benchmark")

    def test_cvdp_lowercase_triggers(self):
        assert _triggers("score cvdp")

    def test_rtllm_triggers(self):
        assert _triggers("rerun RTLLM")

    def test_pyhdl_eval_triggers(self):
        assert _triggers("PyHDL-Eval setup")

    def test_rtl_repo_triggers(self):
        assert _triggers("RTL-Repo dataset")

    def test_metrex_triggers(self):
        assert _triggers("score MetRex")


class TestNonTriggerInputs:
    def test_plain_greeting_does_not_trigger(self):
        assert not _triggers("just say hi")

    def test_code_review_request_does_not_trigger(self):
        assert not _triggers("please review my RTL")

    def test_design_question_does_not_trigger(self):
        assert not _triggers("how do I close timing")


class TestReminderShape:
    """The injected reminder must contain the canonical pointers."""

    def test_includes_open_benchmark_methodology_skill(self):
        out = _run_with_prompt("run benchmark")
        assert "vibe-ic:open-benchmark-methodology" in out

    def test_includes_runner_front_door(self):
        out = _run_with_prompt("CVDP")
        assert "/vibe-ic-benchmark" in out

    def test_includes_decision_matrix_section(self):
        out = _run_with_prompt("benchmark")
        assert "decision matrix" in out

    def test_includes_anti_handroll_directive(self):
        # Doctrine guardrail: programs-first, NOT a hand-rolled harness.
        out = _run_with_prompt("benchmark")
        assert "hand-rolled" in out
        assert "DO NOT" in out

    def test_no_reminder_when_no_keyword(self):
        out = _run_with_prompt("plain text")
        assert "Benchmark keyword detected" not in out
        assert "/vibe-ic-benchmark" not in out
