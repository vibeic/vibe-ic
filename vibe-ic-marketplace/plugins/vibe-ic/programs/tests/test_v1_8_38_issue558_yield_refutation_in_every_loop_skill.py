#!/usr/bin/env python3
"""vibe-ic#558 — the instruction was everywhere, the fact that refutes the
belief was not.

A dispatched benchmark agent ended its turn on a still-running Phase-3 flow,
saying it would "yield until the harness re-invokes me when Phase 3 exits".
Nothing re-invoked it: `claude -p` is one-shot. The flow ran on with no one to
write its result.

"Keep your turn alive" was present in the skill that agent loaded. It reads as
a preference about style, and it loses to a specific, plausible-sounding model
of the runtime. What beats a wrong model is the FACT that contradicts it, and
that sentence lived only in skills the failing role does not load.

So each of the five skills a long-running role can load must carry BOTH: the
instruction, and the three impossible beliefs named one by one — the agent
listed exactly these three as its justification.

`phase1-coverage-loop` had NEITHER, and it is a loop skill: the shape most
likely to invite "I'll pick it up next round". That was the urgent half.

Enforced through the existing `skill_doc_section_present_check`, which is
case- and blockquote-insensitive, rather than a bespoke grep — a plain
`grep -rl` without `-i` reports 2 of these 5 files while the same search with
`-i` reports all 5, and that discrepancy is exactly how a "captured" lesson
gets reported as missing or present at random.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parents[2]
_PROG = _PLUGIN / "programs" / "skill_doc_section_present_check.py"

#: Every skill a long-running role loads. Each must carry the instruction AND
#: the refutation; the whole point of #558 is that having one is not enough.
_SKILLS = [
    "benchmark-enhancement-capture",
    "open-benchmark-methodology",
    "field-agent-loop",
    "phase1-coverage-loop",
    "core-agent-loop",
]

#: The instruction, and the three beliefs it must name as impossible.
_MARKERS = [
    "turn alive to completion",
    "re-invokes",
    "still alive",
    "notifies the DISPATCHER",
]


def _doc(skill: str) -> Path:
    return _PLUGIN / "skills" / skill / "SKILL.md"


@pytest.mark.parametrize("skill", _SKILLS)
def test_the_instruction_and_its_refutation_are_both_present(skill):
    doc = _doc(skill)
    if not doc.is_file():
        pytest.skip(f"{skill}/SKILL.md is not in this checkout")
    args = [sys.executable, str(_PROG), "--doc", str(doc)]
    for m in _MARKERS:
        args += ["--marker", m]
    cp = subprocess.run(args, capture_output=True, text=True)
    assert cp.returncode == 0, f"{skill}: {cp.stdout}\n{cp.stderr}"


def test_the_guard_fails_when_the_refutation_is_stripped(tmp_path):
    """A guard that cannot fail is not a guard.

    The instruction alone must NOT satisfy it — that state is precisely what
    #558 describes, and it is what shipped.
    """
    only_the_rule = tmp_path / "SKILL.md"
    only_the_rule.write_text(
        "# skill\n\n- **Keep your turn alive to completion.** Run the long "
        "tool through the BLOCKING call.\n")
    args = [sys.executable, str(_PROG), "--doc", str(only_the_rule)]
    for m in _MARKERS:
        args += ["--marker", m]
    cp = subprocess.run(args, capture_output=True, text=True)
    assert cp.returncode == 1, (
        "a skill carrying the instruction but none of the three impossible "
        "beliefs passed — that is the exact state that shipped in #558")


@pytest.mark.parametrize("skill", _SKILLS)
def test_all_three_beliefs_are_named_not_just_one(skill):
    """Naming one belief leaves the other two available.

    The agent in #558 gave all three as justification: the harness re-invoking
    it, an armed waiter, and a monitor firing. A text that refutes only the
    first still leaves a route to the same outcome.
    """
    doc = _doc(skill)
    if not doc.is_file():
        pytest.skip(f"{skill}/SKILL.md is not in this checkout")
    txt = doc.read_text().lower()
    for belief, phrase in (("harness re-invokes", "re-invokes"),
                           ("armed waiter", "still alive"),
                           ("monitor fires", "notifies the dispatcher")):
        assert phrase in txt, f"{skill} does not refute '{belief}'"
