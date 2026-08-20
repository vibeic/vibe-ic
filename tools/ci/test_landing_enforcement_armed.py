"""The chain ends in a hook, and `.git/hooks/` is not tracked by git.

`landing_enforcement_armed_check` exists because the fix for this defect was
applied ONCE, by hand, and came back. `d6ea46e9c` (2026-07-30, v1.8.39) —
subject line "pre-push: the hooks were never installed, and CI is never coming
back" — found `.git/hooks/` empty, installed the hooks with
`tools/install-git-hooks.sh`, and wrote it down. Twenty-two days later the
directory holds only git's `.sample` files again, on every one of the 54 `.git`
directories on the machine those landings were made from, and fourteen
consecutive landings (v1.11.5 .. v1.11.18) went past a gate declared always-run
and BLOCKING that was red at all of them.

An action on an untracked directory is exactly as durable as the machine it ran
on. This file pins the CHECK that the action was not.

EVERY DIRECTION, because a checker that refused everything would satisfy the
disarmed cases and enforce nothing: armed by symlink, armed by copy, absent,
foreign, non-executable, redirected by `core.hooksPath` both ways, and the three
distinct "I could not look" cases which must be rc 2 and never rc 0.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[1]
sys.path.insert(0, str(_HERE))

import landing_enforcement_armed_check as A       # noqa: E402

_TRACKED = _REPO / A.TRACKED_HOOK_REL


def _repo(tmp_path: Path, *, with_tracked_hook: bool = True) -> Path:
    """A throwaway checkout carrying this repo's tracked hook, or not."""
    r = tmp_path / "repo"
    (r / "tools" / "git-hooks").mkdir(parents=True)
    if with_tracked_hook:
        (r / A.TRACKED_HOOK_REL).write_bytes(_TRACKED.read_bytes())
    (r / "f.txt").write_text("x\n")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True)
    return r


def _install(repo: Path, *, symlink: bool) -> Path:
    """Arm the checkout the way `tools/install-git-hooks.sh` does, or by copy."""
    hd = repo / ".git" / "hooks"
    hd.mkdir(parents=True, exist_ok=True)
    dst = hd / "pre-push"
    src = repo / A.TRACKED_HOOK_REL
    if symlink:
        dst.symlink_to(src)
    else:
        dst.write_bytes(src.read_bytes())
    dst_real = dst if not symlink else src
    dst_real.chmod(dst_real.stat().st_mode | stat.S_IXUSR)
    return dst


# --------------------------------------------------------------------------- #
# ARMED
# --------------------------------------------------------------------------- #
def test_a_symlinked_hook_is_armed(tmp_path):
    """The shape `tools/install-git-hooks.sh` actually produces: a symlink, so
    that a later `git pull` improving the hook takes effect with no re-install.
    """
    r = _repo(tmp_path)
    _install(r, symlink=True)
    assert A.main(["--repo", str(r)]) == A.RC_OK


def test_a_byte_identical_copy_is_armed_too(tmp_path):
    """Some installers copy. The question is whether the hook that will run IS
    this repository's, not how it got there."""
    r = _repo(tmp_path)
    _install(r, symlink=False)
    assert A.main(["--repo", str(r)]) == A.RC_OK


def test_core_hooksPath_is_honoured_when_it_points_at_an_armed_dir(tmp_path):
    r = _repo(tmp_path)
    alt = tmp_path / "elsewhere"
    alt.mkdir()
    (alt / "pre-push").write_bytes((r / A.TRACKED_HOOK_REL).read_bytes())
    (alt / "pre-push").chmod(0o755)
    subprocess.run(["git", "-C", str(r), "config", "core.hooksPath", str(alt)],
                   check=True)
    assert A.main(["--repo", str(r)]) == A.RC_OK


# --------------------------------------------------------------------------- #
# DISARMED
# --------------------------------------------------------------------------- #
def test_the_measured_defect_no_hook_at_all(tmp_path):
    """THE ONE THAT HAPPENED, twice. `.git/hooks/` exists and holds nothing but
    the samples git ships."""
    r = _repo(tmp_path)
    hd = r / ".git" / "hooks"
    hd.mkdir(parents=True, exist_ok=True)
    (hd / "pre-push.sample").write_text("#!/bin/sh\nexit 0\n")
    rep = A.inspect(r)
    assert A.main(["--repo", str(r)]) == A.RC_DISARMED
    assert rep["installed"] is False
    assert any("install-git-hooks" in p for p in rep["problems"]), (
        "the refusal does not say how to arm it")


def test_core_hooksPath_pointing_at_an_EMPTY_dir_is_disarmed(tmp_path):
    """The one way an installed hook can be present and still never run: git
    looks somewhere else. `.git/hooks/` is fully armed here and the answer is
    still DISARMED, which is the whole reason the path is asked of git."""
    r = _repo(tmp_path)
    _install(r, symlink=True)
    empty = tmp_path / "empty"
    empty.mkdir()
    subprocess.run(["git", "-C", str(r), "config", "core.hooksPath", str(empty)],
                   check=True)
    assert A.main(["--repo", str(r)]) == A.RC_DISARMED


def test_a_FOREIGN_hook_is_disarmed_not_armed(tmp_path):
    """Harder to notice than a missing one, because the directory looks armed."""
    r = _repo(tmp_path)
    hd = r / ".git" / "hooks"
    hd.mkdir(parents=True, exist_ok=True)
    (hd / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    (hd / "pre-push").chmod(0o755)
    rep = A.inspect(r)
    assert A.main(["--repo", str(r)]) == A.RC_DISARMED
    assert rep["installed"] is True and rep["authentic"] is False, rep


def test_a_present_but_NON_EXECUTABLE_hook_is_disarmed(tmp_path):
    r = _repo(tmp_path)
    dst = _install(r, symlink=False)
    dst.chmod(dst.stat().st_mode & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    assert A.main(["--repo", str(r)]) == A.RC_DISARMED


def test_a_hook_that_stopped_reading_the_stamp_is_disarmed(tmp_path):
    """An armed hook that no longer consumes `.git/gatekeeper-stamp` is armed at
    nothing. Same silence, new place — so it is a separate finding rather than
    something the INSTALLED answer absorbs."""
    r = _repo(tmp_path)
    t = r / A.TRACKED_HOOK_REL
    t.write_text(t.read_text(errors="replace")
                 .replace(A.STAMP_BASENAME, "some-other-artefact"))
    _install(r, symlink=True)
    rep = A.inspect(r)
    assert A.main(["--repo", str(r)]) == A.RC_DISARMED
    assert rep["installed"] is True and rep["consumer"] is False, rep


# --------------------------------------------------------------------------- #
# COULD NOT LOOK -- rc 2, never rc 0
# --------------------------------------------------------------------------- #
def test_a_directory_that_is_not_a_checkout_is_UNDETERMINED(tmp_path):
    d = tmp_path / "plain"
    d.mkdir()
    assert A.main(["--repo", str(d)]) == A.RC_UNDETERMINED


def test_a_checkout_without_the_tracked_hook_is_UNDETERMINED(tmp_path):
    """No reference to compare against. Reporting ARMED would be a guess and
    reporting DISARMED would blame the checkout for the checker's blindness."""
    r = _repo(tmp_path, with_tracked_hook=False)
    _install_dir = r / ".git" / "hooks"
    _install_dir.mkdir(parents=True, exist_ok=True)
    rep = A.inspect(r)
    assert A.main(["--repo", str(r)]) == A.RC_UNDETERMINED
    assert rep["undetermined"] and not rep["problems"], rep


def test_the_three_verdicts_are_three_different_exit_codes():
    """The floor this whole family of defects sits on: a checker whose "could
    not look" and "looked and it was fine" share an exit code is one more green
    light standing in for an absence."""
    assert len({A.RC_OK, A.RC_DISARMED, A.RC_UNDETERMINED}) == 3


# --------------------------------------------------------------------------- #
# The live answer, recorded rather than enforced
# --------------------------------------------------------------------------- #
def test_this_checkouts_live_answer_is_reported(record_property):
    """NOT an assertion about this machine.

    A test that demanded an armed hook would fail inside the hermetic runner,
    where the subject is mounted read-only and there is no `.git` at all — and a
    gate that cannot pass in the venue it runs in gets switched off. The verdict
    is PUBLISHED as a run property instead, so a reader of the junit sees what
    this checkout actually is, and `RESULT.md` / the lander decide what to do
    about it.
    """
    rep = A.inspect(_REPO)
    record_property("landing_enforcement", str(rep.get("verdict") or "?"))
    record_property("landing_enforcement_hooks_dir", str(rep.get("hooks_dir")))
    assert rep.get("installed") is not None or rep.get("undetermined"), (
        "the checker neither answered nor said it could not look")
