"""#1254 — pre-push aborts with no message, and gates that cannot look exit 0.

TWO FACES OF ONE RULE, both measured on `a38902d1` before anything was changed.

FACE 1 — THE HOOK COULD NOT SAY WHY IT REFUSED.
`tools/git-hooks/pre-push` runs under `set -euo pipefail`, and the line that
fed the prohibition guard was untested:

    git log --format='%B' $PUSH_RANGE > /tmp/gk_push_commit_text.txt 2>/dev/null

Single-variable control, everything else held fixed: make that ONE path
unwritable and push. The hook dies there with `FAILED` already 1, and neither
`pre-push: BLOCKED — see the gate(s) named above.` nor the remediation block
below it is ever printed — `set -e` exits AT the failing command, so the lines
that exist to explain the refusal are unreachable on exactly the path that
needs them. With `2>/dev/null` discarding git's own reason as well, a failure
of `git log` itself leaves NOTHING but

    error: failed to push some refs to '…'

which reads as an auth or network failure and is neither. The reporter lost
about an hour to that reading, and every agent would lose the same hour,
because the dispatch doctrine tells all of us to work in a worktree.

The fix is a MECHANISM, not a patch for that one line: an ERR trap that names
the aborting line, the command, and the rc. Patching the one known command
leaves the next untested one just as silent.

That fixed path was also a SECOND defect on its own: a fixed name in a shared
/tmp is not private, and several agents push from one host. The second writer
wins, so the guard could scan the other push's commit messages.

FACE 2 — A GATE THAT COULD NOT LOOK REPORTED THAT IT HAD LOOKED.
Measured directly, each program run outside a git repo:

    nda_diff_scan_check.py                 rc=2   <- already correct
    agent_checkin_scope_guard.py           rc=2   <- already correct
    landing_collateral_revert_check.py     rc=2   <- already correct
    marketplace_version_sync_check.py      rc=2   <- already correct
    benchmark_evidence_structure_check.py  rc=0   <- reported clean
    benchmark_run_manifest.py              rc=0   <- reported clean

So four of the six already refuse; their OUTPUT looks like an error dump, which
is what made them look guilty. The two that returned 0 are fixed here.

This is not a new policy. `benchmark_evidence_structure_check`'s own header
already cites `gate_zero_denominator_refuses_check` — "the gate states it read
NOTHING and still exits 0 … Either make it refuse (rc 2 is the disclosed-skip
convention)" — and already implements exactly that for the case where every
discovered unit examined nothing. These two paths were simply left out.

WHAT MUST NOT MOVE, and is guarded below in the other direction: "I looked and
nothing changed" is a REAL answer and stays rc 0. Grandfathering depends on it,
and collapsing it into the refusal would be the same error mirrored — a gate
that fails a push over work nobody is doing.
"""
from __future__ import annotations

import importlib
import os
import pathlib

import pytest

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

ESC = importlib.import_module("benchmark_evidence_structure_check")
RUN = importlib.import_module("benchmark_run_manifest")

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_REPO = _PROGRAMS.parents[3]
_HOOK = _REPO / "tools" / "git-hooks" / "pre-push"

def _repo(tmp_path: pathlib.Path) -> pathlib.Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    def g(*a):
        return _pr.run(["git", "-C", str(tmp_path), *a],
                              capture_output=True, text=True)
    g("init", "-q", ".")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    g("add", "seed.txt")
    g("commit", "-q", "-m", "seed")
    return tmp_path


def _run_main(mod, argv, cwd):
    """Drive the program's real main() from `cwd`, as the hook drives it."""
    here = os.getcwd()
    try:
        os.chdir(cwd)
        return mod.main(argv)
    finally:
        os.chdir(here)


# ── FACE 2a: benchmark_evidence_structure_check ────────────────────────────

def test_a_tree_that_is_not_there_is_undeterminable_not_clean(tmp_path):
    """The hook passes `--tree benchmark-data`, a RELATIVE path. A caller whose
    cwd is not the repo root discovers zero folders — which is not the same
    fact as "there are none"."""
    rc = _run_main(ESC, ["--tree", "benchmark-data",
                         "--changed-since", "HEAD"], tmp_path)
    assert rc == 2, ("a gate that never found the tree it was pointed at "
                     f"reported rc={rc}; only 0 and 2 are distinguishable to "
                     "the hook, and 0 means CHECKED AND CLEAN")


def test_an_undeterminable_change_set_is_refused_not_failed_open(tmp_path):
    """`kept is None` means git could not answer. The old code printed
    'checking nothing (fail-open)' and exited 0 — an honest sentence with a
    dishonest exit code, and only the exit code is read."""
    tree = tmp_path / "benchmark-data" / "ic" / "spm" / "v1.0.0_sky130A"
    tree.mkdir(parents=True)
    (tree / "RESULT.md").write_text("# result\n", encoding="utf-8")
    # NOT a git repo -> _changed_file_set returns (None, "not a git repo").
    rc = _run_main(ESC, ["--tree", "benchmark-data",
                         "--changed-since", "origin/main"], tmp_path)
    assert rc == 2, (f"change set undeterminable reported rc={rc}; a check "
                     "that could not look has not passed")


def test_REVERSE_a_present_tree_with_nothing_changed_still_passes(tmp_path):
    """THE DIRECTION THAT MUST NOT MOVE. 'I looked and nothing changed' is a
    real determination; grandfathering depends on it answering 0. If this test
    ever fails, the refusal above has been widened into the case it was
    explicitly scoped away from."""
    repo = _repo(tmp_path)
    tree = repo / "benchmark-data" / "ic" / "spm" / "v1.0.0_sky130A"
    tree.mkdir(parents=True)
    (tree / "RESULT.md").write_text("# result\n", encoding="utf-8")
    _pr.run(["git", "-C", str(repo), "add", "-A"],
                   capture_output=True, text=False)
    _pr.run(["git", "-C", str(repo), "commit", "-q", "-m", "publish"],
                   capture_output=True, text=False)
    rc = _run_main(ESC, ["--tree", "benchmark-data", "--changed-since", "HEAD"],
                   repo)
    assert rc == 0, ("a determinable change set with nothing to enforce must "
                     f"still pass; got rc={rc}")


# ── FACE 2b: benchmark_run_manifest ────────────────────────────────────────

def test_run_manifest_refuses_when_git_cannot_answer(tmp_path):
    """`changed_run_dirs` returned [] on a git failure, so 'git could not
    answer' and 'nothing was touched' were the SAME value — and the caller
    renders [] as `PASS — 0 run director(y/ies) touched`."""
    (tmp_path / "benchmark-data").mkdir()
    rc = _run_main(RUN, ["check", "--tree", "benchmark-data",
                         "--changed-since", "origin/main"], tmp_path)
    assert rc == 2, (f"git could not answer and the gate reported rc={rc}; "
                     "0 here is a PASS the gate did not earn")


def test_changed_run_dirs_signals_undeterminable_distinctly(tmp_path):
    """The two states must be distinguishable AT THE ONLY PLACE that can tell
    them apart. None (could not answer) vs [] (answered: nothing)."""
    # `changed_run_dirs` drives a bare `git diff` with no `-C`, so it resolves
    # from the CWD entirely — which is the same cwd-fragility this issue is
    # about. Drive it from each place rather than assuming.
    here = os.getcwd()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "benchmark-data").mkdir()
    try:
        os.chdir(outside)
        assert RUN.changed_run_dirs(pathlib.Path("benchmark-data"),
                                    "origin/main") is None
        repo = _repo(tmp_path / "inside")
        (repo / "benchmark-data").mkdir()
        os.chdir(repo)
        assert RUN.changed_run_dirs(pathlib.Path("benchmark-data"), "HEAD") == []
    finally:
        os.chdir(here)


def test_REVERSE_run_manifest_passes_when_it_really_saw_nothing(tmp_path):
    """The other direction, guarded: a real repo where the diff genuinely names
    no scored run must still be rc 0."""
    repo = _repo(tmp_path)
    (repo / "benchmark-data").mkdir()
    rc = _run_main(RUN, ["check", "--tree", "benchmark-data",
                         "--changed-since", "HEAD"], repo)
    assert rc == 0, f"a determined, genuinely empty change set must pass; rc={rc}"


# ── FACE 1: the hook must never refuse without naming a reason ─────────────

def _hook_text() -> str:
    return _HOOK.read_text(encoding="utf-8")


def _hook_code() -> str:
    """The hook with COMMENTS STRIPPED.

    The comments quote the defective line verbatim to explain what was wrong,
    so a naive substring search over the whole file finds the very string it is
    asserting the absence of — and passes or fails for the wrong reason. Read
    the code."""
    out = []
    for line in _hook_text().splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)


@pytest.mark.skipif(not _HOOK.is_file(), reason="hook not present in this tree")
def test_the_hook_installs_an_abort_trap():
    """A mechanism, not a patch for one line: every abort is named, including
    the untested commands nobody has hit yet."""
    txt = _hook_text()
    assert "trap '_hook_aborted" in txt, (
        "no ERR trap: an abort at any untested command exits non-zero with "
        "nothing said, which reads as a network failure")
    assert "$BASH_COMMAND" in txt and "$LINENO" in txt, (
        "the trap must name WHICH command aborted; 'something failed' costs "
        "the same hour it cost in #1254")


@pytest.mark.skipif(not _HOOK.is_file(), reason="hook not present in this tree")
def test_the_hook_does_not_write_to_a_fixed_shared_tmp_path():
    """Several agents push from one host. A fixed name means the second writer
    wins and the guard scans the OTHER push's commit messages."""
    code = _hook_code()
    assert "/tmp/gk_push_commit_text.txt" not in code, (
        "fixed shared path: not private between concurrent pushes, and its "
        "untested redirect is what made the abort silent")
    assert "mktemp" in code


@pytest.mark.skipif(not _HOOK.is_file(), reason="hook not present in this tree")
def test_the_range_read_is_tested_and_keeps_gits_reason():
    """`> file 2>/dev/null` on an untested command is the exact shape that
    discards both the verdict and the reason."""
    assert "> /tmp/gk_push_commit_text.txt 2>/dev/null" not in _hook_code()
    assert "NOT CHECKED — git prohibition guard" in _hook_text(), (
        "a gate that could not be fed has not passed, and must say which "
        "range it could not read")


def _drive_hook(hook: pathlib.Path, cwd: pathlib.Path):
    """Invoke a pre-push hook the way git does: argv = <remote> <url>, and the
    ref line on stdin."""
    stdin = f"HEAD {'a' * 40} refs/heads/probe {'0' * 40}\n"
    return _pr.run(["bash", str(hook), "origin", str(cwd)],
                          input=stdin, capture_output=True, text=True,
                          cwd=str(cwd))


@pytest.mark.skipif(not _HOOK.is_file(), reason="hook not present in this tree")
def test_the_trap_names_the_command_when_the_hook_really_aborts(tmp_path):
    """DRIVEN, not read.

    The cheapest true trigger is the FIRST thing the hook does — resolving the
    repo. Run it where there is no repo and `git rev-parse --show-toplevel`
    fails on line 1 of the body, under `set -e`, before a single diagnostic
    could print. That is the same class as the reporter's failure and it needs
    no gate to run.

    PAIRED, and load-bearing: the identical scenario against a mutant hook with
    ONLY the trap line removed must produce NOTHING. Without that arm this test
    would pass just as well against a hook that prints for some other reason."""
    nogit = tmp_path / "nowhere"
    nogit.mkdir()

    r = _drive_hook(_HOOK, nogit)
    assert r.returncode != 0, "a hook that cannot resolve the repo must refuse"
    assert "ABORTED" in r.stderr, (
        "the hook exited non-zero and never said why — that is #1254 itself:\n"
        + (r.stderr or "<no stderr at all>")[-2000:])
    assert "line:" in r.stderr and "command:" in r.stderr, (
        "an abort that does not name its command still costs the reader the "
        "hour:\n" + r.stderr[-2000:])

    # ── the paired arm: remove the trap, keep everything else ──
    mutant = tmp_path / "pre-push-mutant"
    mutant.write_text(
        "\n".join(l for l in _hook_text().splitlines()
                  if not l.startswith("trap '_hook_aborted")),
        encoding="utf-8")
    m = _drive_hook(mutant, nogit)
    assert m.returncode != 0, "the mutant must still refuse — only silently"
    assert "ABORTED" not in m.stderr, (
        "the mutant printed the abort banner without the trap, so this test "
        "does not measure the trap:\n" + m.stderr[-2000:])
