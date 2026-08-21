#!/usr/bin/env python3
"""Tests for version_bump_monotonic_check.py — strict version-bump gate
(current > previous) + marketplace equality re-assert (chip-AGNOSTIC)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1] / "version_bump_monotonic_check.py"
_spec = importlib.util.spec_from_file_location("version_bump_monotonic_check", _PROG)
vbm = importlib.util.module_from_spec(_spec)
sys.modules["version_bump_monotonic_check"] = vbm
_spec.loader.exec_module(vbm)


# ---- explicit two-value compare (no git) --------------------------------
def test_pass_patch_bump():
    assert vbm.main(["--current", "0.2.14", "--previous", "0.2.13"]) == 0


def test_pass_minor_bump():
    assert vbm.main(["--current", "0.3.0", "--previous", "0.2.99"]) == 0


def test_pass_numeric_not_lexical():
    # 0.2.10 > 0.2.9 numerically (lexical would say the opposite).
    assert vbm.main(["--current", "0.2.10", "--previous", "0.2.9"]) == 0


def test_fail_no_bump_equal():
    assert vbm.main(["--current", "0.2.13", "--previous", "0.2.13"]) == 1


def test_fail_regression():
    assert vbm.main(["--current", "0.2.12", "--previous", "0.2.13"]) == 1


def test_error_unparseable_current():
    assert vbm.main(["--current", "garbage", "--previous", "0.2.13"]) == 2


def test_error_unparseable_previous():
    assert vbm.main(["--current", "0.2.14", "--previous", ""]) == 2


# ---- evaluate() equality re-assert --------------------------------------
def test_evaluate_equality_mismatch_fails():
    rep, rc = vbm.evaluate("0.2.14", "0.2.13", "0.2.13", equality_checked=True)
    assert rc == 1
    assert rep.equality_ok is False


def test_evaluate_equality_ok():
    rep, rc = vbm.evaluate("0.2.14", "0.2.13", "0.2.14", equality_checked=True)
    assert rc == 0
    assert rep.bump_ok is True
    assert rep.equality_ok is True


# ---- git-backed path (real synthetic repo) ------------------------------
def _git(repo: Path, *args):
    subprocess.run(["git", "-C", str(repo), *args],
                   check=True, capture_output=True, text=True)


def _stage_repo(tmp_path: Path, first_ver: str) -> Path:
    repo = tmp_path / "repo"
    pjdir = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / ".claude-plugin"
    pjdir.mkdir(parents=True)
    pj = pjdir / "plugin.json"
    pj.write_text(json.dumps({"name": "vibe-ic", "version": first_ver}) + "\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"v{first_ver}")
    return pj


def test_git_pass_after_bump(tmp_path):
    pj = _stage_repo(tmp_path, "0.2.13")
    # working-tree bump (not yet committed) -> compares vs HEAD = 0.2.13.
    pj.write_text(json.dumps({"name": "vibe-ic", "version": "0.2.14"}) + "\n")
    rc = vbm.main(["--plugin-json", str(pj), "--base", "HEAD"])
    assert rc == 0


def test_git_fail_when_not_bumped(tmp_path):
    pj = _stage_repo(tmp_path, "0.2.13")
    # forgot to bump -> working tree == HEAD == 0.2.13 -> FAIL.
    rc = vbm.main(["--plugin-json", str(pj), "--base", "HEAD"])
    assert rc == 1


def test_git_with_marketplace_equality(tmp_path):
    pj = _stage_repo(tmp_path, "0.2.13")
    pj.write_text(json.dumps({"name": "vibe-ic", "version": "0.2.14"}) + "\n")
    mj = tmp_path / "repo" / "vibe-ic-marketplace" / ".claude-plugin" / "marketplace.json"
    mj.parent.mkdir(parents=True, exist_ok=True)
    mj.write_text(json.dumps({"plugins": [{"name": "vibe-ic", "version": "0.2.14"}]}) + "\n")
    out = tmp_path / "r.json"
    rc = vbm.main(["--plugin-json", str(pj), "--marketplace-json", str(mj),
                   "--base", "HEAD", "--json", str(out)])
    assert rc == 0
    rep = json.loads(out.read_text())
    assert rep["passed"] is True
    assert rep["equality_ok"] is True


def test_git_marketplace_mismatch_fails(tmp_path):
    pj = _stage_repo(tmp_path, "0.2.13")
    pj.write_text(json.dumps({"name": "vibe-ic", "version": "0.2.14"}) + "\n")
    mj = tmp_path / "repo" / "vibe-ic-marketplace" / ".claude-plugin" / "marketplace.json"
    mj.parent.mkdir(parents=True, exist_ok=True)
    mj.write_text(json.dumps({"plugins": [{"name": "vibe-ic", "version": "0.2.13"}]}) + "\n")
    rc = vbm.main(["--plugin-json", str(pj), "--marketplace-json", str(mj),
                   "--base", "HEAD"])
    assert rc == 1


# ---- honest errors on absent input --------------------------------------
def test_missing_plugin_json_is_error(tmp_path):
    assert vbm.main(["--plugin-json", str(tmp_path / "nope.json")]) == 2


def test_no_args_is_error():
    assert vbm.main([]) == 2


# =========================================================================
# THREE CASES, NOT TWO  (regression tests for the always-red PR gate)
#
# The gate used to reduce current-vs-previous to ONE boolean (cur > prev), so
# "no version change" and "version went BACKWARDS" shared exit code 1. Because
# the documented workflow is that authoring PRs are VERSION-LESS (the
# gatekeeper assigns the version at merge), the gate failed on EVERY
# conforming PR and carried no information.
#
# These tests pin the public behaviour — EXIT CODE + MESSAGE — of all three
# cases. The tests ABOVE are unchanged and still pin the STRICT default, which
# the direct-push loop and the gatekeeper's post-assignment re-run rely on.
# =========================================================================

_GK = "--version-by-gatekeeper"


def _msg(capsys) -> str:
    return capsys.readouterr().out


# ---- 1. no version change -> PASS under the version-less-PR flag --------
def test_versionless_pr_no_change_passes(capsys):
    """The documented normal path. This is the case that used to fail."""
    assert vbm.main(["--current", "1.5.10", "--previous", "1.5.10", _GK]) == 0
    out = _msg(capsys)
    assert "[PASS]" in out
    assert "version-less" in out


def test_versionless_pr_no_change_reports_unchanged_not_bumped(capsys):
    """The report must name the case, so the two are never conflated again."""
    rep, rc = vbm.evaluate("1.5.10", "1.5.10", None, False,
                           version_by_gatekeeper=True)
    assert rc == 0
    assert rep.change == "unchanged"
    assert rep.deferred is True
    assert rep.bump_ok is False        # it PASSED without a bump — distinct facts


# ---- 2. monotonic bump -> PASS (with or without the flag) --------------
def test_monotonic_bump_passes_with_flag(capsys):
    assert vbm.main(["--current", "1.5.11", "--previous", "1.5.10", _GK]) == 0
    assert "[PASS]" in _msg(capsys)


def test_monotonic_bump_passes_without_flag(capsys):
    assert vbm.main(["--current", "1.5.11", "--previous", "1.5.10"]) == 0
    assert "[PASS]" in _msg(capsys)


def test_minor_rollover_bump_passes(capsys):
    # x.y.99 -> x.(y+1).0 is the BINDING scheme in gatekeeper_assign_version.
    assert vbm.main(["--current", "1.6.0", "--previous", "1.5.99", _GK]) == 0
    assert "[PASS]" in _msg(capsys)


# ---- 3. backwards -> FAIL, and the flag must NOT excuse it -------------
def test_backwards_bump_fails_even_with_flag(capsys):
    """THE anti-weakening test. If this ever passes, the gate is useless."""
    assert vbm.main(["--current", "1.5.9", "--previous", "1.5.10", _GK]) == 1
    out = _msg(capsys)
    assert "[FAIL]" in out
    assert "REGRESSED" in out


def test_backwards_minor_fails_with_flag(capsys):
    assert vbm.main(["--current", "1.4.79", "--previous", "1.5.10", _GK]) == 1
    assert "[FAIL]" in _msg(capsys)


def test_backwards_major_fails_with_flag(capsys):
    assert vbm.main(["--current", "0.9.0", "--previous", "1.5.10", _GK]) == 1
    assert "[FAIL]" in _msg(capsys)


def test_regression_and_no_bump_have_DISTINCT_messages(capsys):
    """The root cause was that these two produced the same verdict."""
    vbm.main(["--current", "1.5.10", "--previous", "1.5.10"])
    unchanged = _msg(capsys)
    vbm.main(["--current", "1.5.9", "--previous", "1.5.10"])
    regressed = _msg(capsys)
    assert unchanged != regressed
    assert "not bumped" in unchanged and "REGRESSED" not in unchanged
    assert "REGRESSED" in regressed


# ---- 4. skipped version -> PASS, deliberately, WITH a stated reason -----
def test_skipped_version_passes_but_is_reported(capsys):
    """Repo convention (gatekeeper_assign_version.next_version) is strictly
    +1 patch, so a GAP is not normal. It is still not failed HERE: this
    program's baseline is the PR's merge-base, and `main` advances many times
    a day, so a conforming PR can legitimately sit several versions behind its
    base. The one-step rule is enforced by gatekeeper_assign_version.py at the
    moment of assignment, where the baseline is CURRENT main. Failing a gap
    here would re-create the same always-red bug in a new place."""
    assert vbm.main(["--current", "1.5.20", "--previous", "1.5.10", _GK]) == 0
    out = _msg(capsys)
    assert "[PASS]" in out
    assert "non-adjacent" in out          # reported, never silent


def test_adjacent_bump_is_not_flagged_non_adjacent(capsys):
    vbm.main(["--current", "1.5.11", "--previous", "1.5.10", _GK])
    assert "non-adjacent" not in _msg(capsys)


# ---- malformed still an honest ERROR, never a silent pass --------------
def test_malformed_current_is_error_even_with_flag():
    assert vbm.main(["--current", "not-a-version", "--previous", "1.5.10", _GK]) == 2


def test_malformed_previous_is_error_even_with_flag():
    assert vbm.main(["--current", "1.5.11", "--previous", "1.5.x", _GK]) == 2


# ---- marketplace equality stays enforced in the unchanged case ---------
def test_unchanged_still_enforces_marketplace_equality():
    rep, rc = vbm.evaluate("1.5.10", "1.5.10", "1.5.9", equality_checked=True,
                           version_by_gatekeeper=True)
    assert rc == 1
    assert rep.equality_ok is False


# =========================================================================
# GIT-BACKED FIXTURES — real repo, real commits, real `--base <sha>`, exactly
# as .github/workflows/gatekeeper-ci.yml invokes it.
#
# The negative control switches fixtures with `git checkout` (NEVER
# `git stash`), so the PASS cases are proven non-vacuous: the same harness
# that returns 0 on a version-less PR returns 1 on a backwards one.
# =========================================================================

_PJ_REL = "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json"


def _write_ver(pj: Path, ver: str) -> None:
    pj.parent.mkdir(parents=True, exist_ok=True)
    pj.write_text(json.dumps({"name": "vibe-ic", "version": ver}) + "\n")


def _pr_repo(tmp_path: Path, base_ver: str) -> tuple:
    """A repo whose `main` sits at base_ver. Returns (repo, pj, base_sha)."""
    repo = tmp_path / "repo"
    pj = repo / _PJ_REL
    _write_ver(pj, base_ver)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"release v{base_ver}")
    base_sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    return repo, pj, base_sha


def _branch_with(repo: Path, pj: Path, name: str, ver: str = None,
                 touch_only: bool = False) -> None:
    """Create branch `name` off main; optionally set the version on it."""
    _git(repo, "checkout", "-q", "-b", name, "main")
    if touch_only:
        (repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
         / "programs").mkdir(parents=True, exist_ok=True)
        (repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
         / "programs" / "some_fix.py").write_text("# a real code fix\n")
    if ver is not None:
        _write_ver(pj, ver)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"work on {name}")


def test_git_versionless_pr_passes(tmp_path, capsys):
    """FIXTURE 1: a PR that changes code but NOT the version -> PASS.

    This is the shape of every PR that failed the old gate."""
    repo, pj, base = _pr_repo(tmp_path, "1.5.10")
    _branch_with(repo, pj, "fix/some-real-bug", ver=None, touch_only=True)
    rc = vbm.main(["--plugin-json", str(pj), "--base", base, _GK])
    assert rc == 0
    assert "[PASS]" in _msg(capsys)


def test_git_monotonic_bump_passes(tmp_path, capsys):
    """FIXTURE 2: the gatekeeper's post-assignment tree -> PASS."""
    repo, pj, base = _pr_repo(tmp_path, "1.5.10")
    _branch_with(repo, pj, "release/next", ver="1.5.11")
    rc = vbm.main(["--plugin-json", str(pj), "--base", base, _GK])
    assert rc == 0
    assert "[PASS]" in _msg(capsys)


def test_git_backwards_bump_fails(tmp_path, capsys):
    """FIXTURE 3: the REAL defect -> FAIL. Must stay red forever."""
    repo, pj, base = _pr_repo(tmp_path, "1.5.10")
    _branch_with(repo, pj, "bad/rollback", ver="1.5.9")
    rc = vbm.main(["--plugin-json", str(pj), "--base", base, _GK])
    assert rc == 1
    assert "REGRESSED" in _msg(capsys)


def test_git_skipped_version_passes_reported(tmp_path, capsys):
    """FIXTURE 4: a gap -> PASS with the gap named (see rationale above)."""
    repo, pj, base = _pr_repo(tmp_path, "1.5.10")
    _branch_with(repo, pj, "jump/skip", ver="1.5.20")
    rc = vbm.main(["--plugin-json", str(pj), "--base", base, _GK])
    assert rc == 0
    assert "non-adjacent" in _msg(capsys)


def test_git_NEGATIVE_CONTROL_checkout_flips_the_verdict(tmp_path, capsys):
    """NEGATIVE CONTROL (git checkout, never git stash).

    One repo, one base sha, one command — only the checked-out branch differs.
    Proves the version-less PASS is a real measurement and not the check
    silently passing everything: the identical invocation returns 0 on the
    version-less branch and 1 on the backwards branch."""
    repo, pj, base = _pr_repo(tmp_path, "1.5.10")
    _branch_with(repo, pj, "pr/versionless", ver=None, touch_only=True)
    _git(repo, "checkout", "-q", "main")
    _branch_with(repo, pj, "pr/backwards", ver="1.5.9")

    argv = ["--plugin-json", str(pj), "--base", base, _GK]

    _git(repo, "checkout", "-q", "pr/versionless")
    rc_versionless = vbm.main(argv)
    out_versionless = _msg(capsys)

    _git(repo, "checkout", "-q", "pr/backwards")
    rc_backwards = vbm.main(argv)
    out_backwards = _msg(capsys)

    assert rc_versionless == 0, "version-less PR must PASS"
    assert rc_backwards == 1, "backwards version must FAIL"
    assert rc_versionless != rc_backwards, "gate cannot discriminate — useless"
    assert "version-less" in out_versionless
    assert "REGRESSED" in out_backwards


# ---- the STALE-BASE case: main moved on while the PR sat open -----------
# `--base` is the base-BRANCH TIP (github.event.pull_request.base.sha), not a
# merge-base. This repo bumps versions dozens of times a day, so an open
# version-less PR is routinely BEHIND main. If the gate inferred "version-less"
# only from `cur == prev`, it would call these PRs REGRESSED and go red again
# for a new reason. The diff is the source of truth: an untouched plugin.json
# has nothing to enforce.

def test_git_versionless_pr_passes_when_main_moved_ahead(tmp_path, capsys):
    """FIXTURE 5: version-less PR + main advanced 1.5.10 -> 1.5.12."""
    repo, pj, _ = _pr_repo(tmp_path, "1.5.10")
    _branch_with(repo, pj, "pr/versionless", ver=None, touch_only=True)
    # main marches on without this PR.
    _git(repo, "checkout", "-q", "main")
    _write_ver(pj, "1.5.12")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "release v1.5.12")
    new_main = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    # The PR head is checked out; base is the NEW main tip.
    _git(repo, "checkout", "-q", "pr/versionless")
    rc = vbm.main(["--plugin-json", str(pj), "--base", new_main, _GK])
    assert rc == 0, "a version-less PR must not fail because main moved"
    assert "version-less" in _msg(capsys)


def test_git_backwards_STILL_fails_when_main_moved_ahead(tmp_path, capsys):
    """The anti-weakening counterpart of the test above: a PR that ACTUALLY
    edits plugin.json backwards is still caught in the same stale-base
    situation. The escape hatch is keyed to an untouched file, not to being
    behind main."""
    repo, pj, _ = _pr_repo(tmp_path, "1.5.10")
    _branch_with(repo, pj, "bad/rollback", ver="1.5.9")   # touches the file
    _git(repo, "checkout", "-q", "main")
    _write_ver(pj, "1.5.12")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "release v1.5.12")
    new_main = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()
    _git(repo, "checkout", "-q", "bad/rollback")
    rc = vbm.main(["--plugin-json", str(pj), "--base", new_main, _GK])
    assert rc == 1
    assert "REGRESSED" in _msg(capsys)


def test_unknown_touch_state_never_becomes_a_silent_pass():
    """version_file_touched=None (git could not answer) must NOT be treated as
    'untouched'. An unknown falls through to the normal comparison."""
    rep, rc = vbm.evaluate("1.5.9", "1.5.10", None, False,
                           version_by_gatekeeper=True,
                           version_file_touched=None)
    assert rc == 1
    assert rep.change == "regressed"


def test_git_versionless_pr_STILL_FAILS_without_the_flag(tmp_path):
    """The strict default is intact: the direct-push loop and the
    gatekeeper's post-assignment re-run still REQUIRE a real bump."""
    repo, pj, base = _pr_repo(tmp_path, "1.5.10")
    _branch_with(repo, pj, "fix/some-real-bug", ver=None, touch_only=True)
    assert vbm.main(["--plugin-json", str(pj), "--base", base]) == 1
