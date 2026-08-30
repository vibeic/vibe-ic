"""programs/tests/_hostpaths.py — portable replacements for host-hardwired paths.

WHY THIS EXISTS
===============
A large slice of the test suite used to reference the *original developer's*
personal filesystem layout literally, e.g.::

    _DATASET = Path("/home/<dev>/AI_IC_design/_extbench/RTLLM")
    real     = Path("/home/<dev>/vibe-ic/benchmark-data/ic/spm/...")

Those tests only ever ran on ONE machine. Everywhere else they silently
skipped (when guarded by ``skipif``) or errored (when not), so a CI runner or
a second developer got a green-looking suite that had actually exercised far
less than it claimed. Worse, the skip reasons never said what was missing or
how to supply it.

The references fall into exactly two classes, and this module gives each one
a first-class resolver:

CLASS (a) — IN-REPO data (``/home/<dev>/vibe-ic/...``)
    Checked-in artifacts. These live in THIS checkout, so they need no
    configuration — only a correct root. Use :func:`repo_path` /
    :func:`require_repo`, which derive the root from ``__file__`` instead of
    from a literal.

    THE EXAMPLE THIS PARAGRAPH USED TO GIVE WAS ``benchmark-data/``, AND IT IS
    NOT CLASS (a) ANY MORE. That tree left the repository at ``c5d7f2d00``;
    ``git ls-tree -r HEAD -- benchmark-data`` matches nothing. So every
    ``require_repo("benchmark-data", ...)`` in the suite resolved to a path that
    cannot exist on ANY host, and skipped — reading in every report as an
    ordinary "not in this checkout" probe that a checkout could satisfy. No
    checkout can. That is silently-absent coverage: the shape that lets a real
    regression land while the report stays green.

    ``benchmark-data`` is therefore RE-ROUTED here, in one place, onto the
    published corpus ``_published_corpus.corpus_root()`` resolves — the same
    answer ``test_tool_diagnostic_id_gate.py:338`` already uses. The in-repo
    root is still tried, so a checkout that carries the tree is read exactly as
    before, and nothing is weakened: where neither resolves the skip is the same
    skip, now naming which of the two states it is in.

CLASS (b) — EXTERNAL corpora (``/home/<dev>/AI_IC_design/...`` and friends)
    Large benchmark datasets (RTLLM, VerilogEval, CVDP, past run artifacts)
    that are deliberately NOT in the repo. They cannot be derived — the user
    must say where they are, via the ``VIBEIC_CORPUS_ROOT`` environment
    variable. Use :func:`require_corpus` (raising / skipping) or
    :func:`corpus_path` (non-raising, for module-level constants).

CONTRACT
========
* A test that CAN run must still really run — nothing here weakens an
  assertion; the corpus tests go from "pass on one laptop" to "pass anywhere
  the corpus is mounted, skip with an actionable reason anywhere else".
* Every skip reason names the thing that is missing and, for the external
  corpus, the exact environment variable that would supply it.
* This module contains NO absolute host path of any kind.

USAGE
=====
Inside a test function body — prefer the ``require_*`` forms, which produce
an explicit, self-documenting skip::

    def test_something():
        ds = require_corpus("_extbench", "RTLLM")
        art = require_repo("benchmark-data", "ic", "spm", "reports")

At MODULE level — use the non-raising :func:`corpus_path` together with the
test module's existing ``skipif``, so collection never triggers a skip from
inside an import::

    _DATASET = corpus_path("_extbench", "RTLLM")
    pytestmark = pytest.mark.skipif(
        not _DATASET.is_dir(),
        reason="external benchmark corpus not available: set $VIBEIC_CORPUS_ROOT",
    )
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# A path that is guaranteed not to exist, used by the non-raising resolvers so
# that a module-level constant is always a real Path object (never None) and an
# existence check on it is unambiguously False.
_MISSING = Path("/nonexistent-corpus")
_MISSING_REPO = Path("/nonexistent-repo")

_CORPUS_ENV = "VIBEIC_CORPUS_ROOT"


def _find_repo_root() -> Path | None:
    """Walk up from this file until a directory containing ``vibe-ic-marketplace``.

    Returns ``None`` in a tree where the marketplace directory has no ancestor —
    notably the flattened *installed plugin cache*, which has no monorepo
    ancestors at all (see ``_plugin_tree.py`` for the two-tree posture).
    """
    for parent in Path(__file__).resolve().parents:
        if (parent / "vibe-ic-marketplace").is_dir():
            return parent
    return None


#: Root of the source monorepo (the directory that CONTAINS
#: ``vibe-ic-marketplace``), or ``None`` when running from the installed
#: plugin cache where no such ancestor exists.
REPO_ROOT: Path | None = _find_repo_root()


def _published_root() -> "Path | None":
    """`_published_corpus.corpus_root()`, imported lazily and never fatally."""
    mod = _published_corpus()
    if mod is None:
        return None
    try:
        return mod.corpus_root()
    except Exception:
        return None


def _published_corpus():
    """The helper module, or None. Lazy because it measures the corpus at
    import (it shells out to git); non-fatal because ~147 test modules import
    THIS one and a resolver that raises would take all of them down over a
    question that has a perfectly good answer of "no"."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import _published_corpus as _pc
        return _pc
    except Exception:
        return None


def _published_reroute(parts) -> "Path | None":
    """Delegate to `_published_corpus.reroute_moved_path` — written once."""
    mod = _published_corpus()
    if mod is None:
        return None
    try:
        return mod.reroute_moved_path(*parts)
    except Exception:
        return None


_PUBLISHED_PREFIX = "benchmark-data"


def repo_path(*parts: str) -> Path:
    """``REPO_ROOT`` joined with *parts*; skip when the repo root is unresolvable.

    Use for in-repo, checked-in data. Skips (rather than failing) on the
    installed-cache tree, where the monorepo simply is not present.
    """
    rerouted = _published_reroute(parts)
    if rerouted is not None:
        return rerouted
    if REPO_ROOT is None:
        pytest.skip(
            "source monorepo not available: no 'vibe-ic-marketplace' ancestor "
            "of the test tree (running from the installed plugin cache?)"
        )
    return REPO_ROOT.joinpath(*parts)


def require_repo(*parts: str) -> Path:
    """:func:`repo_path` that additionally skips when the path does not exist."""
    p = repo_path(*parts)
    if not p.exists():
        rel = "/".join(str(x) for x in parts)
        # TWO STATES, TWO SENTENCES. "not in this checkout" is only true of the
        # in-repo class; for the moved prefix the honest reading is whether a
        # corpus was named at all, which is what the operator can act on.
        if rel == _PUBLISHED_PREFIX or rel.startswith(_PUBLISHED_PREFIX + "/"):
            root = _published_root()
            pytest.skip(
                f"{rel}: the published corpus at {root} does not carry it"
                if root is not None else
                f"{rel}: this tree no longer carries benchmark-data (it moved "
                f"to vibeic/benchmark-data) and no VIBE_IC_BENCHMARK_DATA "
                f"pointer names a clone — this is 'could not look'")
        pytest.skip(f"in-repo artifact not present in this checkout: {rel}")
    return p


def repo_path_opt(*parts: str) -> Path:
    """Non-raising :func:`repo_path` — for MODULE-level constants.

    The in-repo counterpart of :func:`corpus_path`: returns a
    definitely-missing path instead of skipping when ``REPO_ROOT`` is
    unresolvable, so it is safe to evaluate at import time. Pair it with the
    module's own ``pytest.mark.skipif``.
    """
    rerouted = _published_reroute(parts)
    if rerouted is not None:
        return rerouted
    if REPO_ROOT is None:
        return _MISSING_REPO.joinpath(*parts)
    return REPO_ROOT.joinpath(*parts)


def corpus_root() -> Path | None:
    """The external-corpus root from ``$VIBEIC_CORPUS_ROOT``, or ``None``.

    ``None`` means either the variable is unset/empty or it does not point at
    an existing directory.
    """
    raw = os.environ.get(_CORPUS_ENV)
    if not raw:
        return None
    root = Path(raw)
    return root if root.is_dir() else None


def corpus_path(*parts: str) -> Path:
    """Non-raising external-corpus path — for MODULE-level constants.

    Returns ``corpus_root()/parts`` when the corpus is configured, and a
    definitely-missing path otherwise. It never skips, so it is safe to
    evaluate at import time; pair it with the module's own
    ``pytest.mark.skipif(not <const>.exists(), reason=...)``. Prefer
    :func:`require_corpus` inside test bodies, where an explicit skip reason
    is more useful than a marker.
    """
    root = corpus_root()
    if root is None:
        return _MISSING.joinpath(*parts)
    return root.joinpath(*parts)


def require_corpus(*parts: str) -> Path:
    """``corpus_root()/parts``; skip with an actionable reason if unavailable.

    Skips both when ``$VIBEIC_CORPUS_ROOT`` is unset and when it is set but the
    requested path underneath it does not exist — in either case the operator
    needs to point the variable at a tree that contains *parts*.
    """
    rel = "/".join(parts)
    reason = (
        f"external benchmark corpus not available: set ${_CORPUS_ENV} "
        f"to a directory containing {rel}"
    )
    root = corpus_root()
    if root is None:
        pytest.skip(reason)
    p = root.joinpath(*parts)
    if not p.exists():
        pytest.skip(reason)
    return p


def skip_if_missing(p: Path, reason: str = "") -> Path:
    """Return *p*, or skip when it does not exist.

    For paths that are neither in-repo nor corpus-rooted (e.g. one already
    resolved by another helper, or a tool output produced earlier in the test).
    """
    p = Path(p)
    if not p.exists():
        pytest.skip(reason or f"required path not present: {p}")
    return p
