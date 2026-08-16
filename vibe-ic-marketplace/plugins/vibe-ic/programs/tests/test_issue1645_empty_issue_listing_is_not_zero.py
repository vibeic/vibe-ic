#!/usr/bin/env python3
"""vibe-ic#1645 — an empty REST issue listing is not a count of zero issues.

`#1384` fixed this for `core-agent-loop/programs/poll.py`. `tools/
issue_state_notify.py` is the OTHER consumer of the same REST collection, and
that fix never reached it: it is the cron's only source of issue state-change
events, and an empty listing made it emit a clean "nothing changed".

MEASURED 2026-08-16, core quota healthy (`X-Ratelimit-Remaining: 4994`, so not
throttling), against `reyerchu/AI_IC_design` — the repository the tool itself
targets:

    GET /repos/reyerchu/AI_IC_design/issues?state=closed&per_page=20   []
    GraphQL repository.issues(states:CLOSED).totalCount               808

and the program on the pre-fix tree, run for real against that API:

    $ python3 tools/issue_state_notify.py
    {"events": [], "tracked": 0, "fetched": 0}
    rc=0

`fetched: 0`, no events, rc 0 — the same stdout and the same exit code the
program emits for a genuinely quiet repository, while 808 issues sat behind a
listing that could not see them.

WHAT THIS FILE PINS, IN BOTH DIRECTIONS
=======================================
The failing direction is cheap to buy by refusing every empty listing, and that
would be worse than the bug: a cron that halts on every quiet fire is a cron
somebody switches off. The second arm is the load-bearing one.

    contradiction   listing [], repository declares items    -> CannotLook,
                    rc 2, stdout carries `error` and NO `events` key, and the
                    message names both numbers.
    agreement       listing [], repository declares 0        -> rc 0, still a
                    zero. The quiet repository is not disturbed.
    all-PR page     listing non-empty but every item is a PR -> rc 0, and the
                    witness is never asked. The RAW page is what gets
                    witnessed, because the pull-request filter runs after it.
    unreadable      listing [], witness unreachable          -> rc 0, but
                    [UNWITNESSED] on stderr. None is not zero; it is also not
                    grounds to halt, because the listing itself succeeded.
    not asked       listing non-empty                        -> no witness
                    call at all. One extra call, only on the fire that would
                    otherwise go back to sleep.
    snapshot        a refused fire must not rewrite the snapshot — it is the
                    only record of the last state that was actually seen.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from _hostpaths import require_repo


def _load_module():
    """Import `tools/issue_state_notify.py` from the source monorepo.

    Skips (never fails) when the monorepo is absent — this test lives in the
    plugin tree and the tool it exercises does not ship with the plugin.
    """
    path = require_repo("tools", "issue_state_notify.py")
    spec = importlib.util.spec_from_file_location(
        "_issue_state_notify_under_test_1645", path)
    if spec is None or spec.loader is None:
        pytest.skip(f"cannot load a module spec from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def mod():
    return _load_module()


def _issue(number: int, state: str = "open") -> dict:
    return {"number": number, "state": state, "labels": [],
            "updated_at": "2026-08-16T00:00:00Z", "title": f"issue {number}"}


def _pr(number: int) -> dict:
    d = _issue(number, "closed")
    d["pull_request"] = {"url": "https://example.invalid/pr"}
    return d


_ALL_ZERO = {"openIssues": 0, "closedIssues": 0,
             "openPrs": 0, "closedPrs": 0, "mergedPrs": 0}


def _wire(mod, monkeypatch, tmp_path, *, open_page, closed_page, declared,
          snapshot=None):
    """Stub both REST pages and the witness; isolate the snapshot file.

    Returns a dict recording how many times the witness was consulted, so the
    "not asked" arm can be asserted rather than assumed.
    """
    calls = {"witness": 0}

    def fake_gh(path: str, token: str):
        assert "/issues?" in path, path
        return open_page if "state=open" in path else closed_page

    def fake_declared(token: str):
        calls["witness"] += 1
        return declared

    state_path = tmp_path / "state.json"
    if snapshot is not None:
        state_path.write_text(json.dumps(snapshot))
    token_path = tmp_path / "token"
    token_path.write_text("gho_stub\n")

    monkeypatch.setattr(mod, "_gh", fake_gh)
    monkeypatch.setattr(mod, "_declared_counts", fake_declared)
    monkeypatch.setattr(mod, "STATE_PATH", state_path)
    monkeypatch.setattr(mod, "TOKEN_PATH", token_path)
    monkeypatch.setattr(sys, "argv", ["issue_state_notify.py"])
    return calls, state_path


# ---------------------------------------------------------------------------
# The failing direction: an empty listing the repository contradicts
# ---------------------------------------------------------------------------

def test_empty_closed_listing_against_a_declared_count_is_refused(
        mod, monkeypatch, tmp_path, capsys):
    """The live 2026-08-16 case: closed listing [], repository declares 808."""
    _wire(mod, monkeypatch, tmp_path,
          open_page=[], closed_page=[],
          declared={**_ALL_ZERO, "closedIssues": 808})

    rc = mod.main()
    out = capsys.readouterr()

    assert rc == 2, f"a listing that could not look must not exit 0 (rc={rc})"
    payload = json.loads(out.out)
    assert payload["error"] == "listing_contradicts_repository"
    # The whole point: a reader doing payload["events"] must raise here rather
    # than quietly find an empty list.
    assert "events" not in payload, payload
    assert "808" in payload["detail"], payload["detail"]
    assert "closed" in payload["detail"], payload["detail"]


def test_empty_open_listing_against_a_declared_count_is_refused(
        mod, monkeypatch, tmp_path, capsys):
    """The open arm, witnessed against open issues AND open PRs."""
    _wire(mod, monkeypatch, tmp_path,
          open_page=[], closed_page=[_issue(1, "closed")],
          declared={**_ALL_ZERO, "openIssues": 22, "openPrs": 13})

    rc = mod.main()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 2
    # 22 + 13: the REST collection enumerates PRs too, so the witness counts
    # the same population the listing does.
    assert "35" in payload["detail"], payload["detail"]


def test_a_refused_fire_does_not_rewrite_the_snapshot(
        mod, monkeypatch, tmp_path):
    """The snapshot is the last state we could actually see. Keep it."""
    before = {"7": {"state": "open", "labels": ["bug"],
                    "updated_at": "2026-08-01T00:00:00Z", "title": "seven"}}
    _calls, state_path = _wire(
        mod, monkeypatch, tmp_path,
        open_page=[], closed_page=[],
        declared={**_ALL_ZERO, "closedIssues": 808},
        snapshot=before)

    assert mod.main() == 2
    assert json.loads(state_path.read_text()) == before


# ---------------------------------------------------------------------------
# The load-bearing direction: a real zero must stay a zero
# ---------------------------------------------------------------------------

def test_an_agreed_zero_is_still_a_zero(mod, monkeypatch, tmp_path, capsys):
    """A genuinely quiet repository must not be disturbed on any fire.

    This arm is why the fix is a witness and not a refusal. If this test can be
    made to pass by refusing every empty listing, the fix has become an outage.
    """
    _wire(mod, monkeypatch, tmp_path,
          open_page=[], closed_page=[], declared=dict(_ALL_ZERO))

    rc = mod.main()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0, "an empty repository is not an error"
    assert payload["events"] == []
    assert payload["fetched"] == 0
    assert "error" not in payload, payload


def test_an_all_pull_request_page_is_not_witnessed(
        mod, monkeypatch, tmp_path, capsys):
    """A page of nothing but PRs filters down to zero issues — legitimately.

    The witness is deliberately applied to the RAW page, before the
    pull-request filter. Witnessing the FILTERED result against an
    issues-only count is the substitution that turns this fix into a cron
    that refuses every fire on a PR-heavy repository.
    """
    calls, _ = _wire(mod, monkeypatch, tmp_path,
                     open_page=[_pr(101), _pr(102)],
                     closed_page=[_pr(103)],
                     declared={**_ALL_ZERO, "closedIssues": 808})

    rc = mod.main()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0, "an all-PR page is a legitimate zero for this program"
    assert payload["fetched"] == 0
    assert calls["witness"] == 0, "the raw pages were not empty; do not ask"


def test_an_unreadable_witness_does_not_halt_but_is_said_out_loud(
        mod, monkeypatch, tmp_path, capsys):
    """None is not zero — and it is not grounds to stop either."""
    _wire(mod, monkeypatch, tmp_path,
          open_page=[], closed_page=[], declared=None)

    rc = mod.main()
    out = capsys.readouterr()

    assert rc == 0, "the listing itself succeeded; do not halt on a silent witness"
    assert json.loads(out.out)["events"] == []
    assert "[UNWITNESSED]" in out.err, out.err


def test_a_non_empty_listing_never_pays_for_the_witness(
        mod, monkeypatch, tmp_path, capsys):
    """One extra call, only on the fire that would otherwise report nothing."""
    calls, _ = _wire(mod, monkeypatch, tmp_path,
                     open_page=[_issue(5)], closed_page=[_issue(6, "closed")],
                     declared=dict(_ALL_ZERO))

    rc = mod.main()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["fetched"] == 2
    assert calls["witness"] == 0


# ---------------------------------------------------------------------------
# The witness itself must not be built on the stale index it is checking
# ---------------------------------------------------------------------------

def test_the_witness_is_graphql_and_not_the_rest_counter(mod):
    """`open_issues_count` is served by the same index that returns the empty
    listing — it read 0 alongside it in every measurement, so a witness built
    on it would agree with the bug. Pinned so it cannot be swapped back in."""
    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert "graphql" in src.lower(), "the witness must use a different backend"
    query = mod._WITNESS_QUERY
    assert "issues(states:OPEN)" in query, query
    assert "issues(states:CLOSED)" in query, query
    # PRs on both sides, because that is what the REST collection returns.
    assert "pullRequests(states:OPEN)" in query, query
    assert "pullRequests(states:MERGED)" in query, query
    # Comment lines may NAME the rejected counter — the file explains why it is
    # rejected, and that prose is the point. What must not exist is a live
    # reference to it.
    code = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    offenders = [ln for ln in code if "open_issues_count" in ln]
    assert not offenders, (
        "open_issues_count is the stale counter itself, not a witness for it: "
        f"{offenders}")
