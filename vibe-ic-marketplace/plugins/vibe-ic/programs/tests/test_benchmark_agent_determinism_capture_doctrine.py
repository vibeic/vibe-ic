"""Regression: the Benchmark Agent definition must carry the PRIME DIRECTIVE —
converge every SOLVABLE-but-flaky fail into a DETERMINISTIC program capture
(never shelve it as "pass@1 variance / noise").

WHY (owner directive 2026-06-22): "把所有可以解的都淬鍊在我們的 program 裡面 …
這是 Benchmark Agent 最重要的事情." The benchmark loop's purpose is to harden the
plugin: a problem that is solvable (golden passes + at least one blind draw passes)
but oscillates pass/fail on the same plugin version is a DETERMINISM GAP — the plugin
hasn't captured the deterministic path. That must be captured (program-first gate,
or a sharp lesson) until the pass-rate → 1, GENERAL to the class (never a per-problem
hack). This test pins the doctrine into the agent definition so it can't be dropped.

chip/problem-AGNOSTIC: asserts only on the agent-definition TEXT.
"""
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_AGENT_MD = _PROGRAMS.parent / "agents" / "benchmark-agent.md"


def _text() -> str:
    return _AGENT_MD.read_text(encoding="utf-8")


def test_agent_definition_exists():
    assert _AGENT_MD.is_file(), "benchmark-agent.md must exist"


def test_prime_directive_section_present():
    t = _text().lower()
    assert "prime directive" in t, "the PRIME DIRECTIVE section must be present"
    # it must frame the loop as converging solvable fails into the program
    assert "deterministic" in t and "capture" in t


def test_variance_is_a_capturable_gap_not_a_terminal_verdict():
    t = _text().lower()
    # the doctrine must explicitly reject "pass@1 variance" as a terminal classification
    assert "variance" in t
    assert ("determinism gap" in t or "not a terminal" in t or
            "not yet captured" in t or "capturable bug" in t), \
        "doctrine must say solvable-but-flaky variance is a determinism GAP / capturable bug, not a shelf"


def test_program_first_mechanism_and_passk_method():
    t = _text().lower()
    assert "program-first" in t or "program first" in t
    assert "gate-as-sole-emit-path" in t or "emit gate" in t or "program rule" in t
    assert "pass@k" in t, "the capture METHOD (pass@k → discriminator → distill) must be stated"
    assert "discriminator" in t


def test_convergence_target_is_pass_rate_to_one():
    t = _text().lower()
    assert "pass-rate" in t and ("→ 1" in _text() or "->1" in t or "toward 1" in t or "to ~1" in t or "to 1" in t)


def test_capture_must_be_general_not_per_problem_overfit():
    t = _text().lower()
    assert "general" in t
    assert "over-fit" in t or "overfit" in t or "problem-specific" in t, \
        "must forbid a problem-specific per-Prob hack (cheating)"


def test_shelving_variance_is_an_anti_pattern():
    t = _text().lower()
    assert "anti-pattern" in t
    # the explicit anti-pattern: shelving a solvable-but-flaky fail as variance/noise
    assert "shelv" in t or "noise" in t
