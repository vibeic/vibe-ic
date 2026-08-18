"""Unit tests for the `_hostpaths` portable-path helper.

The helper is what lets the rest of the suite stop hard-coding one
developer's home directory, so its own behaviour has to be pinned: the repo
root must resolve inside this checkout, and the external-corpus resolvers must
skip (never error, never silently pass) when $VIBEIC_CORPUS_ROOT is absent.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import _hostpaths as HP

# `pytest.skip()` raises a BaseException subclass, so `pytest.raises(Exception)`
# would let it through and skip the asserting test instead of catching it.
_Skipped = pytest.skip.Exception


# --------------------------------------------------------------------------- #
# REPO_ROOT / repo_path
# --------------------------------------------------------------------------- #
def test_repo_root_resolves_under_this_checkout():
    """REPO_ROOT is the ancestor that CONTAINS vibe-ic-marketplace."""
    if HP.REPO_ROOT is None:
        pytest.skip("installed-cache tree: no monorepo ancestor to resolve")
    assert (HP.REPO_ROOT / "vibe-ic-marketplace").is_dir()
    # this test file must live underneath it
    assert str(Path(__file__).resolve()).startswith(str(HP.REPO_ROOT))


def test_repo_path_joins_parts():
    if HP.REPO_ROOT is None:
        pytest.skip("installed-cache tree: no monorepo ancestor to resolve")
    p = HP.repo_path("vibe-ic-marketplace", "plugins")
    assert p == HP.REPO_ROOT / "vibe-ic-marketplace" / "plugins"
    assert p.is_dir()


def test_require_repo_skips_on_missing():
    if HP.REPO_ROOT is None:
        pytest.skip("installed-cache tree: no monorepo ancestor to resolve")
    with pytest.raises(_Skipped) as exc:
        HP.require_repo("definitely-not-a-real-dir-9f3a")
    assert "definitely-not-a-real-dir-9f3a" in str(exc.value)


# --------------------------------------------------------------------------- #
# corpus_root / corpus_path / require_corpus
# --------------------------------------------------------------------------- #
def test_corpus_root_returns_dir_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBEIC_CORPUS_ROOT", str(tmp_path))
    assert HP.corpus_root() == tmp_path


def test_corpus_root_none_when_unset(monkeypatch):
    monkeypatch.delenv("VIBEIC_CORPUS_ROOT", raising=False)
    assert HP.corpus_root() is None


def test_corpus_root_none_when_not_a_dir(monkeypatch, tmp_path):
    f = tmp_path / "a-file"
    f.write_text("x")
    monkeypatch.setenv("VIBEIC_CORPUS_ROOT", str(f))
    assert HP.corpus_root() is None


def test_require_corpus_skips_when_env_unset(monkeypatch):
    monkeypatch.delenv("VIBEIC_CORPUS_ROOT", raising=False)
    with pytest.raises(_Skipped) as exc:
        HP.require_corpus("_extbench", "RTLLM")
    msg = str(exc.value)
    assert "VIBEIC_CORPUS_ROOT" in msg
    assert "_extbench/RTLLM" in msg


def test_require_corpus_returns_path_when_present(monkeypatch, tmp_path):
    (tmp_path / "_extbench" / "RTLLM").mkdir(parents=True)
    monkeypatch.setenv("VIBEIC_CORPUS_ROOT", str(tmp_path))
    assert HP.require_corpus("_extbench", "RTLLM") == tmp_path / "_extbench" / "RTLLM"


def test_require_corpus_skips_when_subpath_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBEIC_CORPUS_ROOT", str(tmp_path))
    with pytest.raises(_Skipped) as exc:
        HP.require_corpus("_extbench", "RTLLM")
    assert "VIBEIC_CORPUS_ROOT" in str(exc.value)


def test_corpus_path_is_non_raising_and_missing_when_unset(monkeypatch):
    """Module-level form: never skips at import, but is never accidentally real."""
    monkeypatch.delenv("VIBEIC_CORPUS_ROOT", raising=False)
    p = HP.corpus_path("_extbench", "RTLLM")
    assert isinstance(p, Path)
    assert not p.exists()


def test_corpus_path_resolves_under_root_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("VIBEIC_CORPUS_ROOT", str(tmp_path))
    assert HP.corpus_path("a", "b") == tmp_path / "a" / "b"


# --------------------------------------------------------------------------- #
# skip_if_missing
# --------------------------------------------------------------------------- #
def test_skip_if_missing_passes_through_existing(tmp_path):
    assert HP.skip_if_missing(tmp_path) == tmp_path


def test_skip_if_missing_skips_with_reason(tmp_path):
    with pytest.raises(_Skipped) as exc:
        HP.skip_if_missing(tmp_path / "nope", reason="my custom reason")
    assert "my custom reason" in str(exc.value)


# --------------------------------------------------------------------------- #
# hygiene: the helper itself must carry no personal absolute path
# --------------------------------------------------------------------------- #
def test_helper_module_has_no_personal_home_path():
    src = Path(HP.__file__).read_text(encoding="utf-8")
    import re
    assert not re.search(r"/home/[a-z][a-z0-9_-]*/", src), \
        "_hostpaths.py must not contain any personal absolute path"
