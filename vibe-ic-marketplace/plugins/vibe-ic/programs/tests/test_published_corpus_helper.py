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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


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
    return _pr.run([sys.executable, "-c", prog], capture_output=True,
                          text=True, env=env)


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
