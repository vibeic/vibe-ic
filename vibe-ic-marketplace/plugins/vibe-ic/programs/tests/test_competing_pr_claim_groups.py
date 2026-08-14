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


# --------------------------------------------------------------------------
# region 3 — same FILE, no conflict, no shared claim (vibe-ic#1413 review)
#
# Measured on this program's own branch: of eight PRs in four hand-found
# competing groups, SIX claim no issue, so claim-grouping had nothing to group
# them by. These pin the extension that covers them.
# --------------------------------------------------------------------------
def _pra(number, files, body="", title="", added=None):
    pr = _pr(number, files, body, title)
    if added is not None:
        pr["added"] = added
    return pr


def test_two_unclaimed_prs_sharing_a_file_are_reported():
    """The six-of-eight case: no claim anywhere, so only the path can group."""
    prs = [_pra(1, ["programs/a.py"]), _pra(2, ["programs/a.py"])]
    assert [(a, b) for a, b, _, _ in G.path_overlap_pairs(prs)] == [(1, 2)]


def test_unclaimed_prs_sharing_NOTHING_are_not_reported():
    """The paired guard for the test above. A rule that reported every pair
    would 'find' all 19110 pairs in the queue and be worthless."""
    prs = [_pra(1, ["programs/a.py"]), _pra(2, ["programs/b.py"])]
    assert G.path_overlap_pairs(prs) == []


def test_a_shared_claim_is_left_to_the_claim_report():
    """Not because it matters less — `invisible_pairs` already has it, and a
    reviewer reading both lists wants them disjoint."""
    prs = [_pra(1, ["programs/a.py"], body="Closes #9"),
           _pra(2, ["programs/a.py"], body="Closes #9")]
    assert G.path_overlap_pairs(prs) == []
    # ...and it is genuinely reported by the other list, not merely dropped.
    assert [(a, b) for _, a, b in G.invisible_pairs(prs)] == []  # they collide
    assert G.shares_a_file(prs) is True


def test_pairs_are_ranked_by_how_much_they_overlap():
    """An identical file set must outrank a one-file brush, because the output
    is read top-down and truncated wherever the reader loses interest."""
    prs = [_pra(1, ["p/a.py", "p/b.py"]),
           _pra(2, ["p/a.py", "p/b.py"]),          # identical -> 100%
           _pra(3, ["p/a.py"] + [f"p/x{i}.py" for i in range(8)])]
    ranked = G.path_overlap_pairs(prs)
    assert (ranked[0][0], ranked[0][1]) == (1, 2)
    assert ranked[0][2] == 1.0
    assert ranked[0][2] > ranked[-1][2]


def test_the_hot_floor_drops_the_generated_index_but_keeps_the_flow_yaml():
    """Measured on the 196-PR queue of 2026-08-14: INDEX.md 27 PRs,
    repo_hygiene_gates.sh 14, flow yaml 9. The floor must sit ABOVE 9 — the
    flow yaml's nine include #1239/#1258, a real competing pair this program
    exists to surface, so swallowing it would defeat the extension."""
    assert G.default_hot_floor(196) == 10
    assert G.default_hot_floor(196) > 9
    # tiny queues must not end up with a floor of 0, which would hide everything
    assert G.default_hot_floor(1) == 5

    prs = [_pra(i, ["shared/hot.py", f"p/own{i}.py"]) for i in range(12)]
    assert "shared/hot.py" in G.hot_paths(prs, floor=10)
    assert G.path_overlap_pairs(prs, floor=10) == []
    # paired guard: below the floor the SAME file is signal again
    assert G.path_overlap_pairs(prs, floor=99) != []


# --------------------------------------------------------------------------
# add/add — the one output here that is a fact, not advice
# --------------------------------------------------------------------------
def test_two_prs_creating_the_same_path_cannot_both_land():
    """Measured 2026-08-14: four such pairs among 196 open PRs, every one
    reporting MERGEABLE on BOTH sides, because that flag compares a PR to main
    and never to its batch-mates. #1066/#1336 was one; it was closed that
    afternoon on exactly this evidence."""
    prs = [_pra(1066, ["p/probe.py"], added=["p/probe.py"]),
           _pra(1336, ["p/probe.py"], added=["p/probe.py"])]
    assert G.add_add_pairs(prs) == [(1066, 1336, ["p/probe.py"])]


def test_editing_a_file_both_prs_did_not_create_is_not_an_add_add():
    """The paired guard. Two PRs modifying one existing file usually merge, so
    calling that un-landable would be a false certainty in the only output of
    this program that carries a verdict."""
    prs = [_pra(1, ["p/existing.py"], added=[]),
           _pra(2, ["p/existing.py"], added=[])]
    assert G.add_add_pairs(prs) == []
    # it is still surfaced by the softer report, which is the correct home
    assert [(a, b) for a, b, _, _ in G.path_overlap_pairs(prs)] == [(1, 2)]


def test_a_pr_without_changeType_is_silent_rather_than_guessed():
    """If `added` is absent, treating every changed path as new would report
    the whole queue as un-landable. A silence is the honest failure here."""
    prs = [_pr(1, ["p/a.py"]), _pr(2, ["p/a.py"])]        # no `added` key
    assert G.add_add_pairs(prs) == []
    prs2 = [_pra(1, ["p/a.py"], added=["p/a.py"]), _pr(2, ["p/a.py"])]
    assert G.add_add_pairs(prs2) == []


def test_add_add_ignores_the_generated_index():
    """Every PR adding a program adds its INDEX.md row; that is bookkeeping and
    regenerates, so it must not be reported as an un-landable collision."""
    prs = [_pra(1, ["programs/INDEX.md"], added=["programs/INDEX.md"]),
           _pra(2, ["programs/INDEX.md"], added=["programs/INDEX.md"])]
    assert G.add_add_pairs(prs) == []


# --------------------------------------------------------------------------
# stacks are related, never competing
# --------------------------------------------------------------------------
def _stk(number, files, head, base, body="", title=""):
    pr = _pra(number, files, body, title)
    pr["headRefName"], pr["baseRefName"] = head, base
    return pr


def test_a_pr_built_on_another_is_a_stack_not_a_competitor():
    """#1262 targets #1247's branch, so it shares #1247's files BY
    CONSTRUCTION. The reviewer's top-ranked "duplicate" was exactly this."""
    prs = [_stk(1247, ["p/a.py"], "fix/alias-order", "main"),
           _stk(1262, ["p/a.py"], "fix/sta-alias", "fix/alias-order")]
    assert G.stacked(prs) == frozenset({(1247, 1262)})
    assert G.path_overlap_pairs(prs) == []


def test_stack_detection_is_transitive():
    """The queue chains three deep (#1257 <- #1328 <- #1465). Stopping at one
    hop would call the two ENDS of a chain competitors, which is the same false
    positive one link further out."""
    prs = [_stk(1257, ["p/a.py"], "b1", "main"),
           _stk(1328, ["p/a.py"], "b2", "b1"),
           _stk(1465, ["p/a.py"], "b3", "b2")]
    assert G.stacked(prs) == frozenset({(1257, 1328), (1328, 1465),
                                        (1257, 1465)})
    assert G.path_overlap_pairs(prs) == []


def test_two_branches_off_MAIN_sharing_a_file_are_still_competitors():
    """The paired guard. If the stack filter swallowed same-base pairs it would
    silence the whole report — every ordinary PR is based on main."""
    prs = [_stk(1, ["p/a.py"], "feat/x", "main"),
           _stk(2, ["p/a.py"], "feat/y", "main")]
    assert G.stacked(prs) == frozenset()
    assert [(a, b) for a, b, _, _ in G.path_overlap_pairs(prs)] == [(1, 2)]


# --------------------------------------------------------------------------
# a verdict must name the tree it was computed from (2026-08-14)
# --------------------------------------------------------------------------
def test_the_add_add_verdict_names_the_tip_it_was_computed_from(tmp_path, capsys):
    """A pair reported without its tips cannot be re-checked later.

    MEASURED on this queue: a branch moved between one analysis fetching it and
    that analysis finishing. The stale ref said the PR no longer created the
    file at all — the exact opposite of the truth — and the API's file list was
    the correct one. By the time anyone reads a verdict, the tips have moved, so
    the verdict has to carry them or it is unfalsifiable.
    """
    import json
    prs = [{"number": 11, "title": "a", "body": "", "files": ["p/x.py"],
            "added": ["p/x.py"], "headRefOid": "aaaaaaaaaaaa1111"},
           {"number": 22, "title": "b", "body": "", "files": ["p/x.py"],
            "added": ["p/x.py"], "headRefOid": "bbbbbbbbbbbb2222"}]
    f = tmp_path / "prs.json"
    f.write_text(json.dumps(prs))
    G.main(["--prs-json", str(f)])
    out = capsys.readouterr().out
    assert "#11 x #22" in out, out
    # the SHORT tips, both of them, on the line that follows the pair
    assert "aaaaaaaaa" in out and "bbbbbbbbb" in out, (
        "the add/add verdict does not name the tips it was computed from, so a "
        f"reader cannot re-verify it against a branch that has since moved:\n{out}")


def test_a_pr_without_a_recorded_tip_is_shown_as_unknown_not_omitted(tmp_path, capsys):
    """PAIRED GUARD. Printing nothing when the tip is absent would read as
    'no tip needed' rather than 'tip unknown', which is the silent-omission
    shape this repo removes elsewhere."""
    import json
    prs = [{"number": 11, "title": "a", "body": "", "files": ["p/x.py"],
            "added": ["p/x.py"]},                      # no headRefOid
           {"number": 22, "title": "b", "body": "", "files": ["p/x.py"],
            "added": ["p/x.py"]}]
    f = tmp_path / "prs.json"
    f.write_text(json.dumps(prs))
    G.main(["--prs-json", str(f)])
    out = capsys.readouterr().out
    assert "#11 x #22" in out, out
    assert "#11@?" in out and "#22@?" in out, (
        f"an absent tip must be shown as unknown, not omitted:\n{out}")
