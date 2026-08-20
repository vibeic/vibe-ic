#!/usr/bin/env python3
"""The guarantees `_published_corpus` rests on — written, rather than claimed.

WHY THIS FILE EXISTS
====================
`_published_corpus.py`'s first docstring said a test named
`test_the_skip_is_not_reachable_when_the_corpus_is_present` pinned its central
property. No such test existed. The sentence WAS the guarantee.

An adversarial review grepped for the name, found it only inside that docstring, and
then demonstrated exactly the hole it was covering:

    VIBE_IC_BENCHMARK_DATA=<empty dir> pytest ...  ->  29 passed, 2 skipped

A green run with every corpus check switched off, reached through a mistyped path, a
failed clone, or a CI fetch step that silently did nothing.

A skip mechanism is a way to make tests not run. The one thing it MUST NOT do is
become reachable when there is data — that turns a whole suite off while reporting
success. That property is what this file pins, in both directions.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import _published_corpus as C  # noqa: E402


def _cell(root: Path, design: str = "d", ver: str = "v1.0.0_pdk") -> Path:
    """The minimum thing PUBLISHING.md calls a published cell."""
    c = root / "ic" / design / ver
    c.mkdir(parents=True, exist_ok=True)
    (c / "RESULT.md").write_text("PASS\n", encoding="utf-8")
    return c


def _in_subprocess(env_value, body: str) -> subprocess.CompletedProcess:
    """Import the module fresh in a child, because `needs_corpus` is evaluated at
    import time and a reload in-process would not reproduce what pytest does."""
    prog = (
        "import sys; sys.path.insert(0, %r)\n" % str(_HERE)
        + "import _published_corpus as C\n"
        + body
    )
    import os
    env = dict(os.environ)
    if env_value is None:
        env.pop(C.CORPUS_ENV, None)
    else:
        env[C.CORPUS_ENV] = str(env_value)
    return subprocess.run([sys.executable, "-c", prog], capture_output=True,
                          text=True, timeout=60, env=env)


# ══════════════════════════════════════════════════════════════════════
# THE property. Both directions.
# ══════════════════════════════════════════════════════════════════════

def test_the_skip_is_not_reachable_when_the_corpus_is_present(tmp_path):
    """The one that was claimed and never written. With cells present, no skip."""
    _cell(tmp_path)
    r = _in_subprocess(tmp_path, "print('SKIP' if C.corpus_root() is None else 'RUN')")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "RUN", (
        "the corpus is present and the marker would still skip — that is a suite "
        f"switched off while reporting success. stdout={r.stdout!r} stderr={r.stderr[-400:]!r}")


def test_the_skip_IS_reachable_when_nothing_was_ever_offered(tmp_path, monkeypatch):
    """The paired half: with no pointer and no cells, skipping is the honest answer."""
    monkeypatch.delenv(C.CORPUS_ENV, raising=False)
    monkeypatch.setattr(C, "_REPO", tmp_path)          # a repo with no benchmark-data
    assert C.corpus_root() is None


# ══════════════════════════════════════════════════════════════════════
# The exploit that was demonstrated. It must now be impossible.
# ══════════════════════════════════════════════════════════════════════

def test_a_pointer_at_an_empty_directory_REFUSES_rather_than_skipping(tmp_path):
    """`I was told where it is and it is not there` is not `there is none`.

    This is the measured exploit: an empty dir used to yield a fully green run.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(C.CorpusPointerBroken) as e:
        import os
        os.environ[C.CORPUS_ENV] = str(empty)
        try:
            C.corpus_root()
        finally:
            os.environ.pop(C.CORPUS_ENV, None)
    assert "no published cell" in str(e.value)
    assert C.CORPUS_ENV in str(e.value)


def test_a_pointer_at_a_path_that_does_not_exist_REFUSES(tmp_path):
    import os
    os.environ[C.CORPUS_ENV] = str(tmp_path / "nope")
    try:
        with pytest.raises(C.CorpusPointerBroken) as e:
            C.corpus_root()
    finally:
        os.environ.pop(C.CORPUS_ENV, None)
    assert "does not exist" in str(e.value)


def test_the_refusal_is_visible_to_a_whole_pytest_run(tmp_path):
    """It must not be swallowed into a skip by the marker's own evaluation.

    Asserted through a real interpreter, because the failure mode being guarded is
    precisely 'the suite reported success'.
    """
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _in_subprocess(empty, "C.corpus_root()")
    assert r.returncode != 0, "a broken pointer exited 0 — it was swallowed"
    assert "CorpusPointerBroken" in r.stderr


# ══════════════════════════════════════════════════════════════════════
# What counts as a cell — the directory alone must not
# ══════════════════════════════════════════════════════════════════════

def test_a_benchmark_data_directory_with_only_inputs_is_not_a_corpus(tmp_path):
    """vibe-ic still HAS benchmark-data — 542 design-input files. Its presence must
    not read as 'the results are here', or every check would run against nothing."""
    (tmp_path / "benchmark-data" / "ic" / "d" / "input").mkdir(parents=True)
    (tmp_path / "benchmark-data" / "ic" / "d" / "input" / "spec.md").write_text("x")
    import os
    os.environ.pop(C.CORPUS_ENV, None)
    saved = C._REPO
    try:
        C._REPO = tmp_path
        assert C.corpus_root() is None, "an input-only tree was read as a corpus"
    finally:
        C._REPO = saved


def test_cell_dirs_lists_exactly_the_cells(tmp_path):
    _cell(tmp_path, "alpha", "v1.0.0_sky130A")
    _cell(tmp_path, "alpha", "v2.0.0_gf180mcuD")
    _cell(tmp_path, "beta", "v1.5.0_ihp-sg13g2")
    (tmp_path / "ic" / "alpha" / "clean_run_v1427").mkdir()   # not a cell
    (tmp_path / "ic" / "beta" / "input").mkdir()              # not a cell
    import os
    os.environ[C.CORPUS_ENV] = str(tmp_path)
    try:
        names = sorted(p.name for p in C.cell_dirs())
    finally:
        os.environ.pop(C.CORPUS_ENV, None)
    assert names == ["v1.0.0_sky130A", "v1.5.0_ihp-sg13g2", "v2.0.0_gf180mcuD"], names


def test_one_reason_string_and_it_names_what_is_missing():
    """Every skip in the suite must say the same thing, and say it is an inability
    to look rather than a finding."""
    assert C.CORPUS_ENV in C.SKIP_REASON
    assert "could not look" in C.SKIP_REASON
    assert "benchmark-data" in C.SKIP_REASON


# ══════════════════════════════════════════════════════════════════════
# FOUR STATES, FOUR VERDICTS. Collapsing any two of them is the defect.
#
# `unset` and `publishes_nothing` are both SKIPs and they are NOT the same skip.
# `broken` is neither and never becomes either. Before 2026-08-20 there were
# THREE states in the code and TWO verdicts: a corpus that is present, readable
# and publishes zero cells raised the same `CorpusPointerBroken` as a mistyped
# path, at MODULE IMPORT, so a whole test file died as a collection ERROR —
# including the tests in it that never touch the corpus.
#
# That state is not hypothetical. `vibeic/benchmark-data @ bcf2f94`
# ("withdraw all four published cells", 2026-08-20) is exactly it, and the
# refusal's printed remedy — "point it at a clone of vibeic/benchmark-data" —
# was already satisfied by the reader who hit it.
# ══════════════════════════════════════════════════════════════════════

def _corpus_checkout(root: Path) -> Path:
    """A real clone-shaped corpus: a git checkout that TRACKS an `ic/` tree.

    Tracked, not merely present. A mistyped path, a failed clone, an archive
    export and a bare `mkdir` all fail this, which is what keeps the empty-corpus
    state from becoming a way to launder a broken pointer.
    """
    import os
    (root / "ic" / "d").mkdir(parents=True, exist_ok=True)
    (root / "ic" / "d" / "input").mkdir(exist_ok=True)
    (root / "ic" / "d" / "input" / "spec.md").write_text("design input\n")
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull, GIT_AUTHOR_NAME="t",
               GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    for args in (("init", "-q", "-b", "main"), ("add", "-A"),
                 ("commit", "-qm", "corpus")):
        subprocess.run(("git", "-C", str(root)) + args, env=env, check=True,
                       capture_output=True, timeout=60)
    return root


def _state(env_value):
    """`corpus_state()` from a FRESH import, the way pytest reaches it."""
    r = _in_subprocess(env_value, "print(C.corpus_state()[0])")
    return r


def test_the_four_states_are_four_distinct_answers(tmp_path):
    unset_dir = tmp_path / "nothing"
    unset_dir.mkdir()
    broken = tmp_path / "does-not-exist"
    empty = _corpus_checkout(tmp_path / "empty-corpus")
    full = _corpus_checkout(tmp_path / "full-corpus")
    _cell(full)

    seen = {}
    for label, value in (("unset", None), ("broken", broken),
                         ("publishes_nothing", empty), ("present", full)):
        r = _state(value)
        assert r.returncode == 0, (
            f"{label}: the module would not import\n{r.stderr}")
        seen[label] = r.stdout.strip()
    assert seen == {"unset": C.UNSET, "broken": C.BROKEN,
                    "publishes_nothing": C.PUBLISHES_NOTHING,
                    "present": C.PRESENT}, seen
    assert len(set(seen.values())) == 4, f"two states collapsed: {seen}"


def test_bug_a_corpus_that_publishes_nothing_does_not_kill_COLLECTION(tmp_path):
    """The live 2026-08-20 state must leave the suite collectable.

    Asserted through a real pytest run, because the failure being guarded is a
    COLLECTION error — an in-process check would not reproduce it.
    """
    empty = _corpus_checkout(tmp_path / "empty-corpus")
    subject = tmp_path / "test_uses_the_corpus.py"
    subject.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(_HERE)!r})\n"
        "from _published_corpus import needs_corpus\n"
        "\n"
        "@needs_corpus\n"
        "def test_about_a_published_cell():\n"
        "    assert False, 'must never run without a cell'\n"
        "\n"
        "def test_that_does_not_touch_the_corpus():\n"
        "    assert True\n",
        encoding="utf-8")
    import os
    env = dict(os.environ, **{C.CORPUS_ENV: str(empty)})
    env.pop("PYTEST_ADDOPTS", None)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:randomly",
                        "-p", "no:cacheprovider", str(subject)],
                       capture_output=True, text=True, timeout=300,
                       cwd=str(tmp_path), env=env)
    assert "error" not in r.stdout.lower(), (
        "the file did not collect\n" + r.stdout + r.stderr)
    assert "1 passed" in r.stdout and "1 skipped" in r.stdout, (
        "a corpus that publishes nothing did not leave the file collectable\n"
        f"{r.stdout}\n{r.stderr}")


def test_bug_the_empty_corpus_skip_does_not_say_the_pointer_is_broken(tmp_path):
    """The remedy must not be one the reader has already carried out.

    "Point VIBE_IC_BENCHMARK_DATA at a clone of vibeic/benchmark-data" told a
    reader who WAS pointed at a clean clone of vibeic/benchmark-data to do the
    thing they had done. A refusal whose remedy is already in force is a dead end.
    """
    empty = _corpus_checkout(tmp_path / "empty-corpus")
    r = _in_subprocess(empty, "print(C.corpus_state()[2])")
    assert r.returncode == 0, r.stderr
    reason = r.stdout
    assert "publishes 0 cells" in reason, reason
    assert "IS a readable checkout" in reason, reason
    assert "nothing to fix" in reason, reason
    assert "clone of vibeic/benchmark-data" not in reason, (
        "the empty-corpus skip still prints the broken-pointer remedy: " + reason)


def test_bug_the_two_skips_carry_DIFFERENT_reasons(tmp_path):
    """`I could not look` and `I looked and it was empty` are not one verdict."""
    empty = _corpus_checkout(tmp_path / "empty-corpus")
    unset_reason = _in_subprocess(None, "print(C.corpus_state()[2])").stdout
    empty_reason = _in_subprocess(empty, "print(C.corpus_state()[2])").stdout
    assert unset_reason.strip() and empty_reason.strip()
    assert unset_reason != empty_reason, (
        "the two skips are indistinguishable in the junit record")
    assert "not in this checkout" in unset_reason
    assert "publishes 0 cells" in empty_reason


def test_guard_an_empty_DIRECTORY_still_REFUSES_and_is_not_an_empty_corpus(tmp_path):
    """The measured exploit stays closed. `mkdir` is not a corpus."""
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    r = _state(empty_dir)
    assert r.returncode == 0 and r.stdout.strip() == C.BROKEN, r.stdout
    r2 = _in_subprocess(empty_dir, "C.corpus_root()")
    assert r2.returncode != 0, "a bare mkdir was swallowed into a skip"
    assert "CorpusPointerBroken" in r2.stderr
    assert "not a git checkout" in r2.stderr


def test_guard_a_git_checkout_with_an_UNTRACKED_ic_tree_still_REFUSES(tmp_path):
    """Tracked, not merely present — otherwise a half-finished clone qualifies."""
    import os
    root = tmp_path / "half"
    (root / "ic" / "d").mkdir(parents=True)
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull,
               GIT_CONFIG_SYSTEM=os.devnull)
    subprocess.run(("git", "-C", str(root), "init", "-q", "-b", "main"),
                   env=env, check=True, capture_output=True, timeout=60)
    r = _state(root)
    assert r.returncode == 0 and r.stdout.strip() == C.BROKEN, r.stdout


def test_guard_a_readable_corpus_is_still_PRESENT_and_never_skips(tmp_path):
    """The paired guard: the fix must not be bought by skipping more often."""
    full = _corpus_checkout(tmp_path / "full-corpus")
    _cell(full)
    r = _state(full)
    assert r.returncode == 0 and r.stdout.strip() == C.PRESENT, r.stdout
    r2 = _in_subprocess(full, "print(C.corpus_root())")
    assert r2.returncode == 0 and r2.stdout.strip() == str(full), r2.stdout
