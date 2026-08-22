"""Tests for the required-status poller. vibe-ic#1019/#1036.

The behaviour under test is almost entirely `classify()`, and that is on
purpose: most of the rest of the poller is transport (`gh api`), while
`classify()` is where a wrong answer becomes a WRONG GREEN — a merge allowed
onto `main` because the poller mistook "measured nothing" for "measured and
found nothing wrong".

The ONE piece of transport that is tested too is `prepare_gate_checkout`, and
for the same reason inverted: it used to be `git worktree add`, and a worktree
whose registration a third party pruned mid-tier produced four gate failures
that were about the accident and not about the commit. That is "measured
nothing" arriving dressed as "measured and found something wrong", which is the
same defect pointing the other way.

Every case below is anchored to a real measurement rather than an imagined one:

* the `no tests ran` shape is what `python3 -m pytest` prints on the landing
  host, where autoload pulls in a broken third-party pytest11 plugin (web3's
  `pytest_ethereum`) and the session dies AT COLLECTION. Zero tests run. The
  first time this was read, it was read as "baseline: 0 failures";
* the `2 failed, 379 passed` shape is the real targeted-selection output from
  PR #1056 on 2026-08-12;
* `exit 0 with no test count` is the shape a future refactor could produce if
  the selection file came back empty and the gate declined to notice.

NEGATIVE CONTROL: `test_a_pass_is_still_a_pass` exists so that the suite cannot
be satisfied by a `classify()` that simply refuses everything. A gate that
never says success is a ban, not a check, and would pass every other test here.
"""
import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

_MOD = Path(__file__).resolve().parent / "gatekeeper_status_poller.py"
_spec = importlib.util.spec_from_file_location("gksp", _MOD)
gksp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gksp)


def test_collection_death_is_error_not_failure():
    """The whole point. A gate that could not run must not look like a red gate."""
    out = "ERROR: file or directory not found: programs/tests/test_new.py\n\nno tests ran in 0.13s\n"
    state, desc = gksp.classify(4, out)
    assert state == "error", "collection death must NOT be reported as `failure`"
    assert "COULD NOT RUN" in desc


def test_internalerror_is_error():
    state, _ = gksp.classify(3, "INTERNALERROR> ImportError: cannot import name 'foo'\n")
    assert state == "error"


def test_real_failures_are_failure():
    """PR #1056's measured output: the gate ran and disagreed."""
    state, desc = gksp.classify(1, "2 failed, 379 passed in 90.63s\n")
    assert state == "failure"
    assert "2 failed" in desc


def test_a_pass_is_still_a_pass():
    """NEGATIVE CONTROL — see module docstring. Without this, a classify() that
    returned `error` unconditionally would satisfy every other test here."""
    state, desc = gksp.classify(0, "770 passed, 2 skipped in 101.84s\n")
    assert state == "success"
    assert "770 passed" in desc


def test_zero_exit_without_evidence_of_running_is_error():
    """Exit 0 is not sufficient. Something must actually have been measured."""
    state, desc = gksp.classify(0, "--- cheap tier ---\n  PASS  something\n")
    assert state == "error"
    assert "no test ran" in desc


def test_zero_exit_that_also_reports_failures_is_error_not_success():
    """Contradiction is unmeasured, never a pass. A gate whose exit code and
    whose output disagree is a gate whose verdict is unknown."""
    state, _ = gksp.classify(0, "3 failed, 100 passed in 12s\n")
    assert state == "error"


def test_nonzero_without_a_count_is_still_failure():
    state, desc = gksp.classify(2, "  FAIL  repo hygiene gates\n")
    assert state == "failure"
    assert "exit 2" in desc


@pytest.mark.parametrize("state", ["failure", "error"])
def test_only_success_can_ever_satisfy_protection(state):
    """Documents the fail-closed property: GitHub requires the required context
    to be `success`, so `error` blocks a merge exactly as `failure` does. The
    three-valued verdict changes what a human is TOLD, never what is allowed."""
    assert state != "success"


def test_context_constant_matches_the_protection_rule():
    """The required context string is load-bearing — branch protection on `main`
    requires this exact value. Drift fails closed (nothing satisfies the rule),
    but it fails closed SILENTLY, so it is pinned here."""
    assert gksp.CONTEXT == "vibe-ic/gatekeeper-land"


# ==========================================================================
# THE TIER CHECKOUT IS A CLONE, NOT A WORKTREE  (job TIER)
#
# `run_gate` used to be `git worktree add -f --detach`. A linked worktree's
# registration lives in the SHARED repository, and `git worktree prune` run
# there by any other process removes it mid-tier — after which every git call
# inside the tree fails and gates report the accident instead of the commit.
# MEASURED: four gates lost to pure collateral in one such run.
#
# The pair below is bidirectional, which is the only shape that proves anything
# here: `test_PRE_FIX_CONTROL_...` builds the OLD worktree and asserts it DIES
# when the source loses the registration, and `test_the_tier_checkout_survives_
# ...` puts the new checkout through the identical event and asserts it does not.
# Without the control, "the checkout still works" would be satisfied by any tree
# at all and would show nothing about what was replaced.
# ==========================================================================
def _source_repo(root: Path) -> tuple[Path, str, str]:
    """A source repository with a `main` branch and one extra commit off it."""
    src = root / "src"
    src.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(src), *a], check=True,
                                    capture_output=True, text=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True,
                   capture_output=True, text=True)
    run("config", "user.email", "t@example.invalid")
    run("config", "user.name", "t")
    (src / "tools").mkdir()
    (src / "tools" / "gatekeeper-land.sh").write_text("#!/usr/bin/env bash\n")
    run("add", "-A")
    run("commit", "-qm", "base")
    main_sha = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    # The subject commit lives ONLY under a non-branch ref, the way a fetched
    # PR head does. A clone that only took refs/heads would not have it.
    (src / "extra.txt").write_text("candidate\n")
    run("add", "-A")
    run("commit", "-qm", "candidate")
    head = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"],
                          capture_output=True, text=True,
                          check=True).stdout.strip()
    run("update-ref", "refs/pull/7/head", head)
    run("update-ref", "refs/remotes/origin/main", main_sha)
    run("reset", "-q", "--hard", main_sha)
    return src, head, main_sha


def _drop_worktree_registrations(src: Path) -> int:
    """Do to `src` exactly what a prune does: delete the registrations.

    `git worktree prune` is not called here as the whole event, because it only
    removes a registration whose working directory it finds MISSING — so on a
    still-present tree it is a no-op and would prove nothing either way. The
    OUTCOME of a prune is the removal of `.git/worktrees/<name>`, and that is
    what the running tier actually experiences. It is applied directly so the
    test replays the consequence rather than hoping to reproduce the trigger.
    """
    subprocess.run(["git", "-C", str(src), "worktree", "prune"],
                   capture_output=True, text=True)
    registry = src / ".git" / "worktrees"
    dropped = 0
    if registry.is_dir():
        for entry in sorted(registry.iterdir()):
            shutil.rmtree(entry, ignore_errors=True)
            dropped += 1
    return dropped


def test_PRE_FIX_CONTROL_a_worktree_tier_checkout_dies_when_the_source_prunes(
        tmp_path):
    """The measured failure, reproduced against the shape that was replaced.

    Without this, the test below could be satisfied by any checkout at all and
    would not show that the OLD one was broken. This is the bar the fix had to
    clear: after the registration goes, the tree is not a repository any more
    and every gate running in it starts answering about the accident.
    """
    src, head, _ = _source_repo(tmp_path)
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(src), "worktree", "add", "-f", "--detach",
                    str(wt), head], check=True, capture_output=True, text=True)
    assert subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"],
                          capture_output=True).returncode == 0

    assert _drop_worktree_registrations(src) == 1

    probe = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"],
                           capture_output=True, text=True)
    assert probe.returncode != 0, (
        "the pre-fix worktree survived losing its registration, so this "
        "control proves nothing and the test below is not discriminating")


def test_the_tier_checkout_survives_a_worktree_prune_in_the_source(tmp_path):
    """The same event, against the clone. A clone has no registration to lose."""
    src, head, _ = _source_repo(tmp_path)
    dest, refusal = gksp.prepare_gate_checkout(src, head, tmp_path / "tier")
    assert refusal is None, refusal

    assert _drop_worktree_registrations(src) == 0, (
        "the tier checkout registered itself in the source repository, so a "
        "prune there can still remove it")

    probe = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"],
                           capture_output=True, text=True)
    assert probe.returncode == 0 and probe.stdout.strip() == head, (
        "a prune in the source repository took the tier's checkout with it: "
        f"{probe.stderr.strip()}")
    assert (dest / "extra.txt").is_file(), "the requested commit is not checked out"


def test_the_tier_checkout_is_registered_nowhere_but_itself(tmp_path):
    """`.git` must be a DIRECTORY and borrow no objects.

    A control file, or an `objects/info/alternates`, means some other
    repository can delete what this run is measuring.
    """
    src, head, _ = _source_repo(tmp_path)
    dest, refusal = gksp.prepare_gate_checkout(src, head, tmp_path / "tier")
    assert refusal is None, refusal
    assert (dest / ".git").is_dir(), (
        f"{dest}/.git is not a directory — this is a linked worktree, whose "
        "registration a third party can prune mid-tier")
    assert not (dest / ".git" / "objects" / "info" / "alternates").exists(), (
        "the tier checkout borrows its objects from another repository, which "
        "a `git gc` there can delete mid-run")
    listed = subprocess.run(["git", "-C", str(src), "worktree", "list"],
                            capture_output=True, text=True, check=True).stdout
    assert str(dest) not in listed, (
        "the tier checkout registered itself in the source repository")


def test_the_base_the_gate_compares_against_is_carried_over(tmp_path):
    """`gatekeeper-land.sh` resolves `origin/main`.

    A clone builds `origin/*` from the SOURCE'S LOCAL branches, so without an
    explicit carry-over the gate would silently compare against a different
    commit than the one the poller means — a wrong base is a wrong verdict, in
    whichever direction it happens to fall.
    """
    src, head, main_sha = _source_repo(tmp_path)
    dest, refusal = gksp.prepare_gate_checkout(src, head, tmp_path / "tier")
    assert refusal is None, refusal
    got = subprocess.run(["git", "-C", str(dest), "rev-parse",
                          "refs/remotes/origin/main"],
                         capture_output=True, text=True, check=True).stdout.strip()
    assert got == main_sha, (
        f"origin/main in the tier checkout is {got[:12]}, not the source's "
        f"{main_sha[:12]}")


def test_a_commit_no_ref_reaches_is_REFUSED_and_not_silently_measured(tmp_path):
    """An unreachable commit cannot be cloned, and that must be said.

    Falling back to "measure whatever HEAD happens to be" would report a verdict
    about a different commit under the requested SHA's name.
    """
    src, _head, _ = _source_repo(tmp_path)
    absent = "0" * 40
    dest, refusal = gksp.prepare_gate_checkout(src, absent, tmp_path / "tier")
    assert refusal is not None, "an unreachable commit was accepted"
    assert "not reachable" in refusal, refusal


def test_the_prepared_checkout_is_PROVED_self_contained_not_assumed(tmp_path):
    """`prepare_gate_checkout` reads the preflight's answer about its own output.

    A guard nothing invokes enforces nothing, and "git clone produces a
    self-contained tree" is the assumption the whole change rests on. Here the
    source repository is itself a `--shared` clone, so the tier checkout inherits
    an `objects/info/alternates` chain: every check inside `prepare_gate_checkout`
    passes and the tree is still one `git gc` in a repository nobody owns away
    from losing its objects mid-tier — the same class of failure the worktree had.

    This is the paired guard for the wiring. Deleting the preflight call makes
    this test red rather than making the refusal silently disappear.
    """
    origin, head, _ = _source_repo(tmp_path)
    borrowed = tmp_path / "borrowed"
    subprocess.run(["git", "clone", "--quiet", "--shared", "--no-single-branch",
                    str(origin), str(borrowed)], check=True,
                   capture_output=True, text=True)
    subprocess.run(["git", "-C", str(borrowed), "fetch", "--quiet", str(origin),
                    "+refs/pull/*:refs/pull/*"], check=True,
                   capture_output=True, text=True)
    assert (borrowed / ".git" / "objects" / "info" / "alternates").exists(), (
        "the fixture did not produce a borrowing repository, so this test would "
        "prove nothing")

    dest, refusal = gksp.prepare_gate_checkout(borrowed, head, tmp_path / "tier")
    assert refusal is not None, (
        "a tier checkout that borrows its objects from a repository this run "
        "does not own was accepted")
    assert "not self-contained" in refusal, refusal
    assert "alternates" in refusal, (
        f"the refusal does not name the cause it found: {refusal}")


def test_NEGATIVE_CONTROL_an_ordinary_source_still_produces_an_ACCEPTED_checkout(
        tmp_path):
    """The guard above must discriminate, not refuse everything.

    Same call, same commit; only the source repository's shape differs.
    """
    src, head, _ = _source_repo(tmp_path)
    dest, refusal = gksp.prepare_gate_checkout(src, head, tmp_path / "tier")
    assert refusal is None, refusal
    assert not (dest / ".git" / "objects" / "info" / "alternates").exists()
