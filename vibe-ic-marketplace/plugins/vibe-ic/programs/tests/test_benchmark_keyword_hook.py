"""Regression tests for `hooks/benchmark-keyword-skill-reminder.sh`.

Per user directive 2026-06-03: "benchmark hook should be 'vibe-ic benchmark'
or 'vibeic benchmark' or 'vibe ic benchmark', …". The hook is an
UserPromptSubmit hook that injects a <system-reminder> directing Claude to
load `vibe-ic:open-benchmark-methodology` + use `/vibe-ic-benchmark`.

It now fires ONLY on the explicit project-benchmark phrase / command in any
spelling — NOT on a bare "benchmark", a benchmark NAME alone
(VerilogEval / CVDP / RTLLM / …), "benchmark" + a run/score verb, or any
compound path (benchmark / benchmark_phase1 / benchmark_external).

These tests run the actual bash script through a subprocess to lock the
trigger / non-trigger boundary.
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
    # The reminder always carries the methodology-skill pointer; use it as the
    # stable fire signal (independent of the header wording).
    return "vibe-ic:open-benchmark-methodology" in _run_with_prompt(prompt)


class TestTriggerPhrase:
    """ONLY the explicit 'vibe[ _-]ic … benchmark' phrase / command fires."""

    def test_hyphen_phrase_triggers(self):
        assert _triggers("vibe-ic benchmark VerilogEval")

    def test_squashed_phrase_triggers(self):
        assert _triggers("vibeic benchmark cvdp")

    def test_spaced_phrase_triggers(self):
        assert _triggers("please run the vibe ic benchmark")

    def test_underscore_phrase_triggers(self):
        assert _triggers("vibe_ic benchmark rtllm")

    def test_slash_command_triggers(self):
        assert _triggers("/vibe-ic-benchmark --list")

    def test_slash_command_with_args_triggers(self):
        assert _triggers("run vibe-ic-benchmark RTLLM --score")

    def test_case_insensitive_triggers(self):
        assert _triggers("Vibe-IC Benchmark VerilogEval-v2")


class TestBenchmarkNamesAloneDoNotTrigger:
    """Bare benchmark names / bare 'benchmark' no longer fire — only the
    explicit project phrase does (user directive 2026-06-03)."""

    def test_bare_benchmark_with_verb_does_not_trigger(self):
        assert not _triggers("run this benchmark")
        assert not _triggers("please run the benchmark suite now")
        assert not _triggers("score the benchmark")

    def test_verilogeval_alone_does_not_trigger(self):
        assert not _triggers("score VerilogEval")
        assert not _triggers("rerun VerilogEval-v2")
        assert not _triggers("VerilogEval-Human is failing")
        assert not _triggers("how did VerilogEval do")

    def test_cvdp_alone_does_not_trigger(self):
        assert not _triggers("run CVDP benchmark")
        assert not _triggers("score cvdp")

    def test_rtllm_alone_does_not_trigger(self):
        assert not _triggers("rerun RTLLM")

    def test_pyhdl_rtlrepo_metrex_alone_do_not_trigger(self):
        assert not _triggers("PyHDL-Eval setup")
        assert not _triggers("RTL-Repo dataset")
        assert not _triggers("score MetRex")


class TestNonTriggerInputs:
    def test_plain_greeting_does_not_trigger(self):
        assert not _triggers("just say hi")

    def test_code_review_request_does_not_trigger(self):
        assert not _triggers("please review my RTL")

    def test_design_question_does_not_trigger(self):
        assert not _triggers("how do I close timing")

    def test_vibe_ic_without_benchmark_does_not_trigger(self):
        # mentioning the plugin without the benchmark front door must not fire
        assert not _triggers("does vibe-ic support the CVDP benchmark suite")
        assert not _triggers("the vibe-ic plugin scored well")


class TestReminderShape:
    """The injected reminder must contain the canonical pointers."""

    _P = "vibe-ic benchmark VerilogEval"

    def test_includes_open_benchmark_methodology_skill(self):
        assert "vibe-ic:open-benchmark-methodology" in _run_with_prompt(self._P)

    def test_includes_runner_front_door(self):
        assert "/vibe-ic-benchmark" in _run_with_prompt(self._P)

    def test_includes_decision_matrix_section(self):
        assert "decision matrix" in _run_with_prompt(self._P)

    def test_includes_anti_handroll_directive(self):
        out = _run_with_prompt(self._P)
        assert "hand-rolled" in out
        assert "DO NOT" in out

    def test_no_reminder_when_no_keyword(self):
        out = _run_with_prompt("plain text")
        assert "<system-reminder>" not in out
        assert "/vibe-ic-benchmark" not in out


class TestSensitivity:
    """Incidental 'benchmark' mentions, compound paths, and envelope-only
    matches must NOT fire."""

    def test_bare_benchmark_noun_does_not_trigger(self):
        assert not _triggers("remove or modify benchmark hook")
        assert not _triggers("commit the benchmark candidate doc to community")

    def test_benchmark_compound_paths_do_not_trigger(self):
        assert not _triggers("edit benchmark/score_iverilog_tb.py")
        assert not _triggers("the benchmark_phase1/espi L12 json changed")
        assert not _triggers("stage benchmark_external/interconnect manifests")
        assert not _triggers("invoke the benchmark-enhancement-capture skill")

    def test_keyword_only_in_non_prompt_envelope_field_does_not_trigger(self):
        # "vibe-ic benchmark" appears only in a tool-result field, not in prompt
        envelope = ('{"prompt": "are the 3 places synced?", '
                    '"tool_result": "vibe-ic benchmark VerilogEval ran; '
                    'benchmark_phase1 fixtures present"}\n')
        proc = subprocess.run(
            ["bash", str(HOOK)],
            input=envelope, capture_output=True, text=True, timeout=5,
        )
        assert "<system-reminder>" not in proc.stdout
