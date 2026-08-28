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
    result = _pr.run(
        [sys.executable, str(script), "--classify-comment-stdin"],
        input=stdin,
        capture_output=True,
        text=True,
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


# ---------------------------------------------------------------------------
# vibe-ic#1645 — the enumeration must not go through the REST issue listing
#
# MEASURED 2026-08-15 against `vibeic/vibe-ic`, which had 33 open issues at
# that moment (GraphQL, `gh issue list --state open --limit 200`):
#
#     gh api 'repos/vibeic/vibe-ic/issues?state=open&per_page=50'  ->  []
#     gh api 'repos/vibeic/vibe-ic/issues?state=all&per_page=100'  ->  []
#     gh api 'repos/vibeic/vibe-ic/pulls?state=open&per_page=100'  ->  6
#     gh api repos/vibeic/vibe-ic/issues/1645 -> {"state": "open"}
#
# HTTP 200, a well-formed empty array, for a repository whose issues are
# intact over GraphQL and readable one at a time over REST. The fake
# transport below reproduces exactly that: REST listings answer `[]`,
# GraphQL answers the truth. A notifier built on the REST listing reports
# `{"events": [], "fetched": 0}` with rc 0 — a successful, silent fire.
# ---------------------------------------------------------------------------

import json  # noqa: E402
from typing import Any, Dict, List, Optional  # noqa: E402

import issue_state_notify as isn  # noqa: E402

for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402


def _node(number: int, state: str, title: str,
          labels: Optional[List[str]] = None,
          updated: str = "2026-08-15T00:00:00Z") -> Dict[str, Any]:
    return {"number": number, "state": state, "title": title,
            "updatedAt": updated,
            "labels": {"nodes": [{"name": n} for n in (labels or [])]}}


def _transport(open_nodes: List[dict],
               closed_nodes: Optional[List[dict]] = None,
               errors: Optional[List[dict]] = None,
               urls: Optional[List[str]] = None):
    """A GitHub that behaves the way GitHub behaved on 2026-08-15."""
    def _fake(url: str, token: str, payload: Optional[dict] = None) -> Any:
        if urls is not None:
            urls.append(url)
        if url.endswith("/graphql"):
            if errors is not None:
                return {"data": None, "errors": errors}
            return {"data": {"repository": {
                "openIssues": {"nodes": list(open_nodes)},
                "closedIssues": {"nodes": list(closed_nodes or [])}}}}
        # Every REST *listing* on the affected repository: 200 + [].
        return []
    return _fake


def _point_at_fake_repo(monkeypatch, tmp_path, transport) -> None:
    monkeypatch.setattr(isn, "_http_json", transport)
    monkeypatch.setattr(isn, "REPO", "vibeic/vibe-ic")
    monkeypatch.setattr(isn, "STATE_PATH", tmp_path / "snapshot.json")
    monkeypatch.setenv("GH_TOKEN", "fake-token-for-tests")
    monkeypatch.setattr(isn, "TOKEN_PATH", tmp_path / "no-such-token-file")


def test_open_issues_are_seen_although_the_rest_listing_is_empty(
        monkeypatch, tmp_path, capsys) -> None:
    """The regression. REST says nothing is open; three issues are."""
    urls: List[str] = []
    _point_at_fake_repo(monkeypatch, tmp_path, _transport(
        [_node(1645, "OPEN", "REST reports 0 open issues"),
         _node(1636, "OPEN", "mutation-ledger timeouts"),
         _node(1215, "OPEN", "d7 write-record pin fired correctly")],
        urls=urls))

    rc = isn.main([])
    out = json.loads(capsys.readouterr().out)

    assert rc == 0, out
    assert "error" not in out
    assert out["fetched"] == 3, (
        "the enumeration returned %r issues for a repository with 3 open — "
        "a listing that answers [] is not a repository with nothing open "
        "(vibe-ic#1645)" % out["fetched"])
    seen = sorted(e["number"] for e in out["events"]
                  if e["kind"] == "new_issue")
    assert seen == [1215, 1636, 1645], out["events"]
    assert any(u.endswith("/graphql") for u in urls), urls


def test_a_query_that_could_not_be_answered_is_not_a_quiet_fire(
        monkeypatch, tmp_path, capsys) -> None:
    """GitHub answers a broken GraphQL query with HTTP 200 + `errors`."""
    snapshot = tmp_path / "snapshot.json"
    _point_at_fake_repo(monkeypatch, tmp_path, _transport(
        [], errors=[{"message": "Something went wrong while executing your "
                                "query"}]))

    rc = isn.main([])
    out = json.loads(capsys.readouterr().out)

    assert rc == 2, out
    assert out["error"] == "issue_enumeration_failed", out
    assert "events" not in out, (
        "an empty event list here reads to the cron as 'nothing changed'")
    assert not snapshot.exists(), (
        "a fire that could not enumerate must not overwrite the snapshot")


def test_missing_repository_object_is_refused_not_read_as_empty(
        monkeypatch, tmp_path, capsys) -> None:
    def _fake(url: str, token: str, payload=None):
        if url.endswith("/graphql"):
            return {"data": {"repository": None}}
        return []
    _point_at_fake_repo(monkeypatch, tmp_path, _fake)

    rc = isn.main([])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2, out
    assert out["error"] == "issue_enumeration_failed", out


def test_a_rest_era_snapshot_does_not_fire_a_state_change(
        monkeypatch, tmp_path, capsys) -> None:
    """GraphQL says OPEN; snapshots on disk say open. Same state."""
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({"1645": {
        "state": "open", "labels": ["bug"],
        "updated_at": "2026-08-14T00:00:00Z", "title": "old title"}}))
    _point_at_fake_repo(monkeypatch, tmp_path, _transport(
        [_node(1645, "OPEN", "old title", ["bug"])]))

    rc = isn.main([])
    out = json.loads(capsys.readouterr().out)

    assert rc == 0, out
    assert out["events"] == [], (
        "state casing must be normalised, or the first fire after the "
        "transport change reports a state_change on every tracked issue")


def test_close_and_label_events_still_fire(
        monkeypatch, tmp_path, capsys) -> None:
    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({
        "1645": {"state": "open", "labels": [],
                 "updated_at": "2026-08-14T00:00:00Z", "title": "t"},
        "1600": {"state": "open", "labels": ["bug"],
                 "updated_at": "2026-08-14T00:00:00Z", "title": "t"}}))
    _point_at_fake_repo(monkeypatch, tmp_path, _transport(
        [_node(1645, "OPEN", "t", ["core-closed"])],
        [_node(1600, "CLOSED", "t", ["bug"])]))

    rc = isn.main([])
    out = json.loads(capsys.readouterr().out)

    assert rc == 0, out
    kinds = {(e["kind"], e["number"]) for e in out["events"]}
    assert ("label_added", 1645) in kinds, out["events"]
    assert ("state_change", 1600) in kinds, out["events"]
    change = [e for e in out["events"] if e["kind"] == "state_change"][0]
    assert (change["from"], change["to"]) == ("open", "closed"), change
