#!/usr/bin/env python3
"""Tests for the flow-change-acceptance skill's own compliance contract.

This skill asserts that a test which cannot fail proves nothing. It would be
self-refuting to ship it without tests, so these are its own negative controls.

What is under test is the skill's `compliance.yaml`: the six requirements that a
report authored under this skill must satisfy. Each requirement is exercised in
BOTH directions — a conforming report must match, and a report that omits exactly
that one thing must NOT match. A pattern that accepts everything would pass the
first direction and fail the second, which is the whole point.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover - environment without pyyaml
    yaml = None

SKILL_DIR = Path(__file__).resolve().parents[1]
COMPLIANCE = SKILL_DIR / "compliance.yaml"
SKILL_MD = SKILL_DIR / "SKILL.md"


def _load_requirements():
    if yaml is None:
        pytest.skip("pyyaml unavailable; compliance spec cannot be parsed")
    if not COMPLIANCE.is_file():
        pytest.fail(f"compliance spec missing at {COMPLIANCE}")
    spec = yaml.safe_load(COMPLIANCE.read_text(encoding="utf-8")) or {}
    reqs = spec.get("requirements") or []
    assert reqs, "compliance.yaml declares no requirements"
    return {r["id"]: r for r in reqs}


# A report that satisfies every requirement. Deliberately written the way a real
# report would be, not as a bag of keywords.
CONFORMING = """
## Verification

Negative control, both directions: against the parent revision the new test FAILS
(3 failed), and against HEAD it passes (12 passed). The `*_clears` assertion is only
counted paired with its `*_fires` sibling.

Corpus sweep: swept 138 real project roots, zero false positives. Coverage limit:
all 138 are macro-free so they exercise the SKIP path; the populated arm is a
synthesized fixture.

This gate is BLOCKING. Prove-by-run: on a real design the flow stopped before
detailed routing with `FAIL pnr hard-macro supply pin occupied by a signal net`,
and no DEF was produced.

Chip-agnostic: no design, PDK or vendor literal appears in the new logic; fixtures
are synthesized neutral data.

Full suite compared by failure name set, not counts: `comm -13` returns empty, so
there are no regressions; only-in-baseline is likewise empty.
"""

# Each entry removes exactly ONE requirement's evidence from the conforming report.
# If a pattern is too loose it will still match here, and the test fails — which is
# how these controls catch a rubber-stamp pattern.
OMISSIONS = {
    # Removed by regex rather than exact string: the conforming text is
    # line-wrapped, and an exact-match omission that silently matches nothing would
    # make this control vacuous. The fixture-bug assertion below catches that, and
    # it did catch it once — hence the regex.
    "R_negative_control_bidirectional": (
        re.compile(r"Negative control, both directions:.*?sibling\.\n", re.S),
        "We ran the new tests and they pass.\n",
    ),
    "R_corpus_sweep": (
        "Corpus sweep: swept 138 real project roots, zero false positives.",
        "We looked at some existing projects and it seemed fine.",
    ),
    "R_blocking_declared": (
        "This gate is BLOCKING. Prove-by-run",
        "Prove-by-run",
    ),
    "R_prove_by_run": (
        "Prove-by-run: on a real design the flow stopped before\n"
        "detailed routing with `FAIL pnr hard-macro supply pin occupied by a signal net`,\n"
        "and no DEF was produced.\n",
        "Reading the code confirms it returns a FAIL StepResult.\n",
    ),
    "R_no_literals": (
        "Chip-agnostic: no design, PDK or vendor literal appears in the new logic; "
        "fixtures\nare synthesized neutral data.\n",
        "The implementation looks clean.\n",
    ),
    "R_failure_name_sets": (
        "Full suite compared by failure name set, not counts: `comm -13` returns empty, so\n"
        "there are no regressions; only-in-baseline is likewise empty.\n",
        "Full suite: 55 failed before, 55 failed after.\n",
    ),
}


def test_compliance_spec_is_parseable_and_complete():
    reqs = _load_requirements()
    missing = set(OMISSIONS) - set(reqs)
    assert not missing, f"compliance.yaml is missing requirements exercised here: {sorted(missing)}"
    for rid, r in reqs.items():
        assert r.get("pattern"), f"{rid} has no pattern"
        re.compile(r["pattern"])  # must be a valid regex


@pytest.mark.parametrize("rid", sorted(OMISSIONS))
def test_requirement_matches_a_conforming_report(rid):
    """Direction 1: the pattern must accept a report that genuinely complies."""
    reqs = _load_requirements()
    pat = re.compile(reqs[rid]["pattern"], re.MULTILINE)
    assert pat.search(CONFORMING), (
        f"{rid} did not match a conforming report — the pattern is too strict, "
        f"so it would reject honest work"
    )


@pytest.mark.parametrize("rid", sorted(OMISSIONS))
def test_requirement_rejects_a_report_missing_exactly_that_evidence(rid):
    """Direction 2 — the load-bearing one.

    Remove ONLY this requirement's evidence and the pattern must stop matching. A
    pattern that still matches accepts a report that never did the work, which makes
    the requirement decorative.
    """
    reqs = _load_requirements()
    original, replacement = OMISSIONS[rid]
    if isinstance(original, re.Pattern):
        gutted = original.sub(replacement, CONFORMING)
    else:
        gutted = CONFORMING.replace(original, replacement)
    assert gutted != CONFORMING, (
        f"fixture bug: the {rid} omission did not change the report, so this control "
        f"proves nothing"
    )
    pat = re.compile(reqs[rid]["pattern"], re.MULTILINE)
    assert not pat.search(gutted), (
        f"{rid} still matched after its evidence was removed — the pattern is a "
        f"rubber stamp"
    )


def test_skill_documents_its_own_promotion_path():
    """The skill must name which criteria should become programs.

    A doctrine that does not plan its own replacement by deterministic checks stays
    prose forever, which contradicts program-first.
    """
    assert SKILL_MD.is_file(), f"SKILL.md missing at {SKILL_MD}"
    body = SKILL_MD.read_text(encoding="utf-8")
    assert re.search(r"(?i)promote.{0,40}program|from this prose into programs", body), (
        "SKILL.md does not identify which criteria should be promoted from prose "
        "into deterministic programs"
    )


def test_every_criterion_cites_measured_evidence():
    """Each criterion must carry a measured citation, not an assertion of taste.

    The skill's own claim is that none of its rules is a style preference.
    """
    body = SKILL_MD.read_text(encoding="utf-8")
    measured = len(re.findall(r"(?i)\*measured", body))
    assert measured >= 4, (
        f"only {measured} criteria carry a 'Measured:' citation; a rule without an "
        f"observed failure behind it is a preference, and this skill claims to have none"
    )


# ── gatekeeper addition at merge: the "too strict" direction needs more than
#    one fixture, because the fixture was authored alongside the pattern ─────

_LEGITIMATE_NO_LITERAL_PHRASINGS = [
    "Chip-agnostic: keys only on the manifest.",
    "The helper is chip agnostic by construction.",          # space, not hyphen
    "Verified: no PDK literals appear in the emitted source.",
    "no design literals — checked by grep.",                 # bare, no verb
    "The program contains no vendor names.",                 # different word order
]

_RUBBER_STAMP_TEXTS = [
    # The defect this PR is about: an incidental mention of a synthesized
    # fixture, from a paragraph belonging to a DIFFERENT requirement.
    "Corpus sweep over 138 runs used a synthesized fixture for each cell.",
    "We ran the suite and it passed.",
]


@pytest.mark.parametrize("text", _LEGITIMATE_NO_LITERAL_PHRASINGS)
def test_R_no_literals_accepts_every_honest_phrasing(text):
    """Direction 1, made real.

    The PR's single CONFORMING fixture reads "...literal APPEARS in the new
    logic", and the pattern it shipped required one of
    appear/occur/exist/present/used. Fixture and pattern were written
    together, so `test_requirement_matches_a_conforming_report` could not
    notice that the bare form — "no design literals", the way the assertion is
    normally written in a bullet — had stopped matching. main's pattern
    accepted it; the PR's did not.

    That is the exact objection the PR itself used to DROP the
    R_negative_control_bidirectional hunk: a check firing on legitimate state.
    The pattern was widened at merge so it holds for both hunks, and this list
    is what keeps a future tightening honest.
    """
    reqs = _load_requirements()
    pat = re.compile(reqs["R_no_literals"]["pattern"], re.MULTILINE)
    assert pat.search(text), f"honest phrasing rejected: {text!r}"


@pytest.mark.parametrize("text", _RUBBER_STAMP_TEXTS)
def test_R_no_literals_still_rejects_the_rubber_stamp(text):
    """Direction 2. Widening must not restore what the PR removed: main's
    `synthes(is|ized|ised) fixture` alternative matched any incidental mention
    of a synthesized fixture, so a report that never asserted chip-agnosticism
    was booked compliant."""
    reqs = _load_requirements()
    pat = re.compile(reqs["R_no_literals"]["pattern"], re.MULTILINE)
    assert not pat.search(text), f"rubber stamp still accepted: {text!r}"
