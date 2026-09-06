"""A lesson may never justify itself with what the ORACLE did.

The lessons digest is rendered into every blind run and the backup task calls
applying it MANDATORY. So a digest entry is not advice — it is an instruction a
blind author is required to follow, and it must therefore obey the same rule the
author does: `blind_instructions_shape_c.md` Section 4-E, "Apply a matched
convention ONLY *unless the spec states otherwise* — an explicit prompt
requirement ALWAYS wins, and a lesson NEVER overrides one."

MEASURED, on a full VerilogEval-v2 run. The section "hysteresis level-controller"
told authors that a prompt of that class states the literal rule RISE->open, to
"Do NOT implement that literal reading", and to emit the OPPOSITE — justifying
itself with `oracle-FAIL` observations. An author applied it (it is mandatory),
produced RTL contradicting its prompt's explicit sentence, and the blind review
layer caught and repaired it. Scored against the golden: the lesson-steered
candidate passed (0/2040 mismatches) and the spec-faithful repair failed
(1171/2040). The lesson was worth exactly one benchmark point, and the only way
to earn that point was to know what the hidden golden wanted.

That is benchmark-answer knowledge wearing a convention's clothes: a leak, whatever
score it buys. This test is the grammar that keeps it out.

WHAT IS AND IS NOT FORBIDDEN. Mentioning the oracle is fine and common — 52 of the
209 sections do, nearly all to warn AGAINST it ("not an oracle fit", "the SOURCE
is the prompt, never the oracle harness"), or to record how a lesson was validated
("zero-oracle blind A/B"). What is forbidden is citing an oracle OUTCOME as the
REASON a rule holds, and directing the author to override the prompt. Each pattern
below was measured to fire on exactly one section and no other.
"""
import re
from pathlib import Path

_DIGEST = (Path(__file__).resolve().parents[2] / "agents" / "ic-expert-agent.md")

# Each pattern names a way a lesson can anchor its justification in the oracle
# rather than in the prompt or a design principle.
_FORBIDDEN = {
    "cites an oracle PASS/FAIL outcome as evidence":
        r"oracle-(?:FAIL|PASS)",
    "says a reading 'failed the oracle'":
        r"fail\w*\s+the\s+oracle",
    "directs the author to override the prompt's literal statement":
        r"(?:do\s*not\s+implement\s+that\s+literal"
        r"|OPPOSITE\s+of\s+the\s+literal"
        r"|outrank\w*\s+a\s+relative)",
    "asserts what the oracle expects":
        r"oracle\s+(?:expects|requires|wants)",
}


def _sections():
    txt = _DIGEST.read_text(errors="replace")
    return [("### Skill: " + s.splitlines()[0], s)
            for s in re.split(r"(?m)^### Skill: ", txt)[1:]]


def test_the_digest_actually_parses_into_sections():
    """Guard the guard: a parse that silently yields nothing would make every
    assertion below vacuously true."""
    secs = _sections()
    assert len(secs) > 150, f"only {len(secs)} sections parsed — re-anchor this test"


def test_no_lesson_justifies_itself_with_oracle_behaviour():
    offenders = []
    for title, body in _sections():
        for why, pat in _FORBIDDEN.items():
            if re.search(pat, body, re.I):
                offenders.append(f"{title.strip()[:80]} — {why}")
    assert not offenders, (
        "a lessons-digest entry justifies itself with oracle behaviour instead of "
        "the prompt or a design principle:\n  " + "\n  ".join(offenders))


def test_every_forbidden_pattern_is_individually_live():
    """Negative control on the PATTERNS. A pattern that matches nothing anywhere
    could be silently broken (a bad escape, a renamed term) and this file would
    still pass. Each must demonstrably match its own intended shape."""
    samples = {
        "cites an oracle PASS/FAIL outcome as evidence": "observed oracle-FAIL on half the vectors",
        "says a reading 'failed the oracle'": "three sweeps all failed the oracle while passing their own TBs",
        "directs the author to override the prompt's literal statement": "Do NOT implement that literal reading",
        "asserts what the oracle expects": "the oracle expects the inverted polarity",
    }
    for why, pat in _FORBIDDEN.items():
        assert re.search(pat, samples[why], re.I), f"pattern for {why!r} matches nothing"


def test_legitimate_oracle_mentions_are_not_flagged():
    """Zero false positives is the whole point: the digest mentions the oracle
    constantly, and almost always to warn against it. These real phrasings taken
    from surviving sections must all stay clean."""
    legitimate = [
        "matching it is spec-faithful, not oracle-fitting.",
        "the SOURCE is the prompt, never the oracle harness.",
        "is a faithful-transcription rule, not a hidden-oracle peek.",
        "copy-then-invert is the defining algorithm; it is the spec, not an oracle fit.",
        "Tier 1 — VERIFIED blind-absorbable (zero-oracle blind A/B at the real CVDP oracle)",
        "the clamp-vs-wrap choice is determined by the spec's overflow language, not by any oracle",
        "structural tells in the spec, not oracle data.",
    ]
    for text in legitimate:
        for why, pat in _FORBIDDEN.items():
            assert not re.search(pat, text, re.I), (
                f"false positive: {why!r} flagged a legitimate mention: {text!r}")
