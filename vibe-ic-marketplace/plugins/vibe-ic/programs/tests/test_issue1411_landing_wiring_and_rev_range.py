#!/usr/bin/env python3
"""vibe-ic#1411 — the report has to RUN, and the landing path has to be able
to run it.

#1413 built the measurement. This pins the two things that stand between a
correct measurement and a report anybody ever sees:

  1. **Nothing invoked it.** Measured on `63fd89ade`, the only references to
     `competing_pr_claim_groups` outside the program itself were `INDEX.md` —
     a generated catalog, not a caller — and its own test. Its name ends in
     `_groups`, which is outside `gate_is_wired_check`'s population
     (`_(check|lint|audit|guard)$`), so the gate that exists to catch exactly
     this would not have counted it either.

  2. **The landing path cannot ask GitHub.** `gatekeeper-verify-merge.sh` runs
     `gatekeeper-land.sh` twice, for the base and for the candidate, as one
     differential; an API-only report is one that path cannot use.

...and one thing that would have made the wiring vacuous: `report()` in
`tools/gatekeeper-land.sh` greps a program's output for its own tokens before
printing it, so a finding line without one is dropped and the log shows a
label with nothing under it.

THE MUTANT THAT MUST DIE is not "the module is absent". It is:

    def emit(text=""):        # MUTANT: the pre-wiring printer
        print(text)

Every test below that reads the landing log must fail under it. The run is
recorded in the PR body.

Bounds: every subprocess here is capped at 30 s, under the 60 s ceiling
`ci_harness_timeout_ceiling_check` enforces for a harness running pytest at
`--timeout=180 --timeout-method=thread`.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from _hostpaths import require_repo

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import competing_pr_claim_groups as G  # noqa: E402

_PROG = PROGRAMS / "competing_pr_claim_groups.py"
#: Under the harness ceiling (60 s). See the module docstring.
_TIMEOUT_S = 30

#: The EXACT filter `report()` in `tools/gatekeeper-land.sh` applies to a
#: program's output before printing it into the landing log.
_LANDING_LOG_FILTER = re.compile(r"REPORT|VIOLATION|\[FAIL\]|\[SKIP\]")

#: A commit range on this repo's own landed history carrying a competing pair:
#: `652cc8638` and `ff8da73f8` both claim #1047 in their subjects and touch no
#: file in common (`tools/gatekeeper-land.sh` vs a test module). Real history,
#: not a fixture — nothing here was authored alongside the change it tests.
_TIP = "4b22e36ea"
_RANGE_WITH_PAIR = "%s~12..%s" % (_TIP, _TIP)
_RANGE_WITHOUT = "%s~2..%s" % (_TIP, _TIP)


def _run(*args):
    proc = subprocess.run([sys.executable, str(_PROG), *args],
                          capture_output=True, text=True, timeout=_TIMEOUT_S)
    return proc.returncode, proc.stdout + proc.stderr


def _repo():
    repo = require_repo(".")
    probe = subprocess.run(["git", "-C", str(repo), "cat-file", "-e",
                            _TIP + "^{commit}"],
                           capture_output=True, timeout=_TIMEOUT_S)
    if probe.returncode != 0:
        pytest.skip("commit %s not in this checkout (shallow clone?)" % _TIP)
    return repo


def _content_lines(out):
    return [ln for ln in out.splitlines() if ln.strip()]


# ----------------------------------------------------------------------
# 1. the wiring is real — the landing script names the program
# ----------------------------------------------------------------------
def test_the_landing_script_invokes_the_report():
    """A NAME IS NOT A CALL, so this asserts the invocation, not a mention.

    `gate_is_wired_check` learned this rule twice (#693, #702): a comment
    naming a gate made 44 unreachable gates read as consulted. So the assertion
    is on the `python3 .../competing_pr_claim_groups.py` command line with its
    `--rev-range` argument, not on the word appearing in the file.
    """
    script = require_repo("tools", "gatekeeper-land.sh").read_text()
    executable = "\n".join(ln for ln in script.splitlines()
                           if not ln.lstrip().startswith("#"))
    assert "competing_pr_claim_groups.py" in executable, (
        "the landing script does not invoke the report; a mention in a comment "
        "is not a caller")
    call = [ln for ln in executable.splitlines()
            if "competing_pr_claim_groups.py" in ln]
    assert call, executable
    idx = executable.index("competing_pr_claim_groups.py")
    assert "--rev-range" in executable[idx:idx + 400], (
        "the landing path must use the offline mode; it runs twice per "
        "verification and cannot depend on the API")


def _invoking_command(script_text):
    """The whole shell command that invokes the report, comments stripped.

    Walks BACKWARDS across `\\`-continuations to the command's first word, so
    the answer is `report`/`run` and not whichever line the program name
    happens to sit on.
    """
    lines = [ln for ln in script_text.splitlines()
             if not ln.lstrip().startswith("#")]
    hits = [i for i, ln in enumerate(lines)
            if "competing_pr_claim_groups.py" in ln]
    assert hits, "the landing script does not invoke the report at all"
    i = hits[0]
    while i > 0 and lines[i - 1].rstrip().endswith("\\"):
        i -= 1
    return lines[i].strip()


def test_the_landing_script_runs_it_as_a_report_not_a_gate():
    """Declared ADVISORY, and the declaration is in the wiring, not implied.

    `report` never touches FAILED; `run` sets it. Wiring this through `run`
    would make it a landing bar that is red on most landings, which is the bar
    people learn to bypass.
    """
    script = require_repo("tools", "gatekeeper-land.sh").read_text()
    cmd = _invoking_command(script)
    assert cmd.startswith("report "), (
        "the report must be wired through `report`, not `%s`" % cmd)


# ----------------------------------------------------------------------
# 2. the output survives the filter the landing log applies
# ----------------------------------------------------------------------
def test_every_content_line_survives_the_landing_log_filter(tmp_path):
    """Otherwise the log shows a label and none of the finding."""
    p = tmp_path / "prs.json"
    p.write_text(json.dumps([
        {"number": 1, "title": "", "body": "Closes #10", "files": ["a.py"]},
        {"number": 2, "title": "", "body": "Closes #10", "files": ["b.py"]}]))
    rc, out = _run("--prs-json", str(p))
    assert rc == 0, out
    dropped = [ln for ln in _content_lines(out)
               if not _LANDING_LOG_FILTER.search(ln)]
    assert not dropped, (
        "these lines would be dropped from the landing log: %s" % dropped)
    assert any("#1 x #2" in ln for ln in _content_lines(out)), out


def test_the_refusal_survives_the_filter_too(tmp_path):
    """A reason that gets filtered out leaves a bare non-zero rc, which is a
    silent refusal wearing a loud one's clothes."""
    p = tmp_path / "empty.json"
    p.write_text("[]")
    rc, out = _run("--prs-json", str(p))
    assert rc == 2, out
    kept = [ln for ln in _content_lines(out) if _LANDING_LOG_FILTER.search(ln)]
    assert kept and "NOT CHECKED" in "\n".join(kept), out


def test_a_blank_spacer_line_is_left_bare():
    """Paired guard for the rule above: `emit` must not turn spacing into
    content, or the log's `head -8` fills with empty REPORT lines and pushes
    the findings out of view."""
    assert G.emit is not None
    # The predicate itself, so the assertion does not depend on any one output.
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        G.emit("first\n\nsecond")
    assert buf.getvalue().splitlines() == ["REPORT first", "", "REPORT second"]


# ----------------------------------------------------------------------
# 3. an empty result is not a zero
# ----------------------------------------------------------------------
def test_an_empty_population_refuses_rather_than_reporting_clean(tmp_path):
    p = tmp_path / "empty.json"
    p.write_text("[]")
    rc, out = _run("--prs-json", str(p))
    assert rc == 2, out
    assert "NOT CHECKED" in out
    assert "0 issues" not in out, (
        "an unasked question must not render as a clean answer")


def test_an_empty_rev_range_refuses():
    repo = _repo()
    rc, out = _run("--rev-range", "%s..%s" % (_TIP, _TIP),
                   "--repo-root", str(repo))
    assert rc == 2, out
    assert "NOT CHECKED" in out


def test_an_unresolvable_rev_range_refuses_with_a_reason():
    """rc 2, not rc 1: "could not look" is a gap in the measurement, not a
    finding about the landing."""
    rc, out = _run("--rev-range", "nope..alsonope", "--repo-root", ".")
    assert rc == 2, out
    assert "NOT CHECKED" in out
    assert _LANDING_LOG_FILTER.search(out), out


# ----------------------------------------------------------------------
# 4. the offline mode, driven by this repo's own landed history
# ----------------------------------------------------------------------
def test_the_repos_own_landed_history_carries_an_invisible_pair():
    """A landing that already happened, read from real git history.

    `652cc8638` and `ff8da73f8` both claim #1047 and share no file, so the
    conflict mechanism had nothing to say about them.
    """
    repo = _repo()
    claimants = G.claimants_from_rev_range(str(repo), _RANGE_WITH_PAIR)
    assert len(claimants) == 12, "the range itself must not come back empty"

    pairs = G.invisible_pairs(claimants)
    assert len(pairs) == 1, pairs
    issue, a, b = pairs[0]
    assert issue == 1047
    assert {a, b} == {"652cc8638", "ff8da73f8"}


def test_a_landing_with_no_competing_claim_reports_none():
    """The negative control for the arm above: the same mode over a range that
    carries no repeated claim must find nothing, or the mode reports every
    landing and means nothing."""
    repo = _repo()
    claimants = G.claimants_from_rev_range(str(repo), _RANGE_WITHOUT)
    assert len(claimants) == 2
    assert G.invisible_pairs(claimants) == []


def test_a_commit_is_named_by_its_sha_not_as_an_issue_number():
    """`#652cc8638` would read as an issue number in a report whose whole job
    is naming things a reader can go and look up."""
    assert G.ident(1150) == "#1150"
    assert G.ident("652cc8638") == "652cc8638"


def test_the_landing_arm_names_what_it_did_not_run():
    """Degrade loudly: the queue-shaped regions are skipped over a landing, and
    a report that quietly covers less than its usual scope reads as a clean
    answer to the whole question."""
    repo = _repo()
    rc, out = _run("--rev-range", _RANGE_WITH_PAIR, "--repo-root", str(repo))
    assert rc == 0, out
    assert "SKIPPED" in out
    assert out.count("SKIPPED") == len(G._REV_RANGE_SKIPS)
    for reason in G._REV_RANGE_SKIPS:
        assert reason in out


def test_the_landing_arm_says_commits_not_open_prs():
    repo = _repo()
    rc, out = _run("--rev-range", _RANGE_WITH_PAIR, "--repo-root", str(repo))
    assert rc == 0, out
    assert "commits in this landing" in out
    assert "open PRs " not in out, (
        "a landing contains no open PRs; a label that said so would describe a "
        "population the report never read")


# ----------------------------------------------------------------------
# 5. the confirmed duplicate, captured from the API — see PROVENANCE.md
# ----------------------------------------------------------------------
def test_the_confirmed_duplicate_pair_is_reported_and_git_cannot_see_it():
    """#1150 (`run_metrics.py`) and #1205 (`step_metrics.py`) both closed
    #1080, both passed their own tests, and the ONLY file they share is the
    generated `INDEX.md`. Captured from the GitHub API, not authored here.
    """
    fixture = require_repo(
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs", "tests",
        "fixtures", "competing_pr_claim", "issue1080_confirmed_pair.json")
    records = json.loads(fixture.read_text())
    # The capture keeps `files` in gh's `[{path: ...}]` shape; the rules here
    # take plain paths.
    prs = [{**r, "files": [f["path"] for f in r["files"]]} for r in records]

    assert G.invisible_pairs(prs) == [(1080, 1150, 1205)]
    # ...and the reason it was invisible: with INDEX.md counted the pair reads
    # as SHARED, i.e. as something somebody would already have adjudicated.
    assert not G.shares_a_file(prs)
    assert G._significant_files(prs[0]["files"]) != frozenset(prs[0]["files"])
