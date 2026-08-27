"""The two-arm differential is GONE, and these are the invariants that outlive it.

WHAT THIS FILE USED TO BE
=========================
32 tests driving `tools/gatekeeper-land-differential.sh` — the two-arm landing
gate that ran `gatekeeper-land.sh` twice (candidate, and pristine main in a
throwaway worktree) and diffed the two red sets to answer "is this regression
mine". That script was REMOVED 2026-08-28 on owner instruction, so 26 of those
tests lost their subject and went with it.

They were not deleted to make a removal pass its own suite. The distinction is
the whole point of this file: a test whose SUBJECT no longer exists is finished,
and a test whose subject survives must keep running. Two groups survive here.

  1. THE REFUSAL. `--differential` must be refused BY NAME and must say why.
     The old test asserted the flag EXISTED; that assertion encoded the
     capability, so it is rewritten rather than dropped — the invariant that
     replaces "the gate offers this" is "the gate refuses this, and explains".

  2. THE STAMP READER. `tools/git-hooks/pre-push` parses a `base=`/`tier=` tail
     that only the differential ever wrote. Nothing writes it now, but a stamp
     minted before the removal can still be sitting in a `.git` dir, so the
     hook still reads it and the five tests below still measure a live reader.
     Deleting them would leave the unsafe direction of this change unguarded:
     a hook that stopped applying the staleness rule would let a stale pair
     verdict authorise a push.

WHY THE REMOVAL, so a reader of a green run learns nothing false:
  * ~3.5 hours PER ARM. Three landings on 2026-08-27 spent 6h, 4h and 2h in it
    and none of them landed anything.
  * It reported the ENVIRONMENT as the diff. Arms placed on two hosts returned
    2 new / 89 cleared; 82 of the 89 were one family that is red where docker
    is unreachable and green where it is not.
  * A "fast" variant compared a harness red set against a standalone probe and
    invented a new red that existed under neither mode.

NOT the merge path. `tools/gatekeeper-verify-merge.sh` (#1019) has its own arms
and its own judge and is deliberately untouched.

chip-AGNOSTIC: nothing here reasons about any IC, vendor, SKU or process node.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
LAND = REPO / "tools" / "gatekeeper-land.sh"
HOOK = REPO / "tools" / "git-hooks" / "pre-push"
PLUGIN_REL = "vibe-ic-marketplace/plugins/vibe-ic"

# The files the removal deleted. Named as data so the test below reports WHICH
# one came back rather than just that something did.
_DELETED = (
    "tools/gatekeeper-land-differential.sh",
    "tools/ci/pytest_finding_delta.py",
    "tools/ci/test_pytest_finding_delta.py",
)

sys.path.insert(0, str(REPO / PLUGIN_REL / "programs" / "tests"))
import _protected_transition_fixture as protected  # noqa: E402


def _git(cwd, *args):
    # `protected.scrubbed_env` — the harness's own environment must not be able
    # to change the bytes of the repository the harness is building.
    return subprocess.run(["git", *args], cwd=str(cwd), check=True,
                          capture_output=True, text=True,
                          env=protected.scrubbed_env()).stdout.strip()


# ------------------------------------------------------------- the refusal

def test_the_differential_driver_is_gone():
    """FAILS if any deleted file returns. Named individually: "something came
    back" sends a reader to diff three paths; this sends them to one."""
    back = [rel for rel in _DELETED if (REPO / rel).exists()]
    assert not back, (
        f"these were removed 2026-08-28 (owner) and exist again: {back}. The "
        "removal was not a cleanup — the capability itself is what was taken "
        "away, because telling people not to run it did not work.")


def test_land_sh_refuses_the_flag_by_name_and_says_why():
    """A removal that leaves no trace teaches the next reader nothing.

    The generic `unknown argument` path would already exit 2, so exit code
    alone proves nothing about this flag. What is asserted is that the refusal
    is SPECIFIC: it names the removal, it carries a cause a reader can weigh,
    and it says what to do instead.
    """
    cp = subprocess.run(["bash", str(LAND), "--differential"],
                        capture_output=True, text=True, cwd=str(REPO))
    assert cp.returncode == 2, (
        f"expected refusal rc=2, got {cp.returncode}\n{cp.stdout}\n{cp.stderr}")
    err = cp.stderr
    assert "REMOVED" in err, err
    assert "2026-08-28" in err, err
    # THE CAUSE, not just the fact. A reader who is told only "removed" will
    # reimplement it; the two measured reasons are what stop that.
    assert "3.5h" in err or "3.5 h" in err, err
    assert "environment differences as regressions" in err, err
    # AND THE REMEDY. A refusal that names no next step is a dead end.
    assert "fix the red" in err, err
    assert "commit message" in err, err
    # NOT a generic parse failure — that message would be true and useless.
    assert "unknown argument" not in err, err


def test_the_refusal_is_not_what_every_unknown_flag_gets():
    """NON-VACUITY. If the case above were deleted, `--differential` would fall
    through to the generic handler and still exit 2 — and every assertion about
    "it refuses" would still pass. This pins the DIFFERENCE, so the specific
    refusal cannot rot into the generic one without a red."""
    known = subprocess.run(["bash", str(LAND), "--differential"],
                           capture_output=True, text=True, cwd=str(REPO))
    other = subprocess.run(["bash", str(LAND), "--no-such-flag-xyz"],
                           capture_output=True, text=True, cwd=str(REPO))
    assert other.returncode == 2, other.stderr
    assert "unknown argument" in other.stderr, other.stderr
    assert known.stderr != other.stderr, (
        "--differential now gets the same message as any typo, so the removal "
        "no longer explains itself: " + known.stderr)


def test_the_absolute_explanation_survives_the_removal():
    """The comment block explaining WHY this gate judges absolutely records a
    fact that is still true — main can fail its own gates, so an absolute gate
    refuses the very commit that fixes them. Only the "run the differential"
    remedy was removed. Losing the explanation with it would delete the reason
    the next person needs most."""
    land = LAND.read_text(encoding="utf-8")
    assert "judged ABSOLUTELY" in land
    assert "FAILS ITS OWN GATES" in land
    assert "2026-08-17" in land, (
        "the measured date of the deadlock is what makes the explanation "
        "checkable rather than a claim")


def test_the_failure_path_offers_a_remedy_that_still_exists():
    """The old text sent a failing gate to `--differential`. Whatever replaces
    it must not name a removed thing, and must not be silent either."""
    land = LAND.read_text(encoding="utf-8")
    tail = land[land.index("=== FAILURES ABOVE"):]
    assert "--differential" not in tail, (
        "the failure path still sends the operator to the removed flag")
    assert "notes --ref=landing" in tail, (
        "the failure path names no remedy; a reader with a red and no next "
        "step re-runs the same absolute round forever")


def test_no_live_code_still_routes_anyone_to_the_removed_flag():
    """`pre-push` printed `run: tools/gatekeeper-land.sh --differential` in
    three places. A refusal in one file does not help if another file is still
    handing out the command."""
    for rel in ("tools/git-hooks/pre-push", "tools/gatekeeper-land.sh"):
        text = (REPO / rel).read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue          # prose recording the removal is the point
            assert "gatekeeper-land.sh --differential" not in line, (
                f"{rel}:{i} still tells someone to run the removed flag: "
                f"{line.strip()}")


# ---------------------------------------------- the hook that reads the stamp
# UNCHANGED FROM THE ORIGINAL MODULE, and deliberately so. The differential is
# the only thing that ever WROTE a `base=`/`tier=` tail, but `pre-push` is still
# its READER and a stamp minted before 2026-08-28 can still be on disk. Getting
# this wrong in either direction is a landing bug: too strict and nothing lands,
# too loose and a stale verdict authorises a push. Both directions are exercised
# against the REAL hook, in a synthetic repo whose gate programs are stubs — the
# stamp block is what is under test, not the eight gates ahead of it.

_HOOK_PROGRAMS = (
    "agent_checkin_scope_guard.py", "commit_msg_nda_check.py",
    "git_prohibition_guard.py", "landing_collateral_revert_check.py",
    "marketplace_version_sync_check.py", "nda_diff_scan_check.py",
    "plugin_full_audit.py", "version_bump_monotonic_check.py",
)


@pytest.fixture()
def hook_repo(tmp_path):
    root = tmp_path / "hookrepo"
    prog = root / PLUGIN_REL / "programs"
    prog.mkdir(parents=True)
    for name in _HOOK_PROGRAMS:
        (prog / name).write_text("raise SystemExit(0)\n")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-f", ".")
    _git(root, "commit", "-q", "-m", "base")
    base = _git(root, "rev-parse", "HEAD")
    (root / "later").write_text("x\n")
    _git(root, "add", "-f", "later")
    _git(root, "commit", "-q", "-m", "head")
    head = _git(root, "rev-parse", "HEAD")
    stamp = Path(_git(root, "rev-parse", "--absolute-git-dir")) / "gatekeeper-stamp"
    return root, base, head, stamp


def _push(root: Path, head: str, remote_sha: str):
    """Exactly the stdin git feeds `pre-push` for `git push origin main`."""
    return subprocess.run(
        ["bash", str(HOOK), "origin", "git@example.invalid:x/y.git"],
        input=f"refs/heads/main {head} refs/heads/main {remote_sha}\n",
        capture_output=True, text=True, cwd=str(root))


def test_the_hook_accepts_the_old_single_line_stamp_unchanged(hook_repo):
    """The absolute tier writes one line and claims nothing about a base. This
    is now the ONLY shape anything mints, so it is the path that must work."""
    root, base, head, stamp = hook_repo
    stamp.write_text(head + "\n")
    cp = _push(root, head, base)
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_the_hook_accepts_a_pair_stamp_whose_base_is_still_the_remote_tip(hook_repo):
    """A pre-removal stamp that is still ACCURATE must not start being refused:
    the removal took away a way of measuring, not the validity of a measurement
    already taken."""
    root, base, head, stamp = hook_repo
    stamp.write_text(f"{head}\nbase={base}\ntier=direct-push\n")
    cp = _push(root, head, base)
    assert cp.returncode == 0, cp.stdout + cp.stderr


def test_the_hook_refuses_a_pair_stamp_whose_base_has_moved(hook_repo):
    """THE STALENESS HOLE the single-SHA stamp could not express, and the reason
    the tail reader is KEPT after the writer is gone. A differential verdict is
    about a (base, candidate) PAIR: if `main` moved in between, "this breaks
    nothing new" was decided about a tree nobody is about to create."""
    root, base, head, stamp = hook_repo
    # SOMEBODY ELSE LANDED. The remote tip is a real commit off the same base
    # and not in this branch's history, which is exactly the shape a concurrent
    # landing produces — and it must be a REAL object: `pre-push` computes its
    # range with `git rev-list --count ... || echo 0` and treats an
    # UNRESOLVABLE range as "nothing to push", skipping every gate including
    # the stamp block. A fake sha would make this test pass for the wrong
    # reason and assert nothing.
    _git(root, "checkout", "-q", "--detach", base)
    _git(root, "commit", "-q", "--allow-empty", "-m", "somebody else landed")
    moved = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", "--detach", head)
    stamp.write_text(f"{head}\nbase={base}\ntier=direct-push\n")
    cp = _push(root, head, moved)
    assert cp.returncode == 1, cp.stdout + cp.stderr
    assert "measured against a base that has moved" in cp.stderr


def test_the_hook_still_refuses_a_stamp_for_another_commit(hook_repo):
    root, base, head, stamp = hook_repo
    stamp.write_text(f"{base}\nbase={base}\n")
    cp = _push(root, head, base)
    assert cp.returncode == 1
    assert "stamp is for a different commit" in cp.stderr


def test_the_hook_still_refuses_when_there_is_no_stamp(hook_repo):
    root, base, head, stamp = hook_repo
    assert not stamp.exists()
    cp = _push(root, head, base)
    assert cp.returncode == 1
    assert "the full suites have not been run" in cp.stderr


def test_the_hooks_remediation_names_a_command_that_runs(hook_repo):
    """A refusal that prints a removed command is worse than one that prints
    nothing: the reader spends an hour before finding out. Whatever `pre-push`
    tells them to run must actually parse."""
    root, base, head, stamp = hook_repo
    cp = _push(root, head, base)
    assert cp.returncode == 1
    assert "run: tools/gatekeeper-land.sh" in cp.stderr, cp.stderr
    assert "--differential" not in cp.stderr, cp.stderr
