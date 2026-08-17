"""The hook that runs must be the hook the tree declares, or nothing runs.

`.git/hooks/` is NOT versioned. Nothing in git relates the file that executes on
a push to the file this repository ships, and until this change no command in
the repo compared them.

MEASURED on the orchestrator host, 2026-08-17, with `wc -l` and `diff`:

    installed  .git/hooks/pre-push          410 lines
    declared   tools/git-hooks/pre-push     293 lines   (that checkout's HEAD)
    differing lines (`diff | grep -c '^[<>]'`)          137

A third of the file. The drift has been seen in BOTH directions across hosts:
one ran a hook OLDER than its tree — still running two gates deliberately
relocated to `gatekeeper-land.sh` on 2026-08-14, and missing newer ones — and the
host measured above ran a hook NEWER than its tree. The sentence is the same
either way, and it is the one this repository exists to refuse:

    pushes were judged by a gate set the repository does not declare.

A drifted hook is not a degraded hook. It is a hook whose PASS means nothing,
and whose output gives the reader no way to tell. So the guard REFUSES; a
warning about a wrong hook is printed into the scrollback of a push that
succeeded, which is exactly where nobody reads it.

BOTH DIRECTIONS, AND BOTH INSTALLATION SHAPES. A refusal that fires on
everything is not a check, and a check exercised only in the shape the author
happened to use rots in the other one:

                        identical to the tree      differing from the tree
    installed as a COPY     must PASS through          must REFUSE
    installed as a SYMLINK  must PASS through          must REFUSE
                            (symlink to a divergent tree — the shared-hooks
                             cross-worktree case the installer now blocks)

"PASS through" is observable without running any gate: in the sandbox below the
NDA checker is absent, so a hook that gets past its self-check reaches the
`WARNING — NDA message guard not found ... skipping` branch and exits 0. That
same branch is why the self-check has to sit BEFORE it: a hook stale enough to
have lost its way to the checker would otherwise exit 0 without ever comparing
itself, and `test_the_self_check_precedes_the_checker_early_exit` pins the order.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _find_repo_root() -> Path:
    """Walk up to the artefact rather than counting directories.

    A hard-coded `parents[N]` is a guess about how deep this file sits in the
    marketplace layout, and it has been wrong by one level before in this very
    directory (see `test_pre_push_failure_excerpt_shows_the_finding`).
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "tools" / "git-hooks" / "pre-push").is_file():
            return parent
    raise AssertionError("tools/git-hooks/pre-push not found above this test")


REPO = _find_repo_root()
HOOK = REPO / "tools" / "git-hooks" / "pre-push"

FIX = "tools/install-git-hooks.sh --force"


def _env() -> dict:
    env = dict(os.environ)
    # A push-time hook inherits the pusher's identity config; a sandbox has
    # none, and a missing user.email makes `git commit` fail for a reason that
    # has nothing to do with what is under test.
    env.update(
        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
    )
    # THE HOOK ITSELF DOCUMENTS THIS TRAP (vibe-ic#636): git exports `GIT_DIR`
    # for a push from a worktree, and an inherited one would silently point the
    # sandbox's `git rev-parse --show-toplevel` at the CALLER's repository — so
    # the hook would compare itself against the wrong tree and this suite would
    # measure the host instead of the fixture.
    for stray in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(stray, None)
    return env


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    p = subprocess.run(["git", *args], cwd=str(cwd), env=_env(),
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, f"git {' '.join(args)}: {p.stderr}"
    return p


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    """A real git repo carrying the SHIPPED hook as its declared hook.

    Deliberately WITHOUT the plugin's `programs/` tree: the point is to observe
    whether the hook reaches its gates at all, not to re-test the gates. The
    shipped text is copied rather than re-implemented, so this cannot pass
    against a hook that has drifted away from it.
    """
    repo = tmp_path / "repo"
    (repo / "tools" / "git-hooks").mkdir(parents=True)
    shutil.copy2(HOOK, repo / "tools" / "git-hooks" / "pre-push")
    _git("init", "-q", cwd=repo)
    _git("add", "-A", cwd=repo)
    _git("commit", "-qm", "seed", cwd=repo)
    return repo


def _install_copy(repo: Path, *, stale: bool) -> Path:
    dst = repo / ".git" / "hooks" / "pre-push"
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = (repo / "tools" / "git-hooks" / "pre-push").read_text(encoding="utf-8")
    if stale:
        # One line, appended where it cannot change behaviour — the guard must
        # fire on DIFFERENCE, not on a difference big enough to look scary.
        text += "\n# a gate that used to live here moved to gatekeeper-land.sh\n"
    dst.write_text(text, encoding="utf-8")
    dst.chmod(0o755)
    return dst


def _install_symlink(repo: Path, target: Path) -> Path:
    dst = repo / ".git" / "hooks" / "pre-push"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    dst.symlink_to(target)
    return dst


def _run_hook(repo: Path, hook: Path) -> subprocess.CompletedProcess:
    """Drive the hook the way git does: from the worktree root, on stdin.

    Empty stdin is the honest shape for this test — the ref loop then adds
    nothing, and every path exercised here is reached before any range matters.
    """
    return subprocess.run(
        ["bash", str(hook), "origin", "https://example.invalid/r.git"],
        cwd=str(repo), env=_env(), input="", capture_output=True, text=True,
        timeout=120,
    )


# ── the shape that must pass through: nothing has drifted ──────────────────
@pytest.mark.parametrize("shape", ["copy", "symlink"])
def test_current_installs_pass(sandbox: Path, shape: str):
    """Identical content, both shapes, must reach the gates.

    `cmp` follows symlinks, so the symlink case is identical to its target by
    construction — which is the argument for comparing CONTENT rather than
    resolving paths, and this arm is what keeps that argument checkable.
    """
    declared = sandbox / "tools" / "git-hooks" / "pre-push"
    hook = (_install_copy(sandbox, stale=False) if shape == "copy"
            else _install_symlink(sandbox, declared))

    p = _run_hook(sandbox, hook)
    combined = p.stdout + p.stderr
    assert "BLOCKED" not in combined, (
        f"a {shape} install identical to the tree was refused — the guard "
        f"refuses everything, so its refusals prove nothing:\n{combined}")
    assert "NDA message guard not found" in combined, (
        "the hook did not reach the gates at all; this arm no longer shows "
        f"that a current hook is let THROUGH:\n{combined}")
    assert p.returncode == 0, f"rc={p.returncode}\n{combined}"


# ── the shape that must be refused ─────────────────────────────────────────
@pytest.mark.parametrize("shape", ["copy", "symlink"])
def test_a_stale_install_is_refused_and_names_the_fix(sandbox: Path, shape: str):
    """The defect, in one run, in both installation shapes.

    The symlink variant is not decoration: hooks live in the SHARED git dir, so
    a symlink created from worktree A is what worktree B executes, and B's
    declared hook can differ from A's. That is a real drift path, and it is the
    one `tools/install-git-hooks.sh` now refuses to create.
    """
    if shape == "copy":
        hook = _install_copy(sandbox, stale=True)
    else:
        other = sandbox.parent / "other-worktree-pre-push"
        other.write_text(
            (sandbox / "tools" / "git-hooks" / "pre-push").read_text(
                encoding="utf-8")
            + "\n# this copy belongs to another worktree\n",
            encoding="utf-8")
        other.chmod(0o755)
        hook = _install_symlink(sandbox, other)

    p = _run_hook(sandbox, hook)
    combined = p.stdout + p.stderr
    assert p.returncode != 0, (
        f"a stale {shape} install pushed with rc=0:\n{combined}")
    assert "BLOCKED" in combined and "declare" in combined, combined
    assert FIX in combined, (
        "the refusal does not name the one command that fixes it; a reader is "
        f"stopped and given nothing to do:\n{combined}")
    assert "NDA message guard not found" not in combined, (
        "the hook ran on past its own staleness and started producing verdicts "
        f"from an undeclared gate set:\n{combined}")


def test_the_refusal_reports_how_far_apart_they_are(sandbox: Path):
    """`differing lines: N` is what turns "reinstall, I guess" into a fact.

    The measured incident was 137; a one-line drift must still be reported as a
    number rather than as prose, so the next reader can size it without diffing
    two files by hand.
    """
    hook = _install_copy(sandbox, stale=True)
    p = _run_hook(sandbox, hook)
    combined = p.stdout + p.stderr
    assert "differing lines:" in combined, combined
    n = combined.split("differing lines:")[1].split("\n")[0].strip()
    assert n.isdigit() and int(n) > 0, f"not a usable count: {n!r}\n{combined}"


# ── ordering: the check must precede the branch that exits 0 ───────────────
def test_the_self_check_precedes_the_checker_early_exit():
    """LOAD-BEARING ORDER, not style.

    The hook `exit 0`s when the NDA checker is missing. A self-check placed
    after that branch would never run on precisely the hook that has drifted far
    enough to lose the checker — the case it exists for. Asserted on the code
    with comments stripped: a rule stated only in prose is not a rule.
    """
    code = "\n".join(l for l in HOOK.read_text(encoding="utf-8").splitlines()
                     if not l.lstrip().startswith("#"))
    self_check = code.index("HOOK_DECLARED=")
    early_exit = code.index("NDA message guard not found")
    assert self_check < early_exit, (
        "the staleness self-check sits after the branch that exits 0 when the "
        "NDA checker is absent, so a hook stale enough to have lost the checker "
        "would exit clean without ever comparing itself")


def test_it_refuses_when_it_cannot_look_rather_than_passing(sandbox: Path):
    """A GATE THAT COULD NOT LOOK HAS NOT PASSED — the rule `run_gate` already
    applies to rc 2. With no declared hook in the tree there is nothing to
    compare against, so the installed hook's provenance is UNKNOWN, which is not
    the same as fine.
    """
    hook = _install_copy(sandbox, stale=False)
    (sandbox / "tools" / "git-hooks" / "pre-push").unlink()
    p = _run_hook(sandbox, hook)
    combined = p.stdout + p.stderr
    assert p.returncode != 0, f"an unverifiable hook was let through:\n{combined}"
    assert "BLOCKED" in combined and FIX in combined, combined


def test_the_guard_is_a_refusal_not_a_warning():
    """Stated as a property of the shipped text, because the difference is one
    keyword and the whole value of the change rests on it."""
    src = HOOK.read_text(encoding="utf-8")
    body = src[src.index("HOOK_DECLARED="):src.index("CHECKER=")]
    code = "\n".join(l for l in body.splitlines()
                     if not l.lstrip().startswith("#"))
    assert "exit 1" in code, "the self-check does not exit non-zero"
    assert "WARNING" not in code, (
        "the self-check warns; a warning about a wrong hook is printed into the "
        "scrollback of a push that succeeded")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
