"""Prose-report skills must be satisfiable, and must not fake an RTL verdict.

Thirteen skills whose deliverable is a markdown report carried the cross-check
`X_text_only_skill` with `rule: postcheck_pass_only`. That rule requires the
output to carry an RTL header of the form

    // Post-checks: rtl_hygiene_lint=PASS, fsm_error_invariant=PASS

A report is not RTL, so the header can never legitimately appear — which made
every one of those skills unsatisfiable: an author could supply every required
element and still get FAIL, and the only route to green was to paste a header
asserting two tool verdicts that had never been measured on the document.

`text_only_report` replaces it and keeps the teeth pointed the other way: a
prose report PASSES when it makes no RTL post-check claim, and FAILS when it
makes one.

Both directions are asserted here so that neither half can regress silently.
"""
import subprocess
import sys
from pathlib import Path

import pytest

_PLUGIN = Path(__file__).resolve().parents[2]
_CHECKER = _PLUGIN / "_shared" / "skill_compliance_check.py"
_SKILLS = _PLUGIN / "skills"

# The cross-check id that marks a skill as prose-only.
_TEXT_ONLY_ID = "X_text_only_skill"

_REPORT = """# Phase 1 Completeness Deep Review

**Verdict**: PASS

## Findings

Every layer L1 through L13 was examined for coverage.

## AI patches applied

| L doc | Fact | Source doc | Strategy |
| --- | --- | --- | --- |
| L19_CONSTRAINTS_PDK | some literal | some_input.txt | ai_deep_review_patch |

Next: run /vibe-ic-phase2
"""

_RTL_HEADER = "// Post-checks: rtl_hygiene_lint=PASS, fsm_error_invariant=PASS\n"


def _text_only_skills():
    """Every skill declaring the prose-only cross-check."""
    out = []
    for yaml in sorted(_SKILLS.glob("*/compliance.yaml")):
        if _TEXT_ONLY_ID in yaml.read_text(errors="replace"):
            out.append(yaml)
    return out


def _run(requirements: Path, target: Path):
    proc = subprocess.run(
        [sys.executable, str(_CHECKER),
         "--requirements", str(requirements), str(target)],
        capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def test_text_only_skills_exist():
    """Guard the fixture: if the id is renamed, the rest would vacuously pass."""
    assert _text_only_skills(), (
        f"no skill declares {_TEXT_ONLY_ID}; this test would otherwise be "
        f"vacuous")


def test_no_text_only_skill_demands_an_rtl_postcheck_header():
    """The defect itself: a prose skill must not be wired to the RTL rule.

    Against the pre-fix tree every one of these files says
    `rule: postcheck_pass_only`, so this fails 13 times over.
    """
    offenders = []
    for yaml in _text_only_skills():
        body = yaml.read_text(errors="replace")
        # Look only inside the X_text_only_skill block.
        block = body.split(_TEXT_ONLY_ID, 1)[1].split("- id:", 1)[0]
        if "postcheck_pass_only" in block:
            offenders.append(yaml.parent.name)
    assert not offenders, (
        "prose-report skill(s) still require an RTL post-check header, which "
        "their markdown output can never carry honestly: " + ", ".join(offenders))


def test_clean_report_passes(tmp_path):
    """A complete prose report is accepted (pre-fix: FAIL, post-fix: PASS)."""
    yaml = _SKILLS / "phase1-completeness-deep-review" / "compliance.yaml"
    target = tmp_path / "report.md"
    target.write_text(_REPORT)
    rc, out = _run(yaml, target)
    assert rc == 0, (
        "a prose report carrying every required element was rejected; the "
        "skill is unsatisfiable:\n" + out)


def test_report_claiming_an_rtl_postcheck_is_rejected(tmp_path):
    """The new teeth: fabricating the header must FAIL (pre-fix: PASS)."""
    yaml = _SKILLS / "phase1-completeness-deep-review" / "compliance.yaml"
    target = tmp_path / "report_with_fake_header.md"
    target.write_text(_RTL_HEADER + _REPORT)
    rc, out = _run(yaml, target)
    assert rc != 0, (
        "a prose report asserting rtl_hygiene_lint / fsm_error_invariant "
        "verdicts that were never measured on it was accepted:\n" + out)


@pytest.mark.parametrize("yaml", _text_only_skills(),
                         ids=lambda p: p.parent.name)
def test_every_text_only_skill_accepts_a_minimal_report(tmp_path, yaml):
    """No prose skill may reject output solely for lacking an RTL header.

    Other requirements may legitimately fail on this generic fixture, so this
    asserts only that the RTL-header finding is not the reason.
    """
    target = tmp_path / "report.md"
    target.write_text(_REPORT)
    _, out = _run(yaml, target)
    assert "Add the header to the RTL/output before shipping" not in out, (
        f"{yaml.parent.name} still demands an RTL post-check header:\n{out}")
