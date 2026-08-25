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
import re
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import org_duplicate_fork_check as D  # noqa: E402
import gh_enumerate_all as G  # noqa: E402


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


#: `_branch_fingerprint` now enumerates `refs/heads` through `gh_enumerate_all`
#: instead of reading one capped REST page, so the branch read no longer arrives
#: through `_gh`. This double serves that enumeration from the SAME `fps` table
#: every test below already installs on `_gh`: the tests keep one source of
#: truth, and none of them reaches GitHub. The enumerator's own completeness
#: contract — pagination to exhaustion, node count asserted against the
#: connection's declared totalCount — is pinned in `test_gh_enumerate_all.py`;
#: what is pinned HERE is what this program does with the result.
def _enumerate_from_the_installed_fake(owner, name, collection, *a, **kw):
    assert collection == "refs/heads", collection
    rc, out, _ = D._gh(["api", f"repos/{owner}/{name}/branches?per_page=100",
                        "--jq", "fingerprint"], timeout=60)
    if rc != 0:
        return {"error": f"{owner}/{name}: listing failed"}
    nodes = []
    for token in (out or "").split():
        branch, _, sha = token.partition("@")
        nodes.append({"name": branch, "target": {"oid": sha}})
    return {"owner": owner, "repo": name, "collection": collection,
            "count": len(nodes), "declared_total": len(nodes), "nodes": nodes}


@pytest.fixture(autouse=True)
def _no_test_here_reaches_github(monkeypatch):
    """`D._gh` is resolved at CALL time, so this fixture does not care whether
    the test installs its fake before or after."""
    monkeypatch.setattr(D, "_enumerate_all", _enumerate_from_the_installed_fake)


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


# ── #619 — an empty listing is not a clean org ─────────────────────────────
#
# `gh repo list <owner>` exits 0 with `[]` for an owner that does not exist, so
# every one of these arrived as `rows == []` and left as `[OK] ... rc 0`. The
# two registry-wide meta-checks flagged this file for exactly that.


def test_zero_repositories_listed_is_not_a_clean_org(monkeypatch, capsys):
    """THE LOAD-BEARING CASE, and the one a name-shape check cannot reach:
    `vibeic-typo-xyz` is a perfectly well-formed owner name that does not
    exist. Measured against the real CLI on 2026-08-01:

        $ gh repo list vibeic-typo-xyz --limit 3 --json name,isFork
        []
        rc=0

    Before this change that read `[OK] no upstream in vibeic-typo-xyz is forked
    more than once.` — a monitoring run pointed at a misspelled org reporting
    the account clean forever, which is the precise failure this program was
    written to prevent."""
    monkeypatch.setattr(D, "_gh", _fake_gh([], {}))
    rc = D.main(["vibeic-typo-xyz"])
    err = capsys.readouterr().err
    assert rc == D.RC_CANNOT_CHECK, "an org that was never read reported clean"
    assert "[OK]" not in err
    assert "0 repositories" in err
    # The three causes, because "clean" sends a reader nowhere.
    assert "spelled right" in err and "read:org" in err


def test_a_path_where_an_org_belongs_is_refused_without_a_network_call(
        monkeypatch, capsys):
    """How this file became the shape it audits: the registry-wide fixtures
    drive every gate with a PROJECT PATH as argument one. `.` and an absent
    path are not owner names, and both used to come back `[OK]`."""
    def _no_gh(args, timeout=None):       # pragma: no cover - must not be hit
        raise AssertionError("the network was called for a non-owner argument")
    monkeypatch.setattr(D, "_gh", _no_gh)
    for bad in (".", "/nonexistent/vibeic-absent-project-fixture/no-such-project",
                "vibeic/vibe-ic", "trailing-", "under_score", ""):
        assert D.main([bad]) == D.RC_CANNOT_CHECK, f"{bad!r} was accepted"
    err = capsys.readouterr().err
    assert "not a GitHub owner name" in err
    # `-leading` never reaches main() (argparse claims it as a flag), so the
    # rule itself is exercised where it lives.
    assert "error" in D.find_duplicates("-leading")


def test_an_org_with_no_forks_is_an_honest_zero_and_says_so(monkeypatch, capsys):
    """The OTHER direction, and the reason the fix is not "refuse every zero":
    an org whose repositories really were read and contained no forks is clean.
    rc 0 is correct — but it has to publish the number it is clean over."""
    repos = [{"name": f"own{i}", "isFork": False} for i in range(7)]
    monkeypatch.setattr(D, "_gh", _fake_gh(repos, {}))
    rc = D.main(["vibeic"])
    err = capsys.readouterr().err
    assert rc == D.RC_CLEAN, "a real org with no forks must not be refused"
    assert "[OK]" in err
    assert "7 repositories listed" in err, \
        "the honest zero published no denominator"


def test_every_rc0_line_carries_its_denominator(monkeypatch, capsys):
    """The disclosure the meta-checks require: no rc-0 verdict from this gate
    may state the FINDING without the POPULATION it was found over.

    16 forks among 20 repositories, so the two halves of the denominator are
    DIFFERENT numbers and the line has to carry both — a scan size is not a
    hit count, which is the distinction `_gate_denominator` exists to keep."""
    repos = [_fork(f"tool{i}", f"up{i}/tool{i}") for i in range(16)]
    repos += [{"name": f"own{i}", "isFork": False} for i in range(4)]
    fps = {}
    for i in range(16):
        fps[f"up{i}/tool{i}"] = f"m@{i}"
        fps[f"vibeic/tool{i}"] = f"m@{i}"
    monkeypatch.setattr(D, "_gh", _fake_gh(repos, fps))
    assert D.main(["vibeic"]) == D.RC_CLEAN
    err = capsys.readouterr().err
    assert "examined 16 fork" in err, err
    assert "of 20 considered" in err, err


def test_the_denominator_is_machine_readable_too(monkeypatch, tmp_path):
    """A human line a machine cannot parse is half a disclosure."""
    repos = [_fork("sv-elab"), _fork("sv-elab-1"),
             {"name": "own", "isFork": False}]
    fps = {"povik/sv-elab": _UP_FP, "vibeic/sv-elab": _UP_FP,
           "vibeic/sv-elab-1": _UP_FP}
    monkeypatch.setattr(D, "_gh", _fake_gh(repos, fps))
    out = tmp_path / "forks.json"
    D.main(["vibeic", "--json", str(out)])
    rep = json.loads(out.read_text())
    den = rep["denominator"]
    assert den["examined"] == 2, den          # two forks grouped
    assert den["considered"] == 3, den        # three repositories listed
    assert den["details"]["repositories_listed"] == 3
    assert den["details"]["distinct_upstreams"] == 1


def test_the_guard_is_what_produces_the_refusal(monkeypatch, capsys):
    """NEGATIVE CONTROL — a test that cannot fail against the pre-fix code
    proves nothing, so this reconstructs the pre-fix path and asserts the
    DEFECT REPRODUCES. It is the control for
    `test_zero_repositories_listed_is_not_a_clean_org` directly above: without
    the zero-rows guard, the same input this suite now refuses comes back
    `[OK] ... rc 0`.

    If this ever stops reproducing, the guard above stopped being the thing
    doing the work and both tests need re-deriving."""
    monkeypatch.setattr(D, "_gh", _fake_gh([], {}))
    monkeypatch.setattr(D, "_ORG_NAME", re.compile(r"^.*$"))  # guard 1 off
    original = D.find_duplicates

    def without_the_zero_rows_guard(org, limit=D.DEFAULT_REPO_LIMIT):
        res = original(org, limit)
        if "error" in res and "0 repositories" in res["error"]:
            # Exactly what the function returned before this change.
            return {"org": org, "groups": [],
                    "forks_with_unreadable_parent": [],
                    "denominator": {"unit": "fork", "examined": 0,
                                    "considered": 0,
                                    "not_applicable_reason": "n/a"}}
        return res

    monkeypatch.setattr(D, "find_duplicates", without_the_zero_rows_guard)
    rc = D.main(["vibeic-typo-xyz"])
    assert rc == D.RC_CLEAN, \
        "the pre-fix path no longer reproduces the defect; this control is dead"
    assert "[OK]" in capsys.readouterr().err


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ---------------------------------------------------------------------------
# the branch listing is an ENUMERATION
# ---------------------------------------------------------------------------
def _refs_pages(sha_past_the_cap, total=150):
    """A 150-branch repository served two pages deep, the way GitHub serves it.

    The first 100 are identical across both repositories; the difference lives
    past branch 100, which is precisely where a single `per_page=100` page
    stops looking.
    """
    def fake(query, timeout=120):
        first_page = "after:null" in query
        lo, hi = (0, 100) if first_page else (100, total)
        nodes = [{"name": f"b{i:03d}",
                  "target": {"oid": sha_past_the_cap if i >= 100
                             else f"sha{i:03d}"}}
                 for i in range(lo, hi)]
        return {"data": {"repository": {"refs": {
            "totalCount": total,
            "pageInfo": {"hasNextPage": first_page, "endCursor": "c0"},
            "nodes": nodes}}}}, ""
    return fake


def test_a_difference_past_the_hundredth_branch_is_seen(monkeypatch):
    """THE defect this read used to carry. One REST page of 100 made two forks
    that differ at branch 101 fingerprint IDENTICALLY, and an identical
    fingerprint is what this program calls `empty` — safe to delete.
    """
    monkeypatch.setattr(D, "_enumerate_all", G.enumerate_all)

    monkeypatch.setattr(G, "_gh_graphql", _refs_pages("aaaaaaa"))
    upstream = D._branch_fingerprint("povik/sv-elab")
    monkeypatch.setattr(G, "_gh_graphql", _refs_pages("bbbbbbb"))
    fork = D._branch_fingerprint("vibeic/sv-elab-1")

    assert len(upstream.split()) == 150, "the collection was not enumerated"
    assert upstream.split()[:100] == fork.split()[:100], (
        "the fixture must be indistinguishable inside the old cap, or this "
        "test is not about the cap")
    assert upstream != fork, (
        "a fork carrying work past branch 100 read as byte-identical to its "
        "upstream, which is the recommendation to delete real work")


def test_a_short_read_is_UNREADABLE_and_never_a_smaller_repository(monkeypatch):
    """`None` is the third state. A listing whose node count disagrees with the
    connection's declared total is an error, and an error must not arrive here
    as a fork with fewer branches — that fork would compare unequal and be
    reported as carrying work, or, worse, equal to another short read."""
    monkeypatch.setattr(D, "_enumerate_all", G.enumerate_all)

    def truncated(query, timeout=120):
        return {"data": {"repository": {"refs": {
            "totalCount": 150,
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [{"name": "b000", "target": {"oid": "sha000"}}]}}}}, ""

    monkeypatch.setattr(G, "_gh_graphql", truncated)
    assert D._branch_fingerprint("vibeic/sv-elab-1") is None
