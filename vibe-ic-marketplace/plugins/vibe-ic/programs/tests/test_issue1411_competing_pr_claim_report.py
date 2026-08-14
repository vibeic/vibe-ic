#!/usr/bin/env python3
"""Tests for competing_pr_claim_report.py — vibe-ic#1411.

THE PROPERTY UNDER TEST, in one sentence: **a group whose members share no
file is reported anyway.** That is the whole point — merge conflict already
surfaces the groups that DO share a file, and 16 of 22 groups measured on the
repo shared none, so the conflict-based mechanism could not see them.

So the mutant that must die is not "the program is absent" (that only produces
a collection error, which proves nothing about the logic). It is the program
with the OLD behaviour restored:

    if classify(members, discount) == SHARED:   # report only what git sees
        out.append(...)

Under that mutant every test named ``*_no_file*``/``*_invisible*`` here must
fail. The run is recorded in the PR body; the tests are written so it can be
repeated.

Bounds: every subprocess here is capped at 30 s, under the 60 s ceiling
`ci_harness_timeout_ceiling_check` enforces for a harness running pytest at
`--timeout=180 --timeout-method=thread`.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from _hostpaths import require_repo

_HERE = Path(__file__).resolve().parent
_PROG = _HERE.parent / "competing_pr_claim_report.py"

_spec = importlib.util.spec_from_file_location("competing_pr_claim_report", _PROG)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

#: Under the harness ceiling (60 s). See the module docstring.
_TIMEOUT_S = 30

# The PR-number namespace used by the synthesised records below is deliberately
# far from any real issue number in this repo, so a synthetic record can never
# be mistaken for a captured one when a failure is read.
_A, _B, _C = 90001, 90002, 90003
_ISSUE = 90100


def _pr(number, body="", title="", files=("f.py",)):
    """A `gh pr list --json number,title,body,files` record.

    `files=None` omits the key entirely — the UNDETERMINED input.
    """
    rec = {"number": number, "title": title, "body": body}
    if files is not None:
        rec["files"] = [{"path": f} for f in files]
    return rec


def _run(*args, stdin=None):
    proc = subprocess.run(
        [sys.executable, str(_PROG), *args],
        input=stdin, capture_output=True, text=True, timeout=_TIMEOUT_S)
    return proc.returncode, proc.stdout + proc.stderr


# ----------------------------------------------------------------------
# THE DEFECT: a group that cannot collide is still a group
# ----------------------------------------------------------------------
def test_a_group_sharing_no_file_is_reported():
    """The mutant killer. Two PRs, one issue, disjoint file lists."""
    groups = mod.group_by_claim(mod.claimants_from_prs([
        _pr(_A, body="Closes #%d." % _ISSUE, files=("a/one.py",)),
        _pr(_B, body="Closes #%d." % _ISSUE, files=("b/two.py",)),
    ]))
    assert [g[0] for g in groups] == [_ISSUE]
    assert groups[0][2] == mod.NO_SHARED_FILE
    assert {m.ident for m in groups[0][1]} == {"PR #%d" % _A, "PR #%d" % _B}


def test_a_group_sharing_a_file_is_reported_too():
    """The conflict-visible groups are NOT filtered out — the report is about
    the claim, and whether git can see it is an attribute, not a filter."""
    groups = mod.group_by_claim(mod.claimants_from_prs([
        _pr(_A, body="Closes #%d." % _ISSUE, files=("same.py", "a.py")),
        _pr(_B, body="Fixes #%d." % _ISSUE, files=("same.py", "b.py")),
    ]))
    assert [(g[0], g[2]) for g in groups] == [(_ISSUE, mod.SHARED)]


def test_one_claimant_is_not_a_competing_claim():
    assert mod.group_by_claim(mod.claimants_from_prs([
        _pr(_A, body="Closes #%d." % _ISSUE),
    ])) == []


def test_two_claimants_of_different_issues_are_not_a_group():
    assert mod.group_by_claim(mod.claimants_from_prs([
        _pr(_A, body="Closes #%d." % _ISSUE),
        _pr(_B, body="Closes #%d." % (_ISSUE + 1)),
    ])) == []


# ----------------------------------------------------------------------
# the discount — why INDEX.md cannot count as a shared file
# ----------------------------------------------------------------------
def test_a_discounted_basename_alone_does_not_make_a_group_visible():
    """`INDEX.md` is generated from every program's docstring, so every new
    program touches it. Counting it would classify almost every group as
    SHARED — reading collision as meaning, which is the defect. #1363."""
    members = mod.claimants_from_prs([
        _pr(_A, files=("vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md",
                       "a/one.py")),
        _pr(_B, files=("vibe-ic-marketplace/plugins/vibe-ic/programs/INDEX.md",
                       "b/two.py")),
    ])
    assert mod.classify(members) == mod.NO_SHARED_FILE
    # ...and with NOTHING discounted the same pair reads as SHARED, which is
    # the state the report would be in if the discount were dropped.
    assert mod.classify(members, discount=()) == mod.SHARED


def test_the_discount_is_by_basename_not_by_path():
    members = mod.claimants_from_prs([
        _pr(_A, files=("one/dir/INDEX.md",)),
        _pr(_B, files=("another/dir/INDEX.md",)),
    ])
    assert mod.classify(members) == mod.NO_SHARED_FILE


# ----------------------------------------------------------------------
# degrading loudly: an unread file list is not an empty one
# ----------------------------------------------------------------------
def test_a_missing_file_list_is_undetermined_never_no_shared_file():
    """"Nobody looked" must not render as "they do not overlap"."""
    groups = mod.group_by_claim(mod.claimants_from_prs([
        _pr(_A, body="Closes #%d." % _ISSUE, files=None),
        _pr(_B, body="Closes #%d." % _ISSUE, files=("b/two.py",)),
    ]))
    assert groups[0][2] == mod.UNDETERMINED


def test_an_explicitly_empty_file_list_is_a_measurement_not_a_gap():
    """`files: []` means gh looked and found none; that IS "no shared file"."""
    groups = mod.group_by_claim(mod.claimants_from_prs([
        _pr(_A, body="Closes #%d." % _ISSUE, files=()),
        _pr(_B, body="Closes #%d." % _ISSUE, files=("b/two.py",)),
    ]))
    assert groups[0][2] == mod.NO_SHARED_FILE


def test_undetermined_does_not_erase_a_demonstrated_overlap():
    """Two known members that DO overlap stay SHARED even if a third member's
    files were never supplied — an absence cannot unmake a fact."""
    groups = mod.group_by_claim(mod.claimants_from_prs([
        _pr(_A, body="Closes #%d." % _ISSUE, files=("same.py",)),
        _pr(_B, body="Closes #%d." % _ISSUE, files=("same.py",)),
        _pr(_C, body="Closes #%d." % _ISSUE, files=None),
    ]))
    assert groups[0][2] == mod.SHARED


# ----------------------------------------------------------------------
# what counts as a claim
# ----------------------------------------------------------------------
@pytest.mark.parametrize("phrase", [
    "Closes #%d", "closes #%d", "Close #%d", "Closed #%d",
    "Fixes #%d", "fix #%d", "Fixed #%d",
    "Resolves #%d", "resolved #%d",
    "Advances #%d", "advances #%d",
])
def test_every_claiming_verb_is_a_claim(phrase):
    c = mod.Claimant("x", body=phrase % _ISSUE)
    assert mod.claims(c) == {_ISSUE}


def test_the_title_convention_is_a_claim():
    c = mod.Claimant("x", title="land: something specific (#%d)" % _ISSUE)
    assert mod.claims(c) == {_ISSUE}


def test_a_bare_reference_in_prose_is_not_a_claim():
    """"see #N" is a mention. Treating it as a claim would group every PR that
    cites a neighbouring issue and drown the report it is supposed to make
    readable."""
    c = mod.Claimant("x", body="Background: see #%d for the earlier attempt."
                               % _ISSUE)
    assert mod.claims(c) == set()


def test_a_claim_in_the_body_and_one_in_the_title_are_both_kept():
    c = mod.Claimant("x", title="subject (#%d)" % _ISSUE,
                     body="Advances #%d." % (_ISSUE + 7))
    assert mod.claims(c) == {_ISSUE, _ISSUE + 7}


# ----------------------------------------------------------------------
# CLI — the declared BLOCKING/ADVISORY split, proven by running it
# ----------------------------------------------------------------------
_COMPETING = json.dumps([
    _pr(_A, body="Closes #%d." % _ISSUE, files=("a/one.py",)),
    _pr(_B, body="Closes #%d." % _ISSUE, files=("b/two.py",)),
])


def test_report_mode_is_advisory_and_exits_zero():
    rc, out = _run("--prs-json", "-", stdin=_COMPETING)
    assert rc == 0, out
    assert "#%d" % _ISSUE in out
    assert mod.NO_SHARED_FILE in out


def test_fail_on_competing_actually_blocks():
    """Criterion 3 of flow-change-acceptance: a mode that claims to stop
    something is shown stopping it, not inferred from reading the code."""
    rc, out = _run("--prs-json", "-", "--fail-on-competing", stdin=_COMPETING)
    assert rc == 1, out


def test_fail_on_competing_passes_when_nothing_competes():
    rc, out = _run("--prs-json", "-", "--fail-on-competing",
                   stdin=json.dumps([_pr(_A, body="Closes #%d." % _ISSUE)]))
    assert rc == 0, out


def test_every_run_discloses_its_denominator():
    rc, out = _run("--prs-json", "-", stdin=_COMPETING)
    assert rc == 0, out
    assert "examined 2 claimant(s)" in out


#: The exact filter `report()` in `tools/gatekeeper-land.sh` applies to a
#: report's output before printing it into the landing log.
_LANDING_LOG_FILTER = re.compile(r"REPORT|VIOLATION|\[FAIL\]|\[SKIP\]")


def _survives_landing_log(out):
    return [ln for ln in out.splitlines() if _LANDING_LOG_FILTER.search(ln)]


def test_every_output_line_survives_the_landing_log_filter():
    """The wiring, tested rather than assumed.

    `gatekeeper-land.sh` greps a report's output for its own tokens before
    printing it. A group line without one would be dropped, leaving a count in
    the log with nothing named under it — a silent report wearing a loud one's
    clothes, which is the shape this whole change exists to remove.
    """
    rc, out = _run("--prs-json", "-", stdin=_COMPETING)
    assert rc == 0, out
    kept = _survives_landing_log(out)
    assert len(kept) == len(out.splitlines()), \
        "these lines would be dropped from the landing log: %s" % (
            [ln for ln in out.splitlines() if not _LANDING_LOG_FILTER.search(ln)])
    assert any("#%d" % _ISSUE in ln for ln in kept)


def test_a_refusal_also_survives_the_landing_log_filter():
    rc, out = _run("--prs-json", "-", stdin="[]")
    assert rc == 2
    assert _survives_landing_log(out), \
        "a NOT CHECKED line filtered out of the log is a silent refusal"


def test_zero_claimants_is_not_checked_not_a_clean_report():
    """An empty result is not a zero. rc 2, and the text says so."""
    rc, out = _run("--prs-json", "-", stdin="[]")
    assert rc == 2, out
    assert "NOT CHECKED" in out
    assert "0 claimant" in out


def test_zero_claimants_still_refuses_under_fail_on_competing():
    rc, _ = _run("--prs-json", "-", "--fail-on-competing", stdin="[]")
    assert rc == 2


def test_unreadable_input_is_not_checked():
    rc, out = _run("--prs-json", "-", stdin="{not json at all")
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_a_missing_input_file_is_not_checked(tmp_path):
    rc, out = _run("--prs-json", str(tmp_path / "absent.json"))
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_json_payload_records_the_verdict_and_the_denominator(tmp_path):
    out_json = tmp_path / "report.json"
    rc, _ = _run("--prs-json", "-", "--json", str(out_json), stdin=_COMPETING)
    assert rc == 0
    payload = json.loads(out_json.read_text())
    assert payload["examined"] == 2
    assert payload["groups"] == [{
        "issue": _ISSUE,
        "claimants": ["PR #%d" % _A, "PR #%d" % _B],
        "verdict": mod.NO_SHARED_FILE,
    }]


# ----------------------------------------------------------------------
# REAL ARTEFACTS — the two controls that were not authored for this change
# ----------------------------------------------------------------------
def test_the_confirmed_duplicate_pair_is_reported_and_git_cannot_see_it():
    """The captured #1080 pair (#1150 `run_metrics.py` / #1205
    `step_metrics.py`), straight from the GitHub API — see the fixture's
    PROVENANCE.md. Both closed #1080, both passed their own tests, and the
    ONLY file they share is the generated `INDEX.md`.

    This is the case the issue calls the proven instance, and it is exactly
    the case a conflict cannot report.
    """
    fixture = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "competing_pr_claim", "issue1080_confirmed_pair.json")
    records = json.loads(fixture.read_text())
    groups = mod.group_by_claim(mod.claimants_from_prs(records))

    assert [g[0] for g in groups] == [1080]
    assert {m.ident for m in groups[0][1]} == {"PR #1150", "PR #1205"}
    assert groups[0][2] == mod.NO_SHARED_FILE

    # And the reason it was invisible: with INDEX.md counted the pair reads as
    # SHARED, i.e. as something somebody would already have adjudicated.
    assert mod.classify(groups[0][1], discount=()) == mod.SHARED

    # The same file, fed to the CLI unmodified, because the fixture is in the
    # exact shape `gh pr list --json number,title,body,files` emits.
    rc, out = _run("--prs-json", str(fixture))
    assert rc == 0, out
    assert "#1080" in out and "PR #1150" in out and "PR #1205" in out


def test_the_repos_own_landed_history_carries_an_invisible_pair():
    """A landing that already happened: `652cc8638` and `ff8da73f8` both claim
    #1047 in their subjects and touch NO file in common
    (`tools/gatekeeper-land.sh` vs `programs/tests/test_suite_write_guard.py`).

    Read from this checkout's real git history, not from a fixture — nothing
    here was authored alongside the change it is testing.
    """
    repo = require_repo(".")
    tip = "4b22e36ea"
    probe = subprocess.run(["git", "-C", str(repo), "cat-file", "-e",
                            tip + "^{commit}"],
                           capture_output=True, timeout=_TIMEOUT_S)
    if probe.returncode != 0:
        pytest.skip("commit %s not in this checkout (shallow clone?)" % tip)

    claimants = mod.claimants_from_range(repo, "%s~12..%s" % (tip, tip))
    assert len(claimants) == 12, "the range itself must not come back empty"

    groups = mod.group_by_claim(claimants)
    assert [(g[0], g[2]) for g in groups] == [(1047, mod.NO_SHARED_FILE)]
    assert len(groups[0][1]) == 2


def test_an_unreachable_rev_range_is_not_checked(tmp_path):
    """A git range that cannot be resolved must refuse, not report zero."""
    rc, out = _run("--rev-range", "nope..alsonope", "--repo-root", str(tmp_path))
    assert rc == 2, out
    assert "NOT CHECKED" in out
