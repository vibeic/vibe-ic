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


# --------------------------------------------------------------------------- #
# the moved prefix: `benchmark-data/` is not CLASS (a) any more
# --------------------------------------------------------------------------- #
#
# `require_repo("benchmark-data", ...)` resolved against THIS repository, and
# that tree left it at `c5d7f2d00` — `git ls-tree -r HEAD -- benchmark-data`
# matches nothing. So every such call skipped on every host, over a reason no
# provisioning could satisfy, while reading as an ordinary "not in this
# checkout" probe. Both directions are pinned here: with no corpus the skip is
# the same skip, and with one the data is handed over.


def _fake_corpus(root: Path) -> Path:
    (root / "ic" / "demo" / "v1.0.0_sky130A").mkdir(parents=True)
    (root / "PUBLISHING.md").write_text("x")
    (root / "protocol_parity" / "ucie" / "phase1" / "input_doc").mkdir(parents=True)
    return root


def test_require_repo_on_the_moved_prefix_skips_when_no_corpus(monkeypatch):
    """NEGATIVE half. Without this, the case below could pass because the
    resolver hands back a path for everything."""
    monkeypatch.delenv("VIBE_IC_BENCHMARK_DATA", raising=False)
    with pytest.raises(pytest.skip.Exception) as exc:
        HP.require_repo("benchmark-data", "evaluation", "phase1_parity")
    msg = str(exc.value)
    assert "benchmark-data" in msg
    assert "could not look" in msg, (
        f"the skip must say which of the two states it is in, not just that "
        f"something is absent: {msg}")


def _resolved(*parts):
    """`require_repo`, with its SKIP converted into a failure.

    THIS WRAPPER IS THE POINT OF THE CASE BELOW. Written the obvious way — a
    bare `assert HP.require_repo(...) == ...` — removing the reroute made this
    guard SKIP, not fail: `require_repo` skips when the path is absent, and
    pytest reported `17 passed, 1 skipped` for a resolver that had stopped
    resolving. A control that answers "inconclusive" when its subject is broken
    is the same silently-absent coverage this whole change is about, one level
    up. MEASURED: with the wrapper, the same deletion gives `1 failed`.
    """
    try:
        return HP.require_repo(*parts)
    except pytest.skip.Exception as exc:      # noqa: PT012 - that IS the finding
        pytest.fail(
            f"require_repo({', '.join(map(repr, parts))}) SKIPPED with a corpus "
            f"bound and carrying the path — the moved prefix is not being "
            f"resolved: {exc}")


def test_PAIRED_GUARD_require_repo_reaches_a_bound_corpus(tmp_path, monkeypatch):
    """POSITIVE half, including the RENAMED prefix a plain root swap misses."""
    corpus = _fake_corpus(tmp_path / "corpus")
    monkeypatch.setenv("VIBE_IC_BENCHMARK_DATA", str(corpus))

    assert _resolved("benchmark-data", "evaluation", "phase1_parity") \
        == corpus / "protocol_parity"
    assert _resolved("benchmark-data", "ic", "demo") == corpus / "ic" / "demo"
    assert HP.repo_path_opt("benchmark-data", "ic") == corpus / "ic"


def test_a_bound_corpus_does_not_invent_a_path_it_does_not_carry(
        tmp_path, monkeypatch):
    """The reroute must never turn an absence into a pass.

    Only an EXISTING path is returned, so a request the corpus does not carry
    still skips — and it skips with the sentence for THAT state (the corpus was
    read and does not have it), not with 'I could not look'.
    """
    corpus = _fake_corpus(tmp_path / "corpus")
    monkeypatch.setenv("VIBE_IC_BENCHMARK_DATA", str(corpus))
    with pytest.raises(pytest.skip.Exception) as exc:
        HP.require_repo("benchmark-data", "ic", "no_such_design")
    assert "does not carry it" in str(exc.value), str(exc.value)


def test_a_NON_moved_prefix_is_untouched_by_the_reroute(tmp_path, monkeypatch):
    """The blast radius is exactly one prefix.

    `_hostpaths` resolves ~147 modules' paths; a reroute that leaked into any
    other prefix would silently re-point the whole suite.
    """
    corpus = _fake_corpus(tmp_path / "corpus")
    monkeypatch.setenv("VIBE_IC_BENCHMARK_DATA", str(corpus))
    assert HP.repo_path("tools", "ci") == HP.REPO_ROOT / "tools" / "ci"
    # A prefix that merely STARTS with the same letters is not the moved one.
    assert HP.repo_path_opt("benchmark-data-notes") \
        == HP.REPO_ROOT / "benchmark-data-notes"
