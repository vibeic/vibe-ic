"""A pre-push gate must not inherit the hook's GIT_DIR — vibe-ic#636.

Git exports `GIT_DIR` (and, in a worktree, `GIT_WORK_TREE`) when it runs a hook.
`git -C <dir>` does NOT override an explicitly-set `GIT_DIR`, so every gate that
resolves paths or ranges with `git -C <repo>` silently answered about the wrong
root. Measured: the version gate said `cannot read plugin.json version at
origin/main` and the hook exited 2 — a push blocked with, at the time, no
diagnosis at all — while the identical command run by hand passed.

The failure only appears under a REAL push: every manual reproduction runs
without GIT_DIR, which is why the gate looked healthy when tested directly.
"""
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]
HOOK = REPO / "tools" / "git-hooks" / "pre-push"

pytestmark = pytest.mark.skipif(not HOOK.is_file(), reason="hook not in this tree")


def _run_gate_body() -> str:
    src = HOOK.read_text(encoding="utf-8")
    start = src.index("run_gate()")
    return src[start:src.index("\n}", start)]


def test_the_gate_invocation_strips_the_inherited_git_environment():
    """The structural pin: whatever else run_gate does, it must not hand the
    gate programs an inherited GIT_DIR."""
    body = _run_gate_body()
    assert "python3" in body, "run_gate no longer invokes python3 — re-read this test"
    invocation = [ln for ln in body.splitlines() if "python3" in ln and "$prog" in ln]
    assert invocation, "could not find the gate invocation line"
    assert all("env -u GIT_DIR" in ln and "-u GIT_WORK_TREE" in ln for ln in invocation), (
        "a gate is invoked without stripping GIT_DIR/GIT_WORK_TREE; under a real "
        "push git exports them and the gate resolves against the wrong root "
        "(vibe-ic#636)\n" + "\n".join(invocation))


def test_the_premise_holds_a_real_gate_IS_git_dir_sensitive():
    """PREMISE PIN, not a control for the fix — and labelled so.

    The strip in `run_gate` is only load-bearing while some gate actually answers
    differently under an inherited GIT_DIR. This asserts that it does, so the day
    the gates stop caring, this test fails and the strip can be reconsidered on
    evidence rather than kept as folklore.

    It does NOT detect a regression of the fix — removing the strip leaves this
    green, because it exercises the gate directly rather than through the hook.
    `test_the_gate_invocation_strips_the_inherited_git_environment` is the control.
    """
    prog = REPO / "vibe-ic-marketplace/plugins/vibe-ic/programs/version_bump_monotonic_check.py"
    pj = REPO / "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json"
    if not prog.is_file() or not pj.is_file():
        pytest.skip("gate or manifest not present in this tree")
    git_dir = subprocess.run(["git", "-C", str(REPO), "rev-parse", "--absolute-git-dir"],
                             capture_output=True, text=True).stdout.strip()
    if not git_dir:
        pytest.skip("not a git checkout")

    argv = ["python3", str(prog), "--plugin-json", str(pj),
            "--base", "origin/main", "--version-by-gatekeeper"]
    clean = dict(os.environ); clean.pop("GIT_DIR", None); clean.pop("GIT_WORK_TREE", None)
    dirty = dict(clean); dirty["GIT_DIR"] = git_dir

    # 30 s, MEASURED not guessed: the gate this drives runs in 0.06 s. The
    # ceiling that matters is the harness's 180 s — an inner bound above 60 s
    # can outlive it and kill the SESSION instead of the test, which
    # `ci_harness_timeout_ceiling_check` failed this file on at merge.
    ok = subprocess.run(argv, capture_output=True, text=True, cwd=str(REPO),
                        env=clean, timeout=30)
    bad = subprocess.run(argv, capture_output=True, text=True, cwd=str(REPO),
                         env=dirty, timeout=30)
    if ok.returncode != 0:
        pytest.skip(f"gate does not pass cleanly here: {ok.stdout.strip()[:120]}")
    assert bad.returncode != 0, (
        "the premise no longer holds: this gate answers identically with an "
        "inherited GIT_DIR, so run_gate's env strip is no longer load-bearing "
        "and should be re-justified rather than kept by habit")
