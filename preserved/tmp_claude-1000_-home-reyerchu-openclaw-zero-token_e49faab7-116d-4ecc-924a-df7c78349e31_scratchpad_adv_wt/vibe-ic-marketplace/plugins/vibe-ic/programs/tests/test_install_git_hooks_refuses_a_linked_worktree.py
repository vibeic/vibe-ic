"""Installing hooks from a linked worktree disarms the NDA guard for everyone.

`tools/install-git-hooks.sh` symlinks `tools/git-hooks/*` into the hooks dir it
gets from `git rev-parse --git-path hooks`. From a LINKED WORKTREE that answers
the SHARED `.git/hooks` — which is the point of the feature and the whole problem
here. So the `ln -s` does not configure the worktree; it points the one hook that
EVERY checkout of the repository runs at a directory that the dispatch doctrine
(work in a throwaway worktree) guarantees is temporary.

Remove the worktree and the symlink dangles. git does not complain: an
unresolvable hook path is treated as NO HOOK AT ALL — no message, no exit code,
nothing in the push output. `test_a_dangling_hook_symlink_is_silently_no_hook`
below measures that claim on this git rather than asserting it from memory,
because the entire justification for the refusal rests on it.

The hook's own staleness self-check cannot cover this case. A hook that is never
executed checks nothing. That asymmetry is why the refusal has to live in the
installer, before the symlink exists.

DETECTION, AND WHY NOT THE OBVIOUS SPELLING. Comparing `git rev-parse
--git-common-dir` to the literal string `.git` is wrong, and wrong in the
direction that breaks the ordinary case. MEASURED, git 2.34.1:

    main checkout,   cwd = toplevel   --git-common-dir  .git
    main checkout,   cwd = tools/     --git-common-dir  ../.git      <- not ".git"
    linked worktree, any cwd          --git-common-dir  <abs>/.git

`--git-common-dir` is resolved relative to CWD, so the literal test refuses a
perfectly ordinary main checkout the moment someone runs the installer from a
subdirectory. `test_a_main_checkout_installs_from_a_subdirectory_too` is that
case, and it fails against the literal spelling.

BOTH DIRECTIONS, as the repo's other hook tests do:

    main checkout                  installs        (or the guard is a ban)
    main checkout, from a subdir   installs        (or the spelling is wrong)
    linked worktree                REFUSES, and installs NOTHING
    linked worktree + --force      installs, with the warning
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _find_repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "tools" / "install-git-hooks.sh").is_file():
            return parent
    raise AssertionError("tools/install-git-hooks.sh not found above this test")


REPO = _find_repo_root()
INSTALLER = REPO / "tools" / "install-git-hooks.sh"
HOOKS_SRC = REPO / "tools" / "git-hooks"


def _env() -> dict:
    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
    )
    # A worktree-isolated caller may already carry these; they would silently
    # re-point every `git` call in the sandbox at the caller's repository.
    for stray in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(stray, None)
    return env


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    p = subprocess.run(["git", *args], cwd=str(cwd), env=_env(),
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, f"git {' '.join(args)}: {p.stderr}"
    return p


def _install(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(cwd_installer(cwd)), *args],
                          cwd=str(cwd), env=_env(), capture_output=True,
                          text=True, timeout=120)


def cwd_installer(cwd: Path) -> Path:
    """The installer INSIDE the sandbox, not this repo's copy.

    Running the repo's own file against a sandbox cwd would work, but it would
    also silently keep passing if the sandbox stopped containing an installer at
    all — and the sandbox copy is what a user actually invokes.
    """
    for parent in [cwd, *cwd.parents]:
        candidate = parent / "tools" / "install-git-hooks.sh"
        if candidate.is_file():
            return candidate
    raise AssertionError(f"no tools/install-git-hooks.sh at or above {cwd}")


@pytest.fixture()
def sandbox(tmp_path: Path):
    """A real repo carrying the SHIPPED installer and hooks, plus one worktree.

    Copied, not re-implemented: a fixture that reimplements the script under
    test measures the fixture.
    """
    main = tmp_path / "main"
    (main / "tools").mkdir(parents=True)
    shutil.copy2(INSTALLER, main / "tools" / "install-git-hooks.sh")
    shutil.copytree(HOOKS_SRC, main / "tools" / "git-hooks")
    _git("init", "-q", cwd=main)
    _git("add", "-A", cwd=main)
    _git("commit", "-qm", "seed", cwd=main)
    linked = tmp_path / "linked"
    _git("worktree", "add", "-q", "--detach", str(linked), cwd=main)
    return main, linked


def _hooks_dir(main: Path) -> Path:
    return main / ".git" / "hooks"


def _installed(main: Path) -> list[str]:
    d = _hooks_dir(main)
    return sorted(p.name for p in d.iterdir()
                  if p.is_symlink() and not p.name.endswith(".sample"))


# ── the direction that must keep working ───────────────────────────────────
def test_a_main_checkout_installs(sandbox):
    """The positive arm. A guard that refuses everywhere is a ban, and every
    refusal below would prove nothing without this."""
    main, _ = sandbox
    p = _install(main)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "pre-push" in _installed(main), (p.stdout + p.stderr)
    assert "REFUSING" not in p.stdout + p.stderr


def test_a_main_checkout_installs_from_a_subdirectory_too(sandbox):
    """Two defects in one cell, one of them pre-existing and silent.

    (1) The detection. Comparing `git rev-parse --git-common-dir` to the literal
    `.git` refuses here, because from `tools/` git answers `../.git`. A false
    refusal of the ordinary case, and the reason the installer resolves both
    dirs to physical paths instead.

    (2) FOUND BY WRITING (1), not by reading the script. `git rev-parse
    --git-path hooks` is relative TO CWD, and the installer joined it to
    `$REPO_ROOT`: from `tools/` that is `<repo>/../.git/hooks`, a directory
    BESIDE the repository which `mkdir -p` creates without complaint. The
    installer then printed `2 hook(s) installed` and exited 0 with the
    repository's real hooks dir still empty. rc was never the tell — the second
    assertion is, which is why it looks at the hooks dir rather than at the
    exit code or the printed count.
    """
    main, _ = sandbox
    p = _install(main / "tools")
    assert p.returncode == 0, (
        "the installer refused a MAIN checkout because it was invoked from a "
        "subdirectory:\n" + p.stdout + p.stderr)
    assert "pre-push" in _installed(main), (
        "the installer reported success and installed nothing into the "
        f"repository's hooks dir:\n{p.stdout}{p.stderr}")
    assert not (main.parent / ".git" / "hooks").exists(), (
        "hooks were installed OUTSIDE the repository, beside it — the relative "
        "`--git-path hooks` was joined to the repo root instead of to cwd")


# ── the direction that must be refused ─────────────────────────────────────
def test_a_linked_worktree_is_refused(sandbox):
    """THE DEFECT: this used to install, happily, and point the shared hook at
    a directory about to be deleted."""
    main, linked = sandbox
    p = _install(linked)
    assert p.returncode != 0, (
        "installing from a linked worktree succeeded:\n" + p.stdout + p.stderr)
    out = p.stdout + p.stderr
    assert "REFUSING" in out and "linked worktree" in out, out


def test_the_refusal_installs_nothing_at_all(sandbox):
    """A refusal that has already created half the symlinks is not a refusal.
    The check runs BEFORE the install loop; this is what pins that."""
    main, linked = sandbox
    _install(linked)
    assert _installed(main) == [], (
        "the refusal left symlinks behind in the shared hooks dir: "
        f"{_installed(main)}")


def test_the_refusal_explains_why_and_where_to_run_it(sandbox):
    """A stop with no next step gets worked around with --force by reflex.

    The message must carry the mechanism (shared hooks dir, dangling symlink,
    silence) AND the exact main-checkout path to run instead.
    """
    main, linked = sandbox
    p = _install(linked)
    out = p.stdout + p.stderr
    for expected in ("SHARED", "dangling", "NO HOOK", str(main)):
        assert expected in out, f"missing {expected!r} from the refusal:\n{out}"


def test_force_still_installs_from_a_worktree_and_says_what_it_costs(sandbox):
    """The escape hatch exists, and is not silent.

    Refusing outright would break the one legitimate case — a worktree that is
    the only checkout available — and an escape hatch that prints nothing turns
    the refusal into a speed bump nobody remembers taking.
    """
    main, linked = sandbox
    p = _install(linked, "--force")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "pre-push" in _installed(main), p.stdout + p.stderr
    out = p.stdout + p.stderr
    assert "WARNING" in out and "LINKED WORKTREE" in out, out
    # and it points INTO the worktree — which is precisely the risk it warns of
    assert str(linked) in os.readlink(_hooks_dir(main) / "pre-push")


def test_an_unknown_argument_is_not_silently_ignored(sandbox):
    """The old parser tested `$1` only, so `--frce`, or `--force` in second
    position, read as a plain install. The only flag this script has is the one
    that disarms its refusals."""
    main, _ = sandbox
    p = _install(main, "--frce")
    assert p.returncode != 0, p.stdout + p.stderr
    assert "unknown argument" in p.stdout + p.stderr


# ── the premise the whole refusal rests on, measured ───────────────────────
def test_a_dangling_hook_symlink_is_silently_no_hook(sandbox, tmp_path):
    """MEASURED, not recalled: git runs no hook and reports nothing.

    If this ever fails — a future git that errors on an unresolvable hook — the
    refusal above is arguing from a premise that has stopped being true, and
    should be re-argued rather than kept out of habit.
    """
    main, linked = sandbox
    hooks = _hooks_dir(main)
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-commit"
    if hook.exists() or hook.is_symlink():
        hook.unlink()

    # ARM 1: a hook that resolves and refuses -> the commit is blocked.
    real = tmp_path / "gone" / "pre-commit"
    real.parent.mkdir(parents=True, exist_ok=True)
    real.write_text("#!/usr/bin/env bash\necho REAL-HOOK-RAN >&2\nexit 1\n",
                    encoding="utf-8")
    real.chmod(0o755)
    hook.symlink_to(real)
    (main / "a.txt").write_text("a\n", encoding="utf-8")
    _git("add", "a.txt", cwd=main)
    armed = subprocess.run(["git", "commit", "-m", "blocked"], cwd=str(main),
                           env=_env(), capture_output=True, text=True,
                           timeout=60)
    assert armed.returncode != 0 and "REAL-HOOK-RAN" in armed.stderr, (
        "the control arm did not fire, so this test cannot tell a skipped hook "
        f"from a passing one:\n{armed.stdout}{armed.stderr}")

    # ARM 2: same symlink, target removed -> the commit SUCCEEDS, in silence.
    shutil.rmtree(real.parent)
    assert hook.is_symlink() and not hook.exists(), "the symlink is not dangling"
    dangling = subprocess.run(["git", "commit", "-m", "unguarded"],
                              cwd=str(main), env=_env(), capture_output=True,
                              text=True, timeout=60)
    assert dangling.returncode == 0, (
        "git refused the commit, so a dangling hook is NOT silent on this git — "
        f"re-argue the installer refusal:\n{dangling.stdout}{dangling.stderr}")
    assert "hook" not in (dangling.stdout + dangling.stderr).lower(), (
        "git mentioned the hook; the silence claim in the refusal message and "
        f"in tools/git-hooks/README.md needs updating:\n{dangling.stderr}")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
