"""v0.3.4 — ORGANIC #501 (LOW, Bucket B): synthetic-fixture-vs-real-input
gap, 2nd recurrence. A #491 round-2 fix rebuilt the table SHAPE
(dual-table / borderless / column order) but its fixture used English
headers, while the real document's failure axis was VOCABULARY (CJK +
a multi-word `Port group` group header). The 8/8-green self-tests never
exercised the real axis and the reopen repro survived verbatim.

This is a SKILL-prose-only fix. These source pins assert the doctrine
landed in BOTH owned files:

  * skills/core-agent-loop/SKILL.md — round-2+ reopened-doc-extraction
    doctrine: the three ordered steps (run extractor on the REAL
    artifact FIRST → fix that axis → fixture embeds the real
    discriminating line VERBATIM), the verbatim-fixture obligation, and
    the #499 Bucket-A cross-reference in the why_not_bucket_a residual.
  * agents/ic-expert-agent.md — the matching lessons section with the
    same three-step / verbatim obligation and the #499 cross-ref.

Acceptance (issue ## 驗收): `grep -n "verbatim" SKILL.md` must exit 0
and the touched skill's structure/compliance tests stay green — both
pinned here.
"""
import re
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
import _plugin_tree as PT  # noqa: E402

SKILL = PT.plugin_path("skills", "core-agent-loop", "SKILL.md")
AGENT = PT.plugin_path("agents", "ic-expert-agent.md")


def _read(p: Path) -> str:
    if not p.is_file():
        pytest.skip(f"{p.name}: {PT.NOT_SHIPPED_REASON}")
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------- SKILL.md

def test_skill_has_verbatim_token():
    # 驗收: grep -n "verbatim" SKILL.md → exit 0
    assert "verbatim" in _read(SKILL).lower()


def test_skill_round2_reopened_doc_extraction_section_present():
    txt = _read(SKILL)
    low = txt.lower()
    assert "reopen" in low
    assert "doc-extraction" in low or "doc extraction" in low
    # the failure-axis triad is the load-bearing concept
    assert "vocabulary" in low and "structure" in low and "encoding" in low


def test_skill_three_ordered_steps_present():
    low = _read(SKILL).lower()
    # (1) run the extractor on the REAL named artifact FIRST
    assert "real" in low and ("named artifact" in low or "real artifact" in low
                              or "real named artifact" in low)
    assert "returns empty" in low or "return empty" in low
    # which classifier returned None / which token missed
    assert "classifier" in low and "none" in low
    assert "token" in low
    # (3) fixture embeds the real discriminating line VERBATIM
    assert "fixture" in low
    assert re.search(r"verbatim", low)
    # never a same-shape paraphrase
    assert "paraphrase" in low


def test_skill_failure_axis_is_property_of_real_input():
    low = _read(SKILL).lower()
    assert "real input" in low
    assert "axis" in low


def test_skill_why_not_bucket_a_with_499_crossref():
    txt = _read(SKILL)
    low = txt.lower()
    assert "why_not_bucket_a" in low
    assert "#499" in txt
    assert "bucket-a" in low or "bucket a" in low
    # the programmable residue: reopen repro must pass before close
    assert "reopen repro" in low or ("repro" in low and "before close" in low)


# ------------------------------------------------------------ ic-expert-agent.md

def test_agent_has_reopened_extraction_lesson():
    low = _read(AGENT).lower()
    assert "reopened extraction" in low or "reopened doc-extraction" in low \
        or ("reopen" in low and "extraction" in low)
    assert "real artifact" in low or "real named artifact" in low \
        or "real input" in low


def test_agent_three_step_and_verbatim_obligation():
    low = _read(AGENT).lower()
    assert "verbatim" in low
    assert "paraphrase" in low
    assert "classifier" in low and "none" in low
    assert "vocabulary" in low and "structure" in low and "encoding" in low


def test_agent_499_crossref():
    assert "#499" in _read(AGENT)


# ------------------------------------------- acceptance: touched-skill tests green

def test_touched_skill_compliance_tests_green():
    # 驗收: run the skill-structure/compliance tests for the touched skill(s)
    rr = PT.repo_root()
    if rr is None:
        pytest.skip("cache tree — compliance pin runs on the source tree")
    import subprocess
    skill_tests = SKILL.parent / "tests"
    if not skill_tests.is_dir():
        pytest.skip("core-agent-loop/tests absent on this tree")
    # `-B`: this runs pytest INSIDE the shipped tree, and collecting there
    # writes `skills/core-agent-loop/**/__pycache__/*.pyc` — 4 files. That
    # moves the digest `test_shipped_skills_tree_is_untouched_by_this_session`
    # compares, so this test mutated the tree it was only meant to read, and
    # `gatekeeper-land.sh:213` fails the whole landing when the tree moves
    # under the gates. `.pyc` is gitignored, so `git status skills/` stays
    # EMPTY throughout — which is why bisecting for a dirty worktree never
    # found this. Measured: without `-B` 4 files, with it 0.
    r = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", str(skill_tests)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        "core-agent-loop skill tests must stay green:\n"
        + r.stdout[-3000:] + r.stderr[-2000:]
    )
