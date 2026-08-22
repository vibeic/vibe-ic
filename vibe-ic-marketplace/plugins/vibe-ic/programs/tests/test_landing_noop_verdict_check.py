"""`landing_noop_verdict_check` must refuse a "nothing to land" verdict the two
trees do not support.

The program exists for one measured failure (2026-08-21): a batch landing logged
NOTHING TO LAND for a lane whose branch differed from the trunk in four files,
three of them not generated. The tool was answering about its own staging area;
the verdict is about the two trees.

Every arm here is asserted in BOTH directions, and the last test is the
discrimination proof: with the refusal reverted, the negative fixture passes.
A guard never seen to fail has not been shown to discriminate.

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/<this file>
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "landing_noop_verdict_check.py"

RC_PASS, RC_FAIL, RC_VACUOUS, RC_USAGE = 0, 1, 2, 3


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo),
         "-c", "user.email=t@example.invalid", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True, timeout=120, check=False)


def _write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    """A fork point, a lane that edits one file, and a `trunk` branch.

    `trunk` is created as an ORPHAN-style squash of the fork point, so the lane
    and the trunk share a merge base far behind the trunk's content. That is
    the shape a squash-landing repository always has, and it is the reason
    ancestry cannot answer the question.
    """
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "fork")
    _write(repo, "a.txt", "one\n")
    _write(repo, "gen/INDEX.md", "generated\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fork point")
    _git(repo, "branch", "trunk")
    _git(repo, "checkout", "-q", "-b", "lane")
    _write(repo, "a.txt", "two\n")
    _write(repo, "gen/INDEX.md", "generated v2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "the lane's work")
    _git(repo, "checkout", "-q", "trunk")
    return repo


def _run(*args, cwd: Path = None) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(PROG), *[str(a) for a in args]],
                          capture_output=True, text=True, timeout=300,
                          cwd=str(cwd) if cwd else None)


# ── the honest case ──────────────────────────────────────────────────────────

def test_a_lane_whose_bytes_are_all_in_the_target_is_a_verified_noop(tmp_path):
    """The trunk was given the lane's bytes WITHOUT the lane's commits — a
    squash land. Ancestry says nothing landed; the blobs say it all did."""
    repo = _repo(tmp_path)
    _write(repo, "a.txt", "two\n")
    _write(repo, "gen/INDEX.md", "generated v2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "squash of the lane")

    r = _run("--repo", repo, "--branch", "lane", "--target", "trunk")
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    # The reach has to be VISIBLE: a verdict whose denominator is invisible
    # cannot be told from a verdict over nothing.
    assert "2 path(s)" in r.stdout, r.stdout


# ── the defect ───────────────────────────────────────────────────────────────

def test_a_partly_landed_lane_refuses_the_noop_and_names_the_paths(tmp_path):
    repo = _repo(tmp_path)
    _write(repo, "gen/INDEX.md", "generated v2\n")     # only the generated half
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "half of the lane")

    # The control: a SECOND trunk that received both files. If this does not
    # pass, the negative below proves nothing — it would only show the program
    # refuses everything.
    _git(repo, "checkout", "-q", "-b", "trunk-complete")
    _write(repo, "a.txt", "two\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "the other half")
    _git(repo, "checkout", "-q", "trunk")
    ok = _run("--repo", repo, "--branch", "lane", "--target", "trunk-complete")
    assert ok.returncode == RC_PASS, (
        "the control arm must pass or the negative proves nothing:\n" + ok.stdout)

    r = _run("--repo", repo, "--branch", "lane", "--target", "trunk")
    assert r.returncode == RC_FAIL, "a partly landed lane passed:\n" + r.stdout
    assert "a.txt" in r.stdout, "the unlanded path is not named:\n" + r.stdout
    assert "gen/INDEX.md" not in r.stdout, \
        "a path that DID land was reported as unlanded:\n" + r.stdout


def test_a_path_the_target_has_never_seen_refuses(tmp_path):
    """The ABSENT verdict: the lane adds a file, the trunk does not carry it."""
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "lane")
    _write(repo, "new.txt", "added by the lane\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "add a file")
    _git(repo, "checkout", "-q", "trunk")
    _write(repo, "a.txt", "two\n")
    _write(repo, "gen/INDEX.md", "generated v2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "squash without the new file")

    r = _run("--repo", repo, "--branch", "lane", "--target", "trunk")
    assert r.returncode == RC_FAIL, r.stdout
    assert "new.txt" in r.stdout and "never seen" in r.stdout, r.stdout


def test_a_deletion_the_target_did_not_apply_refuses(tmp_path):
    """The UNDELETED verdict. A land that keeps a file the lane removed is a
    partial land, and it is the direction a content-only comparison misses."""
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "lane")
    (repo / "gen" / "INDEX.md").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "the lane removes the generated file")
    _git(repo, "checkout", "-q", "trunk")
    _write(repo, "a.txt", "two\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "squash, keeping the generated file")

    r = _run("--repo", repo, "--branch", "lane", "--target", "trunk")
    assert r.returncode == RC_FAIL, r.stdout
    assert "gen/INDEX.md" in r.stdout and "still carries" in r.stdout, r.stdout


def test_generated_paths_are_labelled_and_never_waived(tmp_path):
    """`--generated` picks the remedy; it must not shrink the finding. The
    measured lane lost three non-generated files behind one generated one."""
    repo = _repo(tmp_path)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "trunk moves on")

    r = _run("--repo", repo, "--branch", "lane", "--target", "trunk",
             "--generated", "gen/*")
    assert r.returncode == RC_FAIL, r.stdout
    assert "[generated]" in r.stdout, r.stdout
    assert "a.txt" in r.stdout, "the non-generated path vanished:\n" + r.stdout
    assert "1 generated, 1 not" in r.stdout, r.stdout


# ── the vacuous tier ─────────────────────────────────────────────────────────

def test_a_branch_that_touches_nothing_is_vacuous_and_says_so(tmp_path):
    """rc 2 with the printed marker. A lane with no work has not been shown to
    have landed; it has been shown to have nothing to say."""
    repo = _repo(tmp_path)
    r = _run("--repo", repo, "--branch", "trunk", "--target", "trunk")
    assert r.returncode == RC_VACUOUS, r.stdout + r.stderr
    assert "VACUOUS_PASS:" in (r.stdout + r.stderr), \
        "the vacuous tier passed silently:\n" + r.stdout + r.stderr
    assert "NOT a verified no-op" in r.stdout, r.stdout


# ── the bad invocation tier ──────────────────────────────────────────────────

def test_a_ref_that_does_not_resolve_is_rc3_not_rc2(tmp_path):
    """rc 2 means "there was nothing to examine". A wrong command line is not
    that, and argparse's default 2 would make the two indistinguishable."""
    repo = _repo(tmp_path)
    r = _run("--repo", repo, "--branch", "no-such-ref", "--target", "trunk")
    assert r.returncode == RC_USAGE, r.stdout + r.stderr
    assert "USAGE_ERROR:" in r.stderr, r.stderr


def test_an_unknown_flag_is_rc3_not_argparse_2(tmp_path):
    r = _run("--branch", "a", "--target", "b", "--not-a-flag")
    assert r.returncode == RC_USAGE, r.stdout + r.stderr
    assert "USAGE_ERROR:" in r.stderr, r.stderr


def test_a_gitlink_the_target_does_not_carry_is_not_read_as_identical(tmp_path):
    """A submodule pointer is a real content change at a real path. Indexing
    only `blob` entries drops it from BOTH trees, and `classify` reads a path
    absent from both as "both deleted it" — IDENTICAL, a false pass.

    This repository carries no submodule today, which is exactly why the case is
    pinned: a rule that is right only while a fact happens to hold is the shape
    this whole batch is about.
    """
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-q", "lane")
    pointer = _git(repo, "rev-parse", "fork").stdout.strip()
    _git(repo, "update-index", "--add", "--cacheinfo",
         f"160000,{pointer},vendor")
    _git(repo, "commit", "-qm", "the lane adds a submodule pointer")
    _git(repo, "checkout", "-q", "trunk")
    _write(repo, "a.txt", "two\n")
    _write(repo, "gen/INDEX.md", "generated v2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "squash without the pointer")

    r = _run("--repo", repo, "--branch", "lane", "--target", "trunk")
    assert r.returncode == RC_FAIL, \
        "a gitlink the target does not carry passed as landed:\n" + r.stdout
    assert "vendor" in r.stdout, "the gitlink path is not named:\n" + r.stdout


# ── the same measurement, the opposite claim ─────────────────────────────────

def test_claim_work_passes_when_the_lane_really_carries_something(tmp_path):
    """`--claim work` is the landing gate's premise. The exit code answers the
    CLAIM, so neither caller has to invert a verdict in their head."""
    repo = _repo(tmp_path)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "trunk moves on")
    r = _run("--repo", repo, "--branch", "lane", "--target", "trunk",
             "--claim", "work")
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    assert "there is work to land" in r.stdout, r.stdout


def test_claim_work_refuses_a_landing_whose_bytes_are_already_there(tmp_path):
    """THE ANCESTRY TRAP. `gatekeeper-land-differential.sh` refuses a landing
    when `BASE_SHA = HEAD_SHA`, which is ancestry. A branch squash-landed and
    then rebased has a DIFFERENT HEAD and IDENTICAL bytes, and an hour of gates
    then runs over a landing with nothing in it."""
    repo = _repo(tmp_path)
    _write(repo, "a.txt", "two\n")
    _write(repo, "gen/INDEX.md", "generated v2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "squash of the lane")
    assert _git(repo, "rev-parse", "trunk").stdout.strip() \
        != _git(repo, "rev-parse", "lane").stdout.strip(), \
        "the fixture is wrong: the two tips are the same commit, which ancestry " \
        "already catches, so it proves nothing"

    r = _run("--repo", repo, "--branch", "lane", "--target", "trunk",
             "--claim", "work")
    assert r.returncode == RC_FAIL, \
        "an empty landing passed the premise:\n" + r.stdout
    assert "carries nothing" in r.stdout, r.stdout


def test_an_unknown_claim_is_rc3_not_argparse_2(tmp_path):
    repo = _repo(tmp_path)
    r = _run("--repo", repo, "--branch", "lane", "--target", "trunk",
             "--claim", "maybe")
    assert r.returncode == RC_USAGE, r.stdout + r.stderr


# ── discrimination: revert the rule, the refusal disappears ──────────────────

def test_reverting_the_refusal_makes_the_partial_land_pass(tmp_path):
    """THE MUTATION ARM. `classify` is the rule: it is the only thing that can
    say a path is not IDENTICAL. Neutered to call every path identical, the
    partly landed fixture — which the test above proves is refused — passes.

    That is the proof this file measures the DECISION and not the plumbing.
    """
    repo = _repo(tmp_path)
    _write(repo, "gen/INDEX.md", "generated v2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "half of the lane")

    honest = _run("--repo", repo, "--branch", "lane", "--target", "trunk")
    assert honest.returncode == RC_FAIL, "control arm is not red:\n" + honest.stdout

    source = PROG.read_text(encoding="utf-8")
    mutant_body = source.replace(
        "            rows.append((p, IDENTICAL if b == t else CONTENT))",
        "            rows.append((p, IDENTICAL))")
    assert mutant_body != source, "the mutation did not apply — the rule moved"
    mutant = tmp_path / "mutant.py"
    mutant.write_text(mutant_body, encoding="utf-8")

    r = subprocess.run(
        [sys.executable, str(mutant), "--repo", str(repo),
         "--branch", "lane", "--target", "trunk"],
        capture_output=True, text=True, timeout=300,
        env={**__import__("os").environ,
             "PYTHONPATH": str(PROG.parent)})
    assert r.returncode == RC_PASS, (
        "the mutant still refused, so the refusal does not come from the rule "
        "this test names:\n" + r.stdout + r.stderr)
