"""The section-14.4 boundary for `ppa-distill`, as a fixture rather than as prose.

An agent skill emits a structured proposal or an evidence-linked report. The
pass/fail call belongs to a deterministic program. That sentence is in
SKILL.md, but a sentence in SKILL.md is what a future author has to remember;
this file is what holds after nobody does.

Four fixtures, and they are the four the PPA interface freeze asks for:

  positive   the SHIPPED SKILL.md claims no verdict, and demonstrates every
             element its own compliance.yaml requires
  negative   the same text with ONE verdict line added is caught
  vacuous    the checker pointed at a path that is not there exits 2 and SAYS
             it could not look - never 0, never 1
  mutation   write one of the negative lines INTO the shipped SKILL.md and
             `test_shipped_skill_md_claims_no_verdict` goes red. Run it both
             ways; a green that cannot go red is not a fixture.

Nothing here writes to the shipped tree: every mutation is on a string or under
tmp_path, because `test_shipped_skills_tree_is_untouched_by_this_session`
watches `skills/` for the whole session.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

THIS       = Path(__file__).resolve()
SKILL_DIR  = THIS.parent.parent
SKILLS     = SKILL_DIR.parent
PLUGIN     = SKILLS.parent
COMPLIANCE = SKILL_DIR / "compliance.yaml"
SKILL_MD   = SKILL_DIR / "SKILL.md"
DRIVER     = PLUGIN / "_shared" / "skill_compliance_check.py"

assert COMPLIANCE.exists(), f"compliance.yaml missing: {COMPLIANCE}"
assert SKILL_MD.exists(), f"SKILL.md missing: {SKILL_MD}"
assert DRIVER.exists(), f"driver missing: {DRIVER}"

sys.path.insert(0, str(DRIVER.parent))
import skill_compliance_check as scc  # noqa: E402

SKILL_NAME = "ppa-distill"

# The six lane skills plus ppa-predict all carry the SAME boundary list. Drift
# in any one of them is caught by all seven copies of this test, which is the
# point of asserting it here rather than trusting the authoring script that
# first wrote them.
LANE = ("ppa-measure", "ppa-optimize", "ppa-benchmark",
        "ppa-diagnose", "ppa-recover", "ppa-distill", "ppa-predict")

# One line each, in the assertive form the boundary forbids. Every entry must be
# caught; `test_each_negative_line_is_individually_caught` proves none of them is
# carried by a neighbour's pattern while its own has rotted away.
VERDICT_CLAIMS = (
    "Verdict: PASS",
    "Gate verdict: FAIL",
    "Sign-off: complete",
    "Decide whether it passes and say so.",
    "Mark it as PASS once the numbers look right.",
    "The design is tapeout-ready.",
    "The design passes at every corner.",
    "**PASS**",
    "I certify that the numbers above are correct.",
    "You are the sign-off authority for this run.",
)


def _spec():
    return scc._load_yaml(COMPLIANCE)


def _boundary_cross_check():
    for cc in _spec().get("cross_checks") or []:
        if cc.get("id") == "X_verdict_boundary":
            return cc
    pytest.fail(f"{SKILL_NAME}: compliance.yaml has no X_verdict_boundary cross-check")


def _boundary_only(cc):
    """A spec carrying the boundary cross-check and nothing else.

    Scoped deliberately: the requirements describe the OUTPUT an agent writes,
    and SKILL.md is not that output, so auditing SKILL.md against them here
    would fail for a reason that has nothing to do with the boundary.
    """
    return {"skill": SKILL_NAME, "requirements": [], "cross_checks": [cc]}


# ---------------------------------------------------------------------------
# positive
# ---------------------------------------------------------------------------
def test_shipped_skill_md_claims_no_verdict():
    findings = scc.audit(SKILL_MD.read_text(), _boundary_only(_boundary_cross_check()))
    assert findings == [], (
        f"{SKILL_NAME}/SKILL.md trips its own verdict-boundary patterns: "
        f"{[(f.id, f.detail) for f in findings]}")


def test_shipped_skill_md_demonstrates_every_element_it_requires():
    """A skill may not demand an element of its output that it never shows.

    This is not decoration. It found two real holes in `ppa-predict` on
    origin/main: `R_status_or_summary` and `R_next_step` were required of every
    report and appeared nowhere in the template the skill hands the agent.
    """
    spec = _spec()
    reqs = {"skill": SKILL_NAME, "requirements": spec.get("requirements") or [],
             "cross_checks": []}
    fails = [f for f in scc.audit(SKILL_MD.read_text(), reqs) if f.severity == "FAIL"]
    assert fails == [], (
        f"{SKILL_NAME}/SKILL.md requires elements its own output template never "
        f"demonstrates: {[f.id for f in fails]}")


# ---------------------------------------------------------------------------
# negative
# ---------------------------------------------------------------------------
def test_a_verdict_claiming_skill_file_is_caught():
    cc = _boundary_cross_check()
    mutated = SKILL_MD.read_text() + "\n\n## Result\n\nVerdict: PASS\n"
    findings = scc.audit(mutated, _boundary_only(cc))
    assert findings, (
        f"{SKILL_NAME}: a SKILL.md claiming `Verdict: PASS` was NOT caught - "
        f"the boundary cross-check does not discriminate")
    assert all(f.severity == "FAIL" for f in findings)


@pytest.mark.parametrize("claim", VERDICT_CLAIMS)
def test_each_negative_line_is_individually_caught(claim):
    cc = _boundary_cross_check()
    findings = scc.audit("# report\n\n" + claim + "\n", _boundary_only(cc))
    assert findings, f"{SKILL_NAME}: verdict claim not caught: {claim!r}"


def test_an_honest_report_is_not_caught():
    """The other half of discrimination: text that quotes a program's verdict,
    with its program name and its exit code, is what this skill is FOR."""
    cc = _boundary_cross_check()
    honest = (
        "# report\n\n"
        "Verdict authority: _ppa/feasibility.py - this report states no "
        "pass/fail of its own.\n\n"
        "Program-first: _ppa/agent_router.py rc=2 - it reached no conclusion, "
        "so the two remaining endpoints are carried as residual questions "
        "rather than assumed clean.\n"
    )
    findings = scc.audit(honest, _boundary_only(cc))
    assert findings == [], (
        f"{SKILL_NAME}: an honest attributed report was flagged: "
        f"{[(f.id, f.detail) for f in findings]}")


# ---------------------------------------------------------------------------
# vacuous - the one that is not paperwork
# ---------------------------------------------------------------------------
def test_absent_output_file_is_undetermined_not_a_finding(tmp_path):
    """rc=1 is a claim about the design. A checker that never opened its input
    has made no such claim and must not exit 1 - nor 0, which would let a gate
    pass by pointing at nothing."""
    missing = tmp_path / "no_such_report.md"
    assert not missing.exists()
    res = subprocess.run(
        [sys.executable, str(DRIVER), "--requirements", str(COMPLIANCE), str(missing)],
        capture_output=True, text=True)
    assert res.returncode == 2, (
        f"absent input gave rc={res.returncode}; expected 2 (UNDETERMINED). "
        f"stdout={res.stdout!r} stderr={res.stderr!r}")
    said_so = (res.stdout + res.stderr)
    assert "no_such_report.md" in said_so and "not found" in said_so.lower(), (
        "the checker exited 2 without saying what it could not read; "
        "'could not look' and 'looked and found nothing' must never print alike")


def test_absent_compliance_file_is_undetermined_too(tmp_path):
    report = tmp_path / "report.md"
    report.write_text("# report\n")
    res = subprocess.run(
        [sys.executable, str(DRIVER),
         "--requirements", str(tmp_path / "no_such_compliance.yaml"), str(report)],
        capture_output=True, text=True)
    assert res.returncode == 2, (
        f"absent requirements gave rc={res.returncode}; expected 2")


def test_empty_output_fails_the_real_cli(tmp_path):
    """rc=1 IS available, and an empty report earns it: every required element
    is genuinely absent from a document that exists and was read."""
    report = tmp_path / "empty.md"
    report.write_text("")
    res = subprocess.run(
        [sys.executable, str(DRIVER), "--requirements", str(COMPLIANCE), str(report)],
        capture_output=True, text=True)
    assert res.returncode == 1, f"empty report gave rc={res.returncode}; expected 1"


# ---------------------------------------------------------------------------
# the list itself
# ---------------------------------------------------------------------------
def test_boundary_patterns_are_identical_across_the_ppa_lane():
    mine = _boundary_cross_check().get("patterns") or []
    assert mine, f"{SKILL_NAME}: X_verdict_boundary carries no patterns"
    for other in LANE:
        d = SKILLS / other / "compliance.yaml"
        if not d.exists():
            pytest.fail(f"lane skill {other} has no compliance.yaml")
        spec = scc._load_yaml(d)
        cc = next((c for c in (spec.get("cross_checks") or [])
                   if c.get("id") == "X_verdict_boundary"), None)
        assert cc is not None, f"{other}: no X_verdict_boundary cross-check"
        assert (cc.get("patterns") or []) == mine, (
            f"verdict-boundary patterns drifted between {SKILL_NAME} and {other}")


def test_every_boundary_pattern_compiles_and_is_case_insensitive():
    import re
    for pat in _boundary_cross_check().get("patterns") or []:
        re.compile(pat)
        assert pat.startswith("(?i)"), (
            f"{SKILL_NAME}: boundary pattern is case-sensitive: {pat!r}. The "
            f"driver applies re.MULTILINE only to no_forbidden_patterns, so a "
            f"pattern without (?i) misses `VERDICT:` and `verdict:` alike.")
