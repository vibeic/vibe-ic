#!/usr/bin/env python3
"""Q2 gatekeeper-loop — poll_prs.py regression tests.

`skills/gatekeeper-loop/programs/poll_prs.py` is the PR-merge counterpart
of `skills/core-agent-loop/programs/poll.py`. It enumerates the open,
NON-DRAFT PRs the single gatekeeper agent must service this tick. The
poll is a DETERMINISTIC enumerator — it never makes a merge decision (that
is the machine gates + Step-2.7 adversarial review). These tests pin the
exit-code contract and the four hard enumeration rules:

  rc=0  no actionable PRs  (healthy idle — never a stop signal)
  rc=1  >=1 actionable PR
  rc=2  io/auth error      (retry next tick; NOT actionable)

ENUMERATION RULES (pinned here so a future query change cannot leak):
  - drafts are excluded (the author's own "not ready" signal)
  - a PR against a DIFFERENT base is excluded (belt-and-braces re-check)
  - actionable PRs are returned NEWEST-FIRST (highest number first)
  - a CONFLICTING / DIRTY PR is STILL actionable — `mergeable` is surfaced
    as ADVISORY context, NEVER as a poll filter (silently dropping it
    would wedge the PR with no eject path; §4.05 no-leak: the poll must
    not mask a PR that needs the gatekeeper to request-changes)
  - the REST fallback path projects into the SAME shape as the gh path

chip-AGNOSTIC: every assertion is over generic PR metadata (number /
base / draft / mergeable) — no chip / vendor / SKU literal anywhere.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PLUGIN_ROOT = Path(__file__).resolve().parents[2]
_POLL_PRS = (_PLUGIN_ROOT / "skills" / "gatekeeper-loop" / "programs"
             / "poll_prs.py")


def _load():
    """Import the shipped program WITHOUT leaving bytecode beside it.

    `skills/` is the SHIPPED tree. Importing a file from it makes CPython drop
    `__pycache__/poll_prs.cpython-3XX.pyc` next to the source, which is a new
    file inside the tree `test_tools_and_integration.py` digests byte-for-byte
    — and that digest is captured when THAT module is imported, so this write
    only trips it when this file is collected later in the same session. It is
    gitignored, so `git status`, `git add -A` and `suite_write_guard` are all
    clean and the failure has no visible author.
    """
    spec = importlib.util.spec_from_file_location("poll_prs", str(_POLL_PRS))
    mod = importlib.util.module_from_spec(spec)
    pdir = str(_POLL_PRS.parent)
    if pdir not in sys.path:
        sys.path.insert(0, pdir)
    _no_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = _no_bytecode
    return mod


P = _load()


# ---------------------------------------------------------------------------
# THIS MODULE OWNS THE TRANSPORT IT MEASURES OVER.
#
# `poll()` chooses its transport at call time: `if prefer_gh and _have_gh()`,
# where `_have_gh` is `shutil.which("gh") is not None`. Eight tests below stub
# `_list_open_prs_gh` and then assert over what `poll`/`main` returns — an
# experiment that only takes place on a host that HAPPENS to have the gh CLI
# installed. On one that does not, the stub is never consulted, `poll` walks
# into the PAT branch and raises before a single enumeration rule is reached.
#
# MEASURED in the digest-pinned runtime image (`ghcr.io/vibeic/vibeic-eda@
# sha256:66c33ff2…`, where `command -v gh` finds nothing), on unmodified main:
#
#     7 failed, 6 passed
#     RuntimeError: no GitHub auth — install the `gh` CLI (preferred) or set
#         $GITHUB_TOKEN / $GH_TOKEN / ~/.config/github/token
#
# and 13 passed on a host with gh on PATH. Same tree, same commit; the variable
# was the harness. THE PROGRAM IS NOT THE DEFECT — `_have_gh` answering
# truthfully is the behaviour `test_rest_used_when_gh_unavailable` exists to
# pin, and making `poll` prefer a monkeypatched lister over its own probe would
# delete that. What was missing is this module declaring which transport its
# assertions are about.
#
# THE EIGHTH IS THE EXPENSIVE ONE. `test_rc2_io_error` asserts rc 2 and was
# GREEN in that image — for the wrong reason. Its stub was counted, driving the
# same program through the same `main(["--repo", "o/r"])` in both environments:
#
#     image (no gh)   _have_gh()=False  rc=2  stub_calls=0
#     host  (gh 2.4)  _have_gh()=True   rc=2  stub_calls=1
#
# Identical rc, opposite fact. In the image the 2 came from the missing-auth
# raise, so the one test that proves a lister failure maps to "retry next tick"
# was passing without ever calling the lister. A red that hides a vacuous green
# beside it is the usual shape; both are repaired by the same line.
#
# SCOPED and OVERRIDABLE. A function-scoped autouse `monkeypatch` pins the
# probe for THIS module only. The two tests that are ABOUT the absent-gh path
# (`test_rest_used_when_gh_unavailable`, `test_no_auth_raises`) set it back to
# False in their own bodies, which runs after this fixture and therefore wins —
# so the fallback path keeps being proved on every host, including one where gh
# really is installed.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _gh_cli_present(monkeypatch):
    monkeypatch.setattr(P, "_have_gh", lambda: True)


def _gh_pr(number, *, base="main", draft=False, mergeable="MERGEABLE",
           author="alice", labels=None, title="t"):
    """A PR record shaped like `gh pr list --json ...` output."""
    return {
        "number": number, "headRefName": f"h{number}", "baseRefName": base,
        "author": {"login": author}, "isDraft": draft, "mergeable": mergeable,
        "mergeStateStatus": "CLEAN" if mergeable == "MERGEABLE" else "DIRTY",
        "labels": [{"name": n} for n in (labels or [])],
        "title": title, "updatedAt": "2026-06-17T00:00:00Z",
        "url": f"https://example/{number}",
    }


# --------------------------------------------------------------------------
# Exit-code contract
# --------------------------------------------------------------------------
def test_program_file_exists():
    assert _POLL_PRS.is_file(), f"missing {_POLL_PRS}"


def test_rc0_no_open_prs(monkeypatch):
    monkeypatch.setattr(P, "_list_open_prs_gh", lambda repo, base: [])
    rc = P.main(["--repo", "o/r"])
    assert rc == 0


def test_rc1_one_actionable(monkeypatch):
    monkeypatch.setattr(P, "_list_open_prs_gh",
                        lambda repo, base: [_gh_pr(3)])
    rc = P.main(["--repo", "o/r"])
    assert rc == 1


def test_rc2_io_error(monkeypatch):
    def boom(repo, base):
        raise RuntimeError("gh pr list exited 1: no such repo")
    monkeypatch.setattr(P, "_list_open_prs_gh", boom)
    rc = P.main(["--repo", "o/r"])
    assert rc == 2


# --------------------------------------------------------------------------
# Enumeration rules
# --------------------------------------------------------------------------
def test_drafts_excluded(monkeypatch):
    monkeypatch.setattr(P, "_list_open_prs_gh", lambda repo, base: [
        _gh_pr(10, draft=False), _gh_pr(11, draft=True)])
    rep = P.poll(repo="o/r", base="main")
    nums = [e["number"] for e in rep["actionable"]]
    assert nums == [10]
    assert rep["skipped_drafts"] == 1
    assert rep["draft_numbers"] == [11]


def test_wrong_base_excluded(monkeypatch):
    monkeypatch.setattr(P, "_list_open_prs_gh", lambda repo, base: [
        _gh_pr(20, base="main"), _gh_pr(21, base="release-1.x")])
    rep = P.poll(repo="o/r", base="main")
    nums = [e["number"] for e in rep["actionable"]]
    assert nums == [20]


def test_newest_first(monkeypatch):
    monkeypatch.setattr(P, "_list_open_prs_gh", lambda repo, base: [
        _gh_pr(5), _gh_pr(42), _gh_pr(17)])
    rep = P.poll(repo="o/r", base="main")
    nums = [e["number"] for e in rep["actionable"]]
    assert nums == [42, 17, 5]


def test_conflicting_pr_is_still_actionable(monkeypatch):
    """§4.05 no-leak: a CONFLICTING PR must NOT be silently dropped — the
    gatekeeper still has to eject it back to the author."""
    monkeypatch.setattr(P, "_list_open_prs_gh", lambda repo, base: [
        _gh_pr(30, mergeable="CONFLICTING")])
    rep = P.poll(repo="o/r", base="main")
    assert [e["number"] for e in rep["actionable"]] == [30]
    assert rep["actionable"][0]["mergeable"] == "CONFLICTING"


def test_missing_base_fails_open(monkeypatch):
    """A PR whose base field is absent must NOT be dropped (fail open to the
    gatekeeper — never silently swallow a candidate on a missing field)."""
    pr = _gh_pr(40)
    pr.pop("baseRefName")
    monkeypatch.setattr(P, "_list_open_prs_gh", lambda repo, base: [pr])
    rep = P.poll(repo="o/r", base="main")
    assert [e["number"] for e in rep["actionable"]] == [40]


# --------------------------------------------------------------------------
# REST fallback path parity
# --------------------------------------------------------------------------
def test_rest_path_projects_into_gh_shape(monkeypatch):
    rest_raw = [{
        "number": 5, "head": {"ref": "h5"}, "base": {"ref": "main"},
        "user": {"login": "eve"}, "draft": False,
        "labels": [{"name": "x"}, {"name": "y"}],
        "title": "rest pr", "updated_at": "2026-06-17T00:00:00Z",
        "html_url": "https://h/5",
    }]
    monkeypatch.setattr(P, "_api_get", lambda url, tok: (200, rest_raw))
    rows = P._list_open_prs_rest("o/r", "main", "tok")
    r = rows[0]
    # The keys _to_entry + _is_actionable consume must all be present.
    for k in ("number", "headRefName", "baseRefName", "author",
              "isDraft", "labels", "title", "url"):
        assert k in r, k
    assert r["headRefName"] == "h5" and r["baseRefName"] == "main"
    assert r["author"]["login"] == "eve"
    e = P._to_entry(r)
    assert e["author"] == "eve" and e["labels"] == ["x", "y"]
    assert P._is_actionable(r, "main") is True


def test_rest_used_when_gh_unavailable(monkeypatch):
    """When gh is absent the poll must transparently fall back to REST."""
    monkeypatch.setattr(P, "_have_gh", lambda: False)
    called = {}

    def fake_rest(repo, base, tok):
        called["hit"] = True
        return [P._list_open_prs_gh.__doc__ and None] and []  # empty
    monkeypatch.setattr(P, "_load_pat", lambda: "fake-token")
    monkeypatch.setattr(P, "_list_open_prs_rest", fake_rest)
    rep = P.poll(repo="o/r", base="main", prefer_gh=True)
    assert called.get("hit") is True
    assert rep["actionable_count"] == 0


def test_no_auth_raises(monkeypatch):
    """No gh + no PAT must raise RuntimeError -> main() maps to rc=2."""
    monkeypatch.setattr(P, "_have_gh", lambda: False)
    monkeypatch.setattr(P, "_load_pat", lambda: None)
    with pytest.raises(RuntimeError):
        P.poll(repo="o/r", base="main", prefer_gh=True)


# --------------------------------------------------------------------------
# Field-set single-source guard (gh path & REST path cannot drift)
# --------------------------------------------------------------------------
def test_pr_fields_constant_covers_consumed_keys():
    """The gh `--json` field list must include every field the projection
    consumes, so the two paths cannot drift (Step-2.7 single-source rule)."""
    for needed in ("number", "headRefName", "baseRefName", "author",
                   "isDraft", "mergeable", "labels", "title", "url"):
        assert needed in P._PR_FIELDS, needed
