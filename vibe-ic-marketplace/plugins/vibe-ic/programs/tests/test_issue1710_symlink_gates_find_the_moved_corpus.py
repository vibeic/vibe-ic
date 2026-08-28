#!/usr/bin/env python3
"""The two tracked-symlink gates after the corpus moved out (#1710's treatment).

WHY THIS FILE EXISTS
====================
`tracked_symlink_portability_check` and `tracked_symlink_target_present_check`
are one subject asked from two sides — is a committed pointer PORTABLE, and does
it point at anything. Both were aimed at a literal `benchmark-data` directory.
v1.10.56 moved the published corpus to `vibeic/benchmark-data`, and both then
answered:

    [SKIP] tracked_symlink_portability_check: no scan root                rc 2
    [NOT CHECKED] git tracks nothing at all under benchmark-data          rc 2

Both refusals were CORRECT for what they were asked — a check that could not look
has not passed. What was wrong is WHERE they were told to look. `run` in
`_gate_dispatch.sh` maps rc 2 to FAIL, so an absent corpus failed every landing
sweep, and the only way to land became bypassing the gates.

THE THREE OUTCOMES, WHICH MUST NOT COLLAPSE INTO TWO
====================================================
    pointer set + broken            -> UNDETERMINED (rc 2). Never excused, with
                                       or without --corpus-may-be-absent.
    nothing set + nothing local
      + the caller said so          -> NO_CORPUS (rc 0). Nothing scanned, and
                                       nothing CLAIMED to have been scanned.
    nothing set + nothing local
      + nobody said so              -> UNDETERMINED (rc 2). Unchanged.

EVERY CASE HERE IS PAIRED, and the pairing that matters most is the LAST GROUP:
#1700 recorded 31 dangling `steps/` pointers in that corpus. A change that only
proved "the gates stopped blocking" would pass just as well against gates that
had been deleted. So a corpus with a PLANTED DEFECT is supplied through
$VIBE_IC_BENCHMARK_DATA, with `--corpus-may-be-absent` set, and both gates must
still return rc 1 — the escape hatch must not reach the case where there IS
something to look at.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROGRAMS = Path(__file__).resolve().parents[1]
PORTABILITY = PROGRAMS / "tracked_symlink_portability_check.py"
TARGET_PRESENT = PROGRAMS / "tracked_symlink_target_present_check.py"
ENV = "VIBE_IC_BENCHMARK_DATA"


def _run(prog: Path, *args: str, env_tree: str | None = None):
    """Invoke a gate the way CI does — as a process, reading only its rc.

    The exit code is the entire contract with `_gate_dispatch.sh`; a test that
    imported `main()` and asserted on returned objects would leave the rc free
    to be anything, which is how a gate that had stopped gating once kept eight
    green tests.

    60 s, not 180 (vibe-ic#1711). 180 was the WHOLE pytest session budget, and
    with `--timeout-method=thread` a bound that large can never fire as a TEST
    failure: pytest kills the SESSION first, `--maxfail` stops applying, and
    every other file in the subset loses its verdict. 60 s is the ceiling
    `ci_harness_timeout_ceiling_check` resolves (180 // 3) and the bound 464
    other call sites in this corpus already use. MEASURED here: 18 passed in
    1.19 s, slowest item 0.04 s — 60 s cannot fire on passing work.
    """
    env = dict(os.environ)
    env.pop(ENV, None)                      # never inherit the developer's own
    if env_tree is not None:
        env[ENV] = env_tree
    r = _pr.run([sys.executable, str(prog), *args], env=env,
                       capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr)


# 60 s for the same reason as `_run` above (it was 120). These are `git init` /
# `add` / `commit` over a handful of files in a tmp_path, measured well under a
# second each; a bound of 120 could only ever be reached after the 180 s session
# clock had already killed the run.
def _git(cwd: Path, *a: str) -> None:
    _pr.run(["git", "-C", str(cwd), *a], check=True, text=False,
                   capture_output=True)


def _empty_register(tmp_path: Path) -> str:
    """An explicitly-empty baseline, so a FAIL below is about the planted defect
    and not about whatever the shipped register happens to hold today."""
    p = tmp_path / "register.json"
    p.write_text(json.dumps({"known": []}))
    return str(p)


@pytest.fixture()
def corpus_clone(tmp_path: Path) -> Path:
    """A clone-shaped corpus carrying ONE defect of each kind.

    Both defects are the real measured shapes, not stand-ins:

      * an ABSOLUTE target — #371 found 159 of 172 tracked symlinks in this
        state, and it made a gate's verdict differ between local and CI;
      * a dangling relative `steps/` pointer — the shape #1700 counted 31 of,
        a corpus stating that a step produced an artefact while pointing at
        nothing.

    It is a real git repository because both gates read git's INDEX, never a
    filesystem walk: whether a path materialises is the condition under test.
    """
    root = tmp_path / "benchmark-data-clone"
    steps = root / "ic" / "spm" / "v1.9.96_pdkX" / "steps"
    steps.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    real = root / "ic" / "spm" / "v1.9.96_pdkX" / "RESULT.json"
    real.write_text('{"verdict": "PASS"}\n')
    (steps / "repair_log.json").symlink_to("../../../../phase3/postroute_timing_repair/repair_log.json")
    (steps / "result.json").symlink_to(real)                     # ABSOLUTE
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "corpus")
    return root


@pytest.fixture()
def clean_corpus_clone(tmp_path: Path) -> Path:
    """The same shape with nothing wrong with it — the control for the arms
    below that assert a FAIL. Without it, "the gate failed" is compatible with a
    gate that fails on every corpus it is handed."""
    root = tmp_path / "clean-clone"
    steps = root / "ic" / "spm" / "v1.9.96_pdkX" / "steps"
    steps.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    real = root / "ic" / "spm" / "v1.9.96_pdkX" / "RESULT.json"
    real.write_text('{"verdict": "PASS"}\n')
    (steps / "result.json").symlink_to("../RESULT.json")         # relative, live
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "corpus")
    return root


# ===========================================================================
# 1. NOTHING ANYWHERE + the caller said so -> NO_CORPUS, rc 0, and it SAYS
#    nothing was scanned. This is the case that unblocks the removal.
# ===========================================================================
def test_portability_no_corpus_with_the_flag_is_rc0_and_says_it_scanned_nothing(
        tmp_path):
    rc, out = _run(PORTABILITY, str(tmp_path / "gone"), "--corpus-may-be-absent")
    assert rc == 0, out
    assert "NO_CORPUS" in out, out
    assert "NOTHING WAS SCANNED" in out, \
        "an rc 0 must not read as a scan that happened"
    assert "[PASS]" not in out, "a scan that did not happen was spelled as a pass"


def test_target_present_no_corpus_with_the_flag_is_rc0_and_says_it_scanned_nothing(
        tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "unrelated.txt").write_text("x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "x")
    rc, out = _run(TARGET_PRESENT, "--root", str(root), "--corpus-may-be-absent")
    assert rc == 0, out
    assert "NO_CORPUS" in out, out
    assert "NOTHING WAS SCANNED" in out, out
    assert "0 pointers adjudicated" in out, \
        "the zero must be stated, not left to be inferred from silence"
    assert "register was NOT evaluated" in out, (
        "a run that skipped the ratchet must say the ratchet was skipped, or the "
        "rc 0 covers a register nobody looked at")
    assert "[PASS]" not in out, out


# ===========================================================================
# 2. …AND WITHOUT THE FLAG BOTH STILL BLOCK. The half that makes case 1 mean
#    something: the relaxation is OPT-IN AT THE CALL SITE, not a new default.
# ===========================================================================
def test_portability_without_the_flag_is_still_undetermined(tmp_path):
    rc, out = _run(PORTABILITY, str(tmp_path / "gone"))
    assert rc == 2, f"the relaxation must be opt-in\n{out}"
    assert "UNDETERMINED" in out, out


def test_target_present_without_the_flag_is_still_undetermined(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "unrelated.txt").write_text("x\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "x")
    rc, out = _run(TARGET_PRESENT, "--root", str(root))
    assert rc == 2, f"the relaxation must be opt-in\n{out}"
    assert "not a pass" in out, out


# ===========================================================================
# 3. A BROKEN POINTER IS NEVER EXCUSED — not even with the flag. "Somebody said
#    where the corpus is and was wrong" is a different event from "there is
#    none", and a mistyped path or a no-op CI fetch step must not go green.
# ===========================================================================
def test_portability_a_broken_pointer_is_undetermined_even_with_the_flag(tmp_path):
    rc, out = _run(PORTABILITY, "--corpus-may-be-absent",
                   env_tree=str(tmp_path / "nowhere"))
    assert rc == 2, f"a set-and-wrong pointer must never be waved through\n{out}"
    assert "UNDETERMINED" in out and ENV in out, out
    assert "NO_CORPUS" not in out, "a broken pointer was laundered as an absent corpus"


def test_target_present_a_broken_pointer_is_undetermined_even_with_the_flag(tmp_path):
    rc, out = _run(TARGET_PRESENT, "--root", str(tmp_path),
                   "--corpus-may-be-absent", env_tree=str(tmp_path / "nowhere"))
    assert rc == 2, f"a set-and-wrong pointer must never be waved through\n{out}"
    assert "UNDETERMINED" in out and ENV in out, out
    assert "NO_CORPUS" not in out, out


def test_target_present_a_corpus_that_is_not_a_checkout_is_undetermined(tmp_path):
    """A loose directory of files has no index, and this gate judges what git
    TRACKS (#555). Scanning it from a walk would answer a different question and
    call it the same one."""
    loose = tmp_path / "loose"
    (loose / "ic").mkdir(parents=True)
    (loose / "ic" / "f.json").write_text("{}")
    rc, out = _run(TARGET_PRESENT, "--root", str(tmp_path),
                   "--corpus-may-be-absent", env_tree=str(loose))
    assert rc == 2, out
    assert "not a git checkout" in out, out
    assert "NO_CORPUS" not in out, out


# ===========================================================================
# 4. THE POINTER IS FOLLOWED, AND ANNOUNCED. A gate that scans a different tree
#    from the one on its command line must say so — that silence is how a
#    mis-aimed `--tree` once reported "13/28 conformant" over a tree an absolute
#    path found 8 failures in.
# ===========================================================================
def test_portability_announces_the_override(clean_corpus_clone):
    rc, out = _run(PORTABILITY, "--corpus-may-be-absent",
                   env_tree=str(clean_corpus_clone))
    assert f"{ENV} overrides" in out, out
    assert str(clean_corpus_clone) in out, "the tree actually scanned must be named"


def test_target_present_announces_the_override(clean_corpus_clone):
    rc, out = _run(TARGET_PRESENT, "--corpus-may-be-absent",
                   "--baseline", str(clean_corpus_clone.parent / "reg.json"),
                   env_tree=str(clean_corpus_clone))
    assert f"{ENV} overrides" in out, out
    assert str(clean_corpus_clone) in out, "the tree actually scanned must be named"


# ===========================================================================
# 5. A SUPPLIED CORPUS IS REALLY EXAMINED, and the denominator is printed.
#    Without this, everything above is compatible with gates that never scan.
# ===========================================================================
def test_portability_really_enumerates_a_supplied_corpus(clean_corpus_clone, tmp_path):
    out_json = tmp_path / "p.json"
    rc, out = _run(PORTABILITY, "--corpus-may-be-absent",
                   "--json", str(out_json), env_tree=str(clean_corpus_clone))
    assert rc == 0, out
    assert "NO_CORPUS" not in out, "a present corpus was reported as absent"
    assert json.loads(out_json.read_text())["symlinks"] == 1, out


def test_target_present_really_enumerates_a_supplied_corpus(
        clean_corpus_clone, tmp_path):
    rc, out = _run(TARGET_PRESENT, "--corpus-may-be-absent",
                   "--baseline", _empty_register(tmp_path),
                   env_tree=str(clean_corpus_clone))
    assert rc == 0, out
    assert "NO_CORPUS" not in out, out
    assert "1 tracked symlink(s) among 2 tracked path(s)" in out, (
        f"a zero-or-any count without its denominator is the shape #1700 is "
        f"about\n{out}")


# ===========================================================================
# 6. THE LOAD-BEARING PAIR: A PLANTED DEFECT IN A SUPPLIED CORPUS STILL FAILS,
#    WITH THE FLAG SET. #1700 recorded 31 dangling `steps/` pointers and #371
#    recorded 159 absolute targets; supplying that corpus must still find them.
#    If the rc 2 -> rc 0 widening above had been bought by weakening the gates,
#    these two are the tests that would have gone green with it.
# ===========================================================================
def test_portability_still_fails_on_an_absolute_target_in_a_supplied_corpus(
        corpus_clone):
    rc, out = _run(PORTABILITY, "--corpus-may-be-absent",
                   env_tree=str(corpus_clone))
    assert rc == 1, (
        f"--corpus-may-be-absent reached a corpus that IS present and excused a "
        f"non-portable pointer in it\n{out}")
    assert "absolute target" in out, out
    assert "steps/result.json" in out, "the offending pointer must be named"


def test_target_present_still_fails_on_a_dangling_pointer_in_a_supplied_corpus(
        corpus_clone, tmp_path):
    rc, out = _run(TARGET_PRESENT, "--corpus-may-be-absent",
                   "--baseline", _empty_register(tmp_path),
                   env_tree=str(corpus_clone))
    assert rc == 1, (
        f"--corpus-may-be-absent reached a corpus that IS present and excused a "
        f"pointer at a file that exists nowhere\n{out}")
    assert "steps/repair_log.json" in out, "the offending pointer must be named"
    assert "NO_CORPUS" not in out, out


def test_portability_still_counts_dangling_links_it_declines_to_gate(corpus_clone,
                                                                    tmp_path):
    """The disclosure that survives the move. This gate deliberately does not
    FAIL on a dangling relative link — a missing FILE is a different defect from
    a non-portable POINTER — but for months the count was the only evidence the
    31 existed, so it must still be produced over a relocated corpus."""
    out_json = tmp_path / "p.json"
    rc, out = _run(PORTABILITY, "--corpus-may-be-absent", "--json",
                   str(out_json), env_tree=str(corpus_clone))
    assert json.loads(out_json.read_text())["dangling_inside_repo"] == 1, out
    assert "dangling" in out, out


# ===========================================================================
# 7. THE SHIPPED CALL SITES CARRY THE FLAG. Everything above tests the programs;
#    this tests the only lines that ever invoke them in production. Without it
#    both programs could be perfect and both gates still red.
# ===========================================================================
@pytest.mark.parametrize("prog", ["tracked_symlink_portability_check.py",
                                  "tracked_symlink_target_present_check.py"])
def test_the_hygiene_sweep_actually_passes_the_flag(prog):
    sweep = PROGRAMS.parents[3] / "tools" / "ci" / "repo_hygiene_gates.sh"
    if not sweep.is_file():
        pytest.skip(f"{sweep} not present in this checkout")
    lines = [ln for ln in sweep.read_text().splitlines()
             if prog in ln and not ln.strip().startswith("#")]
    assert lines, f"the hygiene sweep no longer invokes {prog} at all"
    assert all("--corpus-may-be-absent" in ln for ln in lines), (
        f"the sweep invokes {prog} without the flag, so a repo with no corpus is "
        f"still blocked:\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# A DIRECTORY IS NOT A CHECKOUT — the fatal an adversarial reviewer found in the
# first version of this fix, pinned so it cannot come back.
#
# `tracked_symlinks()` reads git's INDEX and returns [] when git exits non-zero.
# Over a corpus that is PRESENT but not a checkout, that empty list reached
# `audit()` as "no symlinks" and the program printed
#     [PASS] every tracked symlink is relative and stays inside the repository.
# over a tree physically carrying an absolute-target link.
#
# The corpus lives in its own repository now, so a tarball fetch, an archive
# export, a dead `git clone` or a worktree without `.git` all produce that input:
# a failed fetch certifying a tree, which is worse than NO_CORPUS because
# NO_CORPUS at least says nothing was scanned.
#
# BOTH ARMS, built byte-identically except for `git init`.
# ---------------------------------------------------------------------------
def _corpus_with_one_absolute_symlink(base, as_git_checkout):
    c = base / "benchmark-data"
    (c / "ic" / "x" / "steps").mkdir(parents=True)
    (c / "ic" / "x" / "RESULT.json").write_text('{"v":1}\n')
    (c / "ic" / "x" / "steps" / "result.json").symlink_to("/tmp/absolute/RESULT.json")
    if as_git_checkout:
        for args in (["init", "-q"], ["add", "-A"],
                     ["-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-q", "-m", "x"]):
            _pr.run(["git", "-C", str(c), *args],
                           capture_output=True, text=False)
    return c


def test_a_real_checkout_still_catches_the_absolute_target(tmp_path):
    c = _corpus_with_one_absolute_symlink(tmp_path, as_git_checkout=True)
    rc, out = _run(PORTABILITY, "--corpus-may-be-absent", env_tree=str(c))
    assert rc == 1, f"the defect this gate exists for was not caught\n{out}"
    assert "non-portable" in out, out


def test_a_present_but_unversioned_corpus_is_undetermined_never_pass(tmp_path):
    c = _corpus_with_one_absolute_symlink(tmp_path, as_git_checkout=False)
    rc, out = _run(PORTABILITY, "--corpus-may-be-absent", env_tree=str(c))
    assert rc == 2, (
        f"a corpus that is PRESENT and carries the defect was certified because it "
        f"is not a git checkout — an empty `git ls-files` read as 'there are none'\n{out}")
    assert "UNDETERMINED" in out, out
    assert "PASS]" not in out, "it still printed a pass over a tree it could not read"
    assert "NO_CORPUS" not in out, (
        "a present-but-unversioned corpus was laundered as an absent one; "
        "the corpus is right there")
