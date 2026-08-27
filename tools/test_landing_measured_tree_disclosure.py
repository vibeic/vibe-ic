#!/usr/bin/env python3
"""`landing_measured_tree_disclosure` — the one sentence that says WHICH TREE.

MEASURED 2026-08-28. The landing gate reported 225 targeted / 50 repo-tools /
133 unselectable; an independent reproduction on the same declared base got
221 / 50 / 132, and no base in that history yields 225. The cause is that
neither of the two moving counts measures a COMMIT --
`landing_unselectable_pytest_corpus` enumerates with `git ls-files` (the INDEX)
and `ci_targeted_test_select` diffs `<base>` against the WORKING TREE -- so on a
landing, which runs on a staged squash, both describe the worktree and neither
describes the candidate. Uncommitted work in one directory reproduces all three
numbers with the commit tree held byte-identical to main's. See
docs/research/2026-08-28-both-landing-counts-read-the-index-not-the-commit.md.

The function under test is a DISCLOSURE and not a refusal: landing on a staged
squash is the normal case, so refusing there would refuse every landing. What is
asserted here is that it can never say the reassuring thing when it does not
know -- the arm that caught the first draft, which piped `git status` into
`grep -c ''` and so turned a FAILED git into a count of 0 and printed "clean".

The real function body is extracted from `tools/gatekeeper-land.sh` by name and
executed; a copy of it here would keep passing after the original stopped
matching it.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path

import pytest

_LAND = Path(__file__).resolve().parents[1] / "tools" / "gatekeeper-land.sh"


@pytest.fixture(scope="module")
def fn() -> str:
    text = _LAND.read_text(encoding="utf-8")
    match = re.search(r"^landing_measured_tree_disclosure\(\) \{.*?^\}$", text,
                      re.MULTILINE | re.DOTALL)
    assert match, ("landing_measured_tree_disclosure() is gone from "
                   "tools/gatekeeper-land.sh")
    return match.group(0)


def _say(fn: str, root: Path) -> str:
    script = (f'set -uo pipefail\nROOT="{root}"\n{fn}\n'
              f'landing_measured_tree_disclosure\n')
    return subprocess.run(["bash", "-c", script], capture_output=True,
                          text=True, timeout=60).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    r.mkdir()

    def git(*a):
        subprocess.run(["git", "-C", str(r), *a], check=True,
                       capture_output=True, timeout=60)

    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (r / "a.txt").write_text("one\n", encoding="utf-8")
    git("add", "a.txt")
    git("commit", "-qm", "c1")
    return r


def test_a_clean_tree_names_the_commit_the_counts_describe(fn, repo):
    out = _say(fn, repo)
    assert "measured tree: clean at" in out, out
    assert "TRACKED path(s) differ" not in out, out


def test_a_modified_tracked_path_is_counted_and_named_as_not_a_commit(fn, repo):
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    out = _say(fn, repo)
    assert "1 TRACKED path(s) differ from HEAD" in out, out
    assert "measured tree: clean at" not in out, out
    assert "describe THIS TREE and not any commit" in out, out


def test_a_STAGED_path_counts_too_because_the_census_reads_the_index(fn, repo):
    """The state a landing is actually in: `HEAD == base`, candidate staged."""
    (repo / "b.txt").write_text("new\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "b.txt"], check=True,
                   capture_output=True, timeout=60)
    out = _say(fn, repo)
    assert "1 TRACKED path(s) differ from HEAD" in out, out
    assert "measured tree: clean at" not in out, out


def test_an_untracked_file_does_not_raise_the_alarm(fn, repo):
    """It moves NEITHER count -- `ls-files` does not list it and `git diff`
    does not report it -- so counting it here would be an alarm about a state
    that changes no number."""
    (repo / "scratch.txt").write_text("x\n", encoding="utf-8")
    out = _say(fn, repo)
    assert "measured tree: clean at" in out, out


def test_a_git_that_could_not_answer_is_never_reported_as_clean(fn, tmp_path):
    """THE ARM THAT CAUGHT THE FIRST DRAFT.

    Written as `git status … | grep -c ''`, a failed git contributes an empty
    stream, the count is 0, and the function printed "measured tree: clean" for
    a directory that is not a repository at all. Under `pipefail` the pipeline's
    status is git's, but nothing was reading it. The status is captured now.
    """
    nogit = tmp_path / "nogit"
    nogit.mkdir()
    out = _say(fn, nogit)
    assert "UNDETERMINED" in out, out
    assert "measured tree: clean at" not in out, out
    assert "This is NOT a clean tree." in out, out


def test_the_disclosure_is_actually_called_before_the_window(fn):
    """An instrument wired nowhere reports nothing. It must be called from the
    MAIN shell and before the two counts it explains are printed."""
    text = _LAND.read_text(encoding="utf-8")
    lines = [i for i, l in enumerate(text.splitlines())
             if l.strip() == "landing_measured_tree_disclosure"]
    assert lines, "the disclosure is defined and never called"
    launch = [i for i, l in enumerate(text.splitlines())
              if l.strip() == "lane_run_window"]
    assert launch and min(lines) < min(launch), (
        "the disclosure must run before the window whose counts it explains")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
