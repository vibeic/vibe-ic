"""`git ls-tree` that FAILED is not the same as a tree with nothing in it.

``tracked_under`` treated the two adjacent failure modes of the same subprocess
in opposite ways:

* git binary MISSING → `AssertionError`, refusing to guess, because it "cannot
  tell a committed artefact from a local build product" (#527). Correct.
* git binary PRESENT but the call FAILED → `return frozenset()`, i.e. *nothing
  under this root is tracked at HEAD*.

The second is a guess, and it is the more dangerous of the two, because it is
confident. Every caller reads "not tracked at HEAD" as "this artefact is not
produced" — the same shape a genuine finding has.

MEASURED (#1348 / #1356): mounting this repo's worktree into a container, where
`.git` is a file pointing at a host path that does not exist there, took the d3
contradiction count from 16 to 54. The extra 38 artefacts ARE committed and ARE
on disk — the failure text listed each one *with its byte size* and still called
it "matched but NOT tracked at HEAD — a local build product, not evidence".

The discriminator is not the message text (both shapes exit 128; only the wording
differs, and wording is not a contract). It is whether anything at or above the
root CLAIMS to be a checkout.

No mocking of git: both worlds are built as real directories and the real
`git ls-tree` is what fails in each.
"""
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN / "programs" / "tests"))
import test_matrix_d3_outputs_produced as D  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


@pytest.fixture(autouse=True)
def _no_cache():
    # tracked_under is lru_cached; each shape below must reach the real call.
    D.tracked_under.cache_clear()
    yield
    D.tracked_under.cache_clear()


def _git_fails_here(root: Path) -> None:
    """Precondition: the real git really does fail under *root*."""
    proc = _pr.run(["git", "ls-tree", "-r", "--name-only", "-z", "HEAD"],
                          cwd=str(root), capture_output=True, text=False)
    assert proc.returncode != 0, (
        f"this fixture is meaningless unless git actually fails under {root}")


def test_a_tree_with_no_git_at_all_still_answers_empty(tmp_path):
    """OVER-CORRECTION GUARD, and the reason this is not a one-line change.

    An unpacked archive or a flattened install cache is legitimately not a
    checkout. Nothing there is committed, so the empty set is the honest
    answer and must survive. A fix that raised on every non-zero exit would
    pass the test below and break every non-git install.
    """
    (tmp_path / "some_artefact.v").write_text("module m; endmodule\n")
    _git_fails_here(tmp_path)
    assert D.tracked_under(tmp_path) == frozenset()


def test_a_checkout_git_cannot_read_must_refuse_not_answer_empty(tmp_path):
    """The container case, reproduced exactly: a `git worktree` .git file
    whose gitdir does not exist here."""
    (tmp_path / ".git").write_text(
        "gitdir: /nonexistent/path/to/.git/worktrees/mounted\n")
    (tmp_path / "committed_artefact.v").write_text("module m; endmodule\n")
    _git_fails_here(tmp_path)

    with pytest.raises(AssertionError) as exc:
        D.tracked_under(tmp_path)
    msg = str(exc.value)
    # it must say WHICH of the two worlds it is in, or the reader cannot act
    assert "broken environment" in msg, msg
    assert "not a tree without commits" in msg, msg


def test_a_directory_INSIDE_a_broken_checkout_also_refuses(tmp_path):
    """The realistic shape: the run root is a subdirectory, and the `.git`
    that cannot be read sits above it. Checking only `root/.git` would miss
    this and hand back the same confident empty set."""
    (tmp_path / ".git").write_text("gitdir: /nonexistent/x\n")
    sub = tmp_path / "benchmark-data" / "ic" / "spm"
    sub.mkdir(parents=True)
    (sub / "committed.v").write_text("module m; endmodule\n")
    _git_fails_here(sub)

    with pytest.raises(AssertionError):
        D.tracked_under(sub)


def test_the_refusal_names_what_git_actually_said(tmp_path):
    # A refusal a human cannot act on is only marginally better than a wrong
    # answer, so git's own stderr has to survive into the message.
    (tmp_path / ".git").write_text("gitdir: /nonexistent/path/to/worktrees/x\n")
    _git_fails_here(tmp_path)
    with pytest.raises(AssertionError) as exc:
        D.tracked_under(tmp_path)
    assert "not a git repository" in str(exc.value)


def test_a_real_checkout_is_unaffected(tmp_path):
    """The path everyone actually runs: git works, and the answer is the
    tracked set — unchanged, and specifically NOT an exception."""
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True)
    (tmp_path / "a.v").write_text("module a; endmodule\n")
    subprocess.run(["git", "add", "a.v"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "x"], cwd=str(tmp_path), check=True)
    assert D.tracked_under(tmp_path) == frozenset({"a.v"})
