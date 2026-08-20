"""A tier run may not start in a checkout something else can delete (job TIER).

WHY
===
The full tier is an hour of gate wall-clock. A LINKED WORKTREE's registration
lives in `<shared repo>/.git/worktrees/<name>` — a repository the run does not
own — and `git worktree prune` there removes it MID-RUN. MEASURED: one tier run
lost four gates to pure collateral that way; four verdicts about the accident
rather than about the commit, and the run's third measurement lost to something
outside the measurement.

The landing arms already avoid this and already say why
(`tools/ci/hermetic_git_subject.py:4-9`): they materialize a standalone
repository. What was missing was the refusal for every other way a tier gets
started — by hand, by a poller, by an agent that happened to `cd` somewhere.

BIDIRECTIONAL, WHICH IS THE POINT
=================================
Each refusal below is paired with the same event applied to a CLONE, which must
pass. A guard that refuses everything is a ban, not a check: it would satisfy
every "must refuse" assertion here and stop every landing.

chip-AGNOSTIC: pure git/path plumbing. No design, PDK or vendor literal.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
_TOOL = _PROGRAMS / "landing_tier_checkout_preflight.py"
_LAND = _PROGRAMS.parents[3] / "tools" / "gatekeeper-land.sh"

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "landing_tier_checkout_preflight", _TOOL)
PF = importlib.util.module_from_spec(_spec)
sys.modules["landing_tier_checkout_preflight"] = PF
_spec.loader.exec_module(PF)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True)


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True,
                   capture_output=True, text=True)
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "c")
    return root


def _cli(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(_TOOL), "--root", str(root)],
                          capture_output=True, text=True)


# --------------------------------------------------------------------------
# the pair: a worktree is refused, a clone of the same commit is not
# --------------------------------------------------------------------------
def test_a_linked_worktree_is_REFUSED(tmp_path):
    src = _repo(tmp_path / "src")
    wt = tmp_path / "wt"
    _git(src, "worktree", "add", "-q", "--detach", str(wt), "HEAD")

    why = PF.refusal(wt)
    assert why is not None, (
        "a linked worktree was accepted; a prune in the shared repository can "
        "remove it in the middle of an hour-long tier")
    assert "LINKED WORKTREE" in why, why
    assert "git clone" in why, f"the refusal names no remedy: {why}"

    proc = _cli(wt)
    assert proc.returncode == 2, proc.stderr
    assert "NOTHING WAS MEASURED" in proc.stderr, proc.stderr


def test_NEGATIVE_CONTROL_a_plain_clone_is_ACCEPTED(tmp_path):
    """Without this the guard could be `return refusal` and pass every test."""
    src = _repo(tmp_path / "src")
    dest = tmp_path / "clone"
    subprocess.run(["git", "clone", "--quiet", str(src), str(dest)], check=True,
                   capture_output=True, text=True)

    assert PF.refusal(dest) is None, PF.refusal(dest)
    proc = _cli(dest)
    assert proc.returncode == 0, proc.stderr
    assert "self-contained" in proc.stdout


def test_the_source_repository_itself_is_ACCEPTED(tmp_path):
    """The ordinary case: a maintainer's own clone is not a worktree."""
    src = _repo(tmp_path / "src")
    assert PF.refusal(src) is None, PF.refusal(src)


# --------------------------------------------------------------------------
# borrowed objects are the same class of failure
# --------------------------------------------------------------------------
def test_a_checkout_that_BORROWS_ITS_OBJECTS_is_REFUSED(tmp_path):
    """`git clone --shared` leaves the objects in a repository that can gc them.

    `hermetic_git_subject.py:252-254` already refuses this shape for the landing
    arms; a tier started any other way deserves the same answer.
    """
    src = _repo(tmp_path / "src")
    dest = tmp_path / "shared"
    subprocess.run(["git", "clone", "--quiet", "--shared", str(src), str(dest)],
                   check=True, capture_output=True, text=True)
    alternates = dest / ".git" / "objects" / "info" / "alternates"
    if not alternates.exists():
        # This git chose hardlinks over alternates. The property under test is
        # the alternates file, so write the shape the guard must refuse rather
        # than skipping and reporting a pass over an unexercised branch.
        alternates.parent.mkdir(parents=True, exist_ok=True)
        alternates.write_text(f"{src}/.git/objects\n")

    why = PF.refusal(dest)
    assert why is not None, "a checkout borrowing its objects was accepted"
    assert "borrows its objects" in why, why


def test_a_tree_that_is_not_a_repository_at_all_is_REFUSED(tmp_path):
    loose = tmp_path / "loose"
    loose.mkdir()
    proc = _cli(loose)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "not a git checkout" in proc.stderr, proc.stderr


def test_a_missing_directory_is_REFUSED_not_crashed(tmp_path):
    proc = _cli(tmp_path / "nope")
    assert proc.returncode == 2, proc.stdout + proc.stderr


# --------------------------------------------------------------------------
# the guard is WIRED, and wired where it can still be reached
# --------------------------------------------------------------------------
def test_the_full_tier_actually_calls_this_program():
    """A guard nothing invokes is a guard that enforces nothing.

    Read out of the shipped script rather than restated here, so deleting the
    call is red instead of invisible.
    """
    lines = _LAND.read_text(encoding="utf-8").splitlines()
    calls = [i for i, line in enumerate(lines)
             if line.startswith("if ! ")
             and "landing_tier_checkout_preflight.py" in line]
    assert len(calls) == 1, (
        f"gatekeeper-land.sh guards the full tier with {len(calls)} checkout "
        "preflight call(s), expected exactly 1")
    cheap_exit = next(i for i, line in enumerate(lines)
                      if line.startswith('if [ "$CHEAP_ONLY" = "1" ]'))
    assert calls[0] > cheap_exit, (
        "the checkout preflight would refuse a --cheap-only run. That tier is "
        "the pre-push hook's path, it runs in whatever checkout the developer "
        "is in, and it finishes in seconds — the failure this refuses needs an "
        "hour to happen.")
    # THE FIRST ARM IS WHERE AN ARM IS CALLED, not where a particular line
    # shape is. This used to be `line.strip() == "run_pytest"`. The full tier's
    # independent stages now run at the same time, so the arms are called from
    # inside the lane bodies the window launches, that generator matched
    # nothing, and `next` raised StopIteration — "the preflight is too late"
    # and "I could not find an arm" became the same red.
    arms = ("run_pytest", "run_repo_tools_pytest", "run_unselectable_pytest")
    spans = []
    for name in arms:
        define = next(i for i, line in enumerate(lines)
                      if line.startswith(f"{name}() {{"))
        close = next(i for i in range(define + 1, len(lines))
                     if lines[i] == "}")
        spans.append((define, close))
    arm_calls = [i for i, line in enumerate(lines)
                 if not any(a <= i <= b for a, b in spans)
                 and not line.lstrip().startswith("#")
                 and any(re.search(rf"(?<![\w./-]){name}(?![\w(])", line)
                         for name in arms)]
    assert arm_calls, (
        "gatekeeper-land.sh defines the test arms but calls none of them")
    first_arm = min(arm_calls)
    assert calls[0] < first_arm, (
        "the checkout preflight runs after an arm has already spent time in a "
        "tree it should never have started in")


def test_there_is_no_environment_escape_hatch():
    """"Impossible by accident" is the property; a flag would sell it back.

    A variable that permits a worktree gets exported once, in one wrapper, and
    is then in force for every run on that host forever.
    """
    source = _TOOL.read_text(encoding="utf-8")
    body = source.split('"""', 2)[-1]
    assert "os.environ" not in body and "getenv" not in body, (
        "the refusal reads an environment variable, so it can be turned off "
        "from outside the run it is protecting")
