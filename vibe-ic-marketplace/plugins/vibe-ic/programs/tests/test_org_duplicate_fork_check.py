#!/usr/bin/env python3
"""vibe-ic — the org-hygiene check whose absence cost the account its visibility.

25 forks of one upstream appeared in six minutes on 2026-07-28, all empty, all
from a retried non-idempotent `gh repo fork`. Two days later the account was
flagged and the org's issues and PRs left the search index.

The three properties that make this check safe to act on are the three tested
here, because each one, wrong, causes a distinct kind of damage:

* Reporting a fork that carries work as removable would delete real fixes.
* Reporting an unreadable fork as empty would delete work we merely could not
  see — worse, because it looks identical to the safe case.
* Reporting a legitimately-named `foo-2` as a retry artifact would train the
  reader to ignore the signal.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import org_duplicate_fork_check as D  # noqa: E402


_UP_FP = "master@3dddccd47861 dev@aaaa1111"


def _fake_gh(repos, fps, list_rc=0):
    """`repos` is the repo-list payload; `fps` maps full-name → fingerprint.

    A name absent from `fps` answers rc 1 — the unreadable case, which must stay
    distinguishable from an empty string.
    """
    def gh(args, timeout=None):
        if args[:2] == ["repo", "list"]:
            return list_rc, json.dumps(repos), "" if not list_rc else "boom"
        if args[0] == "api":
            full = args[1].split("repos/", 1)[1].split("/branches")[0]
            if full not in fps:
                return 1, "", "not found"
            return 0, fps[full], ""
        raise AssertionError(f"unexpected gh call: {args}")
    return gh


def _fork(name, upstream="povik/sv-elab"):
    owner, repo = upstream.split("/")
    return {"name": name, "isFork": True,
            "parent": {"name": repo, "owner": {"login": owner}}}


def test_the_incident_is_detected_and_the_empties_named(monkeypatch, capsys):
    """The 2026-07-28 shape, in miniature: one real fork, three empty retries."""
    repos = [_fork("sv-elab"), _fork("sv-elab-1"), _fork("sv-elab-2"),
             _fork("sv-elab-3")]
    fps = {"povik/sv-elab": _UP_FP, "vibeic/sv-elab": _UP_FP,
           "vibeic/sv-elab-1": _UP_FP, "vibeic/sv-elab-2": _UP_FP,
           "vibeic/sv-elab-3": _UP_FP}
    monkeypatch.setattr(D, "_gh", _fake_gh(repos, fps))
    rc = D.main(["vibeic"])
    err = capsys.readouterr().err
    assert rc == D.RC_DUPLICATES
    assert "forked 4 times" in err
    assert "numbered suffix" in err, "the retry fingerprint went unreported"
    assert "removable" in err


def test_a_fork_carrying_work_is_never_called_removable(monkeypatch, capsys):
    """The expensive direction. A fork with one commit of its own holds a fix
    that exists nowhere else."""
    repos = [_fork("sv-elab"), _fork("sv-elab-1")]
    fps = {"povik/sv-elab": _UP_FP,
           "vibeic/sv-elab": "master@dddd4444 dev@aaaa1111",  # ahead
           "vibeic/sv-elab-1": _UP_FP}
    monkeypatch.setattr(D, "_gh", _fake_gh(repos, fps))
    D.main(["vibeic"])
    err = capsys.readouterr().err
    assert "RECONCILED, not deleted" in err
    assert "Keeping sv-elab," in err, \
        "the fork carrying work was not the one kept"


def test_an_unreadable_fork_is_not_reported_as_empty(monkeypatch, capsys):
    """A fork we could not read looks exactly like a fork with nothing in it.
    Collapsing the two is how the safe-looking case deletes real work."""
    repos = [_fork("sv-elab"), _fork("sv-elab-1")]
    fps = {"povik/sv-elab": _UP_FP, "vibeic/sv-elab": _UP_FP}  # -1 unreadable
    monkeypatch.setattr(D, "_gh", _fake_gh(repos, fps))
    D.main(["vibeic"])
    err = capsys.readouterr().err
    assert "UNKNOWN" in err
    assert "sv-elab-1" not in err.split("byte-identical")[-1], \
        "an unreadable fork was listed among the removable ones"


def test_a_numbered_name_without_its_sibling_is_not_a_retry(monkeypatch, capsys):
    """`sv-elab-2` alone is somebody's project, not a retry artifact."""
    repos = [_fork("sv-elab-2"), _fork("other", "a/b")]
    fps = {"povik/sv-elab": _UP_FP, "vibeic/sv-elab-2": _UP_FP,
           "a/b": "m@1", "vibeic/other": "m@1"}
    monkeypatch.setattr(D, "_gh", _fake_gh(repos, fps))
    rc = D.main(["vibeic"])
    assert rc == D.RC_CLEAN, "a single fork per upstream was flagged"
    assert "numbered suffix" not in capsys.readouterr().err


def test_distinct_upstreams_forked_once_each_are_clean(monkeypatch, capsys):
    """The state this org should be in, and the reason the check must not fire
    on legitimate forking: 16 upstreams, one fork each."""
    repos = [_fork(f"tool{i}", f"up{i}/tool{i}") for i in range(16)]
    fps = {}
    for i in range(16):
        fps[f"up{i}/tool{i}"] = f"m@{i}"
        fps[f"vibeic/tool{i}"] = f"m@{i}"
    monkeypatch.setattr(D, "_gh", _fake_gh(repos, fps))
    assert D.main(["vibeic"]) == D.RC_CLEAN
    assert "[OK]" in capsys.readouterr().err


def test_a_truncated_listing_is_not_a_clean_org(monkeypatch, capsys):
    monkeypatch.setattr(D, "_gh", _fake_gh([_fork("x")], {}))
    rc = D.main(["vibeic", "--repo-limit", "1"])
    assert rc == D.RC_CANNOT_CHECK
    assert "NOT 'no duplicates'" in capsys.readouterr().err


def test_a_fork_with_no_readable_parent_blocks_the_verdict(monkeypatch, capsys):
    """It cannot be grouped, so a duplicate it belongs to would go unseen."""
    repos = [{"name": "orphan", "isFork": True, "parent": None}]
    monkeypatch.setattr(D, "_gh", _fake_gh(repos, {}))
    assert D.main(["vibeic"]) == D.RC_CANNOT_CHECK
    assert "no readable parent" in capsys.readouterr().err


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
