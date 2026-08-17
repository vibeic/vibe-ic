"""Landing from a worktree was impossible, and the failure named neither cause.

`gatekeeper-land.sh` writes the verified commit to a stamp; the pre-push hook
refuses a push to main whose stamp does not name the commit being pushed. Both
computed the path as `$(git rev-parse --show-toplevel)/.git/gatekeeper-stamp`.

In a WORKTREE `.git` is a FILE — a `gitdir:` pointer — so:

    writer   `git rev-parse HEAD > .../batch/.git/gatekeeper-stamp`
             -> bash: .../batch/.git/gatekeeper-stamp: Not a directory
             -> no stamp, and the landing script had already printed
                "=== ALL GATES PASS — stamped <sha> ==="
    reader   `[ ! -f "$REPO_ROOT/.git/gatekeeper-stamp" ]` -> true
             -> "the full suites have not been run for this commit"

Every gate had passed. The message said they had not been run. The two halves
agreed on a broken path, so neither could see the other's problem, and the one
observable symptom — a redirect error on stderr — appeared AFTER the success
line.

MEASURED in the worktree that found it:

    old expression   write fails "Not a directory"   stamp present: NO
    new expression   write succeeds                  stamp present: yes, == HEAD

`--absolute-git-dir` is PER-WORKTREE (.git/worktrees/<name>), which is what this
stamp must be: two worktrees at different commits must not share one, or a gate
run in one would authorise a push from the other. In the main checkout it
resolves to the same `.git` as before, so the previously-working case is
unchanged.
"""
from __future__ import annotations

import pathlib
import re
import subprocess

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_REPO = _PROGRAMS.parents[3]
_LAND = _REPO / "tools/gatekeeper-land.sh"
_HOOK = _REPO / "tools/git-hooks/pre-push"

_EXPR = "git rev-parse --absolute-git-dir"


def _bodies():
    out = []
    for p in (_LAND, _HOOK):
        src = p.read_text(encoding="utf-8")
        out.append((p.name, "\n".join(l for l in src.splitlines()
                                      if not l.lstrip().startswith("#"))))
    return out


def test_neither_side_builds_the_path_from_the_worktree_root():
    """The defect, in one assertion. `<toplevel>/.git` is a FILE in a worktree,
    so a path built that way can neither be written nor read."""
    for name, body in _bodies():
        assert ".git/gatekeeper-stamp" not in body.replace(
            "gatekeeper-stamp", "", 0) or "/.git/gatekeeper-stamp" not in body, name
        assert "$ROOT/.git/gatekeeper-stamp" not in body, name
        assert "$REPO_ROOT/.git/gatekeeper-stamp" not in body, name


def test_both_sides_name_the_stamp_the_same_way():
    """LOAD-BEARING. A writer and a reader that compute the path differently
    produce exactly this failure in reverse: a stamp written where nobody looks
    reads as 'not verified' forever, and the gate becomes unpassable rather than
    bypassable."""
    for name, body in _bodies():
        assert _EXPR in body, name


def test_the_removal_path_uses_it_too():
    """On FAILURE the script removes the stamp so a stale one cannot authorise
    the next push. Removing the wrong path leaves a real stamp in place — the
    one direction of this bug that fails OPEN."""
    body = dict(_bodies())["gatekeeper-land.sh"]
    # anchor on the REMOVAL OF THE STAMP, not on the first `rm -f` in the file —
    # that one is an unrelated EXIT trap for the fingerprint temp file, and
    # matching it made this test pass while asserting nothing about the stamp.
    rms = [l for l in body.splitlines()
           if "rm -f" in l and "gatekeeper-stamp" in l]
    # THE ROSTER, exact on purpose: adding a refusal path that forgets the stamp
    # is invisible, so the count is asserted and a new path has to come here and
    # say so. Four paths drop it today:
    #
    #   1. the terminal failure block          — any gate failed
    #   2. the composite NO_STAMP path         — merge verification owns the join
    #   3. the cheap-tier refusal              — the full tier is not entered
    #   4. the mid-round fingerprint abort     — the tree moved under the gates
    #
    # 3 and 4 exit BEFORE the terminal block, so without their own removal a
    # stale stamp from an earlier round would survive a red one — the one
    # direction of this bug that fails OPEN. All four must resolve the same
    # per-worktree location the writer and the hook use.
    assert len(rms) == 4, rms
    assert all(_EXPR in line for line in rms)


def test_it_resolves_to_a_real_directory_here(tmp_path):
    """RUN, not read: whatever this repo is checked out as — main clone or
    worktree — the expression must name a directory that can be written."""
    d = subprocess.run(["git", "-C", str(_REPO), "rev-parse",
                        "--absolute-git-dir"],
                       capture_output=True, text=True, timeout=30)
    assert d.returncode == 0, d.stderr
    p = pathlib.Path(d.stdout.strip())
    assert p.is_dir(), f"{p} is not a directory"


def test_a_worktree_gets_its_own_stamp_not_a_shared_one():
    """Per-worktree is the point, not an accident of the expression: a shared
    stamp would let a gate run in one worktree authorise a push of a DIFFERENT
    commit from another."""
    def _rp(flag):
        out = subprocess.run(["git", "-C", str(_REPO), "rev-parse", flag],
                             capture_output=True, text=True,
                             timeout=30).stdout.strip()
        # RESOLVE BOTH. `--git-common-dir` answers RELATIVE (".git") in a main
        # checkout while `--absolute-git-dir` is absolute, so comparing the raw
        # strings says "these differ" about one directory — and this test then
        # asserted the main checkout was a worktree. Measured: it failed in the
        # main checkout while passing in every worktree, which is the one place
        # a stamp test must not be wrong.
        return (_REPO / out).resolve()

    common, own = _rp("--git-common-dir"), _rp("--absolute-git-dir")
    if own == common:
        return                      # main checkout: they coincide, by design
    assert "worktrees" in own.as_posix(), own


def test_the_success_line_and_the_write_cannot_disagree_silently():
    """The write must come BEFORE the 'ALL GATES PASS — stamped' line, so a
    failing write cannot be reported as a successful stamp. This is what made
    the original so hard to see: the error printed after the success."""
    body = dict(_bodies())["gatekeeper-land.sh"]
    w = body.index("gatekeeper-stamp")
    s = body.index("ALL GATES PASS")
    assert w < s, "the stamp is announced before it is written"
