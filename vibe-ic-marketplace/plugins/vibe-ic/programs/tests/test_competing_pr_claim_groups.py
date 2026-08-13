#!/usr/bin/env python3
"""vibe-ic#1411 — grouping open PRs by the ISSUE they claim.

Every test here is offline. The module's whole point is that its rules are pure
functions over plain dicts, so a checker about competing PRs is itself exercised
without a network — the alternative is logic that only ever runs against the
live API and is therefore never tested.

The load-bearing cases are the NEGATIVE ones: a rule that reported every group
as invisible would "find" all 22 and be useless, so each test below pins a way
of being wrong, not just the happy path.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import competing_pr_claim_groups as G  # noqa: E402


def _pr(number, files, body="", title=""):
    return {"number": number, "title": title, "body": body, "files": files}


# --------------------------------------------------------------------------
# claim parsing
# --------------------------------------------------------------------------
def test_body_keywords_and_title_convention_are_both_claims():
    assert G.claimed_issues("", "Closes #1080") == frozenset({1080})
    assert G.claimed_issues("", "fixes #12\nAdvances #34") == frozenset({12, 34})
    # The repo's title convention, which a body-only parser would miss.
    assert G.claimed_issues("d3: re-emit the ledger (#1300)", "") == \
        frozenset({1300})


def test_refs_counts_as_a_claim():
    """#1407 says `Refs #1403` BECAUSE it fixes part of an issue. A partial fix
    competing with another partial fix is exactly what this must surface, so
    dropping `Refs` would blind the tool to the case it was built for."""
    assert G.claimed_issues("", "Refs #1403") == frozenset({1403})


def test_a_bare_number_is_not_a_claim():
    """The negative control. Issue numbers appear constantly in prose — '#1363'
    as a citation is not a claim to fix it, and a parser that took every `#N`
    would group nearly every PR with nearly every other."""
    assert G.claimed_issues("", "same class as #1363, measured there") == \
        frozenset()
    assert G.claimed_issues("", "see #999 for context") == frozenset()


# --------------------------------------------------------------------------
# grouping
# --------------------------------------------------------------------------
def test_only_issues_with_more_than_one_pr_are_groups():
    prs = [_pr(1, ["a.py"], "Closes #10"), _pr(2, ["b.py"], "Closes #11")]
    assert G.group_by_claim(prs) == {}


def test_a_pr_claiming_two_issues_competes_in_both():
    prs = [_pr(1, ["a.py"], "Closes #10\nCloses #11"),
           _pr(2, ["b.py"], "Closes #10"),
           _pr(3, ["c.py"], "Closes #11")]
    groups = G.group_by_claim(prs)
    assert set(groups) == {10, 11}
    assert {m["number"] for m in groups[10]} == {1, 2}
    assert {m["number"] for m in groups[11]} == {1, 3}


# --------------------------------------------------------------------------
# visibility to the conflict mechanism
# --------------------------------------------------------------------------
def test_a_group_sharing_a_file_is_visible_and_not_reported():
    """The NEGATIVE half: git already surfaces these, so reporting them would
    bury the ones only this tool can find."""
    prs = [_pr(1, ["x.py"], "Closes #10"), _pr(2, ["x.py"], "Closes #10")]
    assert G.shares_a_file(prs) is True
    assert G.invisible_groups(prs) == []


def test_a_group_sharing_no_file_is_reported():
    prs = [_pr(1, ["x.py"], "Closes #10"), _pr(2, ["y.py"], "Closes #10")]
    assert G.shares_a_file(prs) is False
    assert [i for i, _ in G.invisible_groups(prs)] == [10]


def test_overlap_is_pairwise_not_a_global_intersection():
    """Three PRs where two collide and a third is disjoint IS visible — git
    reports the colliding pair. A global intersection would be empty here and
    would wrongly call the group invisible, hiding it behind a conflict that
    does exist."""
    prs = [_pr(1, ["x.py"], "Closes #10"),
           _pr(2, ["x.py"], "Closes #10"),
           _pr(3, ["z.py"], "Closes #10")]
    assert G.shares_a_file(prs) is True
    assert G.invisible_groups(prs) == []


def test_sharing_only_the_generated_index_does_not_count_as_sharing():
    """~27 open PRs touch `programs/INDEX.md` and it is generated (#1363), so
    counting it would report unrelated PRs as colliding and erase the signal."""
    idx = "vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md"
    prs = [_pr(1, [idx, "x.py"], "Closes #10"),
           _pr(2, [idx, "y.py"], "Closes #10")]
    assert G.shares_a_file(prs) is False
    assert [i for i, _ in G.invisible_groups(prs)] == [10]
    # ...but a real shared file still counts even alongside the index.
    prs2 = [_pr(1, [idx, "x.py"], "Closes #10"),
            _pr(2, [idx, "x.py"], "Closes #10")]
    assert G.shares_a_file(prs2) is True


def test_the_1080_case_shows_the_PAIR_is_the_right_unit():
    """Measured 2026-08-13, and it is why this reports pairs, not groups.

    #1080's group is #1122/#1150/#1205. The confirmed duplicate is
    #1150 x #1205, which share NO file. But #1122 x #1205 share
    `programs/step_metrics.py`, so the GROUP collides — a group-level report
    calls #1080 visible and loses the duplicate pair inside it.

    Six of the sixteen groups #1411 counted as invisible are of exactly this
    shape: empty global intersection, but a colliding pair.
    """
    prs = [_pr(1122, ["programs/step_metrics.py"], "Advances #1080"),
           _pr(1150, ["programs/run_metrics.py"], "Closes #1080"),
           _pr(1205, ["programs/step_metrics.py",
                      "programs/step_metrics_emit.py"], "Closes #1080")]
    # The group collides, so a group-level rule reports nothing...
    assert G.shares_a_file(prs) is True
    assert G.invisible_groups(prs) == []
    # ...while the duplicate pair is still invisible, and pairs find it.
    assert (1080, 1150, 1205) in G.invisible_pairs(prs)
    # The colliding pair must NOT be reported — git already surfaces it.
    assert (1080, 1122, 1205) not in G.invisible_pairs(prs)


def test_cli_reads_a_json_file_and_needs_no_network(tmp_path, capsys):
    import json
    p = tmp_path / "prs.json"
    p.write_text(json.dumps([
        _pr(1, ["x.py"], "Closes #10"), _pr(2, ["y.py"], "Closes #10")]))
    assert G.main(["--prs-json", str(p)]) == 0
    out = capsys.readouterr().out
    assert "issues with >1 open PR                    1" in out
    assert "#10" in out
    # It must not present itself as a verdict.
    assert "NOT 'duplicate'" in out
