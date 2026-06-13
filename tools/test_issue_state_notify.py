"""tests/test_issue_state_notify.py - v1.6.71

Closes the cron-triage classifier bug. The cron's prompt embedded an
inline classifier that conflated core-agent push comments with
field-agent verification reports. This moves the classifier into a
testable helper in ``tools/issue_state_notify.py`` and pins the
contract with positive + negative test pairs.

Contract (from durable rule
``feedback_debug_agent_field_agent_terminology.md`` + the cron prompt
spec):
  * core-agent push comments start with ``## v<X.Y.Z> -`` and do NOT
    contain the keyword ``verification`` on the first line
  * field-agent verification reports start with ``## v<X.Y.Z>
    verification ...``
  * other comments (questions, prose, anything else) classify as
    non-core (i.e. ``False``)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Make tools/ importable when run via pytest from the repo root.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from issue_state_notify import comment_is_core_agent  # noqa: E402


# ---------------------------------------------------------------------------
# Positive (core-agent push) cases
# ---------------------------------------------------------------------------

def test_classifier_core_push_em_dash() -> None:
    body = "## v1.6.71 - Bugs A/B/C fixed\n\nDetails follow."
    assert comment_is_core_agent(body) is True


def test_classifier_core_push_unicode_em_dash() -> None:
    # Real em-dash (U+2014); regex matches the v<X.Y.Z>\b prefix only
    # and tolerates whatever follows as long as `verification` is absent.
    body = "## v1.6.71 — Bugs A/B/C fixed"
    assert comment_is_core_agent(body) is True


def test_classifier_core_push_lowercase_v() -> None:
    body = "## V1.6.71 - fix"
    assert comment_is_core_agent(body) is True


def test_classifier_leading_blank_lines_tolerated() -> None:
    body = "\n\n   ## v1.6.71 - bundled fixes\n"
    assert comment_is_core_agent(body) is True


# ---------------------------------------------------------------------------
# Negative (field-agent verification) cases
# ---------------------------------------------------------------------------

def test_classifier_field_verification_single_version() -> None:
    body = ("## v1.6.70 verification - Bug A fully fixed; "
            "Bug B regressed")
    assert comment_is_core_agent(body) is False


def test_classifier_field_verification_dual_version_prefix() -> None:
    body = ("## v1.6.67/v1.6.70 verification - Bug B fully fixed; "
            "Bug A and Bug C have residual gaps")
    # Note: this starts with `## v1.6.67/v1.6.70` so the regex
    # `^##\s*v\d+\.\d+\.\d+\b` matches v1.6.67 and the slash is a
    # \b break -- still a valid version prefix; the `verification`
    # keyword on the same line is what classifies it as field.
    assert comment_is_core_agent(body) is False


def test_classifier_verification_capitalised() -> None:
    body = "## v1.6.71 Verification report"
    assert comment_is_core_agent(body) is False


# ---------------------------------------------------------------------------
# Neither (questions, prose, off-format)
# ---------------------------------------------------------------------------

def test_classifier_plain_question_is_not_core() -> None:
    body = "Hi, just a question about the regex"
    assert comment_is_core_agent(body) is False


def test_classifier_no_version_prefix_is_not_core() -> None:
    body = "## Bugs fixed"
    assert comment_is_core_agent(body) is False


def test_classifier_empty_body_is_not_core() -> None:
    assert comment_is_core_agent("") is False
    assert comment_is_core_agent(None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# CLI: --classify-comment-stdin contract
# ---------------------------------------------------------------------------

def _run_classifier_cli(stdin: str) -> str:
    script = _HERE / "issue_state_notify.py"
    result = subprocess.run(
        [sys.executable, str(script), "--classify-comment-stdin"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "HOME": os.environ.get("HOME", "/tmp")},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_classifier_cli_prints_core_for_push() -> None:
    out = _run_classifier_cli("## v1.6.71 - bugs fixed")
    assert out == "core"


def test_classifier_cli_prints_field_for_verification() -> None:
    out = _run_classifier_cli("## v1.6.71 verification - residual gap")
    assert out == "field"


def test_classifier_cli_prints_field_for_random_text() -> None:
    out = _run_classifier_cli("Just a comment, no markdown header")
    assert out == "field"
