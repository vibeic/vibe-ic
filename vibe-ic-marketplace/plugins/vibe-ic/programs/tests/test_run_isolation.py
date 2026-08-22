"""test_run_isolation.py — the shared isolation harness must actually isolate.

Every test here builds a REAL writer and lets it run. Nothing asserts that the
harness has a function with the right name: the hazard this module exists for
is a copy that looks complete and is not, so every check has to survive the
copy being made and then written into.

THE ONE THAT MATTERS is
:func:`test_a_hardlink_mirror_is_refused_before_anything_writes`. It rebuilds
the ledger's actual bug — ``cp -al``, then an ordinary open-for-write — and
asserts BOTH halves: that the harness refuses the mirror, and that the mirror
really would have truncated the published file. Without the second half the
first is a test of a rule nobody has shown to matter.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _run_isolation as I  # noqa: E402
#: WHY THESE TWO SKIP, and why `needs_corpus` was the WRONG instrument for them.
#:
#: `_run_isolation` hardcodes CORPUS = "benchmark-data" and runs
#: `git status --porcelain benchmark-data/` in THIS repository. Marking these with
#: `@needs_corpus` made them RUN whenever a corpus clone was pointed at — and then
#: fail anyway, because the program never consults that clone. Measured: with
#: VIBE_IC_BENCHMARK_DATA set, 2 failed with EmptySubject. A marker that turns a
#: test green here by not running it, while leaving it broken wherever it does run,
#: is the switched-off-test shape.
#:
#: The property itself is NOT lost. `suite_write_guard` runs at the END of every
#: pytest session and asserts the same thing over the WHOLE tree — "this session
#: wrote nothing `git status --porcelain` would show". These two were the
#: corpus-SPECIFIC version of it, and the corpus is now vibeic/benchmark-data.
#: They belong there, against the cells that repository actually publishes.
_SUBJECT_MOVED = (
    "the published corpus moved to vibeic/benchmark-data; _run_isolation still "
    "hardcodes a local benchmark-data/ path, so this cannot measure anything here. "
    "suite_write_guard covers the tree-wide property. Tracked in vibe-ic#1703.")

#: Bound for the two CLI launches at the bottom of this file. NOT a round number
#: picked by feel: `ci_harness_timeout_ceiling_check` (BLOCKING) resolves the
#: pytest harness bound from `tools/gatekeeper-land.sh` — `--timeout=180`,
#: `--timeout-method=thread` — and permits any ONE blocking call at most
#: `180 // 3` = 60 s. The landed value was 120, which is ABOVE that and so could
#: never fire: pytest reaches 180 s first and the thread method takes the whole
#: SESSION down instead of the test, so `--maxfail` stops counting and every
#: other file in the subset loses its verdict.
#:
#: The full 60 and not less, because each of the two tests below makes exactly
#: ONE bounded call — this is the single-call shape the ceiling is stated for.
#: MEASURED here, three runs each: the PASS arm walks this whole checkout's
#: `git status --porcelain` and costs 0.31 s cold / 0.08 s warm; the refusal arm
#: costs 0.04 s. 60 s is ~190x the cold worst case.
_CLI_TIMEOUT_S = 60


def _run(tmp: Path, files=(("a.txt", "one"), ("d/b.txt", "two"))) -> Path:
    """A published run, small enough to reason about and >1 file."""
    root = tmp / "published"
    for rel, body in files:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    return root


def _writer(tmp: Path, body: str) -> Path:
    p = tmp / "writer.py"
    p.write_text(textwrap.dedent(body))
    return p


# ══════════════════════════════════════════════════════════════════════
# The copy
# ══════════════════════════════════════════════════════════════════════
def test_a_hardlink_mirror_is_refused_before_anything_writes(tmp_path):
    """The ledger's bug, rebuilt: `cp -al` then an ordinary write.

    Both halves are asserted. A test that only showed the refusal would not
    have shown that the thing refused is dangerous, and this repository has
    the measurement that it is: eight published JSON artefacts were left
    modified in the worktree by exactly this shape.
    """
    src = _run(tmp_path)
    original = (src / "a.txt").read_text()

    # --- half 1: the mirror really does truncate the published file ---------
    mirror = tmp_path / "mirror"
    subprocess.run(["cp", "-al", str(src), str(mirror)], check=True)
    (mirror / "a.txt").write_text("clobbered by the gate's own report")
    assert (src / "a.txt").read_text() != original, (
        "a `cp -al` mirror did NOT share inodes on this filesystem, so this "
        "control cannot demonstrate the hazard and the refusal below would "
        "prove nothing")

    # --- half 2: the harness refuses that copy, by inode not by path --------
    src2 = _run(tmp_path / "second")
    mirror2 = tmp_path / "mirror2"
    subprocess.run(["cp", "-al", str(src2), str(mirror2)], check=True)
    before, after = I.snapshot(src2), I.snapshot(mirror2)
    shared = I.shared_inodes(before, after)
    assert set(shared) == set(before), (
        f"the inode check saw {len(shared)} shared of {len(before)}; a "
        f"hardlink mirror shares all of them")

    # and a path-completeness assertion, the thing a careful author writes
    # instead, would have passed the mirror happily:
    assert set(before) == set(after), (
        "the mirror is path-complete — which is exactly why 'did we copy "
        "every file' was not enough and the inode comparison is")


def test_copy_run_itself_refuses_when_the_copy_shares_inodes(tmp_path,
                                                             monkeypatch):
    """The REFUSAL, driven through `copy_run`, not just through its predicate.

    THIS TEST EXISTS BECAUSE THE MUTANT ARM CAUGHT ITS ABSENCE. The first
    version of this file asserted `shared_inodes()` on a hand-built mirror and
    stopped there. Neutering `copy_run`'s `if shared:` to `if False:` left all
    19 tests GREEN — the guard was unreachable from the suite, because
    `shutil.copytree` never produces hardlinks, so nothing exercised the branch
    that does the refusing.

    The copy mechanism is swapped for a hardlinking one, which is not a
    contrivance: it is precisely what the ledger's replay used to do.
    """
    src = _run(tmp_path)

    def _hardlink_copytree(s, d, **kw):
        subprocess.run(["cp", "-al", str(s), str(d)], check=True)

    monkeypatch.setattr(I.shutil, "copytree", _hardlink_copytree)
    with pytest.raises(I.SubjectPerturbed) as e:
        I.copy_run(src, tmp_path / "dst")
    assert "shares" in str(e.value) and "inode" in str(e.value), str(e.value)
    assert "cp -al" in str(e.value), (
        "the refusal should name the defect it is refusing, so a reader who "
        "hits it knows what changed rather than only that something did")


def test_isolated_run_refuses_a_sharing_copy_before_yielding(tmp_path,
                                                             monkeypatch):
    """And the refusal reaches the context manager: no body runs on a mirror."""
    src = _run(tmp_path)
    monkeypatch.setattr(
        I.shutil, "copytree",
        lambda s, d, **kw: subprocess.run(["cp", "-al", str(s), str(d)],
                                          check=True))
    entered = []
    with pytest.raises(I.SubjectPerturbed):
        with I.isolated_run(src):
            entered.append(True)
    assert not entered, (
        "isolated_run yielded a copy that shares inodes with the published "
        "run; the body would have written through to the original")


def test_copy_run_produces_a_tree_that_shares_nothing(tmp_path):
    src = _run(tmp_path)
    dst = tmp_path / "copy"
    n = I.copy_run(src, dst)
    assert n == 2, f"copied {n} files, expected 2"
    assert not I.shared_inodes(I.snapshot(src), I.snapshot(dst))
    (dst / "a.txt").write_text("written into the copy")
    assert (src / "a.txt").read_text() == "one", (
        "writing into the copy changed the source")


def test_copy_run_refuses_an_empty_subject(tmp_path):
    """A zero denominator refuses rather than reporting a successful isolation."""
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(I.EmptySubject):
        I.copy_run(empty, tmp_path / "dst")
    with pytest.raises(I.EmptySubject):
        I.copy_run(tmp_path / "does_not_exist", tmp_path / "dst2")


# ══════════════════════════════════════════════════════════════════════
# The subject must not move
# ══════════════════════════════════════════════════════════════════════
def test_isolated_run_lets_a_real_writer_write_and_the_source_stands(tmp_path):
    src = _run(tmp_path)
    w = _writer(tmp_path, """
        import sys, pathlib
        r = pathlib.Path(sys.argv[1])
        (r / 'a.txt').write_text('rewritten')
        (r / 'new_report.json').write_text('{}')
    """)
    out = I.run_against_copy(src, [sys.executable, str(w), "{run}"])
    assert out.returncode == 0, out.stderr
    assert out.examined == 2, f"examined {out.examined}"
    assert "new_report.json" in out.wrote.added, out.wrote.describe()
    assert "a.txt" in out.wrote.changed, out.wrote.describe()
    # the whole point:
    assert (src / "a.txt").read_text() == "one"
    assert not (src / "new_report.json").exists()


def test_a_source_that_moves_during_the_run_is_named_not_swallowed(tmp_path):
    """CONTROL: the guard must fire when the subject really is perturbed.

    The writer is pointed at the SOURCE on purpose — this is the failure the
    harness exists to catch, staged deliberately so the detection is measured
    rather than assumed.
    """
    src = _run(tmp_path)
    with pytest.raises(I.SubjectPerturbed) as e:
        with I.isolated_run(src):
            (src / "a.txt").write_text("the instrument wrote into its subject")
    assert "a.txt" in str(e.value), str(e.value)
    assert "changed" in str(e.value), str(e.value)


def test_the_source_is_checked_even_when_the_program_raises(tmp_path):
    """A crash is when a half-written file is most likely to be left behind."""
    src = _run(tmp_path)
    with pytest.raises(I.SubjectPerturbed):
        with I.isolated_run(src):
            (src / "d" / "b.txt").write_text("half a write")
            raise RuntimeError("the program died here")


def test_isolated_run_refuses_an_empty_subject(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(I.EmptySubject):
        with I.isolated_run(empty):
            pass


def test_the_scratch_copy_is_gone_afterwards(tmp_path):
    src = _run(tmp_path)
    with I.isolated_run(src) as iso:
        seen = iso.copy
        assert seen.is_dir()
    assert not seen.exists(), f"{seen} survived the context"


# ══════════════════════════════════════════════════════════════════════
# Drift arithmetic — the denominator
# ══════════════════════════════════════════════════════════════════════
def test_drift_examines_the_union_and_says_so(tmp_path):
    src = _run(tmp_path)
    before = I.snapshot(src)
    (src / "c.txt").write_text("three")
    (src / "a.txt").unlink()
    after = I.snapshot(src)
    d = I.drift(before, after)
    assert d.added == ("c.txt",) and d.removed == ("a.txt",)
    assert d.examined == 3, (
        f"examined {d.examined}; the union of a 2-file and a 2-file snapshot "
        f"that differ by one add and one remove is 3")
    assert not d.clean and "of 3 file(s) examined" in d.describe()


def test_a_clean_drift_still_states_its_reach(tmp_path):
    """A PASS must say how much it looked at."""
    src = _run(tmp_path)
    d = I.drift(I.snapshot(src), I.snapshot(src))
    assert d.clean
    assert "2 file(s)" in d.describe(), d.describe()


def test_a_symlink_swapped_for_a_regular_file_is_drift(tmp_path):
    """`lstat`, not `stat` — following the link would hide the swap."""
    src = _run(tmp_path)
    (src / "link").symlink_to("a.txt")
    before = I.snapshot(src)
    (src / "link").unlink()
    (src / "link").write_text("one")           # same CONTENT as the target
    assert "link" in I.drift(before, I.snapshot(src)).changed


# ══════════════════════════════════════════════════════════════════════
# The tripwire
# ══════════════════════════════════════════════════════════════════════
def _repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    (r / I.CORPUS / "ic" / "cell").mkdir(parents=True)
    (r / I.CORPUS / "ic" / "cell" / "kept.txt").write_text("x\n")
    subprocess.run(["git", "init", "-q", str(r)], check=True)
    for k, v in (("user.email", "t@t"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(r), "config", k, v], check=True)
    subprocess.run(["git", "-C", str(r), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "base"], check=True)
    return r


def test_the_tripwire_passes_on_a_pristine_corpus_and_states_the_count(tmp_path):
    st = I.assert_corpus_pristine(_repo(tmp_path))
    assert st.clean and st.tracked == 1
    assert "1 tracked file(s)" in st.describe(), st.describe()


def test_the_tripwire_fires_on_a_modified_tracked_file(tmp_path):
    r = _repo(tmp_path)
    (r / I.CORPUS / "ic" / "cell" / "kept.txt").write_text("contaminated\n")
    with pytest.raises(I.CorpusContaminated) as e:
        I.assert_corpus_pristine(r, what="this test's sweep")
    assert "kept.txt" in str(e.value)
    assert "this test's sweep" in str(e.value)


def test_the_tripwire_fires_on_an_untracked_leftover(tmp_path):
    """The corpus baseline left 64 untracked files as well as 2336 modified."""
    r = _repo(tmp_path)
    (r / I.CORPUS / "ic" / "cell" / "leftover.json").write_text("{}\n")
    with pytest.raises(I.CorpusContaminated) as e:
        I.assert_corpus_pristine(r)
    assert "leftover.json" in str(e.value)


def test_the_tripwire_refuses_a_path_it_cannot_see(tmp_path):
    """A zero denominator must refuse, not pass.

    `git status --porcelain` over a typo'd or absent path is empty, and an
    empty porcelain is indistinguishable from a clean corpus. That is the
    shape this whole campaign keeps removing, so the tripwire counts what git
    tracks and refuses when the answer is none.
    """
    r = _repo(tmp_path)
    for absent in ("benchmark-dat", "no/such/dir"):
        with pytest.raises(I.EmptySubject) as e:
            I.assert_corpus_pristine(r, absent)
        assert "zero denominator" in str(e.value)


def test_the_tripwire_is_not_fooled_by_dirt_outside_the_corpus(tmp_path):
    """It must speak for the corpus and be silent about everything else."""
    r = _repo(tmp_path)
    (r / "unrelated.txt").write_text("a source edit, which is not corpus dirt\n")
    assert I.assert_corpus_pristine(r).clean


@pytest.mark.skip(reason=_SUBJECT_MOVED)
def test_the_tripwire_runs_against_this_repository(tmp_path):
    """Not only against a synthetic probe: the real corpus, right now.

    This is the assertion the three hand-written docstrings were each making
    for their own sweep. If a test in this suite ever leaves the published
    corpus modified, this fails for everyone rather than for whoever thought
    to look.
    """
    st = I.assert_corpus_pristine(what="the pytest session that just ran")
    assert st.tracked > 0
    assert st.clean, st.describe()


# ══════════════════════════════════════════════════════════════════════
# The CLI
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.skip(reason=_SUBJECT_MOVED)
def test_the_cli_reports_pass_with_its_denominator():
    out = subprocess.run(
        [sys.executable, str(Path(I.__file__))],
        capture_output=True, text=True, timeout=_CLI_TIMEOUT_S)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "[PASS]" in out.stdout and "tracked file(s)" in out.stdout, out.stdout


def test_the_cli_refuses_a_subpath_it_cannot_see():
    out = subprocess.run(
        [sys.executable, str(Path(I.__file__)), "no-such-corpus-dir"],
        capture_output=True, text=True, timeout=_CLI_TIMEOUT_S)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "zero denominator" in out.stdout, out.stdout
