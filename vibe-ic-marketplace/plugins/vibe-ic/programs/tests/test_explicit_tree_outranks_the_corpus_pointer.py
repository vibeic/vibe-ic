"""An EXPLICIT `--tree` / `--root` must outrank `$VIBE_IC_BENCHMARK_DATA`.

THE MEASURED DEFECT
===================
v1.10.56 moved the published corpus into its own repository and every gate over it
learned to follow `$VIBE_IC_BENCHMARK_DATA`. Three of them learned it as *the
pointer wins over the path*, unconditionally:

    benchmark_evidence_structure_check.py   if env and args.tree: args.tree = env
    tracked_symlink_portability_check.py    if env: root = Path(env)
    tracked_symlink_target_present_check.py if env: corpus = Path(env)

An environment DEFAULT outranking an EXPLICIT command-line argument is backwards,
and it is not a style complaint. MEASURED 2026-08-20 on `9cc09b86` (v1.11.5), host
8HD-8, corpus `vibeic/benchmark-data @ 146d665`, the same six files run twice:

    VIBE_IC_BENCHMARK_DATA bound  -> 52 failed
    VIBE_IC_BENCHMARK_DATA unset  -> 11 failed
    red ONLY when bound, and PASSING when unbound: 22

Those 22 build a synthetic corpus in a tmpdir, pass it as `--tree <tmpdir>`, and
were answered about the real 265 MB corpus instead — their failure text says so
verbatim: `note: VIBE_IC_BENCHMARK_DATA overrides --tree /…/pytest-of-…/<fixture>`.
So *bind the corpus* (which the hygiene tier requires — unbound it refuses in 0s)
and *run the targeted tests* were MUTUALLY EXCLUSIVE, and the landing gate was red
in a way that said nothing about the code under test.

The 23rd is worse than a red test. `tools/ci/gate_fixtures/tracked_symlink_target_
present.py` is a MUTATION FIXTURE: it builds a subject with a tracked symlink and a
second copy with that symlink repointed at nothing, and the pair proves the gate can
go both ways. With the pointer set, both arms were answered about the real corpus,
both returned rc 0, and a gate whose entire job is to discriminate did not —
`test_gate_fixtures_discriminate[tracked_symlink_target_present]` is the alarm that
caught it.

THE RULE, AND WHY IT IS NOT SIMPLY "THE ARGUMENT WINS"
=====================================================
The pointer cannot just lose: both shipped call sites of the structure check pass the
literal `--tree benchmark-data`, a relative path that has not existed in this repo
since v1.10.56, and the symlink gates default to the same name. If an explicit
argument won unconditionally, every shipped call site would scan nothing.

`_corpus_location.resolve()` already held the correct rule and said so in its own
docstring — *"THE POINTER REPLACES A MISSING CORPUS; IT DOES NOT REPLACE A PRESENT
ONE"* — and its test is `named.is_dir()`. An absent literal still falls through to
the pointer; a directory that carries a tree does not. These three programs did not
go through it. Now they do, and both directions are ANNOUNCED, because a gate that
silently scans a tree other than the one named on its command line is how
`--tree ../../../benchmark-data` once reported "13/28 conformant" over a tree an
absolute path found 8 failures in.

TWO-ARM CONTROL
===============
Every `test_bug_*` here FAILS against v1.11.5's programs and PASSES against the fixed
ones — proved by running each against a second checkout at the base revision, not by
reading the diff. Every `test_guard_*` passes in BOTH arms: they pin the fall-through
the pointer exists for, so the fix cannot be bought by making the pointer inert.

chip-AGNOSTIC: every name is synthetic (`ic_alpha`, `pdka`). No design, PDK, foundry
or process identifier appears.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_TIMEOUT = 180

STRUCTURE = _PROGRAMS / "benchmark_evidence_structure_check.py"
PORTABILITY = _PROGRAMS / "tracked_symlink_portability_check.py"
TARGET_PRESENT = _PROGRAMS / "tracked_symlink_target_present_check.py"


# --------------------------------------------------------------------------
# Fixtures. TWO corpora per test: the one the argument names, and the one the
# pointer names. They must be DISTINGUISHABLE BY VERDICT, or the test cannot
# tell which was scanned — a same-verdict pair would pass either way, which is
# the shape this whole file is about.
# --------------------------------------------------------------------------

def _git(root: Path, *args: str) -> None:
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull, GIT_AUTHOR_NAME="t",
               GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(("git", "-C", str(root)) + args, env=env, check=True,
                   capture_output=True, timeout=_TIMEOUT)


def _init(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    return root


def _clean_corpus(root: Path) -> Path:
    """A corpus every rule under test PASSES on — the decoy the pointer names."""
    _init(root)
    (root / "benchmark-data").mkdir()
    (root / "benchmark-data" / "real.txt").write_text("published artefact\n")
    os.symlink("real.txt", root / "benchmark-data" / "pointer.txt")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "clean")
    return root


def _run(program: Path, *args: str, pointer: Path | None,
         cwd: Path | None = None) -> "subprocess.CompletedProcess[str]":
    env = dict(os.environ)
    env.pop("GATEKEEPER_BENCHMARK_DATA_SHA", None)
    if pointer is None:
        env.pop("VIBE_IC_BENCHMARK_DATA", None)
    else:
        env["VIBE_IC_BENCHMARK_DATA"] = str(pointer)
    return subprocess.run([sys.executable, str(program), *args],
                          capture_output=True, text=True, timeout=_TIMEOUT,
                          cwd=None if cwd is None else str(cwd), env=env)


# ══════════════════════════════════════════════════════════════════════
# benchmark_evidence_structure_check --tree
# ══════════════════════════════════════════════════════════════════════

def _evidence_tree(root: Path) -> Path:
    """One IC carrying a stray at the IC level — a NAMED nonconformance, so the
    verdict cannot be confused with a corpus that merely has nothing in it."""
    (root / "ic" / "ic_alpha").mkdir(parents=True)
    (root / "ic" / "ic_alpha" / "stray.txt").write_text("run output\n")
    return root


def test_bug_an_explicit_tree_that_exists_is_scanned_not_the_pointer(tmp_path):
    named = _evidence_tree(tmp_path / "named")
    decoy = _clean_corpus(tmp_path / "decoy")
    r = _run(STRUCTURE, "--tree", str(named), pointer=decoy)
    assert str(named) in r.stdout, (
        "the gate did not scan the tree its own --tree named\n"
        f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}")
    assert str(decoy) not in r.stdout, (
        "the pointer's tree was scanned instead of the explicit --tree\n"
        f"stdout:\n{r.stdout}")
    assert r.returncode == 1, (
        f"the stray at the IC level was not reported (rc={r.returncode})\n"
        f"{r.stdout}\n{r.stderr}")


def test_bug_declining_the_pointer_is_ANNOUNCED_never_silent(tmp_path):
    """A reader with the pointer set must be able to see it was not followed.

    Both directions are announced on purpose: a verdict whose scanned tree is
    unstated is unreadable either way round.
    """
    named = _evidence_tree(tmp_path / "named")
    decoy = _clean_corpus(tmp_path / "decoy")
    r = _run(STRUCTURE, "--tree", str(named), pointer=decoy)
    assert "NOT followed" in r.stderr and str(decoy) in r.stderr, (
        f"the declined pointer was not announced\nstderr:\n{r.stderr}")


def test_guard_an_absent_tree_still_falls_through_to_the_pointer(tmp_path):
    """The shipped call sites' shape: `--tree benchmark-data`, which is gone.

    This is the whole reason the pointer exists, so it must keep working —
    otherwise the fix is bought by making the pointer inert.
    """
    decoy = _clean_corpus(tmp_path / "decoy")
    (decoy / "ic" / "ic_alpha" / "v1.2.3_pdka").mkdir(parents=True)
    r = _run(STRUCTURE, "--tree", "benchmark-data", "--corpus-may-be-absent",
             pointer=decoy, cwd=tmp_path)
    assert "overrides" in r.stderr and str(decoy) in r.stderr, (
        f"an absent --tree did not reach the pointer\nstderr:\n{r.stderr}")
    assert str(decoy) in r.stdout, f"nothing under the pointer was scanned\n{r.stdout}"


def test_guard_an_absent_tree_with_no_pointer_is_still_UNDETERMINED(tmp_path):
    """rc 2, not 0: a gate that could not look has not passed."""
    r = _run(STRUCTURE, "--tree", str(tmp_path / "nope"), pointer=None)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "UNDETERMINED" in r.stderr


# ══════════════════════════════════════════════════════════════════════
# tracked_symlink_portability_check <root>
# ══════════════════════════════════════════════════════════════════════

def _absolute_symlink_corpus(root: Path) -> Path:
    _init(root)
    (root / "benchmark-data").mkdir()
    (root / "benchmark-data" / "real.txt").write_text("x\n")
    os.symlink(os.devnull, root / "benchmark-data" / "abs.txt")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "absolute")
    return root


def test_bug_an_explicit_root_that_exists_outranks_the_pointer(tmp_path):
    named = _absolute_symlink_corpus(tmp_path / "named")
    decoy = _clean_corpus(tmp_path / "decoy")
    r = _run(PORTABILITY, str(named / "benchmark-data"),
             "--corpus-may-be-absent", pointer=decoy)
    assert r.returncode == 1, (
        "the absolute-target symlink under the NAMED root was not reported "
        f"(rc={r.returncode})\n{r.stdout}\n{r.stderr}")
    assert "abs.txt" in r.stdout
    assert "NOT followed" in r.stderr


def test_guard_no_root_at_all_still_follows_the_pointer(tmp_path):
    decoy = _absolute_symlink_corpus(tmp_path / "decoy")
    r = _run(PORTABILITY, "--corpus-may-be-absent", pointer=decoy)
    assert "overrides" in r.stderr and str(decoy) in r.stderr, (
        f"the pointer was not followed with no root given\nstderr:\n{r.stderr}")


def test_guard_a_pointer_that_is_set_and_wrong_stays_UNDETERMINED(tmp_path):
    """--corpus-may-be-absent must never launder a broken pointer into rc 0."""
    r = _run(PORTABILITY, "--corpus-may-be-absent",
             pointer=tmp_path / "does-not-exist")
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "UNDETERMINED" in r.stderr


# ══════════════════════════════════════════════════════════════════════
# tracked_symlink_target_present_check --root
#
# This is the one the mutation fixture exercises, so both arms are pinned here
# in the shape `tools/ci/gate_fixtures/tracked_symlink_target_present.py` builds
# them and `repo_hygiene_gates.sh:356` invokes them.
# ══════════════════════════════════════════════════════════════════════

def _pointer_corpus(root: Path, target: str) -> Path:
    _init(root)
    (root / "benchmark-data").mkdir()
    (root / "benchmark-data" / "real.txt").write_text("published artefact\n")
    os.symlink(target, root / "benchmark-data" / "pointer.txt")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "subject")
    return root


def test_bug_the_gate_fixtures_CAN_FAIL_arm_fails_with_the_pointer_set(tmp_path):
    """The mutation the fixture makes must move the verdict, pointer or no pointer."""
    named = _pointer_corpus(tmp_path / "named", "absent.txt")
    decoy = _clean_corpus(tmp_path / "decoy")
    r = _run(TARGET_PRESENT, "--root", str(named), "--corpus-may-be-absent",
             pointer=decoy, cwd=named)
    assert r.returncode == 1, (
        "the can-FAIL arm of the shipped mutation fixture passed — the gate was "
        f"answered about the pointer's tree (rc={r.returncode})\n"
        f"{r.stdout}\n{r.stderr}")
    assert "benchmark-data/pointer.txt" in r.stdout


def test_guard_the_gate_fixtures_CAN_PASS_arm_still_passes(tmp_path):
    """The paired guard. A gate that only ever says no is a ban, not a check."""
    named = _pointer_corpus(tmp_path / "named", "real.txt")
    decoy = _clean_corpus(tmp_path / "decoy")
    r = _run(TARGET_PRESENT, "--root", str(named), "--corpus-may-be-absent",
             pointer=decoy, cwd=named)
    assert r.returncode == 0, (
        f"the can-PASS arm went red (rc={r.returncode})\n{r.stdout}\n{r.stderr}")


def test_guard_a_root_whose_subdir_is_absent_still_falls_through(tmp_path):
    """The shipped call site: `--root $ROOT` where `$ROOT/benchmark-data` is gone
    since v1.10.56. It must still reach the pointer."""
    named = _init(tmp_path / "named")          # a checkout with NO benchmark-data
    (named / "keep.txt").write_text("x\n")
    _git(named, "add", "-A")
    _git(named, "commit", "-qm", "no corpus here")
    decoy = _clean_corpus(tmp_path / "decoy")
    r = _run(TARGET_PRESENT, "--root", str(named), "--corpus-may-be-absent",
             pointer=decoy, cwd=named)
    assert "overrides" in r.stderr and str(decoy) in r.stderr, (
        f"an absent subdir did not reach the pointer\nstderr:\n{r.stderr}")


# ══════════════════════════════════════════════════════════════════════
# The bound-landing protocol is NOT weakened by any of the above.
# ══════════════════════════════════════════════════════════════════════

def test_guard_a_bound_landing_still_forces_the_pointer_over_a_named_tree(tmp_path):
    """`$GATEKEEPER_BENCHMARK_DATA_SHA` byte-attests ONE external checkout.

    Inside that protocol a candidate-local tree must NOT win, or the summary would
    name the external SHA while the scan walked something else. `_corpus_location`
    has always held this and it must survive the precedence change.
    """
    named = _evidence_tree(tmp_path / "named")
    decoy = _clean_corpus(tmp_path / "decoy")
    (decoy / "ic" / "ic_alpha" / "v1.2.3_pdka").mkdir(parents=True)
    env_extra = {"GATEKEEPER_BENCHMARK_DATA_SHA": "0" * 40,
                 "VIBE_IC_BENCHMARK_DATA": str(decoy)}
    r = subprocess.run([sys.executable, str(STRUCTURE), "--tree", str(named)],
                       capture_output=True, text=True, timeout=_TIMEOUT,
                       env=dict(os.environ, **env_extra))
    assert str(decoy) in r.stdout, (
        "a bound landing scanned the candidate-local tree instead of the "
        f"byte-attested checkout\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")
    assert "binds the landing corpus" in r.stderr


def test_guard_a_bound_landing_without_its_pointer_REFUSES(tmp_path):
    """A SHA with no checkout is UNDETERMINED, never a scan of local bytes."""
    named = _evidence_tree(tmp_path / "named")
    env = dict(os.environ, GATEKEEPER_BENCHMARK_DATA_SHA="0" * 40)
    env.pop("VIBE_IC_BENCHMARK_DATA", None)
    r = subprocess.run([sys.executable, str(STRUCTURE), "--tree", str(named)],
                       capture_output=True, text=True, timeout=_TIMEOUT, env=env)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "UNDETERMINED" in r.stderr


# ══════════════════════════════════════════════════════════════════════
# AN EXPLICIT ARGUMENT BEATS THE POINTER EVEN WHEN IT IS ABSENT.
#
# `named.is_dir()` alone leaves half the rule unstated: a caller who names a
# path that is NOT there still gets somebody else's tree. MEASURED 2026-08-20 in
# ONE test file — `test_issue1025_empty_corpus_sweep_blocks` — where
#
#     --corpus <tmpdir>/corpus   (empty, exists)  -> honoured, rc 2
#     --corpus <tmpdir>/gone     (absent)         -> substituted, rc 0
#
# so an empty tree was respected and an absent one was not, and the test that
# asked "does an absent corpus also exit 2" was answered by a full sweep of the
# real 265 MB corpus.
#
# The pointer's remit is the location v1.10.56 ORPHANED and nothing else. All
# four shipped call sites carry `benchmark-data` as a path component; a path that
# does not was never part of that move.
# ══════════════════════════════════════════════════════════════════════

BUBBLE_UP = _PROGRAMS / "step_internal_fail_bubble_up_check.py"

sys.path.insert(0, str(_PROGRAMS))
import _corpus_location as _cloc  # noqa: E402


@pytest.mark.parametrize("path,expected", [
    ("benchmark-data", True),                      # gatekeeper-land.sh:229
    ("benchmark-data/ic", True),
    ("/repo/benchmark-data", True),                # repo_hygiene_gates.sh:356
    ("/repo/benchmark-data/ic", True),             # repo_hygiene_gates.sh:800
    ("/tmp/pytest-of-x/test_a0/gone", False),
    ("/tmp/pytest-of-x/test_a0/corpus", False),
    ("/some/other/tree", False),
])
def test_the_pointers_remit_is_the_orphaned_location_and_nothing_else(path, expected):
    assert _cloc.pointer_may_replace(Path(path)) is expected, path


def test_bug_an_absent_explicit_corpus_is_UNDETERMINED_not_the_pointers_tree(tmp_path):
    decoy = _clean_corpus(tmp_path / "decoy")
    (decoy / "ic" / "ic_alpha" / "v1.2.3_pdka").mkdir(parents=True)
    r = _run(BUBBLE_UP, "--corpus", str(tmp_path / "gone"), pointer=decoy)
    assert r.returncode == 2, (
        "an absent explicit --corpus was answered from the pointer's tree "
        f"(rc={r.returncode})\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    assert "NOT followed" in r.stderr, r.stderr


def test_bug_the_refusal_does_not_prescribe_a_remedy_already_in_force(tmp_path):
    """"Point $VIBE_IC_BENCHMARK_DATA at a clone" is a dead end for a reader who
    has, and whose pointer was declined on purpose."""
    decoy = _clean_corpus(tmp_path / "decoy")
    (decoy / "ic" / "ic_alpha" / "v1.2.3_pdka").mkdir(parents=True)
    r = _run(BUBBLE_UP, "--corpus", str(tmp_path / "gone"), pointer=decoy)
    assert "IS set and was NOT followed on purpose" in r.stderr, r.stderr
    assert "fix the path you named" in r.stderr, r.stderr


def test_guard_the_shipped_corpus_call_site_still_reaches_the_pointer(tmp_path):
    """`repo_hygiene_gates.sh:800` passes `$ROOT/benchmark-data/ic`, absent since
    v1.10.56. It must still be answered by the pointer, or the gate scans nothing."""
    decoy = _clean_corpus(tmp_path / "decoy")
    (decoy / "ic" / "ic_alpha" / "v1.2.3_pdka").mkdir(parents=True)
    r = _run(BUBBLE_UP, "--corpus", str(tmp_path / "repo" / "benchmark-data" / "ic"),
             "--corpus-may-be-absent", pointer=decoy)
    assert "overrides" in r.stderr and str(decoy) in r.stderr, (
        f"the orphaned default did not reach the pointer\nstderr:\n{r.stderr}")


def test_guard_an_EMPTY_explicit_corpus_is_still_honoured(tmp_path):
    """The half that already worked must keep working: an empty directory is a
    real determination ("I looked, there is nothing"), not a missing one."""
    empty = tmp_path / "corpus"
    empty.mkdir()
    decoy = _clean_corpus(tmp_path / "decoy")
    (decoy / "ic" / "ic_alpha" / "v1.2.3_pdka").mkdir(parents=True)
    r = _run(BUBBLE_UP, "--corpus", str(empty), pointer=decoy)
    assert r.returncode == 2, f"rc={r.returncode}\n{r.stdout[-1200:]}"
    assert "0 published run tree(s)" in r.stdout, r.stdout[-1200:]
