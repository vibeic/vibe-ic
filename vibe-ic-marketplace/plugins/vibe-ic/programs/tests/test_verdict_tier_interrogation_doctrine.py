"""The verdict-tier interrogation doctrine stays in the agent, verbatim in force.

Owner doctrine (2026-09-01, spm case): every non-PASS tier row must be
interrogated against the three legitimate justifications before a verdict is
handed over. This pin makes silently dropping the section a red, the same way
the benchmark doctrine sections are kept.
"""
from pathlib import Path

_AGENT = Path(__file__).resolve().parents[2] / "agents" / "ic-expert-agent.md"


def test_the_interrogation_section_is_present():
    text = _AGENT.read_text(encoding="utf-8")
    assert "VERDICT-TIER INTERROGATION" in text


def test_the_three_justifications_are_named():
    text = _AGENT.read_text(encoding="utf-8")
    for phrase in ("Condition genuinely absent",
                   "Capability genuinely absent",
                   "Genuinely external"):
        assert phrase in text, phrase


def test_the_could_not_ask_corollaries_survive():
    text = _AGENT.read_text(encoding="utf-8")
    assert "the question was put and the answer was no" in text
    assert "never to the failure mode of the call" in text
