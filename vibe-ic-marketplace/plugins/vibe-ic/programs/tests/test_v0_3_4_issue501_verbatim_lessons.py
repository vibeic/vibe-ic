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
    import os
    import subprocess
    skill_tests = SKILL.parent / "tests"
    if not skill_tests.is_dir():
        pytest.skip("core-agent-loop/tests absent on this tree")
    # The child runs pytest INSIDE the SHIPPED `skills/` tree, so it collects
    # and imports files from under it — and CPython caches the byte-code NEXT
    # TO THE SOURCE. Measured on clean main `75776dbbb`, this one call left
    # four files inside the tree this repository ships:
    #
    #   skills/core-agent-loop/programs/__pycache__/api_health.cpython-310.pyc
    #   skills/core-agent-loop/programs/__pycache__/poll.cpython-310.pyc
    #   skills/core-agent-loop/tests/__pycache__/
    #       test_compliance.cpython-310-pytest-9.1.1.pyc
    #   skills/core-agent-loop/tests/__pycache__/
    #       test_poll_actionable_is_open.cpython-310-pytest-9.1.1.pyc
    #
    # WHICH DETECTOR ACTUALLY OWNS THIS, measured rather than assumed. Three
    # plausible ones do NOT, and saying otherwise would be a comment that
    # stops being true the moment someone checks it:
    #
    #   * `git status skills/` is EMPTY — `__pycache__/` is gitignored — so
    #     `landing_worktree_is_clean_check` reads the tree as clean;
    #   * `suite_write_guard` classifies them through `_is_cache_noise` and
    #     logs them ADVISORY, never blocking;
    #   * `test_tools_and_integration.py::
    #      test_shipped_skills_tree_is_untouched_by_this_session` skips them
    #     too — `_digest_tree` filters on that same `_is_cache_noise`
    #     predicate, deliberately, because digesting them made the gate cry
    #     wolf on bare collection. Measured both arms here: with the writer
    #     live and running BEFORE it in one session, that digest still passes.
    #
    # The invariant that IS violated is "the shipped tree carries no build
    # output", owned by `test_issue1417_no_test_bytecompiles_the_shipped_tree`.
    # Both of its relevant assertions go red on the pre-fix file, and one of
    # them is red on clean main with nothing else running:
    # `test_no_test_module_spawns_a_child_into_the_shipped_tree_unsuppressed`
    # names this module as the offender by source shape, and
    # `test_the_shipped_tree_carries_no_committed_bytecode` goes red once the
    # child has actually run.
    #
    # This is a SPAWNED child, so the `sys.dont_write_bytecode` remedy that
    # `_load_shipped_module` uses for the in-process importers cannot reach
    # it — `dont_write_bytecode` is per-interpreter. Only the child's own
    # environment can suppress it. `PYTHONDONTWRITEBYTECODE` covers pytest's
    # assertion-rewrite caches too: with it set, the same run leaves zero
    # files under `skills/` and the child still reports 5 passed, 1 skipped.
    #
    # `-p no:cacheprovider` is deliberately NOT added. `.pytest_cache` is
    # placed at ROOTDIR, which `vibe-ic/pytest.ini` pins to the plugin root —
    # measured from `cwd=/` as well, so it does not depend on the caller's
    # directory. It never lands under `skills/`, so disabling it would be a
    # flag added to silence a check that had nothing to say.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    # Measured BEFORE and AFTER, and differenced, so this accuses only its own
    # child. An absolute "no .pyc under skills/" would inherit whatever an
    # earlier test in the session left there and point at the wrong writer —
    # the exact failure mode that cost #1417 a bisection.
    skills_root = SKILL.parents[1]
    before = {str(q) for q in skills_root.rglob("*.pyc")}
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(skill_tests)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    leaked = sorted(str(q) for q in skills_root.rglob("*.pyc")
                    if str(q) not in before)
    assert r.returncode == 0, (
        "core-agent-loop skill tests must stay green:\n"
        + r.stdout[-3000:] + r.stderr[-2000:]
    )
    assert not leaked, (
        "this test's own child byte-compiled the SHIPPED skills/ tree: "
        f"{leaked}. `sys.dont_write_bytecode` is per-interpreter and cannot "
        "reach a spawned child; the child needs PYTHONDONTWRITEBYTECODE=1 in "
        "its environment. Almost nothing else reports it: `.pyc` is "
        "gitignored, so `git status` and `git add -A` stay clean, and "
        "suite_write_guard and the skills/ digest in "
        "test_tools_and_integration.py both filter it out as cache noise. "
        "The invariant is owned by "
        "test_issue1417_no_test_bytecompiles_the_shipped_tree, which is the "
        "only other thing that goes red."
    )
